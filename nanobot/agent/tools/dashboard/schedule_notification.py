"""Schedule notification tool.

Ledger-only: writes a pending notification to storage.
GCal sync and delivery are handled by ReconciliationScheduler.

Guards:
- Dedup: rejects duplicate notifications for the same task + date + type.
- Per-task cap: max 3 pending notifications per task.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from loguru import logger

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


def _scheduled_date(scheduled_at: str, notification_id: str = "?") -> date | None:
    """Extract calendar date from a scheduled_at ISO string.

    Returns None on parse failure (logged as warning). Callers must
    treat None as a potential match (fail-closed) to avoid dedup bypass.
    """
    try:
        return datetime.fromisoformat(scheduled_at).date()
    except (ValueError, TypeError):
        logger.warning(
            "Could not parse scheduled_at for dedup: id={}, value='{}'",
            notification_id,
            scheduled_at,
        )
        return None


class ScheduleNotificationTool(BaseDashboardTool):
    """Schedule a notification for future delivery."""

    @property
    def name(self) -> str:
        return "schedule_notification"

    @property
    def description(self) -> str:
        return (
            "Schedule a notification to be delivered at a specific time. "
            "Use this to remind the user about tasks, deadlines, or blockers."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The notification message to deliver",
                },
                "scheduled_at": {
                    "type": "string",
                    "description": (
                        "When to deliver the notification in ISO datetime format: "
                        "YYYY-MM-DDTHH:MM:SS (e.g., '2026-03-05T15:00:00'). "
                        "Always convert natural language to ISO datetime."
                    ),
                },
                "type": {
                    "type": "string",
                    "enum": [
                        "reminder",
                        "deadline_alert",
                        "progress_check",
                        "blocker_followup",
                        "question_reminder",
                    ],
                    "default": "reminder",
                    "description": "Type of notification",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "default": "medium",
                    "description": "Priority level",
                },
                "related_task_id": {
                    "type": "string",
                    "description": "Optional task ID this notification is related to",
                },
                "related_question_id": {
                    "type": "string",
                    "description": "Optional question ID this notification is related to",
                },
                "context": {
                    "type": "string",
                    "default": "",
                    "description": "Additional context about why this notification was scheduled",
                },
                "created_by": {
                    "type": "string",
                    "enum": ["worker", "user", "main_agent"],
                    "default": "main_agent",
                    "description": "Who created this notification",
                },
            },
            "required": ["message", "scheduled_at"],
        }

    @with_dashboard_lock
    async def execute(
        self,
        message: str,
        scheduled_at: str,
        type: str = "reminder",
        priority: str = "medium",
        related_task_id: Optional[str] = None,
        related_question_id: Optional[str] = None,
        context: str = "",
        created_by: str = "main_agent",
    ) -> str:
        """Schedule a notification (ledger write only)."""
        try:
            scheduled_dt = self._parse_datetime(scheduled_at)
            if not scheduled_dt:
                return f"Error: Could not parse scheduled_at '{scheduled_at}'"

            notifications_data = await self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            # Guards: dedup + per-task cap
            if related_task_id:
                task_pending = [
                    n
                    for n in notifications_list
                    if n.get("status") == "pending" and n.get("related_task_id") == related_task_id
                ]

                # Per-task cap (max 3 pending notifications)
                max_per_task = 3
                if len(task_pending) >= max_per_task:
                    ids = ", ".join(n.get("id", "?") for n in task_pending)
                    return (
                        f"Rejected: {related_task_id} already has "
                        f"{len(task_pending)} pending notifications (max {max_per_task}): "
                        f"{ids}. Use update_notification or cancel_notification first."
                    )

                # Dedup: same task + same date + same type → reject
                # Fail-closed: unparsable scheduled_at treated as potential match
                target_date = scheduled_dt.date()
                duplicates = [
                    n
                    for n in task_pending
                    if n.get("type") == type
                    and (
                        (d := _scheduled_date(n.get("scheduled_at", ""), n.get("id", "?"))) is None
                        or d == target_date
                    )
                ]
                if duplicates:
                    ids = ", ".join(n.get("id", "?") for n in duplicates)
                    return (
                        f"Duplicate rejected: pending {type} already exists "
                        f"for {related_task_id} on {target_date}: {ids}. "
                        f"Use update_notification to modify."
                    )

            notification_id = self._generate_id("n")

            notification = {
                "id": notification_id,
                "message": message,
                "scheduled_at": scheduled_dt.isoformat(),
                "scheduled_at_text": (scheduled_at if not scheduled_at.startswith("20") else None),
                "type": type,
                "priority": priority,
                "related_task_id": related_task_id,
                "related_question_id": related_question_id,
                "status": "pending",
                "created_at": self._now(),
                "delivered_at": None,
                "cancelled_at": None,
                "context": context,
                "created_by": created_by,
                "gcal_event_id": None,
                "gcal_sync_hash": None,
            }

            notifications_list.append(notification)
            notifications_data["notifications"] = notifications_list

            success, msg = await self._validate_and_save_notifications(notifications_data)
            if not success:
                return msg

            return (
                f"\u2705 Notification scheduled: {notification_id}\n"
                f"Message: {message}\n"
                f"Scheduled at: {scheduled_dt.strftime('%Y-%m-%d %H:%M:%S')}"
            )

        except Exception as e:
            logger.exception("Unexpected error in schedule_notification")
            return f"Error scheduling notification ({type(e).__name__}): {e}"
