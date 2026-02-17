"""Pydantic schemas for Dashboard data validation."""

from datetime import datetime
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
    people: list[str] = Field(default_factory=list)
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
    status: Literal["active", "someday", "completed", "cancelled"] = "active"
    priority: Literal["low", "medium", "high"] = "medium"
    context: str = ""
    tags: list[str] = Field(default_factory=list)
    links: TaskLinks = Field(default_factory=TaskLinks)
    created_at: str  # ISO datetime
    updated_at: str  # ISO datetime
    completed_at: Optional[str] = None  # ISO datetime


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
        "routine_check"
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
    type: Literal["reminder", "deadline_alert", "progress_check", "blocker_followup", "question_reminder"] = "reminder"
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


class NotificationsFile(BaseModel):
    """notifications.json schema."""
    version: str = "1.0"
    notifications: list[Notification] = Field(default_factory=list)


# ============================================================================
# Knowledge Schemas
# ============================================================================

class CompletedTask(BaseModel):
    """Completed task in history."""
    id: str
    title: str
    completed_at: str  # ISO datetime
    duration_days: int
    progress_note: str = ""
    links: dict = Field(default_factory=dict)
    moved_at: str  # ISO datetime


class Project(BaseModel):
    """Project schema."""
    id: str
    name: str
    description: str = ""
    status: Literal["active", "completed", "cancelled"] = "active"
    task_ids: list[str] = Field(default_factory=list)
    created_at: str  # ISO datetime
    updated_at: str  # ISO datetime


class HistoryFile(BaseModel):
    """history.json schema."""
    version: str = "1.0"
    completed_tasks: list[CompletedTask] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)


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


class Person(BaseModel):
    """Person schema."""
    id: str
    name: str
    role: str = ""
    relationship: str = ""
    context: str = ""
    contact: str = ""
    links: dict = Field(default_factory=dict)
    notes: str = ""
    last_contact: Optional[str] = None


class PeopleFile(BaseModel):
    """people.json schema."""
    version: str = "1.0"
    people: list[Person] = Field(default_factory=list)


# ============================================================================
# Complete Dashboard Schema
# ============================================================================

class Dashboard(BaseModel):
    """Complete dashboard schema."""
    tasks: list[Task]
    questions: list[Question]
    notifications: list[Notification] = Field(default_factory=list)
    knowledge: dict  # Contains history, insights, people


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


def validate_history_file(data: dict) -> HistoryFile:
    """Validate history.json."""
    return HistoryFile(**data)


def validate_insights_file(data: dict) -> InsightsFile:
    """Validate insights.json."""
    return InsightsFile(**data)


def validate_people_file(data: dict) -> PeopleFile:
    """Validate people.json."""
    return PeopleFile(**data)


def validate_dashboard(dashboard: dict) -> Dashboard:
    """Validate complete dashboard."""
    return Dashboard(**dashboard)
