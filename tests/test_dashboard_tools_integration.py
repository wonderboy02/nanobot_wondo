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


def test_notification_tools_registered_with_cron(temp_workspace):
    """Notification tools are registered when cron_service is provided."""
    from unittest.mock import Mock
    from nanobot.cron.service import CronService

    bus = MessageBus()
    provider = LiteLLMProvider(api_key="test")
    cron = Mock(spec=CronService)

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=temp_workspace,
        model="gpt-3.5-turbo",
        cron_service=cron,
    )

    tool_names = agent.tools.tool_names
    assert "schedule_notification" in tool_names
    assert "update_notification" in tool_names
    assert "cancel_notification" in tool_names
    assert "list_notifications" in tool_names


def test_notification_tools_receive_gcal_params(temp_workspace):
    """Notification tools receive gcal_client and send_callback when configured."""
    from unittest.mock import Mock
    from nanobot.cron.service import CronService

    bus = MessageBus()
    provider = LiteLLMProvider(api_key="test")
    cron = Mock(spec=CronService)
    mock_gcal = Mock()

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=temp_workspace,
        model="gpt-3.5-turbo",
        cron_service=cron,
        notification_chat_id="test_chat_123",
    )
    # Inject gcal client after construction (avoids real Google auth)
    agent._gcal_client = mock_gcal

    # Re-register tools to pick up the gcal client
    agent.tools = __import__(
        "nanobot.agent.tools.registry", fromlist=["ToolRegistry"]
    ).ToolRegistry()
    agent._register_default_tools()

    schedule = agent.tools.get("schedule_notification")
    update = agent.tools.get("update_notification")
    cancel = agent.tools.get("cancel_notification")

    assert schedule._gcal_client is mock_gcal
    assert update._gcal_client is mock_gcal
    assert cancel._gcal_client is mock_gcal
    assert schedule._notification_chat_id == "test_chat_123"
    assert cancel._notification_chat_id == "test_chat_123"


def test_notification_tools_set_context_propagation(temp_workspace):
    """set_context propagates to all 3 notification tools including cancel."""
    from unittest.mock import Mock
    from nanobot.cron.service import CronService

    bus = MessageBus()
    provider = LiteLLMProvider(api_key="test")
    cron = Mock(spec=CronService)

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=temp_workspace,
        model="gpt-3.5-turbo",
        cron_service=cron,
    )

    # Simulate set_context like _process_message does
    for name in ("schedule_notification", "update_notification", "cancel_notification"):
        tool = agent.tools.get(name)
        assert tool is not None, f"{name} not registered"
        assert hasattr(tool, "set_context"), f"{name} missing set_context"
        tool.set_context("telegram", "chat_999")
        assert tool._chat_id == "chat_999"
        assert tool._channel == "telegram"


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
