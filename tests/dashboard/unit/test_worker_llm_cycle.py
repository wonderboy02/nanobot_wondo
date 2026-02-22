"""Test Worker LLM cycle with mocked provider.

Tests the Phase 2 LLM-powered analysis:
- Context building
- Tool registration
- LLM chat loop with tool calls
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock

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


@pytest.fixture
def mock_cron_service(tmp_path):
    """Create a real CronService with temp storage."""
    from nanobot.cron.service import CronService

    cron_store = tmp_path / "cron" / "jobs.json"
    cron_store.parent.mkdir(parents=True)
    return CronService(cron_store)


@pytest.mark.asyncio
async def test_llm_cycle_runs_when_provider_available(test_workspace, mock_cron_service):
    """LLM cycle should run when provider and model are provided."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    mock_bus = Mock()

    # LLM returns no tool calls (simple analysis)
    mock_provider.chat = AsyncMock(return_value=_make_response("No maintenance needed."))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
        cron_service=mock_cron_service,
        bus=mock_bus,
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
async def test_llm_cycle_with_tool_call(test_workspace, mock_cron_service):
    """LLM cycle should execute tool calls from LLM response."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    mock_bus = Mock()

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
        cron_service=mock_cron_service,
        bus=mock_bus,
    )

    await worker.run_cycle()

    # Verify question was created
    questions_data = backend.load_questions()
    assert len(questions_data["questions"]) == 1
    assert "블로그" in questions_data["questions"][0]["question"]


@pytest.mark.asyncio
async def test_llm_cycle_handles_error_gracefully(test_workspace, mock_cron_service):
    """LLM cycle should handle provider errors gracefully."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    mock_bus = Mock()

    # LLM raises an error
    mock_provider.chat = AsyncMock(side_effect=Exception("API Error"))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
        cron_service=mock_cron_service,
        bus=mock_bus,
    )

    # Should not raise (error is caught and logged)
    await worker.run_cycle()


@pytest.mark.asyncio
async def test_context_includes_dashboard_summary(test_workspace, mock_cron_service):
    """Context building should include dashboard summary."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    mock_bus = Mock()

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
        cron_service=mock_cron_service,
        bus=mock_bus,
    )

    await worker.run_cycle()

    # Check that the task title appears in the context
    call_args = mock_provider.chat.call_args
    messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
    user_msg = next((m for m in messages if m["role"] == "user"), None)
    assert user_msg is not None
    assert "Context Test Task" in user_msg["content"]


@pytest.mark.asyncio
async def test_worker_tools_registered(test_workspace, mock_cron_service):
    """Worker should register expected tools for LLM cycle."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    mock_bus = Mock()

    mock_provider.chat = AsyncMock(return_value=_make_response("Done."))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
        cron_service=mock_cron_service,
        bus=mock_bus,
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
async def test_notifications_summary_empty(test_workspace, mock_cron_service):
    """_build_notifications_summary returns 'no notifications' when list is empty."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=AsyncMock(),
        model="test-model",
        cron_service=mock_cron_service,
        bus=Mock(),
    )

    result = worker._build_notifications_summary()
    assert "No notifications scheduled" in result


@pytest.mark.asyncio
async def test_notifications_summary_no_pending(test_workspace, mock_cron_service):
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
        cron_service=mock_cron_service,
        bus=Mock(),
    )

    result = worker._build_notifications_summary()
    assert "No pending notifications" in result


@pytest.mark.asyncio
async def test_notifications_summary_with_pending(test_workspace, mock_cron_service):
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
        cron_service=mock_cron_service,
        bus=Mock(),
    )

    result = worker._build_notifications_summary()
    assert "n_pending" in result
    assert "블로그 마감 알림" in result
    assert "task_001" in result


# ============================================================================
# Max iterations test
# ============================================================================


@pytest.mark.asyncio
async def test_llm_cycle_stops_at_max_iterations(test_workspace, mock_cron_service):
    """LLM cycle should stop after max_iterations even if LLM keeps calling tools."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    mock_bus = Mock()

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
        cron_service=mock_cron_service,
        bus=mock_bus,
    )

    await worker.run_cycle()

    # Should have been called exactly max_iterations (10) times
    assert mock_provider.chat.call_count == 10


# ============================================================================
# Tool execution error handling test
# ============================================================================


@pytest.mark.asyncio
async def test_llm_cycle_tool_error_returns_error_message(test_workspace, mock_cron_service):
    """Tool execution error should be returned to LLM as error message, not crash."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    mock_bus = Mock()

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
        cron_service=mock_cron_service,
        bus=mock_bus,
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
async def test_maintenance_task_error_does_not_block_questions(test_workspace, mock_cron_service):
    """If task maintenance fails, question cleanup should still run."""
    from unittest.mock import patch

    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    # Add an answered question (should be cleaned up)
    questions_data = backend.load_questions()
    questions_data["questions"].append(
        {
            "id": "q_answered",
            "question": "Done?",
            "answered": True,
            "created_at": now.isoformat(),
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
async def test_notifications_summary_handles_load_error(test_workspace, mock_cron_service):
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
        cron_service=mock_cron_service,
        bus=Mock(),
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
async def test_context_uses_fallback_when_worker_md_missing(test_workspace, mock_cron_service):
    """Context should use fallback system prompt when WORKER.md doesn't exist."""
    import os

    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    mock_provider = AsyncMock()
    mock_bus = Mock()

    # Remove WORKER.md
    worker_md = test_workspace / "WORKER.md"
    if worker_md.exists():
        os.remove(worker_md)

    mock_provider.chat = AsyncMock(return_value=_make_response("Done."))

    worker = WorkerAgent(
        workspace=test_workspace,
        storage_backend=backend,
        provider=mock_provider,
        model="test-model",
        cron_service=mock_cron_service,
        bus=mock_bus,
    )

    await worker.run_cycle()

    # Check that fallback system prompt was used
    call_args = mock_provider.chat.call_args
    messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
    system_msg = next((m for m in messages if m["role"] == "system"), None)
    assert system_msg is not None
    assert "Worker Agent" in system_msg["content"]
    assert "Phase 1" in system_msg["content"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
