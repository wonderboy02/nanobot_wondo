"""Unit tests for notification management tools (ledger-only, no cron)."""

import json
import pytest
from datetime import datetime, timedelta

from nanobot.agent.tools.dashboard.schedule_notification import ScheduleNotificationTool
from nanobot.agent.tools.dashboard.update_notification import UpdateNotificationTool
from nanobot.agent.tools.dashboard.cancel_notification import CancelNotificationTool
from nanobot.agent.tools.dashboard.list_notifications import ListNotificationsTool


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


class TestScheduleNotificationTool:
    """Test schedule_notification tool (ledger-only)."""

    @pytest.mark.asyncio
    async def test_schedule_notification_iso_datetime(self, temp_workspace):
        """Test scheduling notification with ISO datetime."""
        tool = ScheduleNotificationTool(temp_workspace)

        scheduled_at = "2026-02-10T09:00:00"
        result = await tool.execute(
            message="Test notification",
            scheduled_at=scheduled_at,
            type="reminder",
            priority="medium",
        )

        assert "✅" in result
        assert "Notification scheduled" in result

        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text())

        assert len(data["notifications"]) == 1
        notif = data["notifications"][0]
        assert notif["message"] == "Test notification"
        assert notif["scheduled_at"] == scheduled_at
        assert notif["type"] == "reminder"
        assert notif["priority"] == "medium"
        assert notif["status"] == "pending"
        assert notif["gcal_event_id"] is None

    @pytest.mark.asyncio
    async def test_schedule_notification_relative_time(self, temp_workspace):
        """Test scheduling notification with relative time."""
        tool = ScheduleNotificationTool(temp_workspace)

        result = await tool.execute(
            message="Reminder in 2 hours", scheduled_at="in 2 hours", type="reminder"
        )

        assert "✅" in result

        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text())

        notif = data["notifications"][0]
        scheduled_dt = datetime.fromisoformat(notif["scheduled_at"])
        now = datetime.now()

        time_diff = (scheduled_dt - now).total_seconds()
        assert 7000 < time_diff < 7500  # ~2 hours ± 5 minutes

    @pytest.mark.asyncio
    async def test_schedule_notification_with_related_task(self, temp_workspace):
        """Test scheduling notification with related task."""
        tool = ScheduleNotificationTool(temp_workspace)

        result = await tool.execute(
            message="Task deadline tomorrow",
            scheduled_at="2026-02-10T09:00:00",
            type="deadline_alert",
            priority="high",
            related_task_id="task_001",
            context="Automatic deadline reminder",
        )

        assert "✅" in result

        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text())

        notif = data["notifications"][0]
        assert notif["related_task_id"] == "task_001"
        assert notif["context"] == "Automatic deadline reminder"
        assert notif["type"] == "deadline_alert"

    @pytest.mark.asyncio
    async def test_schedule_notification_invalid_datetime(self, temp_workspace):
        """Test scheduling notification with invalid datetime."""
        tool = ScheduleNotificationTool(temp_workspace)

        result = await tool.execute(
            message="Test", scheduled_at="invalid_datetime", type="reminder"
        )

        assert "Error" in result
        assert "Could not parse" in result

    @pytest.mark.asyncio
    async def test_schedule_with_backend_injection(self, temp_workspace):
        """Test that backend parameter is properly forwarded."""
        from nanobot.dashboard.storage import JsonStorageBackend

        backend = JsonStorageBackend(temp_workspace)
        tool = ScheduleNotificationTool(temp_workspace, backend)

        result = await tool.execute(message="Backend test", scheduled_at="2026-03-01T10:00:00")

        assert "✅" in result


class TestUpdateNotificationTool:
    """Test update_notification tool (ledger-only)."""

    @pytest.mark.asyncio
    async def test_update_notification_message(self, temp_workspace):
        """Test updating notification message."""
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Old message",
                    "scheduled_at": "2026-02-10T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateNotificationTool(temp_workspace)

        result = await tool.execute(notification_id="n_001", message="New message")

        assert "✅" in result

        data = json.loads(notifications_file.read_text())
        notif = data["notifications"][0]
        assert notif["message"] == "New message"

    @pytest.mark.asyncio
    async def test_update_notification_scheduled_at(self, temp_workspace):
        """Test updating notification scheduled time resets gcal_event_id."""
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Test",
                    "scheduled_at": "2026-02-10T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                    "gcal_event_id": "gcal_evt_old",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateNotificationTool(temp_workspace)

        result = await tool.execute(notification_id="n_001", scheduled_at="2026-02-11T10:00:00")

        assert "✅" in result

        data = json.loads(notifications_file.read_text())
        notif = data["notifications"][0]
        assert notif["scheduled_at"] == "2026-02-11T10:00:00"
        assert notif["gcal_event_id"] is None  # Reset for Reconciler

    @pytest.mark.asyncio
    async def test_update_notification_not_found(self, temp_workspace):
        """Test updating non-existent notification."""
        tool = UpdateNotificationTool(temp_workspace)

        result = await tool.execute(notification_id="n_nonexistent", message="Test")

        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_update_notification_already_delivered(self, temp_workspace):
        """Test updating already delivered notification."""
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Test",
                    "scheduled_at": "2026-02-10T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "delivered",
                    "delivered_at": "2026-02-10T09:00:05",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateNotificationTool(temp_workspace)

        result = await tool.execute(notification_id="n_001", message="New message")

        assert "Error" in result
        assert "delivered" in result


