"""Dashboard manager for loading and saving dashboard state."""

import json
from pathlib import Path
from typing import Any


class DashboardManager:
    """
    Manages the dashboard state (tasks, questions, notifications, knowledge).

    Provides a simple interface to load and save dashboard data.
    """

    def __init__(self, dashboard_path: Path):
        self.dashboard_path = Path(dashboard_path)
        self.tasks_file = self.dashboard_path / "tasks.json"
        self.questions_file = self.dashboard_path / "questions.json"
        self.notifications_file = self.dashboard_path / "notifications.json"
        self.knowledge_path = self.dashboard_path / "knowledge"

    def load(self) -> dict[str, Any]:
        """
        Load the entire dashboard state.

        Returns:
            dict with keys: tasks, questions, notifications, knowledge
        """
        return {
            "tasks": self._load_json(self.tasks_file).get("tasks", []),
            "questions": self._load_json(self.questions_file).get("questions", []),
            "notifications": self._load_json(self.notifications_file).get("notifications", []),
            "knowledge": {
                "insights": self._load_json(self.knowledge_path / "insights.json").get("insights", []),
            }
        }

    def save(self, dashboard: dict[str, Any]) -> None:
        """
        Save the entire dashboard state.

        Args:
            dashboard: Dashboard state dict
        """
        # Save tasks
        self._save_json(self.tasks_file, {
            "version": "1.0",
            "tasks": dashboard.get("tasks", [])
        })

        # Save questions
        self._save_json(self.questions_file, {
            "version": "1.0",
            "questions": dashboard.get("questions", [])
        })

        # Save notifications
        self._save_json(self.notifications_file, {
            "version": "1.0",
            "notifications": dashboard.get("notifications", [])
        })

        # Save knowledge
        knowledge = dashboard.get("knowledge", {})
        self._save_json(self.knowledge_path / "insights.json", {
            "version": "1.0",
            "insights": knowledge.get("insights", [])
        })

    def _load_json(self, file_path: Path) -> dict[str, Any]:
        """Load JSON file or return empty dict if not exists."""
        if not file_path.exists():
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_json(self, file_path: Path, data: dict[str, Any]) -> None:
        """Save JSON file with pretty printing."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
