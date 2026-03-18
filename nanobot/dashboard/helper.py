"""Dashboard helper functions for Context Builder."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from nanobot.dashboard.storage import StorageBackend


def _format_notification_line(n: dict) -> str:
    """Format a single notification as a markdown list item."""
    scheduled_at = n.get("scheduled_at", "")
    try:
        dt = datetime.fromisoformat(scheduled_at)
        time_str = dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        time_str = scheduled_at
    priority = n.get("priority", "medium")
    return (
        f"  - {n.get('id', '?')} ({n.get('type', '?')}, {priority}): "
        f"{n.get('message', '')} [{time_str}]"
    )


def get_dashboard_summary(
    dashboard_path: Path,
    storage_backend: StorageBackend | None = None,
    on_error: Callable[[str], None] | None = None,
) -> str:
    """
    Generate COMPLETE Dashboard state for Agent context.

    Includes ALL information with NO limits:
    - All active tasks (with full details)
    - All unanswered questions (with metadata)
    - All pending notifications (grouped by task)

    This is the single source of truth for the agent.
    Session history is NOT included in context.

    Args:
        dashboard_path: Path to dashboard directory.
        storage_backend: Optional StorageBackend instance.
            If provided, loads data through the backend (supports Notion).
            Otherwise falls back to direct JSON file reading.
        on_error: Optional callback invoked with a message string when
            a section fails to load. Called at most once per failed section
            (tasks, questions, notifications). Note: only fires for
            StorageBackend errors; JSON backend's load_json_file swallows
            parse errors internally (returns empty dict).

    Returns:
        Complete formatted dashboard state.
    """
    if storage_backend is None and not dashboard_path.exists():
        return ""

    parts = []

    # Load all data upfront — each section wrapped individually so one
    # failure doesn't break the others. StorageBackend errors are logged
    # and reported via on_error; JSON backend's load_json_file swallows
    # parse errors internally (returns empty dict).
    if storage_backend is not None:

        def _safe_load(loader: Callable, error_msg: str, default: dict) -> tuple[dict, str | None]:
            try:
                return loader(), None
            except Exception:
                logger.exception("[DashboardHelper] {}", error_msg)
                return default, error_msg

        # Short-lived pool: thread creation cost (~µs) is negligible vs Notion I/O (~s).
        # A persistent pool would add lifecycle complexity for no measurable gain.
        with ThreadPoolExecutor(max_workers=3) as pool:
            ft = pool.submit(
                _safe_load,
                storage_backend.load_tasks,
                "Failed to load tasks for dashboard summary",
                {},
            )
            fq = pool.submit(
                _safe_load,
                storage_backend.load_questions,
                "Failed to load questions for dashboard summary",
                {},
            )
            fn = pool.submit(
                _safe_load,
                storage_backend.load_notifications,
                "Failed to load pending notifications for dashboard summary",
                {},
            )

        # _safe_load catches Exception internally, so .result() only re-raises
        # BaseException (e.g. KeyboardInterrupt) — which should propagate anyway.
        tasks_data, t_err = ft.result()
        questions_data, q_err = fq.result()
        notif_data, n_err = fn.result()

        for err in (t_err, q_err, n_err):
            if err and on_error:
                on_error(err)
    else:
        from nanobot.dashboard.storage import load_json_file

        tasks_data = load_json_file(dashboard_path / "tasks.json")
        questions_data = load_json_file(dashboard_path / "questions.json")
        notif_data = load_json_file(dashboard_path / "notifications.json")

    # Format tasks
    active_tasks = [task for task in tasks_data.get("tasks", []) if task.get("status") == "active"]

    if active_tasks:
        task_lines = ["## Active Tasks\n"]
        for task in active_tasks:  # NO LIMIT - show all
            task_id = task.get("id", "?")
            title = task.get("title", "Untitled")
            deadline = task.get("deadline_text") or task.get("deadline", "No deadline")
            progress_data = task.get("progress", {})
            progress = progress_data.get("percentage", 0)
            priority = task.get("priority", "medium")
            context = task.get("context", "")
            blocked = progress_data.get("blocked", False)
            blocker_note = progress_data.get("blocker_note", "")
            tags = task.get("tags", [])

            task_lines.append(f"**{task_id}**: {title}")
            task_lines.append(f"  - Progress: {progress}%")
            task_lines.append(f"  - Deadline: {deadline}")
            task_lines.append(f"  - Priority: {priority}")
            if context:
                task_lines.append(f"  - Context: {context}")
            if blocked:
                task_lines.append(f"  - ⚠️ Blocked: {blocker_note}")
            if tags:
                task_lines.append(f"  - Tags: {', '.join(tags)}")
            recurring = task.get("recurring")
            if recurring and recurring.get("enabled"):
                freq = recurring.get("frequency", "daily")
                task_lines.append(f"  - Recurring: {freq}")
            task_lines.append("")  # Empty line between tasks

        parts.append("\n".join(task_lines))

    # Format questions
    # Treat as answered if flag is set OR answer text is present
    # (matches Worker's detection logic in _extract_answered_questions)
    unanswered = [
        q
        for q in questions_data.get("questions", [])
        if not q.get("answered", False) and not (q.get("answer") or "").strip()
    ]

    if unanswered:
        question_lines = ["## Question Queue (Unanswered)\n"]
        for q in unanswered:  # NO LIMIT - show all
            q_id = q.get("id", "?")
            question = q.get("question", "")
            priority = q.get("priority", "medium")
            q_type = q.get("type", "info_gather")
            related_task = q.get("related_task_id", "")
            asked_count = q.get("asked_count", 0)
            last_asked = q.get("last_asked_at")
            q_context = q.get("context", "")

            question_lines.append(f"**{q_id}**: {question}")
            question_lines.append(f"  - Priority: {priority}")
            question_lines.append(f"  - Type: {q_type}")
            if related_task:
                question_lines.append(f"  - Related Task: {related_task}")
            question_lines.append(f"  - Asked: {asked_count} times")
            if last_asked:
                question_lines.append(f"  - Last Asked: {last_asked[:16]}")
            if q_context:
                question_lines.append(f"  - Context: {q_context}")
            question_lines.append("")  # Empty line between questions

        parts.append("\n".join(question_lines))

    # Format pending notifications (grouped by task)
    pending = [n for n in notif_data.get("notifications", []) if n.get("status") == "pending"]

    if pending:
        # Build task_id -> title map from already-loaded tasks_data
        task_titles: dict[str, str] = {}
        for t in tasks_data.get("tasks", []):
            tid = t.get("id", "")
            if tid:
                task_titles[tid] = t.get("title", "Untitled")

        # Group by related_task_id
        grouped: dict[str | None, list[dict]] = {}
        for n in pending:
            key = n.get("related_task_id") or None
            grouped.setdefault(key, []).append(n)

        notif_lines = ["## Pending Notifications\n"]
        # Task-linked groups first
        for task_id, notifs in grouped.items():
            if task_id is None:
                continue
            title = task_titles.get(task_id, "")
            count = len(notifs)
            if title:
                header = f"**{task_id}** ({title}) — {count} pending:"
            else:
                header = f"**{task_id}** — {count} pending:"
            notif_lines.append(header)
            for n in notifs:
                notif_lines.append(_format_notification_line(n))
            notif_lines.append("")

        # Unlinked group
        unlinked = grouped.get(None, [])
        if unlinked:
            notif_lines.append("**기타** (Task 미연결):")
            for n in unlinked:
                notif_lines.append(_format_notification_line(n))
            notif_lines.append("")

        parts.append("\n".join(notif_lines))

    if not parts:
        return "No active tasks or questions."

    return "\n\n".join(parts)
