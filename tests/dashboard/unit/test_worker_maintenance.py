"""Test Worker deterministic maintenance logic.

Tests the Phase 1 maintenance methods that always run:
- _archive_completed_tasks
- _reevaluate_active_status
- _cleanup_answered_questions
"""

import json
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def test_workspace(tmp_path):
    """Create test workspace with dashboard structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    dashboard_dir = workspace / "dashboard"
    dashboard_dir.mkdir()

    (dashboard_dir / "tasks.json").write_text(json.dumps({"version": "1.0", "tasks": []}, indent=2))
    (dashboard_dir / "questions.json").write_text(
        json.dumps({"version": "1.0", "questions": []}, indent=2)
    )
    (dashboard_dir / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []}, indent=2)
    )

    knowledge_dir = dashboard_dir / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "insights.json").write_text(
        json.dumps({"version": "1.0", "insights": []}, indent=2)
    )

    return workspace


# ============================================================================
# Archive Tests
# ============================================================================


@pytest.mark.asyncio
async def test_archive_completed_task(test_workspace):
    """Completed task should be archived with progress=100%."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_001",
            "title": "Done Task",
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

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "archived"
    assert result["tasks"][0]["progress"]["percentage"] == 100


@pytest.mark.asyncio
async def test_archive_cancelled_task_preserves_progress(test_workspace):
    """Cancelled task should be archived but keep original progress."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_002",
            "title": "Cancelled Task",
            "status": "cancelled",
            "created_at": (now - timedelta(days=1)).isoformat(),
            "updated_at": now.isoformat(),
            "progress": {
                "percentage": 40,
                "last_update": now.isoformat(),
            },
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "archived"
    assert result["tasks"][0]["progress"]["percentage"] == 40


@pytest.mark.asyncio
async def test_archive_does_not_touch_active_tasks(test_workspace):
    """Active tasks should NOT be archived."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_003",
            "title": "Active Task",
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "progress": {
                "percentage": 50,
                "last_update": now.isoformat(),
            },
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"


# ============================================================================
# Reevaluate Status Tests
# ============================================================================


@pytest.mark.asyncio
async def test_reevaluate_far_deadline_low_priority_becomes_someday(test_workspace):
    """Task with far deadline, low priority, no progress → someday."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()
    old_update = now - timedelta(days=10)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_far",
            "title": "Far Future Task",
            "status": "active",
            "deadline": (now + timedelta(days=30)).isoformat(),
            "priority": "low",
            "progress": {
                "percentage": 0,
                "last_update": old_update.isoformat(),
            },
            "created_at": old_update.isoformat(),
            "updated_at": old_update.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "someday"


@pytest.mark.asyncio
async def test_reevaluate_close_deadline_becomes_active(test_workspace):
    """Task with close deadline → active (even if someday)."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_soon",
            "title": "Due Soon Task",
            "status": "someday",
            "deadline": (now + timedelta(days=3)).isoformat(),
            "priority": "low",
            "progress": {
                "percentage": 0,
                "last_update": (now - timedelta(days=10)).isoformat(),
            },
            "created_at": (now - timedelta(days=10)).isoformat(),
            "updated_at": (now - timedelta(days=10)).isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_reevaluate_high_priority_stays_active(test_workspace):
    """High priority task stays active regardless of deadline."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()
    old_update = now - timedelta(days=10)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_high",
            "title": "High Priority Task",
            "status": "active",
            "priority": "high",
            "progress": {
                "percentage": 0,
                "last_update": old_update.isoformat(),
            },
            "created_at": old_update.isoformat(),
            "updated_at": old_update.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_reevaluate_with_progress_stays_active(test_workspace):
    """Task with any progress stays active."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()
    old_update = now - timedelta(days=10)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_prog",
            "title": "In Progress Task",
            "status": "active",
            "priority": "low",
            "progress": {
                "percentage": 20,
                "last_update": old_update.isoformat(),
            },
            "created_at": old_update.isoformat(),
            "updated_at": old_update.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_reevaluate_skips_archived(test_workspace):
    """Archived tasks should not be re-evaluated."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_archived",
            "title": "Archived Task",
            "status": "archived",
            "priority": "low",
            "progress": {
                "percentage": 100,
                "last_update": now.isoformat(),
            },
            "created_at": (now - timedelta(days=30)).isoformat(),
            "updated_at": now.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "archived"


# ============================================================================
# Question Cleanup Tests
# ============================================================================


@pytest.mark.asyncio
async def test_cleanup_removes_answered_questions(test_workspace):
    """_cleanup_answered_questions should remove answered questions."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    questions_data = {
        "questions": [
            {
                "id": "q_answered",
                "question": "Done?",
                "answered": True,
                "created_at": now.isoformat(),
            },
            {
                "id": "q_open",
                "question": "Still open?",
                "answered": False,
                "created_at": now.isoformat(),
            },
        ]
    }

    changed = worker._cleanup_answered_questions(questions_data)
    assert changed is True
    assert len(questions_data["questions"]) == 1
    assert questions_data["questions"][0]["id"] == "q_open"


