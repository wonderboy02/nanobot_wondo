"""Worker agent for dashboard maintenance and progress tracking."""

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.dashboard.manager import DashboardManager


def parse_datetime(dt_str: str) -> datetime:
    """Parse ISO datetime string."""
    return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))


def generate_id() -> str:
    """Generate unique ID."""
    return str(uuid.uuid4())[:8]


class WorkerAgent:
    """
    Dashboard management worker agent.

    Runs periodically to:
    - Check task progress
    - Generate questions
    - Move completed tasks to history
    - Re-evaluate active status
    - Process notifications
    """

    # Configuration
    PROGRESS_GAP_CRITICAL = 20  # % gap to trigger urgent question
    PROGRESS_GAP_WARNING = 10   # % gap to trigger check

    UPDATE_STALE_HOURS = 48     # Hours without update → check
    UPDATE_VERY_STALE_HOURS = 96

    DEADLINE_URGENT_DAYS = 1
    DEADLINE_SOON_DAYS = 3
    DEADLINE_APPROACHING_DAYS = 7

    COOLDOWN_HOURS = {
        "start_check": 24,
        "blocker_check": 12,
        "progress_check": 24,
        "status_check": 72,
        "deadline_check": 12,
        "completion_check": 6,
        "routine_check": 168,
    }

    def __init__(self, dashboard_path: Path):
        self.dashboard_path = Path(dashboard_path)
        self.manager = DashboardManager(dashboard_path)

    async def run_cycle(self) -> None:
        """Run a full worker cycle."""
        logger.info("[Worker] Starting cycle...")

        # Load dashboard
        dashboard = self.manager.load()

        # Check all tasks
        await self.check_all_tasks(dashboard)

        # Move completed tasks to history
        self.move_completed_to_history(dashboard)

        # Re-evaluate active status
        self.reevaluate_active_status(dashboard)

        # Clean up question queue
        self.cleanup_question_queue(dashboard)

        # Save dashboard
        self.manager.save(dashboard)

        logger.info("[Worker] Cycle complete.")

    async def check_all_tasks(self, dashboard: dict[str, Any]) -> None:
        """Check all active tasks for progress."""
        active_tasks = [t for t in dashboard['tasks'] if t['status'] == 'active']

        for task in active_tasks:
            await self.check_task_progress(task, dashboard)

    async def check_task_progress(self, task: dict[str, Any], dashboard: dict[str, Any]) -> None:
        """Check individual task progress and generate questions if needed."""
        now = datetime.now()

        # Last update check (모든 task에 적용, deadline 불필요)
        last_update = parse_datetime(task['progress']['last_update'])
        hours_since_update = (now - last_update).total_seconds() / 3600

        # Case 4: Stale (no update for 48h) - deadline과 무관하게 체크
        if hours_since_update > self.UPDATE_STALE_HOURS:
            self.add_question(
                dashboard,
                question=f"'{task['title']}' 요즘 어떻게 되고 있어?",
                task_id=task['id'],
                priority="low",
                type="status_check",
                cooldown_hours=self.COOLDOWN_HOURS["status_check"]
            )
            return

        # Case 7: Very stale (96h+) - deadline과 무관하게 체크
        if hours_since_update > self.UPDATE_VERY_STALE_HOURS:
            self.add_question(
                dashboard,
                question=f"'{task['title']}' 잘 진행되고 있어?",
                task_id=task['id'],
                priority="low",
                type="routine_check",
                cooldown_hours=self.COOLDOWN_HOURS["routine_check"]
            )
            return

        # Deadline-based checks (deadline 필요)
        deadline = parse_datetime(task['deadline']) if task.get('deadline') else None

        if not deadline:
            # No deadline - skip progress-based checks
            return

        # Time-based calculation
        created = parse_datetime(task['created_at'])
        time_elapsed = now - created
        time_total = deadline - created

        if time_total.total_seconds() <= 0:
            # Already past deadline
            return

        time_progress_ratio = time_elapsed / time_total
        expected_progress = time_progress_ratio * 100

        # Actual progress
        actual_progress = task['progress']['percentage']
        progress_gap = expected_progress - actual_progress

        # Deadline proximity
        time_until_deadline = deadline - now
        days_left = time_until_deadline.days

        # Decision logic (deadline 기반 checks)

        # Case 1: Not started (0% & time passed)
        if actual_progress == 0 and time_progress_ratio > 0.2:
            self.add_question(
                dashboard,
                question=f"'{task['title']}' 시작했어?",
                task_id=task['id'],
                priority=self._calculate_priority(progress_gap, days_left),
                type="start_check",
                cooldown_hours=self.COOLDOWN_HOURS["start_check"]
            )
            return

        # Case 2: Very behind (20%+ gap)
        if progress_gap > self.PROGRESS_GAP_CRITICAL:
            if days_left <= self.DEADLINE_SOON_DAYS:
                self.add_question(
                    dashboard,
                    question=f"'{task['title']}' {days_left}일 남았는데 {actual_progress:.0f}%밖에 안 됐어. 막히는 부분 있어?",
                    task_id=task['id'],
                    priority="high",
                    type="blocker_check",
                    cooldown_hours=self.COOLDOWN_HOURS["blocker_check"]
                )
            else:
                self.add_question(
                    dashboard,
                    question=f"'{task['title']}' 진행이 좀 느린데 괜찮아?",
                    task_id=task['id'],
                    priority="medium",
                    type="progress_check",
                    cooldown_hours=self.COOLDOWN_HOURS["progress_check"]
                )
            return

        # Case 3: Somewhat behind (10-20% gap)
        if progress_gap > self.PROGRESS_GAP_WARNING:
            if days_left <= self.DEADLINE_SOON_DAYS:
                self.add_question(
                    dashboard,
                    question=f"'{task['title']}' 어디까지 했어?",
                    task_id=task['id'],
                    priority="medium",
                    type="progress_check",
                    cooldown_hours=self.COOLDOWN_HOURS["progress_check"]
                )
            return

        # Case 5: Deadline imminent (2 days) & incomplete
        if days_left <= self.DEADLINE_SOON_DAYS and actual_progress < 90:
            self.add_question(
                dashboard,
                question=f"'{task['title']}' {days_left}일 남았는데 마무리 가능해?",
                task_id=task['id'],
                priority="high",
                type="deadline_check",
                cooldown_hours=self.COOLDOWN_HOURS["deadline_check"]
            )
            return

        # Case 6: Almost done (80%+) but not complete
        if actual_progress >= 80 and actual_progress < 100:
            if days_left <= self.DEADLINE_URGENT_DAYS:
                self.add_question(
                    dashboard,
                    question=f"'{task['title']}' 거의 다 된 것 같은데 완료했어?",
                    task_id=task['id'],
                    priority="medium",
                    type="completion_check",
                    cooldown_hours=self.COOLDOWN_HOURS["completion_check"]
                )
            return

    def add_question(
        self,
        dashboard: dict[str, Any],
        question: str,
        task_id: str,
        priority: str,
        type: str,
        cooldown_hours: int
    ) -> None:
        """Add question to queue (with duplicate prevention)."""
        questions = dashboard['questions']

        # Check for existing question
        existing = None
        for q in questions:
            if (q.get('related_task_id') == task_id and
                q.get('type') == type and
                not q.get('answered', False)):
                existing = q
                break

        if existing:
            # Check cooldown
            if existing.get('last_asked_at'):
                last_asked = parse_datetime(existing['last_asked_at'])
                cooldown_until = last_asked + timedelta(hours=existing.get('cooldown_hours', 24))

                if datetime.now() < cooldown_until:
                    logger.debug(f"[Worker] Question skipped (cooldown): {question}")
                    return
                else:
                    # Update priority if higher
                    if self._is_higher_priority(priority, existing.get('priority', 'low')):
                        existing['priority'] = priority
                    existing['asked_count'] = existing.get('asked_count', 0) + 1
                    logger.debug(f"[Worker] Question priority updated: {question}")
                    return
            else:
                # Not asked yet, just update priority
                if self._is_higher_priority(priority, existing.get('priority', 'low')):
                    existing['priority'] = priority
                return

        # Add new question
        new_question = {
            "id": f"q_{generate_id()}",
            "question": question,
            "context": f"Task progress check for {task_id}",
            "priority": priority,
            "type": type,
            "related_task_id": task_id,
            "asked_count": 0,
            "last_asked_at": None,
            "created_at": datetime.now().isoformat(),
            "cooldown_hours": cooldown_hours,
            "answered": False,
            "answer": None,
            "answered_at": None
        }

        questions.append(new_question)
        logger.info(f"[Worker] Question added: {question}")

    def _calculate_priority(self, progress_gap: float, days_left: int) -> str:
        """Calculate priority based on gap and deadline."""
        if days_left <= self.DEADLINE_URGENT_DAYS:
            return "high"
        elif days_left <= self.DEADLINE_SOON_DAYS and progress_gap > 20:
            return "high"
        elif days_left <= self.DEADLINE_APPROACHING_DAYS and progress_gap > 30:
            return "medium"
        else:
            return "low"

    def _is_higher_priority(self, new_priority: str, old_priority: str) -> bool:
        """Check if new priority is higher."""
        priority_order = {"high": 3, "medium": 2, "low": 1}
        return priority_order.get(new_priority, 0) > priority_order.get(old_priority, 0)

    def move_completed_to_history(self, dashboard: dict[str, Any]) -> None:
        """Move completed tasks to history."""
        tasks = dashboard['tasks']
        history = dashboard['knowledge']['history']

        completed_tasks = [t for t in tasks if t.get('status') == 'completed']

        for task in completed_tasks:
            # Add to history
            history_entry = {
                "id": task['id'],
                "title": task['title'],
                "completed_at": task.get('completed_at', datetime.now().isoformat()),
                "duration_days": self._calculate_duration(task),
                "progress_note": task.get('progress', {}).get('note', ''),
                "links": task.get('links', {}),
                "moved_at": datetime.now().isoformat()
            }

            history.setdefault('completed_tasks', []).append(history_entry)

            # Remove from tasks
            tasks.remove(task)

            logger.info(f"[Worker] Task moved to history: {task['title']}")

    def _calculate_duration(self, task: dict[str, Any]) -> int:
        """Calculate task duration in days."""
        created = parse_datetime(task['created_at'])
        completed = parse_datetime(task.get('completed_at', datetime.now().isoformat()))
        return (completed - created).days

    def reevaluate_active_status(self, dashboard: dict[str, Any]) -> None:
        """Re-evaluate active/someday status for all tasks."""
        now = datetime.now()
        tasks = dashboard['tasks']

        for task in tasks:
            if task.get('status') in ['completed', 'cancelled']:
                continue

            old_status = task.get('status', 'someday')
            new_status = self._determine_status(task, now)

            if old_status != new_status:
                task['status'] = new_status
                logger.info(f"[Worker] Task '{task['title']}' status: {old_status} → {new_status}")

    def _determine_status(self, task: dict[str, Any], now: datetime) -> str:
        """Determine if task should be active or someday."""
        # Has deadline and it's close → active
        if task.get('deadline'):
            deadline = parse_datetime(task['deadline'])
            days_until = (deadline - now).days

            if days_until <= self.DEADLINE_APPROACHING_DAYS:
                return 'active'

        # High priority → active
        if task.get('priority') == 'high':
            return 'active'

        # Has progress → active
        if task.get('progress', {}).get('percentage', 0) > 0:
            return 'active'

        # Recent update → active
        last_update = parse_datetime(task.get('progress', {}).get('last_update', task['created_at']))
        days_since_update = (now - last_update).days
        if days_since_update <= 7:
            return 'active'

        # Otherwise → someday
        return 'someday'

    def cleanup_question_queue(self, dashboard: dict[str, Any]) -> None:
        """Clean up question queue - remove old/duplicate questions."""
        questions = dashboard['questions']
        now = datetime.now()

        original_count = len(questions)

        # Remove answered questions
        questions[:] = [q for q in questions if not q.get('answered', False)]

        # Remove very old questions (2 weeks+)
        questions[:] = [
            q for q in questions
            if (now - parse_datetime(q['created_at'])).days <= 14
        ]

        # Group by task
        task_questions = {}
        for q in questions:
            task_id = q.get('related_task_id')
            if task_id:
                if task_id not in task_questions:
                    task_questions[task_id] = []
                task_questions[task_id].append(q)

        # Keep only highest priority per task
        to_keep = []
        for task_id, qs in task_questions.items():
            if len(qs) == 1:
                to_keep.extend(qs)
            else:
                # Sort by priority, then by asked_count (lower is better)
                qs_sorted = sorted(
                    qs,
                    key=lambda x: (
                        {"high": 3, "medium": 2, "low": 1}.get(x.get('priority', 'low'), 0),
                        -x.get('asked_count', 0)
                    ),
                    reverse=True
                )
                to_keep.append(qs_sorted[0])

        # Add questions without task_id
        to_keep.extend([q for q in questions if not q.get('related_task_id')])

        dashboard['questions'] = to_keep

        logger.info(f"[Worker] Question queue cleaned: {original_count} → {len(to_keep)}")
