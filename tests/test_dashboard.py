"""Tests for Dashboard functionality."""

import asyncio
import json
from pathlib import Path
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
    (dashboard_dir / "notifications.json").write_text(json.dumps({"version": "1.0", "notifications": []}))

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
    dashboard["tasks"].append({
        "id": "task_001",
        "title": "Test Task",
        "status": "active",
        "created_at": datetime.now().isoformat()
    })

    # Save
    manager.save(dashboard)

    # Reload and verify
    dashboard2 = manager.load()
    assert len(dashboard2["tasks"]) == 1
    assert dashboard2["tasks"][0]["title"] == "Test Task"


@pytest.mark.asyncio
async def test_worker_check_task_progress(test_workspace):
    """Test Worker checks task progress and generates questions."""
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    # Create a task that's behind schedule
    # last_update must be < 48h ago to avoid stale check (Case 4)
    now = datetime.now()
    deadline = now + timedelta(days=3)
    created = now - timedelta(days=2)  # Created 2 days ago, deadline in 3 days
    recent_update = now - timedelta(hours=12)  # Updated 12h ago (not stale)

    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_001",
        "title": "Test Task",
        "status": "active",
        "deadline": deadline.isoformat(),
        "progress": {
            "percentage": 0,  # Not started
            "last_update": recent_update.isoformat(),
            "note": "",
            "blocked": False
        },
        "priority": "medium",
        "created_at": created.isoformat(),
        "updated_at": recent_update.isoformat()
    })
    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    # Check if question was added (Case 1: not started, time_progress_ratio > 0.2)
    dashboard2 = manager.load()
    assert len(dashboard2["questions"]) > 0
    assert "시작했어" in dashboard2["questions"][0]["question"]


@pytest.mark.asyncio
async def test_worker_archive_completed_tasks(test_workspace):
    """Test Worker archives completed tasks."""
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    # Create a completed task
    now = datetime.now()
    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_001",
        "title": "Completed Task",
        "status": "completed",
        "completed_at": now.isoformat(),
        "created_at": (now - timedelta(days=1)).isoformat(),
        "updated_at": now.isoformat(),
        "progress": {
            "percentage": 100,
            "last_update": now.isoformat(),
            "note": "Done"
        }
    })
    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    # Check if task is archived (stays in tasks list with archived status)
    dashboard2 = manager.load()
    assert len(dashboard2["tasks"]) == 1  # Still in tasks
    assert dashboard2["tasks"][0]["status"] == "archived"
    assert dashboard2["tasks"][0]["title"] == "Completed Task"


@pytest.mark.asyncio
async def test_worker_archive_cancelled_tasks(test_workspace):
    """Test Worker archives cancelled tasks."""
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    now = datetime.now()
    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_cancelled",
        "title": "Cancelled Task",
        "status": "cancelled",
        "created_at": (now - timedelta(days=1)).isoformat(),
        "updated_at": now.isoformat(),
        "progress": {
            "percentage": 30,
            "last_update": now.isoformat(),
            "note": ""
        }
    })
    manager.save(dashboard)

    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    dashboard2 = manager.load()
    assert len(dashboard2["tasks"]) == 1
    assert dashboard2["tasks"][0]["status"] == "archived"
    # Cancelled tasks preserve original progress (not forced to 100%)
    assert dashboard2["tasks"][0]["progress"]["percentage"] == 30


def test_worker_reevaluate_active_status(test_workspace):
    """Test Worker re-evaluates active/someday status."""
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    # Create a task with far deadline and old update (should be someday)
    now = datetime.now()
    far_deadline = now + timedelta(days=30)
    old_update = now - timedelta(days=10)  # Last update 10 days ago (> 7 days threshold)

    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_001",
        "title": "Far Future Task",
        "status": "active",  # Currently active
        "deadline": far_deadline.isoformat(),
        "priority": "low",
        "progress": {
            "percentage": 0,
            "last_update": old_update.isoformat(),
            "note": ""
        },
        "created_at": old_update.isoformat(),
        "updated_at": old_update.isoformat()
    })
    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    asyncio.run(worker.run_cycle())

    # Check if status changed to someday
    dashboard2 = manager.load()
    assert dashboard2["tasks"][0]["status"] == "someday"


def test_question_cooldown(test_workspace):
    """Test that questions respect cooldown period."""
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    # Create a task
    now = datetime.now()
    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_001",
        "title": "Test Task",
        "status": "active",
        "deadline": (now + timedelta(days=2)).isoformat(),
        "progress": {
            "percentage": 0,
            "last_update": now.isoformat(),
            "note": ""
        },
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    })

    # Add a question that was just asked
    dashboard["questions"].append({
        "id": "q_001",
        "question": "Test question",
        "type": "start_check",
        "related_task_id": "task_001",
        "priority": "medium",
        "asked_count": 1,
        "last_asked_at": now.isoformat(),  # Just asked
        "cooldown_hours": 24,
        "created_at": now.isoformat(),
        "answered": False
    })
    manager.save(dashboard)

    # Run worker (should not add duplicate question due to cooldown)
    worker = WorkerAgent(dashboard_path)
    asyncio.run(worker.run_cycle())

    # Check that no duplicate question was added
    dashboard2 = manager.load()
    assert len(dashboard2["questions"]) == 1  # Still just 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
