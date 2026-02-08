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

    (dashboard_dir / "tasks.json").write_text(
        json.dumps(tasks_data, indent=2), encoding="utf-8"
    )
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
    assert "move_to_history" in tool_names, "move_to_history tool not registered"

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
