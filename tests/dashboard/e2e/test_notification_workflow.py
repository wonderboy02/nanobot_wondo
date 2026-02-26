"""E2E tests for notification workflow with Worker and Main Agent."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from nanobot.dashboard.storage import JsonStorageBackend
from nanobot.dashboard.worker import WorkerAgent
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_response(content: str, tool_calls: list[dict] | None = None) -> LLMResponse:
    """Build an LLMResponse from simplified dict spec used in tests."""
    tc_objects = []
    for tc in tool_calls or []:
        tc_objects.append(
            ToolCallRequest(
                id=tc.get("id", ""),
                name=tc["name"],
                arguments=tc.get("arguments", {}),
            )
        )
    return LLMResponse(content=content, tool_calls=tc_objects)


@pytest.fixture
async def test_environment(tmp_path):
    """Set up test environment with workspace, dashboard, and mock components."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create dashboard structure
    dashboard_path = workspace / "dashboard"
    dashboard_path.mkdir()

    # Initialize dashboard files
    tasks_file = dashboard_path / "tasks.json"
    tasks_file.write_text(json.dumps({"version": "1.0", "tasks": []}), encoding="utf-8")

    questions_file = dashboard_path / "questions.json"
    questions_file.write_text(json.dumps({"version": "1.0", "questions": []}), encoding="utf-8")

    notifications_file = dashboard_path / "notifications.json"
    notifications_file.write_text(
        json.dumps({"version": "1.0", "notifications": []}), encoding="utf-8"
    )

    # Create workspace instruction files
    (workspace / "WORKER.md").write_text("# Worker Instructions\nYou are the Worker Agent.")
    (workspace / "AGENTS.md").write_text("# Agent Instructions")
    (workspace / "DASHBOARD.md").write_text("# Dashboard Management")
    (workspace / "TOOLS.md").write_text("# Available Tools")

    # Mock components
    mock_provider = AsyncMock()

    return {
        "workspace": workspace,
        "dashboard_path": dashboard_path,
        "provider": mock_provider,
    }


