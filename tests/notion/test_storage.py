"""Tests for JsonStorageBackend (nanobot/dashboard/storage.py).

Covers load defaults, save/load round-trip, and validation failures.
"""

import json
from pathlib import Path

import pytest

from nanobot.dashboard.storage import JsonStorageBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace directory structure."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "dashboard").mkdir()
    (ws / "dashboard" / "knowledge").mkdir()
    return ws


@pytest.fixture
def storage(workspace: Path) -> JsonStorageBackend:
    """Create a JsonStorageBackend pointing to the tmp workspace."""
    return JsonStorageBackend(workspace)


# ---------------------------------------------------------------------------
# load_* with missing files returns defaults
# ---------------------------------------------------------------------------

class TestLoadDefaults:
    """load_* methods should return sensible defaults when files are missing."""

    def test_load_tasks_missing_file(self, storage):
        result = storage.load_tasks()
        assert result == {"version": "1.0", "tasks": []}

    def test_load_questions_missing_file(self, storage):
        result = storage.load_questions()
        assert result == {"version": "1.0", "questions": []}

    def test_load_notifications_missing_file(self, storage):
        result = storage.load_notifications()
        assert result == {"version": "1.0", "notifications": []}

    def test_load_insights_missing_file(self, storage):
        result = storage.load_insights()
        assert result == {"version": "1.0", "insights": []}



# ---------------------------------------------------------------------------
# save then load round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """save_* then load_* should return the same data."""

    def test_tasks_round_trip(self, storage):
        data = {
            "version": "1.0",
            "tasks": [
                {
                    "id": "task_001",
                    "title": "Test task",
                    "raw_input": None,
                    "deadline": None,
                    "deadline_text": None,
                    "estimation": {"hours": None, "complexity": "medium", "confidence": "medium"},
                    "progress": {
                        "percentage": 0,
                        "last_update": "2026-02-20T00:00:00",
                        "note": "",
                        "blocked": False,
                        "blocker_note": None,
                    },
                    "status": "active",
                    "priority": "medium",
                    "context": "",
                    "tags": [],
                    "links": {"projects": [], "insights": [], "resources": []},
                    "created_at": "2026-02-20T00:00:00",
                    "updated_at": "2026-02-20T00:00:00",
                    "completed_at": None,
                }
            ],
        }
        ok, msg = storage.save_tasks(data)
        assert ok is True
        assert "success" in msg.lower() or "Saved" in msg

        loaded = storage.load_tasks()
        assert loaded["tasks"][0]["id"] == "task_001"
        assert loaded["tasks"][0]["title"] == "Test task"

    def test_questions_round_trip(self, storage):
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "How is it going?",
                    "context": "",
                    "priority": "medium",
                    "type": "info_gather",
                    "related_task_id": None,
                    "asked_count": 0,
                    "last_asked_at": None,
                    "created_at": "2026-02-20T00:00:00",
                    "cooldown_hours": 24,
                    "answered": False,
                    "answer": None,
                    "answered_at": None,
                }
            ],
        }
        ok, msg = storage.save_questions(data)
        assert ok is True

        loaded = storage.load_questions()
        assert loaded["questions"][0]["id"] == "q_001"

    def test_notifications_round_trip(self, storage):
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "notif_001",
                    "message": "Reminder",
                    "scheduled_at": "2026-02-21T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "context": "",
                    "created_by": "worker",
                    "created_at": "2026-02-20T00:00:00",
                }
            ],
        }
        ok, msg = storage.save_notifications(data)
        assert ok is True

        loaded = storage.load_notifications()
        assert loaded["notifications"][0]["id"] == "notif_001"


# ---------------------------------------------------------------------------
# save_* with invalid data fails validation
# ---------------------------------------------------------------------------

class TestValidationFailures:
    """save_* with invalid data should return (False, error message)."""

    def test_save_tasks_invalid_status(self, storage):
        """Invalid status value should fail Pydantic validation."""
        data = {
            "version": "1.0",
            "tasks": [
                {
                    "id": "task_bad",
                    "title": "Bad task",
                    "status": "invalid_status",  # not in Literal
                    "priority": "medium",
                    "progress": {
                        "percentage": 0,
                        "last_update": "2026-02-20",
                        "note": "",
                    },
                    "created_at": "2026-02-20",
                    "updated_at": "2026-02-20",
                }
            ],
        }
        ok, msg = storage.save_tasks(data)
        assert ok is False
        assert "Validation error" in msg or "error" in msg.lower()

    def test_save_tasks_missing_required_field(self, storage):
        """Missing required 'id' should fail validation."""
        data = {
            "version": "1.0",
            "tasks": [
                {
                    # missing "id"
                    "title": "No ID task",
                    "progress": {"percentage": 0, "last_update": "2026-02-20"},
                    "created_at": "2026-02-20",
                    "updated_at": "2026-02-20",
                }
            ],
        }
        ok, msg = storage.save_tasks(data)
        assert ok is False

    def test_save_questions_invalid_type(self, storage):
        """Invalid question type should fail validation."""
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_bad",
                    "question": "Bad question",
                    "type": "nonexistent_type",  # not in Literal
                    "created_at": "2026-02-20",
                }
            ],
        }
        ok, msg = storage.save_questions(data)
        assert ok is False

    def test_save_notifications_invalid_priority(self, storage):
        """Invalid priority should fail validation."""
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "notif_bad",
                    "message": "Bad notif",
                    "scheduled_at": "2026-02-21",
                    "priority": "ultra_high",  # not in Literal
                    "created_at": "2026-02-20",
                }
            ],
        }
        ok, msg = storage.save_notifications(data)
        assert ok is False


# ---------------------------------------------------------------------------
# load_* with corrupted file returns default
# ---------------------------------------------------------------------------

class TestCorruptedFiles:
    """load_* should return defaults when files contain invalid JSON."""

    def test_load_tasks_corrupted_json(self, workspace, storage):
        (workspace / "dashboard" / "tasks.json").write_text("not valid json!!!")
        result = storage.load_tasks()
        assert result == {"version": "1.0", "tasks": []}

    def test_load_questions_corrupted_json(self, workspace, storage):
        (workspace / "dashboard" / "questions.json").write_text("{broken")
        result = storage.load_questions()
        assert result == {"version": "1.0", "questions": []}
