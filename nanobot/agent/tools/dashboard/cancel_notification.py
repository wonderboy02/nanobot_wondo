"""Cancel notification tool.

Ledger-only: marks notification as cancelled in storage.
GCal cleanup is handled by ReconciliationScheduler on next trigger.
"""

from __future__ import annotations

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class CancelNotificationTool(BaseDashboardTool):
    """Cancel a scheduled notification."""

    @property
    def name(self) -> str:
        return "cancel_notification"

    @property
    def description(self) -> str:
        return "Cancel a scheduled notification. Marks it as cancelled."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notification_id": {
                    "type": "string",
                    "description": "ID of the notification to cancel",
                },
                "reason": {
                    "type": "string",
                    "default": "",
                    "description": "Optional reason for cancellation",
                },
            },
            "required": ["notification_id"],
        }

    @with_dashboard_lock
    async def execute(self, notification_id: str, reason: str = "") -> str:
        """Cancel a notification (ledger write only)."""
        try:
            notifications_data = await self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            notification, index = self._find_notification(notifications_list, notification_id)
            if not notification:
                return f"Error: Notification '{notification_id}' not found"

            if notification.get("status") == "cancelled":
                return f"Notification '{notification_id}' is already cancelled"

            if notification.get("status") == "delivered":
                return f"Error: Cannot cancel delivered notification '{notification_id}'"

            notification["status"] = "cancelled"
            notification["cancelled_at"] = self._now()
            if reason:
                notification["context"] = (
                    f"{notification.get('context', '')}\nCancellation reason: {reason}".strip()
                )

            success, msg = await self._validate_and_save_notifications(notifications_data)
            if not success:
                return msg

            return f"\u2705 Notification '{notification_id}' cancelled successfully"

        except Exception as e:
            return f"Error cancelling notification: {str(e)}"
