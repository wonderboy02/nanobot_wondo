"""Test Worker bootstrap logic for manually-added items.

Tests the _bootstrap_new_items() method that assigns IDs and timestamps
to items created via Notion UI (which lack NanobotID).

NOTE: Initial test data is written directly to JSON files (bypassing Pydantic
validation) because bootstrap items simulate Notion-loaded data that hasn't
been validated yet. This mirrors the real flow where mapper returns items
with empty IDs before bootstrap fills them in.
"""

import json
from datetime import datetime
from unittest.mock import patch

import pytest


@pytest.fixture
def test_workspace(tmp_path):
    """Create test workspace with dashboard structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    dashboard_dir = workspace / "dashboard"
    dashboard_dir.mkdir()

    (dashboard_dir / "tasks.json").write_text(json.dumps({"version": "1.0", "tasks": []}, indent=2))
    (dashboard_dir / "questions.json").write_text(
        json.dumps({"version": "1.0", "questions": []}, indent=2)
    )
    (dashboard_dir / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []}, indent=2)
    )

    knowledge_dir = dashboard_dir / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "insights.json").write_text(
        json.dumps({"version": "1.0", "insights": []}, indent=2)
    )

    return workspace


def _write_json(workspace, filename, data):
    """Write JSON directly to dashboard file (bypasses Pydantic validation)."""
    path = workspace / "dashboard" / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================================
# Bootstrap Tests
# ============================================================================


@pytest.mark.asyncio
async def test_bootstrap_empty_id_task(test_workspace):
    """Task with empty ID should get task_ prefix ID + timestamps."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    # Write directly (simulates Notion mapper output with empty NanobotID)
    _write_json(
        test_workspace,
        "tasks.json",
        {
            "version": "1.0",
            "tasks": [
                {
                    "id": "",
                    "title": "Manually Created Task",
                    "status": "active",
                    "priority": "medium",
                    "progress": {"percentage": 0, "last_update": ""},
                    "created_at": "",
                    "updated_at": "",
                }
            ],
        },
    )

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    worker._bootstrap_new_items()

    result = backend.load_tasks()
    task = result["tasks"][0]
    assert task["id"].startswith("task_")
    assert len(task["id"]) == 13  # "task_" + 8 hex chars
    assert task["created_at"]  # Non-empty
    assert task["updated_at"]  # Non-empty
    assert task["progress"]["last_update"]  # Non-empty


@pytest.mark.asyncio
async def test_bootstrap_empty_id_question(test_workspace):
    """Question with empty ID should get q_ prefix ID + created_at."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    _write_json(
        test_workspace,
        "questions.json",
        {
            "version": "1.0",
            "questions": [
                {
                    "id": "",
                    "question": "What is the deadline?",
                    "answered": False,
                    "created_at": "",
                }
            ],
        },
    )

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    worker._bootstrap_new_items()

    result = backend.load_questions()
    q = result["questions"][0]
    assert q["id"].startswith("q_")
    assert len(q["id"]) == 10  # "q_" + 8 hex chars
    assert q["created_at"]  # Non-empty (overwritten by bootstrap)


@pytest.mark.asyncio
async def test_bootstrap_empty_id_notification(test_workspace):
    """Notification with empty ID should get n_ prefix ID + created_at + created_by=user."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    _write_json(
        test_workspace,
        "notifications.json",
        {
            "version": "1.0",
            "notifications": [
                {
                    "id": "",
                    "message": "Remind me about X",
                    "type": "reminder",
                    "status": "pending",
                    "scheduled_at": datetime.now().isoformat(),
                    "created_at": "",
                }
            ],
        },
    )

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    worker._bootstrap_new_items()

    result = backend.load_notifications()
    n = result["notifications"][0]
    assert n["id"].startswith("n_")
    assert len(n["id"]) == 10  # "n_" + 8 hex chars
    assert n["created_at"]  # Non-empty
    assert n["created_by"] == "user"


@pytest.mark.asyncio
async def test_bootstrap_skips_existing_id(test_workspace):
    """Items with existing IDs should not be modified."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now().isoformat()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_existing",
            "title": "Existing Task",
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "progress": {"percentage": 50, "last_update": now},
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    worker._bootstrap_new_items()

    result = backend.load_tasks()
    task = result["tasks"][0]
    assert task["id"] == "task_existing"
    assert task["created_at"] == now


@pytest.mark.asyncio
async def test_bootstrap_save_and_reload(test_workspace):
    """Bootstrapped ID should persist after save and reload."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    _write_json(
        test_workspace,
        "tasks.json",
        {
            "version": "1.0",
            "tasks": [
                {
                    "id": "",
                    "title": "Persist Test",
                    "status": "active",
                    "priority": "medium",
                    "progress": {"percentage": 0, "last_update": ""},
                    "created_at": "",
                    "updated_at": "",
                }
            ],
        },
    )

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    worker._bootstrap_new_items()

    # Reload from disk
    result = backend.load_tasks()
    task_id = result["tasks"][0]["id"]
    assert task_id.startswith("task_")

    # Second bootstrap should not change anything
    worker._bootstrap_new_items()
    result2 = backend.load_tasks()
    assert result2["tasks"][0]["id"] == task_id


