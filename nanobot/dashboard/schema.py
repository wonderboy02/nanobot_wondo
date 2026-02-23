"""Pydantic schemas for Dashboard data validation."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


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


class Task(BaseModel):
    """Task schema."""

    id: str
    title: str
    raw_input: Optional[str] = None
    deadline: Optional[str] = None  # ISO datetime
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
    cron_job_id: Optional[str] = None
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
