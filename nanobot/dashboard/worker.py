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

    Extract — Read-only snapshot (always runs):
      - Extract answered questions for Phase 2 context

    Phase 2 — LLM-powered analysis (requires provider and model):
      - Analyze task progress, schedule notifications
      - Process answered questions (update tasks, save insights)
      - Manage question queue (create/update/remove)
      NOTE: Skipped when provider/model are not configured.

    Cleanup — Question cleanup (always runs, after Phase 2):
      - Remove stale (14+ day) unanswered questions
      - Remove answered questions only if Phase 2 succeeded
        (preserved for retry when Phase 2 was skipped/failed)
    """

    # Status evaluation thresholds
    DEADLINE_APPROACHING_DAYS = 7
    # Max answered questions to include in LLM context (prevents prompt blowup
    # after extended LLM downtime). Oldest beyond this cap are still cleaned up.
    MAX_ANSWERED_IN_CONTEXT = 20

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
        """Run a full worker cycle.

        Order: maintenance → extract answers → LLM analysis → question cleanup.
        Question cleanup is deferred until after Phase 2 so that the LLM can
        see answered questions and take action (update tasks, save insights).

        If Phase 2 is skipped or fails while there are pending answers,
        cleanup preserves answered questions so the next cycle can retry.
        """
        logger.info("[Worker] Starting cycle...")

        # Phase 1: Deterministic maintenance — tasks only (always runs)
        await self._run_maintenance()

        # Extract answered questions before cleanup (read-only snapshot)
        pending_answers = self._extract_answered_questions()

        # Phase 2: LLM-powered analysis (requires provider + model).
        # When unavailable (e.g. `nanobot dashboard worker` CLI), only Phase 1
        # runs — question generation and notification scheduling are skipped.
        # This is an intentional trade-off: see module docstring for rationale.
        phase2_ok = False
        if self.provider is not None and self.model is not None:
            phase2_ok = await self._run_llm_cycle(pending_answers)
        else:
            logger.debug("[Worker] LLM not configured; skipping Phase 2")

        # Cleanup: remove answered + stale questions (after Phase 2 processed them).
        # If Phase 2 was skipped/failed AND there were pending answers, preserve
        # answered questions so they can be retried in the next cycle.
        # NOTE: Partial Phase 2 success (some tool calls ran before crash) may
        # cause duplicate side effects on retry. Accepted trade-off: the LLM sees
        # fresh dashboard state each cycle, so already-saved insights / updated
        # tasks are visible and the LLM should avoid re-doing them. For a
        # single-user 30-min-interval system, this is preferable to the
        # complexity of partial-success tracking.
        # Compute which answered question IDs were actually shown to the LLM
        # (capped at MAX_ANSWERED_IN_CONTEXT). Questions beyond the cap are
        # preserved for the next cycle to avoid unprocessed data loss.
        processed_ids: set[str] | None = None
        if pending_answers:
            processed_ids = {
                q.get("id", "") for q in pending_answers[: self.MAX_ANSWERED_IN_CONTEXT]
            }

        skip_answered = bool(pending_answers) and not phase2_ok
        await self._cleanup_questions(skip_answered=skip_answered, processed_ids=processed_ids)
        if skip_answered:
            logger.info(
                "[Worker] Preserved {} answered question(s) for next cycle",
                len(pending_answers),
            )

        logger.info("[Worker] Cycle complete.")

    # =========================================================================
    # Phase 1: Deterministic Maintenance
    # =========================================================================

    async def _run_maintenance(self) -> None:
        """Run deterministic maintenance tasks (tasks only).

        Question cleanup is handled separately by _cleanup_questions()
        after Phase 2, so the LLM can process answered questions first.
        """
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

    def _cleanup_answered_questions(
        self,
        questions_data: dict,
        *,
        skip_answered: bool = False,
        processed_ids: set[str] | None = None,
    ) -> bool:
        """Remove answered questions and questions older than 14 days.

        Args:
            skip_answered: When True, keep answered questions (they haven't
                been processed by Phase 2 yet). Stale questions still removed.
            processed_ids: When provided, only remove answered questions whose
                ID is in this set (the ones actually shown to the LLM).
                Questions beyond the MAX_ANSWERED_IN_CONTEXT cap are preserved.
        """
        questions = questions_data.get("questions", [])
        now = datetime.now()
        original_count = len(questions)

        filtered = []
        for q in questions:
            is_answered = q.get("answered", False) or (q.get("answer") or "").strip()

            # Remove answered questions (flag or non-empty answer field)
            if not skip_answered and is_answered:
                # If processed_ids is set, only remove questions the LLM actually saw;
                # overflow beyond MAX_ANSWERED_IN_CONTEXT is preserved for next cycle.
                if processed_ids is not None and q.get("id") not in processed_ids:
                    filtered.append(q)
                continue

            # Remove very old questions (14+ days) — but not answered ones
            # when skip_answered is set (they need to survive for next cycle)
            if not (skip_answered and is_answered):
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

    def _extract_answered_questions(self) -> list[dict]:
        """Extract answered questions from storage (read-only).

        Detects both ``answered=True`` and non-empty ``answer`` field
        (covers case where user fills Answer but forgets the checkbox).
        """
        try:
            questions_data = self.storage_backend.load_questions()
            questions = questions_data.get("questions", [])
            answered = [
                q for q in questions if q.get("answered", False) or (q.get("answer") or "").strip()
            ]
            if answered:
                logger.info(f"[Worker] Found {len(answered)} answered question(s)")
            return answered
        except Exception:
            logger.exception("[Worker] Error extracting answered questions")
            return []

    def _build_answered_questions_summary(self, pending_answers: list[dict]) -> str:
        """Build LLM context section for recently answered questions.

        Caps output at MAX_ANSWERED_IN_CONTEXT to prevent prompt blowup
        after extended LLM downtime.
        """
        if not pending_answers:
            return ""

        # Cap to first N items (by storage order)
        capped = pending_answers[: self.MAX_ANSWERED_IN_CONTEXT]
        overflow = len(pending_answers) - len(capped)

        lines = ["## Recently Answered Questions\n"]
        if overflow > 0:
            lines.append(
                f"(Showing {len(capped)} of {len(pending_answers)}; "
                f"{overflow} older answered question(s) omitted)\n"
            )
        for q in capped:
            qid = q.get("id", "?")
            question_text = q.get("question", "")
            answer_text = (q.get("answer") or "").strip() or "(체크만 됨, 답변 내용 없음)"
            lines.append(f"**{qid}**: {question_text}")
            lines.append(f'  - Answer: "{answer_text}"')
            if q.get("related_task_id"):
                lines.append(f"  - Related Task: {q['related_task_id']}")
            if q.get("type"):
                lines.append(f"  - Question Type: {q['type']}")
            lines.append("")

        lines.append(
            "이 답변을 분석하고 관련 Task 업데이트, 인사이트 저장 등 필요한 조치를 수행하라."
        )
        return "\n".join(lines)

    async def _cleanup_questions(
        self,
        *,
        skip_answered: bool = False,
        processed_ids: set[str] | None = None,
    ) -> None:
        """Remove stale questions (and answered questions unless skipped).

        Args:
            skip_answered: When True, preserve all answered questions
                (including old ones) because Phase 2 hasn't processed them.
                Only stale *unanswered* questions are removed in this mode.
            processed_ids: Forwarded to _cleanup_answered_questions to limit
                deletion to questions the LLM actually processed.
        """
        try:
            questions_data = self.storage_backend.load_questions()
            if self._cleanup_answered_questions(
                questions_data,
                skip_answered=skip_answered,
                processed_ids=processed_ids,
            ):
                ok, msg = self.storage_backend.save_questions(questions_data)
                if not ok:
                    logger.error(f"[Worker] Failed to save questions: {msg}")
        except Exception:
            logger.exception("[Worker] Question cleanup error")

    # =========================================================================
    # Phase 2: LLM-Powered Analysis
    # =========================================================================

    async def _run_llm_cycle(self, pending_answers: list[dict] | None = None) -> bool:
        """Run LLM-powered analysis cycle.

        Returns True if the cycle completed without exception, False otherwise.
        """
        logger.info("[Worker] Starting LLM-powered analysis")

        try:
            from nanobot.agent.tools.registry import ToolRegistry

            # Recreated each cycle (not cached across cycles).
            # Stored on self so tests can inspect registered tools after run_cycle().
            self.tools = ToolRegistry()
            self._register_worker_tools()

            # Build context (includes answered questions if any)
            messages = await self._build_context(pending_answers)

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
            return True

        except Exception:
            logger.exception("[Worker] LLM analysis error")
            return False

    async def _build_context(self, pending_answers: list[dict] | None = None) -> list[dict]:
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
                        "- Process answered questions: update related tasks, "
                        "save useful insights (save_insight tool)\n"
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
        answered_summary = self._build_answered_questions_summary(pending_answers or [])

        # 3. Combine into user message
        parts = [
            "## Current Dashboard State\n\n",
            f"{dashboard_summary}\n\n",
            f"{notifications_summary}\n\n",
        ]
        if answered_summary:
            parts.append(f"{answered_summary}\n\n")
        parts.append("위 상태를 분석하고 필요한 유지보수를 수행하라.")

        messages.append({"role": "user", "content": "".join(parts)})

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

        # Insight management (for saving insights from answered questions)
        from nanobot.agent.tools.dashboard.save_insight import SaveInsightTool

        self.tools.register(SaveInsightTool(self.workspace))
