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
    (bootstrap, consistency, archive, status reevaluation), so dashboard
    integrity is safe.
    Question generation is a "nice to have" — missing a cycle is harmless.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.dashboard.storage import StorageBackend

from loguru import logger

from nanobot.dashboard.utils import parse_datetime  # noqa: F401 — re-exported for back-compat


def _generate_id(prefix: str) -> str:
    """Generate unique ID: {prefix}_xxxxxxxx (same pattern as BaseDashboardTool)."""
    return f"{prefix}_{str(uuid4())[:8]}"


def _is_recurring_enabled(task: dict) -> bool:
    """Check if a task has recurring enabled (defensive against malformed data)."""
    recurring = task.get("recurring")
    if not isinstance(recurring, dict):
        return False
    return recurring.get("enabled") is True


class WorkerAgent:
    """
    Unified Dashboard Worker Agent.

    Phase 1 — Deterministic maintenance (always runs):
      - Bootstrap manually-added items (assign IDs, timestamps)
      - Enforce data consistency (progress/status/blocked field invariants)
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
        scheduler: Any | None = None,
    ):
        self.workspace = workspace
        self.storage_backend = storage_backend
        self.provider = provider
        self.model = model
        self.scheduler = scheduler  # ReconciliationScheduler (or None)
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

        # Phase 1: Deterministic maintenance (always runs)
        # - Bootstrap: all entities (tasks, questions, notifications)
        # - Consistency/archive/reevaluate: tasks only
        await self._run_maintenance()

        # Extract answered questions before cleanup (read-only snapshot).
        # None means extraction itself failed — treat as "answers may exist"
        # so cleanup preserves them rather than risking data loss.
        pending_answers = self._extract_answered_questions()
        extraction_failed = pending_answers is None

        # Phase 2: LLM-powered analysis (requires provider + model).
        # When unavailable (e.g. `nanobot dashboard worker` CLI), only Phase 1
        # runs — question generation and notification scheduling are skipped.
        # This is an intentional trade-off: see module docstring for rationale.
        phase2_ok = False
        if self.provider is not None and self.model is not None:
            phase2_ok = await self._run_llm_cycle(pending_answers or [])
        else:
            logger.debug("[Worker] LLM not configured; skipping Phase 2")

        # Cleanup: remove answered + stale questions (after Phase 2 processed them).
        # If Phase 2 was skipped/failed AND there were pending answers, preserve
        # answered questions so they can be retried in the next cycle.
        # Also preserve if extraction itself failed (answered questions may
        # exist in storage but we couldn't read them — don't blindly delete).
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

        skip_answered = extraction_failed or (bool(pending_answers) and not phase2_ok)
        await self._cleanup_questions(skip_answered=skip_answered, processed_ids=processed_ids)
        if skip_answered:
            reason = "extraction failed" if extraction_failed else "Phase 2 incomplete"
            logger.info("[Worker] Preserved answered question(s) for next cycle ({})", reason)

        if self.scheduler:
            try:
                await self.scheduler.trigger()
            except Exception:
                logger.exception("[Worker] Scheduler trigger error")

        logger.info("[Worker] Cycle complete.")

    # =========================================================================
    # Phase 1: Deterministic Maintenance
    # =========================================================================

    async def _run_maintenance(self) -> None:
        """Run deterministic maintenance tasks.

        Order:
        1. Bootstrap — assign IDs/timestamps to manually-added items (all entities)
        2. Consistency — enforce field invariants (tasks only)
        3. Archive — completed/cancelled → archived (tasks only)
        4. Reevaluate — active/someday status (tasks only)
        5. Recurring — reset completed habits, record misses (tasks only)

        Bootstrap runs independently per entity (separate load/save).
        Steps 2-5 share a single load_tasks() call.
        Question cleanup is handled separately by _cleanup_questions()
        after Phase 2, so the LLM can process answered questions first.
        """
        # Step 1: Bootstrap — assign IDs to manually-added items (all entities)
        self._bootstrap_new_items()

        # Steps 2-5: Task maintenance (single load/save)
        try:
            tasks_data = self.storage_backend.load_tasks()
            changed = self._enforce_consistency(tasks_data)
            changed |= self._archive_completed_tasks(tasks_data)
            changed |= self._reevaluate_active_status(tasks_data)
            changed |= self._check_recurring_tasks(tasks_data)
            if changed:
                ok, msg = self.storage_backend.save_tasks(tasks_data)
                if not ok:
                    logger.error(f"[Worker] Failed to save tasks: {msg}")
        except Exception:
            logger.exception("[Worker] Task maintenance error")

    def _bootstrap_new_items(self) -> None:
        """Assign IDs and timestamps to manually-added items (e.g. via Notion UI).

        Iterates over tasks, questions, and notifications independently.
        Items with empty ``id`` (mapper returns "" for blank NanobotID) get
        a fresh ID and required timestamps.

        For NotionStorageBackend, the Notion id_map is registered BEFORE
        save so that ``_save_entity_items()`` does ``update_page()`` on the
        existing Notion page instead of ``create_page()`` (which would
        create a duplicate). On save failure, id_map entries are rolled back.

        Each entity is error-isolated: one failure doesn't block the others.
        Insights are excluded (system-generated only, no manual creation).
        """
        now = datetime.now().isoformat()

        # (entity_type, loader, saver, id_prefix, extra_fields_fn)
        configs: list[tuple[str, Any, Any, str, Any]] = [
            (
                "tasks",
                self.storage_backend.load_tasks,
                self.storage_backend.save_tasks,
                "task",
                lambda item, ts: self._bootstrap_task_fields(item, ts),
            ),
            (
                "questions",
                self.storage_backend.load_questions,
                self.storage_backend.save_questions,
                "q",
                lambda item, ts: item.update({"created_at": ts}),
            ),
            (
                "notifications",
                self.storage_backend.load_notifications,
                self.storage_backend.save_notifications,
                "n",
                lambda item, ts: item.update({"created_at": ts, "created_by": "user"}),
            ),
        ]

        for entity_type, loader, saver, prefix, extra_fn in configs:
            try:
                data = loader()
                # Entity list key matches entity_type (tasks, questions, notifications)
                items = data.get(entity_type, [])
                bootstrapped = []

                for item in items:
                    if item.get("id") != "":
                        continue

                    new_id = _generate_id(prefix)
                    item["id"] = new_id
                    extra_fn(item, now)
                    bootstrapped.append(new_id)

                if bootstrapped:
                    # Register id mappings BEFORE save so that Notion's
                    # _save_entity_items() sees the mapping and calls
                    # update_page() instead of create_page() (prevents
                    # duplicate pages). No-op for JsonStorageBackend.
                    # NOTE: runs outside @with_dashboard_lock (tool-level lock).
                    # Protected by _processing_lock when called from HeartbeatService.
                    # CLI `nanobot dashboard worker` runs without any lock
                    # (single-user, no event loop contention).
                    id_map_registered: list[tuple[str, str]] = []
                    save_ok = False
                    try:
                        for item in items:
                            notion_page_id = item.get("_notion_page_id")
                            if notion_page_id and item["id"] in bootstrapped:
                                self.storage_backend.register_id_mapping(
                                    entity_type, item["id"], notion_page_id
                                )
                                id_map_registered.append((item["id"], notion_page_id))

                        ok, msg = saver(data)
                        save_ok = ok
                        if not ok:
                            logger.error(f"[Worker] Bootstrap save failed for {entity_type}: {msg}")
                    except Exception:
                        logger.exception(f"[Worker] Bootstrap save exception for {entity_type}")
                    finally:
                        if not save_ok and id_map_registered:
                            # Rollback on ANY failure (register loop, save
                            # return False, save exception). Bootstrap IDs
                            # were not persisted, so stale id_map entries
                            # would route to update_page for a non-existent
                            # ID. Next successful load() also rebuilds
                            # id_map from scratch, but we clean up eagerly.
                            for nid, _ in id_map_registered:
                                self.storage_backend.unregister_id_mapping(entity_type, nid)

                    if save_ok:
                        logger.info(
                            f"[Worker] Bootstrapped {len(bootstrapped)} {entity_type}: "
                            f"{bootstrapped}"
                        )

            except Exception:
                logger.exception(f"[Worker] Bootstrap error for {entity_type}")

    @staticmethod
    def _bootstrap_task_fields(item: dict, now: str) -> None:
        """Assign bootstrap fields specific to tasks."""
        item["created_at"] = now
        item["updated_at"] = now
        item.setdefault("progress", {})["last_update"] = now

    def _enforce_consistency(self, tasks_data: dict) -> bool:
        """Enforce field invariants on tasks (deterministic, no LLM).

        Rules (applied in order per task):
          R6: active/someday + completed_at → clear completed_at
          R1: active/someday + progress=100% → completed + completed_at=now
          R2a: completed + progress<100% → progress=100%
          R2b: cancelled + progress=100% → warning only
          R3: completed/archived + no completed_at → backfill completed_at
          R4: blocked=true + no blocker_note → warning only
          R5: blocked=false + blocker_note → clear blocker_note

        Returns True if any task was modified.
        """
        tasks = tasks_data.get("tasks", [])
        if not tasks:
            return False

        now = datetime.now().isoformat()
        changed = False

        for task in tasks:
            try:
                task_id = task.get("id", "?")
                status = task.get("status", "active")
                progress_dict = task.get("progress", {})
                progress = progress_dict.get("percentage", 0)
                completed_at = task.get("completed_at")
                # blocked/blocker_note live inside progress (schema.py:27-28)
                blocked = progress_dict.get("blocked", False)
                blocker_note = progress_dict.get("blocker_note")

                # R6: active/someday should not have completed_at
                if status in ("active", "someday") and completed_at is not None:
                    task["completed_at"] = None
                    completed_at = None
                    changed = True
                    logger.info(f"[Worker] R6: {task_id} — cleared stale completed_at")

                # R1: progress=100% on active/someday → auto-complete
                if status in ("active", "someday") and progress >= 100:
                    task["status"] = "completed"
                    task["completed_at"] = now
                    status = "completed"  # Update local var for subsequent rules
                    completed_at = now  # Prevent R3 from redundant backfill
                    changed = True
                    logger.info(f"[Worker] R1: {task_id} — progress 100% → completed")

                # R2a: completed but progress < 100% → fix progress
                if status == "completed" and progress < 100:
                    task.setdefault("progress", {})["percentage"] = 100
                    task.setdefault("progress", {})["last_update"] = now
                    changed = True
                    logger.info(f"[Worker] R2a: {task_id} — completed, progress → 100%")

                # R2b: cancelled with 100% → warning only (user intent unclear)
                if status == "cancelled" and progress >= 100:
                    logger.warning(
                        f"[Worker] R2b: {task_id} — cancelled with progress=100%, preserved as-is"
                    )

                # R3: completed/archived without completed_at → backfill
                if status in ("completed", "archived") and completed_at is None:
                    task["completed_at"] = now
                    changed = True
                    logger.info(f"[Worker] R3: {task_id} — backfilled completed_at")

                # R4/R5: blocked field consistency (only for active/someday)
                if status in ("active", "someday"):
                    has_note = bool(blocker_note and str(blocker_note).strip())

                    # R4: blocked=true but no note → warning
                    if blocked and not has_note:
                        logger.warning(f"[Worker] R4: {task_id} — blocked=true but no blocker_note")

                    # R5: not blocked but has note → clear note
                    if not blocked and has_note:
                        progress_dict["blocker_note"] = None
                        changed = True
                        logger.info(f"[Worker] R5: {task_id} — cleared orphan blocker_note")

            except Exception:
                # Guard against task not being a dict (e.g. corrupted data)
                try:
                    tid = task.get("id", "?") if isinstance(task, dict) else "???"
                except Exception:
                    tid = "???"
                logger.exception(f"[Worker] Consistency check error for task {tid}")

        return changed

    def _archive_completed_tasks(self, tasks_data: dict) -> bool:
        """Archive completed or cancelled tasks by setting status to 'archived'.

        Recurring tasks that are completed are excluded — Worker resets them.
        Cancelled recurring tasks ARE archived (cancel = stop recurring).
        """
        tasks = tasks_data.get("tasks", [])
        targets = [
            t
            for t in tasks
            if isinstance(t, dict)
            and t.get("status") in ("completed", "cancelled")
            and not (t.get("status") == "completed" and _is_recurring_enabled(t))
        ]

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
            if not isinstance(task, dict):
                continue
            if task.get("status") in ("completed", "cancelled", "archived"):
                continue

            # Recurring tasks always stay active (never demoted to someday)
            if _is_recurring_enabled(task):
                if task.get("status") != "active":
                    task["status"] = "active"
                    changed = True
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

    # =========================================================================
    # Recurring Tasks (Daily Habits)
    # =========================================================================

    def _check_recurring_tasks(self, tasks_data: dict) -> bool:
        """Process all recurring-enabled tasks. Entry point for recurring logic.

        For each recurring task, checks if it's a valid day and processes
        completion or miss. Each task is exception-isolated.
        Skips archived/cancelled tasks to prevent reviving them.
        """
        tasks = tasks_data.get("tasks", [])
        today = date.today()
        changed = False

        for task in tasks:
            try:
                if not _is_recurring_enabled(task):
                    continue
                # Archived/cancelled tasks must not be processed
                if task.get("status") in ("archived", "cancelled"):
                    continue
                changed |= self._process_one_recurring(task, today)
            except Exception:
                tid = task.get("id", "?") if isinstance(task, dict) else "???"
                logger.exception(f"[Worker] Recurring error for task {tid}")

        return changed

    def _process_one_recurring(self, task: dict, today: date) -> bool:
        """Process a single recurring task for today.

        Returns True if the task was modified.
        """
        recurring = task["recurring"]
        days = recurring.get("days_of_week", list(range(7)))
        last_completed = recurring.get("last_completed_date")
        last_miss = recurring.get("last_miss_date")

        # If completed today, handle the completion
        if task.get("status") == "completed" or (
            task.get("progress", {}).get("percentage", 0) >= 100
        ):
            return self._handle_recurring_completion(task, recurring, today, days)

        # Brand-new task (never completed or missed) → skip miss detection
        if not last_completed and not last_miss:
            return False

        # Check if we need to record a miss for a previous valid day
        if last_completed:
            last_completed_date = date.fromisoformat(last_completed)
        else:
            last_completed_date = None

        prev_day = self._find_prev_valid_day(today, days)
        if prev_day is None:
            return False

        # Already handled (completed or missed) for the previous valid day
        if last_completed_date and last_completed_date >= prev_day:
            return False
        if last_miss:
            last_miss_date = date.fromisoformat(last_miss)
            if last_miss_date >= prev_day:
                return False

        # Previous valid day was not completed or missed → record miss
        return self._handle_recurring_miss(task, recurring, today, days, prev_day)

    def _handle_recurring_completion(
        self,
        task: dict,
        recurring: dict,
        today: date,
        days: list[int],
    ) -> bool:
        """Handle a completed recurring task: update stats and reset."""
        last_completed = recurring.get("last_completed_date")
        today_str = today.isoformat()

        # Same-day duplicate guard
        if last_completed == today_str:
            self._reset_recurring_task(task)
            return True

        # Update stats
        recurring["total_completed"] = recurring.get("total_completed", 0) + 1

        # Streak logic
        if last_completed:
            prev_date = date.fromisoformat(last_completed)
            if self._is_consecutive_day(prev_date, today, days):
                recurring["streak_current"] = recurring.get("streak_current", 0) + 1
            else:
                recurring["streak_current"] = 1
        else:
            recurring["streak_current"] = 1

        recurring["streak_best"] = max(
            recurring.get("streak_best", 0),
            recurring["streak_current"],
        )
        recurring["last_completed_date"] = today_str

        self._reset_recurring_task(task)
        logger.info(
            f"[Worker] Recurring completed: {task.get('id', '?')} "
            f"(streak: {recurring['streak_current']})"
        )
        return True

    def _handle_recurring_miss(
        self,
        task: dict,
        recurring: dict,
        today: date,
        days: list[int],
        missed_day: date,
    ) -> bool:
        """Handle a missed recurring task: update stats and reset streak."""
        recurring["total_missed"] = recurring.get("total_missed", 0) + 1
        recurring["streak_current"] = 0
        recurring["last_miss_date"] = missed_day.isoformat()

        logger.info(
            f"[Worker] Recurring missed: {task.get('id', '?')} (missed: {missed_day.isoformat()})"
        )
        return True

    @staticmethod
    def _reset_recurring_task(task: dict) -> None:
        """Reset a recurring task for the next cycle."""
        task["status"] = "active"
        task["completed_at"] = None
        now = datetime.now().isoformat()
        task["updated_at"] = now
        progress = task.get("progress", {})
        progress["percentage"] = 0
        progress["last_update"] = now
        task["progress"] = progress

    @staticmethod
    def _find_prev_valid_day(today: date, days: list[int]) -> date | None:
        """Find the most recent valid day before today (within 7 days)."""
        for i in range(1, 8):
            candidate = today - timedelta(days=i)
            if candidate.weekday() in days:
                return candidate
        return None

    @staticmethod
    def _is_consecutive_day(prev: date, current: date, days: list[int]) -> bool:
        """Check if current is the next valid day after prev in the schedule.

        Handles non-adjacent schedules (e.g., Mon/Wed/Fri) where consecutive
        valid days may be more than 1 calendar day apart.
        """
        # Walk forward from prev to find the next valid day
        for i in range(1, 8):
            candidate = prev + timedelta(days=i)
            if candidate.weekday() in days:
                return candidate == current
        return False

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

    def _extract_answered_questions(self) -> list[dict] | None:
        """Extract answered questions from storage (read-only).

        Detects both ``answered=True`` and non-empty ``answer`` field
        (covers case where user fills Answer but forgets the checkbox).

        Returns None on failure so callers can distinguish "no answered
        questions" (empty list) from "extraction failed" (None) and
        preserve answered questions in storage accordingly.
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
            return None

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
        """Build summary of pending and recently delivered notifications.

        Includes two sections:
        - Pending notifications (scheduled, not yet delivered)
        - Recently Delivered (last 48h) with follow-up instructions
        """
        try:
            data = self.storage_backend.load_notifications()
            notifications = data.get("notifications", [])

            if not notifications:
                return "## Scheduled Notifications\n\nNo notifications scheduled."

            pending = [n for n in notifications if n.get("status") == "pending"]

            # Recently delivered (last 48h)
            now = datetime.now()
            cutoff = now - timedelta(hours=48)
            delivered_recent = []
            for n in notifications:
                if n.get("status") != "delivered":
                    continue
                delivered_at = n.get("delivered_at", "")
                try:
                    dt = parse_datetime(delivered_at)
                    if dt >= cutoff:
                        delivered_recent.append(n)
                except (ValueError, TypeError):
                    # Skip: including unparseable entries would cause infinite
                    # repetition since they can never age past the 48h cutoff.
                    logger.error(
                        f"[Worker] Skipping notification {n.get('id', '?')}: "
                        f"invalid delivered_at={delivered_at!r} — fix data to restore tracking"
                    )

            if not pending and not delivered_recent:
                return "## Scheduled Notifications\n\nNo pending notifications."

            lines = ["## Scheduled Notifications\n"]

            # Pending section
            if pending:
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
            else:
                lines.append("No pending notifications.\n")

            # Recently delivered section
            if delivered_recent:
                lines.append("\n### Recently Delivered Notifications (last 48h)\n")
                for notif in delivered_recent:
                    delivered_at = notif.get("delivered_at", "")
                    try:
                        dt = parse_datetime(delivered_at)
                        time_str = dt.strftime("%Y-%m-%d %H:%M")
                    except (ValueError, TypeError):
                        time_str = delivered_at

                    lines.append(
                        f"- **{notif.get('id', '?')}** "
                        f"({notif.get('type', '?')}, {notif.get('priority', '?')}): "
                        f"{notif.get('message', '')} [Delivered: {time_str}]"
                    )
                    if notif.get("related_task_id"):
                        lines.append(f"  Related Task: {notif['related_task_id']}")

                lines.append(
                    "\n위 알림은 이미 전달되었다. "
                    "WORKER.md의 '전달된 알림 후속 조치' 지침에 따라 처리하라."
                )

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

        self.tools.register(CreateQuestionTool(self.workspace, self.storage_backend))
        self.tools.register(UpdateQuestionTool(self.workspace, self.storage_backend))
        self.tools.register(RemoveQuestionTool(self.workspace, self.storage_backend))

        # Notification management (ledger-only — GCal/delivery via Reconciler)
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

        self.tools.register(ScheduleNotificationTool(self.workspace, self.storage_backend))
        self.tools.register(UpdateNotificationTool(self.workspace, self.storage_backend))
        self.tools.register(CancelNotificationTool(self.workspace, self.storage_backend))
        self.tools.register(ListNotificationsTool(self.workspace, self.storage_backend))

        # Task management
        from nanobot.agent.tools.dashboard.archive_task import ArchiveTaskTool
        from nanobot.agent.tools.dashboard.update_task import UpdateTaskTool

        self.tools.register(UpdateTaskTool(self.workspace, self.storage_backend))
        self.tools.register(ArchiveTaskTool(self.workspace, self.storage_backend))

        # Insight management (for saving insights from answered questions)
        from nanobot.agent.tools.dashboard.save_insight import SaveInsightTool

        self.tools.register(SaveInsightTool(self.workspace, self.storage_backend))
