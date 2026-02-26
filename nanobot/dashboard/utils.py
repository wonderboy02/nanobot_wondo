"""Shared utilities for Dashboard modules."""

from datetime import datetime


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
