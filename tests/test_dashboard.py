"""Tests for Dashboard functionality."""

import json
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def test_workspace(tmp_path):
    """Create a test workspace with dashboard structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create dashboard directory
    dashboard_dir = workspace / "dashboard"
    dashboard_dir.mkdir()

    # Create empty JSON files
    (dashboard_dir / "tasks.json").write_text(json.dumps({"version": "1.0", "tasks": []}))
    (dashboard_dir / "questions.json").write_text(json.dumps({"version": "1.0", "questions": []}))
    (dashboard_dir / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []})
    )

    # Create knowledge directory
    knowledge_dir = dashboard_dir / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "insights.json").write_text(json.dumps({"version": "1.0", "insights": []}))

    return workspace


def test_dashboard_manager_load(test_workspace):
    """Test DashboardManager can load empty dashboard."""
    from nanobot.dashboard.manager import DashboardManager

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    dashboard = manager.load()

    assert "tasks" in dashboard
    assert "questions" in dashboard
    assert "notifications" in dashboard
    assert "knowledge" in dashboard
    assert isinstance(dashboard["tasks"], list)
    assert len(dashboard["tasks"]) == 0


def test_dashboard_manager_save(test_workspace):
    """Test DashboardManager can save dashboard."""
    from nanobot.dashboard.manager import DashboardManager

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    # Add a task
    dashboard = manager.load()
    dashboard["tasks"].append(
        {
            "id": "task_001",
            "title": "Test Task",
            "status": "active",
            "created_at": datetime.now().isoformat(),
        }
    )

    # Save
    manager.save(dashboard)

    # Reload and verify
    dashboard2 = manager.load()
    assert len(dashboard2["tasks"]) == 1
    assert dashboard2["tasks"][0]["title"] == "Test Task"


@pytest.mark.asyncio
async def test_worker_archive_completed_tasks(test_workspace):
    """Test Worker archives completed tasks via StorageBackend."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    # Create a completed task
    now = datetime.now()
    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_001",
            "title": "Completed Task",
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

    # Run worker (maintenance only, no LLM)
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    # Check if task is archived
    tasks_data2 = backend.load_tasks()
    assert len(tasks_data2["tasks"]) == 1
    assert tasks_data2["tasks"][0]["status"] == "archived"
    assert tasks_data2["tasks"][0]["title"] == "Completed Task"


@pytest.mark.asyncio
async def test_worker_archive_cancelled_tasks(test_workspace):
    """Test Worker archives cancelled tasks."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    now = datetime.now()
    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_cancelled",
            "title": "Cancelled Task",
            "status": "cancelled",
            "created_at": (now - timedelta(days=1)).isoformat(),
            "updated_at": now.isoformat(),
            "progress": {
                "percentage": 30,
                "last_update": now.isoformat(),
                "note": "",
            },
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    tasks_data2 = backend.load_tasks()
    assert len(tasks_data2["tasks"]) == 1
    assert tasks_data2["tasks"][0]["status"] == "archived"
    # Cancelled tasks preserve original progress (not forced to 100%)
    assert tasks_data2["tasks"][0]["progress"]["percentage"] == 30


@pytest.mark.asyncio
async def test_worker_reevaluate_active_status(test_workspace):
    """Test Worker re-evaluates active/someday status."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    # Create a task with far deadline and old update (should become someday)
    now = datetime.now()
    far_deadline = now + timedelta(days=30)
    old_update = now - timedelta(days=10)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_001",
            "title": "Far Future Task",
            "status": "active",
            "deadline": far_deadline.isoformat(),
            "priority": "low",
            "progress": {
                "percentage": 0,
                "last_update": old_update.isoformat(),
                "note": "",
            },
            "created_at": old_update.isoformat(),
            "updated_at": old_update.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    tasks_data2 = backend.load_tasks()
    assert tasks_data2["tasks"][0]["status"] == "someday"


@pytest.mark.asyncio
async def test_worker_cleanup_answered_questions(test_workspace):
    """Test Worker cleans up answered questions."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    now = datetime.now()
    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_001",
            "question": "Answered question",
            "answered": True,
            "created_at": now.isoformat(),
        },
        {
            "id": "q_002",
            "question": "Unanswered question",
            "answered": False,
            "created_at": now.isoformat(),
        },
        {
            "id": "q_003",
            "question": "Old unanswered question",
            "answered": False,
            "created_at": (now - timedelta(days=20)).isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    questions_data2 = backend.load_questions()
    # Only the recent unanswered question should remain
    assert len(questions_data2["questions"]) == 1
    assert questions_data2["questions"][0]["id"] == "q_002"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
