"""Update notification tool."""

from pathlib import Path
from typing import Optional

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule


class UpdateNotificationTool(BaseDashboardTool):
    """Update an existing notification."""

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
            notifications_data = self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            # Find notification
            notification, index = self._find_notification(
                notifications_list, notification_id
            )
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

            if scheduled_at is not None:
                # Parse new scheduled_at
                scheduled_dt = self._parse_datetime(scheduled_at)
                if not scheduled_dt:
                    return f"Error: Could not parse scheduled_at '{scheduled_at}'"

                notification["scheduled_at"] = scheduled_dt.isoformat()
                notification["scheduled_at_text"] = (
                    scheduled_at if not scheduled_at.startswith("20") else None
                )

                # Update cron job
                cron_job_id = notification.get("cron_job_id")
                if cron_job_id:
                    # Remove old job and create new one
                    self.cron_service.remove_job(cron_job_id)

                    schedule = CronSchedule(
                        kind="at", at_ms=int(scheduled_dt.timestamp() * 1000)
                    )

                    new_job = self.cron_service.add_job(
                        name=f"notification_{notification_id}",
                        schedule=schedule,
                        message=notification["message"],
                        deliver=True,
                        channel=self._channel,
                        to=self._chat_id,
                        delete_after_run=True,
                    )

                    notification["cron_job_id"] = new_job.id

            # Save
            notifications_list[index] = notification
            notifications_data["notifications"] = notifications_list

            success, msg = self._validate_and_save_notifications(notifications_data)
            if not success:
                return msg

            return f"\u2705 Notification '{notification_id}' updated successfully"

        except Exception as e:
            return f"Error updating notification: {str(e)}"
