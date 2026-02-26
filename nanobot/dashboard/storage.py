"""Storage backend abstraction for Dashboard data.

Provides a clean interface between Dashboard tools and the actual storage layer.
- StorageBackend: Abstract base class defining the interface.
- JsonStorageBackend: File-based JSON storage (default fallback).
- load_json_file: Shared utility for safe JSON file loading.

Notion-specific backends live in nanobot.notion.storage.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import NamedTuple


class SaveResult(NamedTuple):
    """Result of a storage save operation.

    NamedTuple so existing ``ok, msg = save_tasks(data)`` unpacking still works.
    """

    success: bool
    message: str


def load_json_file(path: Path, default: dict | None = None) -> dict:
    """Load a JSON file safely, returning default on any error.

    DESIGN: Intentionally swallows parse errors and returns default.
    Dashboard summary and tool reads should not crash the agent when a JSON
    file is corrupted or temporarily locked. The trade-off is that a corrupt
    file will silently return empty data — acceptable because the next write
    (via dashboard tools with Pydantic validation) will restore valid structure.

    Shared utility used by JsonStorageBackend and helper.py.
    """
    if not path.exists():
        return default or {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default or {}


# ============================================================================
# Storage Backend ABC
# ============================================================================


class StorageBackend(ABC):
    """Abstract storage backend for Dashboard data.

    Each entity has a load/save pair:
    - load_* returns the full file-level dict (e.g., {"version": "1.0", "tasks": [...]}).
    - save_* validates, then delegates to _persist_* (Template Method pattern).

    Subclasses implement _persist_* (and load_*) only.
    Validation lives once in the ABC, eliminating duplication across backends.
    """

    # --- Tasks ---
    @abstractmethod
    def load_tasks(self) -> dict: ...

    def save_tasks(self, data: dict) -> SaveResult:
        """Validate and persist tasks data."""
        try:
            from nanobot.dashboard.schema import validate_tasks_file

            validate_tasks_file(data)
        except Exception as e:
            return SaveResult(False, f"Validation error: {e}")
        return self._persist_tasks(data)

    @abstractmethod
    def _persist_tasks(self, data: dict) -> SaveResult: ...

    # --- Questions ---
    @abstractmethod
    def load_questions(self) -> dict: ...

    def save_questions(self, data: dict) -> SaveResult:
        """Validate and persist questions data."""
        try:
            from nanobot.dashboard.schema import validate_questions_file

            validate_questions_file(data)
        except Exception as e:
            return SaveResult(False, f"Validation error: {e}")
        return self._persist_questions(data)

    @abstractmethod
    def _persist_questions(self, data: dict) -> SaveResult: ...

    # --- Notifications ---
    @abstractmethod
    def load_notifications(self) -> dict: ...

    def save_notifications(self, data: dict) -> SaveResult:
        """Validate and persist notifications data."""
        try:
            from nanobot.dashboard.schema import validate_notifications_file

            validate_notifications_file(data)
        except Exception as e:
            return SaveResult(False, f"Validation error: {e}")
        return self._persist_notifications(data)

    @abstractmethod
    def _persist_notifications(self, data: dict) -> SaveResult: ...

    # --- Insights ---
    @abstractmethod
    def load_insights(self) -> dict: ...

    def save_insights(self, data: dict) -> SaveResult:
        """Persist insights data (no Pydantic validation — flexible schema)."""
        return self._persist_insights(data)

    @abstractmethod
    def _persist_insights(self, data: dict) -> SaveResult: ...

    # --- ID mapping (Notion bootstrap support) ---
    def register_id_mapping(self, entity_type: str, nanobot_id: str, page_id: str) -> None:
        """Register a nanobot_id → external page_id mapping.

        Called by Worker bootstrap to ensure that newly-assigned IDs are
        recognised during save (preventing duplicate page creation in Notion).
        No-op for backends that don't use external page IDs (e.g. JSON).
        """

    def unregister_id_mapping(self, entity_type: str, nanobot_id: str) -> None:
        """Remove a previously registered id mapping (rollback on save failure).

        No-op for backends that don't use external page IDs.
        """

    # --- Lifecycle ---
    def close(self) -> None:
        """Release resources (HTTP clients, etc.). No-op for stateless backends."""

    def invalidate_cache(self) -> None:
        """Invalidate any cached data. No-op for backends without caching."""


# ============================================================================
# JSON Storage Backend (default / fallback)
# ============================================================================


class JsonStorageBackend(StorageBackend):
    """File-based JSON storage — the original Dashboard storage mechanism.

    Used when Notion is not configured (notion.enabled=false).
    Reads/writes directly to workspace/dashboard/*.json files.
    """

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._dashboard_dir = workspace / "dashboard"
        self._knowledge_dir = self._dashboard_dir / "knowledge"

    def _load_json(self, path: Path, default: dict | None = None) -> dict:
        return load_json_file(path, default)

    def _save_json(self, path: Path, data: dict) -> SaveResult:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return SaveResult(True, "Saved successfully")
        except Exception as e:
            return SaveResult(False, f"Error: {e}")

    # --- Tasks ---

    def load_tasks(self) -> dict:
        return self._load_json(
            self._dashboard_dir / "tasks.json",
            default={"version": "1.0", "tasks": []},
        )

    def _persist_tasks(self, data: dict) -> SaveResult:
        return self._save_json(self._dashboard_dir / "tasks.json", data)

    # --- Questions ---

    def load_questions(self) -> dict:
        return self._load_json(
            self._dashboard_dir / "questions.json",
            default={"version": "1.0", "questions": []},
        )

    def _persist_questions(self, data: dict) -> SaveResult:
        return self._save_json(self._dashboard_dir / "questions.json", data)

    # --- Notifications ---

    def load_notifications(self) -> dict:
        return self._load_json(
            self._dashboard_dir / "notifications.json",
            default={"version": "1.0", "notifications": []},
        )

    def _persist_notifications(self, data: dict) -> SaveResult:
        return self._save_json(self._dashboard_dir / "notifications.json", data)

    # --- Insights ---

    def load_insights(self) -> dict:
        return self._load_json(
            self._knowledge_dir / "insights.json",
            default={"version": "1.0", "insights": []},
        )

    def _persist_insights(self, data: dict) -> SaveResult:
        return self._save_json(self._knowledge_dir / "insights.json", data)
