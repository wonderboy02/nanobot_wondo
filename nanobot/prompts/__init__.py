"""Default instruction prompts shipped with nanobot.

Resolution order: workspace/ override -> nanobot/prompts/ package default.
Follows the same pattern as nanobot/skills/ (builtin vs workspace).
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def resolve_instruction_file(workspace: Path, filename: str) -> Path | None:
    """Resolve an instruction file: workspace override -> package default.

    Args:
        workspace: User's workspace directory.
        filename: Instruction file name (e.g., "AGENTS.md").

    Returns:
        Path to resolved file, or None if not found.
    """
    ws_path = workspace / filename
    if ws_path.exists():
        return ws_path
    default_path = PROMPTS_DIR / filename
    if default_path.exists():
        return default_path
    return None


def load_instruction_file(workspace: Path, filename: str) -> str:
    """Load instruction file content: workspace override -> package default.

    Args:
        workspace: User's workspace directory.
        filename: Instruction file name (e.g., "AGENTS.md").

    Returns:
        File content, or empty string if not found.
    """
    path = resolve_instruction_file(workspace, filename)
    return path.read_text(encoding="utf-8") if path else ""
