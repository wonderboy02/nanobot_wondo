"""LLM-powered Worker Agent for autonomous Dashboard maintenance."""

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.cron.service import CronService
from nanobot.dashboard.helper import get_dashboard_summary
from nanobot.providers.litellm_provider import LiteLLMProvider as LLMProvider


class LLMWorkerAgent:
    """
    LLM-powered Worker Agent for intelligent Dashboard maintenance.

    Runs periodically (via Heartbeat) to:
    - Analyze task progress and schedule notifications
    - Manage question queue (create/update/remove)
    - Clean up obsolete data
    - Archive completed tasks
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        cron_service: CronService,
        bus: MessageBus,
        storage_backend: "StorageBackend | None" = None,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.cron_service = cron_service
        self.bus = bus
        self.storage_backend = storage_backend
        self.tools = ToolRegistry()

        # Register Worker-specific tools
        self._register_worker_tools()

    def _register_worker_tools(self):
        """Register all tools available to Worker Agent."""
        # Question management (3 tools)
        # Worker creates, updates, and removes questions autonomously
        # Note: answer_question removed - Worker doesn't answer questions (Main Agent's role)
        from nanobot.agent.tools.dashboard.create_question import CreateQuestionTool
        from nanobot.agent.tools.dashboard.update_question import UpdateQuestionTool
        from nanobot.agent.tools.dashboard.remove_question import RemoveQuestionTool

        self.tools.register(CreateQuestionTool(self.workspace))
        self.tools.register(UpdateQuestionTool(self.workspace))
        self.tools.register(RemoveQuestionTool(self.workspace))

        # Notification management (4 tools)
        # Worker schedules, updates, cancels, and lists notifications
        from nanobot.agent.tools.dashboard.schedule_notification import ScheduleNotificationTool
        from nanobot.agent.tools.dashboard.update_notification import UpdateNotificationTool
        from nanobot.agent.tools.dashboard.cancel_notification import CancelNotificationTool
        from nanobot.agent.tools.dashboard.list_notifications import ListNotificationsTool

        self.tools.register(ScheduleNotificationTool(self.workspace, self.cron_service))
        self.tools.register(UpdateNotificationTool(self.workspace, self.cron_service))
        self.tools.register(CancelNotificationTool(self.workspace, self.cron_service))
        self.tools.register(ListNotificationsTool(self.workspace))

        # Task management (2 tools)
        # Worker updates and archives tasks
        # Note: create_task removed - Worker doesn't create tasks (Main Agent's role)
        from nanobot.agent.tools.dashboard.update_task import UpdateTaskTool
        from nanobot.agent.tools.dashboard.archive_task import ArchiveTaskTool

        self.tools.register(UpdateTaskTool(self.workspace))
        self.tools.register(ArchiveTaskTool(self.workspace))

        # Knowledge management removed - save_insight not actively used

    async def _build_context(self) -> list[dict]:
        """Build context messages for Worker Agent."""
        messages = []

        # 1. Load WORKER.md instructions
        worker_instructions_path = self.workspace / "WORKER.md"
        if worker_instructions_path.exists():
            worker_instructions = worker_instructions_path.read_text(encoding="utf-8")
            messages.append({
                "role": "system",
                "content": worker_instructions
            })
        else:
            # Fallback minimal instructions
            messages.append({
                "role": "system",
                "content": (
                    "You are the Worker Agent. Analyze the Dashboard and perform maintenance tasks:\n"
                    "- Schedule notifications for deadlines and progress checks\n"
                    "- Manage question queue (create, update, remove)\n"
                    "- Archive completed tasks\n"
                    "- Clean up obsolete data\n"
                    "Operate autonomously and efficiently."
                )
            })

        # 2. Build Dashboard Summary + Notifications Summary
        # Use asyncio.to_thread when Notion backend is active to avoid blocking
        if self.storage_backend is not None:
            dashboard_summary = await asyncio.to_thread(
                get_dashboard_summary,
                self.workspace / "dashboard",
                self.storage_backend,
            )
            notifications_summary = await asyncio.to_thread(
                self._build_notifications_summary
            )
        else:
            dashboard_summary = get_dashboard_summary(self.workspace / "dashboard")
            notifications_summary = self._build_notifications_summary()

        # 4. Combine into user message
        user_message = (
            "## Current Dashboard State\n\n"
            f"{dashboard_summary}\n\n"
            f"{notifications_summary}\n\n"
            "## Your Task\n\n"
            "Analyze the Dashboard state and perform necessary maintenance actions:\n"
            "1. Check for tasks needing notifications (deadlines, stagnant progress, blockers)\n"
            "2. Manage question queue (create, update, remove as needed)\n"
            "3. Archive completed tasks\n"
            "4. Schedule appropriate notifications (check existing ones first!)\n"
            "5. Clean up obsolete questions\n\n"
            "Use the available tools to make changes. Be proactive but avoid spam."
        )

        messages.append({
            "role": "user",
            "content": user_message
        })

        return messages

    def _build_notifications_summary(self) -> str:
        """Build summary of scheduled notifications."""
        from datetime import datetime

        try:
            if self.storage_backend is not None:
                data = self.storage_backend.load_notifications()
            else:
                notifications_path = self.workspace / "dashboard" / "notifications.json"
                if not notifications_path.exists():
                    return "## Scheduled Notifications\n\nNo notifications scheduled."
                data = json.loads(notifications_path.read_text(encoding="utf-8"))
            notifications = data.get("notifications", [])

            if not notifications:
                return "## Scheduled Notifications\n\nNo notifications scheduled."

            # Filter pending notifications
            pending = [n for n in notifications if n.get("status") == "pending"]

            if not pending:
                return "## Scheduled Notifications\n\nNo pending notifications."

            lines = ["## Scheduled Notifications\n"]
            for notif in pending:
                scheduled_at = notif.get("scheduled_at", "")
                try:
                    dt = datetime.fromisoformat(scheduled_at)
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    time_str = scheduled_at

                lines.append(
                    f"- **{notif['id']}** ({notif['type']}, {notif['priority']}): "
                    f"{notif['message']} [Scheduled: {time_str}]"
                )
                if notif.get("related_task_id"):
                    lines.append(f"  Related Task: {notif['related_task_id']}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Error building notifications summary: {e}")
            return "## Scheduled Notifications\n\nError loading notifications."

    async def run_cycle(self) -> None:
        """Run a single Worker Agent cycle."""
        logger.info("Worker Agent: Starting LLM-powered cycle")

        try:
            # Build context
            messages = await self._build_context()

            # Get tool schemas
            tool_schemas = [self.tools.get(name).to_schema() for name in self.tools.tool_names]

            # Run LLM loop with tool calls (max 10 iterations)
            max_iterations = 10
            temperature = 0.3  # Low temperature for consistency

            for iteration in range(max_iterations):
                logger.debug(f"Worker Agent: Iteration {iteration + 1}/{max_iterations}")

                # Call LLM
                response = await self.provider.chat(
                    model=self.model,
                    messages=messages,
                    tools=tool_schemas if tool_schemas else None,
                    temperature=temperature
                )

                # Check for tool calls (LLMResponse is a dataclass, not a dict)
                tool_calls = response.tool_calls

                if not tool_calls:
                    # No more tool calls - Worker is done
                    final_message = response.content or ""
                    if final_message:
                        logger.info(f"Worker Agent: {final_message}")
                    break

                # Add assistant message to history
                # Convert ToolCallRequest dataclasses to dicts for message format
                tool_calls_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in tool_calls
                ]
                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": tool_calls_dicts
                })

                # Execute tool calls (ToolCallRequest is a dataclass)
                tool_results = []
                for tool_call in tool_calls:
                    tool_name = tool_call.name
                    tool_args = tool_call.arguments
                    tool_id = tool_call.id

                    logger.debug(f"Worker Agent: Executing tool {tool_name}")

                    try:
                        result = await self.tools.execute(tool_name, tool_args)
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "name": tool_name,
                            "content": result
                        })
                        logger.debug(f"Worker Agent: Tool {tool_name} result: {result[:200]}")
                    except Exception as e:
                        error_msg = f"Error: {str(e)}"
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "name": tool_name,
                            "content": error_msg
                        })
                        logger.error(f"Worker Agent: Tool {tool_name} error: {e}")

                # Add tool results to messages
                messages.extend(tool_results)

            logger.info("Worker Agent: Cycle completed")

        except Exception as e:
            logger.error(f"Worker Agent: Error during cycle: {e}")