class TestCancelNotificationTool:
    """Test cancel_notification tool (ledger-only)."""

    @pytest.mark.asyncio
    async def test_cancel_notification(self, temp_workspace):
        """Test cancelling notification."""
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Test",
                    "scheduled_at": "2026-02-10T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = CancelNotificationTool(temp_workspace)

        result = await tool.execute(notification_id="n_001", reason="Task completed early")

        assert "✅" in result

        data = json.loads(notifications_file.read_text())
        notif = data["notifications"][0]
        assert notif["status"] == "cancelled"
        assert notif["cancelled_at"] is not None
        assert "Task completed early" in notif.get("context", "")

    @pytest.mark.asyncio
    async def test_cancel_notification_not_found(self, temp_workspace):
        """Test cancelling non-existent notification."""
        tool = CancelNotificationTool(temp_workspace)

        result = await tool.execute(notification_id="n_nonexistent")

        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_cancel_notification_already_cancelled(self, temp_workspace):
        """Test cancelling already cancelled notification."""
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Test",
                    "scheduled_at": "2026-02-10T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "cancelled",
                    "cancelled_at": "2026-02-09T10:00:00",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = CancelNotificationTool(temp_workspace)

        result = await tool.execute(notification_id="n_001")

        assert "already cancelled" in result

    @pytest.mark.asyncio
    async def test_cancel_delivered_notification_rejected(self, temp_workspace):
        """Test cancelling a delivered notification returns error."""
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Test",
                    "scheduled_at": "2026-02-10T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "delivered",
                    "delivered_at": "2026-02-10T09:00:05",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = CancelNotificationTool(temp_workspace)

        result = await tool.execute(notification_id="n_001")

        assert "Error" in result
        assert "delivered" in result


class TestListNotificationsTool:
    """Test list_notifications tool."""

    @pytest.mark.asyncio
    async def test_list_all_notifications(self, temp_workspace):
        """Test listing all notifications."""
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Test 1",
                    "scheduled_at": "2026-02-10T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                },
                {
                    "id": "n_002",
                    "message": "Test 2",
                    "scheduled_at": "2026-02-11T09:00:00",
                    "type": "deadline_alert",
                    "priority": "high",
                    "status": "pending",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                },
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = ListNotificationsTool(temp_workspace)

        result = await tool.execute()

        assert "Found 2 notification" in result
        assert "n_001" in result
        assert "n_002" in result

    @pytest.mark.asyncio
    async def test_list_notifications_by_status(self, temp_workspace):
        """Test filtering notifications by status."""
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Pending",
                    "scheduled_at": "2026-02-10T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                },
                {
                    "id": "n_002",
                    "message": "Delivered",
                    "scheduled_at": "2026-02-09T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "delivered",
                    "delivered_at": "2026-02-09T09:00:05",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                },
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = ListNotificationsTool(temp_workspace)

        result = await tool.execute(status="pending")

        assert "Found 1 notification" in result
        assert "n_001" in result
        assert "n_002" not in result

    @pytest.mark.asyncio
    async def test_list_notifications_by_task(self, temp_workspace):
        """Test filtering notifications by related task."""
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Task 1 reminder",
                    "scheduled_at": "2026-02-10T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "related_task_id": "task_001",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                },
                {
                    "id": "n_002",
                    "message": "Task 2 reminder",
                    "scheduled_at": "2026-02-11T09:00:00",
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "related_task_id": "task_002",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                },
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = ListNotificationsTool(temp_workspace)

        result = await tool.execute(related_task_id="task_001")

        assert "Found 1 notification" in result
        assert "n_001" in result
        assert "n_002" not in result

    @pytest.mark.asyncio
    async def test_list_notifications_empty(self, temp_workspace):
        """Test listing when no notifications exist."""
        tool = ListNotificationsTool(temp_workspace)

        result = await tool.execute()

        assert "No notifications found" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
