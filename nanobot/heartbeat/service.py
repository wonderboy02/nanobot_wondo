"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

if TYPE_CHECKING:
    from nanobot.dashboard.storage import StorageBackend
    from nanobot.google.calendar import GoogleCalendarClient

from loguru import logger

# Default interval: 30 minutes
DEFAULT_HEARTBEAT_INTERVAL_S = 30 * 60

# The prompt sent to agent during heartbeat
HEARTBEAT_PROMPT = """Read HEARTBEAT.md in your workspace (if it exists).
Follow any instructions or tasks listed there.
If nothing needs attention, reply with just: HEARTBEAT_OK"""

# Token that indicates "nothing to do"
HEARTBEAT_OK_TOKEN = "HEARTBEAT_OK"


def _is_heartbeat_empty(content: str | None) -> bool:
    """Check if HEARTBEAT.md has no actionable content."""
    if not content:
        return True

    # Lines to skip: empty, headers, HTML comments, empty checkboxes
    skip_patterns = {"- [ ]", "* [ ]", "- [x]", "* [x]"}

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("<!--") or line in skip_patterns:
            continue
        return False  # Found actionable content

    return True


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    The agent reads HEARTBEAT.md from the workspace and executes any
    tasks listed there. If nothing needs attention, it replies HEARTBEAT_OK.
    """

    def __init__(
        self,
        workspace: Path,
        on_heartbeat: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S,
        enabled: bool = True,
        provider: Optional[Any] = None,  # LLMProvider
        model: Optional[str] = None,
        cron_service: Optional[Any] = None,  # CronService
        bus: Optional[Any] = None,  # MessageBus
        storage_backend: "StorageBackend | None" = None,
        send_callback: Optional[Any] = None,
        notification_chat_id: Optional[str] = None,
        gcal_client: "GoogleCalendarClient | None" = None,
        gcal_timezone: str = "Asia/Seoul",
        gcal_duration_minutes: int = 30,
    ):
        self.workspace = workspace
        self.on_heartbeat = on_heartbeat
        self.interval_s = interval_s
        self.enabled = enabled
        self.provider = provider
        self.model = model
        self.cron_service = cron_service
        self.bus = bus
        self.storage_backend = storage_backend
        self.send_callback = send_callback
        self.notification_chat_id = notification_chat_id
        self.gcal_client = gcal_client
        self.gcal_timezone = gcal_timezone
        self.gcal_duration_minutes = gcal_duration_minutes
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        """Read HEARTBEAT.md content."""
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text()
            except Exception:
                return None
        return None

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Heartbeat started (every {self.interval_s}s)")

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        # Run Worker Agent first
        await self._run_worker()

        # Then check HEARTBEAT.md
        content = self._read_heartbeat_file()

        # Skip if HEARTBEAT.md is empty or doesn't exist
        if _is_heartbeat_empty(content):
            logger.debug("Heartbeat: no tasks (HEARTBEAT.md empty)")
            return

        logger.info("Heartbeat: checking for tasks...")

        if self.on_heartbeat:
            try:
                response = await self.on_heartbeat(HEARTBEAT_PROMPT)

                # Check if agent said "nothing to do"
                if HEARTBEAT_OK_TOKEN.replace("_", "") in response.upper().replace("_", ""):
                    logger.info("Heartbeat: OK (no action needed)")
                else:
                    logger.info(f"Heartbeat: completed task")

            except Exception as e:
                logger.error(f"Heartbeat execution failed: {e}")

    async def _run_worker(self) -> None:
        """Run the unified Worker Agent to check dashboard."""
        dashboard_path = self.workspace / "dashboard"

        # Dashboard not initialized - skip worker
        if not dashboard_path.exists() and self.storage_backend is None:
            return

        # Invalidate cache so worker sees latest Notion data
        if self.storage_backend:
            self.storage_backend.invalidate_cache()

        try:
            from nanobot.dashboard.storage import JsonStorageBackend
            from nanobot.dashboard.worker import WorkerAgent

            backend = self.storage_backend or JsonStorageBackend(self.workspace)
            worker = WorkerAgent(
                workspace=self.workspace,
                storage_backend=backend,
                provider=self.provider,
                model=self.model,
                cron_service=self.cron_service,
                bus=self.bus,
                send_callback=self.send_callback,
                notification_chat_id=self.notification_chat_id,
                gcal_client=self.gcal_client,
                gcal_timezone=self.gcal_timezone,
                gcal_duration_minutes=self.gcal_duration_minutes,
            )
            await worker.run_cycle()
            logger.debug("Worker cycle completed successfully")

        except ImportError:
            logger.debug("Dashboard worker not available")
        except FileNotFoundError as e:
            logger.warning(f"Dashboard files missing: {e}")
        except Exception as e:
            logger.error(f"Worker execution failed: {e}")
