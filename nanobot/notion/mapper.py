"""Bidirectional mapping between internal Pydantic schemas and Notion page properties.

All functions are pure and stateless. Two directions:
- `*_to_notion(data: dict) -> dict`: Convert internal dict to Notion properties.
- `notion_to_*(page: dict) -> dict`: Convert Notion page to internal dict.
"""

import json
from typing import Any

from loguru import logger

# ============================================================================
# Notion Property Builders (internal → Notion)
# ============================================================================


def _title(value: str) -> dict:
    return {"title": [{"text": {"content": value or ""}}]}


def _rich_text(value: str) -> dict:
    # Notion rich_text content limit is 2000 characters per segment
    text = value or ""
    if len(text) > 2000:
        logger.warning(f"Notion rich_text truncated: {len(text)} → 2000 chars")
        text = text[:2000]
    return {"rich_text": [{"text": {"content": text}}]}


def _number(value: int | float | None) -> dict:
    return {"number": value}


def _checkbox(value: bool) -> dict:
    return {"checkbox": value}


def _select(value: str | None) -> dict:
    if not value:
        return {"select": None}
    return {"select": {"name": value}}


def _multi_select(values: list[str]) -> dict:
    return {"multi_select": [{"name": v} for v in (values or [])]}


def _date(value: str | None) -> dict:
    if not value:
        return {"date": None}
    return {"date": {"start": value}}


# ============================================================================
# Notion Property Extractors (Notion → internal)
# ============================================================================


def _extract_title(prop: dict) -> str:
    parts = prop.get("title", [])
    return "".join(p.get("text", {}).get("content", "") for p in parts)


def _extract_rich_text(prop: dict) -> str:
    parts = prop.get("rich_text", [])
    return "".join(p.get("text", {}).get("content", "") for p in parts)


def _extract_number(prop: dict) -> int | float | None:
    return prop.get("number")


def _extract_checkbox(prop: dict) -> bool:
    return prop.get("checkbox", False)


def _extract_select(prop: dict) -> str | None:
    sel = prop.get("select")
    if sel:
        return sel.get("name")
    return None


def _extract_multi_select(prop: dict) -> list[str]:
    items = prop.get("multi_select", [])
    return [item.get("name", "") for item in items]


def _extract_date(prop: dict) -> str | None:
    date_obj = prop.get("date")
    if date_obj:
        return date_obj.get("start")
    return None


def _get_prop(properties: dict, name: str) -> dict:
    """Safely get a property from Notion properties dict."""
    return properties.get(name, {})


# ============================================================================
# Task Mapping
# ============================================================================


def task_to_notion(task: dict) -> dict[str, Any]:
    """Convert internal task dict to Notion properties."""
    progress = task.get("progress", {})
    estimation = task.get("estimation", {})

    props: dict[str, Any] = {
        "Title": _title(task.get("title", "")),
        "NanobotID": _rich_text(task.get("id", "")),
        "Status": _select(_capitalize(task.get("status", "active"))),
        "Priority": _select(_capitalize(task.get("priority", "medium"))),
        "Progress": _number(progress.get("percentage", 0)),
        "Blocked": _checkbox(progress.get("blocked", False)),
        "BlockerNote": _rich_text(progress.get("blocker_note", "") or ""),
        "ProgressNote": _rich_text(progress.get("note", "")),
        "Context": _rich_text(task.get("context", "")),
        "Tags": _multi_select(task.get("tags", [])),
        "Complexity": _select(_capitalize(estimation.get("complexity", "medium"))),
        "CreatedAt": _date(task.get("created_at")),
        "UpdatedAt": _date(task.get("updated_at")),
    }

    if task.get("deadline"):
        props["Deadline"] = _date(task["deadline"])
    if task.get("deadline_text"):
        props["DeadlineText"] = _rich_text(task["deadline_text"])
    if estimation.get("hours") is not None:
        props["EstimationHours"] = _number(estimation["hours"])
    if task.get("completed_at"):
        props["CompletedAt"] = _date(task["completed_at"])
    if task.get("reflection"):
        props["Reflection"] = _rich_text(task["reflection"])
    if task.get("recurring"):
        props["RecurringConfig"] = _rich_text(json.dumps(task["recurring"], ensure_ascii=False))

    return props


