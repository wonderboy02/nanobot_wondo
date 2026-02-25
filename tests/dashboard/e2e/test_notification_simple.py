"""Simple E2E tests for notification system."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta


@pytest.fixture
def test_workspace(tmp_path):
    """Create test workspace with dashboard."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    dashboard = workspace / "dashboard"
    dashboard.mkdir()

    # Initialize files
    (dashboard / "tasks.json").write_text(json.dumps({"version": "1.0", "tasks": []}))
    (dashboard / "questions.json").write_text(json.dumps({"version": "1.0", "questions": []}))
    (dashboard / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []})
    )

    return workspace


class TestNotificationCreation:
    """Test notification creation and management."""

    @pytest.mark.asyncio
    async def test_schedule_notification_creates_entry(self, test_workspace):
        """Test that scheduling a notification creates entry in notifications.json."""
        from nanobot.agent.tools.dashboard.schedule_notification import ScheduleNotificationTool
        from nanobot.cron.service import CronService
        from unittest.mock import Mock

        # Mock cron service
        cron = Mock(spec=CronService)
        mock_job = Mock()
        mock_job.id = "cron_123"
        cron.add_job = Mock(return_value=mock_job)

        tool = ScheduleNotificationTool(test_workspace, cron)

        # Schedule notification
        scheduled_time = (datetime.now() + timedelta(hours=1)).isoformat()
        result = await tool.execute(
            message="Test notification",
            scheduled_at=scheduled_time,
            type="reminder",
            priority="medium",
        )

        assert "✅" in result
        assert "Notification scheduled" in result

        # Verify notification saved
        notifications_file = test_workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text())

        assert len(data["notifications"]) == 1
        notif = data["notifications"][0]
        assert notif["message"] == "Test notification"
        assert notif["type"] == "reminder"
        assert notif["priority"] == "medium"
        assert notif["status"] == "pending"
        assert notif["cron_job_id"] == "cron_123"

        # Verify cron job created
        cron.add_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_notifications_shows_pending(self, test_workspace):
        """Test listing notifications shows pending notifications."""
        from nanobot.agent.tools.dashboard.list_notifications import ListNotificationsTool

        # Create test notification
        notifications_file = test_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Test notification",
                    "scheduled_at": (datetime.now() + timedelta(hours=1)).isoformat(),
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data))

        tool = ListNotificationsTool(test_workspace)
        result = await tool.execute()

        assert "Found 1 notification" in result
        assert "n_001" in result
        assert "Test notification" in result

    @pytest.mark.asyncio
    async def test_cancel_notification_marks_cancelled(self, test_workspace):
        """Test cancelling notification marks it as cancelled."""
        from nanobot.agent.tools.dashboard.cancel_notification import CancelNotificationTool
        from nanobot.cron.service import CronService
        from unittest.mock import Mock

        # Create test notification
        notifications_file = test_workspace / "dashboard" / "notifications.json"
        data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_001",
                    "message": "Test notification",
                    "scheduled_at": (datetime.now() + timedelta(hours=1)).isoformat(),
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "cron_job_id": "cron_123",
                    "created_at": datetime.now().isoformat(),
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(data))

        # Mock cron service
        cron = Mock(spec=CronService)
        cron.remove_job = Mock(return_value=True)

        tool = CancelNotificationTool(test_workspace, cron)
        result = await tool.execute("n_001", reason="Task completed")

        assert "✅" in result
        assert "cancelled" in result

        # Verify status updated
        data = json.loads(notifications_file.read_text())
        notif = data["notifications"][0]
        assert notif["status"] == "cancelled"
        assert notif["cancelled_at"] is not None

        # Verify cron job removed
        cron.remove_job.assert_called_once_with("cron_123")


class TestQuestionManagement:
    """Test question management tools."""

    @pytest.mark.asyncio
    async def test_update_question_changes_priority(self, test_workspace):
        """Test updating question priority."""
        from nanobot.agent.tools.dashboard.update_question import UpdateQuestionTool

        # Create test question
        questions_file = test_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Test question?",
                    "priority": "low",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": datetime.now().isoformat(),
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data))

        tool = UpdateQuestionTool(test_workspace)
        result = await tool.execute("q_001", priority="high")

        assert "✅" in result
        assert "low → high" in result

        # Verify priority updated
        data = json.loads(questions_file.read_text())
        assert data["questions"][0]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_remove_question_deletes_entry(self, test_workspace):
        """Test removing question deletes it from queue."""
        from nanobot.agent.tools.dashboard.remove_question import RemoveQuestionTool

        # Create test question
        questions_file = test_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Test question?",
                    "priority": "medium",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": datetime.now().isoformat(),
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data))

        tool = RemoveQuestionTool(test_workspace)
        result = await tool.execute("q_001", reason="duplicate")

        assert "✅" in result
        assert "removed" in result

        # Verify question removed
        data = json.loads(questions_file.read_text())
        assert len(data["questions"]) == 0


class TestNotificationTaskIntegration:
    """Test notification system integration with tasks."""

    @pytest.mark.asyncio
    async def test_notification_linked_to_task(self, test_workspace):
        """Test notification can be linked to a task."""
        from nanobot.agent.tools.dashboard.schedule_notification import ScheduleNotificationTool
        from nanobot.cron.service import CronService
        from unittest.mock import Mock

        # Create test task
        tasks_file = test_workspace / "dashboard" / "tasks.json"
        task_data = {
            "version": "1.0",
            "tasks": [
                {
                    "id": "task_001",
                    "title": "Test task",
                    "status": "active",
                    "priority": "high",
                    "progress": {
                        "percentage": 50,
                        "last_update": datetime.now().isoformat(),
                        "note": "",
                        "blocked": False,
                    },
                    "estimation": {"hours": None, "complexity": "medium", "confidence": "medium"},
                    "context": "",
                    "tags": [],
                    "links": {"projects": [], "insights": [], "resources": []},
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                }
            ],
        }
        tasks_file.write_text(json.dumps(task_data))

        # Mock cron service
        cron = Mock(spec=CronService)
        mock_job = Mock()
        mock_job.id = "cron_123"
        cron.add_job = Mock(return_value=mock_job)

        tool = ScheduleNotificationTool(test_workspace, cron)

        # Schedule notification for task
        scheduled_time = (datetime.now() + timedelta(hours=1)).isoformat()
        result = await tool.execute(
            message="Task deadline approaching",
            scheduled_at=scheduled_time,
            type="deadline_alert",
            priority="high",
            related_task_id="task_001",
        )

        assert "✅" in result

        # Verify notification linked to task
        notifications_file = test_workspace / "dashboard" / "notifications.json"
        data = json.loads(notifications_file.read_text())

        assert len(data["notifications"]) == 1
        notif = data["notifications"][0]
        assert notif["related_task_id"] == "task_001"
        assert notif["type"] == "deadline_alert"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
