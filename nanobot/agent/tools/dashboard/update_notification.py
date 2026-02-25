"""Update notification tool."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from loguru import logger

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule

if TYPE_CHECKING:
    from nanobot.bus.events import OutboundMessage
    from nanobot.google.calendar import GoogleCalendarClient


class UpdateNotificationTool(BaseDashboardTool):
    """Update an existing notification."""

    def __init__(
        self,
        workspace: Path,
        cron_service: CronService,
        *,
        backend=None,
        gcal_client: "GoogleCalendarClient | None" = None,
        send_callback: Callable[["OutboundMessage"], Awaitable[None]] | None = None,
        notification_chat_id: str | None = None,
        gcal_timezone: str = "Asia/Seoul",
        gcal_duration_minutes: int = 30,
    ):
        super().__init__(workspace, backend)
        self.cron_service = cron_service
        self._gcal_client = gcal_client
        self._send_callback = send_callback
        self._notification_chat_id = notification_chat_id
        self._gcal_timezone = gcal_timezone
        self._gcal_duration_minutes = gcal_duration_minutes
        self._channel: str | None = None
        self._chat_id: str | None = None

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current channel and chat_id for notification delivery."""
        self._channel = channel
        self._chat_id = chat_id

    async def _send_telegram(self, content: str) -> None:
        """Send an instant notification via bus callback (uses current channel, falls back to telegram)."""
        if not self._send_callback:
            return
        chat_id = self._chat_id or self._notification_chat_id
        if not chat_id:
            return
        from nanobot.bus.events import OutboundMessage

        msg = OutboundMessage(channel=self._channel or "telegram", chat_id=chat_id, content=content)
        try:
            await self._send_callback(msg)
        except Exception as e:
            logger.warning(f"Failed to send Telegram notification: {e}")

    @property
    def name(self) -> str:
        return "update_notification"

    @property
    def description(self) -> str:
        return (
            "Update an existing notification's message, time, or priority. "
            "Also updates the associated cron job if scheduled_at is changed."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notification_id": {
                    "type": "string",
                    "description": "ID of the notification to update",
                },
                "message": {
                    "type": "string",
                    "description": "New message (optional)",
                },
                "scheduled_at": {
                    "type": "string",
                    "description": "New scheduled time (optional, ISO datetime or relative)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "New priority (optional)",
                },
            },
            "required": ["notification_id"],
        }

    @with_dashboard_lock
    async def execute(
        self,
        notification_id: str,
        message: Optional[str] = None,
        scheduled_at: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> str:
        """Update a notification."""
        try:
            # Load notifications
            notifications_data = await self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            # Find notification
            notification, index = self._find_notification(notifications_list, notification_id)
            if not notification:
                return f"Error: Notification '{notification_id}' not found"

            # Check if notification is already delivered/cancelled
            if notification.get("status") in ["delivered", "cancelled"]:
                return f"Error: Cannot update {notification['status']} notification"

            # Update fields
            if message is not None:
                notification["message"] = message

            if priority is not None:
                notification["priority"] = priority

            # Track whether cron needs updating
            old_cron_job_id = None
            new_cron_schedule = None

            if scheduled_at is not None:
                # Parse new scheduled_at
                scheduled_dt = self._parse_datetime(scheduled_at)
                if not scheduled_dt:
                    return f"Error: Could not parse scheduled_at '{scheduled_at}'"

                notification["scheduled_at"] = scheduled_dt.isoformat()
                notification["scheduled_at_text"] = (
                    scheduled_at if not scheduled_at.startswith("20") else None
                )

                old_cron_job_id = notification.get("cron_job_id")
                new_cron_schedule = CronSchedule(
                    kind="at", at_ms=int(scheduled_dt.timestamp() * 1000)
                )

            # DESIGN: Save storage FIRST, then update cron (storage-first commit).
            notifications_list[index] = notification
            notifications_data["notifications"] = notifications_list

            success, msg = await self._validate_and_save_notifications(notifications_data)
            if not success:
                return msg

            # Now update cron (safe: storage already committed)
            if new_cron_schedule:
                try:
                    new_job = self.cron_service.add_job(
                        name=f"notification_{notification_id}",
                        schedule=new_cron_schedule,
                        message=notification["message"],
                        deliver=True,
                        channel=self._channel,
                        to=self._chat_id,
                        delete_after_run=True,
                    )
                    if old_cron_job_id:
                        removed = self.cron_service.remove_job(old_cron_job_id)
                        if not removed:
                            logger.warning(
                                f"Old cron job {old_cron_job_id} not found during "
                                f"update of notification {notification_id} "
                                f"(may cause duplicate delivery)"
                            )
                    notification["cron_job_id"] = new_job.id
                    notifications_data["notifications"] = notifications_list
                    ok2, msg2 = await self._validate_and_save_notifications(notifications_data)
                    if not ok2:
                        logger.warning(
                            f"cron_job_id update save failed for {notification_id}: {msg2}"
                        )
                except Exception as cron_err:
                    logger.warning(
                        f"Cron update failed for notification {notification_id}: {cron_err}"
                    )
                    return (
                        f"⚠️ Notification '{notification_id}' data updated, "
                        f"but schedule registration failed: {cron_err}"
                    )

            # Google Calendar sync (best-effort, after cron update)
            if self._gcal_client:
                gcal_event_id = notification.get("gcal_event_id")
                try:
                    if gcal_event_id:
                        await asyncio.to_thread(
                            self._gcal_client.update_event,
                            event_id=gcal_event_id,
                            summary=message,
                            start_iso=(notification["scheduled_at"] if scheduled_at else None),
                            timezone=self._gcal_timezone,
                            duration_minutes=self._gcal_duration_minutes,
                        )
                    else:
                        new_gcal_id = await asyncio.to_thread(
                            self._gcal_client.create_event,
                            summary=notification["message"],
                            start_iso=notification["scheduled_at"],
                            timezone=self._gcal_timezone,
                            duration_minutes=self._gcal_duration_minutes,
                        )
                        notification["gcal_event_id"] = new_gcal_id
                        notifications_data["notifications"] = notifications_list
                        ok3, msg3 = await self._validate_and_save_notifications(notifications_data)
                        if not ok3:
                            logger.warning(
                                f"gcal_event_id save failed for {notification_id}: {msg3}"
                            )
                except Exception as e:
                    logger.warning(f"GCal sync failed (update): {e}")
                    await self._send_telegram(f"⚠️ Google Calendar 동기화 실패 (update): {e}")

            # Send instant Telegram notification
            await self._send_telegram(f"✅ 일정 수정: {notification_id}")

            return f"\u2705 Notification '{notification_id}' updated successfully"

        except Exception as e:
            return f"Error updating notification: {str(e)}"
