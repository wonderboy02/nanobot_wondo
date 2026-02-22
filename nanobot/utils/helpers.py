"""Utility functions for nanobot."""

import os
from datetime import datetime
from pathlib import Path


def ensure_dir(path: Path) -> Path:
    """Ensure a directory exists, creating it if necessary."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_path() -> Path:
    """Get the nanobot data directory (~/.nanobot or NANOBOT_DATA_DIR)."""
    # NOTE: ensure_dir runs Path.mkdir(exist_ok=True) on every call.
    # Acceptable — it's a cheap no-op syscall when the directory already exists.
    override = (os.environ.get("NANOBOT_DATA_DIR") or "").strip() or None
    return ensure_dir(Path(override) if override else Path.home() / ".nanobot")


def get_workspace_path(workspace: str | None = None) -> Path:
    """
    Get the workspace path.
    
    Args:
        workspace: Optional workspace path. Defaults to ~/.nanobot/workspace.
    
    Returns:
        Expanded and ensured workspace path.
    """
    if workspace:
        path = Path(workspace).expanduser()
    else:
        # Docker: resolves to /app/data/workspace, but config.json always provides
        # an explicit workspace path (/app/workspace), so this default is not reached.
        path = get_data_path() / "workspace"
    return ensure_dir(path)


def get_sessions_path() -> Path:
    """Get the sessions storage directory."""
    return ensure_dir(get_data_path() / "sessions")


def today_date() -> str:
    """Get today's date in YYYY-MM-DD format."""
    return datetime.now().strftime("%Y-%m-%d")


def safe_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    # Replace unsafe characters
    unsafe = '<>:"/\\|?*'
    for char in unsafe:
        name = name.replace(char, "_")
    return name.strip()


