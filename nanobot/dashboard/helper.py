"""Dashboard helper functions for Context Builder."""

import json
from pathlib import Path


def get_dashboard_summary(dashboard_path: Path) -> str:
    """
    Generate COMPLETE Dashboard state for Agent context.

    Includes ALL information with NO limits:
    - All active tasks (with full details)
    - All unanswered questions (with metadata)

    This is the single source of truth for the agent.
    Session history is NOT included in context.

    Args:
        dashboard_path: Path to dashboard directory.

    Returns:
        Complete formatted dashboard state.
    """
    if not dashboard_path.exists():
        return ""

    parts = []

    # Load tasks
    tasks_file = dashboard_path / "tasks.json"
    if tasks_file.exists():
        try:
            with open(tasks_file, "r", encoding="utf-8") as f:
                tasks_data = json.load(f)

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
        except Exception:
            pass  # Silently ignore errors

    # Load questions
    questions_file = dashboard_path / "questions.json"
    if questions_file.exists():
        try:
            with open(questions_file, "r", encoding="utf-8") as f:
                questions_data = json.load(f)

            unanswered = [
                q for q in questions_data.get("questions", [])
                if not q.get("answered", False)
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
        except Exception:
            pass  # Silently ignore errors

    # Header with file paths (CRITICAL: Agent needs to know where to write!)
    header = """## Dashboard State

**To update dashboard, use these paths with write_file:**
- Tasks: `dashboard/tasks.json`
- Questions: `dashboard/questions.json`
- Notifications: `dashboard/notifications.json`
- History: `dashboard/knowledge/history.json`
- Insights: `dashboard/knowledge/insights.json`

**DO NOT modify**: DASHBOARD.md, TOOLS.md, AGENTS.md (read-only instruction files)

---
"""

    if not parts:
        return header + "\nNo active tasks or questions."

    return header + "\n\n".join(parts)
