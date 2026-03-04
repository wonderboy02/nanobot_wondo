"""Tests for nanobot.utils.time module."""

from datetime import datetime
from unittest.mock import patch

from nanobot.utils.time import app_tz, now


def test_now_returns_naive_datetime():
    """now() should return a naive datetime (no tzinfo)."""
    result = now()
    assert isinstance(result, datetime)
    assert result.tzinfo is None


def test_nanobot_timezone_env_takes_priority():
    """NANOBOT_TIMEZONE should override TZ and default."""
    with patch.dict("os.environ", {"NANOBOT_TIMEZONE": "US/Eastern", "TZ": "Europe/London"}):
        tz = app_tz()
        assert str(tz) == "US/Eastern"


def test_tz_env_used_when_no_nanobot_timezone():
    """TZ should be used when NANOBOT_TIMEZONE is not set."""
    with patch.dict("os.environ", {"TZ": "Europe/London"}, clear=False):
        env = {"TZ": "Europe/London"}
        with patch.dict("os.environ", env):
            # Remove NANOBOT_TIMEZONE if present
            import os

            os.environ.pop("NANOBOT_TIMEZONE", None)
            tz = app_tz()
            assert str(tz) == "Europe/London"


def test_default_is_asia_seoul():
    """Default timezone should be Asia/Seoul."""
    with patch.dict("os.environ", {}, clear=True):
        tz = app_tz()
        assert str(tz) == "Asia/Seoul"


def test_invalid_tz_falls_back_to_default():
    """Invalid timezone name should fall back to Asia/Seoul."""
    with patch.dict("os.environ", {"NANOBOT_TIMEZONE": "Invalid/Zone"}):
        tz = app_tz()
        assert str(tz) == "Asia/Seoul"
