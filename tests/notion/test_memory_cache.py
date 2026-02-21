"""Tests for MemoryCache (nanobot/notion/storage.py).

Covers get/set, TTL expiry, invalidate, and invalidate_all.
"""

from unittest.mock import patch

import pytest

from nanobot.notion.storage import MemoryCache


# ---------------------------------------------------------------------------
# Basic get / set
# ---------------------------------------------------------------------------

class TestMemoryCacheBasic:
    """Basic cache operations."""

    def test_set_and_get(self):
        cache = MemoryCache(ttl_s=300)
        cache.set("tasks", [{"id": "t1"}])
        result = cache.get("tasks")
        assert result == [{"id": "t1"}]

    def test_get_missing_key_returns_none(self):
        cache = MemoryCache(ttl_s=300)
        assert cache.get("nonexistent") is None

    def test_set_overwrites_previous(self):
        cache = MemoryCache(ttl_s=300)
        cache.set("key", "v1")
        cache.set("key", "v2")
        assert cache.get("key") == "v2"

    def test_different_keys_independent(self):
        cache = MemoryCache(ttl_s=300)
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.get("a") == 1
        assert cache.get("b") == 2


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------

class TestMemoryCacheTTL:
    """TTL-based expiry."""

    def test_get_returns_none_after_ttl_expires(self):
        """Cached value should be gone after TTL."""
        cache = MemoryCache(ttl_s=10)

        # Mock time.monotonic to control timing
        with patch("nanobot.notion.storage.time.monotonic", return_value=1000.0):
            cache.set("key", "data")

        # Still valid at 1005 (5s elapsed, TTL is 10s)
        with patch("nanobot.notion.storage.time.monotonic", return_value=1005.0):
            assert cache.get("key") == "data"

        # Expired at 1011 (11s elapsed > 10s TTL)
        with patch("nanobot.notion.storage.time.monotonic", return_value=1011.0):
            assert cache.get("key") is None

    def test_expired_entry_is_removed_from_store(self):
        """After TTL expiry, the entry should be deleted from internal store."""
        cache = MemoryCache(ttl_s=5)

        with patch("nanobot.notion.storage.time.monotonic", return_value=100.0):
            cache.set("key", "data")

        with patch("nanobot.notion.storage.time.monotonic", return_value=106.0):
            cache.get("key")  # triggers deletion
            assert "key" not in cache._store


# ---------------------------------------------------------------------------
# invalidate / invalidate_all
# ---------------------------------------------------------------------------

class TestMemoryCacheInvalidation:
    """Cache invalidation methods."""

    def test_invalidate_removes_specific_key(self):
        cache = MemoryCache(ttl_s=300)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.invalidate("a")
        assert cache.get("a") is None
        assert cache.get("b") == 2

    def test_invalidate_nonexistent_key_is_safe(self):
        """Invalidating a key that does not exist should not raise."""
        cache = MemoryCache(ttl_s=300)
        cache.invalidate("ghost")  # no error

    def test_invalidate_all_clears_everything(self):
        cache = MemoryCache(ttl_s=300)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.invalidate_all()
        assert cache.get("a") is None
        assert cache.get("b") is None
        assert cache.get("c") is None
        assert len(cache._store) == 0
