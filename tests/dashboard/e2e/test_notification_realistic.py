"""Realistic E2E tests for notification system.

Tests notification tools directly without complex Mock LLM setup.
These tests verify the actual behavior of the notification system.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock

from nanobot.agent.tools.dashboard.schedule_notification import ScheduleNotificationTool
from nanobot.agent.tools.dashboard.update_notification import UpdateNotificationTool
from nanobot.agent.tools.dashboard.cancel_notification import CancelNotificationTool
from nanobot.agent.tools.dashboard.list_notifications import ListNotificationsTool
from nanobot.cron.service import CronService


@pytest.fixture
def test_workspace(tmp_path):
    """Create test workspace with dashboard and cron service."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    dashboard = workspace / "dashboard"
    dashboard.mkdir()

    # Initialize files
    (dashboard / "tasks.json").write_text(json.dumps({"version": "1.0", "tasks": []}))
    (dashboard / "questions.json").write_text(json.dumps({"version": "1.0", "questions": []}))
    (dashboard / "notifications.json").write_text(json.dumps({"version": "1.0", "notifications": []}))

    # Create cron service
    cron_path = tmp_path / "cron" / "jobs.json"
    cron_path.parent.mkdir(parents=True)
    cron_service = CronService(cron_path)

    return {
        "workspace": workspace,
        "dashboard": dashboard,
        "cron_service": cron_service
    }


class TestNotificationTools:
    """Test notification tools with real Cron Service integration."""

    @pytest.mark.asyncio
    async def test_schedule_notification_creates_cron_job(self, test_workspace):
        """Test that scheduling a notification creates a cron job."""
        workspace = test_workspace["workspace"]
        cron_service = test_workspace["cron_service"]

        tool = ScheduleNotificationTool(workspace, cron_service)

        # Schedule notification
        scheduled_time = (datetime.now() + timedelta(hours=2)).isoformat()
        result = await tool.execute(
            message="Test reminder",
            scheduled_at=scheduled_time,
            type="reminder",
            priority="medium"
        )

        assert "✅" in result
        assert "Notification scheduled" in result

        # Verify notification in JSON
        notifications_file = workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text(encoding="utf-8"))

        assert len(data["notifications"]) == 1
        notif = data["notifications"][0]
        assert notif["message"] == "Test reminder"
        assert notif["type"] == "reminder"
        assert notif["priority"] == "medium"
        assert notif["status"] == "pending"
        assert notif["cron_job_id"] is not None

        # Verify cron job created
        assert notif["cron_job_id"] in [job.id for job in cron_service.list_jobs()]

    @pytest.mark.asyncio
    async def test_update_notification_updates_cron_job(self, test_workspace):
        """Test that updating notification time updates the cron job."""
        workspace = test_workspace["workspace"]
        cron_service = test_workspace["cron_service"]

        schedule_tool = ScheduleNotificationTool(workspace, cron_service)
        update_tool = UpdateNotificationTool(workspace, cron_service)

        # Schedule notification
        scheduled_time = (datetime.now() + timedelta(hours=2)).isoformat()
        await schedule_tool.execute(
            message="Original message",
            scheduled_at=scheduled_time,
            type="reminder",
            priority="medium"
        )

        # Get notification ID
        notifications_file = workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text(encoding="utf-8"))
        notif_id = data["notifications"][0]["id"]
        old_cron_id = data["notifications"][0]["cron_job_id"]

        # Update scheduled time
        new_time = (datetime.now() + timedelta(hours=3)).isoformat()
        result = await update_tool.execute(
            notification_id=notif_id,
            scheduled_at=new_time
        )

        assert "✅" in result
        assert "updated" in result

        # Verify notification updated
        data = json.loads(notifications_file.read_text(encoding="utf-8"))
        notif = data["notifications"][0]
        assert notif["scheduled_at"] == new_time

        # Verify cron job updated (new job ID)
        new_cron_id = notif["cron_job_id"]
        assert new_cron_id != old_cron_id
        assert new_cron_id in [job.id for job in cron_service.list_jobs()]
        assert old_cron_id not in [job.id for job in cron_service.list_jobs()]

    @pytest.mark.asyncio
    async def test_cancel_notification_removes_cron_job(self, test_workspace):
        """Test that cancelling a notification removes the cron job."""
        workspace = test_workspace["workspace"]
        cron_service = test_workspace["cron_service"]

        schedule_tool = ScheduleNotificationTool(workspace, cron_service)
        cancel_tool = CancelNotificationTool(workspace, cron_service)

        # Schedule notification
        scheduled_time = (datetime.now() + timedelta(hours=2)).isoformat()
        await schedule_tool.execute(
            message="To be cancelled",
            scheduled_at=scheduled_time,
            type="reminder",
            priority="medium"
        )

        # Get notification ID and cron job ID
        notifications_file = workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text(encoding="utf-8"))
        notif_id = data["notifications"][0]["id"]
        cron_job_id = data["notifications"][0]["cron_job_id"]

        # Verify cron job exists
        assert cron_job_id in [job.id for job in cron_service.list_jobs()]

        # Cancel notification
        result = await cancel_tool.execute(
            notification_id=notif_id,
            reason="Task completed"
        )

        assert "✅" in result
        assert "cancelled" in result

        # Verify notification cancelled
        data = json.loads(notifications_file.read_text(encoding="utf-8"))
        notif = data["notifications"][0]
        assert notif["status"] == "cancelled"
        assert notif["cancelled_at"] is not None

        # Verify cron job removed
        assert cron_job_id not in [job.id for job in cron_service.list_jobs()]

    @pytest.mark.asyncio
    async def test_list_notifications_filters_correctly(self, test_workspace):
        """Test that list_notifications filters by status and task."""
        workspace = test_workspace["workspace"]
        cron_service = test_workspace["cron_service"]

        schedule_tool = ScheduleNotificationTool(workspace, cron_service)
        list_tool = ListNotificationsTool(workspace)

        # Schedule multiple notifications
        scheduled_time = (datetime.now() + timedelta(hours=2)).isoformat()

        await schedule_tool.execute(
            message="Task 1 reminder",
            scheduled_at=scheduled_time,
            type="reminder",
            priority="high",
            related_task_id="task_001"
        )

        await schedule_tool.execute(
            message="Task 2 reminder",
            scheduled_at=scheduled_time,
            type="reminder",
            priority="medium",
            related_task_id="task_002"
        )

        # List all pending notifications
        result = await list_tool.execute(status="pending")
        assert "Found 2 notification" in result  # "Found 2 notification(s)"
        assert "Task 1 reminder" in result
        assert "Task 2 reminder" in result

        # Filter by task ID
        result = await list_tool.execute(related_task_id="task_001")
        assert "Found 1 notification" in result  # "Found 1 notification(s)"
        assert "Task 1 reminder" in result
        assert "Task 2 reminder" not in result


