"""E2E Test: Worker + Agent Integration

Worker와 Agent가 함께 동작하는 통합 시나리오를 검증합니다.
"""

import asyncio
import json
import os
import pytest
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.config.loader import load_config
from nanobot.dashboard.manager import DashboardManager
from nanobot.dashboard.worker import WorkerAgent


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
        encoding="utf-8"
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
        max_iterations=10
    )

    worker = WorkerAgent(dashboard_path)
    manager = DashboardManager(dashboard_path)

    return {
        "agent": agent_loop,
        "worker": worker,
        "manager": manager,
        "workspace": workspace,
        "dashboard": dashboard_path
    }


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_integration_01_agent_add_worker_ask(integration_setup):
    """Integration 1: Agent adds task → Worker generates question

    Flow:
      1. Agent adds task (with deadline)
      2. Worker runs (simulated 30 min later)
      3. Worker generates question (task not started)
      4. Verify question in queue
    """
    setup = integration_setup
    agent = setup["agent"]
    worker = setup["worker"]
    manager = setup["manager"]

    # Step 1: Agent adds task
    message = "3일 후까지 중요한 프로젝트 완료해야 해"
    await agent.process_direct(message, session_key="test:int01")

    # Verify task added
    dashboard = manager.load()
    assert len(dashboard["tasks"]) >= 1, "Agent should add task"

    # Modify task to be "old" (simulate 25 hours passed)
    task = dashboard["tasks"][0]
    old_time = (datetime.now() - timedelta(hours=25)).isoformat()
    task["created_at"] = old_time
    task["progress"]["last_update"] = old_time
    task["updated_at"] = old_time
    manager.save(dashboard)

    # Step 2: Worker runs
    await worker.run_cycle()

    # Step 3: Verify question generated
    dashboard2 = manager.load()
    questions = dashboard2["questions"]

    assert len(questions) > 0, "Worker should generate question for unstarted task"

    # Find question related to our task
    related_q = [q for q in questions if q.get("related_task_id") == task["id"]]
    assert len(related_q) > 0, f"Should have question for task {task['id']}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_integration_02_worker_ask_agent_answer(integration_setup):
    """Integration 2: Worker asks → User answers → Agent updates

    Flow:
      1. Worker generates question
      2. User provides answer
      3. Agent processes answer and updates task
      4. Verify task updated
    """
    setup = integration_setup
    agent = setup["agent"]
    worker = setup["worker"]
    manager = setup["manager"]

    # Step 1: Create task that triggers question
    now = datetime.now()
    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_int02",
        "title": "Important Project",
        "status": "active",
        "deadline": (now + timedelta(days=3)).isoformat(),
        "progress": {
            "percentage": 0,
            "last_update": (now - timedelta(hours=25)).isoformat(),
            "note": "",
            "blocked": False
        },
        "priority": "high",
        "created_at": (now - timedelta(hours=25)).isoformat(),
        "updated_at": (now - timedelta(hours=25)).isoformat()
    })
    manager.save(dashboard)

    # Run worker to generate question
    await worker.run_cycle()

    dashboard2 = manager.load()
    questions = dashboard2["questions"]
    assert len(questions) > 0, "Worker should generate question"

    # Step 2: User answers the question
    answer_message = "프로젝트 시작했어, 지금 30% 완료했고 순조롭게 진행 중이야"
    await agent.process_direct(answer_message, session_key="test:int02")

    # Step 3: Verify task updated
    dashboard3 = manager.load()
    task = None
    for t in dashboard3["tasks"]:
        if t["id"] == "task_int02":
            task = t
            break

    assert task is not None, "Task should exist"
    assert task["progress"]["percentage"] > 0, \
        f"Task progress should be updated, got {task['progress']['percentage']}"


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

    # Task should still be in tasks list but with archived status
    task = next((t for t in dashboard2["tasks"] if t["id"] == task_id), None)
    assert task is not None, "Task should still exist in tasks.json"
    assert task["status"] == "archived", \
        f"Task should be archived by worker, got {task['status']}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_integration_04_full_lifecycle(integration_setup):
    """Integration 4: 전체 생명주기

    Full lifecycle:
      1. Agent adds task
      2. Worker asks question (not started)
      3. User answers (started, 30%)
      4. Worker checks progress (slightly behind)
      5. User updates (60%)
      6. User completes
      7. Worker archives the task
    """
    setup = integration_setup
    agent = setup["agent"]
    worker = setup["worker"]
    manager = setup["manager"]

    # Step 1: Add task
    await agent.process_direct("1주일 안에 중요한 발표 준비해야 해", session_key="test:int04")
    await asyncio.sleep(1)

    dashboard = manager.load()
    assert len(dashboard["tasks"]) >= 1, "Task should be added"
    task_id = dashboard["tasks"][0]["id"]

    # Step 2: Simulate time passing (make task "old")
    task = dashboard["tasks"][0]
    old_time = (datetime.now() - timedelta(hours=25)).isoformat()
    task["created_at"] = old_time
    task["progress"]["last_update"] = old_time
    task["updated_at"] = old_time
    manager.save(dashboard)

    # Worker runs → should ask "started?"
    await worker.run_cycle()

    dashboard2 = manager.load()
    questions = dashboard2["questions"]
    assert len(questions) > 0, "Worker should generate question"

    # Step 3: User answers (started)
    await agent.process_direct("발표 준비 시작했어, 자료 조사 30% 완료", session_key="test:int04")
    await asyncio.sleep(1)

    # Step 4: User updates progress
    await agent.process_direct("발표 준비 60% 완료했어", session_key="test:int04")
    await asyncio.sleep(1)

    # Step 5: User completes
    await agent.process_direct("발표 준비 다 끝났어", session_key="test:int04")
    await asyncio.sleep(1)

    # Step 6: Worker archives the task
    await worker.run_cycle()

    # Verify final state
    dashboard_final = manager.load()

    # Task should still be in tasks.json but archived
    task = next((t for t in dashboard_final["tasks"] if t["id"] == task_id), None)
    assert task is not None, "Task should still exist in tasks.json"
    assert task["status"] == "archived", \
        f"Task should be archived by worker, got {task['status']}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_integration_05_multiple_workers_cycles(integration_setup):
    """Integration 5: Worker 여러 사이클

    Multiple worker cycles with different task states
    """
    setup = integration_setup
    agent = setup["agent"]
    worker = setup["worker"]
    manager = setup["manager"]

    # Create tasks in different states
    now = datetime.now()
    dashboard = manager.load()

    # Task 1: Not started (old)
    dashboard["tasks"].append({
        "id": "task_multi_1",
        "title": "Task 1",
        "status": "active",
        "deadline": (now + timedelta(days=3)).isoformat(),
        "progress": {"percentage": 0, "last_update": (now - timedelta(hours=30)).isoformat(), "note": ""},
        "created_at": (now - timedelta(hours=30)).isoformat(),
        "updated_at": (now - timedelta(hours=30)).isoformat()
    })

    # Task 2: Behind schedule
    dashboard["tasks"].append({
        "id": "task_multi_2",
        "title": "Task 2",
        "status": "active",
        "deadline": (now + timedelta(days=2)).isoformat(),
        "progress": {"percentage": 10, "last_update": now.isoformat(), "note": ""},
        "created_at": (now - timedelta(days=3)).isoformat(),
        "updated_at": now.isoformat()
    })

    # Task 3: Completed
    dashboard["tasks"].append({
        "id": "task_multi_3",
        "title": "Task 3",
        "status": "completed",
        "completed_at": now.isoformat(),
        "progress": {"percentage": 100, "last_update": now.isoformat(), "note": "Done"},
        "created_at": (now - timedelta(days=2)).isoformat(),
        "updated_at": now.isoformat()
    })

    manager.save(dashboard)

    # Run worker cycle 1
    await worker.run_cycle()

    dashboard2 = manager.load()

    # Should have questions for task 1 and 2
    questions = dashboard2["questions"]
    assert len(questions) >= 1, "Should generate questions for problematic tasks"

    # Task 3 should be archived (still in tasks.json with archived status)
    task_3 = next((t for t in dashboard2["tasks"] if t["id"] == "task_multi_3"), None)
    assert task_3 is not None, "Completed task should still exist in tasks.json"
    assert task_3["status"] == "archived", \
        f"Task should be archived by worker, got {task_3['status']}"

    # Run worker cycle 2 (shouldn't duplicate questions due to cooldown)
    await worker.run_cycle()

    dashboard3 = manager.load()
    questions3 = dashboard3["questions"]

    # Should not have duplicate questions
    question_ids = [q["id"] for q in questions3]
    assert len(question_ids) == len(set(question_ids)), "Should not have duplicate question IDs"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
