"""Test filesystem access control for read-only instruction files."""

import pytest
from pathlib import Path
from nanobot.agent.tools.filesystem import WriteFileTool, EditFileTool, _is_read_only


def test_is_read_only_detects_instruction_files(tmp_path):
    """Test that _is_read_only correctly identifies instruction files."""
    # Create workspace directory
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Test instruction files
    instruction_files = [
        "DASHBOARD.md",
        "TOOLS.md",
        "AGENTS.md",
        "SOUL.md",
        "USER.md",
        "IDENTITY.md",
        "HEARTBEAT.md",
        "config.json",
        ".env",
    ]

    for filename in instruction_files:
        file_path = workspace / filename
        file_path.touch()
        assert _is_read_only(file_path, workspace), f"{filename} should be read-only"


def test_is_read_only_allows_data_files(tmp_path):
    """Test that _is_read_only allows memory files but blocks dashboard JSON."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dashboard_dir = workspace / "dashboard"
    dashboard_dir.mkdir()

    # Dashboard JSON files ARE read-only (use dashboard tools instead)
    dashboard_files = [
        dashboard_dir / "tasks.json",
        dashboard_dir / "questions.json",
        dashboard_dir / "notifications.json",
    ]

    for file_path in dashboard_files:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        assert _is_read_only(file_path, workspace), (
            f"{file_path.name} should be read-only (use dashboard tools)"
        )

    # Memory files should NOT be read-only
    memory_file = workspace / "memory" / "MEMORY.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.touch()
    assert not _is_read_only(memory_file, workspace), "MEMORY.md should be writable"


@pytest.mark.asyncio
async def test_write_tool_blocks_instruction_files(tmp_path):
    """Test that WriteFileTool blocks writing to instruction files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = WriteFileTool(allowed_dir=workspace)

    # Try to write to DASHBOARD.md (should fail)
    dashboard_path = str(workspace / "DASHBOARD.md")
    result = await tool.execute(path=dashboard_path, content="test content")

    assert "Error:" in result
    assert "read-only instruction file" in result


@pytest.mark.asyncio
async def test_write_tool_blocks_dashboard_json(tmp_path):
    """Test that WriteFileTool blocks writing to dashboard JSON files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = WriteFileTool(allowed_dir=workspace)

    # Write to dashboard/tasks.json (should fail - use dashboard tools)
    tasks_path = str(workspace / "dashboard" / "tasks.json")
    result = await tool.execute(path=tasks_path, content='{"tasks": []}')

    assert "Error:" in result
    assert "read-only" in result.lower() or "dashboard tools" in result.lower()


@pytest.mark.asyncio
async def test_edit_tool_blocks_instruction_files(tmp_path):
    """Test that EditFileTool blocks editing instruction files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create DASHBOARD.md
    dashboard_path = workspace / "DASHBOARD.md"
    dashboard_path.write_text("# Dashboard\nOriginal content")

    tool = EditFileTool(allowed_dir=workspace)

    # Try to edit DASHBOARD.md (should fail)
    result = await tool.execute(
        path=str(dashboard_path), old_text="Original content", new_text="Modified content"
    )

    assert "Error:" in result
    assert "read-only instruction file" in result


@pytest.mark.asyncio
async def test_edit_tool_blocks_dashboard_json(tmp_path):
    """Test that EditFileTool blocks editing dashboard JSON files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dashboard_dir = workspace / "dashboard"
    dashboard_dir.mkdir()

    # Create tasks.json
    tasks_path = dashboard_dir / "tasks.json"
    tasks_path.write_text('{"tasks": []}')

    tool = EditFileTool(allowed_dir=workspace)

    # Edit tasks.json (should fail - use dashboard tools)
    result = await tool.execute(
        path=str(tasks_path), old_text='{"tasks": []}', new_text='{"tasks": ["task1"]}'
    )

    assert "Error:" in result
    assert "read-only" in result.lower() or "dashboard tools" in result.lower()
