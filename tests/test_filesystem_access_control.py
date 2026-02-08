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
        ".env"
    ]

    for filename in instruction_files:
        file_path = workspace / filename
        file_path.touch()
        assert _is_read_only(file_path, workspace), f"{filename} should be read-only"


def test_is_read_only_allows_data_files(tmp_path):
    """Test that _is_read_only allows dashboard data files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dashboard_dir = workspace / "dashboard"
    dashboard_dir.mkdir()

    # Test data files (should NOT be read-only)
    data_files = [
        dashboard_dir / "tasks.json",
        dashboard_dir / "questions.json",
        dashboard_dir / "notifications.json",
        workspace / "memory" / "MEMORY.md",
    ]

    for file_path in data_files:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        assert not _is_read_only(file_path, workspace), f"{file_path.name} should be writable"


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
async def test_write_tool_allows_data_files(tmp_path):
    """Test that WriteFileTool allows writing to data files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = WriteFileTool(allowed_dir=workspace)

    # Write to dashboard/tasks.json (should succeed)
    tasks_path = str(workspace / "dashboard" / "tasks.json")
    result = await tool.execute(path=tasks_path, content='{"tasks": []}')

    assert "Successfully wrote" in result
    assert (workspace / "dashboard" / "tasks.json").exists()


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
        path=str(dashboard_path),
        old_text="Original content",
        new_text="Modified content"
    )

    assert "Error:" in result
    assert "read-only instruction file" in result


@pytest.mark.asyncio
async def test_edit_tool_allows_data_files(tmp_path):
    """Test that EditFileTool allows editing data files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dashboard_dir = workspace / "dashboard"
    dashboard_dir.mkdir()

    # Create tasks.json
    tasks_path = dashboard_dir / "tasks.json"
    tasks_path.write_text('{"tasks": []}')

    tool = EditFileTool(allowed_dir=workspace)

    # Edit tasks.json (should succeed)
    result = await tool.execute(
        path=str(tasks_path),
        old_text='{"tasks": []}',
        new_text='{"tasks": ["task1"]}'
    )

    assert "Successfully edited" in result
    assert '{"tasks": ["task1"]}' in tasks_path.read_text()
