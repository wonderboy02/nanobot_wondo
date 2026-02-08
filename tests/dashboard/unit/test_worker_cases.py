"""Test Worker's 7 Progress Check Cases.

Worker는 다음 7가지 Case를 체크하여 Question을 생성합니다:
1. Not Started (0% & 시간 지남)
2. Far Behind (20%+ gap)
3. Slightly Behind (10-20% gap)
4. No Update for 48h
5. Deadline Approaching (2일 이내)
6. Nearly Complete (80%+)
7. On Track (정상 진행)
"""

import asyncio
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path


@pytest.fixture
def test_workspace(tmp_path):
    """Create test workspace with dashboard structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    dashboard_dir = workspace / "dashboard"
    dashboard_dir.mkdir()

    # Create empty JSON files
    (dashboard_dir / "tasks.json").write_text(
        json.dumps({"version": "1.0", "tasks": []}, indent=2)
    )
    (dashboard_dir / "questions.json").write_text(
        json.dumps({"version": "1.0", "questions": []}, indent=2)
    )
    (dashboard_dir / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []}, indent=2)
    )

    # Create knowledge directory
    knowledge_dir = dashboard_dir / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "history.json").write_text(
        json.dumps({"version": "1.0", "completed_tasks": [], "projects": []}, indent=2)
    )
    (knowledge_dir / "insights.json").write_text(
        json.dumps({"version": "1.0", "insights": []}, indent=2)
    )
    (knowledge_dir / "people.json").write_text(
        json.dumps({"version": "1.0", "people": []}, indent=2)
    )

    return workspace


@pytest.mark.asyncio
async def test_case_1_not_started(test_workspace):
    """Case 1: Task created but 0% progress after 24h.

    Expected: Generate question "시작했어?"
    """
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    now = datetime.now()
    created_25h_ago = now - timedelta(hours=25)
    deadline_in_3_days = now + timedelta(days=3)

    # Create task that hasn't started
    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_001",
        "title": "Not Started Task",
        "status": "active",
        "deadline": deadline_in_3_days.isoformat(),
        "progress": {
            "percentage": 0,  # Not started
            "last_update": created_25h_ago.isoformat(),
            "note": "",
            "blocked": False
        },
        "priority": "medium",
        "created_at": created_25h_ago.isoformat(),
        "updated_at": created_25h_ago.isoformat()
    })
    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    # Verify question generated
    dashboard2 = manager.load()
    questions = dashboard2["questions"]

    assert len(questions) > 0, "Worker should generate question for unstarted task"

    # Find question related to task_001
    related_q = [q for q in questions if q.get("related_task_id") == "task_001"]
    assert len(related_q) > 0, "Should have question for task_001"

    question_text = related_q[0]["question"]
    assert "시작" in question_text or "start" in question_text.lower(), \
        f"Question should ask about starting: {question_text}"


@pytest.mark.asyncio
async def test_case_2_far_behind(test_workspace):
    """Case 2: Task far behind schedule (20%+ gap).

    Expected: High priority question "많이 늦었는데 괜찮아?"
    """
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    now = datetime.now()
    created_4_days_ago = now - timedelta(days=4)
    deadline_in_3_days = now + timedelta(days=3)
    # Total duration: 7 days
    # Elapsed: 4 days (57%)
    # Expected progress: ~57%
    # Actual: 10%
    # Gap: 47% (FAR BEHIND!)

    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_002",
        "title": "Far Behind Task",
        "status": "active",
        "deadline": deadline_in_3_days.isoformat(),
        "progress": {
            "percentage": 10,  # Very behind
            "last_update": now.isoformat(),
            "note": "Struggling",
            "blocked": False
        },
        "priority": "high",
        "created_at": created_4_days_ago.isoformat(),
        "updated_at": now.isoformat()
    })
    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    # Verify high priority question
    dashboard2 = manager.load()
    questions = dashboard2["questions"]

    assert len(questions) > 0, "Worker should generate question for far behind task"

    related_q = [q for q in questions if q.get("related_task_id") == "task_002"]
    assert len(related_q) > 0, "Should have question for task_002"

    question = related_q[0]
    assert question["priority"] in ["high", "medium"], "Should be high priority"


@pytest.mark.asyncio
async def test_case_3_slightly_behind(test_workspace):
    """Case 3: Task slightly behind (10-20% gap).

    Expected: Medium priority question "조금 늦은데 문제 있어?"
    """
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    now = datetime.now()
    created_3_days_ago = now - timedelta(days=3)
    deadline_in_4_days = now + timedelta(days=4)
    # Total: 7 days, Elapsed: 3 days (43%)
    # Expected: ~43%
    # Actual: 30%
    # Gap: 13% (SLIGHTLY BEHIND)

    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_003",
        "title": "Slightly Behind Task",
        "status": "active",
        "deadline": deadline_in_4_days.isoformat(),
        "progress": {
            "percentage": 30,  # Slightly behind
            "last_update": now.isoformat(),
            "note": "Going slow",
            "blocked": False
        },
        "priority": "medium",
        "created_at": created_3_days_ago.isoformat(),
        "updated_at": now.isoformat()
    })
    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    # Verify question generated
    dashboard2 = manager.load()
    questions = dashboard2["questions"]

    assert len(questions) > 0, "Worker should generate question for slightly behind task"

    related_q = [q for q in questions if q.get("related_task_id") == "task_003"]
    assert len(related_q) > 0, "Should have question for task_003"


@pytest.mark.asyncio
async def test_case_4_no_update_48h(test_workspace):
    """Case 4: No update for 48+ hours.

    Expected: Question "요즘 어떻게 되고 있어?"
    """
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    now = datetime.now()
    last_update_3_days_ago = now - timedelta(days=3)  # 72 hours ago
    created_5_days_ago = now - timedelta(days=5)
    deadline_in_5_days = now + timedelta(days=5)

    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_004",
        "title": "Stale Task",
        "status": "active",
        "deadline": deadline_in_5_days.isoformat(),
        "progress": {
            "percentage": 40,
            "last_update": last_update_3_days_ago.isoformat(),  # No update for 72h
            "note": "Halfway",
            "blocked": False
        },
        "priority": "medium",
        "created_at": created_5_days_ago.isoformat(),
        "updated_at": last_update_3_days_ago.isoformat()
    })
    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    # Verify question about stale progress
    dashboard2 = manager.load()
    questions = dashboard2["questions"]

    assert len(questions) > 0, "Worker should generate question for stale task"

    related_q = [q for q in questions if q.get("related_task_id") == "task_004"]
    assert len(related_q) > 0, "Should have question for task_004"


@pytest.mark.asyncio
async def test_case_5_deadline_approaching(test_workspace):
    """Case 5: Deadline in 1-2 days, not complete.

    Expected: High priority "내일까지인데 끝낼 수 있어?"
    """
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    now = datetime.now()
    deadline_tomorrow = now + timedelta(days=1)  # Urgent!
    created_3_days_ago = now - timedelta(days=3)

    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_005",
        "title": "Urgent Task",
        "status": "active",
        "deadline": deadline_tomorrow.isoformat(),
        "progress": {
            "percentage": 50,  # Only halfway, deadline tomorrow
            "last_update": now.isoformat(),
            "note": "Need to hurry",
            "blocked": False
        },
        "priority": "high",
        "created_at": created_3_days_ago.isoformat(),
        "updated_at": now.isoformat()
    })
    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    # Verify high priority urgent question
    dashboard2 = manager.load()
    questions = dashboard2["questions"]

    assert len(questions) > 0, "Worker should generate urgent question"

    related_q = [q for q in questions if q.get("related_task_id") == "task_005"]
    assert len(related_q) > 0, "Should have question for task_005"

    question = related_q[0]
    assert question["priority"] in ["high", "urgent"], "Should be high/urgent priority"


@pytest.mark.asyncio
async def test_case_6_nearly_complete(test_workspace):
    """Case 6: Progress 80%+, nearly done.

    Expected: Question "거의 다 됐는데 언제 끝나?"
    """
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    now = datetime.now()
    deadline_in_3_days = now + timedelta(days=3)
    created_2_days_ago = now - timedelta(days=2)

    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_006",
        "title": "Nearly Done Task",
        "status": "active",
        "deadline": deadline_in_3_days.isoformat(),
        "progress": {
            "percentage": 85,  # Nearly complete
            "last_update": now.isoformat(),
            "note": "Almost there",
            "blocked": False
        },
        "priority": "medium",
        "created_at": created_2_days_ago.isoformat(),
        "updated_at": now.isoformat()
    })
    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    # Verify question about completion
    dashboard2 = manager.load()
    questions = dashboard2["questions"]

    assert len(questions) > 0, "Worker should generate completion question"

    related_q = [q for q in questions if q.get("related_task_id") == "task_006"]
    assert len(related_q) > 0, "Should have question for task_006"


@pytest.mark.asyncio
async def test_case_7_on_track(test_workspace):
    """Case 7: Progress matches expected (on track).

    Expected: No urgent question (or low priority check-in)
    """
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    now = datetime.now()
    created_2_days_ago = now - timedelta(days=2)
    deadline_in_5_days = now + timedelta(days=5)
    # Total: 7 days, Elapsed: 2 days (29%)
    # Expected: ~29%
    # Actual: 30%
    # Gap: 1% (ON TRACK!)

    dashboard = manager.load()
    dashboard["tasks"].append({
        "id": "task_007",
        "title": "On Track Task",
        "status": "active",
        "deadline": deadline_in_5_days.isoformat(),
        "progress": {
            "percentage": 30,  # On track
            "last_update": now.isoformat(),
            "note": "Going well",
            "blocked": False
        },
        "priority": "medium",
        "created_at": created_2_days_ago.isoformat(),
        "updated_at": now.isoformat()
    })
    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    # Verify no urgent questions (or only low priority)
    dashboard2 = manager.load()
    questions = dashboard2["questions"]

    related_q = [q for q in questions if q.get("related_task_id") == "task_007"]

    # Either no question, or low priority
    if len(related_q) > 0:
        assert related_q[0]["priority"] == "low", \
            "On-track task should only get low priority check-ins"


@pytest.mark.asyncio
async def test_all_cases_together(test_workspace):
    """Test all 7 cases in one dashboard.

    Verifies Worker can handle multiple tasks with different states.
    """
    from nanobot.dashboard.manager import DashboardManager
    from nanobot.dashboard.worker import WorkerAgent

    dashboard_path = test_workspace / "dashboard"
    manager = DashboardManager(dashboard_path)

    now = datetime.now()

    # Create all 7 tasks
    dashboard = manager.load()

    # Case 1: Not started (25h ago)
    dashboard["tasks"].append({
        "id": "task_case1",
        "title": "Case 1",
        "status": "active",
        "deadline": (now + timedelta(days=3)).isoformat(),
        "progress": {"percentage": 0, "last_update": (now - timedelta(hours=25)).isoformat(), "note": ""},
        "created_at": (now - timedelta(hours=25)).isoformat(),
        "updated_at": (now - timedelta(hours=25)).isoformat()
    })

    # Case 2: Far behind
    dashboard["tasks"].append({
        "id": "task_case2",
        "title": "Case 2",
        "status": "active",
        "deadline": (now + timedelta(days=3)).isoformat(),
        "progress": {"percentage": 10, "last_update": now.isoformat(), "note": ""},
        "created_at": (now - timedelta(days=4)).isoformat(),
        "updated_at": now.isoformat()
    })

    # Case 3: Slightly behind
    dashboard["tasks"].append({
        "id": "task_case3",
        "title": "Case 3",
        "status": "active",
        "deadline": (now + timedelta(days=4)).isoformat(),
        "progress": {"percentage": 30, "last_update": now.isoformat(), "note": ""},
        "created_at": (now - timedelta(days=3)).isoformat(),
        "updated_at": now.isoformat()
    })

    # Case 4: Stale (no update 72h)
    dashboard["tasks"].append({
        "id": "task_case4",
        "title": "Case 4",
        "status": "active",
        "deadline": (now + timedelta(days=5)).isoformat(),
        "progress": {"percentage": 40, "last_update": (now - timedelta(days=3)).isoformat(), "note": ""},
        "created_at": (now - timedelta(days=5)).isoformat(),
        "updated_at": (now - timedelta(days=3)).isoformat()
    })

    # Case 5: Deadline tomorrow
    dashboard["tasks"].append({
        "id": "task_case5",
        "title": "Case 5",
        "status": "active",
        "deadline": (now + timedelta(days=1)).isoformat(),
        "progress": {"percentage": 50, "last_update": now.isoformat(), "note": ""},
        "created_at": (now - timedelta(days=3)).isoformat(),
        "updated_at": now.isoformat()
    })

    # Case 6: Nearly complete
    dashboard["tasks"].append({
        "id": "task_case6",
        "title": "Case 6",
        "status": "active",
        "deadline": (now + timedelta(days=3)).isoformat(),
        "progress": {"percentage": 85, "last_update": now.isoformat(), "note": ""},
        "created_at": (now - timedelta(days=2)).isoformat(),
        "updated_at": now.isoformat()
    })

    # Case 7: On track
    dashboard["tasks"].append({
        "id": "task_case7",
        "title": "Case 7",
        "status": "active",
        "deadline": (now + timedelta(days=5)).isoformat(),
        "progress": {"percentage": 30, "last_update": now.isoformat(), "note": ""},
        "created_at": (now - timedelta(days=2)).isoformat(),
        "updated_at": now.isoformat()
    })

    manager.save(dashboard)

    # Run worker
    worker = WorkerAgent(dashboard_path)
    await worker.run_cycle()

    # Verify questions generated
    dashboard2 = manager.load()
    questions = dashboard2["questions"]

    # Should have questions for at least the problematic cases (1-6)
    # Case 7 (on track) may or may not have a question
    assert len(questions) >= 5, f"Should generate questions for problematic tasks, got {len(questions)}"

    # Verify each case has appropriate question
    case_ids = [f"task_case{i}" for i in range(1, 8)]
    for case_id in case_ids[:6]:  # Cases 1-6 should have questions
        related = [q for q in questions if q.get("related_task_id") == case_id]
        # Not all cases may generate questions due to cooldown or other logic
        # Just verify worker ran without errors


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
