"""Set or update recurring (daily habit) configuration for a task."""

from typing import Any

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _format_days(days: list[int]) -> str:
    """Format day-of-week list as human-readable string."""
    if sorted(days) == list(range(7)):
        return "매일"
    if sorted(days) == list(range(5)):
        return "평일"
    if sorted(days) == [5, 6]:
        return "주말"
    return ", ".join(_DAY_NAMES[d] for d in sorted(days))


class SetRecurringTool(BaseDashboardTool):
    """Tool to set or update recurring (daily habit) configuration on a task."""

    @property
    def name(self) -> str:
        return "set_recurring"

    @property
    def description(self) -> str:
        return (
            "Set or update recurring (daily habit) configuration for a task. "
            "Enables daily habit tracking with streak counting. "
            "Preserves existing streak/stats when updating configuration."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID (required)"},
                "enabled": {
                    "type": "boolean",
                    "description": "Enable or disable recurring (default: true)",
                },
                "days_of_week": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    "description": (
                        "Days of week (0=Mon, 6=Sun). Default: [0,1,2,3,4,5,6] (every day)"
                    ),
                },
                "check_time": {
                    "type": "string",
                    "description": "Check time in HH:MM format (e.g., '22:00')",
                },
            },
            "required": ["task_id"],
        }

    @with_dashboard_lock
    async def execute(
        self,
        task_id: str,
        enabled: bool = True,
        days_of_week: list[int] | None = None,
        check_time: str | None = None,
    ) -> str:
        try:
            tasks_data = await self._load_tasks()
            task, index = self._find_task(tasks_data["tasks"], task_id)

            if task is None:
                return f"Error: Task {task_id} not found"

            # Merge with existing config (preserve stats)
            existing = task.get("recurring") or {}

            config = {
                "enabled": enabled,
                "frequency": "daily",
                "days_of_week": days_of_week
                if days_of_week is not None
                else existing.get("days_of_week", list(range(7))),
                "check_time": check_time if check_time is not None else existing.get("check_time"),
                # Preserve stats from existing config
                "streak_current": existing.get("streak_current", 0),
                "streak_best": existing.get("streak_best", 0),
                "total_completed": existing.get("total_completed", 0),
                "total_missed": existing.get("total_missed", 0),
                "last_completed_date": existing.get("last_completed_date"),
                "last_miss_date": existing.get("last_miss_date"),
            }

            task["recurring"] = config
            task["updated_at"] = self._now()
            tasks_data["tasks"][index] = task

            success, message = await self._validate_and_save_tasks(tasks_data)

            if success:
                days_str = _format_days(config["days_of_week"])
                parts = [f"Set recurring on {task_id}: {days_str}"]
                if config["check_time"]:
                    parts.append(f"check at {config['check_time']}")
                if not enabled:
                    parts = [f"Disabled recurring on {task_id}"]
                return " | ".join(parts)
            else:
                return message

        except Exception as e:
            return f"Error setting recurring: {str(e)}"
