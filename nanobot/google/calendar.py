"""Google Calendar client for notification sync.

Sync I/O (same pattern as NotionClient). Callers wrap with asyncio.to_thread().
Lazy imports — graceful error when google libraries are not installed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger


class GoogleCalendarError(Exception):
    """Raised on any Google Calendar API failure."""


class GoogleCalendarClient:
    """Thin wrapper around Google Calendar API v3."""

    def __init__(
        self,
        client_secret_path: str,
        token_path: str,
        calendar_id: str = "primary",
    ):
        self._client_secret_path = Path(client_secret_path).expanduser()
        self._token_path = Path(token_path).expanduser()
        self._calendar_id = calendar_id
        self._service = None

    def _get_service(self):
        """Build or return cached Calendar service (lazy, sync)."""
        if self._service is not None:
            return self._service

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            raise GoogleCalendarError(
                "Google Calendar libraries not installed. "
                "Install with: pip install nanobot-ai[google]"
            )

        scopes = ["https://www.googleapis.com/auth/calendar"]
        creds = None

        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self._token_path), scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self._client_secret_path.exists():
                    raise GoogleCalendarError(
                        f"Client secret file not found: {self._client_secret_path}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._client_secret_path), scopes
                )
                creds = flow.run_local_server(port=0)

            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(creds.to_json())

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def create_event(
        self,
        summary: str,
        start_iso: str,
        timezone: str = "Asia/Seoul",
        duration_minutes: int = 30,
        description: str | None = None,
    ) -> str:
        """Create a calendar event. Returns the event ID."""
        try:
            service = self._get_service()
            start_dt = datetime.fromisoformat(start_iso)
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            body: dict = {
                "summary": summary,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
            }
            if description:
                body["description"] = description

            event = service.events().insert(calendarId=self._calendar_id, body=body).execute()
            event_id = event.get("id", "")
            logger.debug(f"GCal event created: {event_id}")
            return event_id
        except GoogleCalendarError:
            raise
        except Exception as e:
            raise GoogleCalendarError(f"Failed to create event: {e}") from e

    def update_event(
        self,
        event_id: str,
        summary: str | None = None,
        start_iso: str | None = None,
        timezone: str = "Asia/Seoul",
        duration_minutes: int = 30,
        description: str | None = None,
    ) -> None:
        """Update an existing calendar event."""
        try:
            service = self._get_service()
            event = service.events().get(calendarId=self._calendar_id, eventId=event_id).execute()

            if summary is not None:
                event["summary"] = summary
            if start_iso is not None:
                start_dt = datetime.fromisoformat(start_iso)
                end_dt = start_dt + timedelta(minutes=duration_minutes)
                event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": timezone}
                event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": timezone}
            if description is not None:
                event["description"] = description

            service.events().update(
                calendarId=self._calendar_id, eventId=event_id, body=event
            ).execute()
            logger.debug(f"GCal event updated: {event_id}")
        except GoogleCalendarError:
            raise
        except Exception as e:
            raise GoogleCalendarError(f"Failed to update event: {e}") from e

    def delete_event(self, event_id: str) -> None:
        """Delete a calendar event."""
        try:
            service = self._get_service()
            service.events().delete(calendarId=self._calendar_id, eventId=event_id).execute()
            logger.debug(f"GCal event deleted: {event_id}")
        except GoogleCalendarError:
            raise
        except Exception as e:
            raise GoogleCalendarError(f"Failed to delete event: {e}") from e

    def close(self) -> None:
        """Close the underlying HTTP transport."""
        if self._service:
            try:
                self._service.close()
            except Exception as e:
                logger.warning(f"Error closing Calendar service: {e}")
            self._service = None
