"""Test Worker LLM cycle with mocked provider.

Tests the Phase 2 LLM-powered analysis:
- Context building
- Tool registration
- LLM chat loop with tool calls
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_response(content: str, tool_calls: list[dict] | None = None) -> LLMResponse:
    """Build an LLMResponse from simplified dict spec."""
    tc_objects = []
    for tc in tool_calls or []:
        tc_objects.append(
            ToolCallRequest(
                id=tc.get("id", "call_1"),
                name=tc["name"],
                arguments=tc.get("arguments", {}),
            )
        )
    return LLMResponse(content=content, tool_calls=tc_objects)


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

    (workspace / "WORKER.md").write_text("# Worker Instructions\nYou are the Worker Agent.")

    return workspace


@pytest.mark.asyncio
async def test_llm_cycle_runs_when_provider_available(test_workspace):
    """LLM cycle should run when provider and model are provided."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()

    # LLM returns no tool calls (simple analysis)
    mock_provider.chat = AsyncMock(return_value=_make_response("No maintenance needed."))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    await worker.run_cycle()

    # Verify LLM was called
    mock_provider.chat.assert_called_once()

    # Verify context was built (check system message)
    call_args = mock_provider.chat.call_args
    messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
    assert any("Worker" in m.get("content", "") for m in messages)


@pytest.mark.asyncio
async def test_llm_cycle_skipped_without_provider(test_workspace):
    """LLM cycle should NOT run when provider is None."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        # No provider, no model
    )

    # Should not raise
    await worker.run_cycle()


@pytest.mark.asyncio
async def test_llm_cycle_with_tool_call(test_workspace):
    """LLM cycle should execute tool calls from LLM response."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()

    # Set up task with deadline
    now = datetime.now()
    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_001",
            "title": "블로그 작성",
            "status": "active",
            "deadline": (now + timedelta(days=1)).isoformat(),
            "priority": "high",
            "progress": {
                "percentage": 30,
                "last_update": now.isoformat(),
            },
            "created_at": (now - timedelta(days=3)).isoformat(),
            "updated_at": now.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    # LLM creates a question via tool call, then finishes
    mock_provider.chat = AsyncMock(
        side_effect=[
            _make_response(
                "Task behind schedule, creating question.",
                [
                    {
                        "id": "call_1",
                        "name": "create_question",
                        "arguments": {
                            "question": "블로그 작성 진행 어떻게 되고 있나요?",
                            "priority": "high",
                            "type": "progress_check",
                            "related_task_id": "task_001",
                        },
                    }
                ],
            ),
            _make_response("Question created successfully."),
        ]
    )

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    await worker.run_cycle()

    # Verify question was created
    questions_data = backend.load_questions()
    assert len(questions_data["questions"]) == 1
    assert "블로그" in questions_data["questions"][0]["question"]


@pytest.mark.asyncio
async def test_llm_cycle_handles_error_gracefully(test_workspace):
    """LLM cycle should handle provider errors gracefully."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()

    # LLM raises an error
    mock_provider.chat = AsyncMock(side_effect=Exception("API Error"))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    # Should not raise (error is caught and logged)
    await worker.run_cycle()


@pytest.mark.asyncio
async def test_context_includes_dashboard_summary(test_workspace):
    """Context building should include dashboard summary."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()

    # Add active task
    now = datetime.now()
    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_ctx",
            "title": "Context Test Task",
            "status": "active",
            "priority": "medium",
            "progress": {
                "percentage": 50,
                "last_update": now.isoformat(),
            },
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    mock_provider.chat = AsyncMock(return_value=_make_response("Analysis complete."))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    await worker.run_cycle()

    # Check that the task title appears in the context
    call_args = mock_provider.chat.call_args
    messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
    user_msg = next((m for m in messages if m["role"] == "user"), None)
    assert user_msg is not None
    assert "Context Test Task" in user_msg["content"]


@pytest.mark.asyncio
async def test_worker_tools_registered(test_workspace):
    """Worker should register expected tools for LLM cycle."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()

    mock_provider.chat = AsyncMock(return_value=_make_response("Done."))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    await worker.run_cycle()

    # Verify tools were registered
    expected_tools = {
        "create_question",
        "update_question",
        "remove_question",
        "schedule_notification",
        "update_notification",
        "cancel_notification",
        "list_notifications",
        "update_task",
        "archive_task",
    }
    registered = set(worker.tools.tool_names)
    assert expected_tools.issubset(registered), f"Missing tools: {expected_tools - registered}"


# ============================================================================
# _build_notifications_summary branch tests
# ============================================================================


@pytest.mark.asyncio
async def test_notifications_summary_empty(test_workspace):
    """_build_notifications_summary returns 'no notifications' when list is empty."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
    )

    result = worker._build_notifications_summary()
    assert "No notifications scheduled" in result


