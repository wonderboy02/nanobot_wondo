"""Unit tests for HealthcheckService."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.healthcheck.service import HealthcheckService


class TestStartStop:
    """start/stop lifecycle."""

    async def test_disabled_does_not_start(self):
        svc = HealthcheckService(ping_url="https://hc-ping.com/test", enabled=False)
        await svc.start()
        assert svc._task is None

    async def test_empty_url_does_not_start(self):
        svc = HealthcheckService(ping_url="", enabled=True)
        await svc.start()
        assert svc._task is None

    async def test_enabled_starts_task(self):
        svc = HealthcheckService(ping_url="https://hc-ping.com/test", interval_s=60, enabled=True)
        with patch("nanobot.healthcheck.service.httpx.AsyncClient") as mock_client:
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = lambda: None
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp.get = AsyncMock(return_value=mock_resp)

            await svc.start()
            assert svc._task is not None
            assert svc._running is True

            svc.stop()
            assert svc._running is False
            assert svc._task is None


class TestPing:
    """_ping() behavior."""

    async def test_successful_ping(self):
        svc = HealthcheckService(ping_url="https://hc-ping.com/test", interval_s=60, enabled=True)
        with patch("nanobot.healthcheck.service.httpx.AsyncClient") as mock_client:
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = lambda: None

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc._ping()
            mock_instance.get.assert_called_once_with("https://hc-ping.com/test")

    async def test_ping_network_error_does_not_raise(self):
        svc = HealthcheckService(ping_url="https://hc-ping.com/test", interval_s=60, enabled=True)
        with patch("nanobot.healthcheck.service.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(side_effect=ConnectionError("refused"))
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not raise
            await svc._ping()

    async def test_ping_cancelled_error_propagates(self):
        svc = HealthcheckService(ping_url="https://hc-ping.com/test", interval_s=60, enabled=True)
        with patch("nanobot.healthcheck.service.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(side_effect=asyncio.CancelledError())
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(asyncio.CancelledError):
                await svc._ping()


class TestConfig:
    """HealthcheckConfig schema."""

    def test_default_values(self):
        from nanobot.config.schema import HealthcheckConfig

        cfg = HealthcheckConfig()
        assert cfg.enabled is False
        assert cfg.ping_url == ""
        assert cfg.interval_s == 300

    def test_minimum_interval(self):
        from pydantic import ValidationError

        from nanobot.config.schema import HealthcheckConfig

        with pytest.raises(ValidationError):
            HealthcheckConfig(interval_s=30)

    def test_config_root_has_healthcheck(self):
        from nanobot.config.schema import Config

        cfg = Config()
        assert hasattr(cfg, "healthcheck")
        assert cfg.healthcheck.enabled is False
