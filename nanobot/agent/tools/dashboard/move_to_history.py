"""Move task to history tool."""

from typing import Any

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class MoveToHistoryTool(BaseDashboardTool):
    """Tool to move a completed task to history."""

    @property
    def name(self) -> str:
        return "move_to_history"

    @property
    def description(self) -> str:
        return (
            "Move a completed task to the history knowledge base. "
            "Use this for tasks that are completed or cancelled. "
            "The task will be removed from the active tasks list and stored in history."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to move to history",
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
            # Load existing tasks via backend
            tasks_data = await self._load_tasks()

            # Find task
            task, index = self._find_task(tasks_data["tasks"], task_id)

            if task is None:
                return f"Error: Task {task_id} not found"

            # Load history via backend
            history_data = await self._load_history()

            # Add reflection if provided
            if reflection:
                task["reflection"] = reflection

            # Add timestamp
            now = self._now()
            task["archived_at"] = now

            # Add to history
            history_data["completed_tasks"].append(task)

            # Remove from tasks
            tasks_data["tasks"].pop(index)

            # DESIGN: Non-atomic 2-step write (intentional).
            # Save history FIRST, then remove from tasks.
            # If history save fails → task stays in active list (no data loss).
            # If task removal fails → task appears in both places (recoverable,
            # next worker cycle or manual cleanup can fix it).
            # This is the safer failure mode compared to removing first.
            success, message = await self._validate_and_save_history(history_data)
            if not success:
                return f"Error saving history (task not removed): {message}"

            success, message = await self._validate_and_save_tasks(tasks_data)
            if not success:
                # History saved but task removal failed — log warning
                from loguru import logger
                logger.warning(f"History saved but task removal failed: {message}")
                return f"Warning: Task added to history but removal failed: {message}"

            return f"Moved {task_id} to history"

        except Exception as e:
            return f"Error moving task to history: {str(e)}"
