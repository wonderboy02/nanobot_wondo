"""Unit tests for Google Calendar + Telegram integration in notification tools.

Tests GCal sync, instant Telegram notifications, backward compatibility,
and the _send_telegram helper.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, MagicMock, patch

from nanobot.agent.tools.dashboard.schedule_notification import ScheduleNotificationTool
from nanobot.agent.tools.dashboard.update_notification import UpdateNotificationTool
from nanobot.agent.tools.dashboard.cancel_notification import CancelNotificationTool
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule, CronJob


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
def mock_cron_service():
    """Mock CronService."""
    cron = Mock(spec=CronService)

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


@pytest.fixture
def mock_gcal_client():
    """Mock GoogleCalendarClient."""
    client = Mock()
    client.create_event = Mock(return_value="gcal_evt_123")
    client.update_event = Mock()
    client.delete_event = Mock()
    return client


@pytest.fixture
def mock_send_callback():
    """Mock async send_callback (bus.publish_outbound)."""
    return AsyncMock()


def _create_notification(temp_workspace, notification):
    """Helper to write a notification to the JSON file."""
    notif_file = temp_workspace / "dashboard" / "notifications.json"
    data = {
        "version": "1.0",
        "notifications": [notification] if isinstance(notification, dict) else notification,
    }
    notif_file.write_text(json.dumps(data), encoding="utf-8")


def _read_notifications(temp_workspace):
    """Helper to read notifications from the JSON file."""
    notif_file = temp_workspace / "dashboard" / "notifications.json"
    return json.loads(notif_file.read_text())


# ============================================================================
# TestScheduleNotificationGCal
# ============================================================================


class TestScheduleNotificationGCal:
    """Test schedule_notification with GCal and Telegram integration."""

    @pytest.mark.asyncio
    async def test_schedule_gcal_success(
        self, temp_workspace, mock_cron_service, mock_gcal_client, mock_send_callback
    ):
        """GCal create_event called, gcal_event_id saved, Telegram notified."""
        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
            send_callback=mock_send_callback,
            notification_chat_id="chat_123",
        )

        result = await tool.execute(message="Test GCal", scheduled_at="2026-02-25T10:00:00")

        assert "✅" in result
        mock_gcal_client.create_event.assert_called_once()

        # Verify gcal_event_id persisted
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["gcal_event_id"] == "gcal_evt_123"

        # Verify Telegram sent with "✅ 일정 추가"
        assert mock_send_callback.call_count >= 1
        telegram_msgs = [call.args[0].content for call in mock_send_callback.call_args_list]
        assert any("✅ 일정 추가" in m for m in telegram_msgs)

    @pytest.mark.asyncio
    async def test_schedule_gcal_failure_sends_telegram_error(
        self, temp_workspace, mock_cron_service, mock_gcal_client, mock_send_callback
    ):
        """GCal failure sends ⚠️ Telegram but notification is still saved."""
        mock_gcal_client.create_event.side_effect = Exception("API down")

        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
            send_callback=mock_send_callback,
            notification_chat_id="chat_123",
        )

        result = await tool.execute(message="Test fail", scheduled_at="2026-02-25T10:00:00")

        assert "✅" in result  # Tool result still success (notification saved)

        telegram_msgs = [call.args[0].content for call in mock_send_callback.call_args_list]
        assert any("⚠️" in m for m in telegram_msgs)

    @pytest.mark.asyncio
    async def test_schedule_gcal_failure_notification_still_saved(
        self, temp_workspace, mock_cron_service, mock_gcal_client
    ):
        """GCal failure: notification saved, cron created, gcal_event_id=None."""
        mock_gcal_client.create_event.side_effect = Exception("API down")

        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
        )

        result = await tool.execute(message="Test", scheduled_at="2026-02-25T10:00:00")

        assert "✅" in result
        data = _read_notifications(temp_workspace)
        notif = data["notifications"][0]
        assert notif["status"] == "pending"
        assert notif["gcal_event_id"] is None
        mock_cron_service.add_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_schedule_without_gcal_client(
        self, temp_workspace, mock_cron_service, mock_send_callback
    ):
        """gcal_client=None: GCal skipped, Telegram still sent."""
        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            send_callback=mock_send_callback,
            notification_chat_id="chat_123",
        )

        result = await tool.execute(message="No GCal", scheduled_at="2026-02-25T10:00:00")

        assert "✅" in result
        # Telegram should still be sent
        assert mock_send_callback.call_count >= 1
        telegram_msgs = [call.args[0].content for call in mock_send_callback.call_args_list]
        assert any("✅ 일정 추가" in m for m in telegram_msgs)

    @pytest.mark.asyncio
    async def test_schedule_without_send_callback(
        self, temp_workspace, mock_cron_service, mock_gcal_client
    ):
        """send_callback=None: Telegram skipped, GCal works."""
        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
        )

        result = await tool.execute(message="No Telegram", scheduled_at="2026-02-25T10:00:00")

        assert "✅" in result
        mock_gcal_client.create_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_schedule_gcal_with_context_data(
        self, temp_workspace, mock_cron_service, mock_gcal_client
    ):
        """Context and related_task_id reflected in GCal description."""
        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
        )

        await tool.execute(
            message="Deadline alert",
            scheduled_at="2026-02-25T10:00:00",
            context="Urgent deadline",
            related_task_id="task_001",
        )

        call_kwargs = mock_gcal_client.create_event.call_args
        desc = call_kwargs.kwargs.get("description") or call_kwargs[1].get("description")
        assert "Urgent deadline" in desc
        assert "task_001" in desc

    @pytest.mark.asyncio
    async def test_schedule_telegram_uses_chat_id_from_context(
        self, temp_workspace, mock_cron_service, mock_send_callback
    ):
        """set_context chat_id used in Telegram message."""
        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            send_callback=mock_send_callback,
            notification_chat_id="fallback_chat",
        )
        tool.set_context("telegram", "context_chat_456")

        await tool.execute(message="Test", scheduled_at="2026-02-25T10:00:00")

        # Should use context chat_id, not fallback
        msg = mock_send_callback.call_args_list[-1].args[0]
        assert msg.chat_id == "context_chat_456"

    @pytest.mark.asyncio
    async def test_schedule_telegram_falls_back_to_notification_chat_id(
        self, temp_workspace, mock_cron_service, mock_send_callback
    ):
        """Without set_context, falls back to notification_chat_id."""
        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            send_callback=mock_send_callback,
            notification_chat_id="fallback_chat_789",
        )
        # No set_context called

        await tool.execute(message="Fallback test", scheduled_at="2026-02-25T10:00:00")

        msg = mock_send_callback.call_args_list[-1].args[0]
        assert msg.chat_id == "fallback_chat_789"


# ============================================================================
# TestUpdateNotificationGCal
# ============================================================================


class TestUpdateNotificationGCal:
    """Test update_notification with GCal and Telegram integration."""

    def _make_notification(self, gcal_event_id=None):
        return {
            "id": "n_001",
            "message": "Old message",
            "scheduled_at": "2026-02-25T10:00:00",
            "type": "reminder",
            "priority": "medium",
            "status": "pending",
            "cron_job_id": "cron_001",
            "created_at": "2026-02-23T10:00:00",
            "created_by": "worker",
            "gcal_event_id": gcal_event_id,
        }

    @pytest.mark.asyncio
    async def test_update_gcal_existing_event(
        self, temp_workspace, mock_cron_service, mock_gcal_client, mock_send_callback
    ):
        """Existing gcal_event_id -> update_event called."""
        _create_notification(temp_workspace, self._make_notification("gcal_evt_100"))

        tool = UpdateNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
            send_callback=mock_send_callback,
            notification_chat_id="chat_123",
        )

        result = await tool.execute(notification_id="n_001", message="New message")

        assert "✅" in result
        mock_gcal_client.update_event.assert_called_once()
        call_kwargs = mock_gcal_client.update_event.call_args.kwargs
        assert call_kwargs["event_id"] == "gcal_evt_100"
        assert call_kwargs["summary"] == "New message"

    @pytest.mark.asyncio
    async def test_update_gcal_creates_new_when_no_id(
        self, temp_workspace, mock_cron_service, mock_gcal_client
    ):
        """No gcal_event_id -> create_event called, new ID saved."""
        _create_notification(temp_workspace, self._make_notification(None))

        tool = UpdateNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
        )

        await tool.execute(notification_id="n_001", message="Updated")

        mock_gcal_client.create_event.assert_called_once()
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["gcal_event_id"] == "gcal_evt_123"

    @pytest.mark.asyncio
    async def test_update_gcal_failure_sends_telegram_error(
        self, temp_workspace, mock_cron_service, mock_gcal_client, mock_send_callback
    ):
        """GCal failure sends ⚠️ Telegram, notification data already saved."""
        mock_gcal_client.update_event.side_effect = Exception("GCal down")
        _create_notification(temp_workspace, self._make_notification("gcal_evt_100"))

        tool = UpdateNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
            send_callback=mock_send_callback,
            notification_chat_id="chat_123",
        )

        result = await tool.execute(notification_id="n_001", message="Updated")

        assert "✅" in result  # notification update succeeded
        telegram_msgs = [call.args[0].content for call in mock_send_callback.call_args_list]
        assert any("⚠️" in m for m in telegram_msgs)

    @pytest.mark.asyncio
    async def test_update_gcal_success_sends_telegram(
        self, temp_workspace, mock_cron_service, mock_gcal_client, mock_send_callback
    ):
        """Successful update sends ✅ Telegram."""
        _create_notification(temp_workspace, self._make_notification("gcal_evt_100"))

        tool = UpdateNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
            send_callback=mock_send_callback,
            notification_chat_id="chat_123",
        )

        await tool.execute(notification_id="n_001", message="Updated")

        telegram_msgs = [call.args[0].content for call in mock_send_callback.call_args_list]
        assert any("✅ 일정 수정" in m for m in telegram_msgs)

    @pytest.mark.asyncio
    async def test_update_without_gcal_client(self, temp_workspace, mock_cron_service):
        """gcal_client=None: GCal skipped entirely."""
        _create_notification(temp_workspace, self._make_notification("gcal_evt_100"))

        tool = UpdateNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_001", message="Updated")

        assert "✅" in result

    @pytest.mark.asyncio
    async def test_update_message_only_no_gcal_reschedule(
        self, temp_workspace, mock_cron_service, mock_gcal_client
    ):
        """Message-only update: GCal update_event called with summary only, no start_iso."""
        _create_notification(temp_workspace, self._make_notification("gcal_evt_100"))

        tool = UpdateNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
        )

        await tool.execute(notification_id="n_001", message="New msg only")

        call_kwargs = mock_gcal_client.update_event.call_args.kwargs
        assert call_kwargs["summary"] == "New msg only"
        assert call_kwargs["start_iso"] is None  # No reschedule

    @pytest.mark.asyncio
    async def test_update_scheduled_at_changes_gcal_time(
        self, temp_workspace, mock_cron_service, mock_gcal_client
    ):
        """Changing scheduled_at passes new start_iso to GCal."""
        _create_notification(temp_workspace, self._make_notification("gcal_evt_100"))

        tool = UpdateNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
        )

        await tool.execute(
            notification_id="n_001",
            scheduled_at="2026-02-26T15:00:00",
        )

        call_kwargs = mock_gcal_client.update_event.call_args.kwargs
        assert call_kwargs["start_iso"] == "2026-02-26T15:00:00"


# ============================================================================
# TestCancelNotificationGCal
# ============================================================================


class TestCancelNotificationGCal:
    """Test cancel_notification with GCal and Telegram integration."""

    def _make_notification(self, gcal_event_id=None):
        return {
            "id": "n_001",
            "message": "To cancel",
            "scheduled_at": "2026-02-25T10:00:00",
            "type": "reminder",
            "priority": "medium",
            "status": "pending",
            "cron_job_id": "cron_001",
            "created_at": "2026-02-23T10:00:00",
            "created_by": "worker",
            "gcal_event_id": gcal_event_id,
        }

    @pytest.mark.asyncio
    async def test_cancel_gcal_delete_success(
        self, temp_workspace, mock_cron_service, mock_gcal_client, mock_send_callback
    ):
        """With gcal_event_id: delete_event called, ✅ Telegram sent."""
        _create_notification(temp_workspace, self._make_notification("gcal_evt_200"))

        tool = CancelNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
            send_callback=mock_send_callback,
            notification_chat_id="chat_123",
        )
        tool.set_context("telegram", "chat_123")

        result = await tool.execute(notification_id="n_001")

        assert "✅" in result
        mock_gcal_client.delete_event.assert_called_once()

        telegram_msgs = [call.args[0].content for call in mock_send_callback.call_args_list]
        assert any("✅ 일정 취소" in m for m in telegram_msgs)

    @pytest.mark.asyncio
    async def test_cancel_gcal_delete_failure(
        self, temp_workspace, mock_cron_service, mock_gcal_client, mock_send_callback
    ):
        """GCal delete fails: ⚠️ Telegram, notification still cancelled."""
        mock_gcal_client.delete_event.side_effect = Exception("API error")
        _create_notification(temp_workspace, self._make_notification("gcal_evt_200"))

        tool = CancelNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
            send_callback=mock_send_callback,
            notification_chat_id="chat_123",
        )
        tool.set_context("telegram", "chat_123")

        result = await tool.execute(notification_id="n_001")

        assert "✅" in result
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["status"] == "cancelled"

        telegram_msgs = [call.args[0].content for call in mock_send_callback.call_args_list]
        assert any("⚠️" in m for m in telegram_msgs)

    @pytest.mark.asyncio
    async def test_cancel_no_gcal_event_id(
        self, temp_workspace, mock_cron_service, mock_gcal_client, mock_send_callback
    ):
        """gcal_event_id=None: delete_event NOT called, ✅ Telegram sent."""
        _create_notification(temp_workspace, self._make_notification(None))

        tool = CancelNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
            send_callback=mock_send_callback,
            notification_chat_id="chat_123",
        )
        tool.set_context("telegram", "chat_123")

        result = await tool.execute(notification_id="n_001")

        assert "✅" in result
        mock_gcal_client.delete_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_without_gcal_client(self, temp_workspace, mock_cron_service):
        """gcal_client=None: GCal logic skipped."""
        _create_notification(temp_workspace, self._make_notification("gcal_evt_200"))

        tool = CancelNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_001")

        assert "✅" in result

    @pytest.mark.asyncio
    async def test_cancel_set_context(self, temp_workspace, mock_cron_service, mock_send_callback):
        """CancelNotificationTool.set_context() works correctly."""
        _create_notification(temp_workspace, self._make_notification(None))

        tool = CancelNotificationTool(
            temp_workspace,
            mock_cron_service,
            send_callback=mock_send_callback,
            notification_chat_id="fallback_chat",
        )
        tool.set_context("telegram", "specific_chat_999")

        await tool.execute(notification_id="n_001")

        msg = mock_send_callback.call_args_list[-1].args[0]
        assert msg.chat_id == "specific_chat_999"

    @pytest.mark.asyncio
    async def test_cancel_without_send_callback(
        self, temp_workspace, mock_cron_service, mock_gcal_client
    ):
        """send_callback=None: Telegram skipped, GCal delete works."""
        _create_notification(temp_workspace, self._make_notification("gcal_evt_200"))

        tool = CancelNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
        )

        result = await tool.execute(notification_id="n_001")

        assert "✅" in result
        mock_gcal_client.delete_event.assert_called_once()


# ============================================================================
# TestBackwardCompatibility
# ============================================================================


class TestBackwardCompatibility:
    """Ensure existing code still works with new optional parameters."""

    @pytest.mark.asyncio
    async def test_schedule_tool_no_new_params(self, temp_workspace, mock_cron_service):
        """Old-style ScheduleNotificationTool(workspace, cron_service) works."""
        tool = ScheduleNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(
            message="Backward compat",
            scheduled_at="2026-02-25T10:00:00",
        )

        assert "✅" in result

    @pytest.mark.asyncio
    async def test_update_tool_no_new_params(self, temp_workspace, mock_cron_service):
        """Old-style UpdateNotificationTool(workspace, cron_service) works."""
        _create_notification(
            temp_workspace,
            {
                "id": "n_001",
                "message": "Test",
                "scheduled_at": "2026-02-25T10:00:00",
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
                "cron_job_id": "cron_001",
                "created_at": "2026-02-23T10:00:00",
                "created_by": "worker",
            },
        )

        tool = UpdateNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_001", message="Updated")

        assert "✅" in result

    @pytest.mark.asyncio
    async def test_cancel_tool_no_new_params(self, temp_workspace, mock_cron_service):
        """Old-style CancelNotificationTool(workspace, cron_service) works."""
        _create_notification(
            temp_workspace,
            {
                "id": "n_001",
                "message": "Test",
                "scheduled_at": "2026-02-25T10:00:00",
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
                "cron_job_id": "cron_001",
                "created_at": "2026-02-23T10:00:00",
                "created_by": "worker",
            },
        )

        tool = CancelNotificationTool(temp_workspace, mock_cron_service)

        result = await tool.execute(notification_id="n_001")

        assert "✅" in result

    @pytest.mark.asyncio
    async def test_existing_notification_without_gcal_event_id(
        self, temp_workspace, mock_cron_service, mock_gcal_client
    ):
        """Existing notification data without gcal_event_id loads fine."""
        _create_notification(
            temp_workspace,
            {
                "id": "n_old",
                "message": "Old notification",
                "scheduled_at": "2026-02-25T10:00:00",
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
                "cron_job_id": "cron_old",
                "created_at": "2026-02-23T10:00:00",
                "created_by": "worker",
                # No gcal_event_id field at all
            },
        )

        tool = UpdateNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
        )

        result = await tool.execute(notification_id="n_old", message="Updated old")

        assert "✅" in result
        # Should create new GCal event since no gcal_event_id
        mock_gcal_client.create_event.assert_called_once()


# ============================================================================
# TestSendTelegramHelper
# ============================================================================


class TestSendTelegramHelper:
    """Test the _send_telegram helper method."""

    @pytest.mark.asyncio
    async def test_send_telegram_with_context_chat_id(
        self, temp_workspace, mock_cron_service, mock_send_callback
    ):
        """_chat_id set -> uses _chat_id."""
        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            send_callback=mock_send_callback,
            notification_chat_id="fallback",
        )
        tool._chat_id = "context_chat"
        tool._channel = "telegram"

        await tool._send_telegram("Test msg")

        msg = mock_send_callback.call_args.args[0]
        assert msg.chat_id == "context_chat"

    @pytest.mark.asyncio
    async def test_send_telegram_fallback_notification_chat_id(
        self, temp_workspace, mock_cron_service, mock_send_callback
    ):
        """_chat_id=None -> falls back to notification_chat_id."""
        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            send_callback=mock_send_callback,
            notification_chat_id="fallback_chat",
        )
        # _chat_id is None by default

        await tool._send_telegram("Test msg")

        msg = mock_send_callback.call_args.args[0]
        assert msg.chat_id == "fallback_chat"

    @pytest.mark.asyncio
    async def test_send_telegram_no_chat_id_no_send(
        self, temp_workspace, mock_cron_service, mock_send_callback
    ):
        """Both chat IDs None -> send_callback NOT called."""
        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            send_callback=mock_send_callback,
        )

        await tool._send_telegram("Test msg")

        mock_send_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_telegram_callback_error_caught(self, temp_workspace, mock_cron_service):
        """send_callback exception is caught (warning logged, no crash)."""
        failing_callback = AsyncMock(side_effect=Exception("Network error"))

        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            send_callback=failing_callback,
            notification_chat_id="chat_123",
        )

        # Should not raise
        await tool._send_telegram("Test msg")

        failing_callback.assert_called_once()


# ============================================================================
# TestSecondSaveFailure
# ============================================================================


class TestSecondSaveFailure:
    """Test that second save failure (gcal_event_id persist) logs warning."""

    @pytest.mark.asyncio
    async def test_schedule_second_save_failure_logs_warning(
        self, temp_workspace, mock_cron_service, mock_gcal_client
    ):
        """GCal succeeds but second save fails: warning logged, tool still succeeds."""
        tool = ScheduleNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
        )

        # First save succeeds, second save fails
        original_validate = tool._validate_and_save_notifications
        call_count = 0

        async def patched_validate(data):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return (False, "Storage write error")
            return await original_validate(data)

        tool._validate_and_save_notifications = patched_validate

        result = await tool.execute(message="Test save fail", scheduled_at="2026-02-25T10:00:00")

        assert "✅" in result  # Tool still reports success
        mock_gcal_client.create_event.assert_called_once()
        # gcal_event_id NOT persisted due to second save failure
        data = _read_notifications(temp_workspace)
        assert data["notifications"][0]["gcal_event_id"] is None

    @pytest.mark.asyncio
    async def test_update_second_save_failure_logs_warning(
        self, temp_workspace, mock_cron_service, mock_gcal_client
    ):
        """Update: GCal create succeeds but gcal_event_id save fails."""
        _create_notification(
            temp_workspace,
            {
                "id": "n_001",
                "message": "Test",
                "scheduled_at": "2026-02-25T10:00:00",
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
                "cron_job_id": "cron_001",
                "created_at": "2026-02-23T10:00:00",
                "created_by": "worker",
                "gcal_event_id": None,
            },
        )

        tool = UpdateNotificationTool(
            temp_workspace,
            mock_cron_service,
            gcal_client=mock_gcal_client,
        )

        # First save succeeds, second save (gcal_event_id) fails
        original_validate = tool._validate_and_save_notifications
        call_count = 0

        async def patched_validate(data):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return (False, "Storage write error")
            return await original_validate(data)

        tool._validate_and_save_notifications = patched_validate

        result = await tool.execute(notification_id="n_001", message="Updated")

        assert "✅" in result
        mock_gcal_client.create_event.assert_called_once()
