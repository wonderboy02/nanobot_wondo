"""List notifications tool."""

from pathlib import Path
from typing import Optional

from nanobot.agent.tools.dashboard.base import BaseDashboardTool


class ListNotificationsTool(BaseDashboardTool):
    """List scheduled notifications."""

    @property
    def name(self) -> str:
        return "list_notifications"

    @property
    def description(self) -> str:
        return (
            "List all scheduled notifications, optionally filtered by status or related task. "
            "Use this to see what notifications are already scheduled to avoid duplicates."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "delivered", "cancelled"],
                    "description": "Filter by notification status (optional)"
                },
                "related_task_id": {
                    "type": "string",
                    "description": "Filter by related task ID (optional)"
                }
            }
        }

    async def execute(
        self,
        status: Optional[str] = None,
        related_task_id: Optional[str] = None
    ) -> str:
        """List notifications."""
        try:
            # Load notifications
            notifications_data = await self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            if not notifications_list:
                return "No notifications found."

            # Filter notifications
            filtered = notifications_list

            if status:
                filtered = [n for n in filtered if n.get("status") == status]

            if related_task_id:
                filtered = [n for n in filtered if n.get("related_task_id") == related_task_id]

            if not filtered:
                filters = []
                if status:
                    filters.append(f"status={status}")
                if related_task_id:
                    filters.append(f"task={related_task_id}")
                return f"No notifications found with filters: {', '.join(filters)}"

            # Format output
            from datetime import datetime

            result = []
            result.append(f"Found {len(filtered)} notification(s):\n")

            for notif in filtered:
                result.append(f"**{notif['id']}**: {notif['message']}")
                result.append(f"  - Status: {notif['status']}")
                result.append(f"  - Type: {notif['type']}")
                result.append(f"  - Priority: {notif['priority']}")

                # Format scheduled time
                scheduled_at = notif.get("scheduled_at")
                if scheduled_at:
                    try:
                        dt = datetime.fromisoformat(scheduled_at)
                        result.append(f"  - Scheduled: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    except (ValueError, TypeError):
                        result.append(f"  - Scheduled: {scheduled_at}")

                if notif.get("scheduled_at_text"):
                    result.append(f"  - Original: {notif['scheduled_at_text']}")

                if notif.get("related_task_id"):
                    result.append(f"  - Related Task: {notif['related_task_id']}")

                if notif.get("related_question_id"):
                    result.append(f"  - Related Question: {notif['related_question_id']}")

                if notif.get("delivered_at"):
                    try:
                        dt = datetime.fromisoformat(notif["delivered_at"])
                        result.append(f"  - Delivered: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    except (ValueError, TypeError):
                        result.append(f"  - Delivered: {notif['delivered_at']}")

                if notif.get("cancelled_at"):
                    try:
                        dt = datetime.fromisoformat(notif["cancelled_at"])
                        result.append(f"  - Cancelled: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    except (ValueError, TypeError):
                        result.append(f"  - Cancelled: {notif['cancelled_at']}")

                if notif.get("context"):
                    result.append(f"  - Context: {notif['context']}")

                result.append("")  # Empty line

            return "\n".join(result)

        except Exception as e:
            return f"Error listing notifications: {str(e)}"
