"""Cancel notification tool."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock
from nanobot.cron.service import CronService

if TYPE_CHECKING:
    from nanobot.bus.events import OutboundMessage
    from nanobot.google.calendar import GoogleCalendarClient


class CancelNotificationTool(BaseDashboardTool):
    """Cancel a scheduled notification."""

    def __init__(
        self,
        workspace: Path,
        cron_service: CronService,
        gcal_client: "GoogleCalendarClient | None" = None,
        send_callback: Callable[["OutboundMessage"], Awaitable[None]] | None = None,
        notification_chat_id: str | None = None,
        gcal_timezone: str = "Asia/Seoul",
        gcal_duration_minutes: int = 30,
    ):
        super().__init__(workspace)
        self.cron_service = cron_service
        self._gcal_client = gcal_client
        self._send_callback = send_callback
        self._notification_chat_id = notification_chat_id
        # gcal_timezone/gcal_duration_minutes accepted for signature parity
        # with Schedule/Update tools but unused by cancel operations.
        self._channel: str | None = None
        self._chat_id: str | None = None

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current channel and chat_id for notification delivery."""
        self._channel = channel
        self._chat_id = chat_id

    async def _send_telegram(self, content: str) -> None:
        """Send an instant notification via bus callback (uses current channel, falls back to telegram)."""
        if not self._send_callback:
            return
        chat_id = self._chat_id or self._notification_chat_id
        if not chat_id:
            return
        from nanobot.bus.events import OutboundMessage

        msg = OutboundMessage(channel=self._channel or "telegram", chat_id=chat_id, content=content)
        try:
            await self._send_callback(msg)
        except Exception as e:
            logger.warning(f"Failed to send Telegram notification: {e}")

    @property
    def name(self) -> str:
        return "cancel_notification"

    @property
    def description(self) -> str:
        return (
            "Cancel a scheduled notification. "
            "Removes the associated cron job and marks the notification as cancelled."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notification_id": {
                    "type": "string",
                    "description": "ID of the notification to cancel",
                },
                "reason": {
                    "type": "string",
                    "default": "",
                    "description": "Optional reason for cancellation",
                },
            },
            "required": ["notification_id"],
        }

    @with_dashboard_lock
    async def execute(self, notification_id: str, reason: str = "") -> str:
        """Cancel a notification."""
        try:
            # Load notifications
            notifications_data = await self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            # Find notification
            notification, index = self._find_notification(notifications_list, notification_id)
            if not notification:
                return f"Error: Notification '{notification_id}' not found"

            # Check if already cancelled
            if notification.get("status") == "cancelled":
                return f"Notification '{notification_id}' is already cancelled"

            # Check if already delivered
            if notification.get("status") == "delivered":
                return f"Error: Cannot cancel delivered notification '{notification_id}'"

            # Update notification status
            cron_job_id = notification.get("cron_job_id")
            gcal_event_id = notification.get("gcal_event_id")
            notification["status"] = "cancelled"
            notification["cancelled_at"] = self._now()
            if reason:
                notification["context"] = (
                    f"{notification.get('context', '')}\nCancellation reason: {reason}".strip()
                )

            # DESIGN: Save storage FIRST, then remove cron (storage-first commit).
            notifications_list[index] = notification
            notifications_data["notifications"] = notifications_list

            success, msg = await self._validate_and_save_notifications(notifications_data)
            if not success:
                return msg

            # Now remove cron job (safe: storage already committed)
            if cron_job_id:
                try:
                    removed = self.cron_service.remove_job(cron_job_id)
                    if not removed:
                        logger.warning(
                            f"Cron job {cron_job_id} not found during cancellation "
                            f"of notification {notification_id}"
                        )
                except Exception as cron_err:
                    logger.warning(
                        f"Notification {notification_id} cancelled in storage, "
                        f"but cron removal failed: {cron_err}"
                    )
                    return (
                        f"⚠️ Notification '{notification_id}' cancelled, "
                        f"but cron job cleanup failed (will be ignored on next run)."
                    )

            # Google Calendar sync (best-effort, after cron removal)
            if self._gcal_client and gcal_event_id:
                try:
                    await asyncio.to_thread(self._gcal_client.delete_event, event_id=gcal_event_id)
                except Exception as e:
                    logger.warning(f"GCal sync failed (cancel): {e}")
                    await self._send_telegram(f"⚠️ Google Calendar 동기화 실패 (cancel): {e}")

            # Send instant Telegram notification
            await self._send_telegram(f"✅ 일정 취소: {notification_id}")

            return f"✅ Notification '{notification_id}' cancelled successfully"

        except Exception as e:
            return f"Error cancelling notification: {str(e)}"
