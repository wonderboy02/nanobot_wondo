# Available Tools

## File Operations

```python
read_file(path: str) -> str
write_file(path: str, content: str) -> str
edit_file(path: str, old_text: str, new_text: str) -> str
list_dir(path: str) -> str
```

## Shell Execution

```python
exec(command: str, working_dir: str = None) -> str
```
⚠️ Dangerous commands blocked. 60s timeout. Output truncated at 10KB.

## Web Access

```python
web_search(query: str, count: int = 5) -> str
web_fetch(url: str, extractMode: str = "markdown") -> str
```

## Messaging

```python
message(text: str, channel: str, to: str) -> str
```
Send messages to chat channels (telegram, discord, etc.).

## Background Tasks

```python
spawn(task_description: str, skill_names: list[str] = None) -> str
```
Spawn a subagent for complex background tasks.

## Dashboard Management

### Task Management
```python
create_task(title: str, deadline: str = "", priority: str = "medium",
            context: str = "", tags: list[str] = []) -> str

update_task(task_id: str, progress: int = None, status: str = None,
            blocked: bool = None, blocker_note: str = None,
            context: str = None, deadline: str = None,
            priority: str = None, tags: list[str] = None) -> str

archive_task(task_id: str, reflection: str = "") -> str
```

**Status values**: `active`, `completed`, `someday`, `cancelled`, `archived`
**Priority values**: `low`, `medium`, `high`

### Question Management
```python
answer_question(question_id: str, answer: str) -> str

create_question(question: str, priority: str = "medium",
                type: str = "info_gather",
                related_task_id: str = None) -> str

update_question(question_id: str, priority: str = None,
                type: str = None, cooldown_hours: int = None,
                context: str = None) -> str

remove_question(question_id: str, reason: str = "") -> str
```

**Question Types**: `info_gather`, `progress_check`, `deadline_check`, `blocker_check`, etc.

### Notification Management
```python
schedule_notification(message: str, scheduled_at: str,
                     type: str = "reminder", priority: str = "medium",
                     related_task_id: str = None,
                     related_question_id: str = None,
                     context: str = "") -> str

update_notification(notification_id: str, message: str = None,
                   scheduled_at: str = None, priority: str = None) -> str

cancel_notification(notification_id: str, reason: str = "") -> str

list_notifications(status: str = None, related_task_id: str = None) -> str
```

**Notification Types**: `reminder`, `deadline_alert`, `progress_check`, `blocker_followup`, `question_reminder`
**Status values**: `pending`, `delivered`, `cancelled`

**When to use:**
- Schedule reminders for deadlines, progress checks, or follow-ups
- Notifications are delivered via Cron at exact scheduled time
- Always check `list_notifications()` before creating new ones to avoid duplicates