class TestNotificationTaskIntegration:
    """Test notification integration with tasks."""

    @pytest.mark.asyncio
    async def test_notification_with_deadline_task(self, test_workspace):
        """Test creating notification for a task with deadline."""
        workspace = test_workspace["workspace"]
        cron_service = test_workspace["cron_service"]

        # Create task with deadline
        tasks_file = workspace / "dashboard" / "tasks.json"
        tomorrow = (datetime.now() + timedelta(days=1)).isoformat()
        tasks_data = {
            "version": "1.0",
            "tasks": [{
                "id": "task_001",
                "title": "블로그 작성",
                "deadline": tomorrow,
                "deadline_text": "내일",
                "status": "active",
                "priority": "high",
                "progress": {
                    "percentage": 70,
                    "last_update": datetime.now().isoformat(),
                    "note": "",
                    "blocked": False
                },
                "estimation": {"hours": None, "complexity": "medium", "confidence": "medium"},
                "context": "",
                "tags": [],
                "links": {"projects": [], "people": [], "insights": [], "resources": []},
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }]
        }
        tasks_file.write_text(json.dumps(tasks_data), encoding="utf-8")

        # Schedule deadline notification
        tool = ScheduleNotificationTool(workspace, cron_service)

        # Schedule for tomorrow morning
        tomorrow_morning = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0)
        result = await tool.execute(
            message="블로그 작성 마감이 오늘이에요! 현재 70%입니다.",
            scheduled_at=tomorrow_morning.isoformat(),
            type="deadline_alert",
            priority="high",
            related_task_id="task_001"
        )

        assert "✅" in result

        # Verify notification linked to task
        notifications_file = workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text(encoding="utf-8"))

        notif = data["notifications"][0]
        assert notif["related_task_id"] == "task_001"
        assert notif["type"] == "deadline_alert"
        assert notif["priority"] == "high"
        assert "블로그" in notif["message"]

    @pytest.mark.asyncio
    async def test_multiple_notifications_for_same_task(self, test_workspace):
        """Test creating multiple notifications for the same task."""
        workspace = test_workspace["workspace"]
        cron_service = test_workspace["cron_service"]

        tool = ScheduleNotificationTool(workspace, cron_service)

        # Schedule deadline alert
        deadline_time = (datetime.now() + timedelta(days=1, hours=9)).isoformat()
        await tool.execute(
            message="Deadline approaching!",
            scheduled_at=deadline_time,
            type="deadline_alert",
            priority="high",
            related_task_id="task_001"
        )

        # Schedule progress check
        progress_time = (datetime.now() + timedelta(days=2)).isoformat()
        await tool.execute(
            message="How's progress?",
            scheduled_at=progress_time,
            type="progress_check",
            priority="medium",
            related_task_id="task_001"
        )

        # Verify both notifications created
        notifications_file = workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text(encoding="utf-8"))

        assert len(data["notifications"]) == 2

        task_notifications = [n for n in data["notifications"] if n["related_task_id"] == "task_001"]
        assert len(task_notifications) == 2

        types = [n["type"] for n in task_notifications]
        assert "deadline_alert" in types
        assert "progress_check" in types


class TestNotificationPriority:
    """Test notification priority handling."""

    @pytest.mark.asyncio
    async def test_high_priority_notification(self, test_workspace):
        """Test creating high priority notification."""
        workspace = test_workspace["workspace"]
        cron_service = test_workspace["cron_service"]

        tool = ScheduleNotificationTool(workspace, cron_service)

        scheduled_time = (datetime.now() + timedelta(hours=1)).isoformat()
        result = await tool.execute(
            message="Urgent deadline!",
            scheduled_at=scheduled_time,
            type="deadline_alert",
            priority="high"
        )

        assert "✅" in result

        # Verify high priority
        notifications_file = workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text(encoding="utf-8"))

        notif = data["notifications"][0]
        assert notif["priority"] == "high"
        assert notif["type"] == "deadline_alert"

    @pytest.mark.asyncio
    async def test_low_priority_notification(self, test_workspace):
        """Test creating low priority notification."""
        workspace = test_workspace["workspace"]
        cron_service = test_workspace["cron_service"]

        tool = ScheduleNotificationTool(workspace, cron_service)

        scheduled_time = (datetime.now() + timedelta(days=7)).isoformat()
        result = await tool.execute(
            message="Weekly reminder",
            scheduled_at=scheduled_time,
            type="reminder",
            priority="low"
        )

        assert "✅" in result

        # Verify low priority
        notifications_file = workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text(encoding="utf-8"))

        notif = data["notifications"][0]
        assert notif["priority"] == "low"
        assert notif["type"] == "reminder"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