@pytest.mark.asyncio
async def test_cleanup_removes_old_questions(test_workspace):
    """Questions older than 14 days should be removed."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_old",
            "question": "Ancient question?",
            "answered": False,
            "created_at": (now - timedelta(days=20)).isoformat(),
        },
        {
            "id": "q_recent",
            "question": "Recent question?",
            "answered": False,
            "created_at": (now - timedelta(days=5)).isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_questions()
    assert len(result["questions"]) == 1
    assert result["questions"][0]["id"] == "q_recent"


@pytest.mark.asyncio
async def test_cleanup_no_change_when_all_valid(test_workspace):
    """No changes when all questions are valid."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_valid",
            "question": "Valid question?",
            "answered": False,
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_questions()
    assert len(result["questions"]) == 1


# ============================================================================
# Combined Maintenance Tests
# ============================================================================


@pytest.mark.asyncio
async def test_maintenance_runs_without_llm(test_workspace):
    """Worker without LLM should still run task maintenance; answered questions preserved."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    # Set up tasks and questions
    tasks_data = backend.load_tasks()
    tasks_data["tasks"] = [
        {
            "id": "task_done",
            "title": "Done",
            "status": "completed",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "progress": {"percentage": 100, "last_update": now.isoformat()},
        },
        {
            "id": "task_active",
            "title": "Active",
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "progress": {"percentage": 50, "last_update": now.isoformat()},
        },
    ]
    backend.save_tasks(tasks_data)

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_done",
            "question": "Answered",
            "answered": True,
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    # No provider/model → Phase 2 skipped, answered question preserved
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    # Verify task maintenance ran
    tasks_result = backend.load_tasks()
    assert tasks_result["tasks"][0]["status"] == "archived"
    assert tasks_result["tasks"][1]["status"] == "active"

    # Answered question preserved (LLM not available to process it)
    questions_result = backend.load_questions()
    assert len(questions_result["questions"]) == 1
    assert questions_result["questions"][0]["id"] == "q_done"


# ============================================================================
# Extract Answered Questions Tests
# ============================================================================


@pytest.mark.asyncio
async def test_extract_answered_questions_returns_answered(test_workspace):
    """_extract_answered_questions should return questions with answered=True."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_answered",
            "question": "React Hook 어디까지?",
            "answered": True,
            "answer": "Chapter 5까지 완료",
            "related_task_id": "task_001",
            "type": "progress_check",
            "created_at": now.isoformat(),
        },
        {
            "id": "q_open",
            "question": "Still open?",
            "answered": False,
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    result = worker._extract_answered_questions()

    assert len(result) == 1
    assert result[0]["id"] == "q_answered"
    assert result[0]["answer"] == "Chapter 5까지 완료"


@pytest.mark.asyncio
async def test_extract_detects_answer_without_checkbox(test_workspace):
    """_extract_answered_questions should detect non-empty answer field even without answered=True."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_answer_only",
            "question": "블로그 진행?",
            "answered": False,
            "answer": "70% 완료",
            "created_at": now.isoformat(),
        },
        {
            "id": "q_nothing",
            "question": "No answer",
            "answered": False,
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    result = worker._extract_answered_questions()

    assert len(result) == 1
    assert result[0]["id"] == "q_answer_only"


@pytest.mark.asyncio
async def test_extract_handles_answer_none(test_workspace):
    """answer=None (create_question default) must not crash _extract or _cleanup."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_none_answer",
            "question": "Progress?",
            "answered": False,
            "answer": None,
            "created_at": now.isoformat(),
        },
        {
            "id": "q_checked_none",
            "question": "Done?",
            "answered": True,
            "answer": None,
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    # _extract should not raise and should detect only the answered=True one
    extracted = worker._extract_answered_questions()
    assert len(extracted) == 1
    assert extracted[0]["id"] == "q_checked_none"

    # _cleanup_answered_questions should not raise with None answer values
    data = {"questions": list(questions_data["questions"])}
    changed = worker._cleanup_answered_questions(data)
    assert changed is True
    assert len(data["questions"]) == 1
    assert data["questions"][0]["id"] == "q_none_answer"


@pytest.mark.asyncio
async def test_cleanup_runs_after_phase2(test_workspace):
    """Answered questions should still exist during Phase 2 (cleanup is deferred)."""
    from unittest.mock import AsyncMock, Mock, patch

    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent
    from nanobot.providers.base import LLMResponse

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    # Set up an answered question
    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_answered",
            "question": "Done?",
            "answered": True,
            "answer": "Yes, completed",
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    (test_workspace / "WORKER.md").write_text("# Worker\nYou are the Worker Agent.")

    mock_provider = AsyncMock()
    mock_provider.chat = AsyncMock(return_value=LLMResponse(content="Done.", tool_calls=[]))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    # Track when cleanup happens vs when LLM is called
    call_order = []
    original_cleanup = worker._cleanup_questions
    original_llm = worker._run_llm_cycle

    async def tracked_llm(pending_answers=None):
        # During LLM call, answered question should still be in storage
        q_data = backend.load_questions()
        call_order.append(("llm", len(q_data["questions"])))
        return await original_llm(pending_answers)

    async def tracked_cleanup(**kwargs):
        call_order.append(("cleanup_start", None))
        await original_cleanup(**kwargs)

    with (
        patch.object(worker, "_run_llm_cycle", side_effect=tracked_llm),
        patch.object(worker, "_cleanup_questions", side_effect=tracked_cleanup),
    ):
        await worker.run_cycle()

    # LLM was called before cleanup, and question was still present during LLM call
    assert call_order[0][0] == "llm"
    assert call_order[0][1] == 1  # question still exists
    assert call_order[1][0] == "cleanup_start"


@pytest.mark.asyncio
async def test_answered_preserved_when_llm_not_configured(test_workspace):
    """Answered questions must survive cleanup when LLM is not configured."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_answered",
            "question": "Done?",
            "answered": True,
            "answer": "Yes",
            "created_at": now.isoformat(),
        },
        {
            "id": "q_answered_old",
            "question": "Old answered?",
            "answered": True,
            "answer": "Done long ago",
            "created_at": (now - timedelta(days=20)).isoformat(),
        },
        {
            "id": "q_stale",
            "question": "Old unanswered?",
            "answered": False,
            "created_at": (now - timedelta(days=20)).isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    # No provider → Phase 2 skipped
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_questions()
    ids = [q["id"] for q in result["questions"]]
    # Both answered questions preserved (even old one), stale unanswered removed
    assert "q_answered" in ids
    assert "q_answered_old" in ids
    assert "q_stale" not in ids


@pytest.mark.asyncio
async def test_answered_preserved_when_llm_fails(test_workspace):
    """Answered questions must survive cleanup when LLM cycle raises."""
    from unittest.mock import AsyncMock

    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    (test_workspace / "WORKER.md").write_text("# Worker\nYou are the Worker Agent.")

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_answered",
            "question": "Done?",
            "answered": True,
            "answer": "Yes",
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    mock_provider = AsyncMock()
    mock_provider.chat = AsyncMock(side_effect=Exception("API down"))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )
    await worker.run_cycle()

    result = backend.load_questions()
    assert len(result["questions"]) == 1
    assert result["questions"][0]["id"] == "q_answered"


@pytest.mark.asyncio
async def test_answered_cleaned_after_successful_llm(test_workspace):
    """Answered questions should be cleaned up after successful LLM cycle."""
    from unittest.mock import AsyncMock

    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent
    from nanobot.providers.base import LLMResponse

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    (test_workspace / "WORKER.md").write_text("# Worker\nYou are the Worker Agent.")

    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_answered",
            "question": "Done?",
            "answered": True,
            "answer": "Yes",
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    mock_provider = AsyncMock()
    mock_provider.chat = AsyncMock(return_value=LLMResponse(content="Done.", tool_calls=[]))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )
    await worker.run_cycle()

    result = backend.load_questions()
    assert len(result["questions"]) == 0


@pytest.mark.asyncio
async def test_cleanup_preserves_overflow_beyond_cap(test_workspace):
    """Answered questions beyond MAX_ANSWERED_IN_CONTEXT should survive cleanup."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    # 25 answered questions + 1 unanswered
    questions = [
        {
            "id": f"q_{i}",
            "question": f"Question {i}?",
            "answered": True,
            "answer": f"Answer {i}",
            "created_at": now.isoformat(),
        }
        for i in range(25)
    ]
    questions.append(
        {
            "id": "q_open",
            "question": "Open?",
            "answered": False,
            "created_at": now.isoformat(),
        }
    )
    data = {"questions": questions}

    # Simulate processed_ids = first 20 (matching MAX_ANSWERED_IN_CONTEXT)
    processed_ids = {f"q_{i}" for i in range(20)}

    changed = worker._cleanup_answered_questions(data, processed_ids=processed_ids)
    assert changed is True

    remaining_ids = {q["id"] for q in data["questions"]}
    # First 20 answered removed, last 5 answered + 1 open preserved
    assert len(data["questions"]) == 6
    for i in range(20, 25):
        assert f"q_{i}" in remaining_ids
    assert "q_open" in remaining_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
