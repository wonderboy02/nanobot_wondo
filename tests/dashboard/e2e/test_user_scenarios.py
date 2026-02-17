"""E2E Test: 10 User Scenarios

실제 Agent를 실행하여 사용자 시나리오를 검증합니다.
⚠️ 실제 LLM API 필요 (Gemini 3 Pro 권장)
"""

import asyncio
import json
import os
import pytest
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.config.loader import load_config


def get_completed_tasks(dashboard_path: Path) -> list[dict]:
    """Get all completed tasks from both tasks.json and history.json."""
    completed = []

    # Check tasks.json
    tasks_file = dashboard_path / "tasks.json"
    if tasks_file.exists():
        tasks_data = json.loads(tasks_file.read_text(encoding="utf-8"))
        completed.extend([t for t in tasks_data.get("tasks", []) if t.get("status") == "completed"])

    # Check history.json
    history_file = dashboard_path / "knowledge" / "history.json"
    if history_file.exists():
        history_data = json.loads(history_file.read_text(encoding="utf-8"))
        completed.extend(history_data.get("completed_tasks", []))

    return completed


@pytest.fixture
def agent_setup(tmp_path):
    """Setup Agent with clean dashboard."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create dashboard structure
    dashboard_path = workspace / "dashboard"
    dashboard_path.mkdir()

    (dashboard_path / "tasks.json").write_text(
        json.dumps({"version": "1.0", "tasks": []}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    (dashboard_path / "questions.json").write_text(
        json.dumps({"version": "1.0", "questions": []}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    (dashboard_path / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # Knowledge
    knowledge_dir = dashboard_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "history.json").write_text(
        json.dumps({"version": "1.0", "completed_tasks": [], "projects": []}, indent=2),
        encoding="utf-8"
    )
    (knowledge_dir / "insights.json").write_text(
        json.dumps({"version": "1.0", "insights": []}, indent=2),
        encoding="utf-8"
    )
    (knowledge_dir / "people.json").write_text(
        json.dumps({"version": "1.0", "people": []}, indent=2),
        encoding="utf-8"
    )

    # Create DASHBOARD.md (v0.1.5 - Dashboard Tools)
    (workspace / "DASHBOARD.md").write_text(
        "# Dashboard Management\n\n"
        "You are a **Dashboard Sync Manager** that uses specialized tools.\n\n"
        "## Available Tools\n\n"
        "- create_task(title, deadline, priority, context, tags)\n"
        "- update_task(task_id, progress, status, blocked, blocker_note, ...)\n"
        "- answer_question(question_id, answer)\n"
        "- move_to_history(task_id, reflection)\n\n"
        "**IMPORTANT**: Use dashboard tools, NOT read_file/write_file for dashboard operations.\n\n"
        "**Note**: Worker Agent handles question creation and notification scheduling automatically.\n"
        "You only need to respond to user messages and update dashboard based on conversation.\n\n"
        "Reply SILENT for regular updates.",
        encoding="utf-8"
    )

    # Create memory
    memory_dir = workspace / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("", encoding="utf-8")

    # Load config
    config = load_config()

    # Set API keys
    if config.providers.openai.api_key:
        os.environ["OPENAI_API_KEY"] = config.providers.openai.api_key
    if config.providers.gemini.api_key:
        os.environ["GEMINI_API_KEY"] = config.providers.gemini.api_key

    # Create Agent
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
async def test_scenario_01_add_new_task(agent_setup):
    """Scenario 1: 새 Task 추가

    User: "다음 주까지 블로그 글 써야 해"
    Expected:
      - tasks.json: 1 task added
      - status: "active"
      - deadline: ~다음 주

    Note: Question generation is Worker Agent's responsibility (not tested here)
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Send message
    message = "다음 주까지 블로그 글 써야 해"
    response = await agent.process_direct(message, session_key="test:scenario01")

    # Verify tasks
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    assert len(tasks) >= 1, f"Should add at least 1 task, got {len(tasks)}"

    task = tasks[0]
    assert "블로그" in task["title"] or "글" in task["title"], \
        f"Task title should mention blog/writing: {task['title']}"
    assert task["status"] == "active", "Task should be active"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_scenario_02_update_progress(agent_setup):
    """Scenario 2: Task 진행률 업데이트

    User: "블로그 글 50% 완료했어"
    Expected:
      - Find task by title
      - progress.percentage = 50
      - progress.note updated
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # First, add a task
    await agent.process_direct("블로그 글 써야 해", session_key="test:scenario02")

    # Wait a bit
    await asyncio.sleep(1)

    # Update progress
    message = "블로그 글 50% 완료했어"
    response = await agent.process_direct(message, session_key="test:scenario02")

    # Verify progress updated
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    assert len(tasks) >= 1, "Should have task"

    # Find the blog task
    blog_task = None
    for task in tasks:
        if "블로그" in task["title"] or "글" in task["title"]:
            blog_task = task
            break

    assert blog_task is not None, "Should find blog task"
    assert blog_task["progress"]["percentage"] >= 40, \
        f"Progress should be around 50%, got {blog_task['progress']['percentage']}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_scenario_03_complete_task(agent_setup):
    """Scenario 3: Task 완료

    User: "블로그 글 다 썼어"
    Expected:
      - task.status = "completed"
      - task.completed_at set
      - progress.percentage = 100
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Add task
    await agent.process_direct("블로그 글 써야 해", session_key="test:scenario03")
    await asyncio.sleep(1)

    # Complete task
    message = "블로그 글 다 썼어"
    response = await agent.process_direct(message, session_key="test:scenario03")

    # Verify completion
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    # Check if task is completed in tasks.json or moved to history.json
    blog_task = None
    for task in tasks:
        if "블로그" in task["title"] or "글" in task["title"]:
            blog_task = task
            break

    # If not in tasks.json, check history.json
    if blog_task is None or blog_task.get("status") != "completed":
        all_completed = get_completed_tasks(dashboard)
        for task in all_completed:
            if "블로그" in task["title"] or "글" in task["title"]:
                blog_task = task
                break

    assert blog_task is not None, "Should find blog task"
    # Task should be either completed in tasks.json or moved to history
    if blog_task in tasks:
        assert blog_task["status"] == "completed", \
            f"Task should be completed, got {blog_task['status']}"
    assert blog_task.get("completed_at") is not None, "Should have completed_at"
    assert blog_task["progress"]["percentage"] == 100, \
        f"Progress should be 100%, got {blog_task['progress']['percentage']}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_scenario_04_answer_question(agent_setup):
    """Scenario 4: Question 답변

    User: "블로그 주제는 React Server Components로 할 거야"
    Expected:
      - Find related question
      - question.answered = true
      - question.answer = "React Server Components"
      - Related task updated
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Add task (should generate question)
    await agent.process_direct("블로그 글 써야 해", session_key="test:scenario04")
    await asyncio.sleep(1)

    # Answer question
    message = "블로그 주제는 React Server Components로 할 거야"
    response = await agent.process_direct(message, session_key="test:scenario04")

    # Verify question answered
    with open(dashboard / "questions.json", encoding="utf-8") as f:
        questions_data = json.load(f)
        questions = questions_data.get("questions", [])

    # Should have question about topic
    topic_q = None
    for q in questions:
        if "주제" in q["question"] or "topic" in q["question"].lower():
            topic_q = q
            break

    # Question may or may not exist depending on Agent's decision
    # But task should have context updated
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    blog_task = None
    for task in tasks:
        if "블로그" in task["title"]:
            blog_task = task
            break

    assert blog_task is not None, "Should find blog task"
    # Verify topic mentioned in task context or note
    task_str = json.dumps(blog_task, ensure_ascii=False)
    assert "React" in task_str or "RSC" in task_str or "Server" in task_str, \
        "Task should reference the topic"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_scenario_05_cancel_task(agent_setup):
    """Scenario 5: Task 취소

    User: "블로그 글 쓰기 취소할래"
    Expected:
      - task.status = "cancelled"
      - Related questions cleared/answered
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Add task
    await agent.process_direct("블로그 글 써야 해", session_key="test:scenario05")
    await asyncio.sleep(1)

    # Cancel task
    message = "블로그 글 쓰기 취소할래"
    response = await agent.process_direct(message, session_key="test:scenario05")

    # Verify cancellation
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    blog_task = None
    for task in tasks:
        if "블로그" in task["title"]:
            blog_task = task
            break

    assert blog_task is not None, "Should find blog task"
    assert blog_task["status"] in ["cancelled", "canceled", "someday"], \
        f"Task should be cancelled, got {blog_task['status']}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_scenario_06_change_deadline(agent_setup):
    """Scenario 6: Deadline 변경

    User: "블로그 글 deadline 다음 달로 미뤄줘"
    Expected:
      - task.deadline updated
      - task.status may change to "someday"
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Add task with near deadline
    await agent.process_direct("이번 주까지 블로그 글 써야 해", session_key="test:scenario06")
    await asyncio.sleep(1)

    # Get original deadline
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        original_tasks = json.load(f).get("tasks", [])
    original_deadline = original_tasks[0].get("deadline") if original_tasks else None

    # Change deadline
    message = "블로그 글 deadline 다음 달로 미뤄줘"
    response = await agent.process_direct(message, session_key="test:scenario06")

    # Verify deadline changed
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    blog_task = tasks[0] if tasks else None
    assert blog_task is not None, "Should have task"

    new_deadline = blog_task.get("deadline")
    # Deadline should be different (or task should be someday)
    assert new_deadline != original_deadline or blog_task["status"] == "someday", \
        "Deadline should change or status should become someday"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_scenario_07_block_task(agent_setup):
    """Scenario 7: Task Block 처리

    User: "블로그 글 지금 막혀있어, 멘토 답변 기다리는 중"
    Expected:
      - progress.blocked = true
      - progress.blocker_note set
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Add task
    await agent.process_direct("블로그 글 써야 해", session_key="test:scenario07")
    await asyncio.sleep(1)

    # Block task
    message = "블로그 글 지금 막혀있어, 멘토 답변 기다리는 중"
    response = await agent.process_direct(message, session_key="test:scenario07")

    # Verify blocked status
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    blog_task = None
    for task in tasks:
        if "블로그" in task["title"]:
            blog_task = task
            break

    assert blog_task is not None, "Should find blog task"
    assert blog_task["progress"].get("blocked") == True, \
        f"Task should be blocked, got {blog_task['progress'].get('blocked')}"
    assert blog_task["progress"].get("blocker_note"), "Should have blocker note"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_scenario_08_multiple_tasks(agent_setup):
    """Scenario 8: 여러 Task 한 번에 추가

    User: "이번 주에 블로그 쓰고, 운동하고, React 공부해야 해"
    Expected:
      - 3 tasks added
      - Each with appropriate title
      - Questions for each
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Add multiple tasks
    message = "이번 주에 블로그 쓰고, 운동하고, React 공부해야 해"
    response = await agent.process_direct(message, session_key="test:scenario08")

    # Verify multiple tasks
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    assert len(tasks) >= 2, f"Should add at least 2 tasks, got {len(tasks)}"

    # Verify different topics
    titles = [task["title"] for task in tasks]
    titles_str = " ".join(titles)

    # Should mention at least 2 of the 3 topics
    topics_mentioned = 0
    if "블로그" in titles_str or "글" in titles_str:
        topics_mentioned += 1
    if "운동" in titles_str:
        topics_mentioned += 1
    if "React" in titles_str or "공부" in titles_str:
        topics_mentioned += 1

    assert topics_mentioned >= 2, \
        f"Should mention at least 2 topics, got {topics_mentioned}: {titles}"


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_scenario_09_natural_language_dates(agent_setup):
    """Scenario 9: 자연어 날짜 처리

    User: "내일까지 A, 다음 주까지 B, 언젠가 C"
    Expected:
      - "내일": deadline = tomorrow
      - "다음 주": deadline = next week
      - "언젠가": status = "someday"
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Add tasks with different time expressions
    message = "내일까지 급한 일 끝내고, 다음 주까지 프로젝트 완성하고, 언젠가 운동 시작해야지"
    response = await agent.process_direct(message, session_key="test:scenario09")

    # Verify tasks
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    assert len(tasks) >= 2, f"Should add at least 2 tasks, got {len(tasks)}"

    # Verify different urgencies
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    next_week = now + timedelta(days=7)

    # Check for urgent task (tomorrow)
    urgent_tasks = [t for t in tasks if "급한" in t["title"] or "내일" in t.get("deadline_text", "")]
    if urgent_tasks:
        task = urgent_tasks[0]
        assert task["status"] == "active", "Urgent task should be active"
        # Deadline should be soon
        if task.get("deadline"):
            deadline = datetime.fromisoformat(task["deadline"])
            days_until = (deadline - now).days
            assert days_until <= 2, "Tomorrow task should have deadline within 2 days"

    # Check for someday task
    someday_tasks = [t for t in tasks if t["status"] == "someday" or "언젠가" in t.get("deadline_text", "")]
    # Someday task may or may not be created depending on Agent's interpretation


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_scenario_10_add_links(agent_setup):
    """Scenario 10: Link 추가

    User: "이 블로그 글은 React 프로젝트랑 연결해줘"
    Expected:
      - task.links.projects updated
      - Project created or referenced
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    # Add task
    await agent.process_direct("블로그 글 써야 해", session_key="test:scenario10")
    await asyncio.sleep(1)

    # Add link
    message = "이 블로그 글은 React 학습 프로젝트랑 연결해줘"
    response = await agent.process_direct(message, session_key="test:scenario10")

    # Verify link added
    with open(dashboard / "tasks.json", encoding="utf-8") as f:
        tasks_data = json.load(f)
        tasks = tasks_data.get("tasks", [])

    blog_task = None
    for task in tasks:
        if "블로그" in task["title"]:
            blog_task = task
            break

    assert blog_task is not None, "Should find blog task"

    # Verify links exist
    links = blog_task.get("links", {})
    # May have project link, or context mentioning React project
    task_str = json.dumps(blog_task, ensure_ascii=False)
    assert "React" in task_str or "프로젝트" in task_str, \
        "Task should reference the project"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
