"""Unified Worker Agent for dashboard maintenance.

Combines deterministic maintenance (always runs) with LLM-powered analysis
(runs when provider/model are available). Replaces the old split between
rule-based WorkerAgent and LLMWorkerAgent.

DESIGN: Question generation is intentionally LLM-only (Phase 2).
The old rule-based worker had 7 progress check cases with cooldown and
priority escalation, but these were brittle and produced generic questions.
The LLM approach trades deterministic guarantees for context-aware analysis:
  - Pro: richer, context-aware questions; fewer false positives
  - Con: no questions when provider/model unavailable (e.g. CLI manual run)
  - Mitigation: Phase 1 still handles all deterministic maintenance
    (archive, status reevaluation, cleanup), so dashboard integrity is safe.
    Question generation is a "nice to have" — missing a cycle is harmless.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.dashboard.storage import StorageBackend

from loguru import logger


def parse_datetime(dt_str: str) -> datetime:
    """Parse ISO datetime string to naive datetime.

    Strips timezone info to avoid naive/aware comparison TypeError
    with datetime.now(). Acceptable for single-user, single-timezone usage.
    """
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    return dt.replace(tzinfo=None)


class WorkerAgent:
    """
    Unified Dashboard Worker Agent.

    Phase 1 — Deterministic maintenance (always runs):
      - Archive completed/cancelled tasks
      - Re-evaluate active/someday status
      - Clean up answered + stale questions

    Phase 2 — LLM-powered analysis (requires provider and model):
      - Analyze task progress, schedule notifications
      - Manage question queue (create/update/remove)
      - Clean up obsolete data
      NOTE: Skipped when provider/model are not configured.
      This means question generation and notification scheduling only happen
      when the LLM is available (e.g. gateway mode, not CLI manual run).
    """

    # Status evaluation thresholds
    DEADLINE_APPROACHING_DAYS = 7

    def __init__(
        self,
        workspace: Path,
        storage_backend: StorageBackend,
        provider: Any | None = None,
        model: str | None = None,
        cron_service: Any | None = None,
        bus: Any | None = None,
    ):
        self.workspace = workspace
        self.storage_backend = storage_backend
        self.provider = provider
        self.model = model
        self.cron_service = cron_service
        self.bus = bus  # Reserved for future event bus integration
        # Recreated each _run_llm_cycle(); None when Phase 2 never runs.
        self.tools: ToolRegistry | None = None

    # =========================================================================
    # Public API
    # =========================================================================

    async def run_cycle(self) -> None:
        """Run a full worker cycle: maintenance first, then LLM analysis."""
        logger.info("[Worker] Starting cycle...")

        # Phase 1: Deterministic maintenance (always runs, no LLM needed)
        await self._run_maintenance()

        # Phase 2: LLM-powered analysis (requires provider + model).
        # When unavailable (e.g. `nanobot dashboard worker` CLI), only Phase 1
        # runs — question generation and notification scheduling are skipped.
        # This is an intentional trade-off: see module docstring for rationale.
        if self.provider is not None and self.model is not None:
            await self._run_llm_cycle()
        else:
            logger.debug("[Worker] LLM not configured; skipping Phase 2")

        logger.info("[Worker] Cycle complete.")

    # =========================================================================
    # Phase 1: Deterministic Maintenance
    # =========================================================================

    async def _run_maintenance(self) -> None:
        """Run deterministic maintenance tasks."""
        # --- Tasks ---
        try:
            tasks_data = self.storage_backend.load_tasks()
            changed = self._archive_completed_tasks(tasks_data)
            changed |= self._reevaluate_active_status(tasks_data)
            if changed:
                ok, msg = self.storage_backend.save_tasks(tasks_data)
                if not ok:
                    logger.error(f"[Worker] Failed to save tasks: {msg}")
        except Exception:
            logger.exception("[Worker] Task maintenance error")

        # --- Questions ---
        try:
            questions_data = self.storage_backend.load_questions()
            if self._cleanup_answered_questions(questions_data):
                ok, msg = self.storage_backend.save_questions(questions_data)
                if not ok:
                    logger.error(f"[Worker] Failed to save questions: {msg}")
        except Exception:
            logger.exception("[Worker] Question maintenance error")

    def _archive_completed_tasks(self, tasks_data: dict) -> bool:
        """Archive completed or cancelled tasks by setting status to 'archived'."""
        tasks = tasks_data.get("tasks", [])
        targets = [t for t in tasks if t.get("status") in ("completed", "cancelled")]

        if not targets:
            return False

        now = datetime.now().isoformat()
        for task in targets:
            was_cancelled = task.get("status") == "cancelled"
            task["status"] = "archived"
            task["completed_at"] = task.get("completed_at") or now
            progress = task.setdefault("progress", {"last_update": now})
            if not was_cancelled:
                progress["percentage"] = 100
            progress.setdefault("last_update", now)
            task["updated_at"] = now
            logger.info(f"[Worker] Task archived: {task.get('title', '<unknown>')}")

        return True

    def _reevaluate_active_status(self, tasks_data: dict) -> bool:
        """Re-evaluate active/someday status for non-terminal tasks."""
        now = datetime.now()
        tasks = tasks_data.get("tasks", [])
        changed = False

        for task in tasks:
            if task.get("status") in ("completed", "cancelled", "archived"):
                continue

            old_status = task.get("status", "someday")
            try:
                new_status = self._determine_status(task, now)
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(f"[Worker] Skipping status eval for {task.get('id', '?')}: {e}")
                continue

            if old_status != new_status:
                task["status"] = new_status
                changed = True
                logger.info(
                    f"[Worker] Task '{task.get('title', '<unknown>')}' "
                    f"status: {old_status} → {new_status}"
                )

        return changed

    def _determine_status(self, task: dict, now: datetime) -> str:
        """Determine if task should be active or someday."""
        # Has deadline and it's close → active
        if task.get("deadline"):
            deadline = parse_datetime(task["deadline"])
            days_until = (deadline - now).days
            if days_until <= self.DEADLINE_APPROACHING_DAYS:
                return "active"

        # High priority → active
        if task.get("priority") == "high":
            return "active"

        # Has progress → active
        if task.get("progress", {}).get("percentage", 0) > 0:
            return "active"

        # Recent update → active
        last_update = parse_datetime(
            task.get("progress", {}).get("last_update", task.get("created_at", now.isoformat()))
        )
        days_since_update = (now - last_update).days
        if days_since_update <= 7:
            return "active"

        return "someday"

    def _cleanup_answered_questions(self, questions_data: dict) -> bool:
        """Remove answered questions and questions older than 14 days."""
        questions = questions_data.get("questions", [])
        now = datetime.now()
        original_count = len(questions)

        filtered = []
        for q in questions:
            # Remove answered questions
            if q.get("answered", False):
                continue
            # Remove very old questions (14+ days)
            try:
                created = parse_datetime(q["created_at"])
                if (now - created).days > 14:
                    continue
            except (KeyError, ValueError):
                pass
            filtered.append(q)

        if len(filtered) == original_count:
            return False

        questions_data["questions"] = filtered
        logger.info(f"[Worker] Question queue cleaned: {original_count} → {len(filtered)}")
        return True

    # =========================================================================
    # Phase 2: LLM-Powered Analysis
    # =========================================================================

    async def _run_llm_cycle(self) -> None:
        """Run LLM-powered analysis cycle."""
        logger.info("[Worker] Starting LLM-powered analysis")

        try:
            from nanobot.agent.tools.registry import ToolRegistry

            # Recreated each cycle (not cached across cycles).
            # Stored on self so tests can inspect registered tools after run_cycle().
            self.tools = ToolRegistry()
            self._register_worker_tools()

            # Build context
            messages = await self._build_context()

            # Get tool schemas
            tool_schemas = [self.tools.get(name).to_schema() for name in self.tools.tool_names]

            # Run LLM loop with tool calls (max 10 iterations)
            max_iterations = 10
            temperature = 0.3

            for iteration in range(max_iterations):
                logger.debug(f"[Worker] LLM iteration {iteration + 1}/{max_iterations}")

                response = await self.provider.chat(
                    model=self.model,
                    messages=messages,
                    tools=tool_schemas,
                    temperature=temperature,
                )

                tool_calls = response.tool_calls

                if not tool_calls:
                    final_message = response.content or ""
                    if final_message:
                        logger.info(f"[Worker] LLM: {final_message}")
                    break

                # Add assistant message to history
                tool_calls_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in tool_calls
                ]
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_calls_dicts,
                    }
                )

                # Execute tool calls
                tool_results = []
                for tool_call in tool_calls:
                    tool_name = tool_call.name
                    tool_args = tool_call.arguments
                    tool_id = tool_call.id

                    logger.debug(f"[Worker] Executing tool {tool_name}")

                    try:
                        result = await self.tools.execute(tool_name, tool_args)
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_name,
                                "content": result,
                            }
                        )
                        logger.debug(f"[Worker] Tool {tool_name} result: {result[:200]}")
                    except Exception as e:
                        error_msg = f"Error: {str(e)}"
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_name,
                                "content": error_msg,
                            }
                        )
                        logger.exception(f"[Worker] Tool {tool_name} error")

                messages.extend(tool_results)

            logger.info("[Worker] LLM analysis completed")

        except Exception:
            logger.exception("[Worker] LLM analysis error")

    async def _build_context(self) -> list[dict]:
        """Build context messages for the LLM cycle."""
        from nanobot.dashboard.helper import get_dashboard_summary

        messages = []

        # 1. Load WORKER.md instructions
        worker_instructions_path = self.workspace / "WORKER.md"
        if worker_instructions_path.exists():
            worker_instructions = worker_instructions_path.read_text(encoding="utf-8")
            messages.append({"role": "system", "content": worker_instructions})
        else:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "You are the Worker Agent. Analyze the Dashboard "
                        "and perform maintenance tasks:\n"
                        "- Schedule notifications for deadlines and progress checks\n"
                        "- Manage question queue (create, update, remove)\n"
                        "- Clean up obsolete data\n"
                        "Note: Task archiving is handled by Phase 1.\n"
                        "Operate autonomously and efficiently."
                    ),
                }
            )

        # 2. Build Dashboard Summary + Notifications Summary
        # DESIGN: Always use asyncio.to_thread even for JsonStorageBackend.
        # Negligible overhead for JSON but keeps the code path uniform
        # with NotionStorageBackend (sync httpx, ~300ms).
        # Simplicity over micro-optimization for a 30-minute-interval task.
        dashboard_summary = await asyncio.to_thread(
            get_dashboard_summary,
            self.workspace / "dashboard",
            self.storage_backend,
        )
        notifications_summary = await asyncio.to_thread(self._build_notifications_summary)

        # 3. Combine into user message
        user_message = (
            "## Current Dashboard State\n\n"
            f"{dashboard_summary}\n\n"
            f"{notifications_summary}\n\n"
            "위 상태를 분석하고 필요한 유지보수를 수행하라."
        )
        messages.append({"role": "user", "content": user_message})

        return messages

    def _build_notifications_summary(self) -> str:
        """Build summary of scheduled notifications."""
        try:
            data = self.storage_backend.load_notifications()
            notifications = data.get("notifications", [])

            if not notifications:
                return "## Scheduled Notifications\n\nNo notifications scheduled."

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
                    f"- **{notif.get('id', '?')}** "
                    f"({notif.get('type', '?')}, {notif.get('priority', '?')}): "
                    f"{notif.get('message', '')} [Scheduled: {time_str}]"
                )
                if notif.get("related_task_id"):
                    lines.append(f"  Related Task: {notif['related_task_id']}")

            return "\n".join(lines)

        except Exception:
            logger.exception("[Worker] Error building notifications summary")
            return "## Scheduled Notifications\n\nError loading notifications."

    def _register_worker_tools(self) -> None:
        """Register all tools available to the Worker Agent."""
        # Question management
        from nanobot.agent.tools.dashboard.create_question import CreateQuestionTool
        from nanobot.agent.tools.dashboard.remove_question import RemoveQuestionTool
        from nanobot.agent.tools.dashboard.update_question import UpdateQuestionTool

        self.tools.register(CreateQuestionTool(self.workspace))
        self.tools.register(UpdateQuestionTool(self.workspace))
        self.tools.register(RemoveQuestionTool(self.workspace))

        # Notification management
        from nanobot.agent.tools.dashboard.cancel_notification import (
            CancelNotificationTool,
        )
        from nanobot.agent.tools.dashboard.list_notifications import (
            ListNotificationsTool,
        )
        from nanobot.agent.tools.dashboard.schedule_notification import (
            ScheduleNotificationTool,
        )
        from nanobot.agent.tools.dashboard.update_notification import (
            UpdateNotificationTool,
        )

        self.tools.register(ScheduleNotificationTool(self.workspace, self.cron_service))
        self.tools.register(UpdateNotificationTool(self.workspace, self.cron_service))
        self.tools.register(CancelNotificationTool(self.workspace, self.cron_service))
        self.tools.register(ListNotificationsTool(self.workspace))

        # Task management
        from nanobot.agent.tools.dashboard.archive_task import ArchiveTaskTool
        from nanobot.agent.tools.dashboard.update_task import UpdateTaskTool

        self.tools.register(UpdateTaskTool(self.workspace))
        self.tools.register(ArchiveTaskTool(self.workspace))
