---
name: cron
description: Schedule reminders and notifications.
---

# Cron

Use the `schedule_notification` tool to schedule reminders and notifications.

> **Note**: Notification tools are available only in gateway mode (when cron_service is active).
> In CLI agent mode (`nanobot agent`), these tools are not registered.

## Tools

- `schedule_notification(message, scheduled_at, ...)` - Schedule a notification
- `update_notification(notification_id, ...)` - Update a scheduled notification
- `cancel_notification(notification_id)` - Cancel a notification
- `list_notifications(status, related_task_id)` - List notifications

## Examples

Remind user tomorrow morning:
```
schedule_notification(message="Time to take a break!", scheduled_at="tomorrow 9am")
```

Deadline alert:
```
schedule_notification(message="React 공부 deadline!", scheduled_at="2026-02-15T18:00:00", type="deadline_alert", related_task_id="task_001")
```

List pending notifications:
```
list_notifications(status="pending")
```

Cancel a notification:
```
cancel_notification(notification_id="n_12345678")
```

## Time Expressions

| User says | scheduled_at |
|-----------|------------|
| in 2 hours | "in 2 hours" |
| tomorrow 9am | "tomorrow 9am" |
| 2026-02-15 at 3pm | "2026-02-15T15:00:00" |
| next Monday | "next Monday 9am" |