@pytest.mark.asyncio
async def test_notifications_summary_no_pending(test_workspace):
    """_build_notifications_summary returns 'no pending' when all are delivered."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    # Write directly to file (bypasses Pydantic validation for test simplicity)
    notif_file = test_workspace / "dashboard" / "notifications.json"
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_done",
                "message": "Already delivered",
                "scheduled_at": datetime.now().isoformat(),
                "type": "deadline_alert",
                "priority": "medium",
                "status": "delivered",
            }
        ],
    }
    notif_file.write_text(json.dumps(notif_data), encoding="utf-8")

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
    )

    result = worker._build_notifications_summary()
    assert "No pending notifications" in result


@pytest.mark.asyncio
async def test_notifications_summary_with_pending(test_workspace):
    """_build_notifications_summary lists pending notifications."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    # Write directly to file (bypasses Pydantic validation for test simplicity)
    notif_file = test_workspace / "dashboard" / "notifications.json"
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_pending",
                "message": "블로그 마감 알림",
                "scheduled_at": datetime.now().isoformat(),
                "type": "deadline_alert",
                "priority": "high",
                "status": "pending",
                "related_task_id": "task_001",
            }
        ],
    }
    notif_file.write_text(json.dumps(notif_data), encoding="utf-8")

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
    )

    result = worker._build_notifications_summary()
    assert "n_pending" in result
    assert "블로그 마감 알림" in result
    assert "task_001" in result


# ============================================================================
# Max iterations test
# ============================================================================


@pytest.mark.asyncio
async def test_llm_cycle_stops_at_max_iterations(test_workspace):
    """LLM cycle should stop after max_iterations even if LLM keeps calling tools."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()

    # LLM always returns a tool call (never stops on its own)
    mock_provider.chat = AsyncMock(
        return_value=_make_response(
            "Still working...",
            [
                {
                    "id": "call_loop",
                    "name": "list_notifications",
                    "arguments": {},
                }
            ],
        )
    )

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    await worker.run_cycle()

    # Should have been called exactly max_iterations (10) times
    assert mock_provider.chat.call_count == 10


# ============================================================================
# Tool execution error handling test
# ============================================================================


@pytest.mark.asyncio
async def test_llm_cycle_tool_error_returns_error_message(test_workspace):
    """Tool execution error should be returned to LLM as error message, not crash."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()

    # LLM calls a tool with invalid arguments, then finishes
    mock_provider.chat = AsyncMock(
        side_effect=[
            _make_response(
                "Updating non-existent task.",
                [
                    {
                        "id": "call_bad",
                        "name": "update_task",
                        "arguments": {
                            "task_id": "nonexistent_task",
                            "progress": 50,
                        },
                    }
                ],
            ),
            _make_response("Error acknowledged, stopping."),
        ]
    )

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    # Should not raise
    await worker.run_cycle()

    # LLM should have been called twice (tool call + follow-up)
    assert mock_provider.chat.call_count == 2

    # Second call should include tool result with error
    second_call_messages = mock_provider.chat.call_args_list[1].kwargs.get(
        "messages", mock_provider.chat.call_args_list[1][1].get("messages", [])
    )
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    # Tool result should contain error info (not crash)
    assert "Error" in tool_msgs[0]["content"] or "error" in tool_msgs[0]["content"]


# ============================================================================
# Maintenance no-change-no-save test
# ============================================================================


@pytest.mark.asyncio
async def test_maintenance_no_change_does_not_save(test_workspace):
    """When no maintenance changes occur, save should not be called."""
    from unittest.mock import patch

    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    # Add a valid active task with recent update (no change expected)
    now = datetime.now()
    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_stable",
            "title": "Stable Task",
            "status": "active",
            "priority": "medium",
            "progress": {
                "percentage": 50,
                "last_update": now.isoformat(),
            },
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    with (
        patch.object(backend, "save_tasks") as mock_save_tasks,
        patch.object(backend, "save_questions") as mock_save_questions,
    ):
        await worker.run_cycle()

        # No changes → save should not be called
        mock_save_tasks.assert_not_called()
        mock_save_questions.assert_not_called()


