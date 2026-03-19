"""Unit tests for WorkerAgent task deadline → GCal sync."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock

from nanobot.dashboard.storage import JsonStorageBackend
from nanobot.dashboard.worker import WorkerAgent


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace with dashboard structure."""
    dashboard_path = tmp_path / "dashboard"
    dashboard_path.mkdir(parents=True)

    for fname, data in [
        ("tasks.json", {"version": "1.0", "tasks": []}),
        ("questions.json", {"version": "1.0", "questions": []}),
        ("notifications.json", {"version": "1.0", "notifications": []}),
    ]:
        (dashboard_path / fname).write_text(json.dumps(data), encoding="utf-8")

    knowledge_dir = dashboard_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "insights.json").write_text(
        json.dumps({"version": "1.0", "insights": []}), encoding="utf-8"
    )

    return tmp_path


@pytest.fixture
def backend(temp_workspace):
    return JsonStorageBackend(temp_workspace)


@pytest.fixture
def mock_gcal():
    client = Mock()
    client.create_event = Mock(return_value="gcal_new_001")
    client.update_event = Mock()
    client.delete_event = Mock()
    return client


def _write_tasks(workspace, tasks):
    path = workspace / "dashboard" / "tasks.json"
    path.write_text(json.dumps({"version": "1.0", "tasks": tasks}), encoding="utf-8")


def _read_tasks(workspace):
    path = workspace / "dashboard" / "tasks.json"
    return json.loads(path.read_text())


def _make_task(
    task_id="task_001",
    title="Test task",
    status="active",
    deadline="2026-04-01",
    recurring=None,
    gcal_event_id=None,
    gcal_sync_hash=None,
    context="",
    **kwargs,
):
    task = {
        "id": task_id,
        "title": title,
        "status": status,
        "deadline": deadline,
        "deadline_text": deadline,
        "context": context,
        "priority": "medium",
        "tags": [],
        "created_at": "2026-03-01T10:00:00",
        "updated_at": "2026-03-01T10:00:00",
        "completed_at": None,
        "progress": {"percentage": 0, "last_update": "2026-03-01T10:00:00", "note": ""},
        "estimation": {"hours": None, "complexity": "medium", "confidence": "medium"},
        "links": {"projects": [], "insights": [], "resources": []},
        "reflection": "",
        "gcal_event_id": gcal_event_id,
        "gcal_sync_hash": gcal_sync_hash,
    }
    if recurring is not None:
        task["recurring"] = recurring
    task.update(kwargs)
    return task


# ============================================================================
# Tests
# ============================================================================


