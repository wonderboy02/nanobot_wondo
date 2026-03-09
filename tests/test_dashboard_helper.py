"""Tests for get_dashboard_summary() pending notifications section."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from nanobot.dashboard.helper import _format_notification_line, get_dashboard_summary
from nanobot.dashboard.storage import StorageBackend


@pytest.fixture
def dashboard_dir(tmp_path):
    """Create a dashboard directory with base files."""
    d = tmp_path / "dashboard"
    d.mkdir()
    (d / "tasks.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "tasks": [
                    {
                        "id": "task_001",
                        "title": "블로그 작성",
                        "status": "active",
                        "priority": "high",
                        "progress": {"percentage": 30},
                    },
                    {
                        "id": "task_002",
                        "title": "운동 루틴",
                        "status": "active",
                        "priority": "medium",
                        "progress": {"percentage": 0},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (d / "questions.json").write_text(
        json.dumps({"version": "1.0", "questions": []}), encoding="utf-8"
    )
    (d / "notifications.json").write_text(
        json.dumps({"version": "1.0", "notifications": []}), encoding="utf-8"
    )
    return d


def test_summary_includes_pending_notifications(dashboard_dir):
    """Pending notifications appear in the summary output."""
    now = datetime.now()
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_abc",
                "message": "마감 알림",
                "scheduled_at": (now + timedelta(hours=2)).isoformat(),
                "type": "deadline_alert",
                "priority": "high",
                "status": "pending",
                "related_task_id": "task_001",
            }
        ],
    }
    (dashboard_dir / "notifications.json").write_text(json.dumps(notif_data), encoding="utf-8")

    result = get_dashboard_summary(dashboard_dir)
    assert "Pending Notifications" in result
    assert "n_abc" in result
    assert "마감 알림" in result


def test_summary_groups_notifications_by_task(dashboard_dir):
    """Notifications for the same task are grouped together."""
    now = datetime.now()
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_abc",
                "message": "마감 알림",
                "scheduled_at": (now + timedelta(hours=2)).isoformat(),
                "type": "deadline_alert",
                "priority": "high",
                "status": "pending",
                "related_task_id": "task_001",
            },
            {
                "id": "n_def",
                "message": "진행 확인",
                "scheduled_at": (now + timedelta(hours=4)).isoformat(),
                "type": "progress_check",
                "priority": "medium",
                "status": "pending",
                "related_task_id": "task_001",
            },
        ],
    }
    (dashboard_dir / "notifications.json").write_text(json.dumps(notif_data), encoding="utf-8")

    result = get_dashboard_summary(dashboard_dir)
    # Both notifications under task_001 group
    assert "task_001" in result
    assert "n_abc" in result
    assert "n_def" in result
    # Task title in group header
    assert "블로그 작성" in result


def test_summary_shows_unrelated_notifications(dashboard_dir):
    """Notifications without related_task_id appear in '기타' group."""
    now = datetime.now()
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_xyz",
                "message": "일반 알림",
                "scheduled_at": (now + timedelta(hours=2)).isoformat(),
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
            }
        ],
    }
    (dashboard_dir / "notifications.json").write_text(json.dumps(notif_data), encoding="utf-8")

    result = get_dashboard_summary(dashboard_dir)
    assert "기타" in result
    assert "n_xyz" in result
    assert "일반 알림" in result


def test_summary_excludes_non_pending(dashboard_dir):
    """Only pending notifications are shown; delivered/cancelled are excluded."""
    now = datetime.now()
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_delivered",
                "message": "전달됨",
                "scheduled_at": (now - timedelta(hours=2)).isoformat(),
                "delivered_at": (now - timedelta(hours=1)).isoformat(),
                "type": "reminder",
                "priority": "medium",
                "status": "delivered",
            },
            {
                "id": "n_cancelled",
                "message": "취소됨",
                "scheduled_at": (now + timedelta(hours=5)).isoformat(),
                "type": "reminder",
                "priority": "low",
                "status": "cancelled",
            },
        ],
    }
    (dashboard_dir / "notifications.json").write_text(json.dumps(notif_data), encoding="utf-8")

    result = get_dashboard_summary(dashboard_dir)
    assert "n_delivered" not in result
    assert "n_cancelled" not in result
    assert "Pending Notifications" not in result


def test_summary_shows_task_title_in_group(dashboard_dir):
    """Task title appears in the notification group header."""
    now = datetime.now()
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_001",
                "message": "운동 리마인더",
                "scheduled_at": (now + timedelta(hours=1)).isoformat(),
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
                "related_task_id": "task_002",
            }
        ],
    }
    (dashboard_dir / "notifications.json").write_text(json.dumps(notif_data), encoding="utf-8")

    result = get_dashboard_summary(dashboard_dir)
    assert "task_002" in result
    assert "운동 루틴" in result


def test_summary_no_notifications_no_section(dashboard_dir):
    """When no pending notifications exist, the section is absent."""
    result = get_dashboard_summary(dashboard_dir)
    assert "Pending Notifications" not in result


def test_summary_notifications_error_resilient(dashboard_dir):
    """Tasks and questions still show when notifications.json is corrupted."""
    (dashboard_dir / "notifications.json").write_text("not valid json", encoding="utf-8")

    result = get_dashboard_summary(dashboard_dir)
    # Tasks should still be present
    assert "블로그 작성" in result
    assert "운동 루틴" in result
    # No crash, no notification section
    assert "Pending Notifications" not in result


# --- New tests: StorageBackend, on_error, edge cases ---


def _make_mock_backend(tasks=None, questions=None, notifications=None):
    """Create a MagicMock StorageBackend with given data."""
    backend = MagicMock(spec=StorageBackend)
    backend.load_tasks.return_value = tasks or {"tasks": []}
    backend.load_questions.return_value = questions or {"questions": []}
    backend.load_notifications.return_value = notifications or {"notifications": []}
    return backend


def test_summary_via_storage_backend():
    """Mock StorageBackend renders pending notifications correctly."""
    now = datetime.now()
    backend = _make_mock_backend(
        tasks={
            "tasks": [
                {
                    "id": "task_100",
                    "title": "Backend Task",
                    "status": "active",
                    "priority": "high",
                    "progress": {"percentage": 50},
                }
            ]
        },
        notifications={
            "notifications": [
                {
                    "id": "n_back",
                    "message": "백엔드 알림",
                    "scheduled_at": (now + timedelta(hours=1)).isoformat(),
                    "type": "reminder",
                    "priority": "medium",
                    "status": "pending",
                    "related_task_id": "task_100",
                }
            ]
        },
    )
    from pathlib import Path

    result = get_dashboard_summary(Path("/unused"), storage_backend=backend)
    assert "Pending Notifications" in result
    assert "n_back" in result
    assert "백엔드 알림" in result
    assert "Backend Task" in result


def test_summary_storage_backend_notification_exception():
    """load_notifications() exception → graceful degradation (tasks still shown)."""
    backend = _make_mock_backend(
        tasks={
            "tasks": [
                {
                    "id": "task_200",
                    "title": "Still Visible",
                    "status": "active",
                    "priority": "medium",
                    "progress": {"percentage": 10},
                }
            ]
        },
    )
    backend.load_notifications.side_effect = RuntimeError("Notion API down")

    from pathlib import Path

    result = get_dashboard_summary(Path("/unused"), storage_backend=backend)
    assert "Still Visible" in result
    assert "Pending Notifications" not in result


def test_on_error_callback_called_on_failure():
    """on_error callback is invoked when notification loading fails."""
    backend = _make_mock_backend()
    backend.load_notifications.side_effect = RuntimeError("boom")

    from pathlib import Path

    errors: list[str] = []
    get_dashboard_summary(Path("/unused"), storage_backend=backend, on_error=errors.append)
    assert len(errors) == 1
    assert "Failed to load pending notifications" in errors[0]


def test_invalid_scheduled_at_shows_raw_string(dashboard_dir):
    """Invalid scheduled_at falls back to raw string display."""
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_bad_date",
                "message": "날짜 오류",
                "scheduled_at": "not-a-date",
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
                "related_task_id": "task_001",
            }
        ],
    }
    (dashboard_dir / "notifications.json").write_text(json.dumps(notif_data), encoding="utf-8")

    result = get_dashboard_summary(dashboard_dir)
    assert "n_bad_date" in result
    assert "not-a-date" in result


def test_nonexistent_task_reference(dashboard_dir):
    """Notification referencing non-existent task renders header without title."""
    now = datetime.now()
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_orphan",
                "message": "고아 알림",
                "scheduled_at": (now + timedelta(hours=1)).isoformat(),
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
                "related_task_id": "task_999",
            }
        ],
    }
    (dashboard_dir / "notifications.json").write_text(json.dumps(notif_data), encoding="utf-8")

    result = get_dashboard_summary(dashboard_dir)
    assert "task_999" in result
    assert "n_orphan" in result
    # No empty parens — title-less header should be "**task_999**:"
    assert "():" not in result


def test_mixed_linked_and_unlinked_notifications(dashboard_dir):
    """Both task-linked and unlinked notifications render together."""
    now = datetime.now()
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_linked",
                "message": "연결 알림",
                "scheduled_at": (now + timedelta(hours=1)).isoformat(),
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
                "related_task_id": "task_001",
            },
            {
                "id": "n_unlinked",
                "message": "미연결 알림",
                "scheduled_at": (now + timedelta(hours=2)).isoformat(),
                "type": "reminder",
                "priority": "low",
                "status": "pending",
            },
        ],
    }
    (dashboard_dir / "notifications.json").write_text(json.dumps(notif_data), encoding="utf-8")

    result = get_dashboard_summary(dashboard_dir)
    assert "n_linked" in result
    assert "n_unlinked" in result
    assert "블로그 작성" in result
    assert "기타" in result


def test_missing_notifications_file_no_crash(tmp_path):
    """Dashboard without notifications.json still works (JSON file path)."""
    d = tmp_path / "dashboard"
    d.mkdir()
    (d / "tasks.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "tasks": [
                    {
                        "id": "task_solo",
                        "title": "Solo Task",
                        "status": "active",
                        "priority": "medium",
                        "progress": {"percentage": 0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (d / "questions.json").write_text(
        json.dumps({"version": "1.0", "questions": []}), encoding="utf-8"
    )
    # No notifications.json at all

    result = get_dashboard_summary(d)
    assert "Solo Task" in result
    assert "Pending Notifications" not in result


# --- _format_notification_line unit tests ---


def test_format_notification_line_valid_date():
    """Valid ISO date is formatted as MM-DD HH:MM."""
    n = {
        "id": "n_fmt",
        "type": "reminder",
        "message": "테스트",
        "scheduled_at": "2026-03-15T14:30:00",
    }
    result = _format_notification_line(n)
    assert "n_fmt" in result
    assert "03-15 14:30" in result
    assert "테스트" in result


def test_format_notification_line_invalid_date():
    """Invalid scheduled_at shows raw string."""
    n = {
        "id": "n_bad",
        "type": "reminder",
        "message": "잘못된 날짜",
        "scheduled_at": "invalid",
    }
    result = _format_notification_line(n)
    assert "[invalid]" in result


def test_format_notification_line_missing_fields():
    """Missing fields use defaults ('?')."""
    result = _format_notification_line({})
    assert "?" in result


# --- on_error negative test ---


def test_on_error_not_called_on_success():
    """on_error callback is NOT invoked when everything loads successfully."""
    backend = _make_mock_backend(
        tasks={
            "tasks": [
                {
                    "id": "task_ok",
                    "title": "OK",
                    "status": "active",
                    "priority": "medium",
                    "progress": {"percentage": 0},
                }
            ]
        },
    )

    from pathlib import Path

    errors: list[str] = []
    get_dashboard_summary(Path("/unused"), storage_backend=backend, on_error=errors.append)
    assert errors == []


# --- empty related_task_id coercion test ---


def test_empty_related_task_id_treated_as_unlinked(dashboard_dir):
    """Notification with related_task_id='' goes to '기타' group."""
    now = datetime.now()
    notif_data = {
        "version": "1.0",
        "notifications": [
            {
                "id": "n_empty_ref",
                "message": "빈 참조 알림",
                "scheduled_at": (now + timedelta(hours=1)).isoformat(),
                "type": "reminder",
                "priority": "medium",
                "status": "pending",
                "related_task_id": "",
            }
        ],
    }
    (dashboard_dir / "notifications.json").write_text(json.dumps(notif_data), encoding="utf-8")

    result = get_dashboard_summary(dashboard_dir)
    assert "기타" in result
    assert "n_empty_ref" in result
