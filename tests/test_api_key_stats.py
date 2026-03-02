"""Tests for ApiKeyStats — file-persisted API key usage tracking."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from nanobot.providers.stats import ApiKeyStats, _empty_data


@pytest.fixture
def stats_file(tmp_path):
    return tmp_path / "api_stats.json"


@pytest.fixture
def stats(stats_file):
    return ApiKeyStats(stats_file)


# ---------------------------------------------------------------------------
# record() — basic accumulation
# ---------------------------------------------------------------------------


class TestRecord:
    def test_success_increments_counter(self, stats, stats_file):
        stats.record("gemini", "free", "success", 100)
        data = json.loads(stats_file.read_text())
        assert data["providers"]["gemini"]["free_success"] == 1
        assert data["providers"]["gemini"]["total_tokens"] == 100

    def test_paid_success(self, stats, stats_file):
        stats.record("gemini", "paid", "success", 200)
        data = json.loads(stats_file.read_text())
        assert data["providers"]["gemini"]["paid_success"] == 1
        assert data["providers"]["gemini"]["total_tokens"] == 200

    def test_rate_limited(self, stats, stats_file):
        stats.record("gemini", "free", "rate_limited", 0)
        data = json.loads(stats_file.read_text())
        assert data["providers"]["gemini"]["rate_limited"] == 1
        assert data["providers"]["gemini"]["total_tokens"] == 0

    def test_accumulates_across_calls(self, stats, stats_file):
        stats.record("gemini", "free", "success", 100)
        stats.record("gemini", "free", "success", 200)
        stats.record("gemini", "paid", "success", 50)
        data = json.loads(stats_file.read_text())
        assert data["providers"]["gemini"]["free_success"] == 2
        assert data["providers"]["gemini"]["paid_success"] == 1
        assert data["providers"]["gemini"]["total_tokens"] == 350

    def test_multiple_providers(self, stats, stats_file):
        stats.record("gemini", "free", "success", 100)
        stats.record("anthropic", "free", "success", 200)
        data = json.loads(stats_file.read_text())
        assert "gemini" in data["providers"]
        assert "anthropic" in data["providers"]

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "api_stats.json"
        s = ApiKeyStats(nested)
        s.record("gemini", "free", "success", 10)
        assert nested.exists()


# ---------------------------------------------------------------------------
# File recovery
# ---------------------------------------------------------------------------


class TestFileRecovery:
    def test_corrupted_json_resets(self, stats, stats_file):
        stats_file.write_text("not json at all")
        stats.record("gemini", "free", "success", 50)
        data = json.loads(stats_file.read_text())
        assert data["providers"]["gemini"]["free_success"] == 1

    def test_missing_file_creates_new(self, stats, stats_file):
        assert not stats_file.exists()
        stats.record("gemini", "free", "success", 10)
        assert stats_file.exists()

    def test_invalid_structure_resets(self, stats, stats_file):
        stats_file.write_text(json.dumps({"something": "else"}))
        stats.record("gemini", "free", "success", 10)
        data = json.loads(stats_file.read_text())
        assert data["providers"]["gemini"]["free_success"] == 1


# ---------------------------------------------------------------------------
# get_weekly_summary()
# ---------------------------------------------------------------------------


class TestWeeklySummary:
    def test_returns_none_before_7_days(self, stats, stats_file):
        stats.record("gemini", "free", "success", 100)
        assert stats.get_weekly_summary() is None

    def test_returns_report_after_7_days(self, stats, stats_file):
        old_start = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        data = _empty_data()
        data["period_start"] = old_start
        data["providers"]["gemini"] = {
            "free_success": 100,
            "paid_success": 5,
            "rate_limited": 3,
            "total_tokens": 50000,
        }
        stats_file.write_text(json.dumps(data))

        summary = stats.get_weekly_summary()
        assert summary is not None
        assert "gemini" in summary
        assert "100" in summary
        assert "50,000" in summary

    def test_report_format_contains_total(self, stats, stats_file):
        old_start = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        data = _empty_data()
        data["period_start"] = old_start
        data["providers"]["gemini"] = {
            "free_success": 10,
            "paid_success": 2,
            "rate_limited": 1,
            "total_tokens": 1000,
        }
        stats_file.write_text(json.dumps(data))

        summary = stats.get_weekly_summary()
        assert "Total: 13 calls" in summary


# ---------------------------------------------------------------------------
# mark_reported()
# ---------------------------------------------------------------------------


class TestMarkReported:
    def test_resets_counters(self, stats, stats_file):
        stats.record("gemini", "free", "success", 100)
        stats.mark_reported()
        data = json.loads(stats_file.read_text())
        assert data["providers"] == {}
        assert data["last_report_at"] is not None

    def test_new_period_start(self, stats, stats_file):
        stats.record("gemini", "free", "success", 100)
        before = datetime.now(timezone.utc)
        stats.mark_reported()
        data = json.loads(stats_file.read_text())
        period_start = datetime.fromisoformat(data["period_start"])
        assert period_start >= before


# ---------------------------------------------------------------------------
# Persistence across instances
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_data_survives_new_instance(self, stats_file):
        s1 = ApiKeyStats(stats_file)
        s1.record("gemini", "free", "success", 100)

        s2 = ApiKeyStats(stats_file)
        s2.record("gemini", "free", "success", 200)

        data = json.loads(stats_file.read_text())
        assert data["providers"]["gemini"]["free_success"] == 2
        assert data["providers"]["gemini"]["total_tokens"] == 300
