"""Integration test: Agent using dashboard tools."""

import json
import pytest
from pathlib import Path
import tempfile
import shutil

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.litellm_provider import LiteLLMProvider


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for testing."""
    temp_dir = Path(tempfile.mkdtemp())
    dashboard_dir = temp_dir / "dashboard"
    dashboard_dir.mkdir(parents=True)
    knowledge_dir = dashboard_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)

    # Initialize empty dashboard files
    tasks_data = {"version": "1.0", "tasks": []}
    questions_data = {"version": "1.0", "questions": []}

    (dashboard_dir / "tasks.json").write_text(json.dumps(tasks_data, indent=2), encoding="utf-8")
    (dashboard_dir / "questions.json").write_text(
        json.dumps(questions_data, indent=2), encoding="utf-8"
    )

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir)


def test_agent_has_dashboard_tools(temp_workspace):
    """Test that Agent has dashboard tools registered."""
    bus = MessageBus()
    provider = LiteLLMProvider(api_key="test")

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=temp_workspace,
        model="gpt-3.5-turbo",
        max_iterations=5,
    )

    # Check that dashboard tools are registered
    tool_names = agent.tools.tool_names

    assert "create_task" in tool_names, "create_task tool not registered"
    assert "update_task" in tool_names, "update_task tool not registered"
    assert "answer_question" in tool_names, "answer_question tool not registered"
    assert "create_question" in tool_names, "create_question tool not registered"
    assert "save_insight" in tool_names, "save_insight tool not registered"
    assert "archive_task" in tool_names, "archive_task tool not registered"

    print(f"✅ All 6 dashboard tools registered: {tool_names}")


def test_agent_tool_schemas(temp_workspace):
    """Test that dashboard tools have correct schemas."""
    bus = MessageBus()
    provider = LiteLLMProvider(api_key="test")

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=temp_workspace,
        model="gpt-3.5-turbo",
        max_iterations=5,
    )

    # Get create_task tool
    create_task_tool = agent.tools.get("create_task")

    assert create_task_tool is not None

    # Check parameters
    params = create_task_tool.parameters
    assert "properties" in params
    assert "title" in params["properties"]
    assert "deadline" in params["properties"]
    assert "priority" in params["properties"]
    assert "required" in params
    assert "title" in params["required"]

    print(f"✅ create_task tool has correct schema")
    print(f"   Properties: {list(params['properties'].keys())}")
    print(f"   Required: {params['required']}")


def test_dashboard_files_protected(temp_workspace):
    """Test that dashboard JSON files are protected from write_file."""
    bus = MessageBus()
    provider = LiteLLMProvider(api_key="test")

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=temp_workspace,
        model="gpt-3.5-turbo",
        max_iterations=5,
        restrict_to_workspace=True,  # Enable workspace restriction
    )

    # Get write_file tool
    write_file_tool = agent.tools.get("write_file")

    assert write_file_tool is not None

    # Try to write to dashboard/tasks.json (should be blocked)
    import asyncio

    result = asyncio.run(
        write_file_tool.execute(path="dashboard/tasks.json", content='{"test": true}')
    )

    assert "Error" in result
    assert "dashboard tools" in result.lower() or "read-only" in result.lower()

    print(f"✅ Dashboard files protected: {result[:100]}")


def test_notification_tools_always_registered(temp_workspace):
    """Notification tools are always registered (no cron_service required)."""
    bus = MessageBus()
    provider = LiteLLMProvider(api_key="test")

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=temp_workspace,
        model="gpt-3.5-turbo",
    )

    tool_names = agent.tools.tool_names
    assert "schedule_notification" in tool_names
    assert "update_notification" in tool_names
    assert "cancel_notification" in tool_names
    assert "list_notifications" in tool_names


def test_gcal_public_properties(temp_workspace):
    """AgentLoop exposes gcal_client/timezone/duration as public properties."""
    bus = MessageBus()
    provider = LiteLLMProvider(api_key="test")

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=temp_workspace,
        model="gpt-3.5-turbo",
    )

    # Default values when GCal not configured
    assert agent.gcal_client is None
    assert agent.gcal_timezone == "Asia/Seoul"
    assert agent.gcal_duration_minutes == 30


@pytest.mark.asyncio
async def test_handle_message_appends_refresh_after_tool_call(temp_workspace):
    """Dashboard refresh message is appended after tool calls in _handle_message."""
    from unittest.mock import AsyncMock, patch

    from nanobot.bus.events import InboundMessage
    from nanobot.providers.base import LLMResponse, ToolCallRequest

    bus = MessageBus()
    provider = LiteLLMProvider(api_key="test")

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=temp_workspace,
        model="gpt-3.5-turbo",
        max_iterations=3,
    )

    # Initialize notifications.json for refresh
    dashboard_dir = temp_workspace / "dashboard"
    (dashboard_dir / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []}), encoding="utf-8"
    )

    # Mock provider: first call returns tool call, second returns final text
    mock_chat = AsyncMock(
        side_effect=[
            LLMResponse(
                content="Creating task.",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="create_task",
                        arguments={"title": "테스트 태스크", "context": "테스트"},
                    )
                ],
            ),
            LLMResponse(content="SILENT", tool_calls=[]),
        ]
    )

    captured_messages = []
    original_chat = mock_chat

    async def capture_chat(**kwargs):
        captured_messages.append(list(kwargs.get("messages", [])))
        return await original_chat(**kwargs)

    msg = InboundMessage(
        channel="test",
        chat_id="test_chat",
        sender_id="user",
        content="테스트 태스크 만들어줘",
    )

    with patch.object(agent.provider, "chat", side_effect=capture_chat):
        await agent._handle_message(msg)

    # Second LLM call should have received the refresh message
    assert len(captured_messages) >= 2
    second_msgs = captured_messages[1]
    refresh_found = any("Updated Dashboard State" in m.get("content", "") for m in second_msgs)
    assert refresh_found, "Dashboard refresh message not found in second LLM call"


@pytest.mark.asyncio
async def test_handle_message_warns_on_refresh_failure(temp_workspace):
    """Warning message appended when dashboard refresh fails."""
    from unittest.mock import AsyncMock, patch

    from nanobot.bus.events import InboundMessage
    from nanobot.providers.base import LLMResponse, ToolCallRequest

    bus = MessageBus()
    provider = LiteLLMProvider(api_key="test")

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=temp_workspace,
        model="gpt-3.5-turbo",
        max_iterations=3,
    )

    dashboard_dir = temp_workspace / "dashboard"
    (dashboard_dir / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []}), encoding="utf-8"
    )

    mock_chat = AsyncMock(
        side_effect=[
            LLMResponse(
                content="Creating task.",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="create_task",
                        arguments={"title": "테스트", "context": "테스트"},
                    )
                ],
            ),
            LLMResponse(content="SILENT", tool_calls=[]),
        ]
    )

    captured_messages = []
    original_chat = mock_chat

    async def capture_chat(**kwargs):
        captured_messages.append(list(kwargs.get("messages", [])))
        return await original_chat(**kwargs)

    msg = InboundMessage(
        channel="test",
        chat_id="test_chat",
        sender_id="user",
        content="태스크 만들어줘",
    )

    # _precompute_dashboard calls get_dashboard_summary once, then refresh
    # after tool call calls it again. Fail on the 2nd+ call.
    from nanobot.dashboard.helper import get_dashboard_summary as _real

    _real_result = _real(dashboard_dir)
    call_count = 0

    def _fail_on_refresh(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise RuntimeError("API down")
        return _real_result

    with (
        patch.object(agent.provider, "chat", side_effect=capture_chat),
        patch(
            "nanobot.dashboard.helper.get_dashboard_summary",
            side_effect=_fail_on_refresh,
        ),
    ):
        await agent._handle_message(msg)

    assert len(captured_messages) >= 2
    second_msgs = captured_messages[1]
    warning_found = any(
        "Warning: Dashboard state refresh failed" in m.get("content", "") for m in second_msgs
    )
    assert warning_found, "Warning message not found in second LLM call"
