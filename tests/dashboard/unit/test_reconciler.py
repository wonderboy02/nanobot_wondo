"""Unit tests for NotificationReconciler and ReconciliationScheduler."""

import asyncio
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from nanobot.dashboard.reconciler import (
    NotificationReconciler,
    ReconcileResult,
    ReconciliationScheduler,
)
from nanobot.dashboard.storage import JsonStorageBackend, SaveResult


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace with dashboard structure."""
    dashboard_path = tmp_path / "dashboard"
    dashboard_path.mkdir(parents=True)

    notifications_file = dashboard_path / "notifications.json"
    notifications_file.write_text(
        json.dumps({"version": "1.0", "notifications": []}), encoding="utf-8"
    )

    return tmp_path


@pytest.fixture
def backend(temp_workspace):
    return JsonStorageBackend(temp_workspace)


@pytest.fixture
def mock_gcal_client():
    client = Mock()
    client.create_event = Mock(return_value="gcal_evt_new")
    client.update_event = Mock()
    client.delete_event = Mock()
    return client


def _write_notifications(workspace, notifications):
    """Helper to write notifications to storage."""
    notif_file = workspace / "dashboard" / "notifications.json"
    data = {"version": "1.0", "notifications": notifications}
    notif_file.write_text(json.dumps(data), encoding="utf-8")


def _read_notifications(workspace):
    """Helper to read notifications from storage."""
    notif_file = workspace / "dashboard" / "notifications.json"
    return json.loads(notif_file.read_text())


def _make_notification(
    notif_id="n_001",
    status="pending",
    scheduled_at=None,
    gcal_event_id=None,
    **kwargs,
):
    """Helper to create a notification dict."""
    if scheduled_at is None:
        scheduled_at = (datetime.now() + timedelta(hours=2)).isoformat()
    n = {
        "id": notif_id,
        "message": f"Test {notif_id}",
        "scheduled_at": scheduled_at,
        "type": "reminder",
        "priority": "medium",
        "status": status,
        "created_at": "2026-02-20T10:00:00",
        "created_by": "worker",
        "gcal_event_id": gcal_event_id,
    }
    n.update(kwargs)
    return n


# ============================================================================
# ReconcileResult tests
# ============================================================================


class TestReconcileResult:
    def test_default_values(self):
        result = ReconcileResult()
        assert result.due == []
        assert result.next_due_at is None
        assert result.changed is False


# ============================================================================
# NotificationReconciler tests
# ============================================================================


class TestReconcilerReconcile:
    """Tests for NotificationReconciler.reconcile()."""

    def test_empty_notifications(self, temp_workspace, backend):
        """No notifications → empty result."""
        reconciler = NotificationReconciler(backend)
        result = reconciler.reconcile()

        assert result.due == []
        assert result.next_due_at is None
        assert result.changed is False

    def test_pending_past_is_due(self, temp_workspace, backend):
        """Pending notification in the past → due."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=past)])

        reconciler = NotificationReconciler(backend)
        result = reconciler.reconcile()

        assert len(result.due) == 1
        assert result.due[0]["id"] == "n_001"

    def test_pending_future_not_due(self, temp_workspace, backend):
        """Pending notification in the future → not due, next_due_at set."""
        future = (datetime.now() + timedelta(hours=3)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=future)])

        reconciler = NotificationReconciler(backend)
        result = reconciler.reconcile()

        assert len(result.due) == 0
        assert result.next_due_at is not None

    def test_cancelled_not_due(self, temp_workspace, backend):
        """Cancelled notification → not due, not in next_due_at."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(
            temp_workspace, [_make_notification(status="cancelled", scheduled_at=past)]
        )

        reconciler = NotificationReconciler(backend)
        result = reconciler.reconcile()

        assert len(result.due) == 0
        assert result.next_due_at is None

    def test_delivered_not_due(self, temp_workspace, backend):
        """Delivered notification → not due."""
        _write_notifications(temp_workspace, [_make_notification(status="delivered")])

        reconciler = NotificationReconciler(backend)
        result = reconciler.reconcile()

        assert len(result.due) == 0

    def test_multiple_pending_mixed(self, temp_workspace, backend):
        """Mix of past and future pending → correct split."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        _write_notifications(
            temp_workspace,
            [
                _make_notification("n_due", scheduled_at=past),
                _make_notification("n_future", scheduled_at=future),
            ],
        )

        reconciler = NotificationReconciler(backend)
        result = reconciler.reconcile()

        assert len(result.due) == 1
        assert result.due[0]["id"] == "n_due"
        assert result.next_due_at is not None

    def test_next_due_at_is_nearest(self, temp_workspace, backend):
        """next_due_at is the nearest future notification."""
        t1 = datetime.now() + timedelta(hours=1)
        t2 = datetime.now() + timedelta(hours=5)
        _write_notifications(
            temp_workspace,
            [
                _make_notification("n_1", scheduled_at=t1.isoformat()),
                _make_notification("n_2", scheduled_at=t2.isoformat()),
            ],
        )

        reconciler = NotificationReconciler(backend)
        result = reconciler.reconcile()

        assert result.next_due_at is not None
        diff = abs((result.next_due_at - t1).total_seconds())
        assert diff < 2  # Within 2 seconds tolerance

    def test_invalid_scheduled_at_skipped(self, temp_workspace, backend):
        """Invalid scheduled_at → notification skipped."""
        _write_notifications(temp_workspace, [_make_notification(scheduled_at="not-a-date")])

        reconciler = NotificationReconciler(backend)
        result = reconciler.reconcile()

        assert len(result.due) == 0
        assert result.next_due_at is None


