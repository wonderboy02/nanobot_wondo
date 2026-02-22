"""E2E Test: Worker + Agent Integration

Worker와 Agent가 함께 동작하는 통합 시나리오를 검증합니다.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config
from nanobot.dashboard.manager import DashboardManager
from nanobot.dashboard.storage import JsonStorageBackend
from nanobot.dashboard.worker import WorkerAgent
from nanobot.providers.litellm_provider import LiteLLMProvider


@pytest.fixture
def integration_setup(tmp_path):
    """Setup Agent + Worker with clean dashboard."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    dashboard_path = workspace / "dashboard"
    dashboard_path.mkdir()

    (dashboard_path / "tasks.json").write_text(
        json.dumps({"version": "1.0", "tasks": []}, indent=2), encoding="utf-8"
    )
    (dashboard_path / "questions.json").write_text(
        json.dumps({"version": "1.0", "questions": []}, indent=2), encoding="utf-8"
    )
    (dashboard_path / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []}, indent=2), encoding="utf-8"
    )

    knowledge_dir = dashboard_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "insights.json").write_text(
        json.dumps({"version": "1.0", "insights": []}, indent=2), encoding="utf-8"
    )

    (workspace / "DASHBOARD.md").write_text(
        "# Dashboard Management\nYou are a Dashboard Sync Manager.",
        encoding="utf-8",
    )

    memory_dir = workspace / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("", encoding="utf-8")

    config = load_config()
    if config.providers.gemini.api_key:
        os.environ["GEMINI_API_KEY"] = config.providers.gemini.api_key

    bus = MessageBus()
    provider = LiteLLMProvider(api_key="dummy", api_base=None)

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=config.agents.defaults.model,
        max_iterations=10,
    )

    backend = JsonStorageBackend(workspace)
    worker = WorkerAgent(workspace=workspace, storage_backend=backend)
    manager = DashboardManager(dashboard_path)

    return {
        "agent": agent_loop,
        "worker": worker,
        "manager": manager,
        "backend": backend,
        "workspace": workspace,
        "dashboard": dashboard_path,
    }


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_integration_01_agent_add_worker_ask(integration_setup):
    """Integration 1: Agent adds task → Worker runs maintenance

    Flow:
      1. Agent adds task (with deadline)
      2. Worker runs maintenance (archive, reevaluate)
      3. Verify task state
    """
    setup = integration_setup
    agent = setup["agent"]
    manager = setup["manager"]

    # Step 1: Agent adds task
    message = "3일 후까지 중요한 프로젝트 완료해야 해"
    await agent.process_direct(message, session_key="test:int01")

    # Verify task added
    dashboard = manager.load()
    assert len(dashboard["tasks"]) >= 1, "Agent should add task"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_integration_03_complete_then_archive(integration_setup):
    """Integration 3: Agent completes task → Worker archives it

    Flow:
      1. Agent marks task as completed
      2. Worker runs
      3. Worker archives the completed task (status → archived)
      4. Verify task is archived in tasks.json
    """
    setup = integration_setup
    agent = setup["agent"]
    worker = setup["worker"]
    manager = setup["manager"]

    # Step 1: Add and complete task
    await agent.process_direct("블로그 글 써야 해", session_key="test:int03")
    await asyncio.sleep(1)

    await agent.process_direct("블로그 글 다 썼어", session_key="test:int03")

    # Verify task completed
    dashboard = manager.load()
    completed_tasks = [t for t in dashboard["tasks"] if t["status"] == "completed"]
    assert len(completed_tasks) >= 1, "Should have completed task"

    completed_task = completed_tasks[0]
    task_id = completed_task["id"]

    # Step 2: Worker runs
    await worker.run_cycle()

    # Step 3: Verify task is archived in tasks.json
    dashboard2 = manager.load()

    task = next((t for t in dashboard2["tasks"] if t["id"] == task_id), None)
    assert task is not None, "Task should still exist in tasks.json"
    assert task["status"] == "archived", f"Task should be archived by worker, got {task['status']}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_integration_05_multiple_workers_cycles(integration_setup):
    """Integration 5: Worker 여러 사이클

    Multiple worker cycles with different task states
    """
    setup = integration_setup
    worker = setup["worker"]
    backend = setup["backend"]

    # Create tasks in different states
    now = datetime.now()
    tasks_data = backend.load_tasks()

    # Task 1: Active task
    tasks_data["tasks"].append(
        {
            "id": "task_multi_1",
            "title": "Task 1",
            "status": "active",
            "deadline": (now + timedelta(days=3)).isoformat(),
            "progress": {
                "percentage": 0,
                "last_update": (now - timedelta(hours=30)).isoformat(),
                "note": "",
            },
            "created_at": (now - timedelta(hours=30)).isoformat(),
            "updated_at": (now - timedelta(hours=30)).isoformat(),
        }
    )

    # Task 2: Behind schedule
    tasks_data["tasks"].append(
        {
            "id": "task_multi_2",
            "title": "Task 2",
            "status": "active",
            "deadline": (now + timedelta(days=2)).isoformat(),
            "progress": {
                "percentage": 10,
                "last_update": now.isoformat(),
                "note": "",
            },
            "created_at": (now - timedelta(days=3)).isoformat(),
            "updated_at": now.isoformat(),
        }
    )

    # Task 3: Completed
    tasks_data["tasks"].append(
        {
            "id": "task_multi_3",
            "title": "Task 3",
            "status": "completed",
            "completed_at": now.isoformat(),
            "progress": {
                "percentage": 100,
                "last_update": now.isoformat(),
                "note": "Done",
            },
            "created_at": (now - timedelta(days=2)).isoformat(),
            "updated_at": now.isoformat(),
        }
    )

    backend.save_tasks(tasks_data)

    # Run worker cycle 1
    await worker.run_cycle()

    tasks_data2 = backend.load_tasks()

    # Task 3 should be archived
    task_3 = next((t for t in tasks_data2["tasks"] if t["id"] == "task_multi_3"), None)
    assert task_3 is not None, "Completed task should still exist in tasks.json"
    assert task_3["status"] == "archived", (
        f"Task should be archived by worker, got {task_3['status']}"
    )

    # Run worker cycle 2 (should not error)
    await worker.run_cycle()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
