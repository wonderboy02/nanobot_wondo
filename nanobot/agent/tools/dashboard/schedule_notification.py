"""Schedule notification tool."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from loguru import logger

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule

if TYPE_CHECKING:
    from nanobot.bus.events import OutboundMessage
    from nanobot.google.calendar import GoogleCalendarClient


class ScheduleNotificationTool(BaseDashboardTool):
    """Schedule a notification for future delivery via cron."""

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
        self._gcal_timezone = gcal_timezone
        self._gcal_duration_minutes = gcal_duration_minutes
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
        return "schedule_notification"

    @property
    def description(self) -> str:
        return (
            "Schedule a notification to be delivered at a specific time. "
            "Creates both a notification entry and a cron job for delivery. "
            "Use this to remind the user about tasks, deadlines, or blockers."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The notification message to deliver",
                },
                "scheduled_at": {
                    "type": "string",
                    "description": (
                        "When to deliver the notification. "
                        "ISO datetime (e.g., '2026-02-09T15:00:00') or relative time "
                        "(e.g., 'in 2 hours', 'tomorrow 9am')"
                    ),
                },
                "type": {
                    "type": "string",
                    "enum": [
                        "reminder",
                        "deadline_alert",
                        "progress_check",
                        "blocker_followup",
                        "question_reminder",
                    ],
                    "default": "reminder",
                    "description": "Type of notification",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "default": "medium",
                    "description": "Priority level",
                },
                "related_task_id": {
                    "type": "string",
                    "description": "Optional task ID this notification is related to",
                },
                "related_question_id": {
                    "type": "string",
                    "description": "Optional question ID this notification is related to",
                },
                "context": {
                    "type": "string",
                    "default": "",
                    "description": "Additional context about why this notification was scheduled",
                },
                "created_by": {
                    "type": "string",
                    "enum": ["worker", "user", "main_agent"],
                    "default": "main_agent",
                    "description": "Who created this notification",
                },
            },
            "required": ["message", "scheduled_at"],
        }

    @with_dashboard_lock
    async def execute(
        self,
        message: str,
        scheduled_at: str,
        type: str = "reminder",
        priority: str = "medium",
        related_task_id: Optional[str] = None,
        related_question_id: Optional[str] = None,
        context: str = "",
        created_by: str = "main_agent",
    ) -> str:
        """Schedule a notification."""
        try:
            # Parse scheduled_at to datetime
            scheduled_dt = self._parse_datetime(scheduled_at)
            if not scheduled_dt:
                return f"Error: Could not parse scheduled_at '{scheduled_at}'"

            # Generate notification ID
            notification_id = self._generate_id("n")

            # Create cron job
            schedule = CronSchedule(kind="at", at_ms=int(scheduled_dt.timestamp() * 1000))

            cron_job = self.cron_service.add_job(
                name=f"notification_{notification_id}",
                schedule=schedule,
                message=message,
                deliver=True,
                channel=self._channel,
                to=self._chat_id,
                delete_after_run=True,
            )

            # Create notification entry
            notifications_data = await self._load_notifications()
            notifications_list = notifications_data.get("notifications", [])

            notification = {
                "id": notification_id,
                "message": message,
                "scheduled_at": scheduled_dt.isoformat(),
                "scheduled_at_text": (scheduled_at if not scheduled_at.startswith("20") else None),
                "type": type,
                "priority": priority,
                "related_task_id": related_task_id,
                "related_question_id": related_question_id,
                "status": "pending",
                "cron_job_id": cron_job.id,
                "created_at": self._now(),
                "delivered_at": None,
                "cancelled_at": None,
                "context": context,
                "created_by": created_by,
                "gcal_event_id": None,
            }

            notifications_list.append(notification)
            notifications_data["notifications"] = notifications_list

            # Validate and save
            success, msg = await self._validate_and_save_notifications(notifications_data)
            if not success:
                # Rollback cron job
                if not self.cron_service.remove_job(cron_job.id):
                    logger.warning(f"Cron rollback failed for {cron_job.id}")
                return msg

            # Google Calendar sync (best-effort, after save)
            if self._gcal_client:
                try:
                    desc_parts = []
                    if context:
                        desc_parts.append(context)
                    if related_task_id:
                        desc_parts.append(f"Related Task: {related_task_id}")
                    gcal_desc = "\n".join(desc_parts) if desc_parts else None

                    gcal_event_id = await asyncio.to_thread(
                        self._gcal_client.create_event,
                        summary=message,
                        start_iso=scheduled_dt.isoformat(),
                        timezone=self._gcal_timezone,
                        duration_minutes=self._gcal_duration_minutes,
                        description=gcal_desc,
                    )
                    # Persist gcal_event_id back
                    notification["gcal_event_id"] = gcal_event_id
                    notifications_data["notifications"] = notifications_list
                    ok2, msg2 = await self._validate_and_save_notifications(notifications_data)
                    if not ok2:
                        logger.warning(f"gcal_event_id save failed for {notification_id}: {msg2}")
                except Exception as e:
                    logger.warning(f"GCal sync failed (schedule): {e}")
                    await self._send_telegram(f"⚠️ Google Calendar 동기화 실패 (schedule): {e}")

            # Send instant Telegram notification
            time_str = scheduled_dt.strftime("%Y-%m-%d %H:%M")
            await self._send_telegram(
                f"✅ 일정 추가: {message} ({time_str}, {self._gcal_timezone})"
            )

            return (
                f"\u2705 Notification scheduled: {notification_id}\n"
                f"Message: {message}\n"
                f"Scheduled at: {scheduled_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Cron job: {cron_job.id}"
            )

        except Exception as e:
            return f"Error scheduling notification: {str(e)}"