# ============================================================================
# Exception isolation test (Issue #6)
# ============================================================================


@pytest.mark.asyncio
async def test_maintenance_task_error_does_not_block_questions(test_workspace):
    """If task maintenance fails, question cleanup should still run."""
    from unittest.mock import patch

    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    # Add a stale question (14+ days old, should be cleaned up regardless of LLM)
    questions_data = backend.load_questions()
    questions_data["questions"].append(
        {
            "id": "q_stale",
            "question": "Old?",
            "answered": False,
            "created_at": (now - timedelta(days=20)).isoformat(),
        }
    )
    backend.save_questions(questions_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    # Make load_tasks raise — simulating storage failure
    with patch.object(backend, "load_tasks", side_effect=RuntimeError("Storage down")):
        await worker.run_cycle()

    # Question cleanup should still have run despite task error
    result = backend.load_questions()
    assert len(result["questions"]) == 0


# ============================================================================
# _build_notifications_summary exception path test (Issue #7)
# ============================================================================


@pytest.mark.asyncio
async def test_notifications_summary_handles_load_error(test_workspace):
    """_build_notifications_summary returns error message when load fails."""
    from unittest.mock import patch

    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
    )

    with patch.object(backend, "load_notifications", side_effect=RuntimeError("broken")):
        result = worker._build_notifications_summary()

    assert "Error loading notifications" in result


# ============================================================================
# _determine_status malformed deadline skip test (Issue #8)
# ============================================================================


@pytest.mark.asyncio
async def test_reevaluate_skips_malformed_deadline(test_workspace):
    """Task with malformed deadline should be skipped, not crash."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].extend(
        [
            {
                "id": "task_bad",
                "title": "Bad Deadline Task",
                "status": "active",
                "deadline": "not-a-date",
                "priority": "low",
                "progress": {
                    "percentage": 0,
                    "last_update": (now - timedelta(days=10)).isoformat(),
                },
                "created_at": (now - timedelta(days=10)).isoformat(),
                "updated_at": (now - timedelta(days=10)).isoformat(),
            },
            {
                "id": "task_good",
                "title": "Good Task",
                "status": "active",
                "deadline": (now + timedelta(days=2)).isoformat(),
                "priority": "low",
                "progress": {
                    "percentage": 0,
                    "last_update": (now - timedelta(days=10)).isoformat(),
                },
                "created_at": (now - timedelta(days=10)).isoformat(),
                "updated_at": (now - timedelta(days=10)).isoformat(),
            },
        ]
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    # Should not raise
    await worker.run_cycle()

    result = backend.load_tasks()
    # Good task should still be re-evaluated (deadline close → active)
    good = next(t for t in result["tasks"] if t["id"] == "task_good")
    assert good["status"] == "active"


# ============================================================================
# _build_context WORKER.md fallback test (Issue #9)
# ============================================================================


@pytest.mark.asyncio
async def test_context_uses_fallback_when_worker_md_missing(test_workspace):
    """Context should use inline fallback when load_instruction_file returns empty."""
    from unittest.mock import patch

    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    mock_provider.chat = AsyncMock(return_value=_make_response("Done."))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    # Mock load_instruction_file to return "" — simulates package default also missing
    with patch("nanobot.prompts.load_instruction_file", return_value=""):
        await worker.run_cycle()

    # Check that inline fallback system prompt was used
    call_args = mock_provider.chat.call_args
    messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
    system_msg = next((m for m in messages if m["role"] == "system"), None)
    assert system_msg is not None
    assert "Worker Agent" in system_msg["content"]
    assert "Phase 1" in system_msg["content"]


# ============================================================================
# Answered questions context tests
# ============================================================================


@pytest.mark.asyncio
async def test_context_includes_answered_questions(test_workspace):
    """LLM context should include answered questions summary."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    now = datetime.now()

    # Set up an answered question
    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_ans",
            "question": "React Hook 어디까지?",
            "answered": True,
            "answer": "Chapter 5까지 완료",
            "related_task_id": "task_001",
            "type": "progress_check",
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    mock_provider.chat = AsyncMock(return_value=_make_response("Processed answers."))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    await worker.run_cycle()

    # Check LLM context includes answered question details
    call_args = mock_provider.chat.call_args
    messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
    user_msg = next((m for m in messages if m["role"] == "user"), None)
    assert user_msg is not None
    assert "Recently Answered Questions" in user_msg["content"]
    assert "Chapter 5까지 완료" in user_msg["content"]
    assert "task_001" in user_msg["content"]


