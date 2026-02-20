"""Schedule notification tool."""

from pathlib import Path
from typing import Optional

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule


class ScheduleNotificationTool(BaseDashboardTool):
    """Schedule a notification for future delivery via cron."""

    def __init__(self, workspace: Path, cron_service: CronService):
        super().__init__(workspace)
        self.cron_service = cron_service
        self._channel: str | None = None
        self._chat_id: str | None = None

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current channel and chat_id for notification delivery."""
        self._channel = channel
        self._chat_id = chat_id

    @property
    def name(self) -> str:
        return "schedule_notification"

    @property
    def description(self) -> str:
        return (
            "Schedule a notification to be delivered at a specific time. "
            "Creates both a notification entry and a cron job for delivery. "
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
                        "When to deliver the notification. "
                        "ISO datetime (e.g., '2026-02-09T15:00:00') or relative time "
                        "(e.g., 'in 2 hours', 'tomorrow 9am')"
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
        """Schedule a notification."""
        try:
            # Parse scheduled_at to datetime
            scheduled_dt = self._parse_datetime(scheduled_at)
            if not scheduled_dt:
                return f"Error: Could not parse scheduled_at '{scheduled_at}'"

            # Generate notification ID
            notification_id = self._generate_id("n")

            # Create cron job
            schedule = CronSchedule(
                kind="at", at_ms=int(scheduled_dt.timestamp() * 1000)
            )

            cron_job = self.cron_service.add_job(
                name=f"notification_{notification_id}",
                schedule=schedule,
                message=message,
                deliver=True,
                channel=self._channel,
                to=self._chat_id,
                delete_after_run=True,
            )

            # Create notification entry
            notifications_data = await self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            notification = {
                "id": notification_id,
                "message": message,
                "scheduled_at": scheduled_dt.isoformat(),
                "scheduled_at_text": (
                    scheduled_at if not scheduled_at.startswith("20") else None
                ),
                "type": type,
                "priority": priority,
                "related_task_id": related_task_id,
                "related_question_id": related_question_id,
                "status": "pending",
                "cron_job_id": cron_job.id,
                "created_at": self._now(),
                "delivered_at": None,
                "cancelled_at": None,
                "context": context,
                "created_by": created_by,
            }

            notifications_list.append(notification)
            notifications_data["notifications"] = notifications_list

            # Validate and save
            success, msg = await self._validate_and_save_notifications(notifications_data)
            if not success:
                # Rollback cron job
                self.cron_service.remove_job(cron_job.id)
                return msg

            return (
                f"\u2705 Notification scheduled: {notification_id}\n"
                f"Message: {message}\n"
                f"Scheduled at: {scheduled_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Cron job: {cron_job.id}"
            )

        except Exception as e:
            return f"Error scheduling notification: {str(e)}"
