"""Base class for Dashboard tools with shared utilities."""

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from nanobot.agent.tools.base import Tool
from nanobot.dashboard.manager import DashboardManager


def with_dashboard_lock(fn):
    """Decorator to wrap tool execute methods with the dashboard lock.

    Ensures read-modify-write cycles on dashboard JSON files are atomic,
    preventing race conditions between Main Agent and Worker Agent.
    """
    import functools

    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        async with self._get_lock():
            return await fn(self, *args, **kwargs)

    return wrapper


class BaseDashboardTool(Tool):
    """Base class for all Dashboard tools with shared utilities."""

    _dashboard_lock: asyncio.Lock | None = None

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.manager = DashboardManager(workspace / "dashboard")

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        """Get or create the shared dashboard lock."""
        if cls._dashboard_lock is None:
            cls._dashboard_lock = asyncio.Lock()
        return cls._dashboard_lock

    def _generate_id(self, prefix: str) -> str:
        """Generate unique ID: {prefix}_xxxxxxxx."""
        return f"{prefix}_{str(uuid.uuid4())[:8]}"

    def _now(self) -> str:
        """Current timestamp in ISO 8601 format."""
        return datetime.now().isoformat()

    def _parse_datetime(self, dt_str: str) -> datetime | None:
        """Parse datetime string to datetime object.

        Supports:
        - ISO format (e.g., '2026-02-09T15:00:00')
        - Relative time: 'in X hours', 'in X minutes'
        - 'tomorrow' with optional time (e.g., 'tomorrow 9am')
        """
        # Try ISO format first
        try:
            return datetime.fromisoformat(dt_str)
        except ValueError:
            pass

        # Try relative time parsing (simple cases)
        now = datetime.now()

        # "in X hours"
        match = re.match(r"in (\d+) hours?", dt_str, re.IGNORECASE)
        if match:
            hours = int(match.group(1))
            return now + timedelta(hours=hours)

        # "in X minutes"
        match = re.match(r"in (\d+) minutes?", dt_str, re.IGNORECASE)
        if match:
            minutes = int(match.group(1))
            return now + timedelta(minutes=minutes)

        # "tomorrow"
        if "tomorrow" in dt_str.lower():
            tomorrow = now + timedelta(days=1)
            # Extract time if provided (e.g., "tomorrow 9am")
            time_match = re.search(r"(\d+)(am|pm)", dt_str, re.IGNORECASE)
            if time_match:
                hour = int(time_match.group(1))
                if time_match.group(2).lower() == "pm" and hour != 12:
                    hour += 12
                elif time_match.group(2).lower() == "am" and hour == 12:
                    hour = 0
                return tomorrow.replace(hour=hour, minute=0, second=0, microsecond=0)
            return tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)

        # Could not parse
        return None

    def _validate_and_save_tasks(self, tasks_data: dict) -> tuple[bool, str]:
        """
        Validate tasks data and save if valid.

        Args:
            tasks_data: Dict with 'version' and 'tasks' keys

        Returns:
            (success: bool, message: str)
        """
        try:
            from nanobot.dashboard.schema import validate_tasks_file

            validate_tasks_file(tasks_data)

            tasks_path = self.workspace / "dashboard" / "tasks.json"
            tasks_path.parent.mkdir(parents=True, exist_ok=True)

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
            from nanobot.dashboard.schema import validate_questions_file

            validate_questions_file(questions_data)

            questions_path = self.workspace / "dashboard" / "questions.json"
            questions_path.parent.mkdir(parents=True, exist_ok=True)

            questions_path.write_text(
                json.dumps(questions_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            return (True, "Questions updated successfully")
        except Exception as e:
            return (False, f"Error: {str(e)}")

    def _validate_and_save_notifications(self, notifications_data: dict) -> tuple[bool, str]:
        """
        Validate notifications data and save if valid.

        Args:
            notifications_data: Dict with 'version' and 'notifications' keys

        Returns:
            (success: bool, message: str)
        """
        try:
            from nanobot.dashboard.schema import validate_notifications_file

            validate_notifications_file(notifications_data)

            notifications_path = self.workspace / "dashboard" / "notifications.json"
            notifications_path.parent.mkdir(parents=True, exist_ok=True)

            notifications_path.write_text(
                json.dumps(notifications_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            return (True, "Notifications updated successfully")
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

    def _find_notification(
        self, notifications: list[dict], notification_id: str
    ) -> tuple[dict | None, int]:
        """
        Find notification by ID.

        Returns:
            (notification: dict | None, index: int)
        """
        for i, notif in enumerate(notifications):
            if notif.get("id") == notification_id:
                return (notif, i)
        return (None, -1)

    def _load_tasks(self) -> dict:
        """Load tasks.json file."""
        tasks_path = self.workspace / "dashboard" / "tasks.json"

        if not tasks_path.exists():
            return {"version": "1.0", "tasks": []}

        return json.loads(tasks_path.read_text(encoding="utf-8"))

    def _load_questions(self) -> dict:
        """Load questions.json file."""
        questions_path = self.workspace / "dashboard" / "questions.json"

        if not questions_path.exists():
            return {"version": "1.0", "questions": []}

        return json.loads(questions_path.read_text(encoding="utf-8"))

    def _load_notifications(self) -> dict:
        """Load notifications.json file."""
        notifications_path = self.workspace / "dashboard" / "notifications.json"

        if not notifications_path.exists():
            return {"version": "1.0", "notifications": []}

        return json.loads(notifications_path.read_text(encoding="utf-8"))