def notion_to_task(page: dict) -> dict[str, Any]:
    """Convert Notion page to internal task dict."""
    props = page.get("properties", {})

    percentage = _extract_number(_get_prop(props, "Progress"))

    return {
        "id": _extract_rich_text(_get_prop(props, "NanobotID")),
        "title": _extract_title(_get_prop(props, "Title")),
        "status": _lower(_extract_select(_get_prop(props, "Status")) or "active"),
        "priority": _lower(_extract_select(_get_prop(props, "Priority")) or "medium"),
        "deadline": _extract_date(_get_prop(props, "Deadline")),
        "deadline_text": _extract_rich_text(_get_prop(props, "DeadlineText")) or None,
        "estimation": {
            "hours": _extract_number(_get_prop(props, "EstimationHours")),
            "complexity": _lower(_extract_select(_get_prop(props, "Complexity")) or "medium"),
            "confidence": "medium",
        },
        "progress": {
            "percentage": int(percentage) if percentage is not None else 0,
            "last_update": _extract_date(_get_prop(props, "UpdatedAt")) or "",
            "note": _extract_rich_text(_get_prop(props, "ProgressNote")),
            "blocked": _extract_checkbox(_get_prop(props, "Blocked")),
            "blocker_note": _extract_rich_text(_get_prop(props, "BlockerNote")) or None,
        },
        "context": _extract_rich_text(_get_prop(props, "Context")),
        "tags": _extract_multi_select(_get_prop(props, "Tags")),
        "links": {"projects": [], "insights": [], "resources": []},
        "created_at": _extract_date(_get_prop(props, "CreatedAt")) or "",
        "updated_at": _extract_date(_get_prop(props, "UpdatedAt")) or "",
        "completed_at": _extract_date(_get_prop(props, "CompletedAt")),
        "reflection": _extract_rich_text(_get_prop(props, "Reflection")),
        "recurring": _parse_json_or_none(_extract_rich_text(_get_prop(props, "RecurringConfig"))),
        "_notion_page_id": page.get("id", ""),
    }


# ============================================================================
# Question Mapping
# ============================================================================


def question_to_notion(q: dict) -> dict[str, Any]:
    """Convert internal question dict to Notion properties."""
    props: dict[str, Any] = {
        "Question": _title(q.get("question", "")),
        "NanobotID": _rich_text(q.get("id", "")),
        "Priority": _select(_capitalize(q.get("priority", "medium"))),
        "Type": _select(q.get("type", "info_gather")),
        "RelatedTaskID": _rich_text(q.get("related_task_id") or ""),
        "Context": _rich_text(q.get("context", "")),
        "Answered": _checkbox(q.get("answered", False)),
        "Answer": _rich_text(q.get("answer", "") or ""),
        "AskedCount": _number(q.get("asked_count", 0)),
        "CooldownHours": _number(q.get("cooldown_hours", 24)),
        "CreatedAt": _date(q.get("created_at")),
    }

    if q.get("answered_at"):
        props["AnsweredAt"] = _date(q["answered_at"])
    if q.get("last_asked_at"):
        props["LastAskedAt"] = _date(q["last_asked_at"])

    return props


def notion_to_question(page: dict) -> dict[str, Any]:
    """Convert Notion page to internal question dict."""
    props = page.get("properties", {})

    asked_count = _extract_number(_get_prop(props, "AskedCount"))
    cooldown = _extract_number(_get_prop(props, "CooldownHours"))

    return {
        "id": _extract_rich_text(_get_prop(props, "NanobotID")),
        "question": _extract_title(_get_prop(props, "Question")),
        "context": _extract_rich_text(_get_prop(props, "Context")),
        "priority": _lower(_extract_select(_get_prop(props, "Priority")) or "medium"),
        "type": _extract_select(_get_prop(props, "Type")) or "info_gather",
        "related_task_id": _extract_rich_text(_get_prop(props, "RelatedTaskID")) or None,
        "asked_count": int(asked_count) if asked_count is not None else 0,
        "last_asked_at": _extract_date(_get_prop(props, "LastAskedAt")),
        "created_at": _extract_date(_get_prop(props, "CreatedAt")) or "",
        "cooldown_hours": int(cooldown) if cooldown is not None else 24,
        "answered": _extract_checkbox(_get_prop(props, "Answered")),
        "answer": _extract_rich_text(_get_prop(props, "Answer")) or None,
        "answered_at": _extract_date(_get_prop(props, "AnsweredAt")),
        "_notion_page_id": page.get("id", ""),
    }


# ============================================================================
# Notification Mapping
# ============================================================================


