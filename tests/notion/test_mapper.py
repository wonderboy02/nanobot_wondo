"""Tests for Notion mapper (nanobot/notion/mapper.py).

Covers round-trip conversions for all entity types and edge cases.
"""

import pytest

from nanobot.notion.mapper import (
    task_to_notion,
    notion_to_task,
    question_to_notion,
    notion_to_question,
    notification_to_notion,
    notion_to_notification,
    insight_to_notion,
    notion_to_insight,
    completed_task_to_notion,
    notion_to_completed_task,
    person_to_notion,
    notion_to_person,
    _capitalize,
    _lower,
)


# ============================================================================
# Helper: wrap Notion properties into a fake page object
# ============================================================================

def _wrap_page(properties: dict, page_id: str = "page-abc") -> dict:
    """Wrap Notion properties dict into a page-like dict."""
    return {"id": page_id, "properties": properties}


# ============================================================================
# Task round-trip
# ============================================================================

class TestTaskMapping:
    """Tests for task_to_notion and notion_to_task."""

    SAMPLE_TASK = {
        "id": "task_001",
        "title": "Learn React",
        "status": "active",
        "priority": "high",
        "deadline": "2026-03-01",
        "deadline_text": "next month",
        "estimation": {"hours": 40, "complexity": "high", "confidence": "medium"},
        "progress": {
            "percentage": 50,
            "last_update": "2026-02-20",
            "note": "Watching tutorials",
            "blocked": True,
            "blocker_note": "Hooks are hard",
        },
        "context": "YouTube learning",
        "tags": ["react", "study"],
        "links": {"projects": [], "people": [], "insights": [], "resources": []},
        "created_at": "2026-02-01",
        "updated_at": "2026-02-20",
        "completed_at": None,
    }

    def test_task_round_trip(self):
        """task -> Notion -> task preserves key data."""
        notion_props = task_to_notion(self.SAMPLE_TASK)
        page = _wrap_page(notion_props, page_id="page-xyz")
        result = notion_to_task(page)

        assert result["id"] == "task_001"
        assert result["title"] == "Learn React"
        assert result["status"] == "active"
        assert result["priority"] == "high"
        assert result["deadline"] == "2026-03-01"
        assert result["deadline_text"] == "next month"
        assert result["progress"]["percentage"] == 50
        assert result["progress"]["blocked"] is True
        assert result["progress"]["blocker_note"] == "Hooks are hard"
        assert result["progress"]["note"] == "Watching tutorials"
        assert result["context"] == "YouTube learning"
        assert result["tags"] == ["react", "study"]
        assert result["created_at"] == "2026-02-01"
        assert result["updated_at"] == "2026-02-20"
        assert result["_notion_page_id"] == "page-xyz"

    def test_task_estimation_round_trip(self):
        """Estimation fields survive the round trip."""
        notion_props = task_to_notion(self.SAMPLE_TASK)
        page = _wrap_page(notion_props)
        result = notion_to_task(page)

        assert result["estimation"]["hours"] == 40
        assert result["estimation"]["complexity"] == "high"
        # confidence is hardcoded to "medium" in notion_to_task
        assert result["estimation"]["confidence"] == "medium"

    def test_task_status_capitalization(self):
        """Status gets capitalized for Notion and lowered back."""
        notion_props = task_to_notion({"status": "someday"})
        assert notion_props["Status"]["select"]["name"] == "Someday"

        page = _wrap_page(notion_props)
        result = notion_to_task(page)
        assert result["status"] == "someday"

    def test_task_empty_tags(self):
        """Empty tags list round-trips correctly."""
        notion_props = task_to_notion({"tags": []})
        assert notion_props["Tags"]["multi_select"] == []

        page = _wrap_page(notion_props)
        result = notion_to_task(page)
        assert result["tags"] == []

    def test_task_no_deadline(self):
        """Task with no deadline produces null date in Notion."""
        notion_props = task_to_notion({"title": "No deadline task"})
        # Deadline key should not be present (only set if task.get("deadline") is truthy)
        assert "Deadline" not in notion_props

    def test_task_with_completed_at(self):
        """completed_at field survives the round trip."""
        task = {**self.SAMPLE_TASK, "completed_at": "2026-02-20"}
        notion_props = task_to_notion(task)
        assert notion_props["CompletedAt"]["date"]["start"] == "2026-02-20"

        page = _wrap_page(notion_props)
        result = notion_to_task(page)
        assert result["completed_at"] == "2026-02-20"

    def test_task_missing_properties_returns_defaults(self):
        """notion_to_task with an empty properties dict returns safe defaults."""
        page = _wrap_page({})
        result = notion_to_task(page)

        assert result["id"] == ""
        assert result["title"] == ""
        assert result["status"] == "active"
        assert result["priority"] == "medium"
        assert result["progress"]["percentage"] == 0
        assert result["progress"]["blocked"] is False
        assert result["tags"] == []


