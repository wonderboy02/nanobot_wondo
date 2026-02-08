"""Base class for Dashboard tools with shared utilities."""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.dashboard.manager import DashboardManager


class BaseDashboardTool(Tool):
    """Base class for all Dashboard tools with shared utilities."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.manager = DashboardManager(workspace / "dashboard")

    def _generate_id(self, prefix: str) -> str:
        """Generate unique ID: {prefix}_xxxxxxxx."""
        return f"{prefix}_{str(uuid.uuid4())[:8]}"

    def _now(self) -> str:
        """Current timestamp in ISO 8601 format."""
        return datetime.now().isoformat()

    def _validate_and_save_tasks(self, tasks_data: dict) -> tuple[bool, str]:
        """
        Validate tasks data and save if valid.

        Args:
            tasks_data: Dict with 'version' and 'tasks' keys

        Returns:
            (success: bool, message: str)
        """
        try:
            # Validate using Pydantic schemas
            from nanobot.dashboard.schema import validate_tasks_file

            validate_tasks_file(tasks_data)

            # Save via DashboardManager (atomic write)
            tasks_path = self.workspace / "dashboard" / "tasks.json"
            tasks_path.parent.mkdir(parents=True, exist_ok=True)

            import json

            tasks_path.write_text(
                json.dumps(tasks_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            return (True, "Tasks updated successfully")
        except Exception as e:
            return (False, f"Error: {str(e)}")

    def _validate_and_save_questions(self, questions_data: dict) -> tuple[bool, str]:
        """
        Validate questions data and save if valid.

        Args:
            questions_data: Dict with 'version' and 'questions' keys

        Returns:
            (success: bool, message: str)
        """
        try:
            # Validate using Pydantic schemas
            from nanobot.dashboard.schema import validate_questions_file

            validate_questions_file(questions_data)

            # Save via DashboardManager (atomic write)
            questions_path = self.workspace / "dashboard" / "questions.json"
            questions_path.parent.mkdir(parents=True, exist_ok=True)

            import json

            questions_path.write_text(
                json.dumps(questions_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            return (True, "Questions updated successfully")
        except Exception as e:
            return (False, f"Error: {str(e)}")

    def _find_task(self, tasks: list[dict], task_id: str) -> tuple[dict | None, int]:
        """
        Find task by ID.

        Returns:
            (task: dict | None, index: int)
        """
        for i, task in enumerate(tasks):
            if task.get("id") == task_id:
                return (task, i)
        return (None, -1)

    def _find_question(
        self, questions: list[dict], question_id: str
    ) -> tuple[dict | None, int]:
        """
        Find question by ID.

        Returns:
            (question: dict | None, index: int)
        """
        for i, q in enumerate(questions):
            if q.get("id") == question_id:
                return (q, i)
        return (None, -1)

    def _load_tasks(self) -> dict:
        """Load tasks.json file."""
        import json

        tasks_path = self.workspace / "dashboard" / "tasks.json"

        if not tasks_path.exists():
            # Return empty structure
            return {"version": "1.0", "tasks": []}

        return json.loads(tasks_path.read_text(encoding="utf-8"))

    def _load_questions(self) -> dict:
        """Load questions.json file."""
        import json

        questions_path = self.workspace / "dashboard" / "questions.json"

        if not questions_path.exists():
            # Return empty structure
            return {"version": "1.0", "questions": []}

        return json.loads(questions_path.read_text(encoding="utf-8"))