def notification_to_notion(n: dict) -> dict[str, Any]:
    """Convert internal notification dict to Notion properties."""
    props: dict[str, Any] = {
        "Message": _title(n.get("message", "")),
        "NanobotID": _rich_text(n.get("id", "")),
        "ScheduledAt": _date(n.get("scheduled_at")),
        "ScheduledAtText": _rich_text(n.get("scheduled_at_text") or ""),
        "Type": _select(n.get("type", "reminder")),
        "Priority": _select(_capitalize(n.get("priority", "medium"))),
        "Status": _select(_capitalize(n.get("status", "pending"))),
        "RelatedTaskID": _rich_text(n.get("related_task_id") or ""),
        "RelatedQuestionID": _rich_text(n.get("related_question_id") or ""),
        "Context": _rich_text(n.get("context", "")),
        "CreatedBy": _select(n.get("created_by", "worker")),
        "CreatedAt": _date(n.get("created_at")),
        "DeliveredAt": _date(n.get("delivered_at")),
        "CancelledAt": _date(n.get("cancelled_at")),
    }
    props["GCalEventID"] = _rich_text(n.get("gcal_event_id") or "")
    return props


def notion_to_notification(page: dict) -> dict[str, Any]:
    """Convert Notion page to internal notification dict."""
    props = page.get("properties", {})

    return {
        "id": _extract_rich_text(_get_prop(props, "NanobotID")),
        "message": _extract_title(_get_prop(props, "Message")),
        "scheduled_at": _extract_date(_get_prop(props, "ScheduledAt")) or "",
        "scheduled_at_text": _extract_rich_text(_get_prop(props, "ScheduledAtText")) or None,
        "type": _extract_select(_get_prop(props, "Type")) or "reminder",
        "priority": _lower(_extract_select(_get_prop(props, "Priority")) or "medium"),
        "status": _lower(_extract_select(_get_prop(props, "Status")) or "pending"),
        "related_task_id": _extract_rich_text(_get_prop(props, "RelatedTaskID")) or None,
        "related_question_id": _extract_rich_text(_get_prop(props, "RelatedQuestionID")) or None,
        "context": _extract_rich_text(_get_prop(props, "Context")),
        "created_by": _extract_select(_get_prop(props, "CreatedBy")) or "worker",
        "created_at": _extract_date(_get_prop(props, "CreatedAt")) or "",
        "delivered_at": _extract_date(_get_prop(props, "DeliveredAt")) or None,
        "cancelled_at": _extract_date(_get_prop(props, "CancelledAt")) or None,
        "gcal_event_id": _extract_rich_text(_get_prop(props, "GCalEventID")) or None,
        "_notion_page_id": page.get("id", ""),
    }


# ============================================================================
# Insight Mapping
# ============================================================================


def insight_to_notion(i: dict) -> dict[str, Any]:
    """Convert internal insight dict to Notion properties."""
    return {
        "Title": _title(i.get("title", "")),
        "NanobotID": _rich_text(i.get("id", "")),
        "Category": _select(i.get("category", "tech")),
        "Content": _rich_text(i.get("content", "")),
        "Source": _rich_text(i.get("source", "")),
        "Tags": _multi_select(i.get("tags", [])),
        "CreatedAt": _date(i.get("created_at")),
    }


def notion_to_insight(page: dict) -> dict[str, Any]:
    """Convert Notion page to internal insight dict."""
    props = page.get("properties", {})

    return {
        "id": _extract_rich_text(_get_prop(props, "NanobotID")),
        "category": _extract_select(_get_prop(props, "Category")) or "tech",
        "title": _extract_title(_get_prop(props, "Title")),
        "content": _extract_rich_text(_get_prop(props, "Content")),
        "source": _extract_rich_text(_get_prop(props, "Source")),
        "tags": _extract_multi_select(_get_prop(props, "Tags")),
        "links": {},
        "created_at": _extract_date(_get_prop(props, "CreatedAt")) or "",
        "_notion_page_id": page.get("id", ""),
    }


# ============================================================================
# Helpers
# ============================================================================


def _parse_json_or_none(text: str) -> dict | None:
    """Parse JSON string to dict, return None if empty or invalid."""
    if not text:
        return None
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Failed to parse JSON from Notion rich_text: {text[:100]}")
        return None


def _capitalize(value: str | None) -> str | None:
    """Capitalize first letter for Notion select values."""
    if not value:
        return value
    return value[0].upper() + value[1:]


def _lower(value: str | None) -> str | None:
    """Lowercase for internal schema values."""
    if not value:
        return value
    return value.lower()