@pytest.mark.asyncio
async def test_bootstrap_no_save_when_nothing_to_bootstrap(test_workspace):
    """Save should not be called when no items need bootstrapping."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now().isoformat()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_ok",
            "title": "OK Task",
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "progress": {"percentage": 0, "last_update": now},
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    with patch.object(backend, "save_tasks", wraps=backend.save_tasks) as mock_save:
        worker._bootstrap_new_items()
        mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_error_isolation(test_workspace):
    """Failure in one entity should not block others."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    # Add empty-ID question (write directly to bypass validation)
    _write_json(
        test_workspace,
        "questions.json",
        {
            "version": "1.0",
            "questions": [
                {
                    "id": "",
                    "question": "Test?",
                    "answered": False,
                    "created_at": "",
                }
            ],
        },
    )

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    # Make tasks loader fail
    with patch.object(backend, "load_tasks", side_effect=Exception("tasks broken")):
        worker._bootstrap_new_items()

    # Questions should still be bootstrapped despite tasks failure
    result = backend.load_questions()
    assert result["questions"][0]["id"].startswith("q_")


@pytest.mark.asyncio
async def test_bootstrap_in_full_cycle(test_workspace):
    """Bootstrap should run as part of run_cycle()."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    _write_json(
        test_workspace,
        "tasks.json",
        {
            "version": "1.0",
            "tasks": [
                {
                    "id": "",
                    "title": "Cycle Bootstrap Test",
                    "status": "active",
                    "priority": "medium",
                    "progress": {"percentage": 0, "last_update": ""},
                    "created_at": "",
                    "updated_at": "",
                }
            ],
        },
    )

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["id"].startswith("task_")
    assert result["tasks"][0]["created_at"]


@pytest.mark.asyncio
async def test_bootstrap_calls_register_id_mapping_before_save(test_workspace):
    """register_id_mapping must be called BEFORE save (Notion needs it for update_page).

    NOTE: Uses JsonStorageBackend (where register/unregister are no-ops).
    Verifies Worker's call ordering via spies. Does NOT exercise the real
    Notion update_page/create_page routing — that requires a
    NotionStorageBackend integration test with mocked API calls.
    """
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    _write_json(
        test_workspace,
        "tasks.json",
        {
            "version": "1.0",
            "tasks": [
                {
                    "id": "",
                    "title": "Notion Task",
                    "status": "active",
                    "priority": "medium",
                    "progress": {"percentage": 0, "last_update": ""},
                    "created_at": "",
                    "updated_at": "",
                    "_notion_page_id": "page-abc-123",
                }
            ],
        },
    )

    # Track call ordering: register must happen before save
    call_order = []
    original_save = backend.save_tasks
    register_args = []

    def register_spy(entity_type, nanobot_id, page_id):
        call_order.append("register")
        register_args.append((entity_type, nanobot_id, page_id))

    def save_spy(data):
        call_order.append("save")
        return original_save(data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    with (
        patch.object(backend, "register_id_mapping", side_effect=register_spy),
        patch.object(backend, "save_tasks", side_effect=save_spy),
    ):
        worker._bootstrap_new_items()

    # register was called BEFORE save
    assert call_order == ["register", "save"]
    assert len(register_args) == 1
    assert register_args[0][0] == "tasks"
    assert register_args[0][1].startswith("task_")
    assert register_args[0][2] == "page-abc-123"


@pytest.mark.asyncio
async def test_bootstrap_calls_unregister_on_save_failure(test_workspace):
    """unregister_id_mapping should be called when save returns failure."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    _write_json(
        test_workspace,
        "tasks.json",
        {
            "version": "1.0",
            "tasks": [
                {
                    "id": "",
                    "title": "Fail Save Task",
                    "status": "active",
                    "priority": "medium",
                    "progress": {"percentage": 0, "last_update": ""},
                    "created_at": "",
                    "updated_at": "",
                    "_notion_page_id": "page-xyz-789",
                }
            ],
        },
    )

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    unregister_calls = []

    def unregister_spy(entity_type, nanobot_id):
        unregister_calls.append((entity_type, nanobot_id))

    with (
        patch.object(backend, "save_tasks", return_value=(False, "disk full")),
        patch.object(backend, "unregister_id_mapping", side_effect=unregister_spy),
    ):
        worker._bootstrap_new_items()

    # unregister was called for rollback
    assert len(unregister_calls) == 1
    assert unregister_calls[0][0] == "tasks"
    assert unregister_calls[0][1].startswith("task_")


@pytest.mark.asyncio
async def test_bootstrap_calls_unregister_on_save_exception(test_workspace):
    """unregister_id_mapping should be called when save raises an exception."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    _write_json(
        test_workspace,
        "tasks.json",
        {
            "version": "1.0",
            "tasks": [
                {
                    "id": "",
                    "title": "Exception Save Task",
                    "status": "active",
                    "priority": "medium",
                    "progress": {"percentage": 0, "last_update": ""},
                    "created_at": "",
                    "updated_at": "",
                    "_notion_page_id": "page-exc-456",
                }
            ],
        },
    )

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    unregister_calls = []

    def unregister_spy(entity_type, nanobot_id):
        unregister_calls.append((entity_type, nanobot_id))

    with (
        patch.object(backend, "save_tasks", side_effect=RuntimeError("connection lost")),
        patch.object(backend, "unregister_id_mapping", side_effect=unregister_spy),
    ):
        worker._bootstrap_new_items()

    # unregister was called for rollback despite exception
    assert len(unregister_calls) == 1
    assert unregister_calls[0][0] == "tasks"
    assert unregister_calls[0][1].startswith("task_")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
