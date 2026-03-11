"""Tests for TelegramAlertSink — loguru ERROR+ to Telegram with throttle."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.alerts.service import TelegramAlertSink


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    *,
    name: str = "nanobot.heartbeat.service",
    function: str = "_tick",
    line: int = 147,
    message: str = "Worker execution failed: connection refused",
    level_name: str = "ERROR",
    exception: object = None,
) -> MagicMock:
    """Build a minimal loguru-style Record dict (accessed via [])."""
    record = {
        "name": name,
        "function": function,
        "line": line,
        "message": message,
        "level": MagicMock(name=level_name),
        "exception": exception,
        "time": MagicMock(),
    }
    record["level"].name = level_name
    record["time"].strftime = MagicMock(return_value="2026-03-10 14:30:22 KST")

    # Loguru passes formatted string with .record attribute
    msg_obj = MagicMock(spec=str)
    msg_obj.record = record
    return msg_obj


def _make_sink(
    loop: asyncio.AbstractEventLoop,
    send_fn: AsyncMock | None = None,
    cooldown_s: int = 300,
    max_per_hour: int = 10,
) -> TelegramAlertSink:
    if send_fn is None:
        send_fn = AsyncMock()
    return TelegramAlertSink(
        send_fn=send_fn,
        loop=loop,
        cooldown_s=cooldown_s,
        max_per_hour=max_per_hour,
    )


# ---------------------------------------------------------------------------
# Basic delivery
# ---------------------------------------------------------------------------


class TestBasicDelivery:
    async def test_sends_alert_on_error(self):
        """Sink should enqueue a coroutine via run_coroutine_threadsafe."""
        loop = asyncio.get_running_loop()
        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn)

        msg = _make_record()
        sink(msg)

        # Give the event loop a chance to execute the enqueued coroutine
        await asyncio.sleep(0.05)

        send_fn.assert_called_once()
        text = send_fn.call_args[0][0]
        assert "[ERROR]" in text
        assert "heartbeat.service" in text
        assert "connection refused" in text

    async def test_alert_format_includes_location(self):
        loop = asyncio.get_running_loop()
        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn)

        msg = _make_record(function="reconcile", line=42, name="nanobot.dashboard.reconciler")
        sink(msg)
        await asyncio.sleep(0.05)

        text = send_fn.call_args[0][0]
        assert "reconciler:reconcile (L42)" in text

    async def test_alert_format_includes_timestamp(self):
        loop = asyncio.get_running_loop()
        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn)

        msg = _make_record()
        sink(msg)
        await asyncio.sleep(0.05)

        text = send_fn.call_args[0][0]
        assert "2026-03-10 14:30:22 KST" in text


# ---------------------------------------------------------------------------
# Per-message dedup (cooldown)
# ---------------------------------------------------------------------------


class TestCooldown:
    async def test_duplicate_suppressed_within_cooldown(self):
        loop = asyncio.get_running_loop()
        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn, cooldown_s=300)

        msg1 = _make_record(message="same error")
        msg2 = _make_record(message="same error")

        sink(msg1)
        sink(msg2)  # same hash, should be suppressed

        await asyncio.sleep(0.05)
        assert send_fn.call_count == 1

    async def test_different_errors_not_suppressed(self):
        loop = asyncio.get_running_loop()
        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn, cooldown_s=300)

        msg1 = _make_record(message="error A")
        msg2 = _make_record(message="error B")

        sink(msg1)
        sink(msg2)

        await asyncio.sleep(0.05)
        assert send_fn.call_count == 2

    async def test_resend_after_cooldown_expires(self):
        loop = asyncio.get_running_loop()
        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn, cooldown_s=1)  # 1 second cooldown

        msg1 = _make_record(message="transient error")
        sink(msg1)
        await asyncio.sleep(0.05)
        assert send_fn.call_count == 1

        # Wait for cooldown to expire
        await asyncio.sleep(1.1)

        msg2 = _make_record(message="transient error")
        sink(msg2)
        await asyncio.sleep(0.05)
        assert send_fn.call_count == 2


# ---------------------------------------------------------------------------
# Global rate limit
# ---------------------------------------------------------------------------


class TestRateLimit:
    async def test_hourly_limit_exceeded(self):
        loop = asyncio.get_running_loop()
        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn, max_per_hour=3, cooldown_s=0)

        for i in range(5):
            msg = _make_record(message=f"error {i}")  # unique messages
            sink(msg)

        await asyncio.sleep(0.05)
        assert send_fn.call_count == 3  # capped at max_per_hour


# ---------------------------------------------------------------------------
# _safe_send resilience
# ---------------------------------------------------------------------------


class TestSafeSend:
    async def test_send_fn_exception_does_not_propagate(self):
        """If send_fn raises, the sink should not crash."""
        loop = asyncio.get_running_loop()
        send_fn = AsyncMock(side_effect=Exception("Telegram API down"))
        sink = _make_sink(loop, send_fn)

        msg = _make_record()
        # Should not raise
        sink(msg)
        await asyncio.sleep(0.05)

    def test_loop_not_running_skips_safely(self):
        """If the event loop is not running, _safe_send should skip."""
        loop = MagicMock()
        loop.is_running.return_value = False

        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn)

        msg = _make_record()
        # Should not raise
        sink(msg)

        send_fn.assert_not_called()

    def test_run_coroutine_threadsafe_failure_handled(self, capsys):
        """If run_coroutine_threadsafe itself fails, should print to stderr."""
        loop = MagicMock()
        loop.is_running.return_value = True

        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn)

        # Make run_coroutine_threadsafe raise
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                asyncio,
                "run_coroutine_threadsafe",
                MagicMock(side_effect=RuntimeError("loop closed")),
            )
            msg = _make_record()
            sink(msg)  # should not raise

        captured = capsys.readouterr()
        assert "Failed to enqueue alert" in captured.err


# ---------------------------------------------------------------------------
# Exception info in alert
# ---------------------------------------------------------------------------


class TestExceptionFormatting:
    async def test_exception_included_in_alert(self):
        loop = asyncio.get_running_loop()
        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn)

        exc_info = MagicMock()
        exc_info.type = ValueError
        exc_info.value = ValueError("bad input")

        msg = _make_record(message="Processing failed", exception=exc_info)
        sink(msg)
        await asyncio.sleep(0.05)

        text = send_fn.call_args[0][0]
        assert "ValueError: bad input" in text

    async def test_no_exception_no_extra_text(self):
        loop = asyncio.get_running_loop()
        send_fn = AsyncMock()
        sink = _make_sink(loop, send_fn)

        msg = _make_record(message="Simple error", exception=None)
        sink(msg)
        await asyncio.sleep(0.05)

        text = send_fn.call_args[0][0]
        assert "Exception:" not in text
