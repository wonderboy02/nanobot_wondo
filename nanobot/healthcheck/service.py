"""Healthchecks.io ping service — periodic GET to signal liveness."""

from __future__ import annotations

import asyncio

import httpx
from loguru import logger

PING_TIMEOUT_S = 10


class HealthcheckService:
    """Periodically pings a healthchecks.io URL to signal the container is alive."""

    def __init__(self, ping_url: str, interval_s: int = 300, enabled: bool = False):
        self.ping_url = ping_url
        self.interval_s = interval_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.enabled or not self.ping_url:
            logger.info("Healthcheck disabled")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        masked = self.ping_url.rsplit("/", 1)[0] + "/***"
        logger.info("Healthcheck started (every %ds → %s)", self.interval_s, masked)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        # Ping immediately on startup, then repeat every interval_s
        while self._running:
            try:
                await self._ping()
                await asyncio.sleep(self.interval_s)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Healthcheck error: %s", e)

    async def _ping(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=PING_TIMEOUT_S) as client:
                resp = await client.get(self.ping_url)
                resp.raise_for_status()
                logger.debug("Healthcheck ping OK (%d)", resp.status_code)
        except asyncio.CancelledError:
            raise
        except httpx.HTTPStatusError as e:
            logger.warning("Healthcheck ping bad status: %d", e.response.status_code)
        except Exception as e:
            logger.warning("Healthcheck ping failed: %s", e)
