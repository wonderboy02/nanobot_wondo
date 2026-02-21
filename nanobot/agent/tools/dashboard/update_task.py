"""Update existing task tool."""

from pathlib import Path
from typing import Any

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class UpdateTaskTool(BaseDashboardTool):
    """Tool to update an existing task in the dashboard."""

    @property
    def name(self) -> str:
        return "update_task"

    @property
    def description(self) -> str:
        return (
            "Update an existing task in the dashboard. "
            "Can update progress, status, blockers, context, deadline, and priority. "
            "Use this instead of write_file for updating tasks."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID (required)"},
                "progress": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Progress percentage (0-100)",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "completed", "someday", "cancelled"],
                    "description": "Task status (use archive_task tool for archiving)",
                },
                "blocked": {
                    "type": "boolean",
                    "description": "Is task blocked?",
                },
                "blocker_note": {
                    "type": "string",
                    "description": "Note about what's blocking the task",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context or description",
                },
                "deadline": {
                    "type": "string",
                    "description": "New deadline (e.g., '내일', '2026-02-15')",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Task priority",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags (e.g., ['react', 'study'])",
                },
            },
            "required": ["task_id"],
        }

    @with_dashboard_lock
    async def execute(
        self,
        task_id: str,
        progress: int | None = None,
        status: str | None = None,
        blocked: bool | None = None,
        blocker_note: str | None = None,
        context: str | None = None,
        deadline: str | None = None,
        priority: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            # Load existing tasks
            tasks_data = await self._load_tasks()

            # Find task
            task, index = self._find_task(tasks_data["tasks"], task_id)

            if task is None:
                return f"Error: Task {task_id} not found"

            # Update fields
            now = self._now()
            task["updated_at"] = now

            if progress is not None:
                task["progress"]["percentage"] = progress
                task["progress"]["last_update"] = now

            if status is not None:
                task["status"] = status
                if status == "completed":
                    task["completed_at"] = now
                    task["progress"]["percentage"] = 100

            if blocked is not None:
                task["progress"]["blocked"] = blocked

            if blocker_note is not None:
                task["progress"]["blocker_note"] = blocker_note

            if context is not None:
                task["context"] = context

            if deadline is not None:
                task["deadline_text"] = deadline

            if priority is not None:
                task["priority"] = priority

            if tags is not None:
                task["tags"] = tags

            # Replace task in list
            tasks_data["tasks"][index] = task

            # Validate and save
            success, message = await self._validate_and_save_tasks(tasks_data)

            if success:
                return f"Updated {task_id}"
            else:
                return message

        except Exception as e:
            return f"Error updating task: {str(e)}"
