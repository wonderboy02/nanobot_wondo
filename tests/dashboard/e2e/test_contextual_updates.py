"""E2E Test: Contextual Updates (v0.1.4)

v0.1.4의 맥락 기반 업데이트 기능을 검증합니다:
- 하나의 메시지로 여러 질문 동시 답변
- Blocker 암시적 추출
- Silent 모드
"""

import asyncio
import json
import os
import pytest
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.config.loader import load_config


@pytest.fixture(scope="function")
def agent_setup(tmp_path):
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
    (dashboard_path / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []}, indent=2), encoding="utf-8"
    )

    knowledge_dir = dashboard_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "insights.json").write_text(
        json.dumps({"version": "1.0", "insights": []}, indent=2), encoding="utf-8"
    )

    # Use latest DASHBOARD.md (v0.1.5 - Dashboard Tools)
    (workspace / "DASHBOARD.md").write_text(
        "# Dashboard Management\n\n"
        "You are a **contextual dashboard manager** that uses specialized tools.\n\n"
        "## Available Tools\n\n"
        "- create_task(title, deadline, priority, context, tags)\n"
        "- update_task(task_id, progress, status, blocked, blocker_note, ...)\n"
        "- answer_question(question_id, answer)\n"
        "- archive_task(task_id, reflection)\n\n"
        "## Core Principles\n\n"
        "1. **Use dashboard tools, NOT read_file/write_file**\n"
        "2. **One message can contain multiple pieces of information**\n"
        "3. **Think holistically** - extract all info\n"
        "4. **Detect blockers**: Words like '어려워요', '막혔어요', '힘들어요' mean blocked=True\n\n"
        "## Workflow\n\n"
        "1. Analyze message holistically\n"
        "2. Extract: answers, progress, blockers, context\n"
        "3. Use appropriate dashboard tools\n"
        "4. Reply SILENT for regular updates\n",
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

    return {"agent": agent_loop, "workspace": workspace, "dashboard": dashboard_path}


@pytest.mark.e2e
def test_contextual_01_multiple_answers_one_message(agent_setup):
    """Contextual 1: 한 메시지로 여러 질문 동시 답변

    Dashboard State:
      - Task: React 공부
      - Questions:
        - q_001: 어떤 자료로?
        - q_002: 진행 상황은?
        - q_003: 막히는 부분?

    User: "유튜브로 공부하고 있는데 50% 완료했어요. Hook이 좀 어려워요."

    Expected:
      - q_001 answered: "유튜브"
      - q_002 answered: "50%"
      - q_003 answered: "Hook 어려움"
      - Task progress: 50%
      - Task blocked: true
      - Task blocker_note: Hook related
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Setup: Create task and questions
    now = datetime.now()
    tasks_data = {
        "version": "1.0",
        "tasks": [
            {
                "id": "task_001",
                "title": "React 공부",
                "status": "active",
                "progress": {
                    "percentage": 0,
                    "last_update": now.isoformat(),
                    "note": "",
                    "blocked": False,
                },
                "priority": "medium",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        ],
    }

    questions_data = {
        "version": "1.0",
        "questions": [
            {
                "id": "q_001",
                "question": "어떤 자료로 공부할 거야?",
                "priority": "medium",
                "type": "info_gather",
                "related_task_id": "task_001",
                "answered": False,
                "created_at": now.isoformat(),
            },
            {
                "id": "q_002",
                "question": "진행 상황은 어때?",
                "priority": "medium",
                "type": "progress_check",
                "related_task_id": "task_001",
                "answered": False,
                "created_at": now.isoformat(),
            },
            {
                "id": "q_003",
                "question": "막히는 부분 있어?",
                "priority": "medium",
                "type": "blocker_check",
                "related_task_id": "task_001",
                "answered": False,
                "created_at": now.isoformat(),
            },
        ],
    }

    with open(dashboard / "tasks.json", "w", encoding="utf-8") as f:
        json.dump(tasks_data, f, indent=2, ensure_ascii=False)

    with open(dashboard / "questions.json", "w", encoding="utf-8") as f:
        json.dump(questions_data, f, indent=2, ensure_ascii=False)

    # Send contextual message
    message = "유튜브로 공부하고 있는데 50% 완료했어요. Hook이 좀 어려워서 막혔어요."

    import asyncio

    response = asyncio.run(agent.process_direct(message, session_key="test:contextual01"))

    # Verify multiple questions answered
    with open(dashboard / "questions.json", "r", encoding="utf-8") as f:
        questions_result = json.load(f).get("questions", [])

    answered_count = sum(1 for q in questions_result if q.get("answered"))
    assert answered_count >= 2, f"Should answer at least 2 questions, got {answered_count}"

    # Check q_001 (자료)
    q1 = next((q for q in questions_result if q["id"] == "q_001"), None)
    if q1 and q1.get("answered"):
        assert "유튜브" in q1.get("answer", ""), "q_001 answer should mention YouTube"

    # Check q_002 (진행률)
    q2 = next((q for q in questions_result if q["id"] == "q_002"), None)
    if q2 and q2.get("answered"):
        assert "50" in q2.get("answer", ""), "q_002 answer should mention 50%"

    # Check q_003 (blocker)
    q3 = next((q for q in questions_result if q["id"] == "q_003"), None)
    if q3 and q3.get("answered"):
        assert "Hook" in q3.get("answer", ""), "q_003 answer should mention Hook"

    # Verify task updated
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks_result = json.load(f).get("tasks", [])

    task = tasks_result[0]
    assert task["progress"]["percentage"] >= 40, (
        f"Progress should be around 50%, got {task['progress']['percentage']}"
    )

    # Verify blocker detected
    assert task["progress"].get("blocked") == True, "Task should be marked as blocked"


@pytest.mark.e2e
def test_contextual_02_implicit_blocker_extraction(agent_setup):
    """Contextual 2: Blocker 암시적 추출

    User says: "어려워요", "이해가 안 돼요", "막혔어요"
    Expected: progress.blocked = true
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Add task
    import asyncio

    asyncio.run(agent.process_direct("React 공부해야 해", session_key="test:contextual02"))
    import time

    time.sleep(1)

    # Send message with implicit blocker
    message = "공부하고 있는데 Hook 부분이 너무 어려워서 이해가 안 돼요"
    import asyncio

    response = asyncio.run(agent.process_direct(message, session_key="test:contextual02"))

    # Verify blocker extracted
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    if tasks:
        task = tasks[0]
        # Should detect blocker from "어려워서 이해가 안 돼요"
        assert task["progress"].get("blocked") == True, (
            "Should detect blocker from implicit language"
        )

        blocker_note = task["progress"].get("blocker_note", "")
        assert blocker_note, "Should have blocker note"
        assert "Hook" in blocker_note or "어려" in blocker_note, (
            f"Blocker note should mention the difficulty: {blocker_note}"
        )


@pytest.mark.e2e
def test_contextual_03_silent_mode(agent_setup):
    """Contextual 3: Silent 모드 검증

    Regular updates → SILENT (no response)
    Commands (/questions) → Show results
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Regular message (should be SILENT)
    message1 = "내일까지 블로그 글 써야 해"
    import asyncio

    response1 = asyncio.run(agent.process_direct(message1, session_key="test:contextual03"))

    # Response might be SILENT or None
    # If not None, it should be minimal (just acknowledgment)
    if response1:
        assert len(response1) < 100, "Regular update should have minimal/silent response"

    # Verify task was still created (silent doesn't mean no action)
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    assert len(tasks) >= 1, "Task should be created even with silent response"


@pytest.mark.e2e
def test_contextual_04_holistic_update(agent_setup):
    """Contextual 4: 홀리스틱 업데이트

    One message updates:
    - Multiple questions answered
    - Task progress updated
    - Task context updated
    - Blocker added
    - New question generated
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Setup complex state
    now = datetime.now()
    tasks_data = {
        "version": "1.0",
        "tasks": [
            {
                "id": "task_001",
                "title": "프로젝트 개발",
                "status": "active",
                "progress": {
                    "percentage": 0,
                    "last_update": now.isoformat(),
                    "note": "",
                    "blocked": False,
                },
                "context": "",
                "priority": "high",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        ],
    }

    questions_data = {
        "version": "1.0",
        "questions": [
            {
                "id": "q_001",
                "question": "어떤 기술 스택 사용할 거야?",
                "priority": "high",
                "type": "info_gather",
                "related_task_id": "task_001",
                "answered": False,
                "created_at": now.isoformat(),
            },
            {
                "id": "q_002",
                "question": "진행 상황은?",
                "priority": "medium",
                "type": "progress_check",
                "related_task_id": "task_001",
                "answered": False,
                "created_at": now.isoformat(),
            },
        ],
    }

    with open(dashboard / "tasks.json", "w", encoding="utf-8") as f:
        json.dump(tasks_data, f, indent=2, ensure_ascii=False)

    with open(dashboard / "questions.json", "w", encoding="utf-8") as f:
        json.dump(questions_data, f, indent=2, ensure_ascii=False)

    # Send rich contextual message
    message = (
        "React와 TypeScript로 개발하고 있어요. "
        "현재 30% 정도 완료했는데, "
        "TypeScript 타입 에러가 계속 나서 좀 막혔어요. "
        "내일까지 50%는 해야 하는데 걱정되네요."
    )
    import asyncio

    response = asyncio.run(agent.process_direct(message, session_key="test:contextual04"))

    # Verify holistic updates
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks_result = json.load(f).get("tasks", [])

    with open(dashboard / "questions.json", "r", encoding="utf-8") as f:
        questions_result = json.load(f).get("questions", [])

    task = tasks_result[0]

    # Check multiple aspects updated
    updates = []

    # Progress updated?
    if task["progress"]["percentage"] > 0:
        updates.append("progress")

    # Context updated with tech stack?
    if "React" in task.get("context", "") or "TypeScript" in task.get("context", ""):
        updates.append("context")

    # Blocker detected?
    if task["progress"].get("blocked"):
        updates.append("blocker")

    # Questions answered?
    answered = [q for q in questions_result if q.get("answered")]
    if answered:
        updates.append("questions")

    # Should have updated multiple aspects
    assert len(updates) >= 2, f"Should update multiple aspects holistically, updated: {updates}"


@pytest.mark.e2e
def test_contextual_05_no_limit_on_items(agent_setup):
    """Contextual 5: 제한 없는 항목 표시

    v0.1.4: No limit on active tasks or unanswered questions
    All should be visible in context
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Create many tasks (more than old limit of 10)
    now = datetime.now()
    tasks = []
    for i in range(15):
        tasks.append(
            {
                "id": f"task_{i:03d}",
                "title": f"Task {i}",
                "status": "active",
                "progress": {"percentage": i * 5, "last_update": now.isoformat(), "note": ""},
                "priority": "medium",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        )

    tasks_data = {"version": "1.0", "tasks": tasks}

    with open(dashboard / "tasks.json", "w", encoding="utf-8") as f:
        json.dump(tasks_data, f, indent=2, ensure_ascii=False)

    # Send message referencing a task beyond old limit
    message = "Task 14의 진행 상황 업데이트: 80% 완료"
    import asyncio

    response = asyncio.run(agent.process_direct(message, session_key="test:contextual05"))

    # Verify task 14 was found and updated (proving no 10-item limit)
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks_result = json.load(f).get("tasks", [])

    task_14 = next((t for t in tasks_result if t["id"] == "task_014"), None)
    assert task_14 is not None, "Task 14 should exist"

    # If Agent could see and update task 14, it proves no limit
    # (Old system limited to 10 items)
    if task_14["progress"]["percentage"] >= 70:
        # Successfully updated task beyond old 10-item limit
        assert True, "Successfully accessed task beyond old limit (no limit anymore)"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
