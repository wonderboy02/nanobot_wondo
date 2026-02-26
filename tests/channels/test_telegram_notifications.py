"""Tests for TelegramNotificationManager.

Covers: quiet hours, dedup, daily limits, batching, high priority bypass.
"""

import time
from unittest.mock import patch

import pytest

from nanobot.config.schema import NotificationPolicyConfig
from nanobot.channels.telegram import TelegramNotificationManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def policy():
    return NotificationPolicyConfig(
        quiet_hours_start=23,
        quiet_hours_end=8,
        daily_limit=3,
        dedup_window_hours=24,
        batch_max=2,
    )


@pytest.fixture
def manager(policy):
    return TelegramNotificationManager(policy)


# ---------------------------------------------------------------------------
# should_send — basic
# ---------------------------------------------------------------------------


def test_should_send_normal_message(manager):
    """Normal message outside quiet hours should be sendable."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 12  # noon
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"
        assert manager.should_send("test message") is True


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------


def test_quiet_hours_blocks_medium_priority(manager):
    """Medium priority messages should be blocked during quiet hours."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 2  # 2am - quiet
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"
        assert manager.should_send("test", priority="medium") is False


def test_quiet_hours_allows_high_priority(manager):
    """High priority messages bypass quiet hours."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 2  # 2am - quiet
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"
        assert manager.should_send("urgent", priority="high") is True


def test_quiet_hours_wraps_midnight(manager):
    """Quiet hours 23:00-08:00 correctly wraps around midnight."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        # 23:30 should be quiet
        mock_dt.now.return_value.hour = 23
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"
        assert manager.should_send("test", priority="low") is False

        # 12:00 should not be quiet
        mock_dt.now.return_value.hour = 12
        assert manager.should_send("test2", priority="low") is True


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def test_duplicate_message_blocked(manager):
    """Same message sent twice within dedup window should be blocked."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 12
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"

        # Record first send
        manager._record_sent("same message")
        assert manager.should_send("same message") is False


def test_different_messages_not_blocked(manager):
    """Different messages should not trigger dedup."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 12
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"

        manager._record_sent("message A")
        assert manager.should_send("message B") is True


def test_dedup_expires(manager):
    """Messages should be sendable again after dedup window expires."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 12
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"

        # Record a send far in the past
        h = manager._msg_hash("old message")
        manager._sent_hashes[h] = time.time() - (25 * 3600)  # 25 hours ago

        assert manager.should_send("old message") is True


def test_dedup_blocks_high_priority_too(manager):
    """Dedup blocks even high priority messages (unlike quiet hours/daily limit)."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 12
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"

        manager._record_sent("urgent alert")
        assert manager.should_send("urgent alert", priority="high") is False


# ---------------------------------------------------------------------------
# Daily limit
# ---------------------------------------------------------------------------


def test_daily_limit_blocks(manager):
    """Messages should be blocked after daily limit is reached."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 12
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"

        # Use up the daily limit (3)
        manager._daily_counts["2026-02-20"] = 3

        assert manager.should_send("one more", priority="medium") is False


def test_daily_limit_allows_high_priority(manager):
    """High priority bypasses daily limit."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 12
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"

        manager._daily_counts["2026-02-20"] = 3  # At limit

        assert manager.should_send("urgent", priority="high") is True


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


def test_batch_add_and_flush(manager):
    """add_to_batch + flush_batch returns formatted message."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 12
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"

        manager.add_to_batch("notification 1")
        result = manager.flush_batch()
        assert result == "notification 1"


def test_batch_empty_returns_none(manager):
    """flush_batch on empty batch returns None."""
    assert manager.flush_batch() is None


def test_batch_max_limits(manager):
    """flush_batch sends at most batch_max items, keeps rest."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 12
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"

        manager.add_to_batch("msg 1")
        manager.add_to_batch("msg 2")
        manager.add_to_batch("msg 3")  # batch_max=2, so this stays

        result = manager.flush_batch()
        assert result is not None
        assert "msg 1" in result
        assert "msg 2" in result

        # Third message should still be in batch
        assert len(manager._batch) == 1


def test_batch_multiple_format(manager):
    """Multiple batched notifications use multi-line format."""
    with patch("nanobot.channels.telegram.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 12
        mock_dt.now.return_value.strftime = lambda fmt: "2026-02-20"

        manager.add_to_batch("alert 1", priority="high")
        manager.add_to_batch("alert 2", priority="low")

        result = manager.flush_batch()
        assert "Notifications" in result


# ---------------------------------------------------------------------------
# _msg_hash
# ---------------------------------------------------------------------------


def test_msg_hash_consistent(manager):
    """Same message produces same hash."""
    assert manager._msg_hash("test") == manager._msg_hash("test")


def test_msg_hash_different(manager):
    """Different messages produce different hashes."""
    assert manager._msg_hash("test A") != manager._msg_hash("test B")
