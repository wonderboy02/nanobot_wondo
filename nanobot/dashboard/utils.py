"""Shared utilities for Dashboard modules."""

import re
from datetime import date, datetime

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(dt_str: str) -> datetime:
    """Parse ISO datetime string to naive local-time datetime.

    If the input is timezone-aware, converts to local time first, then
    strips tzinfo so the result is comparable with datetime.now().
    If naive, returns as-is (assumed local time).

    Raises ValueError if dt_str is empty or not a valid ISO datetime.
    """
    if not isinstance(dt_str, str) or not dt_str:
        raise ValueError(f"Invalid datetime string: {dt_str!r}")
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def normalize_iso_date(value: str) -> str | None:
    """Extract YYYY-MM-DD from a date or datetime string.

    Returns the date portion if valid, None otherwise.
    Handles both "2026-02-15" and "2026-02-15T09:00:00" formats.
    """
    if not value:
        return None
    value = value.strip()
    if _ISO_DATE_RE.match(value):
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
        return value
    # Try extracting date portion from datetime string
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", value)
    if m:
        candidate = m.group(1)
        try:
            date.fromisoformat(candidate)
        except ValueError:
            return None
        return candidate
    return None
