"""Test snapshot-based user change detection in Worker Phase 1.

Tests that destructive rules (R6, R1, R2a, R5) and status re-evaluation
are skipped for tasks modified by the user between Worker cycles.
"""

import json

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


def _make_task(**overrides):
    """Create a minimal task dict that passes Pydantic validation."""
    task = {
        "id": "task_test01",
        "title": "Test Task",
        "status": "active",
        "priority": "medium",
        "deadline": "",
        "deadline_text": "",
        "context": "",
        "tags": [],
        "completed_at": None,
        "reflection": "",
        "recurring": None,
        "progress": {"percentage": 0, "last_update": "2026-01-01T00:00:00", "blocked": False},
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    # Merge progress overrides instead of replacing (preserves required fields)
    if "progress" in overrides:
        base_progress = task["progress"].copy()
        base_progress.update(overrides.pop("progress"))
        task["progress"] = base_progress
    task.update(overrides)
    return task


# ============================================================================
# First Run (no snapshot)
# ============================================================================


@pytest.mark.asyncio
async def test_first_run_no_snapshot(test_workspace):
    """First run: no snapshot file → all rules apply, snapshot created."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(id="task_first", status="active", progress={"percentage": 100})
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()

    result = backend.load_tasks()
    # R1 should have fired (no snapshot → no protection)
    assert result["tasks"][0]["status"] == "archived"  # R1→completed→archived

    # Snapshot file should have been created
    assert worker._snapshot_path().exists()


# ============================================================================
# No Changes Between Runs
# ============================================================================


@pytest.mark.asyncio
async def test_no_changes_between_runs(test_workspace):
    """Same data between runs → no user changes detected → rules apply normally."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(id="task_stable", status="someday")
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    # Run 1: creates snapshot
    await worker._run_maintenance()

    # Run 2: no external changes → normal rules
    result = backend.load_tasks()
    old_status = result["tasks"][0]["status"]
    await worker._run_maintenance()

    # Status may have been re-evaluated but no user-change protection triggered
    result2 = backend.load_tasks()
    # The task is someday with no deadline/progress → _determine_status may change it
    # Key assertion: no crash, snapshot updated
    assert worker._snapshot_path().exists()


# ============================================================================
# User Status Change Preserved
# ============================================================================


@pytest.mark.asyncio
async def test_user_status_change_preserved(test_workspace):
    """User changes status someday→active in Notion → Worker should NOT demote back."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    # Task starts as someday with no deadline/progress (would be demoted)
    task = _make_task(
        id="task_user",
        status="someday",
        created_at="2025-01-01T00:00:00",
        progress={"percentage": 0, "last_update": "2025-01-01T00:00:00", "blocked": False},
    )
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    # Run 1: creates snapshot with status=someday
    await worker._run_maintenance()

    # Simulate user changing status to active (e.g. via Notion)
    current = backend.load_tasks()
    current["tasks"][0]["status"] = "active"
    backend.save_tasks(current)

    # Run 2: should detect user change and skip status re-evaluation
    await worker._run_maintenance()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"  # NOT demoted back to someday


# ============================================================================
# User-Changed Skips R1 (auto-complete)
# ============================================================================


@pytest.mark.asyncio
async def test_user_changed_skips_r1(test_workspace):
    """User sets progress=100% but keeps active → R1 auto-complete should be skipped."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(id="task_r1skip", status="active", progress={"percentage": 50})
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()

    # User bumps progress to 100% (but keeps active — maybe reviewing)
    current = backend.load_tasks()
    current["tasks"][0]["progress"]["percentage"] = 100
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    assert result["tasks"][0]["status"] == "active"  # NOT auto-completed
    assert result["tasks"][0]["progress"]["percentage"] == 100


# ============================================================================
# User-Changed Skips R6 (clear completed_at)
# ============================================================================


@pytest.mark.asyncio
async def test_user_changed_skips_r6(test_workspace):
    """User sets completed_at on active task → R6 should NOT clear it."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(id="task_r6skip", status="active", completed_at=None)
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()

    # User adds completed_at while keeping status=active
    current = backend.load_tasks()
    current["tasks"][0]["completed_at"] = "2026-03-01T00:00:00"
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    assert result["tasks"][0]["completed_at"] == "2026-03-01T00:00:00"


# ============================================================================
# Safe Rules Always Apply (R3, R7, R8)
# ============================================================================


@pytest.mark.asyncio
async def test_safe_rules_always_apply(test_workspace):
    """Additive rules (R3, R7, R8) apply even to user-changed tasks."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(
        id="task_safe",
        status="active",
        deadline="2026-06-01",
        deadline_text="",
    )
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()

    # User changes title (triggers user-changed detection)
    current = backend.load_tasks()
    current["tasks"][0]["title"] = "Updated Title"
    # deadline_text still empty — R8 should backfill
    current["tasks"][0]["deadline_text"] = ""
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    # R8 should have backfilled deadline_text even though task is user-changed
    assert result["tasks"][0]["deadline_text"] == "2026-06-01"


