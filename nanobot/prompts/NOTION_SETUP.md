# Notion Dashboard Integration Setup

This guide explains how to set up Notion as the storage backend for nanobot's Dashboard.

## Prerequisites

1. A Notion account
2. A Notion integration (API token)

## Step 1: Create a Notion Integration

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **"New integration"**
3. Name it (e.g., "nanobot")
4. Select your workspace
5. Copy the **Internal Integration Token** (`secret_xxx`)

## Step 2: Create Databases

Create 4 databases in Notion with the exact property names below.
You can create them in a single page for organization.

**Important**: After creating each database, share it with your integration:
- Click "..." menu → "Connections" → Add your integration

### Tasks DB

| Property | Type | Notes |
|----------|------|-------|
| Title | title | Task title |
| NanobotID | text | `task_xxxxxxxx` (unique identifier) |
| Status | select | Options: Active, Someday, Completed, Cancelled, Archived |
| Priority | select | Options: Low, Medium, High |
| Deadline | date | Due date |
| DeadlineText | text | Natural language deadline (e.g., "next Friday") |
| Progress | number (%) | 0-100 |
| Blocked | checkbox | Whether task is blocked |
| BlockerNote | text | Reason for being blocked |
| ProgressNote | text | Progress notes |
| Context | text | Description/context |
| Tags | multi-select | Tags for categorization |
| EstimationHours | number | Estimated hours |
| Complexity | select | Options: Low, Medium, High |
| CreatedAt | date | Creation date |
| UpdatedAt | date | Last update date |
| CompletedAt | date | Completion date |
| Reflection | text | Post-completion reflection note |
| RecurringConfig | text | JSON-serialized recurring config (daily habit tracking) |

### Questions DB

| Property | Type | Notes |
|----------|------|-------|
| Question | title | Question text |
| NanobotID | text | `q_xxxxxxxx` |
| Priority | select | Options: Low, Medium, High |
| Type | select | Options: info_gather, progress_check, deadline_check, start_check, blocker_check, status_check, completion_check, routine_check |
| RelatedTaskID | text | Related task ID (e.g., `task_xxxxxxxx`) |
| Context | text | Question context |
| Answered | checkbox | **User checks this to answer** |
| Answer | text | **User types answer here** |
| AnsweredAt | date | Answer date |
| AskedCount | number | Times asked |
| CooldownHours | number | Hours before re-asking (default: 24) |
| LastAskedAt | date | Last asked date |
| CreatedAt | date | Creation date |

### Notifications DB

| Property | Type | Notes |
|----------|------|-------|
| Message | title | Notification message |
| NanobotID | text | Unique identifier |
| ScheduledAt | date | When to send |
| ScheduledAtText | text | Natural language schedule (e.g., "tomorrow 9am") |
| Type | select | Options: reminder, deadline_alert, progress_check, blocker_followup, question_reminder |
| Priority | select | Options: Low, Medium, High |
| Status | select | Options: Pending, Delivered, Cancelled |
| RelatedTaskID | text | Related task ID |
| RelatedQuestionID | text | Related question ID |
| CronJobID | text | **DEPRECATED** — no longer read/written by mapper (Ledger-Based Delivery) |
| Context | text | Additional context |
| CreatedBy | select | Options: worker, user, main_agent |
| CreatedAt | date | Creation date |
| DeliveredAt | date | Delivery date |
| CancelledAt | date | Cancellation date |
| GCalEventID | text | Google Calendar event ID (for sync) |

### Insights DB

| Property | Type | Notes |
|----------|------|-------|
| Title | title | Insight title |
| NanobotID | text | Unique identifier |
| Category | select | Options: tech, life, work, learning |
| Content | text | Insight content |
| Source | text | Source reference |
| Tags | multi-select | Tags |
| CreatedAt | date | Creation date |

## Step 3: Get Database IDs

For each database:
1. Open the database in Notion
2. The URL will look like: `https://notion.so/xxx?v=yyy`
3. The `xxx` part (32 characters) is the database ID
4. Or use "Copy link" and extract the ID

## Step 4: Configure nanobot

Add to your `~/.nanobot/config.json`:

```json
{
  "notion": {
    "enabled": true,
    "token": "secret_your_token_here",
    "databases": {
      "tasks": "your_tasks_db_id",
      "questions": "your_questions_db_id",
      "notifications": "your_notifications_db_id",
      "insights": "your_insights_db_id"
    },
    "cache_ttl_s": 300
  }
}
```

## Step 5: Validate

Run the validation command:

```bash
nanobot notion validate
```

This checks that all configured databases are accessible (connectivity test).

## How It Works

- **Notion is the single source of truth** — all reads/writes go through the Notion API
- **In-memory cache** (5min TTL) optimizes repeated reads within the same message processing
- **Cache invalidation** on every new message and worker cycle ensures fresh data
- **User edits in Notion** (e.g., answering questions directly) are automatically picked up
- **Fallback**: If `notion.enabled=false`, the original JSON file storage is used

## Answering Questions in Notion

1. Open the Questions database
2. Find the unanswered question
3. Check the **Answered** checkbox
4. Type your answer in the **Answer** field
5. nanobot will pick it up on the next message or worker cycle
