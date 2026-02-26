"""Agent loop: the core processing engine."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import ExecToolConfig, GoogleConfig, NotionConfig
    from nanobot.cron.service import CronService

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import SessionManager


# Silent mode keyword - agent returns this to skip sending response
SILENT_RESPONSE_KEYWORD = "SILENT"


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with dashboard state, memory, skills (stateless)
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        restrict_to_workspace: bool = False,
        notion_config: "NotionConfig | None" = None,
        google_config: "GoogleConfig | None" = None,
        notification_chat_id: str | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig

        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self.notion_config = notion_config
        self._notification_chat_id = notification_chat_id

        # Google Calendar client (sync I/O, initialized eagerly when enabled)
        self._gcal_client = None
        if google_config and google_config.calendar.enabled:
            try:
                from nanobot.google.calendar import GoogleCalendarClient

                cal = google_config.calendar
                self._gcal_client = GoogleCalendarClient(
                    client_secret_path=cal.client_secret_path,
                    token_path=cal.token_path,
                    calendar_id=cal.calendar_id,
                )
                self._gcal_timezone = cal.timezone
                self._gcal_duration_minutes = cal.default_duration_minutes
                logger.info("Google Calendar client configured")
            except Exception as e:
                logger.warning(f"Failed to configure Google Calendar: {e}")
        if not self._gcal_client:
            self._gcal_timezone = "Asia/Seoul"
            self._gcal_duration_minutes = 30

        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._storage_backend = None
        self._notion_setup_warning: str | None = None  # One-time warning for user
        self._configure_storage_backend()
        # Wire storage backend to context builder so dashboard summary uses Notion
        self.context.storage_backend = self._storage_backend

        # Processing lock shared with Heartbeat/Scheduler
        self._processing_lock = asyncio.Lock()
        self._scheduler = self._create_scheduler()

        self._register_default_tools()

    @property
    def storage_backend(self):
        """Public access to the configured storage backend."""
        return self._storage_backend

    @property
    def gcal_client(self):
        """Public access to the Google Calendar client (or None if not configured)."""
        return self._gcal_client

    @property
    def gcal_timezone(self) -> str:
        """Google Calendar timezone setting."""
        return self._gcal_timezone

    @property
    def gcal_duration_minutes(self) -> int:
        """Google Calendar default event duration in minutes."""
        return self._gcal_duration_minutes

    @property
    def processing_lock(self) -> asyncio.Lock:
        """Shared processing lock (used by Heartbeat and Scheduler)."""
        return self._processing_lock

    @property
    def scheduler(self):
        """Public access to the ReconciliationScheduler (or None)."""
        return self._scheduler

    def _create_scheduler(self):
        """Create ReconciliationScheduler for notification delivery.

        Always set in gateway mode (both Notion and JSON backends).
        Returns None only if storage backend initialization failed.
        """
        if not self._storage_backend:
            return None

        try:
            from nanobot.dashboard.reconciler import (
                NotificationReconciler,
                ReconciliationScheduler,
            )

            reconciler = NotificationReconciler(
                storage_backend=self._storage_backend,
                gcal_client=self._gcal_client,
                gcal_timezone=self._gcal_timezone,
                gcal_duration_minutes=self._gcal_duration_minutes,
                default_chat_id=self._notification_chat_id,
                default_channel="telegram",
            )
            return ReconciliationScheduler(
                reconciler=reconciler,
                send_callback=self.bus.publish_outbound,
                processing_lock=self._processing_lock,
            )
        except ImportError:
            logger.info("Reconciler not available (optional dependency)")
            return None

    async def _precompute_dashboard(self) -> None:
        """Precompute dashboard summary off the event loop when Notion backend is active."""
        if self._storage_backend:
            from nanobot.dashboard.helper import get_dashboard_summary

            dashboard_summary = await asyncio.to_thread(
                get_dashboard_summary,
                self.workspace / "dashboard",
                self._storage_backend,
            )
            self.context.set_dashboard_summary(dashboard_summary)

    def _configure_storage_backend(self) -> None:
        """Configure the storage backend based on Notion config.

        If Notion is enabled and configured, uses NotionStorageBackend.
        All fallback paths create JsonStorageBackend so that the scheduler
        and tools always have a working backend.
        """
        from nanobot.dashboard.storage import JsonStorageBackend

        if self.notion_config and self.notion_config.enabled and self.notion_config.token:
            # Validate that core DB IDs are configured
            dbs = self.notion_config.databases
            if not dbs.tasks or not dbs.questions:
                logger.warning(
                    "Notion enabled but core DB IDs (tasks/questions) missing, using JSON fallback"
                )
                self._notion_setup_warning = (
                    "⚠️ Notion enabled but tasks/questions DB IDs are missing. "
                    "Run `nanobot notion validate` to check your config. "
                    "Using local JSON fallback."
                )
                self._storage_backend = JsonStorageBackend(self.workspace)
                return

            try:
                from nanobot.notion.client import NotionClient
                from nanobot.notion.storage import NotionStorageBackend

                client = NotionClient(token=self.notion_config.token)
                backend = NotionStorageBackend(
                    client=client,
                    databases=self.notion_config.databases,
                    cache_ttl_s=self.notion_config.cache_ttl_s,
                )
                self._storage_backend = backend
                logger.info("Notion storage backend configured")
            except Exception as e:
                logger.error(f"Failed to configure Notion backend: {e}, using JSON fallback")
                self._notion_setup_warning = (
                    "⚠️ Notion backend failed to initialize. "
                    "Using local JSON fallback. Check your Notion config."
                )
                self._storage_backend = JsonStorageBackend(self.workspace)
        else:
            self._storage_backend = JsonStorageBackend(self.workspace)
            logger.debug("Using JSON storage backend (Notion not configured)")

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools (restrict to workspace if configured)
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(ReadFileTool(allowed_dir=allowed_dir))
        self.tools.register(WriteFileTool(allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(allowed_dir=allowed_dir))
        self.tools.register(ListDirTool(allowed_dir=allowed_dir))

        # Shell tool
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            )
        )

        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())

        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)

        # Dashboard tools
        from nanobot.agent.tools.dashboard import (
            CreateTaskTool,
            UpdateTaskTool,
            AnswerQuestionTool,
            CreateQuestionTool,
            UpdateQuestionTool,
            RemoveQuestionTool,
            ArchiveTaskTool,
            SaveInsightTool,
            ScheduleNotificationTool,
            UpdateNotificationTool,
            CancelNotificationTool,
            ListNotificationsTool,
        )

        self.tools.register(CreateTaskTool(self.workspace, self._storage_backend))
        self.tools.register(UpdateTaskTool(self.workspace, self._storage_backend))
        self.tools.register(AnswerQuestionTool(self.workspace, self._storage_backend))
        self.tools.register(CreateQuestionTool(self.workspace, self._storage_backend))
        self.tools.register(UpdateQuestionTool(self.workspace, self._storage_backend))
        self.tools.register(RemoveQuestionTool(self.workspace, self._storage_backend))
        self.tools.register(ArchiveTaskTool(self.workspace, self._storage_backend))
        self.tools.register(SaveInsightTool(self.workspace, self._storage_backend))

        # Notification tools (always registered — ledger-only, no cron dependency)
        self.tools.register(ScheduleNotificationTool(self.workspace, self._storage_backend))
        self.tools.register(UpdateNotificationTool(self.workspace, self._storage_backend))
        self.tools.register(CancelNotificationTool(self.workspace, self._storage_backend))
        self.tools.register(ListNotificationsTool(self.workspace, self._storage_backend))

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")

        # Initial reconciliation pass (deliver overdue notifications)
        if self._scheduler:
            try:
                async with self._processing_lock:
                    await self._scheduler.trigger()
            except Exception as e:
                logger.warning(f"Initial scheduler trigger failed: {e}")

        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)

                # Process it
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Send error response
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=f"Sorry, I encountered an error: {str(e)}",
                        )
                    )
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        """Stop the agent loop and clean up resources."""
        self._running = False
        if self._scheduler:
            self._scheduler.stop()
        if self._storage_backend:
            try:
                self._storage_backend.close()
            except Exception as e:
                logger.warning(f"Error closing storage backend: {e}")
        if self._gcal_client:
            try:
                self._gcal_client.close()
            except Exception as e:
                logger.warning(f"Error closing GCal client: {e}")
        logger.info("Agent loop stopping")

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """Process a single inbound message under _processing_lock.

        Acquires the shared processing lock for the entire duration so that
        Heartbeat/Worker cannot run concurrently.  Triggers reconciliation
        (GCal sync + delivery) after the message is handled.
        """
        async with self._processing_lock:
            response = await self._handle_message(msg)

            if self._scheduler:
                try:
                    await self._scheduler.trigger()
                except Exception as e:
                    logger.warning(f"Post-message scheduler trigger failed: {e}")

            return response

    async def _handle_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """Actual message processing logic (called under _processing_lock).

        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)

        # Invalidate Notion cache at message start so user edits are picked up
        if self._storage_backend:
            self._storage_backend.invalidate_cache()

        # Send one-time Notion setup warning to user (first message only)
        if self._notion_setup_warning:
            warning = self._notion_setup_warning
            self._notion_setup_warning = None
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=warning,
                )
            )

        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")

        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)

        # Update tool contexts
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)

        # Handle pre-parsed question answers from numbered mapping
        answer_results: list[str] = []
        question_answers = msg.metadata.get("question_answers")
        if question_answers and isinstance(question_answers, dict):
            answer_tool = self.tools.get("answer_question")
            if answer_tool:
                for q_id, answer in question_answers.items():
                    try:
                        result = await answer_tool.execute(question_id=q_id, answer=answer)
                        answer_results.append(result)
                        logger.info(f"Auto-answered {q_id}: {result}")
                    except Exception as e:
                        answer_results.append(f"Error answering {q_id}: {e}")
                        logger.error(f"Failed to auto-answer {q_id}: {e}")

        # Inject answer results into the message content for Agent awareness
        effective_content = msg.content
        if answer_results:
            summary = "\n".join(f"- {r}" for r in answer_results)
            prefix = f"[System: Auto-answered {len(answer_results)} question(s):\n{summary}]"
            if effective_content:
                effective_content = f"{prefix}\n\n{effective_content}"
            else:
                # All content was numbered answers — no remaining user message.
                # Skip LLM call entirely (saves tokens, prevents spurious messages).
                logger.info(f"All answers auto-processed, skipping LLM call")
                session.add_message("user", msg.content or "[numbered answers]")
                session.add_message("assistant", "[Dashboard updated silently]")
                self.sessions.save(session)
                return self._reaction_message(msg, "👍")

        await self._precompute_dashboard()

        # Build messages (history param kept for session logging, not used in LLM context)
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=effective_content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        # Agent loop
        iteration = 0
        final_content = None

        while iteration < self.max_iterations:
            iteration += 1

            # Call LLM
            response = await self.provider.chat(
                messages=messages, tools=self.tools.get_definitions(), model=self.model
            )

            # Handle tool calls
            if response.has_tool_calls:
                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),  # Must be JSON string
                        },
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )

                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # No tool calls, we're done
                final_content = response.content
                break

        if final_content is None:
            final_content = SILENT_RESPONSE_KEYWORD

        # Check for Silent mode
        is_silent = final_content.strip().upper() == SILENT_RESPONSE_KEYWORD

        # Save to session (always save for logging/debugging)
        session.add_message("user", msg.content)
        if is_silent:
            session.add_message("assistant", "[Dashboard updated silently]")
        else:
            session.add_message("assistant", final_content)
        self.sessions.save(session)

        # Silent mode: send 👍 reaction instead of a text message
        if is_silent:
            logger.debug(f"Silent mode: Dashboard updated without response")
            response_msg = self._reaction_message(msg, "👍")
        else:
            response_msg = OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=final_content
            )

        return response_msg

    @staticmethod
    def _reaction_message(msg: InboundMessage, emoji: str) -> OutboundMessage | None:
        """Create a reaction-only OutboundMessage (no text, just an emoji reaction).

        Returns None if the inbound message has no message_id (e.g. CLI).
        """
        msg_id = msg.metadata.get("message_id")
        if not msg_id:
            return None
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content="",
            metadata={"reaction": emoji, "message_id": msg_id},
        )

    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).

        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info(f"Processing system message from {msg.sender_id}")

        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id

        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)

        # Update tool contexts
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)

        await self._precompute_dashboard()

        # Build messages (history param kept for session logging, not used in LLM context)
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
        )

        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages, tools=self.tools.get_definitions(), model=self.model
            )

            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )

                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break

        if final_content is None:
            final_content = SILENT_RESPONSE_KEYWORD

        is_silent = final_content.strip().upper() == SILENT_RESPONSE_KEYWORD

        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message(
            "assistant", "[Dashboard updated silently]" if is_silent else final_content
        )
        self.sessions.save(session)

        if is_silent:
            return None

        return OutboundMessage(
            channel=origin_channel, chat_id=origin_chat_id, content=final_content
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).

        Args:
            content: The message content.
            session_key: Session identifier.
            channel: Source channel (for context).
            chat_id: Source chat ID (for context).

        Returns:
            The agent's response.
        """
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)

        response = await self._process_message(msg)
        return response.content if response else ""
