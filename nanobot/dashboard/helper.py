"""Dashboard helper functions for Context Builder."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.dashboard.storage import StorageBackend


def get_dashboard_summary(
    dashboard_path: Path,
    storage_backend: "StorageBackend | None" = None,
) -> str:
    """
    Generate COMPLETE Dashboard state for Agent context.

    Includes ALL information with NO limits:
    - All active tasks (with full details)
    - All unanswered questions (with metadata)

    This is the single source of truth for the agent.
    Session history is NOT included in context.

    Args:
        dashboard_path: Path to dashboard directory.
        storage_backend: Optional StorageBackend instance.
            If provided, loads data through the backend (supports Notion).
            Otherwise falls back to direct JSON file reading.

    Returns:
        Complete formatted dashboard state.
    """
    if storage_backend is None and not dashboard_path.exists():
        return ""

    parts = []

    # Load data through backend or direct file access
    # Wrap in try/except so one section failing doesn't break the whole summary
    if storage_backend is not None:
        try:
            tasks_data = storage_backend.load_tasks()
        except Exception:
            tasks_data = {}
        try:
            questions_data = storage_backend.load_questions()
        except Exception:
            questions_data = {}
    else:
        from nanobot.dashboard.storage import load_json_file
        tasks_data = load_json_file(dashboard_path / "tasks.json")
        questions_data = load_json_file(dashboard_path / "questions.json")

    # Format tasks
    active_tasks = [
        task for task in tasks_data.get("tasks", [])
        if task.get("status") == "active"
    ]

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
            task_lines.append("")  # Empty line between tasks

        parts.append("\n".join(task_lines))

    # Format questions
    # Treat as answered if flag is set OR answer text is present
    # (matches Worker's detection logic in _extract_answered_questions)
    unanswered = [
        q for q in questions_data.get("questions", [])
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

    if not parts:
        return "No active tasks or questions."

    return "\n\n".join(parts)