@pytest.mark.asyncio
async def test_answered_questions_summary_empty(test_workspace):
    """_build_answered_questions_summary returns empty string for empty list."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    result = worker._build_answered_questions_summary([])
    assert result == ""


@pytest.mark.asyncio
async def test_answered_questions_summary_handles_none_answer(test_workspace):
    """_build_answered_questions_summary should not crash when answer is None."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    # Simulates answered=True but answer=None (checkbox checked, no text)
    result = worker._build_answered_questions_summary(
        [{"id": "q_1", "question": "Done?", "answered": True, "answer": None}]
    )
    assert "Recently Answered Questions" in result
    assert "체크만 됨" in result


@pytest.mark.asyncio
async def test_answer_without_checkbox_excluded_from_unanswered_summary(
    test_workspace,
):
    """Question with answer text but answered=False should NOT appear in Unanswered section."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    now = datetime.now()

    # answer filled but checkbox not checked
    questions_data = backend.load_questions()
    questions_data["questions"] = [
        {
            "id": "q_text_only",
            "question": "블로그 진행?",
            "answered": False,
            "answer": "70% 완료",
            "type": "progress_check",
            "created_at": now.isoformat(),
        },
    ]
    backend.save_questions(questions_data)

    mock_provider.chat = AsyncMock(return_value=_make_response("Done."))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    await worker.run_cycle()

    call_args = mock_provider.chat.call_args
    messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
    user_msg = next((m for m in messages if m["role"] == "user"), None)
    content = user_msg["content"]

    # Should appear in Recently Answered section
    assert "Recently Answered Questions" in content
    assert "70% 완료" in content

    # Question ID must NOT appear in the Unanswered section.
    # Split on "Recently Answered" to isolate the dashboard summary portion;
    # the question ID should only appear after that boundary.
    before_answered = content.split("Recently Answered Questions")[0]
    assert "q_text_only" not in before_answered, (
        "Question q_text_only should not appear in dashboard summary (unanswered)"
    )


@pytest.mark.asyncio
async def test_worker_registers_save_insight_tool(test_workspace):
    """Worker should register save_insight tool for processing answered questions."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()

    mock_provider.chat = AsyncMock(return_value=_make_response("Done."))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
    )

    await worker.run_cycle()

    assert "save_insight" in worker.tools.tool_names


# ============================================================================
# _build_notifications_summary delivered section tests
# ============================================================================


@pytest.mark.asyncio
async def test_notifications_summary_with_recent_delivered(test_workspace):
    """_build_notifications_summary includes recently delivered notifications."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    notif_file = test_workspace / "dashboard" / "notifications.json"
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_delivered_recent",
                "message": "최근 전달된 알림",
                "scheduled_at": (now - timedelta(hours=2)).isoformat(),
                "delivered_at": (now - timedelta(hours=1)).isoformat(),
                "type": "deadline_alert",
                "priority": "high",
                "status": "delivered",
                "related_task_id": "task_001",
            }
        ],
    }
    notif_file.write_text(json.dumps(notif_data), encoding="utf-8")

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
    )

    result = worker._build_notifications_summary()
    assert "Recently Delivered" in result
    assert "n_delivered_recent" in result
    assert "최근 전달된 알림" in result
    assert "task_001" in result
    assert "WORKER.md" in result


@pytest.mark.asyncio
async def test_notifications_summary_invalid_delivered_at_skipped(
    test_workspace,
):
    """Delivered notification with invalid delivered_at is excluded (not included forever)."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    notif_file = test_workspace / "dashboard" / "notifications.json"
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_bad_date",
                "message": "잘못된 날짜 알림",
                "scheduled_at": "2026-02-25T10:00:00",
                "delivered_at": "not-a-date",
                "type": "reminder",
                "priority": "medium",
                "status": "delivered",
            },
            {
                "id": "n_no_date",
                "message": "날짜 없는 알림",
                "scheduled_at": "2026-02-25T10:00:00",
                "type": "reminder",
                "priority": "medium",
                "status": "delivered",
                # no delivered_at at all
            },
        ],
    }
    notif_file.write_text(json.dumps(notif_data), encoding="utf-8")

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
    )

    result = worker._build_notifications_summary()
    # Invalid delivered_at entries must be excluded to prevent infinite repetition
    assert "n_bad_date" not in result
    assert "n_no_date" not in result