class TestReconcilerGCal:
    """Tests for GCal sync in reconcile()."""

    def test_future_pending_creates_gcal(self, temp_workspace, backend, mock_gcal_client):
        """Future pending without gcal_event_id → create_event called."""
        future = (datetime.now() + timedelta(hours=2)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=future)])

        reconciler = NotificationReconciler(backend, gcal_client=mock_gcal_client)
        result = reconciler.reconcile()

        assert result.changed is True
        mock_gcal_client.create_event.assert_called_once()

        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["gcal_event_id"] == "gcal_evt_new"

    def test_future_pending_with_gcal_skips(self, temp_workspace, backend, mock_gcal_client):
        """Future pending WITH gcal_event_id → create_event NOT called."""
        future = (datetime.now() + timedelta(hours=2)).isoformat()
        _write_notifications(
            temp_workspace,
            [_make_notification(scheduled_at=future, gcal_event_id="existing_evt")],
        )

        reconciler = NotificationReconciler(backend, gcal_client=mock_gcal_client)
        result = reconciler.reconcile()

        assert result.changed is False
        mock_gcal_client.create_event.assert_not_called()

    def test_cancelled_removes_gcal(self, temp_workspace, backend, mock_gcal_client):
        """Cancelled notification with gcal_event_id → delete_event called."""
        _write_notifications(
            temp_workspace,
            [_make_notification(status="cancelled", gcal_event_id="gcal_to_del")],
        )

        reconciler = NotificationReconciler(backend, gcal_client=mock_gcal_client)
        result = reconciler.reconcile()

        assert result.changed is True
        mock_gcal_client.delete_event.assert_called_once_with(event_id="gcal_to_del")

        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["gcal_event_id"] is None

    def test_delivered_removes_gcal(self, temp_workspace, backend, mock_gcal_client):
        """Delivered notification with gcal_event_id → delete_event called."""
        _write_notifications(
            temp_workspace,
            [_make_notification(status="delivered", gcal_event_id="gcal_del_2")],
        )

        reconciler = NotificationReconciler(backend, gcal_client=mock_gcal_client)
        result = reconciler.reconcile()

        assert result.changed is True
        mock_gcal_client.delete_event.assert_called_once()

    def test_no_gcal_client_no_sync(self, temp_workspace, backend):
        """No gcal_client → no GCal operations, no change."""
        future = (datetime.now() + timedelta(hours=2)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=future)])

        reconciler = NotificationReconciler(backend)
        result = reconciler.reconcile()

        assert result.changed is False

    def test_gcal_create_failure_no_crash(self, temp_workspace, backend, mock_gcal_client):
        """GCal create_event failure → warning, no crash, not changed."""
        mock_gcal_client.create_event.side_effect = Exception("API down")
        future = (datetime.now() + timedelta(hours=2)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=future)])

        reconciler = NotificationReconciler(backend, gcal_client=mock_gcal_client)
        result = reconciler.reconcile()

        assert result.changed is False

    def test_gcal_delete_failure_preserves_id(self, temp_workspace, backend, mock_gcal_client):
        """GCal delete_event failure → gcal_event_id preserved for retry."""
        mock_gcal_client.delete_event.side_effect = Exception("API error")
        _write_notifications(
            temp_workspace,
            [_make_notification(status="cancelled", gcal_event_id="gcal_fail")],
        )

        reconciler = NotificationReconciler(backend, gcal_client=mock_gcal_client)
        result = reconciler.reconcile()

        assert result.changed is False
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["gcal_event_id"] == "gcal_fail"


