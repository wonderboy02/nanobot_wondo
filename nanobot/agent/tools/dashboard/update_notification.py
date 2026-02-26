"""Update notification tool.

Ledger-only: updates notification fields in storage.
GCal sync is handled by ReconciliationScheduler on next trigger.
"""

from __future__ import annotations

from typing import Optional

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class UpdateNotificationTool(BaseDashboardTool):
    """Update an existing notification."""

    @property
    def name(self) -> str:
        return "update_notification"

    @property
    def description(self) -> str:
        return "Update an existing notification's message, time, or priority."

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
        """Update a notification (ledger write only)."""
        try:
            notifications_data = await self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            notification, index = self._find_notification(notifications_list, notification_id)
            if not notification:
                return f"Error: Notification '{notification_id}' not found"

            if notification.get("status") in ["delivered", "cancelled"]:
                return f"Error: Cannot update {notification['status']} notification"

            if message is not None:
                notification["message"] = message

            if priority is not None:
                notification["priority"] = priority

            if scheduled_at is not None:
                scheduled_dt = self._parse_datetime(scheduled_at)
                if not scheduled_dt:
                    return f"Error: Could not parse scheduled_at '{scheduled_at}'"

                notification["scheduled_at"] = scheduled_dt.isoformat()
                notification["scheduled_at_text"] = (
                    scheduled_at if not scheduled_at.startswith("20") else None
                )
                # Reset gcal_event_id so Reconciler creates a new event
                notification["gcal_event_id"] = None

            success, msg = await self._validate_and_save_notifications(notifications_data)
            if not success:
                return msg

            return f"\u2705 Notification '{notification_id}' updated successfully"

        except Exception as e:
            return f"Error updating notification: {str(e)}"
