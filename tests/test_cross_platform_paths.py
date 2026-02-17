"""Cross-platform path handling tests for Windows and Linux."""

import pytest
from pathlib import Path
import tempfile
import os


def test_path_parts_cross_platform():
    """Test that Path.parts works identically on Windows and Linux."""
    # Both forward slash and backslash should work
    cases = [
        ("workspace/DASHBOARD.md", ("workspace", "DASHBOARD.md")),
        ("workspace/subdir/DASHBOARD.md", ("workspace", "subdir", "DASHBOARD.md")),
    ]

    for path_str, expected_parts in cases:
        p = Path(path_str)
        assert p.parts == expected_parts


def test_read_only_detection_cross_platform():
    """Test read-only detection on both platforms."""
    from nanobot.agent.tools.filesystem import _is_read_only

    workspace = Path("/workspace")  # POSIX-style (works on Windows too via Path)

    # Test cases
    test_cases = [
        (Path("/workspace/DASHBOARD.md"), True),
        (Path("/workspace/subdir/DASHBOARD.md"), True),
        (Path("/workspace/dashboard/tasks.json"), True),  # Dashboard JSON is read-only (use dashboard tools)
        (Path("/workspace/memory/MEMORY.md"), False),
    ]

    for path, expected in test_cases:
        result = _is_read_only(path, workspace)
        assert result == expected, f"Failed for {path}"


def test_expanduser_before_absolute_check():
    """Test that ~/file.txt is not treated as relative path."""
    from nanobot.agent.tools.filesystem import _resolve_path

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # ~/DASHBOARD.md should NOT be resolved relative to workspace
        # Should raise PermissionError (outside workspace)
        with pytest.raises(PermissionError, match="outside allowed directory"):
            _resolve_path("~/DASHBOARD.md", allowed_dir=workspace, check_write=True)


def test_relative_path_resolution():
    """Test that relative paths resolve to workspace."""
    from nanobot.agent.tools.filesystem import _resolve_path

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Relative path should resolve to workspace
        resolved = _resolve_path("subdir/file.txt", allowed_dir=workspace)
        assert str(resolved).startswith(str(workspace))


def test_absolute_path_outside_workspace():
    """Test that absolute paths outside workspace are rejected."""
    from nanobot.agent.tools.filesystem import _resolve_path

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Absolute path outside workspace
        with pytest.raises(PermissionError, match="outside allowed directory"):
            _resolve_path("/tmp/other/file.txt", allowed_dir=workspace)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
