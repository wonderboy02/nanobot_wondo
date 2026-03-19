"""Unit tests for GoogleCalendarClient (nanobot/google/calendar.py).

All Google API calls are mocked — no real API key needed.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

from nanobot.google.calendar import GoogleCalendarClient, GoogleCalendarError


@pytest.fixture
def mock_service():
    """Mock Google Calendar API service."""
    service = MagicMock()
    return service


@pytest.fixture
def client(mock_service, tmp_path):
    """GoogleCalendarClient with pre-injected mock service."""
    c = GoogleCalendarClient(
        client_secret_path=str(tmp_path / "client_secret.json"),
        token_path=str(tmp_path / "token.json"),
        calendar_id="primary",
    )
    c._service = mock_service
    return c


class TestGoogleCalendarClient:
    """Test GoogleCalendarClient operations."""

    def test_create_event_success(self, client, mock_service):
        """create_event calls events().insert() and returns event_id."""
        mock_service.events().insert().execute.return_value = {"id": "evt_123"}

        result = client.create_event(
            summary="Test event",
            start_iso="2026-02-23T10:00:00",
            timezone="Asia/Seoul",
            duration_minutes=30,
        )

        assert result == "evt_123"
        mock_service.events().insert.assert_called()

    def test_create_event_builds_correct_body(self, client, mock_service):
        """create_event constructs the correct event body."""
        mock_service.events().insert().execute.return_value = {"id": "evt_456"}

        client.create_event(
            summary="Meeting",
            start_iso="2026-03-01T14:00:00",
            timezone="Asia/Seoul",
            duration_minutes=60,
            description="Team standup",
        )

        call_args = mock_service.events().insert.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        assert body["summary"] == "Meeting"
        assert body["description"] == "Team standup"
        assert body["start"]["timeZone"] == "Asia/Seoul"
        assert body["end"]["timeZone"] == "Asia/Seoul"
        # Verify duration: end = start + 60 min
        start_dt = datetime.fromisoformat(body["start"]["dateTime"])
        end_dt = datetime.fromisoformat(body["end"]["dateTime"])
        assert (end_dt - start_dt) == timedelta(minutes=60)

    def test_create_event_duration_calculation(self, client, mock_service):
        """Default 30-minute duration: end = start + 30min."""
        mock_service.events().insert().execute.return_value = {"id": "evt_789"}

        client.create_event(
            summary="Quick check",
            start_iso="2026-02-23T09:00:00",
        )

        call_args = mock_service.events().insert.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        start_dt = datetime.fromisoformat(body["start"]["dateTime"])
        end_dt = datetime.fromisoformat(body["end"]["dateTime"])
        assert (end_dt - start_dt) == timedelta(minutes=30)

    def test_update_event_success(self, client, mock_service):
        """update_event calls events().get() then events().update()."""
        mock_service.events().get().execute.return_value = {
            "id": "evt_123",
            "summary": "Old title",
            "start": {"dateTime": "2026-02-23T10:00:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-02-23T10:30:00", "timeZone": "Asia/Seoul"},
        }
        mock_service.events().update().execute.return_value = {}

        client.update_event(
            event_id="evt_123",
            summary="New title",
        )

        mock_service.events().get.assert_called()
        mock_service.events().update.assert_called()

    def test_update_event_partial_fields(self, client, mock_service):
        """Updating only summary preserves start/end times."""
        original_event = {
            "id": "evt_123",
            "summary": "Old title",
            "start": {"dateTime": "2026-02-23T10:00:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-02-23T10:30:00", "timeZone": "Asia/Seoul"},
        }
        mock_service.events().get().execute.return_value = original_event.copy()
        mock_service.events().update().execute.return_value = {}

        client.update_event(event_id="evt_123", summary="Updated title")

        call_args = mock_service.events().update.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        assert body["summary"] == "Updated title"
        # start/end should remain unchanged
        assert body["start"]["dateTime"] == "2026-02-23T10:00:00"
        assert body["end"]["dateTime"] == "2026-02-23T10:30:00"

    def test_delete_event_success(self, client, mock_service):
        """delete_event calls events().delete().execute()."""
        mock_service.events().delete().execute.return_value = None

        client.delete_event(event_id="evt_123")

        mock_service.events().delete.assert_called()

    def test_api_error_raises_gcal_error(self, client, mock_service):
        """API exception is wrapped in GoogleCalendarError."""
        mock_service.events().insert().execute.side_effect = Exception("API failure")

        with pytest.raises(GoogleCalendarError, match="Failed to create event"):
            client.create_event(
                summary="Test",
                start_iso="2026-02-23T10:00:00",
            )

    def test_create_all_day_event(self, client, mock_service):
        """create_event with all_day_date creates an all-day event."""
        mock_service.events().insert().execute.return_value = {"id": "evt_allday"}

        result = client.create_event(
            summary="Task deadline",
            all_day_date="2026-03-15",
        )

        assert result == "evt_allday"
        call_args = mock_service.events().insert.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        assert body["start"] == {"date": "2026-03-15"}
        assert body["end"] == {"date": "2026-03-16"}
        assert "dateTime" not in body["start"]
        assert "dateTime" not in body["end"]

    def test_create_all_day_overrides_start_iso(self, client, mock_service):
        """all_day_date takes priority over start_iso when both provided."""
        mock_service.events().insert().execute.return_value = {"id": "evt_override"}

        client.create_event(
            summary="Override test",
            start_iso="2026-03-15T10:00:00",
            all_day_date="2026-03-15",
        )

        call_args = mock_service.events().insert.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        assert "date" in body["start"]
        assert "dateTime" not in body["start"]

    def test_update_all_day_event(self, client, mock_service):
        """update_event with all_day_date converts to all-day format."""
        mock_service.events().get().execute.return_value = {
            "id": "evt_123",
            "summary": "Old title",
            "start": {"dateTime": "2026-02-23T10:00:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-02-23T10:30:00", "timeZone": "Asia/Seoul"},
        }
        mock_service.events().update().execute.return_value = {}

        client.update_event(
            event_id="evt_123",
            summary="Updated deadline",
            all_day_date="2026-03-20",
        )

        call_args = mock_service.events().update.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        assert body["start"] == {"date": "2026-03-20"}
        assert body["end"] == {"date": "2026-03-21"}
        assert body["summary"] == "Updated deadline"

    def test_create_no_start_iso_no_all_day_raises(self, client, mock_service):
        """Neither start_iso nor all_day_date → GoogleCalendarError."""
        with pytest.raises(GoogleCalendarError, match="Either start_iso or all_day_date"):
            client.create_event(summary="No time")

    def test_import_error_raises_gcal_error(self, tmp_path):
        """Missing google libraries raises GoogleCalendarError."""
        c = GoogleCalendarClient(
            client_secret_path=str(tmp_path / "secret.json"),
            token_path=str(tmp_path / "token.json"),
        )
        # Force _service to None so _get_service() is called
        c._service = None

        with patch.dict(
            "sys.modules",
            {
                "google.auth.transport.requests": None,
                "google.oauth2.credentials": None,
                "google_auth_oauthlib.flow": None,
                "googleapiclient.discovery": None,
            },
        ):
            with pytest.raises(GoogleCalendarError, match="not installed"):
                c._get_service()