@pytest.mark.asyncio
async def test_notifications_summary_old_delivered_excluded(test_workspace):
    """_build_notifications_summary excludes delivered notifications older than 48h."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    notif_file = test_workspace / "dashboard" / "notifications.json"
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_delivered_old",
                "message": "오래된 전달 알림",
                "scheduled_at": (now - timedelta(hours=72)).isoformat(),
                "delivered_at": (now - timedelta(hours=60)).isoformat(),
                "type": "reminder",
                "priority": "medium",
                "status": "delivered",
            }
        ],
    }
    notif_file.write_text(json.dumps(notif_data), encoding="utf-8")

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
    )

    result = worker._build_notifications_summary()
    assert "n_delivered_old" not in result
    assert "No pending notifications" in result


@pytest.mark.asyncio
async def test_notifications_summary_pending_and_delivered(test_workspace):
    """_build_notifications_summary shows both pending and recently delivered sections."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    notif_file = test_workspace / "dashboard" / "notifications.json"
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_pending_001",
                "message": "대기 중 알림",
                "scheduled_at": (now + timedelta(hours=2)).isoformat(),
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
                "related_task_id": "task_002",
            },
            {
                "id": "n_delivered_001",
                "message": "전달 완료 알림",
                "scheduled_at": (now - timedelta(hours=3)).isoformat(),
                "delivered_at": (now - timedelta(hours=1)).isoformat(),
                "type": "progress_check",
                "priority": "high",
                "status": "delivered",
                "related_task_id": "task_003",
            },
        ],
    }
    notif_file.write_text(json.dumps(notif_data), encoding="utf-8")

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
    )

    result = worker._build_notifications_summary()
    # Pending section
    assert "n_pending_001" in result
    assert "대기 중 알림" in result
    assert "task_002" in result
    # Delivered section
    assert "Recently Delivered" in result
    assert "n_delivered_001" in result
    assert "전달 완료 알림" in result
    assert "task_003" in result


@pytest.mark.asyncio
async def test_notifications_summary_delivered_at_boundary_48h(test_workspace):
    """Boundary test: just inside vs just outside 48h window."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    notif_file = test_workspace / "dashboard" / "notifications.json"
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_boundary_outside",
                "message": "48시간 1분 전 (제외)",
                "scheduled_at": (now - timedelta(hours=50)).isoformat(),
                "delivered_at": (now - timedelta(hours=48, minutes=1)).isoformat(),
                "type": "reminder",
                "priority": "medium",
                "status": "delivered",
            },
            {
                "id": "n_boundary_inside",
                "message": "47시간 59분 전 (포함)",
                "scheduled_at": (now - timedelta(hours=49)).isoformat(),
                "delivered_at": (now - timedelta(hours=47, minutes=59)).isoformat(),
                "type": "reminder",
                "priority": "medium",
                "status": "delivered",
            },
        ],
    }
    notif_file.write_text(json.dumps(notif_data), encoding="utf-8")

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
    )

    result = worker._build_notifications_summary()
    # Just outside 48h -> excluded
    assert "n_boundary_outside" not in result
    # Just inside 48h -> included
    assert "n_boundary_inside" in result


@pytest.mark.asyncio
async def test_notifications_summary_delivered_with_timezone(test_workspace):
    """Delivered notifications with timezone-aware delivered_at should be handled."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    notif_file = test_workspace / "dashboard" / "notifications.json"
    # Use timezone-aware ISO strings (+09:00 and Z)
    recent_kst = (now - timedelta(hours=1)).isoformat() + "+09:00"
    recent_utc = (now - timedelta(hours=1)).isoformat() + "Z"

    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_tz_kst",
                "message": "KST 타임존 알림",
                "scheduled_at": now.isoformat(),
                "delivered_at": recent_kst,
                "type": "reminder",
                "priority": "medium",
                "status": "delivered",
            },
            {
                "id": "n_tz_utc",
                "message": "UTC Z 타임존 알림",
                "scheduled_at": now.isoformat(),
                "delivered_at": recent_utc,
                "type": "reminder",
                "priority": "medium",
                "status": "delivered",
            },
        ],
    }
    notif_file.write_text(json.dumps(notif_data), encoding="utf-8")

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
    )

    result = worker._build_notifications_summary()
    # Both timezone-aware entries should be processed without TypeError
    assert "n_tz_kst" in result
    assert "n_tz_utc" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
