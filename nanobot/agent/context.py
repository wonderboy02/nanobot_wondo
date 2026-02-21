"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.
    
    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """
    
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "DASHBOARD.md"]
    
    def __init__(self, workspace: Path, storage_backend: "StorageBackend | None" = None):
        self.workspace = workspace
        self.storage_backend = storage_backend
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
        self._precomputed_dashboard: str | None = None
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.
        
        Args:
            skill_names: Optional list of skills to include.
        
        Returns:
            Complete system prompt.
        """
        parts = []
        
        # Core identity
        parts.append(self._get_identity())
        
        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        
        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")
        
        # Skills - progressive loading
        # 1. Always-loaded skills: include full content
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # 2. Available skills: only show summary (agent uses read_file to load)
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        # Dashboard state (Active tasks + Question Queue)
        dashboard_context = self._get_dashboard_context()
        if dashboard_context:
            parts.append(f"# Dashboard State\n\n{dashboard_context}")

        return "\n\n---\n\n".join(parts)
    
    def _get_identity(self) -> str:
        """Get the core identity section."""
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        
        return f"""# nanobot

## Current Time
{now}

## Runtime
{runtime}

## Workspace
{workspace_path}
- Memory: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md

Reply directly with text for conversations. Only use the 'message' tool for chat channel delivery."""
    
    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    def set_dashboard_summary(self, summary: str) -> None:
        """Set pre-fetched dashboard summary to avoid blocking sync I/O.

        Call this from async code (via asyncio.to_thread) before build_messages()
        when the storage backend does blocking I/O (e.g., Notion).
        """
        self._precomputed_dashboard = summary

    def _get_dashboard_context(self) -> str:
        """
        Get current Dashboard state for context.

        If a precomputed summary was set via set_dashboard_summary(),
        uses that (one-time) to avoid blocking the event loop.
        Otherwise falls back to synchronous loading (fine for JSON backend / CLI).

        Returns:
            Dashboard summary (active tasks + unanswered questions).
        """
        if self._precomputed_dashboard is not None:
            summary = self._precomputed_dashboard
            self._precomputed_dashboard = None
            return summary

        # Sync fallback — fine for JsonStorageBackend / CLI, but warns if Notion
        # backend is active without precomputed summary (potential event loop block).
        try:
            from nanobot.dashboard.helper import get_dashboard_summary
            dashboard_path = self.workspace / "dashboard"

            if not dashboard_path.exists() and self.storage_backend is None:
                return ""

            if self.storage_backend is not None:
                from loguru import logger
                logger.warning(
                    "Dashboard sync fallback with Notion backend — "
                    "event loop will block during Notion I/O. "
                    "Call set_dashboard_summary() before build_messages() to avoid this."
                )

            return get_dashboard_summary(dashboard_path, storage_backend=self.storage_backend)

        except ImportError:
            return ""
        except Exception as e:
            try:
                from loguru import logger
                logger.debug(f"Dashboard context skipped: {e}")
            except Exception:
                pass
            return ""
    
    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build the complete message list for an LLM call.

        STATELESS DESIGN:
        - Session history is NOT included in LLM context
        - Dashboard Summary provides all necessary context
        - Each request is independent (pure stateless)
        - Session history is kept for logging/debugging only

        Args:
            history: Previous conversation messages (NOT USED in context).
            current_message: The new user message.
            skill_names: Optional skills to include.
            media: Optional list of local file paths for images/media.
            channel: Current channel (telegram, feishu, etc.).
            chat_id: Current chat/user ID.

        Returns:
            List of messages including system prompt.
        """
        messages = []

        # System prompt (includes Dashboard Summary with full state)
        system_prompt = self.build_system_prompt(skill_names)
        if channel and chat_id:
            system_prompt += f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"
        messages.append({"role": "system", "content": system_prompt})

        # Session history REMOVED - Dashboard is single source of truth
        # messages.extend(history)  # ← Stateless: No history in context

        # Current message (with optional image attachments)
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text
        
        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        
        if not images:
            return text
        return images + [{"type": "text", "text": text}]
    
    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.
        
        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.
        
        Returns:
            Updated message list.
        """
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })
        return messages
    
    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.
        
        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.
        
        Returns:
            Updated message list.
        """
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        
        if tool_calls:
            msg["tool_calls"] = tool_calls
        
        messages.append(msg)
        return messages
