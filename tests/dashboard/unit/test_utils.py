"""Unit tests for nanobot.dashboard.utils."""

from datetime import datetime, timezone

import pytest

from nanobot.dashboard.utils import parse_datetime


class TestParseDatetime:
    """Tests for parse_datetime utility."""

    def test_naive_iso_string(self):
        """Common case: datetime.now().isoformat()."""
        result = parse_datetime("2026-02-25T10:30:00")
        assert result == datetime(2026, 2, 25, 10, 30, 0)
        assert result.tzinfo is None

    def test_naive_iso_with_microseconds(self):
        """Naive ISO with microseconds."""
        result = parse_datetime("2026-02-25T10:30:00.123456")
        assert result.year == 2026
        assert result.microsecond == 123456
        assert result.tzinfo is None

    def test_z_suffix_converted(self):
        """'Z' suffix is replaced with +00:00 and converted to local naive."""
        result = parse_datetime("2026-02-25T10:00:00Z")
        # Should be converted to local time and made naive
        assert result.tzinfo is None
        # The exact hour depends on server timezone, but it should be a valid datetime
        assert isinstance(result, datetime)

    def test_timezone_aware_converted_to_naive(self):
        """Timezone-aware input converted to local naive datetime."""
        result = parse_datetime("2026-02-25T10:00:00+09:00")
        assert result.tzinfo is None
        assert isinstance(result, datetime)

    def test_empty_string_raises(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid datetime string"):
            parse_datetime("")

    def test_none_raises(self):
        """None raises ValueError."""
        with pytest.raises(ValueError, match="Invalid datetime string"):
            parse_datetime(None)

    def test_non_string_raises(self):
        """Non-string input raises ValueError."""
        with pytest.raises(ValueError, match="Invalid datetime string"):
            parse_datetime(12345)

    def test_invalid_format_raises(self):
        """Unparseable string raises ValueError."""
        with pytest.raises(ValueError):
            parse_datetime("not-a-date")

    def test_date_only_string(self):
        """Date-only ISO string (no time component)."""
        result = parse_datetime("2026-02-25")
        assert result == datetime(2026, 2, 25, 0, 0, 0)

    def test_utc_timezone_object(self):
        """Timezone-aware UTC datetime."""
        result = parse_datetime("2026-02-25T00:00:00+00:00")
        assert result.tzinfo is None