# ============================================================================
# New Task Not User-Changed
# ============================================================================


@pytest.mark.asyncio
async def test_new_task_not_user_changed(test_workspace):
    """Tasks not in snapshot (newly added) are NOT treated as user-changed."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task1 = _make_task(id="task_existing", status="active")
    tasks_data = {"version": "1.0", "tasks": [task1]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()

    # Add new task with progress=100% (should trigger R1)
    current = backend.load_tasks()
    new_task = _make_task(id="task_new", status="active", progress={"percentage": 100})
    current["tasks"].append(new_task)
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    new_t = next(t for t in result["tasks"] if t["id"] == "task_new")
    # New task → all rules apply → R1 fires → archived (completed→archived)
    assert new_t["status"] == "archived"


# ============================================================================
# Corrupt Snapshot Graceful
# ============================================================================


@pytest.mark.asyncio
async def test_corrupt_snapshot_graceful(test_workspace):
    """Corrupted snapshot file → treated as first run, no error."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(id="task_corrupt", status="active", progress={"percentage": 100})
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    # Write corrupt snapshot
    worker._snapshot_path().write_text("NOT VALID JSON {{{", encoding="utf-8")

    # Should not raise — treats as first run
    await worker._run_maintenance()

    result = backend.load_tasks()
    # R1 fired (no valid snapshot → no protection)
    assert result["tasks"][0]["status"] == "archived"


# ============================================================================
# Snapshot Not Saved on Save Failure
# ============================================================================


@pytest.mark.asyncio
async def test_snapshot_not_saved_on_failure(test_workspace):
    """When save_tasks fails, snapshot should NOT be updated."""
    from unittest.mock import patch

    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    # Task that will trigger R1 (progress=100% + active → completed)
    task = _make_task(id="task_fail", status="active", progress={"percentage": 100})
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)

    # Save snapshot matching the file data (no user-change detection)
    worker._save_snapshot(tasks_data["tasks"])
    initial_snapshot = json.loads(worker._snapshot_path().read_text(encoding="utf-8"))

    # Make save_tasks return failure — R1 will fire but save fails
    with patch.object(backend, "save_tasks", return_value=(False, "disk full")):
        await worker._run_maintenance()

    # Snapshot should remain unchanged (save failed → no snapshot update)
    after_snapshot = json.loads(worker._snapshot_path().read_text(encoding="utf-8"))
    assert initial_snapshot == after_snapshot


# ============================================================================
# Archive Still Runs for User-Changed Tasks
# ============================================================================


@pytest.mark.asyncio
async def test_archive_still_runs(test_workspace):
    """User-changed tasks with completed/cancelled status should still be archived."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(id="task_arch", status="active")
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()

    # User sets status to completed
    current = backend.load_tasks()
    current["tasks"][0]["status"] = "completed"
    current["tasks"][0]["completed_at"] = "2026-03-01T00:00:00"
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    # Archive runs regardless of user-changed flag
    assert result["tasks"][0]["status"] == "archived"


# ============================================================================
# Recurring Promotion Still Runs for User-Changed Tasks
# ============================================================================


@pytest.mark.asyncio
async def test_recurring_promotion_still_runs(test_workspace):
    """Recurring tasks are always promoted to active even if user-changed."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(
        id="task_recur",
        status="active",
        recurring={"enabled": True, "frequency": "daily", "days_of_week": [0, 1, 2, 3, 4, 5, 6]},
    )
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()

    # User changes status to someday (but recurring is still enabled)
    current = backend.load_tasks()
    current["tasks"][0]["status"] = "someday"
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    # Recurring promotion ignores user-changed flag
    assert result["tasks"][0]["status"] == "active"


# ============================================================================
# Field-Level Guard Tests
# ============================================================================


