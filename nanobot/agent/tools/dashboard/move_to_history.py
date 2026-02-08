"""Move task to history tool."""

import json
from pathlib import Path
from typing import Any

from nanobot.agent.tools.dashboard.base import BaseDashboardTool


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

    async def execute(
        self, task_id: str, reflection: str = "", **kwargs: Any
    ) -> str:
        try:
            # Load existing tasks
            tasks_data = self._load_tasks()

            # Find task
            task, index = self._find_task(tasks_data["tasks"], task_id)

            if task is None:
                return f"Error: Task {task_id} not found"

            # Load history
            history_path = self.workspace / "dashboard" / "knowledge" / "history.json"
            history_path.parent.mkdir(parents=True, exist_ok=True)

            if history_path.exists():
                history_data = json.loads(history_path.read_text(encoding="utf-8"))
            else:
                history_data = {"version": "1.0", "completed_tasks": [], "projects": []}

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

            # Save both files
            success, message = self._validate_and_save_tasks(tasks_data)
            if not success:
                return message

            history_path.write_text(
                json.dumps(history_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            return f"Moved {task_id} to history"

        except Exception as e:
            return f"Error moving task to history: {str(e)}"
