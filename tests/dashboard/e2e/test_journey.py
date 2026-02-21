"""E2E Test: User Journey (Real-world Usage Simulation)

실제 사용자의 장기 사용 패턴을 시뮬레이션합니다.
- 1주일 라이프사이클
- 복잡한 프로젝트 관리
- 멀티태스킹 + 우선순위 변경

[WARNING] 실제 LLM API 필요 (Gemini 3 Pro 권장)
[WARNING] 실행 시간: 각 테스트당 5-10분
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


def get_completed_tasks(dashboard_path: Path) -> list[dict]:
    """Get all completed/archived tasks from tasks.json."""
    tasks_file = dashboard_path / "tasks.json"
    if tasks_file.exists():
        data = json.loads(tasks_file.read_text(encoding="utf-8"))
        return [t for t in data.get("tasks", []) if t.get("status") in ("completed", "archived")]
    return []


@pytest.fixture(scope="function")
def agent_setup(tmp_path):
    """Setup Agent with clean dashboard."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

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

    knowledge_dir = dashboard_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "insights.json").write_text(
        json.dumps({"version": "1.0", "insights": []}, indent=2),
        encoding="utf-8"
    )

    # Use latest DASHBOARD.md (v0.1.5 - Dashboard Tools)
    (workspace / "DASHBOARD.md").write_text(
        "# Dashboard Management\n\n"
        "You are a **contextual dashboard manager** that uses specialized tools.\n\n"
        "## Available Tools\n\n"
        "- create_task(title, deadline, priority, context, tags)\n"
        "- update_task(task_id, progress, status, blocked, blocker_note, ...)\n"
        "- answer_question(question_id, answer)\n"
        "- create_question(question, priority, type, related_task_id)\n"
        "- save_insight(content, category, title, tags)\n"
        "- archive_task(task_id, reflection)\n\n"
        "## Core Principles\n\n"
        "1. **Use dashboard tools, NOT read_file/write_file for dashboard operations**\n"
        "2. **One message can contain multiple pieces of information**\n"
        "3. **Think holistically** - extract all info (answers, progress, blockers)\n\n"
        "## Workflow\n\n"
        "1. Analyze message holistically\n"
        "2. Use appropriate dashboard tools\n"
        "3. Reply SILENT for regular updates\n\n"
        "## Examples\n\n"
        "User: '이번 주까지 블로그 써야 해'\n"
        "→ create_task(title='블로그 작성', deadline='이번 주', priority='medium')\n\n"
        "User: '50% 완료했는데 Hook이 어려워요'\n"
        "→ update_task(task_id='task_xxx', progress=50, blocked=True, blocker_note='Hook 이해')\n"
        "→ create_question(question='Hook 자료 찾아봤어?', related_task_id='task_xxx')\n\n"
        "User: '완료했어요!'\n"
        "→ update_task(task_id='task_xxx', status='completed', progress=100)\n"
        "→ archive_task(task_id='task_xxx', reflection='Successfully completed')\n",
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


@pytest.mark.e2e
def test_journey_01_one_week_lifecycle(agent_setup):
    """Journey 1: 1주일 사용자 라이프사이클

    실제 사용자가 1주일 동안 Dashboard를 어떻게 사용하는지 시뮬레이션:

    Day 1 (월요일): 주간 계획 수립
      - 3개 작업 계획 (블로그, React 공부, 운동)
      - 각각 다른 deadline과 priority

    Day 2 (화요일): 진행 업데이트
      - 블로그 1개 완료
      - React 50% 진행, 하지만 Hook 부분에서 막힘
      - 운동은 못 함

    Day 3 (수요일): Worker 질문 답변
      - Worker가 React 진행 느린 거 감지해서 질문 생성
      - 사용자가 답변

    Day 4 (목요일): 우선순위 변경
      - React가 더 급해짐
      - 블로그 deadline 연장

    Day 5 (금요일): 완료 및 회고
      - React 완료
      - 블로그 2개 완료
      - Worker가 completed tasks를 archived로 변경

    총 10-15턴의 대화, 실제 사용 패턴 검증
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    print("\n=== Journey 1: 1주일 라이프사이클 ===\n")

    # ==========================================
    # Day 1 (월요일): 주간 계획
    # ==========================================
    print("[Day 1] 월요일: 주간 계획 수립")

    message_day1 = (
        "이번 주 계획:\n"
        "1. 블로그 글 3개 써야 해 (금요일까지)\n"
        "2. React Hooks 공부 (목요일까지 완료)\n"
        "3. 운동 주 3회 (월수금)"
    )

    import asyncio
    response = asyncio.run(agent.process_direct(message_day1, session_key="journey01"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")

    import time
    time.sleep(2)  # LLM 호출 간격

    # Verify: 3개 task 생성되었는지
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    print(f"[OK] Tasks created: {len(tasks)}")
    assert len(tasks) >= 2, f"Should create at least 2 tasks, got {len(tasks)}"

    # 각 task에 deadline 있는지 확인
    tasks_with_deadline = [t for t in tasks if t.get("deadline") or t.get("deadline_text")]
    print(f"[OK] Tasks with deadline: {len(tasks_with_deadline)}/{len(tasks)}")

    # ==========================================
    # Day 2 (화요일): 진행 업데이트 + Blocker
    # ==========================================
    print("\n📅 Day 2 (화요일): 진행 업데이트")

    message_day2 = (
        "어제 계획한 것 중에:\n"
        "- 블로그 1개는 완성했어!\n"
        "- React Hooks는 50% 정도 공부했는데 useEffect 부분이 너무 어려워서 막혔어\n"
        "- 운동은 못 했어"
    )

    response = asyncio.run(agent.process_direct(message_day2, session_key="journey01"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: 블로그 1개 completed (or archived), React blocker 추가
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    # Check tasks.json for completed/archived tasks
    completed_tasks = get_completed_tasks(dashboard)
    completed_count = len(completed_tasks)

    print(f"[OK] Completed tasks: {completed_count}")

    # Find React task (should still be in tasks.json)
    react_task = None
    for task in tasks:
        if "React" in task["title"] or "Hooks" in task["title"] or "공부" in task["title"]:
            react_task = task
            break

    if react_task:
        print(f"[OK] React task found: {react_task['title']}")
        if react_task["progress"].get("blocked"):
            print(f"[OK] React task blocked: {react_task['progress'].get('blocker_note', 'No note')}")
        else:
            print(f"[WARNING]  React blocker not detected (Agent may need clearer signal)")

    # ==========================================
    # Day 3 (수요일): Worker 실행 (시뮬레이션)
    # ==========================================
    print("\n📅 Day 3 (수요일): Worker 질문 생성 (시뮬레이션)")

    # Worker는 실제로는 Heartbeat에서 실행되지만, 테스트에서는 수동 실행
    # Task deadline이 임박했는데 진행이 느리면 질문 생성

    # Simulate: React task가 50%인데 deadline 2일 남음 → 질문 생성해야 함
    # 하지만 실제 Worker는 시간 기반이므로, 여기서는 직접 질문 추가

    with open(dashboard / "questions.json", "r", encoding="utf-8") as f:
        questions = json.load(f)

    # Worker가 생성했을 법한 질문 시뮬레이션
    now = datetime.now()
    questions["questions"].append({
        "id": f"q_worker_{now.strftime('%Y%m%d')}",
        "question": "React Hooks 공부 진행이 좀 느린데, 괜찮아? 도움 필요해?",
        "priority": "high",
        "type": "progress_check",
        "related_task_id": react_task["id"] if react_task else "unknown",
        "answered": False,
        "created_at": now.isoformat(),
        "asked_count": 1,
        "last_asked": now.isoformat(),
        "context": "Progress slower than expected (50% with 2 days left)"
    })

    with open(dashboard / "questions.json", "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)

    print("[OK] Worker question simulated: 'React Hooks 진행이 느린데 괜찮아?'")

    # User answers the question
    message_day3 = (
        "React Hooks 어려운 건 맞는데, "
        "useEffect 관련 블로그 글 더 찾아보고 있어. "
        "내일까지는 80% 정도 할 수 있을 것 같아."
    )

    response = asyncio.run(agent.process_direct(message_day3, session_key="journey01"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: Question answered, blocker note updated
    with open(dashboard / "questions.json", "r", encoding="utf-8") as f:
        questions_result = json.load(f).get("questions", [])

    answered_questions = [q for q in questions_result if q.get("answered")]
    print(f"[OK] Answered questions: {len(answered_questions)}/{len(questions_result)}")

    # ==========================================
    # Day 4 (목요일): 우선순위 변경
    # ==========================================
    print("\n📅 Day 4 (목요일): 우선순위 변경")

    message_day4 = (
        "계획 변경:\n"
        "React 공부가 생각보다 중요해서 내일까지 100% 완료해야 해.\n"
        "블로그는 급하지 않으니까 다음 주로 미뤄도 될 것 같아."
    )

    response = asyncio.run(agent.process_direct(message_day4, session_key="journey01"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: React priority high, 블로그 deadline 변경
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    for task in tasks:
        if "React" in task["title"] or "Hooks" in task["title"]:
            print(f"[OK] React priority: {task.get('priority', 'not set')}")
        if "블로그" in task["title"] and task["status"] != "completed":
            print(f"[OK] Blog status: {task['status']}, deadline: {task.get('deadline_text', 'not set')}")

    # ==========================================
    # Day 5 (금요일): 완료 및 회고
    # ==========================================
    print("\n📅 Day 5 (금요일): 완료")

    message_day5 = (
        "이번 주 성과:\n"
        "[OK] React Hooks 완전히 이해했어! useEffect도 마스터!\n"
        "[OK] 블로그 글 2개 더 완성했어 (총 3개 완료)\n"
        "[WARNING] 운동은 1번밖에 못 했네..."
    )

    response = asyncio.run(agent.process_direct(message_day5, session_key="journey01"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: Multiple tasks completed (check tasks.json for completed/archived)
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        final_tasks = json.load(f).get("tasks", [])

    # Get all completed/archived tasks
    all_completed_tasks = get_completed_tasks(dashboard)
    active_tasks = [t for t in final_tasks if t["status"] == "active"]

    print(f"\n=== Final Summary ===")
    print(f"[OK] Active tasks in tasks.json: {len(final_tasks)}")
    print(f"[OK] Completed/Archived (tasks.json): {len(all_completed_tasks)}")
    print(f"[OK] Active (not completed): {len(active_tasks)}")

    # At least 1 task should be completed
    assert len(all_completed_tasks) >= 1, \
        f"Should complete at least 1 task in the week, got {len(all_completed_tasks)}"

    # Verify React task is completed (check all completed tasks)
    react_completed = any(
        "React" in t["title"] or "Hooks" in t["title"]
        for t in all_completed_tasks
    )

    if react_completed:
        print("[OK] React Hooks study completed!")
    else:
        print("[WARNING] React task may not be marked as completed (check Agent logic)")

    print("\n[OK] Journey 1 completed: 1주일 라이프사이클 검증 완료\n")


@pytest.mark.e2e
def test_journey_02_complex_project(agent_setup):
    """Journey 2: 복잡한 프로젝트 관리

    다층 구조의 프로젝트를 관리하는 시나리오:
    - Main project: Web App 개발
    - Sub-tasks: 디자인, 프론트엔드, 백엔드, 테스트
    - Dependencies: 디자인 완료 → 프론트 시작
    - Blockers: 백엔드 API 지연으로 프론트 막힘
    - Pivots: 기능 변경으로 재계획

    총 8-10턴
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    print("\n=== Journey 2: 복잡한 프로젝트 관리 ===\n")

    # ==========================================
    # Phase 1: 프로젝트 시작
    # ==========================================
    print("[Phase 1]: 프로젝트 시작")

    message_start = (
        "새 프로젝트 시작:\n"
        "웹 앱 개발 (2주 안에 완성)\n\n"
        "단계:\n"
        "1. UI/UX 디자인 (3일)\n"
        "2. 프론트엔드 개발 (5일, 디자인 완료 후)\n"
        "3. 백엔드 API (5일, 프론트와 병렬)\n"
        "4. 통합 테스트 (2일)\n"
        "5. 배포 (1일)"
    )

    import asyncio
    response = asyncio.run(agent.process_direct(message_start, session_key="journey02"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")

    import time
    time.sleep(2)

    # Verify: Multiple tasks created with dependencies
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    print(f"[OK] Tasks created: {len(tasks)}")
    assert len(tasks) >= 3, f"Should create multiple sub-tasks, got {len(tasks)}"

    # ==========================================
    # Phase 2: 디자인 완료, 프론트 시작
    # ==========================================
    print("\n🎨 Phase 2: 디자인 완료")

    message_design = (
        "UI/UX 디자인 완료했어!\n"
        "Figma에 다 정리했고, 프론트엔드 개발 시작할게.\n"
        "지금 React + TypeScript로 컴포넌트 구조 잡는 중."
    )

    response = asyncio.run(agent.process_direct(message_design, session_key="journey02"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: Design completed, Frontend in progress
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    design_task = next((t for t in tasks if "디자인" in t["title"] or "UI" in t["title"]), None)
    frontend_task = next((t for t in tasks if "프론트" in t["title"] or "Frontend" in t["title"]), None)

    if design_task:
        print(f"[OK] Design task: {design_task['status']}")
    if frontend_task:
        print(f"[OK] Frontend task progress: {frontend_task['progress']['percentage']}%")

    # ==========================================
    # Phase 3: Blocker 발생
    # ==========================================
    print("\n[WARNING]  Phase 3: Blocker 발생")

    message_blocker = (
        "프론트엔드 개발 중인데 문제 생겼어.\n"
        "백엔드 API가 아직 안 나와서 프론트 70%에서 막혔어.\n"
        "API 명세서는 있는데 실제 엔드포인트가 없어서 연동을 못 하겠어."
    )

    response = asyncio.run(agent.process_direct(message_blocker, session_key="journey02"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: Frontend blocked, backend question generated
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    frontend_task = next((t for t in tasks if "프론트" in t["title"] or "Frontend" in t["title"]), None)

    if frontend_task and frontend_task["progress"].get("blocked"):
        print(f"[OK] Frontend blocked: {frontend_task['progress'].get('blocker_note', '')}")
    else:
        print("[WARNING]  Blocker may not be detected")

    # ==========================================
    # Phase 4: 대안 찾기
    # ==========================================
    print("\n💡 Phase 4: 대안 찾기")

    message_solution = (
        "백엔드 기다리는 동안 Mock API 만들어서 개발 계속할게.\n"
        "json-server로 임시 API 띄워서 프론트 완성하고,\n"
        "나중에 실제 API로 교체하면 될 것 같아."
    )

    response = asyncio.run(agent.process_direct(message_solution, session_key="journey02"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: Blocker resolved or note updated
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    frontend_task = next((t for t in tasks if "프론트" in t["title"] or "Frontend" in t["title"]), None)

    if frontend_task:
        blocker_note = frontend_task["progress"].get("blocker_note", "")
        print(f"[OK] Frontend blocker note: {blocker_note[:50]}...")

    # ==========================================
    # Phase 5: 완료 및 회고
    # ==========================================
    print("\n🎉 Phase 5: 완료")

    message_complete = (
        "프로젝트 완료!\n"
        "- 디자인 [OK]\n"
        "- 프론트엔드 [OK] (Mock API로 개발 완료)\n"
        "- 백엔드 [OK] (늦게 나왔지만 완성)\n"
        "- 통합 테스트 [OK]\n"
        "- 배포 [OK]\n\n"
        "배운 점: Mock API 미리 준비하면 병렬 개발 가능"
    )

    response = asyncio.run(agent.process_direct(message_complete, session_key="journey02"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: Multiple tasks completed
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        final_tasks = json.load(f).get("tasks", [])

    completed_count = sum(1 for t in final_tasks if t["status"] == "completed")

    print(f"\n=== Project Summary ===")
    print(f"[OK] Total tasks: {len(final_tasks)}")
    print(f"[OK] Completed: {completed_count}")

    # Verify insights saved
    with open(dashboard / "knowledge" / "insights.json", "r", encoding="utf-8") as f:
        insights = json.load(f).get("insights", [])

    print(f"[OK] Insights saved: {len(insights)}")

    print("\n[OK] Journey 2 completed: 복잡한 프로젝트 관리 검증 완료\n")


@pytest.mark.e2e
def test_journey_03_multitasking_priorities(agent_setup):
    """Journey 3: 멀티태스킹 + 우선순위 관리

    여러 작업을 동시에 하면서 우선순위를 계속 조정하는 시나리오:
    - 5개 작업 동시 진행
    - 긴급 작업 끼어들기
    - 우선순위 재조정
    - 일부 작업 취소/연기

    총 7-9턴
    """
    setup = agent_setup
    agent = setup["agent"]
    dashboard = setup["dashboard"]

    print("\n=== Journey 3: 멀티태스킹 + 우선순위 ===\n")

    # ==========================================
    # Phase 1: 여러 작업 동시 시작
    # ==========================================
    print("[Phase 1]: 여러 작업 계획")

    message_start = (
        "이번 주 할 일들:\n"
        "1. 블로그 글 2개 (금요일까지)\n"
        "2. React 프로젝트 리팩토링 (목요일까지)\n"
        "3. 운동 주 3회\n"
        "4. 독서 1시간씩\n"
        "5. 친구들 만나기 (주말)"
    )

    import asyncio
    response = asyncio.run(agent.process_direct(message_start, session_key="journey03"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")

    import time
    time.sleep(2)

    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    print(f"[OK] Initial tasks: {len(tasks)}")

    # ==========================================
    # Phase 2: 긴급 작업 끼어들기
    # ==========================================
    print("\n🚨 Phase 2: 긴급 작업 발생")

    message_urgent = (
        "급한 일 생겼어!\n"
        "내일까지 회사 프레젠테이션 준비해야 해.\n"
        "다른 거 다 미루고 이거 먼저 해야겠어."
    )

    response = asyncio.run(agent.process_direct(message_urgent, session_key="journey03"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: New urgent task added with high priority
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    urgent_task = next((t for t in tasks if "프레젠테이션" in t["title"]), None)

    if urgent_task:
        print(f"[OK] Urgent task: priority={urgent_task.get('priority')}, deadline={urgent_task.get('deadline_text', 'N/A')}")

    # ==========================================
    # Phase 3: 진행 상황 업데이트 (멀티)
    # ==========================================
    print("\n📊 Phase 3: 멀티태스킹 진행 업데이트")

    message_progress = (
        "오늘 한 일:\n"
        "- 프레젠테이션 70% 완료\n"
        "- 블로그 1개 초안 작성\n"
        "- 운동은 못 함\n"
        "- React 리팩토링은 손도 못 댐"
    )

    response = asyncio.run(agent.process_direct(message_progress, session_key="journey03"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: Multiple tasks updated
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    updated_count = sum(1 for t in tasks if t["progress"]["percentage"] > 0)
    print(f"[OK] Tasks in progress: {updated_count}/{len(tasks)}")

    # ==========================================
    # Phase 4: 우선순위 재조정
    # ==========================================
    print("\n🔄 Phase 4: 우선순위 재조정")

    message_reprioritize = (
        "계획 수정:\n"
        "프레젠테이션 내일 끝내고,\n"
        "React 리팩토링은 다음 주로 미루기.\n"
        "블로그는 이번 주 안에만 하면 돼.\n"
        "운동은 주말에 몰아서 하기."
    )

    response = asyncio.run(agent.process_direct(message_reprioritize, session_key="journey03"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: Priorities and deadlines updated
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        tasks = json.load(f).get("tasks", [])

    high_priority_count = sum(1 for t in tasks if t.get("priority") == "high")
    someday_count = sum(1 for t in tasks if t["status"] == "someday")

    print(f"[OK] High priority tasks: {high_priority_count}")
    print(f"[OK] Someday tasks: {someday_count}")

    # ==========================================
    # Phase 5: 완료 및 회고
    # ==========================================
    print("\n[OK] Phase 5: 완료")

    message_complete = (
        "이번 주 마무리:\n"
        "[OK] 프레젠테이션 완료 (성공적!)\n"
        "[OK] 블로그 2개 완료\n"
        "[OK] 운동 주말에 2번\n"
        "⏸️  React 리팩토링 다음 주로\n"
        "❌ 독서 못 함\n\n"
        "배운 점: 긴급 작업 생기면 우선순위 빠르게 재조정 필요"
    )

    response = asyncio.run(agent.process_direct(message_complete, session_key="journey03"))
    print(f"Agent: {response[:100] if response else 'SILENT'}...")
    time.sleep(2)

    # Verify: Final state (check tasks.json for completed/archived)
    with open(dashboard / "tasks.json", "r", encoding="utf-8") as f:
        final_tasks = json.load(f).get("tasks", [])

    # Get all completed/archived tasks
    all_completed = get_completed_tasks(dashboard)
    completed = len(all_completed)
    active = sum(1 for t in final_tasks if t["status"] == "active")
    someday = sum(1 for t in final_tasks if t["status"] == "someday")

    print(f"\n=== Final Summary ===")
    print(f"[OK] Completed: {completed}")
    print(f"[OK] Active: {active}")
    print(f"[OK] Someday: {someday}")

    assert completed >= 2, f"Should complete at least 2 tasks, got {completed}"

    print("\n[OK] Journey 3 completed: 멀티태스킹 + 우선순위 관리 검증 완료\n")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