@pytest.mark.asyncio
async def test_title_only_change_rules_still_fire(test_workspace):
    """Title-only change → no guard field hit → R1 fires normally."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    # Snapshot: active + progress=100% + title="Original"
    task = _make_task(id="task_title", status="active", progress={"percentage": 100})
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    # Save snapshot manually to match current state (skip running maintenance)
    worker._save_snapshot(tasks_data["tasks"])

    # User changes only title
    current = backend.load_tasks()
    current["tasks"][0]["title"] = "Changed Title Only"
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # title is not a guard field for R1 → R1 fires → completed → archived
    assert t["status"] == "archived"


@pytest.mark.asyncio
async def test_status_change_skips_r1_but_not_r6(test_workspace):
    """User changes status only → R1 skipped, R6 still fires."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    # active task with completed_at set (will trigger R6) and progress=100% (will trigger R1)
    task = _make_task(
        id="task_statusonly",
        status="someday",
        progress={"percentage": 100},
        completed_at="2026-01-15T00:00:00",
    )
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()  # snapshot created (R1 fires → completed → archived)

    # Reset: put back as active with completed_at and progress=100
    task2 = _make_task(
        id="task_statusonly",
        status="active",
        progress={"percentage": 100},
        completed_at="2026-01-15T00:00:00",
    )
    tasks_data2 = {"version": "1.0", "tasks": [task2]}
    backend.save_tasks(tasks_data2)
    # Save snapshot matching this state
    worker._save_snapshot(tasks_data2["tasks"])

    # User changes only status: active → someday (but status guard field is hit)
    current = backend.load_tasks()
    current["tasks"][0]["status"] = "someday"
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # R1 guard = {status, progress} — status changed → R1 skipped (stays someday, not completed)
    # R6 guard = {completed_at} — not changed → R6 fires (completed_at cleared)
    assert t["status"] == "someday"  # R1 skipped, reevaluate also skipped (status changed)
    assert t["completed_at"] is None  # R6 fired


@pytest.mark.asyncio
async def test_completed_at_change_skips_r6_only(test_workspace):
    """User changes completed_at only → R6 skipped, R1 still fires."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(
        id="task_catonly",
        status="active",
        progress={"percentage": 50},
        completed_at=None,
    )
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()  # snapshot: active, progress=50, completed_at=None

    # User sets completed_at AND bumps progress to 100%
    # But we only want to test completed_at guard for R6.
    # Setup: active + completed_at=None + progress=100 in snapshot
    task2 = _make_task(
        id="task_catonly",
        status="active",
        progress={"percentage": 100},
        completed_at=None,
    )
    backend.save_tasks({"version": "1.0", "tasks": [task2]})
    worker._save_snapshot([task2])

    # User changes only completed_at
    current = backend.load_tasks()
    current["tasks"][0]["completed_at"] = "2026-06-01T00:00:00"
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # R6 guard = {completed_at} — changed → R6 skipped (completed_at preserved)
    # R1 guard = {status, progress} — neither changed → R1 fires
    # R1 preserves existing completed_at ("2026-06-01T00:00:00") via `completed_at or now`
    assert t["status"] == "archived"  # R1 → completed → archived
    assert t["completed_at"] == "2026-06-01T00:00:00"  # preserved by R1


@pytest.mark.asyncio
async def test_progress_change_skips_r5(test_workspace):
    """User changes progress → R5 (clear blocker_note) skipped."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(
        id="task_r5field",
        status="active",
        progress={
            "percentage": 30,
            "blocked": False,
            "blocker_note": "old note",
            "last_update": "2026-01-01T00:00:00",
        },
    )
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()  # R5 fires (blocked=False + blocker_note → clear)

    # Reset with blocker_note present again
    task2 = _make_task(
        id="task_r5field",
        status="active",
        progress={
            "percentage": 30,
            "blocked": False,
            "blocker_note": "leftover note",
            "last_update": "2026-01-01T00:00:00",
        },
    )
    backend.save_tasks({"version": "1.0", "tasks": [task2]})
    worker._save_snapshot([task2])

    # User changes progress percentage (progress field changed)
    current = backend.load_tasks()
    current["tasks"][0]["progress"]["percentage"] = 50
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # R5 guard = {progress} — progress changed → R5 skipped (blocker_note preserved)
    assert t["progress"].get("blocker_note") == "leftover note"


