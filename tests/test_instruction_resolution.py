"""Tests for instruction file resolution (nanobot.prompts)."""

import pytest
from pathlib import Path


@pytest.fixture
def test_workspace(tmp_path):
    """Create minimal workspace for resolution tests."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


class TestResolveInstructionFile:
    """Tests for resolve_instruction_file()."""

    def test_workspace_override_takes_priority(self, test_workspace):
        """Workspace file exists → workspace path returned."""
        from nanobot.prompts import resolve_instruction_file

        (test_workspace / "AGENTS.md").write_text("custom agent", encoding="utf-8")
        result = resolve_instruction_file(test_workspace, "AGENTS.md")
        assert result == test_workspace / "AGENTS.md"

    def test_fallback_to_package_default(self, test_workspace):
        """Workspace file missing → package prompts/ path returned."""
        from nanobot.prompts import resolve_instruction_file

        result = resolve_instruction_file(test_workspace, "AGENTS.md")
        assert result is not None
        assert "prompts" in str(result).replace("\\", "/")

    def test_missing_from_both_returns_none(self, test_workspace):
        """File missing everywhere → None."""
        from nanobot.prompts import resolve_instruction_file

        result = resolve_instruction_file(test_workspace, "NONEXISTENT.md")
        assert result is None


class TestLoadInstructionFile:
    """Tests for load_instruction_file()."""

    def test_loads_package_default(self, test_workspace):
        """Package default AGENTS.md → non-empty content."""
        from nanobot.prompts import load_instruction_file

        content = load_instruction_file(test_workspace, "AGENTS.md")
        assert len(content) > 0

    def test_workspace_override_content(self, test_workspace):
        """Workspace copy overrides package default."""
        from nanobot.prompts import load_instruction_file

        (test_workspace / "DASHBOARD.md").write_text("custom dashboard", encoding="utf-8")
        content = load_instruction_file(test_workspace, "DASHBOARD.md")
        assert content == "custom dashboard"

    def test_missing_returns_empty(self, test_workspace):
        """Missing file → empty string."""
        from nanobot.prompts import load_instruction_file

        assert load_instruction_file(test_workspace, "NONEXISTENT.md") == ""


class TestBootstrapIntegration:
    """ContextBuilder integration with package defaults."""

    def test_bootstrap_loads_all_from_package(self, test_workspace):
        """Empty workspace → all bootstrap files from nanobot/prompts/."""
        from nanobot.agent.context import ContextBuilder

        builder = ContextBuilder(workspace=test_workspace)
        result = builder._load_bootstrap_files()
        for filename in ContextBuilder.BOOTSTRAP_FILES:
            assert f"## {filename}" in result

    def test_bootstrap_workspace_override(self, test_workspace):
        """Workspace AGENTS.md overrides package default."""
        from nanobot.agent.context import ContextBuilder

        (test_workspace / "AGENTS.md").write_text("# Custom Agent", encoding="utf-8")
        builder = ContextBuilder(workspace=test_workspace)
        result = builder._load_bootstrap_files()
        assert "# Custom Agent" in result