class TestTaskGCalSync:
    """Tests for WorkerAgent._sync_tasks_gcal_impl()."""

    def test_active_task_with_deadline_creates_gcal(self, temp_workspace, backend, mock_gcal):
        """Active task with deadline → GCal event created."""
        _write_tasks(temp_workspace, [_make_task()])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.create_event.assert_called_once()
        call_kwargs = mock_gcal.create_event.call_args.kwargs
        assert call_kwargs["all_day_date"] == "2026-04-01"
        assert call_kwargs["summary"] == "Test task"

        data = _read_tasks(temp_workspace)
        task = data["tasks"][0]
        assert task["gcal_event_id"] == "gcal_new_001"
        assert task["gcal_sync_hash"] is not None

    def test_no_deadline_no_gcal(self, temp_workspace, backend, mock_gcal):
        """Task without deadline → no GCal event."""
        _write_tasks(temp_workspace, [_make_task(deadline=None)])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.create_event.assert_not_called()

    def test_empty_deadline_no_gcal(self, temp_workspace, backend, mock_gcal):
        """Task with empty string deadline → no GCal event."""
        _write_tasks(temp_workspace, [_make_task(deadline="")])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.create_event.assert_not_called()

    def test_completed_removes_gcal(self, temp_workspace, backend, mock_gcal):
        """Completed task with gcal_event_id → event deleted."""
        _write_tasks(
            temp_workspace,
            [_make_task(status="completed", gcal_event_id="gcal_old")],
        )

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.delete_event.assert_called_once_with(event_id="gcal_old")
        data = _read_tasks(temp_workspace)
        assert data["tasks"][0]["gcal_event_id"] is None
        assert data["tasks"][0]["gcal_sync_hash"] is None

    def test_cancelled_removes_gcal(self, temp_workspace, backend, mock_gcal):
        """Cancelled task with gcal_event_id → event deleted."""
        _write_tasks(
            temp_workspace,
            [_make_task(status="cancelled", gcal_event_id="gcal_cancel")],
        )

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.delete_event.assert_called_once_with(event_id="gcal_cancel")

    def test_archived_removes_gcal(self, temp_workspace, backend, mock_gcal):
        """Archived task with gcal_event_id → event deleted."""
        _write_tasks(
            temp_workspace,
            [_make_task(status="archived", gcal_event_id="gcal_arch")],
        )

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.delete_event.assert_called_once_with(event_id="gcal_arch")

    def test_deadline_change_updates_gcal(self, temp_workspace, backend, mock_gcal):
        """Deadline changed → hash mismatch → update_event called."""
        task = _make_task(gcal_event_id="gcal_existing", gcal_sync_hash="old_hash")
        _write_tasks(temp_workspace, [task])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.update_event.assert_called_once()
        mock_gcal.create_event.assert_not_called()
        call_kwargs = mock_gcal.update_event.call_args.kwargs
        assert call_kwargs["all_day_date"] == "2026-04-01"

    def test_title_change_updates_gcal(self, temp_workspace, backend, mock_gcal):
        """Title changed → hash mismatch → update_event called."""
        task = _make_task(title="New title", gcal_event_id="gcal_exist", gcal_sync_hash="old_hash")
        _write_tasks(temp_workspace, [task])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.update_event.assert_called_once()
        call_kwargs = mock_gcal.update_event.call_args.kwargs
        assert call_kwargs["summary"] == "New title"

    def test_hash_match_no_api_call(self, temp_workspace, backend, mock_gcal):
        """Matching hash → no API calls."""
        task = _make_task()
        # Compute correct hash
        sync_hash = WorkerAgent._compute_task_sync_hash(task)
        task["gcal_event_id"] = "gcal_synced"
        task["gcal_sync_hash"] = sync_hash
        _write_tasks(temp_workspace, [task])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.create_event.assert_not_called()
        mock_gcal.update_event.assert_not_called()
        mock_gcal.delete_event.assert_not_called()

    def test_gcal_create_failure_no_crash(self, temp_workspace, backend, mock_gcal):
        """GCal create failure → no crash, gcal_event_id stays None."""
        from nanobot.google.calendar import GoogleCalendarError

        mock_gcal.create_event.side_effect = GoogleCalendarError("API down")
        _write_tasks(temp_workspace, [_make_task()])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        data = _read_tasks(temp_workspace)
        assert data["tasks"][0]["gcal_event_id"] is None

    def test_gcal_update_404_clears_id(self, temp_workspace, backend, mock_gcal):
        """update_event returns 404 → ID/hash cleared for next cycle recreation."""
        from nanobot.google.calendar import GCalEventNotFound

        mock_gcal.update_event.side_effect = GCalEventNotFound("gone")
        task = _make_task(gcal_event_id="gcal_gone", gcal_sync_hash="old_hash")
        _write_tasks(temp_workspace, [task])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        data = _read_tasks(temp_workspace)
        assert data["tasks"][0]["gcal_event_id"] is None
        assert data["tasks"][0]["gcal_sync_hash"] is None

    @pytest.mark.asyncio
    async def test_no_gcal_client_skips(self, temp_workspace, backend):
        """No gcal_client → _sync_tasks_gcal is a no-op."""
        _write_tasks(temp_workspace, [_make_task()])

        worker = WorkerAgent(workspace=temp_workspace, storage_backend=backend)
        await worker._sync_tasks_gcal()

        data = _read_tasks(temp_workspace)
        assert data["tasks"][0]["gcal_event_id"] is None

    def test_recurring_task_skipped(self, temp_workspace, backend, mock_gcal):
        """Recurring task → GCal sync skipped (calendar noise prevention)."""
        recurring_config = {
            "enabled": True,
            "frequency": "daily",
            "days_of_week": [0, 1, 2, 3, 4, 5, 6],
            "streak_current": 0,
            "streak_best": 0,
            "total_completed": 0,
            "total_missed": 0,
        }
        _write_tasks(temp_workspace, [_make_task(recurring=recurring_config)])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.create_event.assert_not_called()

    def test_someday_with_deadline_synced(self, temp_workspace, backend, mock_gcal):
        """Someday task with deadline → GCal event created."""
        _write_tasks(temp_workspace, [_make_task(status="someday")])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.create_event.assert_called_once()

    def test_separate_load_save(self, temp_workspace, backend, mock_gcal):
        """GCal sync uses its own load/save cycle (independent of Phase 1)."""
        task = _make_task()
        _write_tasks(temp_workspace, [task])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        # Verify tasks were saved with gcal fields
        data = _read_tasks(temp_workspace)
        assert data["tasks"][0]["gcal_event_id"] == "gcal_new_001"

    def test_description_includes_context(self, temp_workspace, backend, mock_gcal):
        """GCal event description includes task context (truncated to 200 chars)."""
        long_context = "A" * 300
        _write_tasks(temp_workspace, [_make_task(context=long_context)])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        call_kwargs = mock_gcal.create_event.call_args.kwargs
        desc = call_kwargs.get("description", "")
        # context truncated to 200 + "\nTask: task_001"
        assert len(desc.split("\n")[0]) == 200
        assert "task_001" in desc

    def test_completed_without_gcal_no_op(self, temp_workspace, backend, mock_gcal):
        """Completed task without gcal_event_id → no delete call."""
        _write_tasks(temp_workspace, [_make_task(status="completed")])

        worker = WorkerAgent(
            workspace=temp_workspace, storage_backend=backend, gcal_client=mock_gcal
        )
        worker._sync_tasks_gcal_impl()

        mock_gcal.delete_event.assert_not_called()