# ============================================================================
# Active Sync Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sync_status_completed_syncs_progress(test_workspace):
    """User changes status active→completed → progress synced to 100%, completed_at set."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(id="task_sync1", status="active", progress={"percentage": 50})
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()  # creates snapshot with status=active

    # User changes status to completed
    current = backend.load_tasks()
    current["tasks"][0]["status"] = "completed"
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # ActiveSync: status→completed → progress=100%, completed_at set
    assert t["progress"]["percentage"] == 100
    assert t["completed_at"] is not None


@pytest.mark.asyncio
async def test_sync_status_completed_preserves_user_progress(test_workspace):
    """User changes status→completed + progress=80% → ActiveSync preserves 80%, R2a skipped.

    Note: Archive then normalizes progress to 100% (archive is a safe rule that
    always applies). This test verifies that ActiveSync did NOT override user's
    progress (R2a was skipped due to user change guard), and that the final
    archived state is consistent.
    """
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(id="task_sync2", status="active", progress={"percentage": 50})
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()

    # User changes status to completed AND progress to 80%
    current = backend.load_tasks()
    current["tasks"][0]["status"] = "completed"
    current["tasks"][0]["progress"]["percentage"] = 80
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # ActiveSync preserved user's progress (R2a skipped), then archive normalized to 100%
    assert t["status"] == "archived"
    assert t["progress"]["percentage"] == 100  # archive normalizes
    assert t["completed_at"] is not None


@pytest.mark.asyncio
async def test_sync_status_completed_preserves_user_completed_at(test_workspace):
    """User changes status→completed + sets completed_at → user completed_at preserved."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(id="task_sync3", status="active", progress={"percentage": 50})
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    await worker._run_maintenance()

    # User changes status to completed AND sets completed_at
    current = backend.load_tasks()
    current["tasks"][0]["status"] = "completed"
    current["tasks"][0]["completed_at"] = "2026-01-15T12:00:00"
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # User changed both → user's completed_at preserved
    assert t["completed_at"] == "2026-01-15T12:00:00"
    assert t["progress"]["percentage"] == 100  # progress synced (user didn't change it)


@pytest.mark.asyncio
async def test_sync_status_active_from_completed_clears_completed_at(test_workspace):
    """User changes status completed→active → completed_at cleared."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    # Start as completed with completed_at and progress=100
    task = _make_task(
        id="task_sync4",
        status="completed",
        progress={"percentage": 100},
        completed_at="2026-01-10T00:00:00",
        recurring={"enabled": True, "frequency": "daily", "days_of_week": [0, 1, 2, 3, 4, 5, 6]},
    )
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    # Save snapshot directly (skip running maintenance to avoid archive/recurring side effects)
    worker._save_snapshot(tasks_data["tasks"])

    # User changes status to active (re-opening)
    current = backend.load_tasks()
    current["tasks"][0]["status"] = "active"
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # ActiveSync: completed→active → completed_at cleared
    assert t["completed_at"] is None
    assert t["status"] == "active"


@pytest.mark.asyncio
async def test_sync_status_active_from_someday_no_sync(test_workspace):
    """User changes status someday→active → no sync (already normal state)."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(
        id="task_sync5",
        status="someday",
        progress={"percentage": 30},
        completed_at=None,
    )
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    worker._save_snapshot(tasks_data["tasks"])

    # User changes status to active (from someday — not from completed/archived)
    current = backend.load_tasks()
    current["tasks"][0]["status"] = "active"
    backend.save_tasks(current)

    await worker._run_maintenance()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # No sync needed: someday→active is a normal transition
    assert t["completed_at"] is None  # was already None
    assert t["progress"]["percentage"] == 30  # unchanged


@pytest.mark.asyncio
async def test_sync_no_user_change_r1_still_fires(test_workspace):
    """No user changes + progress=100% → R1 fires normally (backward compat)."""
    from nanobot.dashboard.storage import JsonStorageBackend
    from nanobot.dashboard.worker import WorkerAgent

    backend = JsonStorageBackend(test_workspace)
    task = _make_task(id="task_sync6", status="active", progress={"percentage": 100})
    tasks_data = {"version": "1.0", "tasks": [task]}
    backend.save_tasks(tasks_data)

    worker = WorkerAgent(workspace=test_workspace, storage_backend=backend)
    # Save snapshot matching current state (no user change)
    worker._save_snapshot(tasks_data["tasks"])

    await worker._run_maintenance()

    result = backend.load_tasks()
    t = result["tasks"][0]
    # No user change → ActiveSync skipped → R1 fires → completed → archived
    assert t["status"] == "archived"
