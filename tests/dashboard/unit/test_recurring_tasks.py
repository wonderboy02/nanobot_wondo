"""Test recurring task (daily habit) feature.

Tests cover:
- Core behavior: completion reset, miss, streak, idempotency
- Archive/someday protection for recurring tasks
- Tool tests: set_recurring, create_task with recurring
- Helper unit tests: _is_consecutive_day, _find_prev_valid_day
- Schema validation: RecurringConfig field validators
- Robustness: malformed data, exception isolation, edge cases
"""

import json
from datetime import date, datetime, timedelta

import pytest


@pytest.fixture
def test_workspace(tmp_path):
    """Create test workspace with dashboard structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    dashboard_dir = workspace / "dashboard"
    dashboard_dir.mkdir()

    (dashboard_dir / "tasks.json").write_text(json.dumps({"version": "1.0", "tasks": []}, indent=2))
    (dashboard_dir / "questions.json").write_text(
        json.dumps({"version": "1.0", "questions": []}, indent=2)
    )
    (dashboard_dir / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []}, indent=2)
    )

    knowledge_dir = dashboard_dir / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "insights.json").write_text(
        json.dumps({"version": "1.0", "insights": []}, indent=2)
    )

    return workspace


def _make_recurring_task(
    task_id="task_r01",
    title="Daily Exercise",
    status="active",
    progress=0,
    days_of_week=None,
    streak_current=0,
    streak_best=0,
    total_completed=0,
    total_missed=0,
    last_completed_date=None,
    last_miss_date=None,
    enabled=True,
    check_time=None,
):
    """Helper to create a recurring task dict."""
    now = datetime.now()
    return {
        "id": task_id,
        "title": title,
        "status": status,
        "priority": "medium",
        "created_at": (now - timedelta(days=7)).isoformat(),
        "updated_at": now.isoformat(),
        "completed_at": now.isoformat() if status == "completed" else None,
        "progress": {
            "percentage": progress,
            "last_update": now.isoformat(),
            "note": "",
            "blocked": False,
            "blocker_note": None,
        },
        "estimation": {"hours": None, "complexity": "medium", "confidence": "medium"},
        "context": "",
        "tags": ["habit"],
        "links": {"projects": [], "insights": [], "resources": []},
        "recurring": {
            "enabled": enabled,
            "frequency": "daily",
            "days_of_week": days_of_week or list(range(7)),
            "check_time": check_time,
            "streak_current": streak_current,
            "streak_best": streak_best,
            "total_completed": total_completed,
            "total_missed": total_missed,
            "last_completed_date": last_completed_date,
            "last_miss_date": last_miss_date,
        },
    }


# ============================================================================
# Core Behavior: Completion & Reset
# ============================================================================


@pytest.mark.asyncio
async def test_recurring_completion_resets_task(test_workspace):
    """Completed recurring task should be reset to active with progress=0."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()
    task = _make_recurring_task(
        status="completed",
        progress=100,
        last_completed_date=(today - timedelta(days=1)).isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    t = result["tasks"][0]
    assert t["status"] == "active"
    assert t["progress"]["percentage"] == 0
    assert t["completed_at"] is None
    assert t["recurring"]["total_completed"] == 1
    assert t["recurring"]["last_completed_date"] == today.isoformat()


@pytest.mark.asyncio
async def test_recurring_completion_increments_streak(test_workspace):
    """Consecutive completions should increment streak."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()
    yesterday = today - timedelta(days=1)

    task = _make_recurring_task(
        status="completed",
        progress=100,
        streak_current=3,
        streak_best=5,
        total_completed=10,
        last_completed_date=yesterday.isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    assert r["streak_current"] == 4
    assert r["streak_best"] == 5  # Unchanged (4 < 5)
    assert r["total_completed"] == 11


@pytest.mark.asyncio
async def test_recurring_completion_updates_best_streak(test_workspace):
    """New best streak should be updated."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()
    yesterday = today - timedelta(days=1)

    task = _make_recurring_task(
        status="completed",
        progress=100,
        streak_current=5,
        streak_best=5,
        last_completed_date=yesterday.isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    assert r["streak_current"] == 6
    assert r["streak_best"] == 6


@pytest.mark.asyncio
async def test_recurring_completion_no_previous(test_workspace):
    """First-ever completion starts streak at 1."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    task = _make_recurring_task(
        status="completed",
        progress=100,
        last_completed_date=None,
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    assert r["streak_current"] == 1
    assert r["total_completed"] == 1


@pytest.mark.asyncio
async def test_recurring_completion_same_day_idempotent(test_workspace):
    """Same-day re-completion should not double-count stats."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()

    task = _make_recurring_task(
        status="completed",
        progress=100,
        streak_current=3,
        total_completed=5,
        last_completed_date=today.isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    # Stats unchanged — same-day guard
    assert r["streak_current"] == 3
    assert r["total_completed"] == 5
    # But task still reset
    assert result["tasks"][0]["status"] == "active"
    assert result["tasks"][0]["progress"]["percentage"] == 0


# ============================================================================
# Core Behavior: Miss Detection
# ============================================================================


@pytest.mark.asyncio
async def test_recurring_miss_resets_streak(test_workspace):
    """Missed day should reset streak and increment miss counter."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()
    # Last completed 3 days ago → missed at least one day
    three_days_ago = today - timedelta(days=3)

    task = _make_recurring_task(
        status="active",
        progress=0,
        streak_current=5,
        total_missed=2,
        last_completed_date=three_days_ago.isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    assert r["streak_current"] == 0
    assert r["total_missed"] == 3


@pytest.mark.asyncio
async def test_recurring_miss_idempotent(test_workspace):
    """Same miss should not be counted twice on consecutive runs."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()
    yesterday = today - timedelta(days=1)

    task = _make_recurring_task(
        status="active",
        progress=0,
        streak_current=0,
        total_missed=1,
        last_completed_date=(today - timedelta(days=3)).isoformat(),
        last_miss_date=yesterday.isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    # Should not double-count — last_miss_date covers yesterday
    assert r["total_missed"] == 1


@pytest.mark.asyncio
async def test_recurring_progress_100_triggers_completion(test_workspace):
    """Progress 100% (not status=completed) should still trigger completion."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()
    yesterday = today - timedelta(days=1)

    task = _make_recurring_task(
        status="active",
        progress=100,
        last_completed_date=yesterday.isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    t = result["tasks"][0]
    assert t["status"] == "active"
    assert t["progress"]["percentage"] == 0
    assert t["recurring"]["total_completed"] == 1


# ============================================================================
# Consistency + Recurring Interaction
# ============================================================================


@pytest.mark.asyncio
async def test_consistency_r1_then_recurring_reset(test_workspace):
    """active + progress=100% → R1 sets completed → recurring resets to active.

    Verifies the full pipeline: _enforce_consistency (R1) marks the task
    as completed, _archive_completed_tasks skips it (recurring), then
    _check_recurring_tasks resets it. All in a single run_cycle.
    """
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()
    yesterday = today - timedelta(days=1)

    # active + progress=100 → R1 will auto-complete this
    task = _make_recurring_task(
        status="active",
        progress=100,
        streak_current=2,
        total_completed=5,
        last_completed_date=yesterday.isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # End state: reset to active (not archived, not completed)
    assert t["status"] == "active"
    assert t["progress"]["percentage"] == 0
    assert t["completed_at"] is None
    # Stats updated
    assert t["recurring"]["total_completed"] == 6
    assert t["recurring"]["streak_current"] == 3


# ============================================================================
# Archive & Someday Protection
# ============================================================================


@pytest.mark.asyncio
async def test_recurring_completed_not_archived(test_workspace):
    """Completed recurring task should NOT be archived (Worker resets it)."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_recurring_task(status="completed", progress=100)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    # Should be reset to active, NOT archived
    assert result["tasks"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_recurring_cancelled_is_archived(test_workspace):
    """Cancelled recurring task SHOULD be archived (cancel = stop recurring)."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_recurring_task(status="cancelled")

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "archived"


@pytest.mark.asyncio
async def test_recurring_task_stays_active(test_workspace):
    """Recurring task should always stay active (not demoted to someday)."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    # Old task with no progress — normally would become someday
    task = _make_recurring_task(status="someday")
    task["created_at"] = (datetime.now() - timedelta(days=30)).isoformat()
    task["progress"]["last_update"] = (datetime.now() - timedelta(days=30)).isoformat()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"


# ============================================================================
# Tool Tests: set_recurring
# ============================================================================


@pytest.mark.asyncio
async def test_set_recurring_tool_basic(test_workspace):
    """set_recurring should add config to existing task."""
    from nanobot.dashboard.storage import JsonStorageBackend

    from nanobot.agent.tools.dashboard.create_task import CreateTaskTool
    from nanobot.agent.tools.dashboard.set_recurring import SetRecurringTool

    backend = JsonStorageBackend(test_workspace)

    # First create a task
    create_tool = CreateTaskTool(test_workspace, backend)
    result = await create_tool.execute(title="Read books")
    task_id = result.split(":")[0].replace("Created ", "")

    # Then set recurring
    set_tool = SetRecurringTool(test_workspace, backend)
    result = await set_tool.execute(
        task_id=task_id,
        days_of_week=[0, 2, 4],  # Mon, Wed, Fri
        check_time="22:00",
    )

    assert "Set recurring" in result

    tasks_data = backend.load_tasks()
    task = tasks_data["tasks"][0]
    assert task["recurring"]["enabled"] is True
    assert task["recurring"]["days_of_week"] == [0, 2, 4]
    assert task["recurring"]["check_time"] == "22:00"


@pytest.mark.asyncio
async def test_set_recurring_preserves_stats(test_workspace):
    """Updating recurring config should preserve existing stats."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.agent.tools.dashboard.set_recurring import SetRecurringTool

    backend = JsonStorageBackend(test_workspace)
    task = _make_recurring_task(streak_current=5, streak_best=10, total_completed=20)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    set_tool = SetRecurringTool(test_workspace, backend)
    await set_tool.execute(task_id="task_r01", days_of_week=[0, 1, 2, 3, 4])

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    assert r["streak_current"] == 5
    assert r["streak_best"] == 10
    assert r["total_completed"] == 20
    assert r["days_of_week"] == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_set_recurring_not_found(test_workspace):
    """set_recurring on nonexistent task should return error."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.agent.tools.dashboard.set_recurring import SetRecurringTool

    backend = JsonStorageBackend(test_workspace)
    set_tool = SetRecurringTool(test_workspace, backend)
    result = await set_tool.execute(task_id="task_nonexistent")
    assert "not found" in result


# ============================================================================
# Tool Tests: create_task with recurring
# ============================================================================


@pytest.mark.asyncio
async def test_create_task_with_recurring(test_workspace):
    """create_task with recurring=True should include recurring config."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.agent.tools.dashboard.create_task import CreateTaskTool

    backend = JsonStorageBackend(test_workspace)
    tool = CreateTaskTool(test_workspace, backend)

    await tool.execute(
        title="Morning run",
        recurring=True,
        recurring_days=[0, 1, 2, 3, 4],
        recurring_check_time="07:00",
    )

    tasks_data = backend.load_tasks()
    task = tasks_data["tasks"][0]
    assert task["recurring"]["enabled"] is True
    assert task["recurring"]["days_of_week"] == [0, 1, 2, 3, 4]
    assert task["recurring"]["check_time"] == "07:00"
    assert task["recurring"]["streak_current"] == 0


# ============================================================================
# Helper Unit Tests: Static Methods
# ============================================================================


def test_is_consecutive_day_adjacent():
    """Mon→Tue should be consecutive for everyday schedule."""
    from nanobot.dashboard.worker import WorkerAgent

    mon = date(2026, 2, 23)  # Monday
    tue = date(2026, 2, 24)  # Tuesday
    assert WorkerAgent._is_consecutive_day(mon, tue, list(range(7))) is True


def test_is_consecutive_day_skip():
    """Mon→Wed should be consecutive for Mon/Wed/Fri schedule."""
    from nanobot.dashboard.worker import WorkerAgent

    mon = date(2026, 2, 23)  # Monday
    wed = date(2026, 2, 25)  # Wednesday
    assert WorkerAgent._is_consecutive_day(mon, wed, [0, 2, 4]) is True


def test_is_consecutive_day_gap():
    """Mon→Thu should NOT be consecutive for Mon/Wed/Fri schedule."""
    from nanobot.dashboard.worker import WorkerAgent

    mon = date(2026, 2, 23)  # Monday
    thu = date(2026, 2, 26)  # Thursday
    assert WorkerAgent._is_consecutive_day(mon, thu, [0, 2, 4]) is False


def test_find_prev_valid_day():
    """Should find previous valid day within 7 days."""
    from nanobot.dashboard.worker import WorkerAgent

    # Wednesday — previous valid for Mon/Wed/Fri should be Monday
    wed = date(2026, 2, 25)
    prev = WorkerAgent._find_prev_valid_day(wed, [0, 2, 4])
    assert prev == date(2026, 2, 23)  # Monday


def test_find_prev_valid_day_none():
    """Should return None if no valid day in 7-day window (shouldn't happen with valid schedule)."""
    from nanobot.dashboard.worker import WorkerAgent

    today = date(2026, 2, 25)
    # Empty-ish scenario: only today's weekday, so no *previous* day matches
    prev = WorkerAgent._find_prev_valid_day(today, [today.weekday()])
    # Should find the same weekday from last week
    assert prev == today - timedelta(days=7)


# ============================================================================
# Schema Validation: RecurringConfig
# ============================================================================


def test_recurring_config_defaults():
    """Default RecurringConfig should have all days and zero stats."""
    from nanobot.dashboard.schema import RecurringConfig

    config = RecurringConfig()
    assert config.enabled is True
    assert config.days_of_week == list(range(7))
    assert config.streak_current == 0
    assert config.check_time is None


def test_recurring_config_days_validation():
    """Invalid day numbers should raise ValueError."""
    from nanobot.dashboard.schema import RecurringConfig

    with pytest.raises(ValueError, match="Invalid day"):
        RecurringConfig(days_of_week=[7])

    with pytest.raises(ValueError, match="Invalid day"):
        RecurringConfig(days_of_week=[-1])


def test_recurring_config_empty_days():
    """Empty days_of_week should raise ValueError."""
    from nanobot.dashboard.schema import RecurringConfig

    with pytest.raises(ValueError, match="must not be empty"):
        RecurringConfig(days_of_week=[])


def test_recurring_config_days_sorted_deduped():
    """days_of_week should be sorted and deduplicated."""
    from nanobot.dashboard.schema import RecurringConfig

    config = RecurringConfig(days_of_week=[4, 2, 0, 2])
    assert config.days_of_week == [0, 2, 4]


def test_recurring_config_check_time_validation():
    """Invalid check_time format should raise ValueError."""
    from nanobot.dashboard.schema import RecurringConfig

    with pytest.raises(ValueError, match="HH:MM"):
        RecurringConfig(check_time="9am")


def test_recurring_config_date_validation():
    """Invalid date format should raise ValueError."""
    from nanobot.dashboard.schema import RecurringConfig

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        RecurringConfig(last_completed_date="not-a-date")


def test_task_with_recurring_field():
    """Task schema should accept recurring config."""
    from nanobot.dashboard.schema import Task

    now = datetime.now().isoformat()
    task = Task(
        id="task_001",
        title="Test",
        progress={"percentage": 0, "last_update": now},
        created_at=now,
        updated_at=now,
        recurring={"enabled": True, "days_of_week": [0, 1, 2, 3, 4]},
    )
    assert task.recurring is not None
    assert task.recurring.enabled is True
    assert task.recurring.days_of_week == [0, 1, 2, 3, 4]


def test_task_deadline_normalization():
    """Task deadline field_validator should convert datetime to date."""
    from nanobot.dashboard.schema import Task

    now = datetime.now().isoformat()
    task = Task(
        id="task_001",
        title="Test",
        deadline="2026-02-15T09:00:00",
        progress={"percentage": 0, "last_update": now},
        created_at=now,
        updated_at=now,
    )
    assert task.deadline == "2026-02-15"


# ============================================================================
# Robustness: Malformed Data
# ============================================================================


@pytest.mark.asyncio
async def test_recurring_malformed_config_skipped(test_workspace):
    """Task with recurring=True (not dict) should be safely skipped."""
    from nanobot.dashboard.worker import WorkerAgent

    now = datetime.now()

    # Write directly to JSON (bypasses Pydantic validation) to test runtime robustness
    tasks_file = test_workspace / "dashboard" / "tasks.json"
    tasks_data = {
        "version": "1.0",
        "tasks": [
            {
                "id": "task_bad",
                "title": "Bad recurring",
                "status": "active",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "progress": {"percentage": 0, "last_update": now.isoformat()},
                "recurring": True,  # Malformed — should be dict
            }
        ],
    }
    tasks_file.write_text(json.dumps(tasks_data, indent=2))

    from nanobot.dashboard.storage import JsonStorageBackend

    backend = JsonStorageBackend(test_workspace)
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    # Should not crash
    await worker.run_cycle()

    # Reload raw JSON to check (save may fail validation, but task should survive)
    result = json.loads(tasks_file.read_text())
    assert result["tasks"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_recurring_missing_fields_handled(test_workspace):
    """Recurring config with missing optional fields should work."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    task = _make_recurring_task(status="completed", progress=100)
    # Remove optional stat fields
    del task["recurring"]["streak_current"]
    del task["recurring"]["streak_best"]
    del task["recurring"]["total_completed"]

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    # Should initialize missing fields via .get() defaults
    assert r["total_completed"] == 1
    assert r["streak_current"] == 1


def test_recurring_exception_isolation(test_workspace):
    """Error in one recurring task should not affect others.

    Tests _check_recurring_tasks directly to verify in-memory exception
    isolation (save_tasks validation is a separate concern).
    """
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    today = date.today()

    good_task = _make_recurring_task(
        task_id="task_good",
        status="completed",
        progress=100,
        last_completed_date=(today - timedelta(days=1)).isoformat(),
    )
    # Bad task: broken date causes ValueError during processing
    bad_task = _make_recurring_task(task_id="task_bad", status="completed", progress=100)
    bad_task["recurring"]["last_completed_date"] = "not-a-date"

    tasks_data = {"version": "1.0", "tasks": [bad_task, good_task]}

    backend = JsonStorageBackend(test_workspace)
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    # Directly test the recurring processing (in-memory)
    changed = worker._check_recurring_tasks(tasks_data)

    assert changed is True
    # Good task should be processed despite bad task's error
    assert good_task["status"] == "active"
    assert good_task["recurring"]["total_completed"] == 1
    assert good_task["progress"]["percentage"] == 0


@pytest.mark.asyncio
async def test_recurring_disabled_not_processed(test_workspace):
    """Recurring with enabled=False should be skipped entirely."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_recurring_task(status="completed", progress=100, enabled=False)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    # Disabled recurring → normal archive behavior
    assert result["tasks"][0]["status"] == "archived"


@pytest.mark.asyncio
async def test_non_recurring_task_unaffected(test_workspace):
    """Non-recurring completed task should still be archived normally."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    now = datetime.now()

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(
        {
            "id": "task_normal",
            "title": "Normal Task",
            "status": "completed",
            "completed_at": now.isoformat(),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "progress": {"percentage": 100, "last_update": now.isoformat()},
        }
    )
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "archived"


@pytest.mark.asyncio
async def test_recurring_no_action_when_prev_day_already_completed(test_workspace):
    """No changes when previous valid day was already completed."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()

    # Schedule only for a day that is NOT today
    other_day = (today.weekday() + 3) % 7
    # Find the previous valid day for this schedule
    from nanobot.dashboard.worker import WorkerAgent as WA

    prev_valid = WA._find_prev_valid_day(today, [other_day])

    task = _make_recurring_task(
        days_of_week=[other_day],
        # Previous valid day already completed → no miss, no completion
        last_completed_date=prev_valid.isoformat() if prev_valid else today.isoformat(),
        last_miss_date=None,
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    assert r["total_completed"] == 0
    assert r["total_missed"] == 0
    assert r["streak_current"] == 0


@pytest.mark.asyncio
async def test_recurring_streak_broken_after_gap(test_workspace):
    """Completion after a gap (non-consecutive) should reset streak to 1."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()
    # Last completed 3 days ago (missed at least 1 day on everyday schedule)
    three_days_ago = today - timedelta(days=3)

    task = _make_recurring_task(
        status="completed",
        progress=100,
        streak_current=5,
        streak_best=5,
        last_completed_date=three_days_ago.isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    assert r["streak_current"] == 1  # Reset to 1
    assert r["streak_best"] == 5  # Best preserved


@pytest.mark.asyncio
async def test_recurring_mwf_streak(test_workspace):
    """Mon/Wed/Fri schedule: Mon→Wed completion should maintain streak."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    # Find a Wednesday
    today = date.today()
    days_until_wed = (2 - today.weekday()) % 7
    if days_until_wed == 0:
        wed = today
    else:
        wed = today + timedelta(days=days_until_wed)
    mon = wed - timedelta(days=2)

    task = _make_recurring_task(
        status="completed",
        progress=100,
        streak_current=3,
        days_of_week=[0, 2, 4],  # Mon, Wed, Fri
        last_completed_date=mon.isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    # Manually test the check method with the target date
    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    tasks_data2 = backend.load_tasks()
    task2 = tasks_data2["tasks"][0]
    changed = worker._process_one_recurring(task2, wed)

    assert changed is True
    assert task2["recurring"]["streak_current"] == 4


# ============================================================================
# Utils: normalize_iso_date
# ============================================================================


def test_normalize_iso_date():
    """normalize_iso_date should extract YYYY-MM-DD."""
    from nanobot.dashboard.utils import normalize_iso_date

    assert normalize_iso_date("2026-02-15") == "2026-02-15"
    assert normalize_iso_date("2026-02-15T09:00:00") == "2026-02-15"
    assert normalize_iso_date("2026-02-15T09:00:00+09:00") == "2026-02-15"
    assert normalize_iso_date("") is None
    assert normalize_iso_date("tomorrow") is None
    assert normalize_iso_date("내일") is None
    # Semantic validation: regex-matching but invalid dates
    assert normalize_iso_date("2026-99-99") is None
    assert normalize_iso_date("2026-13-01") is None
    assert normalize_iso_date("2026-02-30") is None
    assert normalize_iso_date("2026-99-99T09:00:00") is None


# ============================================================================
# Tool: update_task deadline normalization
# ============================================================================


@pytest.mark.asyncio
async def test_update_task_normalizes_deadline(test_workspace):
    """update_task should normalize datetime deadline to YYYY-MM-DD."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.agent.tools.dashboard.create_task import CreateTaskTool
    from nanobot.agent.tools.dashboard.update_task import UpdateTaskTool

    backend = JsonStorageBackend(test_workspace)
    create_tool = CreateTaskTool(test_workspace, backend)
    result = await create_tool.execute(title="Test deadline")
    task_id = result.split(":")[0].replace("Created ", "")

    update_tool = UpdateTaskTool(test_workspace, backend)
    await update_tool.execute(task_id=task_id, deadline="2026-03-15T14:00:00")

    tasks_data = backend.load_tasks()
    task = tasks_data["tasks"][0]
    assert task["deadline"] == "2026-03-15"
    assert task["deadline_text"] == "2026-03-15T14:00:00"


@pytest.mark.asyncio
async def test_update_task_natural_deadline_keeps_empty(test_workspace):
    """update_task with natural language deadline should set deadline to empty."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.agent.tools.dashboard.create_task import CreateTaskTool
    from nanobot.agent.tools.dashboard.update_task import UpdateTaskTool

    backend = JsonStorageBackend(test_workspace)
    create_tool = CreateTaskTool(test_workspace, backend)
    result = await create_tool.execute(title="Test deadline")
    task_id = result.split(":")[0].replace("Created ", "")

    update_tool = UpdateTaskTool(test_workspace, backend)
    await update_tool.execute(task_id=task_id, deadline="내일 오후 3시")

    tasks_data = backend.load_tasks()
    task = tasks_data["tasks"][0]
    assert task["deadline"] == ""  # Can't parse natural language → empty
    assert task["deadline_text"] == "내일 오후 3시"  # Original preserved


# ============================================================================
# Tool: set_recurring disable
# ============================================================================


@pytest.mark.asyncio
async def test_set_recurring_disable(test_workspace):
    """set_recurring(enabled=False) should disable recurring and allow archival."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.agent.tools.dashboard.set_recurring import SetRecurringTool
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_recurring_task(status="active", streak_current=5, total_completed=10)

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    # Disable recurring via tool
    set_tool = SetRecurringTool(test_workspace, backend)
    result = await set_tool.execute(task_id="task_r01", enabled=False)
    assert "Disabled" in result

    # Verify stats preserved
    tasks_data = backend.load_tasks()
    r = tasks_data["tasks"][0]["recurring"]
    assert r["enabled"] is False
    assert r["streak_current"] == 5
    assert r["total_completed"] == 10

    # Now complete and run worker — should be archived (not recurring anymore)
    tasks_data["tasks"][0]["status"] = "completed"
    tasks_data["tasks"][0]["completed_at"] = datetime.now().isoformat()
    tasks_data["tasks"][0]["progress"]["percentage"] = 100
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "archived"


# ============================================================================
# Issue fixes: archived revival, new-task false miss, check_time validation
# ============================================================================


@pytest.mark.asyncio
async def test_recurring_archived_not_revived(test_workspace):
    """Archived recurring task must NOT be processed or revived."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    today = date.today()

    # Archived task with recurring still enabled and progress=100
    task = _make_recurring_task(
        status="archived",
        progress=100,
        last_completed_date=(today - timedelta(days=1)).isoformat(),
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    # Must remain archived — not revived to active
    assert result["tasks"][0]["status"] == "archived"
    assert result["tasks"][0]["recurring"]["total_completed"] == 0


@pytest.mark.asyncio
async def test_recurring_new_task_no_false_miss(test_workspace):
    """Brand-new recurring task should not get a false miss on first cycle."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)

    # New task: both dates are None (just created)
    task = _make_recurring_task(
        status="active",
        progress=0,
        last_completed_date=None,
        last_miss_date=None,
    )

    tasks_data = backend.load_tasks()
    tasks_data["tasks"].append(task)
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker.run_cycle()

    result = backend.load_tasks()
    r = result["tasks"][0]["recurring"]
    # No false miss — brand-new task should be untouched
    assert r["total_missed"] == 0
    assert r["streak_current"] == 0


def test_recurring_config_check_time_out_of_range():
    """check_time with out-of-range values (99:99) should be rejected."""
    from nanobot.dashboard.schema import RecurringConfig

    with pytest.raises(ValueError, match="out of range"):
        RecurringConfig(check_time="99:99")

    with pytest.raises(ValueError, match="out of range"):
        RecurringConfig(check_time="24:00")

    # Valid edge cases
    config = RecurringConfig(check_time="00:00")
    assert config.check_time == "00:00"
    config = RecurringConfig(check_time="23:59")
    assert config.check_time == "23:59"
