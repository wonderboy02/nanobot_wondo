"""File system tools: read, write, edit."""

from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


def _is_read_only(path: Path, workspace: Path | None = None) -> bool:
    """Check if path is a read-only file (instruction/config files).

    Args:
        path: The resolved path to check
        workspace: The workspace directory (if set, check relative paths)

    Returns:
        True if the path is a read-only instruction/config file
    """
    READ_ONLY_PATTERNS = [
        # Instruction files
        "DASHBOARD.md",
        "TOOLS.md",
        "AGENTS.md",
        "SOUL.md",
        "USER.md",
        "IDENTITY.md",
        "HEARTBEAT.md",
        "config.json",
        ".env",
        # Dashboard JSON files (use dashboard tools instead)
        "tasks.json",
        "questions.json",
        "notifications.json",
        "history.json",
        "insights.json",
        "people.json",
    ]

    if workspace:
        try:
            rel_path = path.relative_to(workspace.resolve())

            # Check if the relative path matches any read-only pattern
            for pattern in READ_ONLY_PATTERNS:
                if pattern in rel_path.parts:
                    return True
        except ValueError:
            # Path is outside workspace, check absolute filename
            pass

    # Fallback: check if filename matches any pattern
    filename = path.name
    return filename in READ_ONLY_PATTERNS


def _resolve_path(path: str, allowed_dir: Path | None = None,
                  check_write: bool = False) -> Path:
    """Resolve path and optionally enforce directory restriction.

    Args:
        path: Path to resolve
        allowed_dir: If set, restrict to this directory (workspace)
        check_write: If True, check if path is writable (not read-only)

    Returns:
        Resolved Path object

    Raises:
        PermissionError: If path is outside allowed_dir or is read-only when writing
    """
    # If allowed_dir is set and path is relative, resolve relative to allowed_dir
    path_obj = Path(path).expanduser()
    if allowed_dir and not path_obj.is_absolute():
        resolved = (allowed_dir / path_obj).resolve()
    else:
        resolved = path_obj.resolve()

    # Workspace restriction
    if allowed_dir and not str(resolved).startswith(str(allowed_dir.resolve())):
        raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")

    # Read-only file check (only when writing)
    if check_write and _is_read_only(resolved, allowed_dir):
        # Check if it's a dashboard data file
        if any(pattern in str(resolved) for pattern in ["tasks.json", "questions.json", "history.json", "insights.json"]):
            raise PermissionError(
                f"Path {path} is a dashboard data file. "
                f"Use dashboard tools (create_task, update_task, answer_question, etc.) instead of write_file."
            )
        else:
            raise PermissionError(
                f"Path {path} is a read-only instruction file and cannot be modified. "
                f"Please update the appropriate data files using dashboard tools instead."
            )

    return resolved


class ReadFileTool(Tool):
    """Tool to read file contents."""
    
    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "read_file"
    
    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to read"
                }
            },
            "required": ["path"]
        }
    
    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"
            
            content = file_path.read_text(encoding="utf-8")
            return content
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(Tool):
    """Tool to write content to a file."""
    
    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "write_file"
    
    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to write to"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write"
                }
            },
            "required": ["path", "content"]
        }
    
    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir, check_write=True)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""
    
    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "edit_file"
    
    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to edit"
                },
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find and replace"
                },
                "new_text": {
                    "type": "string",
                    "description": "The text to replace with"
                }
            },
            "required": ["path", "old_text", "new_text"]
        }
    
    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir, check_write=True)
            if not file_path.exists():
                return f"Error: File not found: {path}"

            content = file_path.read_text(encoding="utf-8")

            if old_text not in content:
                return f"Error: old_text not found in file. Make sure it matches exactly."

            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")

            return f"Successfully edited {path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {str(e)}"


class ListDirTool(Tool):
    """Tool to list directory contents."""
    
    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "list_dir"
    
    @property
    def description(self) -> str:
        return "List the contents of a directory."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to list"
                }
            },
            "required": ["path"]
        }
    
    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            dir_path = _resolve_path(path, self._allowed_dir)
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"
            
            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")
            
            if not items:
                return f"Directory {path} is empty"
            
            return "\n".join(items)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
