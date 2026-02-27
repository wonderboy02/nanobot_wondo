"""Pydantic schemas for Dashboard data validation."""

import re
from datetime import date as _date_type
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Task Schemas
# ============================================================================


class TaskEstimation(BaseModel):
    """Task estimation."""

    hours: Optional[int] = None
    complexity: Literal["low", "medium", "high"] = "medium"
    confidence: Literal["low", "medium", "high"] = "medium"


class TaskProgress(BaseModel):
    """Task progress."""

    percentage: int = Field(0, ge=0, le=100)
    last_update: str  # ISO datetime
    note: str = ""
    blocked: bool = False
    blocker_note: Optional[str] = None


class TaskLinks(BaseModel):
    """Task links to other entities."""

    projects: list[str] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)


class RecurringConfig(BaseModel):
    """Recurring (daily habit) configuration for a task."""

    enabled: bool = True
    frequency: Literal["daily"] = "daily"
    days_of_week: list[int] = Field(default_factory=lambda: list(range(7)))
    check_time: Optional[str] = None  # HH:MM
    streak_current: int = Field(0, ge=0)
    streak_best: int = Field(0, ge=0)
    total_completed: int = Field(0, ge=0)
    total_missed: int = Field(0, ge=0)
    last_completed_date: Optional[str] = None  # YYYY-MM-DD
    last_miss_date: Optional[str] = None  # YYYY-MM-DD

    @field_validator("days_of_week")
    @classmethod
    def validate_days_of_week(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("days_of_week must not be empty")
        for d in v:
            if not (0 <= d <= 6):
                raise ValueError(f"Invalid day {d}: must be 0 (Mon) – 6 (Sun)")
        return sorted(set(v))

    @field_validator("check_time")
    @classmethod
    def validate_check_time(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not re.match(r"^\d{2}:\d{2}$", v):
                raise ValueError(f"check_time must be HH:MM format, got {v!r}")
            hh, mm = v.split(":")
            if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                raise ValueError(f"check_time out of range: {v!r}")
        return v

    @field_validator("last_completed_date", "last_miss_date")
    @classmethod
    def validate_date_str(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                _date_type.fromisoformat(v)
            except ValueError:
                raise ValueError(f"Invalid date format {v!r}: expected YYYY-MM-DD")
        return v


class Task(BaseModel):
    """Task schema."""

    id: str
    title: str
    raw_input: Optional[str] = None
    deadline: Optional[str] = None  # YYYY-MM-DD or empty string
    deadline_text: Optional[str] = None
    estimation: TaskEstimation = Field(default_factory=TaskEstimation)
    progress: TaskProgress
    status: Literal["active", "someday", "completed", "cancelled", "archived"] = "active"
    priority: Literal["low", "medium", "high"] = "medium"
    context: str = ""
    tags: list[str] = Field(default_factory=list)
    links: TaskLinks = Field(default_factory=TaskLinks)
    created_at: str  # ISO datetime
    updated_at: str  # ISO datetime
    completed_at: Optional[str] = None  # ISO datetime
    reflection: str = ""
    recurring: Optional[RecurringConfig] = None

    @field_validator("deadline", mode="before")
    @classmethod
    def normalize_deadline(cls, v: Optional[str]) -> Optional[str]:
        """Auto-convert legacy datetime strings to YYYY-MM-DD."""
        if v is None or v == "":
            return v
        # Already YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            return v
        # Extract date portion from datetime string (e.g. 2026-02-15T09:00:00)
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", v)
        if m:
            return m.group(1)
        return v


class TasksFile(BaseModel):
    """tasks.json schema."""

    version: str = "1.0"
    tasks: list[Task] = Field(default_factory=list)


# ============================================================================
# Question Schemas
# ============================================================================


class Question(BaseModel):
    """Question schema."""

    id: str
    question: str
    context: str = ""
    priority: Literal["low", "medium", "high"] = "medium"
    type: Literal[
        "info_gather",
        "progress_check",
        "deadline_check",
        "start_check",
        "blocker_check",
        "status_check",
        "completion_check",
        "routine_check",
    ] = "info_gather"
    related_task_id: Optional[str] = None
    asked_count: int = 0
    last_asked_at: Optional[str] = None  # ISO datetime
    created_at: str  # ISO datetime
    cooldown_hours: int = 24
    answered: bool = False
    answer: Optional[str] = None
    answered_at: Optional[str] = None  # ISO datetime


class QuestionsFile(BaseModel):
    """questions.json schema."""

    version: str = "1.0"
    questions: list[Question] = Field(default_factory=list)


# ============================================================================
# Notification Schemas
# ============================================================================


class Notification(BaseModel):
    """Notification schema."""

    id: str
    message: str
    scheduled_at: str  # ISO datetime
    scheduled_at_text: Optional[str] = None  # Natural language (e.g., "내일 아침")
    type: Literal[
        "reminder", "deadline_alert", "progress_check", "blocker_followup", "question_reminder"
    ] = "reminder"
    priority: Literal["low", "medium", "high"] = "medium"
    related_task_id: Optional[str] = None
    related_question_id: Optional[str] = None
    status: Literal["pending", "delivered", "cancelled"] = "pending"
    created_at: str  # ISO datetime
    delivered_at: Optional[str] = None  # ISO datetime
    cancelled_at: Optional[str] = None  # ISO datetime
    context: str = ""
    created_by: Literal["worker", "user", "main_agent"] = "worker"
    gcal_event_id: Optional[str] = None


class NotificationsFile(BaseModel):
    """notifications.json schema."""

    version: str = "1.0"
    notifications: list[Notification] = Field(default_factory=list)


# ============================================================================
# Knowledge Schemas
# ============================================================================


class Insight(BaseModel):
    """Insight schema."""

    id: str
    category: Literal["tech", "life", "work", "learning"]
    title: str
    content: str
    source: str = ""
    tags: list[str] = Field(default_factory=list)
    links: dict = Field(default_factory=dict)
    created_at: str  # ISO datetime


class InsightsFile(BaseModel):
    """insights.json schema."""

    version: str = "1.0"
    insights: list[Insight] = Field(default_factory=list)


# ============================================================================
# Validation Functions
# ============================================================================


def validate_tasks_file(data: dict) -> TasksFile:
    """Validate tasks.json."""
    return TasksFile(**data)


def validate_questions_file(data: dict) -> QuestionsFile:
    """Validate questions.json."""
    return QuestionsFile(**data)


def validate_notifications_file(data: dict) -> NotificationsFile:
    """Validate notifications.json."""
    return NotificationsFile(**data)
