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
from nanobot.dashboard.storage import SaveResult


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
                return SaveResult(False, "Storage write error")
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
                return SaveResult(False, "Storage write error")
            return await original_validate(data)

        tool._validate_and_save_notifications = patched_validate

        result = await tool.execute(notification_id="n_001", message="Updated")

        assert "✅" in result
        mock_gcal_client.create_event.assert_called_once()


# ============================================================================
# TestDeliveryGCalCleanup — delete_gcal_event_on_delivery() unit tests
# ============================================================================


class TestDeliveryGCalCleanup:
    """Unit tests for the delete_gcal_event_on_delivery() helper."""

    @pytest.mark.asyncio
    async def test_delivery_gcal_delete_success(self, mock_gcal_client):
        """Delivery triggers delete_event with correct gcal_event_id."""
        from nanobot.cli.commands import delete_gcal_event_on_delivery

        await delete_gcal_event_on_delivery(mock_gcal_client, "gcal_evt_del_100")

        mock_gcal_client.delete_event.assert_called_once_with(event_id="gcal_evt_del_100")

    @pytest.mark.asyncio
    async def test_delivery_gcal_delete_failure(self, mock_gcal_client):
        """GCal delete failure does not raise (best-effort)."""
        from nanobot.cli.commands import delete_gcal_event_on_delivery

        mock_gcal_client.delete_event.side_effect = Exception("GCal API down")

        # Should not raise (best-effort)
        await delete_gcal_event_on_delivery(mock_gcal_client, "gcal_evt_del_200")

        # delete_event was attempted
        mock_gcal_client.delete_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_delivery_no_gcal_event_id(self, mock_gcal_client):
        """No gcal_event_id -> delete_event NOT called."""
        from nanobot.cli.commands import delete_gcal_event_on_delivery

        await delete_gcal_event_on_delivery(mock_gcal_client, None)

        mock_gcal_client.delete_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_delivery_no_gcal_client(self):
        """gcal_client=None -> no error, delete_event NOT called."""
        from nanobot.cli.commands import delete_gcal_event_on_delivery

        # Should not raise even with None client
        await delete_gcal_event_on_delivery(None, "gcal_evt_del_300")


# ============================================================================
# TestClaimNotificationDelivered — claim_notification_delivered() unit tests
# ============================================================================


