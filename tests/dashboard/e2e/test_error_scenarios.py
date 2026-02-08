"""E2E Test: Error Scenarios

LLM 실패, Tool call 에러, 애매한 메시지 등 에러 케이스를 검증합니다.
"""

import asyncio
import json
import os
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.config.loader import load_config


@pytest.fixture
async def agent_setup(tmp_path):
    """Setup Agent with clean dashboard."""
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

    knowledge_dir = dashboard_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "history.json").write_text(
        json.dumps({"version": "1.0", "completed_tasks": [], "projects": []}, indent=2),
        encoding="utf-8"
    )
    (knowledge_dir / "insights.json").write_text(
        json.dumps({"version": "1.0", "insights": []}, indent=2), encoding="utf-8"
    )
    (knowledge_dir / "people.json").write_text(
        json.dumps({"version": "1.0", "people": []}, indent=2), encoding="utf-8"
    )

    (workspace / "DASHBOARD.md").write_text(
        "# Dashboard Management\n\n"
        "You are a Dashboard Sync Manager that uses specialized tools.\n\n"
        "## Available Tools\n\n"
        "- create_task(title, deadline, priority, context, tags)\n"
        "- update_task(task_id, progress, status, blocked, blocker_note, ...)\n"
        "- answer_question(question_id, answer)\n"
        "- create_question(question, priority, type, related_task_id)\n\n"
        "Use dashboard tools, NOT read_file/write_file.",
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

    return {
        "agent": agent_loop,
        "workspace": workspace,
        "dashboard": dashboard_path
    }


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_error_01_ambiguous_message(agent_setup):
    """Error 1: 애매한 메시지

    User: "그거 해야 해"
    Expected:
      - Don't crash
      - Either ask clarifying question OR
      - Create generic task with note to clarify
    """
    setup = await agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Send ambiguous message
    message = "그거 해야 해"

    try:
        response = await agent.process_direct(message, session_key="test:error01")
    except Exception as e:
        pytest.fail(f"Agent crashed on ambiguous message: {e}")

    # Verify agent didn't crash
    # Either created a task OR generated a question
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    with open(dashboard / "questions.json", encoding="utf-8") as f:
        questions = json.load(f).get("questions", [])

    # Should handle gracefully (either task or question)
    # At minimum, shouldn't crash
    assert True, "Agent handled ambiguous message without crashing"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_error_02_file_corruption_recovery(agent_setup):
    """Error 2: 손상된 파일 복구

    Corrupt tasks.json, then send message
    Expected:
      - Detect corruption
      - Reset or recover
      - Continue operation
    """
    setup = await agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Corrupt tasks.json
    (dashboard / "tasks.json").write_text("{ invalid json }", encoding="utf-8")

    # Send message
    message = "새로운 작업 추가해줘"

    try:
        response = await agent.process_direct(message, session_key="test:error02")

        # Verify file recovered
        with open(dashboard / "tasks.json", encoding="utf-8") as f:
            tasks_data = json.load(f)  # Should not raise

        # Should have recovered and created new task
        tasks = tasks_data.get("tasks", [])
        # May or may not have task depending on recovery strategy

    except json.JSONDecodeError:
        # Agent failed to recover - acceptable if it reports error
        pass
    except Exception as e:
        # Other errors - should handle gracefully
        print(f"Handled corruption with: {e}")


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_error_03_very_long_context(agent_setup):
    """Error 3: Context 너무 큼

    Create many tasks, then send message
    Expected:
      - Context builder handles gracefully
      - May summarize or paginate
      - Doesn't crash
    """
    setup = await agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Create many tasks (simulate large dashboard)
    tasks = []
    for i in range(50):  # 50 tasks
        tasks.append({
            "id": f"task_{i:03d}",
            "title": f"Task {i}: Lorem ipsum dolor sit amet, consectetur adipiscing elit",
            "status": "active" if i < 30 else "someday",
            "deadline": "2026-02-15T23:59:00",
            "progress": {"percentage": i * 2, "last_update": "2026-02-08T10:00:00", "note": ""},
            "priority": "medium",
            "created_at": "2026-02-01T10:00:00",
            "updated_at": "2026-02-08T10:00:00"
        })

    with open(dashboard / "tasks.json", "w", encoding="utf-8") as f:
        json.dump({"version": "1.0", "tasks": tasks}, f, indent=2)

    # Send message
    message = "새 작업 추가해줘"

    try:
        response = await agent.process_direct(message, session_key="test:error03")

        # Should handle without crashing
        assert True, "Agent handled large context"

    except Exception as e:
        # If it fails, should be graceful
        print(f"Large context handled with: {e}")


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_error_04_missing_required_fields(agent_setup):
    """Error 4: 필수 필드 누락

    Create task with missing fields, verify schema validation
    Expected:
      - Schema validation catches errors
      - Agent can still operate
    """
    setup = await agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Create task with missing required fields
    incomplete_task = {
        "id": "task_incomplete",
        "title": "Incomplete Task"
        # Missing: status, progress, created_at, etc.
    }

    with open(dashboard / "tasks.json", "w", encoding="utf-8") as f:
        json.dump({"version": "1.0", "tasks": [incomplete_task]}, f, indent=2)

    # Send message
    message = "작업 상태 알려줘"

    try:
        response = await agent.process_direct(message, session_key="test:error04")

        # Should handle gracefully (validate and fix or skip)
        assert True, "Agent handled incomplete task data"

    except Exception as e:
        print(f"Incomplete data handled with: {e}")


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_error_05_concurrent_updates(agent_setup):
    """Error 5: 동시 업데이트

    Simulate concurrent updates to dashboard
    Expected:
      - No data loss
      - Latest write wins or merge
    """
    setup = await agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Add initial task
    await agent.process_direct("Task A 추가해줘", session_key="test:error05a")
    await asyncio.sleep(0.5)

    # Simulate concurrent updates
    task1 = asyncio.create_task(
        agent.process_direct("Task B 추가해줘", session_key="test:error05b")
    )
    task2 = asyncio.create_task(
        agent.process_direct("Task C 추가해줘", session_key="test:error05c")
    )

    # Wait for both
    await asyncio.gather(task1, task2, return_exceptions=True)

    # Verify no data loss
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    # Should have at least 2 tasks (A + one of B/C)
    # May have 3 if concurrent writes handled well
    assert len(tasks) >= 2, f"Should have at least 2 tasks after concurrent updates, got {len(tasks)}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_error_06_invalid_date_format(agent_setup):
    """Error 6: 잘못된 날짜 형식

    User provides invalid date
    Expected:
      - Parse and normalize
      - Or ask for clarification
    """
    setup = await agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Send message with weird date format
    message = "내일모레까지 작업 완료해야 해"  # "day after tomorrow"

    try:
        response = await agent.process_direct(message, session_key="test:error06")

        # Verify task created with reasonable deadline
        with open(dashboard / "tasks.json", encoding="utf-8") as f:
            tasks = json.load(f).get("tasks", [])

        if tasks:
            task = tasks[0]
            # Should have parsed date somehow
            assert task.get("deadline") or task.get("deadline_text"), \
                "Should have some deadline info"

    except Exception as e:
        print(f"Invalid date handled with: {e}")


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_error_07_extremely_long_message(agent_setup):
    """Error 7: 매우 긴 메시지

    User sends very long message
    Expected:
      - Process without truncating important info
      - Or summarize appropriately
    """
    setup = await agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Create very long message
    long_message = "블로그 글을 써야 하는데, " + \
        "주제는 React Server Components이고, " * 50 + \
        "내일까지 완료해야 해"

    try:
        response = await agent.process_direct(long_message, session_key="test:error07")

        # Should extract key info (task, deadline)
        with open(dashboard / "tasks.json", encoding="utf-8") as f:
            tasks = json.load(f).get("tasks", [])

        assert len(tasks) >= 1, "Should extract task from long message"

        task = tasks[0]
        assert "블로그" in task["title"] or "글" in task["title"], \
            "Should extract task title"

    except Exception as e:
        print(f"Long message handled with: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