class TestReconcilerMarkDelivered:
    """Tests for NotificationReconciler.mark_delivered()."""

    def test_mark_delivered_success(self, temp_workspace, backend):
        """Mark pending notification as delivered → True."""
        _write_notifications(temp_workspace, [_make_notification()])

        reconciler = NotificationReconciler(backend)
        ok = reconciler.mark_delivered("n_001")

        assert ok is True
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["status"] == "delivered"
        assert data["notifications"][0]["delivered_at"] is not None

    def test_mark_delivered_not_found(self, temp_workspace, backend):
        """Notification not found → False."""
        _write_notifications(temp_workspace, [_make_notification()])

        reconciler = NotificationReconciler(backend)
        ok = reconciler.mark_delivered("n_nonexistent")

        assert ok is False

    def test_mark_delivered_wrong_status(self, temp_workspace, backend):
        """Non-pending notification → False."""
        _write_notifications(temp_workspace, [_make_notification(status="cancelled")])

        reconciler = NotificationReconciler(backend)
        ok = reconciler.mark_delivered("n_001")

        assert ok is False
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["status"] == "cancelled"

    def test_mark_delivered_removes_gcal(self, temp_workspace, backend, mock_gcal_client):
        """mark_delivered removes GCal event."""
        _write_notifications(
            temp_workspace, [_make_notification(gcal_event_id="gcal_del_on_delivery")]
        )

        reconciler = NotificationReconciler(backend, gcal_client=mock_gcal_client)
        ok = reconciler.mark_delivered("n_001")

        assert ok is True
        mock_gcal_client.delete_event.assert_called_once()
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["gcal_event_id"] is None

    def test_mark_delivered_save_failure(self, temp_workspace, backend):
        """Save failure → False."""
        _write_notifications(temp_workspace, [_make_notification()])

        reconciler = NotificationReconciler(backend)

        # Patch save to fail
        original_save = backend.save_notifications
        backend.save_notifications = lambda data: SaveResult(False, "disk full")

        ok = reconciler.mark_delivered("n_001")

        assert ok is False
        backend.save_notifications = original_save


# ============================================================================
# ReconciliationScheduler tests
# ============================================================================


class TestSchedulerTrigger:
    """Tests for ReconciliationScheduler.trigger()."""

    @pytest.mark.asyncio
    async def test_trigger_delivers_due(self, temp_workspace, backend):
        """Due notification → deliver called, mark_delivered called."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=past)])

        reconciler = NotificationReconciler(
            backend, default_chat_id="chat_123", default_channel="telegram"
        )
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        await scheduler.trigger()

        send_cb.assert_called_once()
        msg = send_cb.call_args.args[0]
        assert msg.chat_id == "chat_123"
        assert msg.channel == "telegram"

        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["status"] == "delivered"

    @pytest.mark.asyncio
    async def test_trigger_no_due_no_delivery(self, temp_workspace, backend):
        """No due notifications → send_callback not called."""
        future = (datetime.now() + timedelta(hours=2)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=future)])

        reconciler = NotificationReconciler(backend, default_chat_id="chat_123")
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        await scheduler.trigger()

        send_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_trigger_multiple_due(self, temp_workspace, backend):
        """Multiple due → all delivered."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(
            temp_workspace,
            [
                _make_notification("n_a", scheduled_at=past),
                _make_notification("n_b", scheduled_at=past),
            ],
        )

        reconciler = NotificationReconciler(
            backend, default_chat_id="chat_123", default_channel="telegram"
        )
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        await scheduler.trigger()

        assert send_cb.call_count == 2


