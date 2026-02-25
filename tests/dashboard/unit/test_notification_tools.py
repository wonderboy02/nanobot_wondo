"""Unit tests for notification management tools."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock

from nanobot.agent.tools.dashboard.schedule_notification import ScheduleNotificationTool
from nanobot.agent.tools.dashboard.update_notification import UpdateNotificationTool
from nanobot.agent.tools.dashboard.cancel_notification import CancelNotificationTool
from nanobot.agent.tools.dashboard.list_notifications import ListNotificationsTool
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule, CronJob


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace with dashboard structure."""
    dashboard_path = tmp_path / "dashboard"
    dashboard_path.mkdir(parents=True)

    # Initialize notifications.json
    notifications_file = dashboard_path / "notifications.json"
    notifications_file.write_text(
        json.dumps({"version": "1.0", "notifications": []}), encoding="utf-8"
    )

    return tmp_path


@pytest.fixture
def mock_cron_service():
    """Mock CronService."""
    cron = Mock(spec=CronService)

    # Mock add_job to return a CronJob
    def add_job_side_effect(**kwargs):
        return CronJob(
            id="cron_12345",
            name=kwargs.get("name", "test"),
            enabled=True,
            schedule=kwargs.get("schedule"),
            payload=Mock(),
        )

    cron.add_job = Mock(side_effect=add_job_side_effect)
    cron.remove_job = Mock(return_value=True)

    return cron


class TestScheduleNotificationTool:
    """Test schedule_notification tool."""

    @pytest.mark.asyncio
    async def test_schedule_notification_iso_datetime(self, temp_workspace, mock_cron_service):
        """Test scheduling notification with ISO datetime."""
        tool = ScheduleNotificationTool(temp_workspace, mock_cron_service)

        scheduled_at = "2026-02-10T09:00:00"
        result = await tool.execute(
            message="Test notification",
            scheduled_at=scheduled_at,
            type="reminder",
            priority="medium",
        )

        assert "✅" in result
        assert "Notification scheduled" in result

        # Verify notification saved
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text())

        assert len(data["notifications"]) == 1
        notif = data["notifications"][0]
        assert notif["message"] == "Test notification"
        assert notif["scheduled_at"] == scheduled_at
        assert notif["type"] == "reminder"
        assert notif["priority"] == "medium"
        assert notif["status"] == "pending"
        assert notif["cron_job_id"] == "cron_12345"

        # Verify cron job created
        mock_cron_service.add_job.assert_called_once()
        call_kwargs = mock_cron_service.add_job.call_args.kwargs
        assert call_kwargs["deliver"] is True
        assert call_kwargs["delete_after_run"] is True

    @pytest.mark.asyncio
    async def test_schedule_notification_relative_time(self, temp_workspace, mock_cron_service):
        """Test scheduling notification with relative time."""
        tool = ScheduleNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(
            message="Reminder in 2 hours", scheduled_at="in 2 hours", type="reminder"
        )

        assert "✅" in result

        # Verify notification saved with parsed datetime
        notifications_file = temp_workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text())

        notif = data["notifications"][0]
        scheduled_dt = datetime.fromisoformat(notif["scheduled_at"])
        now = datetime.now()

        # Should be ~2 hours from now (allow 5 minute tolerance)
        time_diff = (scheduled_dt - now).total_seconds()
        assert 7000 < time_diff < 7500  # ~2 hours ± 5 minutes

    @pytest.mark.asyncio
    async def test_schedule_notification_with_related_task(self, temp_workspace, mock_cron_service):
        """Test scheduling notification with related task."""
        tool = ScheduleNotificationTool(temp_workspace, mock_cron_service)

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
    async def test_schedule_notification_invalid_datetime(self, temp_workspace, mock_cron_service):
        """Test scheduling notification with invalid datetime."""
        tool = ScheduleNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(
            message="Test", scheduled_at="invalid_datetime", type="reminder"
        )

        assert "Error" in result
        assert "Could not parse" in result


class TestUpdateNotificationTool:
    """Test update_notification tool."""

    @pytest.mark.asyncio
    async def test_update_notification_message(self, temp_workspace, mock_cron_service):
        """Test updating notification message."""
        # Create existing notification
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
                    "cron_job_id": "cron_001",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_001", message="New message")

        assert "✅" in result

        # Verify update
        data = json.loads(notifications_file.read_text())
        notif = data["notifications"][0]
        assert notif["message"] == "New message"

    @pytest.mark.asyncio
    async def test_update_notification_scheduled_at(self, temp_workspace, mock_cron_service):
        """Test updating notification scheduled time."""
        # Create existing notification
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
                    "cron_job_id": "cron_001",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_001", scheduled_at="2026-02-11T10:00:00")

        assert "✅" in result

        # Verify cron job updated (old removed, new created)
        mock_cron_service.remove_job.assert_called_once_with("cron_001")
        mock_cron_service.add_job.assert_called_once()

        # Verify notification updated
        data = json.loads(notifications_file.read_text())
        notif = data["notifications"][0]
        assert notif["scheduled_at"] == "2026-02-11T10:00:00"
        assert notif["cron_job_id"] == "cron_12345"  # New cron job ID

    @pytest.mark.asyncio
    async def test_update_notification_not_found(self, temp_workspace, mock_cron_service):
        """Test updating non-existent notification."""
        tool = UpdateNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_nonexistent", message="Test")

        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_update_notification_already_delivered(self, temp_workspace, mock_cron_service):
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
                    "cron_job_id": "cron_001",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_001", message="New message")

        assert "Error" in result
        assert "delivered" in result


class TestCancelNotificationTool:
    """Test cancel_notification tool."""

    @pytest.mark.asyncio
    async def test_cancel_notification(self, temp_workspace, mock_cron_service):
        """Test cancelling notification."""
        # Create existing notification
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
                    "cron_job_id": "cron_001",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = CancelNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_001", reason="Task completed early")

        assert "✅" in result

        # Verify cron job removed
        mock_cron_service.remove_job.assert_called_once_with("cron_001")

        # Verify notification status updated
        data = json.loads(notifications_file.read_text())
        notif = data["notifications"][0]
        assert notif["status"] == "cancelled"
        assert notif["cancelled_at"] is not None
        assert "Task completed early" in notif.get("context", "")

    @pytest.mark.asyncio
    async def test_cancel_notification_not_found(self, temp_workspace, mock_cron_service):
        """Test cancelling non-existent notification."""
        tool = CancelNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_nonexistent")

        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_cancel_notification_already_cancelled(self, temp_workspace, mock_cron_service):
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
                    "cron_job_id": "cron_001",
                    "created_at": "2026-02-08T10:00:00",
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data), encoding="utf-8")

        tool = CancelNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_001")

        assert "already cancelled" in result


class TestListNotificationsTool:
    """Test list_notifications tool."""

    @pytest.mark.asyncio
    async def test_list_all_notifications(self, temp_workspace):
        """Test listing all notifications."""
        # Create notifications
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
        assert "Test 1" in result
        assert "Test 2" in result

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
