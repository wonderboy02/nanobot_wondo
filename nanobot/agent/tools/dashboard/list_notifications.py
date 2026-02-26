"""List notifications tool."""

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
                    "description": "Filter by notification status (optional)",
                },
                "related_task_id": {
                    "type": "string",
                    "description": "Filter by related task ID (optional)",
                },
            },
        }

    async def execute(self, status: str | None = None, related_task_id: str | None = None) -> str:
        """List notifications."""
        try:
            notifications_data = await self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            if not notifications_list:
                return "No notifications found."

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

            from datetime import datetime

            def _fmt_dt(value: str | None, label: str) -> str | None:
                """Format an ISO datetime field, falling back to raw string."""
                if not value:
                    return None
                try:
                    dt = datetime.fromisoformat(value)
                    return f"  - {label}: {dt.strftime('%Y-%m-%d %H:%M:%S')}"
                except (ValueError, TypeError):
                    return f"  - {label}: {value}"

            result = []
            result.append(f"Found {len(filtered)} notification(s):\n")

            for notif in filtered:
                result.append(f"**{notif['id']}**: {notif['message']}")
                result.append(f"  - Status: {notif['status']}")
                result.append(f"  - Type: {notif['type']}")
                result.append(f"  - Priority: {notif['priority']}")

                line = _fmt_dt(notif.get("scheduled_at"), "Scheduled")
                if line:
                    result.append(line)

                if notif.get("scheduled_at_text"):
                    result.append(f"  - Original: {notif['scheduled_at_text']}")

                if notif.get("related_task_id"):
                    result.append(f"  - Related Task: {notif['related_task_id']}")

                if notif.get("related_question_id"):
                    result.append(f"  - Related Question: {notif['related_question_id']}")

                line = _fmt_dt(notif.get("delivered_at"), "Delivered")
                if line:
                    result.append(line)

                line = _fmt_dt(notif.get("cancelled_at"), "Cancelled")
                if line:
                    result.append(line)

                if notif.get("context"):
                    result.append(f"  - Context: {notif['context']}")

                result.append("")  # Empty line

            return "\n".join(result)

        except Exception as e:
            return f"Error listing notifications: {str(e)}"