# ============================================================================
# Question round-trip
# ============================================================================

class TestQuestionMapping:
    """Tests for question_to_notion and notion_to_question."""

    SAMPLE_QUESTION = {
        "id": "q_001",
        "question": "What resources are you using?",
        "context": "Task progress check",
        "priority": "medium",
        "type": "info_gather",
        "related_task_id": "task_001",
        "asked_count": 2,
        "last_asked_at": "2026-02-19",
        "created_at": "2026-02-01",
        "cooldown_hours": 24,
        "answered": True,
        "answer": "YouTube tutorials",
        "answered_at": "2026-02-20",
    }

    def test_question_round_trip(self):
        """question -> Notion -> question preserves key data."""
        notion_props = question_to_notion(self.SAMPLE_QUESTION)
        page = _wrap_page(notion_props, page_id="q-page-1")
        result = notion_to_question(page)

        assert result["id"] == "q_001"
        assert result["question"] == "What resources are you using?"
        assert result["context"] == "Task progress check"
        assert result["priority"] == "medium"
        assert result["type"] == "info_gather"
        assert result["asked_count"] == 2
        assert result["last_asked_at"] == "2026-02-19"
        assert result["cooldown_hours"] == 24
        assert result["answered"] is True
        assert result["answer"] == "YouTube tutorials"
        assert result["answered_at"] == "2026-02-20"
        assert result["_notion_page_id"] == "q-page-1"

    def test_question_unanswered(self):
        """Unanswered question with None answer round-trips."""
        q = {**self.SAMPLE_QUESTION, "answered": False, "answer": None, "answered_at": None}
        notion_props = question_to_notion(q)
        page = _wrap_page(notion_props)
        result = notion_to_question(page)

        assert result["answered"] is False
        assert result["answer"] is None  # empty rich_text -> None via `or None`
        assert result["answered_at"] is None  # AnsweredAt key not present in props

    def test_question_empty_context(self):
        """Empty context string round-trips."""
        q = {**self.SAMPLE_QUESTION, "context": ""}
        notion_props = question_to_notion(q)
        page = _wrap_page(notion_props)
        result = notion_to_question(page)
        assert result["context"] == ""

    def test_question_zero_asked_count(self):
        """asked_count of 0 round-trips correctly."""
        q = {**self.SAMPLE_QUESTION, "asked_count": 0}
        notion_props = question_to_notion(q)
        page = _wrap_page(notion_props)
        result = notion_to_question(page)
        assert result["asked_count"] == 0

    def test_question_missing_properties_defaults(self):
        """notion_to_question with empty properties returns defaults."""
        page = _wrap_page({})
        result = notion_to_question(page)
        assert result["id"] == ""
        assert result["question"] == ""
        assert result["type"] == "info_gather"
        assert result["asked_count"] == 0
        assert result["cooldown_hours"] == 24
        assert result["answered"] is False


# ============================================================================
# Notification round-trip
# ============================================================================

class TestNotificationMapping:
    """Tests for notification_to_notion and notion_to_notification."""

    SAMPLE_NOTIFICATION = {
        "id": "notif_001",
        "message": "Deadline approaching for React study",
        "scheduled_at": "2026-02-28T09:00:00",
        "type": "deadline_alert",
        "priority": "high",
        "status": "pending",
        "context": "Task task_001 deadline is March 1",
        "created_by": "worker",
        "created_at": "2026-02-20",
    }

    def test_notification_round_trip(self):
        """notification -> Notion -> notification preserves data."""
        notion_props = notification_to_notion(self.SAMPLE_NOTIFICATION)
        page = _wrap_page(notion_props, page_id="notif-page-1")
        result = notion_to_notification(page)

        assert result["id"] == "notif_001"
        assert result["message"] == "Deadline approaching for React study"
        assert result["scheduled_at"] == "2026-02-28T09:00:00"
        assert result["type"] == "deadline_alert"
        assert result["priority"] == "high"
        assert result["status"] == "pending"
        assert result["context"] == "Task task_001 deadline is March 1"
        assert result["created_by"] == "worker"
        assert result["_notion_page_id"] == "notif-page-1"

    def test_notification_status_capitalization(self):
        """Status is capitalized in Notion and lowered back."""
        notion_props = notification_to_notion({"status": "delivered"})
        assert notion_props["Status"]["select"]["name"] == "Delivered"

        page = _wrap_page(notion_props)
        result = notion_to_notification(page)
        assert result["status"] == "delivered"

    def test_notification_empty_context(self):
        """Empty context string round-trips."""
        n = {**self.SAMPLE_NOTIFICATION, "context": ""}
        notion_props = notification_to_notion(n)
        page = _wrap_page(notion_props)
        result = notion_to_notification(page)
        assert result["context"] == ""

    def test_notification_missing_properties_defaults(self):
        """Missing properties return safe defaults."""
        page = _wrap_page({})
        result = notion_to_notification(page)
        assert result["type"] == "reminder"
        assert result["priority"] == "medium"
        assert result["status"] == "pending"
        assert result["created_by"] == "worker"


