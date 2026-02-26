"""Base class for Dashboard tools with shared utilities."""

import asyncio
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.dashboard.storage import SaveResult, StorageBackend


def with_dashboard_lock(fn):
    """Decorator to wrap tool execute methods with the dashboard lock.

    Ensures read-modify-write cycles on dashboard JSON files are atomic.
    Primary Main Agent vs Worker Agent serialization is handled by
    _processing_lock (AgentLoop). This lock guards against concurrent
    tool calls within a single processing session.
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

    def __init__(self, workspace: Path, backend: "StorageBackend | None" = None):
        self.workspace = workspace
        self._backend_instance = backend  # None → lazy JsonStorageBackend

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        """Get or create the shared dashboard lock."""
        if cls._dashboard_lock is None:
            cls._dashboard_lock = asyncio.Lock()
        return cls._dashboard_lock

    @property
    def _backend(self) -> "StorageBackend":
        """Get the storage backend.

        Uses the backend injected at construction time. If none was provided,
        lazily creates a JsonStorageBackend from this tool's workspace path.
        """
        if self._backend_instance is None:
            from nanobot.dashboard.storage import JsonStorageBackend

            self._backend_instance = JsonStorageBackend(self.workspace)
        return self._backend_instance

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

    # ========================================================================
    # Storage delegation — all I/O goes through _backend via asyncio.to_thread
    # to avoid blocking the event loop when backend does sync I/O (e.g., Notion)
    # ========================================================================

    async def _validate_and_save_tasks(self, tasks_data: dict) -> "SaveResult":
        """Validate and save tasks data via the storage backend."""
        return await asyncio.to_thread(self._backend.save_tasks, tasks_data)

    async def _validate_and_save_questions(self, questions_data: dict) -> "SaveResult":
        """Validate and save questions data via the storage backend."""
        return await asyncio.to_thread(self._backend.save_questions, questions_data)

    async def _validate_and_save_notifications(self, notifications_data: dict) -> "SaveResult":
        """Validate and save notifications data via the storage backend."""
        return await asyncio.to_thread(self._backend.save_notifications, notifications_data)

    def _find_by_id(self, items: list[dict], item_id: str) -> tuple[dict | None, int]:
        """Find an item by its 'id' field. Returns (item, index) or (None, -1)."""
        for i, item in enumerate(items):
            if item.get("id") == item_id:
                return (item, i)
        return (None, -1)

    # Convenience aliases for readability at call sites
    _find_task = _find_by_id
    _find_question = _find_by_id
    _find_notification = _find_by_id

    async def _load_tasks(self) -> dict:
        """Load tasks via the storage backend (non-blocking)."""
        return await asyncio.to_thread(self._backend.load_tasks)

    async def _load_questions(self) -> dict:
        """Load questions via the storage backend (non-blocking)."""
        return await asyncio.to_thread(self._backend.load_questions)

    async def _load_notifications(self) -> dict:
        """Load notifications via the storage backend (non-blocking)."""
        return await asyncio.to_thread(self._backend.load_notifications)

    async def _load_insights(self) -> dict:
        """Load insights via the storage backend (non-blocking)."""
        return await asyncio.to_thread(self._backend.load_insights)

    async def _validate_and_save_insights(self, insights_data: dict) -> tuple[bool, str]:
        """Save insights data via the storage backend."""
        return await asyncio.to_thread(self._backend.save_insights, insights_data)