class TestComputeTaskSyncHash:
    """Tests for WorkerAgent._compute_task_sync_hash()."""

    def test_deterministic(self):
        """Same input → same hash."""
        task = {"deadline": "2026-04-01", "title": "Test", "context": ""}
        h1 = WorkerAgent._compute_task_sync_hash(task)
        h2 = WorkerAgent._compute_task_sync_hash(task)
        assert h1 == h2

    def test_field_sensitivity(self):
        """Changing deadline, title, or context changes the hash."""
        base = {"deadline": "2026-04-01", "title": "Test", "context": "ctx"}
        base_hash = WorkerAgent._compute_task_sync_hash(base)

        for field, new_val in [
            ("deadline", "2026-04-02"),
            ("title", "Changed"),
            ("context", "new ctx"),
        ]:
            modified = {**base, field: new_val}
            assert WorkerAgent._compute_task_sync_hash(modified) != base_hash, f"{field}"

    def test_none_values_safe(self):
        """None/missing values don't cause errors."""
        h = WorkerAgent._compute_task_sync_hash({})
        assert isinstance(h, str) and len(h) == 32


class TestBuildTaskDescription:
    """Tests for WorkerAgent._build_task_description()."""

    def test_context_and_id(self):
        desc = WorkerAgent._build_task_description({"context": "my ctx", "id": "task_001"})
        assert "my ctx" in desc
        assert "task_001" in desc

    def test_no_context(self):
        desc = WorkerAgent._build_task_description({"id": "task_001"})
        assert desc == "Task: task_001"

    def test_empty(self):
        assert WorkerAgent._build_task_description({}) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