# ============================================================================
# Insight round-trip
# ============================================================================

class TestInsightMapping:
    """Tests for insight_to_notion and notion_to_insight."""

    SAMPLE_INSIGHT = {
        "id": "insight_001",
        "category": "tech",
        "title": "React Hooks pattern",
        "content": "useEffect cleanup prevents memory leaks",
        "source": "React docs",
        "tags": ["react", "hooks"],
        "created_at": "2026-02-15",
    }

    def test_insight_round_trip(self):
        """insight -> Notion -> insight preserves data."""
        notion_props = insight_to_notion(self.SAMPLE_INSIGHT)
        page = _wrap_page(notion_props, page_id="insight-page-1")
        result = notion_to_insight(page)

        assert result["id"] == "insight_001"
        assert result["category"] == "tech"
        assert result["title"] == "React Hooks pattern"
        assert result["content"] == "useEffect cleanup prevents memory leaks"
        assert result["source"] == "React docs"
        assert result["tags"] == ["react", "hooks"]
        assert result["_notion_page_id"] == "insight-page-1"

    def test_insight_empty_tags(self):
        """Empty tags list round-trips."""
        i = {**self.SAMPLE_INSIGHT, "tags": []}
        notion_props = insight_to_notion(i)
        page = _wrap_page(notion_props)
        result = notion_to_insight(page)
        assert result["tags"] == []

    def test_insight_empty_source(self):
        """Empty source string round-trips."""
        i = {**self.SAMPLE_INSIGHT, "source": ""}
        notion_props = insight_to_notion(i)
        page = _wrap_page(notion_props)
        result = notion_to_insight(page)
        assert result["source"] == ""

    def test_insight_missing_properties_defaults(self):
        """Missing properties return safe defaults."""
        page = _wrap_page({})
        result = notion_to_insight(page)
        assert result["category"] == "tech"
        assert result["title"] == ""
        assert result["content"] == ""
        assert result["tags"] == []


# ============================================================================
# CompletedTask round-trip
# ============================================================================

class TestCompletedTaskMapping:
    """Tests for completed_task_to_notion and notion_to_completed_task."""

    SAMPLE_COMPLETED = {
        "id": "task_old_001",
        "title": "Set up dev environment",
        "completed_at": "2026-01-15",
        "duration_days": 3,
        "progress_note": "Everything installed and configured",
        "reflection": "Should have used Docker from the start",
        "moved_at": "2026-01-16",
    }

    def test_completed_task_round_trip(self):
        """completed_task -> Notion -> completed_task preserves data."""
        notion_props = completed_task_to_notion(self.SAMPLE_COMPLETED)
        page = _wrap_page(notion_props, page_id="ct-page-1")
        result = notion_to_completed_task(page)

        assert result["id"] == "task_old_001"
        assert result["title"] == "Set up dev environment"
        assert result["completed_at"] == "2026-01-15"
        assert result["duration_days"] == 3
        assert result["progress_note"] == "Everything installed and configured"
        assert result["moved_at"] == "2026-01-16"
        assert result["_notion_page_id"] == "ct-page-1"

    def test_completed_task_zero_duration(self):
        """Zero duration_days round-trips correctly."""
        ct = {**self.SAMPLE_COMPLETED, "duration_days": 0}
        notion_props = completed_task_to_notion(ct)
        page = _wrap_page(notion_props)
        result = notion_to_completed_task(page)
        assert result["duration_days"] == 0

    def test_completed_task_missing_properties_defaults(self):
        """Missing properties return safe defaults."""
        page = _wrap_page({})
        result = notion_to_completed_task(page)
        assert result["id"] == ""
        assert result["title"] == ""
        assert result["duration_days"] == 0