class TestNotificationWorkflow:
    """Test complete notification workflow."""

    @pytest.mark.asyncio
    async def test_worker_schedules_deadline_notification(self, test_environment):
        """Test Worker detects deadline and schedules notification."""
        workspace = test_environment["workspace"]
        dashboard_path = test_environment["dashboard_path"]
        provider = test_environment["provider"]

        # Create task with deadline tomorrow
        tomorrow = (datetime.now() + timedelta(days=1)).isoformat()
        tasks_file = dashboard_path / "tasks.json"
        tasks_data = {
            "version": "1.0",
            "tasks": [
                {
                    "id": "task_001",
                    "title": "블로그 작성",
                    "deadline": tomorrow,
                    "deadline_text": "내일",
                    "status": "active",
                    "priority": "high",
                    "progress": {
                        "percentage": 70,
                        "last_update": (datetime.now() - timedelta(days=1)).isoformat(),
                        "note": "",
                        "blocked": False,
                    },
                    "estimation": {"hours": None, "complexity": "medium", "confidence": "medium"},
                    "context": "React Tutorial 시리즈",
                    "tags": [],
                    "links": {"projects": [], "insights": [], "resources": []},
                    "created_at": (datetime.now() - timedelta(days=3)).isoformat(),
                    "updated_at": (datetime.now() - timedelta(days=1)).isoformat(),
                }
            ],
        }
        tasks_file.write_text(json.dumps(tasks_data), encoding="utf-8")

        # Mock LLM response: Worker decides to schedule notification
        schedule_time = (datetime.now() + timedelta(hours=1)).isoformat()
        provider.chat = AsyncMock(
            side_effect=[
                # First response: Worker calls schedule_notification
                _make_response(
                    "I'll schedule a deadline notification.",
                    [
                        {
                            "id": "call_1",
                            "name": "schedule_notification",
                            "arguments": {
                                "message": "블로그 작성 마감이 내일이에요! 현재 70%입니다.",
                                "scheduled_at": schedule_time,
                                "type": "deadline_alert",
                                "priority": "high",
                                "related_task_id": "task_001",
                            },
                        }
                    ],
                ),
                # Second response: Worker finishes
                _make_response("Deadline notification scheduled successfully."),
            ]
        )

        # Create Worker Agent
        backend = JsonStorageBackend(workspace)
        worker = WorkerAgent(
            workspace=workspace,
            storage_backend=backend,
            provider=provider,
            model="test-model",
        )

        # Run Worker cycle
        await worker.run_cycle()

        # Verify notification created
        notifications_file = dashboard_path / "notifications.json"
        notifications_data = json.loads(notifications_file.read_text(encoding="utf-8"))
        assert len(notifications_data["notifications"]) == 1

        notif = notifications_data["notifications"][0]
        assert "블로그" in notif["message"]
        assert notif["type"] == "deadline_alert"
        assert notif["priority"] == "high"
        assert notif["related_task_id"] == "task_001"
        assert notif["status"] == "pending"

    @pytest.mark.asyncio
    async def test_worker_avoids_duplicate_notifications(self, test_environment):
        """Test Worker checks existing notifications before creating new ones."""
        workspace = test_environment["workspace"]
        dashboard_path = test_environment["dashboard_path"]
        provider = test_environment["provider"]

        # Create task with deadline
        tomorrow = (datetime.now() + timedelta(days=1)).isoformat()
        tasks_file = dashboard_path / "tasks.json"
        tasks_data = {
            "version": "1.0",
            "tasks": [
                {
                    "id": "task_001",
                    "title": "블로그 작성",
                    "deadline": tomorrow,
                    "status": "active",
                    "priority": "high",
                    "progress": {
                        "percentage": 70,
                        "last_update": datetime.now().isoformat(),
                        "note": "",
                        "blocked": False,
                    },
                    "estimation": {"hours": None, "complexity": "medium", "confidence": "medium"},
                    "context": "",
                    "tags": [],
                    "links": {"projects": [], "insights": [], "resources": []},
                    "created_at": (datetime.now() - timedelta(days=2)).isoformat(),
                    "updated_at": datetime.now().isoformat(),
                }
            ],
        }
        tasks_file.write_text(json.dumps(tasks_data), encoding="utf-8")

        # Create existing notification
        notifications_file = dashboard_path / "notifications.json"
        notifications_data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_existing",
                    "message": "블로그 마감이 내일이에요!",
                    "scheduled_at": (datetime.now() + timedelta(hours=12)).isoformat(),
                    "type": "deadline_alert",
                    "priority": "high",
                    "related_task_id": "task_001",
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(notifications_data), encoding="utf-8")

        # Mock LLM response: Worker checks notifications and decides to skip
        provider.chat = AsyncMock(
            side_effect=[
                # First response: Worker calls list_notifications
                _make_response(
                    "Let me check existing notifications first.",
                    [
                        {
                            "id": "call_1",
                            "name": "list_notifications",
                            "arguments": {"related_task_id": "task_001", "status": "pending"},
                        }
                    ],
                ),
                # Second response: Worker sees existing notification and finishes
                _make_response(
                    "Deadline notification already exists for this task. No action needed.",
                ),
            ]
        )

        backend = JsonStorageBackend(workspace)
        worker = WorkerAgent(
            workspace=workspace,
            storage_backend=backend,
            provider=provider,
            model="test-model",
        )

        # Run Worker cycle
        await worker.run_cycle()

        # Verify no duplicate notification created
        notifications_data = json.loads(notifications_file.read_text(encoding="utf-8"))
        assert len(notifications_data["notifications"]) == 1
        assert notifications_data["notifications"][0]["id"] == "n_existing"

    @pytest.mark.asyncio
    async def test_worker_creates_blocker_followup(self, test_environment):
        """Test Worker creates blocker follow-up notification."""
        workspace = test_environment["workspace"]
        dashboard_path = test_environment["dashboard_path"]
        provider = test_environment["provider"]

        # Create blocked task
        blocked_since = (datetime.now() - timedelta(days=2, hours=1)).isoformat()
        tasks_file = dashboard_path / "tasks.json"
        tasks_data = {
            "version": "1.0",
            "tasks": [
                {
                    "id": "task_002",
                    "title": "React 공부",
                    "deadline": None,
                    "status": "active",
                    "priority": "medium",
                    "progress": {
                        "percentage": 50,
                        "last_update": blocked_since,
                        "note": "",
                        "blocked": True,
                        "blocker_note": "Hook 이해 어려움",
                    },
                    "estimation": {"hours": None, "complexity": "medium", "confidence": "medium"},
                    "context": "유튜브 강의",
                    "tags": ["react", "study"],
                    "links": {"projects": [], "insights": [], "resources": []},
                    "created_at": (datetime.now() - timedelta(days=5)).isoformat(),
                    "updated_at": blocked_since,
                }
            ],
        }
        tasks_file.write_text(json.dumps(tasks_data), encoding="utf-8")

        # Mock LLM response
        followup_time = (datetime.now() + timedelta(hours=2)).isoformat()
        provider.chat = AsyncMock(
            side_effect=[
                _make_response(
                    "Task blocked for 48+ hours. Scheduling follow-up.",
                    [
                        {
                            "id": "call_1",
                            "name": "schedule_notification",
                            "arguments": {
                                "message": "'React 공부' 작업이 2일째 막혀있어요. Hook 자료 찾는 거 어떻게 되고 있나요?",
                                "scheduled_at": followup_time,
                                "type": "blocker_followup",
                                "priority": "medium",
                                "related_task_id": "task_002",
                                "context": "Task blocked for 49 hours",
                            },
                        }
                    ],
                ),
                _make_response("Blocker follow-up scheduled."),
            ]
        )

        backend = JsonStorageBackend(workspace)
        worker = WorkerAgent(
            workspace=workspace,
            storage_backend=backend,
            provider=provider,
            model="test-model",
        )

        await worker.run_cycle()

        # Verify blocker follow-up created
        notifications_file = dashboard_path / "notifications.json"
        notifications_data = json.loads(notifications_file.read_text(encoding="utf-8"))
        assert len(notifications_data["notifications"]) == 1

        notif = notifications_data["notifications"][0]
        assert notif["type"] == "blocker_followup"
        assert notif["related_task_id"] == "task_002"
        assert "Hook" in notif["message"] or "막혀" in notif["message"]

    @pytest.mark.asyncio
    async def test_worker_removes_obsolete_questions(self, test_environment):
        """Test Worker removes obsolete questions."""
        workspace = test_environment["workspace"]
        dashboard_path = test_environment["dashboard_path"]
        provider = test_environment["provider"]

        # Create completed task
        tasks_file = dashboard_path / "tasks.json"
        tasks_data = {
            "version": "1.0",
            "tasks": [
                {
                    "id": "task_003",
                    "title": "Completed task",
                    "status": "completed",
                    "priority": "medium",
                    "progress": {
                        "percentage": 100,
                        "last_update": datetime.now().isoformat(),
                        "note": "",
                        "blocked": False,
                    },
                    "estimation": {"hours": None, "complexity": "medium", "confidence": "medium"},
                    "context": "",
                    "tags": [],
                    "links": {"projects": [], "insights": [], "resources": []},
                    "created_at": (datetime.now() - timedelta(days=5)).isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "completed_at": datetime.now().isoformat(),
                }
            ],
        }
        tasks_file.write_text(json.dumps(tasks_data), encoding="utf-8")

        # Create obsolete question
        questions_file = dashboard_path / "questions.json"
        questions_data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "How is the task going?",
                    "priority": "medium",
                    "type": "progress_check",
                    "related_task_id": "task_003",
                    "answered": False,
                    "created_at": (datetime.now() - timedelta(days=2)).isoformat(),
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(questions_data), encoding="utf-8")

        # Mock LLM response
        provider.chat = AsyncMock(
            side_effect=[
                _make_response(
                    "Task completed, removing obsolete question.",
                    [
                        {
                            "id": "call_1",
                            "name": "remove_question",
                            "arguments": {
                                "question_id": "q_001",
                                "reason": "Task completed - question no longer relevant",
                            },
                        }
                    ],
                ),
                _make_response("Obsolete question removed."),
            ]
        )

        backend = JsonStorageBackend(workspace)
        worker = WorkerAgent(
            workspace=workspace,
            storage_backend=backend,
            provider=provider,
            model="test-model",
        )

        await worker.run_cycle()

        # Verify question removed
        questions_data = json.loads(questions_file.read_text())
        assert len(questions_data["questions"]) == 0

    @pytest.mark.asyncio
    async def test_notification_cancellation_on_task_completion(self, test_environment):
        """Test Worker cancels notifications when task is completed."""
        workspace = test_environment["workspace"]
        dashboard_path = test_environment["dashboard_path"]
        provider = test_environment["provider"]

        # Create completed task
        tasks_file = dashboard_path / "tasks.json"
        tasks_data = {
            "version": "1.0",
            "tasks": [
                {
                    "id": "task_004",
                    "title": "Just completed task",
                    "status": "completed",
                    "priority": "high",
                    "progress": {
                        "percentage": 100,
                        "last_update": datetime.now().isoformat(),
                        "note": "",
                        "blocked": False,
                    },
                    "estimation": {"hours": None, "complexity": "medium", "confidence": "medium"},
                    "context": "",
                    "tags": [],
                    "links": {"projects": [], "insights": [], "resources": []},
                    "created_at": (datetime.now() - timedelta(days=3)).isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "completed_at": datetime.now().isoformat(),
                }
            ],
        }
        tasks_file.write_text(json.dumps(tasks_data), encoding="utf-8")

        # Create pending notification for this task
        notifications_file = dashboard_path / "notifications.json"
        notifications_data = {
            "version": "1.0",
            "notifications": [
                {
                    "id": "n_pending",
                    "message": "Task deadline approaching",
                    "scheduled_at": (datetime.now() + timedelta(hours=5)).isoformat(),
                    "type": "deadline_alert",
                    "priority": "high",
                    "related_task_id": "task_004",
                    "status": "pending",
                    "created_at": (datetime.now() - timedelta(hours=1)).isoformat(),
                    "created_by": "worker",
                }
            ],
        }
        notifications_file.write_text(json.dumps(notifications_data), encoding="utf-8")

        # Mock LLM response
        provider.chat = AsyncMock(
            side_effect=[
                _make_response(
                    "Task completed, cancelling pending notification.",
                    [
                        {
                            "id": "call_1",
                            "name": "cancel_notification",
                            "arguments": {
                                "notification_id": "n_pending",
                                "reason": "Task task_004 completed",
                            },
                        }
                    ],
                ),
                _make_response("Notification cancelled."),
            ]
        )

        backend = JsonStorageBackend(workspace)
        worker = WorkerAgent(
            workspace=workspace,
            storage_backend=backend,
            provider=provider,
            model="test-model",
        )

        await worker.run_cycle()

        # Verify notification cancelled
        notifications_data = json.loads(notifications_file.read_text(encoding="utf-8"))
        notif = notifications_data["notifications"][0]
        assert notif["status"] == "cancelled"
        assert notif["cancelled_at"] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
