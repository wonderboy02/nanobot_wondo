#!/usr/bin/env python3
"""
Dashboard Test Script (Python version)
Comprehensive testing of dashboard functionality
"""

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nanobot.dashboard.manager import DashboardManager
from nanobot.dashboard.schema import (
    validate_questions_file,
    validate_tasks_file,
)
from nanobot.dashboard.storage import JsonStorageBackend
from nanobot.dashboard.worker import WorkerAgent


class TestRunner:
    """Simple test runner."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def test(self, name):
        """Decorator for test functions."""

        def decorator(func):
            self.tests.append((name, func))
            return func

        return decorator

    def run(self):
        """Run all tests."""
        print("🧪 Dashboard Test Suite")
        print("=" * 60)
        print()

        for name, func in self.tests:
            try:
                func()
                self.passed += 1
                print(f"✓ {name}")
            except AssertionError as e:
                self.failed += 1
                print(f"✗ {name}: {e}")
            except Exception as e:
                self.failed += 1
                print(f"✗ {name}: Unexpected error: {e}")

        print()
        print("=" * 60)
        print("Test Summary")
        print("=" * 60)
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")

        if self.failed > 0:
            print("\n❌ Some tests failed")
            sys.exit(1)
        else:
            print("\n✨ All tests passed!")
            sys.exit(0)


# Create test runner
runner = TestRunner()


@runner.test("Create test workspace")
def test_create_workspace():
    """Test workspace creation."""
    global test_workspace, dashboard_path, manager

    test_workspace = Path(tempfile.mkdtemp(prefix="nanobot_test_"))
    dashboard_path = test_workspace / "dashboard"
    dashboard_path.mkdir()

    # Create structure
    (dashboard_path / "tasks.json").write_text(json.dumps({"version": "1.0", "tasks": []}))
    (dashboard_path / "questions.json").write_text(json.dumps({"version": "1.0", "questions": []}))
    (dashboard_path / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []})
    )

    knowledge_dir = dashboard_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "insights.json").write_text(json.dumps({"version": "1.0", "insights": []}))

    manager = DashboardManager(dashboard_path)
    assert dashboard_path.exists()


@runner.test("Load empty dashboard")
def test_load_empty():
    """Test loading empty dashboard."""
    dashboard = manager.load()
    assert "tasks" in dashboard
    assert "questions" in dashboard
    assert len(dashboard["tasks"]) == 0


@runner.test("Add and save task")
def test_add_task():
    """Test adding a task."""
    dashboard = manager.load()

    task = {
        "id": "task_001",
        "title": "Test Task",
        "status": "active",
        "progress": {"percentage": 0, "last_update": datetime.now().isoformat(), "note": ""},
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    dashboard["tasks"].append(task)
    manager.save(dashboard)

    # Reload and verify
    dashboard2 = manager.load()
    assert len(dashboard2["tasks"]) == 1
    assert dashboard2["tasks"][0]["title"] == "Test Task"


@runner.test("Schema validation - tasks")
def test_schema_tasks():
    """Test tasks schema validation."""
    dashboard = manager.load()
    tasks_data = {"version": "1.0", "tasks": dashboard["tasks"]}
    validate_tasks_file(tasks_data)  # Should not raise


@runner.test("Schema validation - questions")
def test_schema_questions():
    """Test questions schema validation."""
    dashboard = manager.load()
    questions_data = {"version": "1.0", "questions": dashboard["questions"]}
    validate_questions_file(questions_data)  # Should not raise


@runner.test("Worker - Maintenance runs without LLM")
async def test_worker_maintenance():
    """Test worker runs deterministic maintenance without LLM provider."""
    now = datetime.now()

    dashboard = manager.load()
    dashboard["tasks"] = [
        {
            "id": "task_002",
            "title": "Active Task",
            "status": "active",
            "deadline": (now + timedelta(days=2)).isoformat(),
            "progress": {
                "percentage": 50,
                "last_update": now.isoformat(),
                "note": "",
            },
            "priority": "medium",
            "created_at": (now - timedelta(days=1)).isoformat(),
            "updated_at": now.isoformat(),
        }
    ]
    manager.save(dashboard)

    # Run worker (no LLM → maintenance only)
    backend = JsonStorageBackend(test_workspace)
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    # Should not crash, task stays active
    dashboard2 = manager.load()
    assert len(dashboard2["tasks"]) == 1
    assert dashboard2["tasks"][0]["status"] == "active"


@runner.test("Worker - Archive completed task")
async def test_worker_archive():
    """Test worker archives completed tasks (status → archived)."""
    now = datetime.now()

    dashboard = manager.load()
    dashboard["tasks"] = [
        {
            "id": "task_003",
            "title": "Completed Task",
            "status": "completed",
            "completed_at": now.isoformat(),
            "progress": {"percentage": 100, "last_update": now.isoformat(), "note": "Done"},
            "created_at": (now - timedelta(days=1)).isoformat(),
            "updated_at": now.isoformat(),
        }
    ]
    manager.save(dashboard)

    # Run worker
    backend = JsonStorageBackend(test_workspace)
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    # Task should be archived (not removed)
    dashboard2 = manager.load()
    assert len(dashboard2["tasks"]) == 1, "Task should still exist in tasks.json"
    assert dashboard2["tasks"][0]["status"] == "archived", "Task should be archived"


@runner.test("Load example data")
def test_example_data():
    """Test loading example dashboard data."""
    example_file = Path(__file__).parent.parent / "tests" / "fixtures" / "example_dashboard.json"

    if not example_file.exists():
        print("⚠️  Example file not found, skipping")
        return

    with open(example_file) as f:
        example = json.load(f)

    # Validate example data
    validate_tasks_file({"version": "1.0", "tasks": example["tasks"]})
    validate_questions_file({"version": "1.0", "questions": example["questions"]})

    print(f"   Example has {len(example['tasks'])} tasks, {len(example['questions'])} questions")


@runner.test("Cleanup test workspace")
def test_cleanup():
    """Cleanup test workspace."""
    import shutil

    if test_workspace.exists():
        shutil.rmtree(test_workspace)
    assert not test_workspace.exists()


if __name__ == "__main__":
    # Run async tests with asyncio
    import asyncio

    # Patch async tests
    original_tests = runner.tests.copy()
    runner.tests = []

    for name, func in original_tests:
        if asyncio.iscoroutinefunction(func):
            # Wrap async test
            def make_sync_test(async_func):
                def sync_test():
                    asyncio.run(async_func())

                return sync_test

            runner.tests.append((name, make_sync_test(func)))
        else:
            runner.tests.append((name, func))

    runner.run()
