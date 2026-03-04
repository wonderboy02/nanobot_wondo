"""Timezone-aware current time utility.

All modules should use ``now()`` instead of ``datetime.now()`` to ensure
consistent timezone handling regardless of server locale (e.g., UTC on AWS).

Priority: NANOBOT_TIMEZONE env var > TZ env var > "Asia/Seoul" default.
Returns naive datetime (no tzinfo) for compatibility with existing code
that compares/parses timestamps as naive datetimes.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

_DEFAULT_TZ = "Asia/Seoul"


def app_tz() -> ZoneInfo:
    """Resolve app timezone (used by now() and parse_datetime())."""
    tz_name = os.environ.get("NANOBOT_TIMEZONE") or os.environ.get("TZ") or _DEFAULT_TZ
    try:
        return ZoneInfo(tz_name)
    except (KeyError, ModuleNotFoundError):
        return ZoneInfo(_DEFAULT_TZ)


def now() -> datetime:
    """Current time in app timezone (naive datetime for compatibility)."""
    return datetime.now(app_tz()).replace(tzinfo=None)
