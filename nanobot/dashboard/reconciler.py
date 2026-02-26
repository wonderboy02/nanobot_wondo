"""Ledger-Based Delivery: Reconciler + Scheduler.

Replaces per-notification cron jobs with a single reconciliation loop.
The Reconciler inspects the notification ledger, syncs GCal, and
identifies due notifications.  The Scheduler arms a timer and delivers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.dashboard.utils import parse_datetime

if TYPE_CHECKING:
    from nanobot.dashboard.storage import StorageBackend
    from nanobot.google.calendar import GoogleCalendarClient


# ============================================================================
# ReconcileResult
# ============================================================================


@dataclass
class ReconcileResult:
    """Outcome of a single reconcile() pass."""

    due: list[dict] = field(default_factory=list)
    next_due_at: datetime | None = None
    changed: bool = False


# ============================================================================
# NotificationReconciler (sync — called via asyncio.to_thread)
# ============================================================================


class NotificationReconciler:
    """Walk the notification ledger, sync GCal, identify due items.

    All public methods are **sync** (they call GCal sync I/O).
    Callers must wrap with ``asyncio.to_thread()`` if on an event loop.
    """

    def __init__(
        self,
        storage_backend: "StorageBackend",
        gcal_client: "GoogleCalendarClient | None" = None,
        gcal_timezone: str = "Asia/Seoul",
        gcal_duration_minutes: int = 30,
        default_chat_id: str | None = None,
        default_channel: str = "telegram",
    ):
        self.storage_backend = storage_backend
        self.gcal_client = gcal_client
        self.gcal_timezone = gcal_timezone
        self.gcal_duration_minutes = gcal_duration_minutes
        self.default_chat_id = default_chat_id
        self.default_channel = default_channel

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reconcile(self) -> ReconcileResult:
        """Single pass over the ledger.

        Returns which notifications are due **now**, the next due time,
        and whether the ledger was mutated (GCal sync).
        """
        result = ReconcileResult()
        now = datetime.now()

        data = self.storage_backend.load_notifications()
        notifications = data.get("notifications", [])

        for n in notifications:
            status = n.get("status", "pending")

            # Cancelled / delivered → ensure GCal removed
            if status in ("cancelled", "delivered"):
                if self._remove_gcal(n):
                    result.changed = True
                continue

            if status != "pending":
                continue

            # Parse scheduled_at
            try:
                scheduled = parse_datetime(n["scheduled_at"])
            except (KeyError, ValueError) as e:
                logger.warning(f"[Reconciler] Skip {n.get('id', '?')}: {e}")
                continue

            if scheduled <= now:
                # Due now
                result.due.append(n)
            else:
                # Future — ensure GCal event exists
                if self._ensure_gcal(n):
                    result.changed = True
                # Track nearest future due
                if result.next_due_at is None or scheduled < result.next_due_at:
                    result.next_due_at = scheduled

        # Persist any GCal ID changes
        if result.changed:
            ok, msg = self.storage_backend.save_notifications(data)
            if not ok:
                logger.error(f"[Reconciler] Save failed after GCal sync: {msg}")

        return result

    def mark_delivered(self, notif_id: str) -> bool:
        """Mark a notification as delivered. Returns True on success."""
        data = self.storage_backend.load_notifications()
        notifications = data.get("notifications", [])

        target = next((n for n in notifications if n.get("id") == notif_id), None)
        if target is None:
            logger.error(f"[Reconciler] mark_delivered: {notif_id} not found")
            return False

        if target.get("status") != "pending":
            logger.warning(
                f"[Reconciler] mark_delivered: {notif_id} status={target.get('status')}, skip"
            )
            return False

        target["status"] = "delivered"
        target["delivered_at"] = datetime.now().isoformat()

        # Remove GCal event on delivery
        self._remove_gcal(target)

        ok, msg = self.storage_backend.save_notifications(data)
        if not ok:
            logger.error(f"[Reconciler] mark_delivered save failed: {msg}")
            return False

        return True

    # ------------------------------------------------------------------
    # GCal helpers (idempotent)
    # ------------------------------------------------------------------

    def _ensure_gcal(self, n: dict) -> bool:
        """Create GCal event if missing. Returns True if ledger mutated."""
        if not self.gcal_client:
            return False
        if n.get("gcal_event_id"):
            return False  # already has one

        try:
            desc_parts = []
            if n.get("context"):
                desc_parts.append(n["context"])
            if n.get("related_task_id"):
                desc_parts.append(f"Related Task: {n['related_task_id']}")

            event_id = self.gcal_client.create_event(
                summary=n.get("message", ""),
                start_iso=n["scheduled_at"],
                timezone=self.gcal_timezone,
                duration_minutes=self.gcal_duration_minutes,
                description="\n".join(desc_parts) if desc_parts else None,
            )
            n["gcal_event_id"] = event_id
            logger.debug(f"[Reconciler] GCal created for {n.get('id', '?')}: {event_id}")
            return True
        except Exception as e:
            logger.warning(f"[Reconciler] GCal create failed for {n.get('id', '?')}: {e}")
            return False

    def _remove_gcal(self, n: dict) -> bool:
        """Delete GCal event if present. Returns True if ledger mutated."""
        if not self.gcal_client:
            return False
        gcal_event_id = n.get("gcal_event_id")
        if not gcal_event_id:
            return False

        try:
            self.gcal_client.delete_event(event_id=gcal_event_id)
            n["gcal_event_id"] = None
            return True
        except Exception as e:
            logger.warning(f"[Reconciler] GCal delete failed for {n.get('id', '?')}: {e}")
            return False


# ============================================================================
# ReconciliationScheduler (async)
# ============================================================================


class ReconciliationScheduler:
    """Async wrapper: reconcile → deliver due → arm timer for next.

    Triggered from four locations (all under _processing_lock):
    1. AgentLoop.run() — startup (overdue delivery)
    2. AgentLoop._process_message() — after each message
    3. _timer_fire() — timer expiry (next due)
    4. WorkerAgent.run_cycle() — end of Worker cycle (after Phase 1 + Phase 2)
    """

    def __init__(
        self,
        reconciler: NotificationReconciler,
        send_callback: Callable[..., Awaitable[Any]],
        processing_lock: asyncio.Lock | None = None,
    ):
        self.reconciler = reconciler
        self.send_callback = send_callback
        self._lock = processing_lock
        self._timer_task: asyncio.Task | None = None
        self._delivered: set[str] = set()  # In-flight tracking + mark-failure guard

    async def trigger(self) -> None:
        """Run reconcile, deliver due, arm timer for next."""
        result = await asyncio.to_thread(self.reconciler.reconcile)

        # Deliver due notifications
        for notif in result.due:
            await self._deliver(notif)

        # Arm timer for next due notification
        self._arm_timer(result.next_due_at)

    async def _deliver(self, notification: dict) -> None:
        """Deliver a notification: send first, then mark with retry.

        Flow:
          1. Precondition: chat_id required (no dedup pollution on skip)
          2. Dedup: skip if already in-flight (mark failed on prior attempt)
          3. Send message via send_callback
          4. On send failure → discard from dedup, return (stays pending for retry)
          5. Mark delivered with retry (3 attempts, backoff)
          6. On mark success → discard from dedup (clean state)
          7. On all retries fail → keep in dedup (prevent duplicate this session)
        """
        from nanobot.bus.events import OutboundMessage

        notif_id = notification.get("id", "?")

        # 1. Precondition — early return without touching dedup
        chat_id = self.reconciler.default_chat_id
        channel = self.reconciler.default_channel
        if not chat_id:
            logger.warning(f"[Scheduler] No chat_id for {notif_id}")
            return

        # 2. In-memory dedup (mark-failure guard)
        if notif_id in self._delivered:
            logger.debug(f"[Scheduler] Skipping {notif_id} (in-flight)")
            return
        self._delivered.add(notif_id)

        # 3. Send first
        message = notification.get("message", "")
        try:
            await self.send_callback(
                OutboundMessage(channel=channel, chat_id=chat_id, content=message)
            )
        except Exception as e:
            self._delivered.discard(notif_id)  # allow retry on next trigger
            logger.error(f"[Scheduler] Send failed for {notif_id}: {e}")
            return

        # 4. Mark delivered with retry
        for attempt in range(3):
            try:
                ok = await asyncio.to_thread(self.reconciler.mark_delivered, notif_id)
            except Exception:
                logger.exception(f"[Scheduler] mark_delivered exception for {notif_id}")
                ok = False
            if ok:
                self._delivered.discard(notif_id)
                logger.info(f"[Scheduler] Delivered {notif_id}")
                return
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))

        # All retries exhausted — dedup prevents duplicate this session
        logger.error(f"[Scheduler] {notif_id} sent but mark_delivered failed after 3 attempts")

    def _cancel_timer(self) -> None:
        """Cancel pending timer if running."""
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

    def _arm_timer(self, next_due_at: datetime | None) -> None:
        """Cancel existing timer and arm a new one if needed."""
        self._cancel_timer()

        if next_due_at is None:
            return

        delay = (next_due_at - datetime.now()).total_seconds()
        if delay <= 0:
            # Already due — trigger immediately in next loop iteration
            delay = 0.1

        self._timer_task = asyncio.ensure_future(self._timer_fire(delay))
        logger.debug(f"[Scheduler] Timer armed: {delay:.0f}s until next delivery")

    async def _timer_fire(self, delay: float) -> None:
        """Sleep then trigger reconciliation (acquires lock if available)."""
        try:
            await asyncio.sleep(delay)
            if self._lock:
                async with self._lock:
                    await self.trigger()
            else:
                await self.trigger()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("[Scheduler] Timer fire error")

    def stop(self) -> None:
        """Cancel pending timer."""
        self._cancel_timer()
