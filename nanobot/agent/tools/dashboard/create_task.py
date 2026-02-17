"""Create new task tool."""

from pathlib import Path
from typing import Any

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class CreateTaskTool(BaseDashboardTool):
    """Tool to create a new task in the dashboard."""

    @property
    def name(self) -> str:
        return "create_task"

    @property
    def description(self) -> str:
        return (
            "Create a new task in the dashboard with title, deadline, priority, etc. "
            "This tool automatically generates IDs, timestamps, and ensures proper JSON structure. "
            "Use this instead of write_file for creating tasks."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title (required)"},
                "deadline": {
                    "type": "string",
                    "description": "Deadline (e.g., '내일', '2026-02-15', '금요일')",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Task priority (default: medium)",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context or description",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags (e.g., ['react', 'study'])",
                },
            },
            "required": ["title"],
        }

    @with_dashboard_lock
    async def execute(
        self,
        title: str,
        deadline: str = "",
        priority: str = "medium",
        context: str = "",
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            # Load existing tasks
            tasks_data = self._load_tasks()

            # Generate new task
            task_id = self._generate_id("task")
            now = self._now()

            new_task = {
                "id": task_id,
                "title": title,
                "raw_input": title,  # Store original input
                "deadline": "",  # Parsed deadline (empty for now)
                "deadline_text": deadline,  # Natural language deadline
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
                "progress": {
                    "percentage": 0,
                    "last_update": now,
                    "note": "",
                    "blocked": False,
                    "blocker_note": None,
                },
                "estimation": {
                    "hours": None,
                    "complexity": "medium",
                    "confidence": "medium",
                },
                "status": "active",
                "priority": priority,
                "context": context,
                "tags": tags or [],
                "links": {
                    "projects": [],
                    "people": [],
                    "insights": [],
                    "resources": [],
                },
            }

            # Add to tasks list
            tasks_data["tasks"].append(new_task)

            # Validate and save
            success, message = self._validate_and_save_tasks(tasks_data)

            if success:
                return f"Created {task_id}: {title}"
            else:
                return message

        except Exception as e:
            return f"Error creating task: {str(e)}"
