"""API key usage statistics — records every LLM call to disk immediately.

Uses UTC for period tracking (period_start, last_report_at, interval calc)
because stats are server-internal metadata — not user-facing timestamps.
7-day interval comparison is timezone-insensitive at this granularity.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _empty_counter() -> dict[str, int]:
    return {"free_success": 0, "paid_success": 0, "rate_limited": 0, "total_tokens": 0}


def _empty_data() -> dict[str, Any]:
    return {
        "period_start": datetime.now(timezone.utc).isoformat(),
        "last_report_at": None,
        "providers": {},
    }


class ApiKeyStats:
    """Track API key usage per provider and generate weekly Telegram reports.

    Every call to ``record()`` immediately persists to a JSON file via atomic
    write (temp file + rename) so no data is lost on container restarts.
    """

    REPORT_INTERVAL_DAYS = 7

    def __init__(self, stats_file: Path) -> None:
        self._file = stats_file

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, provider: str, tier: str, event: str, tokens: int) -> None:
        """Record a single LLM call outcome and flush to disk."""
        data = self._load()
        counters = data["providers"].setdefault(provider, _empty_counter())
        if event == "success":
            counters[f"{tier}_success"] += 1
            counters["total_tokens"] += tokens
        elif event == "rate_limited":
            counters["rate_limited"] += 1
        self._save(data)

    def get_weekly_summary(self) -> str | None:
        """Return a formatted report if >= 7 days since period start, else None."""
        data = self._load()
        period_start = self._parse_dt(data.get("period_start"))
        if period_start is None:
            return None

        now = datetime.now(timezone.utc)
        if (now - period_start).days < self.REPORT_INTERVAL_DAYS:
            return None

        return self._format_report(data, period_start, now)

    def mark_reported(self) -> None:
        """Reset counters and start a new period."""
        data = _empty_data()
        data["last_report_at"] = datetime.now(timezone.utc).isoformat()
        self._save(data)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        try:
            text = self._file.read_text(encoding="utf-8")
            data = json.loads(text)
            if not isinstance(data, dict) or "providers" not in data:
                return _empty_data()
            return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return _empty_data()

    def _save(self, data: dict[str, Any]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp = tempfile.mkstemp(dir=str(self._file.parent), suffix=".tmp", prefix=".stats_")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                Path(tmp).replace(self._file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as exc:
            logger.error("Failed to save API stats: {}", exc)

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _format_report(data: dict[str, Any], period_start: datetime, now: datetime) -> str:
        start_str = period_start.strftime("%m/%d")
        end_str = now.strftime("%m/%d")
        lines = [f"\U0001f4ca API Key Usage ({start_str} ~ {end_str})", ""]

        total_calls = 0
        for provider, counters in sorted(data.get("providers", {}).items()):
            free = counters.get("free_success", 0)
            paid = counters.get("paid_success", 0)
            rl = counters.get("rate_limited", 0)
            tokens = counters.get("total_tokens", 0)
            provider_calls = free + paid + rl

            lines.append(f"{provider}:")
            if free or rl:
                lines.append(f"  Free: {free:,} ok / {rl:,} rate-limited")
            if paid:
                lines.append(f"  Paid: {paid:,}")
            lines.append(f"  Tokens: {tokens:,}")
            lines.append("")
            total_calls += provider_calls

        lines.append(f"Total: {total_calls:,} calls")
        return "\n".join(lines)