class TestSchedulerDelivery:
    """Tests for the full delivery flow: send-first + mark retry."""

    @pytest.mark.asyncio
    async def test_successful_delivery_and_mark(self, temp_workspace, backend):
        """Happy path: send succeeds, mark succeeds → clean state."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=past)])

        reconciler = NotificationReconciler(
            backend, default_chat_id="chat_123", default_channel="telegram"
        )
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        await scheduler.trigger()

        send_cb.assert_called_once()
        assert "n_001" not in scheduler._delivered
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["status"] == "delivered"

    @pytest.mark.asyncio
    async def test_send_failure_stays_pending(self, temp_workspace, backend):
        """Send failure → notification stays pending, not in dedup."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=past)])

        reconciler = NotificationReconciler(
            backend, default_chat_id="chat_123", default_channel="telegram"
        )
        send_cb = AsyncMock(side_effect=Exception("Network error"))
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        await scheduler.trigger()  # Should not raise

        send_cb.assert_called_once()
        # Notification stays pending (mark_delivered never called)
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["status"] == "pending"
        # Removed from dedup so next trigger can retry
        assert "n_001" not in scheduler._delivered

    @pytest.mark.asyncio
    async def test_send_failure_retries_on_next_trigger(self, temp_workspace, backend):
        """1st trigger send fails → 2nd trigger succeeds → delivered."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=past)])

        reconciler = NotificationReconciler(
            backend, default_chat_id="chat_123", default_channel="telegram"
        )
        send_cb = AsyncMock(side_effect=Exception("Network error"))
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        # First trigger: send fails
        await scheduler.trigger()
        assert send_cb.call_count == 1
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["status"] == "pending"

        # Fix send_callback for second trigger
        send_cb.side_effect = None
        send_cb.reset_mock()

        await scheduler.trigger()
        assert send_cb.call_count == 1
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["status"] == "delivered"

    @pytest.mark.asyncio
    async def test_no_chat_id_not_in_dedup(self, temp_workspace, backend):
        """No chat_id → skip without adding to dedup set."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=past)])

        reconciler = NotificationReconciler(backend)  # no chat_id
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        await scheduler.trigger()

        send_cb.assert_not_called()
        assert "n_001" not in scheduler._delivered

    @pytest.mark.asyncio
    async def test_mark_failure_retains_dedup(self, temp_workspace, backend):
        """mark_delivered fails all 3 retries → ID retained in dedup."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=past)])

        reconciler = NotificationReconciler(
            backend, default_chat_id="chat_123", default_channel="telegram"
        )
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        # Force mark_delivered to always fail
        reconciler.mark_delivered = lambda nid: False

        await scheduler.trigger()
        assert send_cb.call_count == 1
        assert "n_001" in scheduler._delivered  # Retained in dedup

    @pytest.mark.asyncio
    async def test_mark_retry_succeeds_on_second_attempt(self, temp_workspace, backend):
        """mark_delivered fails first, succeeds second → clean state."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=past)])

        reconciler = NotificationReconciler(
            backend, default_chat_id="chat_123", default_channel="telegram"
        )
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        # First call returns False, second returns True
        call_count = {"n": 0}
        original_mark = reconciler.mark_delivered

        def flaky_mark(nid):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return False
            return original_mark(nid)

        reconciler.mark_delivered = flaky_mark

        await scheduler.trigger()

        assert send_cb.call_count == 1
        assert "n_001" not in scheduler._delivered  # Clean after successful retry
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["status"] == "delivered"

    @pytest.mark.asyncio
    async def test_duplicate_prevented_on_mark_failure(self, temp_workspace, backend):
        """Dedup prevents re-delivery when mark failed on prior trigger."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=past)])

        reconciler = NotificationReconciler(
            backend, default_chat_id="chat_123", default_channel="telegram"
        )
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        reconciler.mark_delivered = lambda nid: False

        # First trigger sends message (mark fails)
        await scheduler.trigger()
        assert send_cb.call_count == 1

        # Second trigger: dedup prevents duplicate send
        await scheduler.trigger()
        assert send_cb.call_count == 1  # Still 1

    @pytest.mark.asyncio
    async def test_successful_mark_allows_future_delivery(self, temp_workspace, backend):
        """Successful mark removes from dedup, allowing future notifications."""
        past = (datetime.now() - timedelta(minutes=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=past)])

        reconciler = NotificationReconciler(
            backend, default_chat_id="chat_123", default_channel="telegram"
        )
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        await scheduler.trigger()
        assert send_cb.call_count == 1
        assert "n_001" not in scheduler._delivered  # Removed on success


class TestSchedulerTimer:
    """Tests for timer arm/cancel."""

    @pytest.mark.asyncio
    async def test_stop_cancels_timer(self, temp_workspace, backend):
        """stop() cancels armed timer."""
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=future)])

        reconciler = NotificationReconciler(backend, default_chat_id="chat_123")
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        await scheduler.trigger()

        assert scheduler._timer_task is not None
        assert not scheduler._timer_task.done()

        scheduler.stop()

        assert scheduler._timer_task is None

    @pytest.mark.asyncio
    async def test_no_future_no_timer(self, temp_workspace, backend):
        """No future notifications → no timer armed."""
        reconciler = NotificationReconciler(backend, default_chat_id="chat_123")
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        await scheduler.trigger()

        assert scheduler._timer_task is None


class TestReconcileSaveFailure:
    """Tests for reconcile() when save fails after GCal sync."""

    def test_save_failure_after_gcal_sync(self, temp_workspace, backend, mock_gcal_client):
        """GCal event created but save fails → result.changed still True."""
        future = (datetime.now() + timedelta(hours=2)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=future)])

        mock_gcal_client.create_event.return_value = "gcal_new"

        # Make save fail
        original_save = backend.save_notifications
        backend.save_notifications = lambda data: SaveResult(False, "disk full")

        reconciler = NotificationReconciler(backend, gcal_client=mock_gcal_client)
        result = reconciler.reconcile()

        assert result.changed is True
        mock_gcal_client.create_event.assert_called_once()

        # Restore for cleanup
        backend.save_notifications = original_save


class TestGCalDescription:
    """Tests for GCal event description content."""

    def test_ensure_gcal_includes_context_and_task(self, temp_workspace, backend, mock_gcal_client):
        """GCal event description includes context and related_task_id."""
        future = (datetime.now() + timedelta(hours=2)).isoformat()
        _write_notifications(
            temp_workspace,
            [
                _make_notification(
                    scheduled_at=future,
                    context="React Tutorial 시리즈",
                    related_task_id="task_001",
                )
            ],
        )

        mock_gcal_client.create_event.return_value = "gcal_ctx"

        reconciler = NotificationReconciler(backend, gcal_client=mock_gcal_client)
        reconciler.reconcile()

        call_kwargs = mock_gcal_client.create_event.call_args
        desc = call_kwargs.kwargs.get("description") or call_kwargs[1].get("description", "")
        assert "React Tutorial" in desc
        assert "task_001" in desc


class TestTimerEdgeCases:
    """Tests for _arm_timer edge cases."""

    @pytest.mark.asyncio
    async def test_timer_replaces_existing(self, temp_workspace, backend):
        """Second trigger replaces existing timer with earlier one."""
        far_future = (datetime.now() + timedelta(hours=5)).isoformat()
        _write_notifications(temp_workspace, [_make_notification("n_far", scheduled_at=far_future)])

        reconciler = NotificationReconciler(backend, default_chat_id="chat_123")
        send_cb = AsyncMock()
        scheduler = ReconciliationScheduler(reconciler, send_cb)

        await scheduler.trigger()
        first_timer = scheduler._timer_task
        assert first_timer is not None

        # Add a closer notification and re-trigger
        near_future = (datetime.now() + timedelta(minutes=10)).isoformat()
        _write_notifications(
            temp_workspace,
            [
                _make_notification("n_far", scheduled_at=far_future),
                _make_notification("n_near", scheduled_at=near_future),
            ],
        )

        await scheduler.trigger()
        second_timer = scheduler._timer_task

        # Allow event loop to process cancellation
        await asyncio.sleep(0)

        # Old timer should have been cancelled, new one armed
        assert first_timer.done()  # cancelled or finished
        assert second_timer is not None
        assert second_timer is not first_timer

        scheduler.stop()

    @pytest.mark.asyncio
    async def test_timer_fires_and_delivers(self, temp_workspace, backend):
        """Timer fires and delivers when notification becomes due."""
        near_future = (datetime.now() + timedelta(seconds=0.2)).isoformat()
        _write_notifications(temp_workspace, [_make_notification(scheduled_at=near_future)])

        reconciler = NotificationReconciler(
            backend, default_chat_id="chat_123", default_channel="telegram"
        )
        send_cb = AsyncMock()
        lock = asyncio.Lock()
        scheduler = ReconciliationScheduler(reconciler, send_cb, processing_lock=lock)

        await scheduler.trigger()  # Arms timer for ~0.2s
        await asyncio.sleep(0.5)  # Wait for timer fire

        send_cb.assert_called_once()
        scheduler.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