# ============================================================================
# Person round-trip
# ============================================================================

class TestPersonMapping:
    """Tests for person_to_notion and notion_to_person."""

    SAMPLE_PERSON = {
        "id": "person_001",
        "name": "Alice Kim",
        "role": "Team Lead",
        "relationship": "Colleague",
        "context": "Works on frontend team",
        "contact": "alice@example.com",
        "notes": "Expert in React and TypeScript",
        "last_contact": "2026-02-10",
    }

    def test_person_round_trip(self):
        """person -> Notion -> person preserves data."""
        notion_props = person_to_notion(self.SAMPLE_PERSON)
        page = _wrap_page(notion_props, page_id="person-page-1")
        result = notion_to_person(page)

        assert result["id"] == "person_001"
        assert result["name"] == "Alice Kim"
        assert result["role"] == "Team Lead"
        assert result["relationship"] == "Colleague"
        assert result["context"] == "Works on frontend team"
        assert result["contact"] == "alice@example.com"
        assert result["notes"] == "Expert in React and TypeScript"
        assert result["last_contact"] == "2026-02-10"
        assert result["_notion_page_id"] == "person-page-1"

    def test_person_no_last_contact(self):
        """Person without last_contact."""
        p = {**self.SAMPLE_PERSON, "last_contact": None}
        notion_props = person_to_notion(p)
        assert notion_props["LastContact"]["date"] is None

        page = _wrap_page(notion_props)
        result = notion_to_person(page)
        assert result["last_contact"] is None

    def test_person_empty_fields(self):
        """Person with all optional fields empty."""
        p = {
            "id": "person_002",
            "name": "Bob",
            "role": "",
            "relationship": "",
            "context": "",
            "contact": "",
            "notes": "",
            "last_contact": None,
        }
        notion_props = person_to_notion(p)
        page = _wrap_page(notion_props)
        result = notion_to_person(page)

        assert result["name"] == "Bob"
        assert result["role"] == ""
        assert result["context"] == ""

    def test_person_missing_properties_defaults(self):
        """Missing properties return safe defaults."""
        page = _wrap_page({})
        result = notion_to_person(page)
        assert result["id"] == ""
        assert result["name"] == ""
        assert result["role"] == ""
        assert result["last_contact"] is None


# ============================================================================
# Edge cases: None values, empty strings
# ============================================================================

class TestEdgeCases:
    """Edge cases for mapper helper functions and property builders."""

    def test_capitalize_none(self):
        assert _capitalize(None) is None

    def test_capitalize_empty(self):
        assert _capitalize("") == ""  # falsy returns the value itself

    def test_capitalize_normal(self):
        assert _capitalize("active") == "Active"
        assert _capitalize("high") == "High"

    def test_lower_none(self):
        assert _lower(None) is None

    def test_lower_empty(self):
        assert _lower("") == ""  # falsy returns the value itself

    def test_lower_normal(self):
        assert _lower("Active") == "active"
        assert _lower("HIGH") == "high"

    def test_task_to_notion_with_none_values(self):
        """task_to_notion handles None/missing values gracefully."""
        task = {}
        props = task_to_notion(task)
        # Title should be empty string wrapped in Notion format
        assert props["Title"]["title"][0]["text"]["content"] == ""
        assert props["NanobotID"]["rich_text"][0]["text"]["content"] == ""

    def test_notion_to_task_none_progress(self):
        """notion_to_task with Progress=None returns 0."""
        props = {"Progress": {"number": None}}
        page = _wrap_page(props)
        result = notion_to_task(page)
        assert result["progress"]["percentage"] == 0

    def test_question_to_notion_none_answer(self):
        """question_to_notion with answer=None produces empty rich_text."""
        q = {"answer": None}
        props = question_to_notion(q)
        assert props["Answer"]["rich_text"][0]["text"]["content"] == ""

    def test_notion_to_question_empty_answer_becomes_none(self):
        """Empty answer rich_text becomes None in internal dict."""
        props = {"Answer": {"rich_text": [{"text": {"content": ""}}]}}
        page = _wrap_page(props)
        result = notion_to_question(page)
        assert result["answer"] is None  # "" or None -> None

    def test_multi_segment_rich_text(self):
        """Rich text with multiple segments is concatenated."""
        props = {
            "Name": {
                "title": [
                    {"text": {"content": "Hello "}},
                    {"text": {"content": "World"}},
                ]
            }
        }
        page = _wrap_page(props)
        result = notion_to_person(page)
        assert result["name"] == "Hello World"
