"""Loguru sink that forwards ERROR+ logs to Telegram with throttle/dedup."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, Coroutine

    from loguru import Record


class TelegramAlertSink:
    """Loguru sink — ERROR+ logs to Telegram (throttled).

    Throttle strategy (2-tier):
      1. Per-message dedup: same {name}:{function}:{first_line} hash suppressed for *cooldown_s*.
      2. Global rate limit: max *max_per_hour* alerts per rolling hour.

    The sink is called from any thread (loguru guarantee), so state is guarded
    by a threading.Lock.  Telegram delivery uses fire-and-forget via
    ``asyncio.run_coroutine_threadsafe`` — never blocks the caller.
    """

    def __init__(
        self,
        send_fn: Callable[[str], Coroutine[Any, Any, None]],
        loop: asyncio.AbstractEventLoop,
        *,
        cooldown_s: int = 300,
        max_per_hour: int = 10,
    ) -> None:
        self._send_fn = send_fn
        self._loop = loop
        self._cooldown_s = cooldown_s
        self._max_per_hour = max_per_hour

        # Throttle state (threading.Lock — loguru sink can be called from any thread)
        self._recent: dict[str, float] = {}  # hash → last_sent_time
        self._hourly_count: int = 0
        self._hour_start: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Loguru sink protocol
    # ------------------------------------------------------------------

    def __call__(self, message: str) -> None:
        """Loguru sink entry point.  ``message`` is the *formatted* string;
        the raw ``Record`` is available via ``message.record``."""
        record: Record = message.record  # type: ignore[attr-defined]
        now = time.monotonic()

        if not self._should_send(record, now):
            return

        text = self._format_alert(record)
        self._safe_send(text)

    # ------------------------------------------------------------------
    # Throttle
    # ------------------------------------------------------------------

    def _message_hash(self, record: Record) -> str:
        """Deterministic key: logger name + function + first line of message."""
        first_line = str(record["message"]).split("\n", 1)[0][:200]
        raw = f"{record['name']}:{record['function']}:{first_line}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _should_send(self, record: Record, now: float) -> bool:
        with self._lock:
            # Reset hourly window
            if now - self._hour_start >= 3600:
                self._hourly_count = 0
                self._hour_start = now

            # Global rate limit
            if self._hourly_count >= self._max_per_hour:
                return False

            # Per-message dedup
            h = self._message_hash(record)
            last = self._recent.get(h)
            if last is not None and (now - last) < self._cooldown_s:
                return False

            # Passed — record and allow
            self._recent[h] = now
            self._hourly_count += 1

            # Prune stale entries (keep dict from growing forever)
            cutoff = now - self._cooldown_s
            self._recent = {k: v for k, v in self._recent.items() if v >= cutoff}

            return True

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_alert(record: Record) -> str:
        level = record["level"].name
        name = record["name"]
        func = record["function"]
        line = record["line"]
        msg = str(record["message"])

        # Truncate long messages (Telegram limit ~4096, keep well under)
        if len(msg) > 1000:
            msg = msg[:1000] + "..."

        # Include exception info if present
        exc_text = ""
        if record["exception"] is not None:
            exc_type = record["exception"].type
            exc_value = record["exception"].value
            if exc_type and exc_value:
                exc_text = f"\n\nException: {exc_type.__name__}: {exc_value}"
                if len(exc_text) > 500:
                    exc_text = exc_text[:500] + "..."

        time_str = record["time"].strftime("%Y-%m-%d %H:%M:%S %Z")

        return f"[{level}] {name}:{func} (L{line})\n{msg}{exc_text}\n\n{time_str}"

    # ------------------------------------------------------------------
    # Async bridge (fire-and-forget)
    # ------------------------------------------------------------------

    def _safe_send(self, text: str) -> None:
        """Enqueue alert delivery.  Never blocks, never raises."""
        try:
            if not self._loop.is_running():
                return
            asyncio.run_coroutine_threadsafe(self._send_fn(text), self._loop)
        except Exception:
            # Last resort — must not use logger (infinite recursion)
            print("[AlertSink] Failed to enqueue alert", file=sys.stderr)
