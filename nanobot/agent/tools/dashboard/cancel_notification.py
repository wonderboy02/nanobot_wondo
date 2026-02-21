"""Cancel notification tool."""

from pathlib import Path

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock
from nanobot.cron.service import CronService


class CancelNotificationTool(BaseDashboardTool):
    """Cancel a scheduled notification."""

    def __init__(self, workspace: Path, cron_service: CronService):
        super().__init__(workspace)
        self.cron_service = cron_service

    @property
    def name(self) -> str:
        return "cancel_notification"

    @property
    def description(self) -> str:
        return (
            "Cancel a scheduled notification. "
            "Removes the associated cron job and marks the notification as cancelled."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notification_id": {
                    "type": "string",
                    "description": "ID of the notification to cancel"
                },
                "reason": {
                    "type": "string",
                    "default": "",
                    "description": "Optional reason for cancellation"
                }
            },
            "required": ["notification_id"]
        }

    @with_dashboard_lock
    async def execute(self, notification_id: str, reason: str = "") -> str:
        """Cancel a notification."""
        try:
            # Load notifications
            notifications_data = await self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            # Find notification
            notification, index = self._find_notification(notifications_list, notification_id)
            if not notification:
                return f"Error: Notification '{notification_id}' not found"

            # Check if already cancelled
            if notification.get("status") == "cancelled":
                return f"Notification '{notification_id}' is already cancelled"

            # Check if already delivered
            if notification.get("status") == "delivered":
                return f"Error: Cannot cancel delivered notification '{notification_id}'"

            # Update notification status
            cron_job_id = notification.get("cron_job_id")
            notification["status"] = "cancelled"
            notification["cancelled_at"] = self._now()
            if reason:
                notification["context"] = (
                    f"{notification.get('context', '')}\nCancellation reason: {reason}".strip()
                )

            # DESIGN: Save storage FIRST, then remove cron (storage-first commit).
            # If cron removal fails after save, the notification is correctly
            # marked as cancelled. Orphaned one-shot cron (delete_after_run=True)
            # will fire once through agent.process_direct but is harmless:
            # the message is just text processed by the LLM, not a direct send
            # that bypasses status checks. The cron self-deletes after running.
            notifications_list[index] = notification
            notifications_data["notifications"] = notifications_list

            success, msg = await self._validate_and_save_notifications(notifications_data)
            if not success:
                return msg

            # Now remove cron job (safe: storage already committed)
            # remove_job returns bool (not raises), so check return value.
            if cron_job_id:
                try:
                    removed = self.cron_service.remove_job(cron_job_id)
                    if not removed:
                        from loguru import logger
                        logger.warning(
                            f"Cron job {cron_job_id} not found during cancellation "
                            f"of notification {notification_id}"
                        )
                except Exception as cron_err:
                    from loguru import logger
                    logger.warning(
                        f"Notification {notification_id} cancelled in storage, "
                        f"but cron removal failed: {cron_err}"
                    )
                    return (
                        f"⚠️ Notification '{notification_id}' cancelled, "
                        f"but cron job cleanup failed (will be ignored on next run)."
                    )

            return f"✅ Notification '{notification_id}' cancelled successfully"

        except Exception as e:
            return f"Error cancelling notification: {str(e)}"
