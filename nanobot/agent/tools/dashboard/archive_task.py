"""Archive task tool."""

from typing import Any

from loguru import logger

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class ArchiveTaskTool(BaseDashboardTool):
    """Tool to archive a completed task."""

    @property
    def name(self) -> str:
        return "archive_task"

    @property
    def description(self) -> str:
        return (
            "Archive a completed or cancelled task. "
            "Sets status to 'archived' with an optional reflection note. "
            "The task stays in the tasks list with archived status."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to archive",
                },
                "reflection": {
                    "type": "string",
                    "description": "Optional reflection or notes about the completed task",
                },
            },
            "required": ["task_id"],
        }

    @with_dashboard_lock
    async def execute(
        self, task_id: str, reflection: str = "", **kwargs: Any
    ) -> str:
        try:
            tasks_data = await self._load_tasks()

            task, index = self._find_task(tasks_data.get("tasks", []), task_id)

            if task is None:
                return f"Error: Task {task_id} not found"

            now = self._now()
            was_cancelled = task.get("status") == "cancelled"
            task["status"] = "archived"
            task["reflection"] = reflection or task.get("reflection", "")
            task["completed_at"] = task.get("completed_at") or now
            progress = task.setdefault("progress", {"last_update": now})
            if not was_cancelled:
                progress["percentage"] = 100
            progress.setdefault("last_update", now)
            task["updated_at"] = now

            success, message = await self._validate_and_save_tasks(tasks_data)
            if not success:
                return f"Error archiving task: {message}"

            return f"Archived {task_id}"

        except Exception as e:
            logger.error(f"[ArchiveTask] Failed to archive {task_id}: {e}")
            return f"Error archiving task: {str(e)}"
