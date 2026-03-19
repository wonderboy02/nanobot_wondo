"""Heartbeat service - periodic worker execution and weekly report."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from nanobot.dashboard.storage import StorageBackend
    from nanobot.providers.stats import ApiKeyStats

from loguru import logger

# Default interval: 2 hours
DEFAULT_HEARTBEAT_INTERVAL_S = 2 * 60 * 60


class HeartbeatService:
    """Periodic service that runs the Worker Agent and checks weekly stats.

    Each periodic job runs independently — no job blocks another.
    """

    def __init__(
        self,
        workspace: Path,
        interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S,
        enabled: bool = True,
        provider: Any | None = None,  # LLMProvider
        model: str | None = None,
        storage_backend: "StorageBackend | None" = None,
        processing_lock: asyncio.Lock | None = None,
        scheduler: Any | None = None,  # ReconciliationScheduler
        api_key_stats: "ApiKeyStats | None" = None,
        report_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        gcal_client: Any | None = None,
        gcal_timezone: str = "Asia/Seoul",
    ):
        self.workspace = workspace
        self.interval_s = interval_s
        self.enabled = enabled
        self.provider = provider
        self.model = model
        self.storage_backend = storage_backend
        self._processing_lock = processing_lock
        self.scheduler = scheduler
        self.api_key_stats = api_key_stats
        self.report_callback = report_callback
        self.gcal_client = gcal_client
        self.gcal_timezone = gcal_timezone
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

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
                logger.error("Heartbeat error: {}", e)

    async def _tick(self) -> None:
        """Execute a single heartbeat tick.

        Each job is independent and runs unconditionally.
        """
        await self._run_worker()
        await self._check_weekly_report()

    async def _check_weekly_report(self) -> None:
        """Send weekly API key usage report if interval has elapsed."""
        if not self.api_key_stats:
            return
        summary = self.api_key_stats.get_weekly_summary()
        if not summary or not self.report_callback:
            return
        try:
            await self.report_callback(summary)
            self.api_key_stats.mark_reported()
            logger.info("Weekly API stats report sent")
        except Exception as e:
            logger.error("Weekly stats report failed: {}", e)

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
                scheduler=self.scheduler,
                report_callback=self.report_callback,
                gcal_client=self.gcal_client,
                gcal_timezone=self.gcal_timezone,
            )

            if self._processing_lock:
                async with self._processing_lock:
                    await worker.run_cycle()
            else:
                await worker.run_cycle()
            logger.debug("Worker cycle completed successfully")

        except ImportError:
            logger.debug("Dashboard worker not available")
        except FileNotFoundError as e:
            logger.warning("Dashboard files missing: {}", e)
        except Exception as e:
            logger.error("Worker execution failed: {}", e)