class TestClaimNotificationDelivered:
    """Unit tests for claim_notification_delivered().

    This function is the extracted core of on_cron_job's delivery path,
    covering: target lookup, TOCTOU status re-check, delivered marking,
    save, and gcal_event_id extraction.
    """

    @staticmethod
    def _make_notif_data(*notifs):
        return {"version": "1.0", "notifications": list(notifs)}

    @staticmethod
    def _make_notif(notif_id="n_001", status="pending", gcal_event_id=None):
        return {
            "id": notif_id,
            "message": "Test notification",
            "scheduled_at": "2026-02-25T10:00:00",
            "type": "reminder",
            "priority": "medium",
            "status": status,
            "gcal_event_id": gcal_event_id,
        }

    @pytest.mark.asyncio
    async def test_claim_success_marks_delivered(self):
        """Pending notification → delivered, suppress_publish=False."""
        from nanobot.cli.commands import claim_notification_delivered

        data = self._make_notif_data(self._make_notif(gcal_event_id="gcal_100"))
        save_called_with = {}

        async def load_fn():
            return data

        async def save_fn(d):
            save_called_with["data"] = d
            return True

        ok, gcal_id, suppress = await claim_notification_delivered("n_001", load_fn, save_fn)

        assert ok is True
        assert gcal_id == "gcal_100"
        assert suppress is False
        saved_notif = save_called_with["data"]["notifications"][0]
        assert saved_notif["status"] == "delivered"
        assert "delivered_at" in saved_notif

    @pytest.mark.asyncio
    async def test_claim_target_not_found(self):
        """Notification not in data (but others exist) → suppress_publish=True, no save."""
        from nanobot.cli.commands import claim_notification_delivered

        data = self._make_notif_data(self._make_notif(notif_id="n_other"))  # different ID
        save_called = False

        async def load_fn():
            return data

        async def save_fn(d):
            nonlocal save_called
            save_called = True
            return True

        ok, gcal_id, suppress = await claim_notification_delivered("n_missing", load_fn, save_fn)

        assert ok is False
        assert gcal_id is None
        assert suppress is True
        assert save_called is False

    @pytest.mark.asyncio
    async def test_claim_already_cancelled(self):
        """Cancelled notification → suppress_publish=True, not overwritten."""
        from nanobot.cli.commands import claim_notification_delivered

        data = self._make_notif_data(self._make_notif(status="cancelled"))
        save_called = False

        async def load_fn():
            return data

        async def save_fn(d):
            nonlocal save_called
            save_called = True
            return True

        ok, gcal_id, suppress = await claim_notification_delivered("n_001", load_fn, save_fn)

        assert ok is False
        assert gcal_id is None
        assert suppress is True
        assert save_called is False
        assert data["notifications"][0]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_claim_already_delivered(self):
        """Already delivered → suppress_publish=True, idempotent."""
        from nanobot.cli.commands import claim_notification_delivered

        data = self._make_notif_data(self._make_notif(status="delivered"))

        async def load_fn():
            return data

        async def save_fn(d):
            return True

        ok, gcal_id, suppress = await claim_notification_delivered("n_001", load_fn, save_fn)

        assert ok is False
        assert gcal_id is None
        assert suppress is True

    @pytest.mark.asyncio
    async def test_claim_save_failure_still_publishes(self):
        """Save fails → suppress_publish=False (transient, still publish)."""
        from nanobot.cli.commands import claim_notification_delivered

        data = self._make_notif_data(self._make_notif())

        async def load_fn():
            return data

        async def save_fn(d):
            return False

        ok, gcal_id, suppress = await claim_notification_delivered("n_001", load_fn, save_fn)

        assert ok is False
        assert gcal_id is None
        assert suppress is False  # transient failure, still publish

    @pytest.mark.asyncio
    async def test_claim_load_exception_still_publishes(self):
        """Load raises → suppress_publish=False (transient, still publish)."""
        from nanobot.cli.commands import claim_notification_delivered

        async def load_fn():
            raise RuntimeError("Storage unavailable")

        async def save_fn(d):
            return True

        ok, gcal_id, suppress = await claim_notification_delivered("n_001", load_fn, save_fn)

        assert ok is False
        assert gcal_id is None
        assert suppress is False  # transient failure, still publish

    @pytest.mark.asyncio
    async def test_claim_missing_notifications_key(self):
        """Storage returns data without 'notifications' key → transient, still publish."""
        from nanobot.cli.commands import claim_notification_delivered

        async def load_fn():
            return {}  # no "notifications" key — possible storage anomaly

        async def save_fn(d):
            return True

        ok, gcal_id, suppress = await claim_notification_delivered("n_001", load_fn, save_fn)

        assert ok is False
        assert gcal_id is None
        assert suppress is False  # transient — don't suppress publish

    @pytest.mark.asyncio
    async def test_claim_empty_notifications_list(self):
        """Empty notifications list during delivery → transient, still publish.

        JsonStorageBackend returns default {"notifications": []} on parse error.
        An empty list is suspicious at delivery time since cancel_notification
        only changes status (doesn't remove entries).
        """
        from nanobot.cli.commands import claim_notification_delivered

        async def load_fn():
            return {"version": "1.0", "notifications": []}  # default from corrupted file

        async def save_fn(d):
            return True

        ok, gcal_id, suppress = await claim_notification_delivered("n_001", load_fn, save_fn)

        assert ok is False
        assert gcal_id is None
        assert suppress is False  # transient — don't suppress publish
