"""Test Worker deterministic maintenance logic.

Tests the Phase 1 maintenance methods that always run:
- _archive_completed_tasks
- _reevaluate_active_status
- _cleanup_answered_questions
"""

import json
from datetime import datetime, timedelta

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


# ============================================================================
# Archive Tests
# ============================================================================


@pytest.mark.asyncio
async def test_archive_completed_task(test_workspace):
    """Completed task should be archived with progress=100%."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_001",
            "title": "Done Task",
            "status": "completed",
            "completed_at": now.isoformat(),
            "created_at": (now - timedelta(days=1)).isoformat(),
            "updated_at": now.isoformat(),
            "progress": {
                "percentage": 100,
                "last_update": now.isoformat(),
                "note": "Done",
            },
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "archived"
    assert result["tasks"][0]["progress"]["percentage"] == 100


@pytest.mark.asyncio
async def test_archive_cancelled_task_preserves_progress(test_workspace):
    """Cancelled task should be archived but keep original progress."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_002",
            "title": "Cancelled Task",
            "status": "cancelled",
            "created_at": (now - timedelta(days=1)).isoformat(),
            "updated_at": now.isoformat(),
            "progress": {
                "percentage": 40,
                "last_update": now.isoformat(),
            },
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "archived"
    assert result["tasks"][0]["progress"]["percentage"] == 40


@pytest.mark.asyncio
async def test_archive_does_not_touch_active_tasks(test_workspace):
    """Active tasks should NOT be archived."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_003",
            "title": "Active Task",
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "progress": {
                "percentage": 50,
                "last_update": now.isoformat(),
            },
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"


# ============================================================================
# Reevaluate Status Tests
# ============================================================================


@pytest.mark.asyncio
async def test_reevaluate_far_deadline_low_priority_becomes_someday(test_workspace):
    """Task with far deadline, low priority, no progress → someday."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()
    old_update = now - timedelta(days=10)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_far",
            "title": "Far Future Task",
            "status": "active",
            "deadline": (now + timedelta(days=30)).isoformat(),
            "priority": "low",
            "progress": {
                "percentage": 0,
                "last_update": old_update.isoformat(),
            },
            "created_at": old_update.isoformat(),
            "updated_at": old_update.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "someday"


@pytest.mark.asyncio
async def test_reevaluate_close_deadline_becomes_active(test_workspace):
    """Task with close deadline → active (even if someday)."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_soon",
            "title": "Due Soon Task",
            "status": "someday",
            "deadline": (now + timedelta(days=3)).isoformat(),
            "priority": "low",
            "progress": {
                "percentage": 0,
                "last_update": (now - timedelta(days=10)).isoformat(),
            },
            "created_at": (now - timedelta(days=10)).isoformat(),
            "updated_at": (now - timedelta(days=10)).isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_reevaluate_high_priority_stays_active(test_workspace):
    """High priority task stays active regardless of deadline."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()
    old_update = now - timedelta(days=10)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_high",
            "title": "High Priority Task",
            "status": "active",
            "priority": "high",
            "progress": {
                "percentage": 0,
                "last_update": old_update.isoformat(),
            },
            "created_at": old_update.isoformat(),
            "updated_at": old_update.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_reevaluate_with_progress_stays_active(test_workspace):
    """Task with any progress stays active."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()
    old_update = now - timedelta(days=10)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_prog",
            "title": "In Progress Task",
            "status": "active",
            "priority": "low",
            "progress": {
                "percentage": 20,
                "last_update": old_update.isoformat(),
            },
            "created_at": old_update.isoformat(),
            "updated_at": old_update.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_reevaluate_skips_archived(test_workspace):
    """Archived tasks should not be re-evaluated."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_archived",
            "title": "Archived Task",
            "status": "archived",
            "priority": "low",
            "progress": {
                "percentage": 100,
                "last_update": now.isoformat(),
            },
            "created_at": (now - timedelta(days=30)).isoformat(),
            "updated_at": now.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "archived"


# ============================================================================
# Question Cleanup Tests
# ============================================================================


@pytest.mark.asyncio
async def test_cleanup_removes_answered_questions(test_workspace):
    """Answered questions should be removed."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_answered",
            "question": "Done?",
            "answered": True,
            "created_at": now.isoformat(),
        },
        {
            "id": "q_open",
            "question": "Still open?",
            "answered": False,
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_questions()
    assert len(result["questions"]) == 1
    assert result["questions"][0]["id"] == "q_open"


@pytest.mark.asyncio
async def test_cleanup_removes_old_questions(test_workspace):
    """Questions older than 14 days should be removed."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_old",
            "question": "Ancient question?",
            "answered": False,
            "created_at": (now - timedelta(days=20)).isoformat(),
        },
        {
            "id": "q_recent",
            "question": "Recent question?",
            "answered": False,
            "created_at": (now - timedelta(days=5)).isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_questions()
    assert len(result["questions"]) == 1
    assert result["questions"][0]["id"] == "q_recent"


@pytest.mark.asyncio
async def test_cleanup_no_change_when_all_valid(test_workspace):
    """No changes when all questions are valid."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_valid",
            "question": "Valid question?",
            "answered": False,
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_questions()
    assert len(result["questions"]) == 1


# ============================================================================
# Combined Maintenance Tests
# ============================================================================


@pytest.mark.asyncio
async def test_maintenance_runs_without_llm(test_workspace):
    """Worker without LLM should still run maintenance."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    # Set up tasks and questions
    tasks_data = backend.load_tasks()
    tasks_data["tasks"] = [
        {
            "id": "task_done",
            "title": "Done",
            "status": "completed",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "progress": {"percentage": 100, "last_update": now.isoformat()},
        },
        {
            "id": "task_active",
            "title": "Active",
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "progress": {"percentage": 50, "last_update": now.isoformat()},
        },
    ]
    backend.save_tasks(tasks_data)

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_done",
            "question": "Answered",
            "answered": True,
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    # No provider/model → maintenance only
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    # Verify maintenance ran
    tasks_result = backend.load_tasks()
    assert tasks_result["tasks"][0]["status"] == "archived"
    assert tasks_result["tasks"][1]["status"] == "active"

    questions_result = backend.load_questions()
    assert len(questions_result["questions"]) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
