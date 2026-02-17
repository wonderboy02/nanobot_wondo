# Notification System - 동작 방식 상세 설명

## 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    30분마다 자동 실행                         │
│                                                               │
│  Heartbeat Service ──────┐                                   │
│                          │                                   │
│                          ▼                                   │
│              ┌──────────────────────┐                        │
│              │  LLM Worker Agent    │                        │
│              │  (Intelligent)       │                        │
│              └──────────────────────┘                        │
│                          │                                   │
│                          │ Analyzes Dashboard               │
│                          ▼                                   │
│         ┌────────────────────────────────────┐              │
│         │  Dashboard Summary (Context)       │              │
│         │  - All active tasks                │              │
│         │  - All unanswered questions        │              │
│         │  - All scheduled notifications     │              │
│         └────────────────────────────────────┘              │
│                          │                                   │
│                          │ Makes decisions via LLM          │
│                          ▼                                   │
│         ┌────────────────────────────────────┐              │
│         │  Worker Tools (13 tools)           │              │
│         │  - schedule_notification           │              │
│         │  - update_notification             │              │
│         │  - cancel_notification             │              │
│         │  - list_notifications              │              │
│         │  - create_question                 │              │
│         │  - update_question                 │              │
│         │  - remove_question                 │              │
│         │  - update_task                     │              │
│         │  - move_to_history                 │              │
│         │  - [REMOVED]
│         └────────────────────────────────────┘              │
│                          │                                   │
│                          ▼                                   │
│         ┌────────────────────────────────────┐              │
│         │  Dashboard Files (JSON)            │              │
│         │  - tasks.json                      │              │
│         │  - questions.json                  │              │
│         │  - notifications.json              │              │
│         │  - knowledge/*.json                │              │
│         └────────────────────────────────────┘              │
│                          │                                   │
│                          │ Creates Cron Job                 │
│                          ▼                                   │
│         ┌────────────────────────────────────┐              │
│         │  CronService (Scheduler)           │              │
│         │  - Waits for scheduled_at time     │              │
│         └────────────────────────────────────┘              │
│                          │                                   │
│                          │ At scheduled time                │
│                          ▼                                   │
│         ┌────────────────────────────────────┐              │
│         │  Message Delivery                  │              │
│         │  MessageBus → Channel → User       │              │
│         └────────────────────────────────────┘              │
│                                                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    사용자 메시지 도착                         │
│                                                               │
│  User Message ──────┐                                        │
│                     │                                        │
│                     ▼                                        │
│         ┌──────────────────────┐                            │
│         │  Main Agent          │                            │
│         │  (Conversation)      │                            │
│         └──────────────────────┘                            │
│                     │                                        │
│                     │ Parses message                        │
│                     ▼                                        │
│         ┌────────────────────────────────────┐              │
│         │  Dashboard Tools (Subset)          │              │
│         │  - answer_question                 │              │
│         │  - create_task                     │              │
│         │  - update_task                     │              │
│         │  - schedule_notification (rare)    │              │
│         └────────────────────────────────────┘              │
│                     │                                        │
│                     ▼                                        │
│         Updates Dashboard → Worker sees changes next cycle  │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## 1. Worker Agent 동작 방식

### Step 1: Context 구성 (WORKER.md + Dashboard Summary)

**WORKER.md 읽기**:
```python
worker_instructions = workspace / "WORKER.md"
# 전체 지시사항 로드 (Analysis Framework, Decision Guidelines, Tool Usage)
```

**Dashboard Summary 생성**:
```python
# DashboardHelper가 생성하는 Summary 예시:
"""
## Active Tasks

**task_001**: 블로그 작성
- Progress: 70%
- Deadline: 2026-02-10 (tomorrow)
- Priority: high
- Last Update: 2026-02-08
- Context: React Tutorial 시리즈 3편

**task_002**: React 공부
- Progress: 50%
- Deadline: None
- Priority: medium
- Last Update: 2026-02-04 (5 days ago)
- ⚠️ Blocked: Hook 이해 어려움
- Context: 유튜브 강의

## Unanswered Questions

**q_001**: Hook 자료 찾아봤어?
- Priority: medium
- Type: info_gather
- Related Task: task_002
- Created: 2026-02-05

## Scheduled Notifications

- **n_001** (deadline_alert, high): 블로그 마감이 내일이에요! [Scheduled: 2026-02-09 09:00]
  Related Task: task_001
"""
```

### Step 2: LLM 분석 및 도구 호출

**Worker의 사고 과정 (LLM이 생성)**:
```
[Analysis]
1. Task 001 (블로그):
   - Deadline tomorrow
   - Progress 70% (reasonable)
   - Already has notification scheduled (n_001) ✓
   - No action needed

2. Task 002 (React):
   - No deadline
   - Progress 50%, stagnant for 5 days
   - Blocked: Hook 이해 어려움
   - Has question q_001 but no follow-up
   - → Need blocker follow-up notification

3. Question Queue:
   - q_001 unanswered for 4 days
   - → Keep monitoring

[Decisions]
- Schedule blocker follow-up for task_002
- No duplicate notifications needed
- Question queue size OK (1 question)

[Tool Calls]
schedule_notification(
  message="'React 공부' 작업이 5일째 50%에서 막혀있어요. Hook 자료 찾는 거 어떻게 되고 있나요?",
  scheduled_at="in 2 hours",
  type="blocker_followup",
  priority="medium",
  related_task_id="task_002"
)
```

### Step 3: 도구 실행 및 저장

**schedule_notification 도구 실행**:
```python
# 1. 파라미터 파싱
scheduled_at = "in 2 hours"
scheduled_dt = parse_datetime(scheduled_at)  # → 2026-02-08T13:00:00

# 2. Notification ID 생성
notification_id = generate_id("n")  # → "n_a7f3e2c1"

# 3. Cron Job 생성
cron_job = cron_service.add_job(
    name=f"notification_{notification_id}",
    schedule=CronSchedule(kind="at", at_ms=1707382800000),
    message="'React 공부' 작업이 5일째...",
    deliver=True,
    delete_after_run=True
)

# 4. Notification 엔트리 생성
notification = {
    "id": "n_a7f3e2c1",
    "message": "'React 공부' 작업이 5일째...",
    "scheduled_at": "2026-02-08T13:00:00",
    "type": "blocker_followup",
    "priority": "medium",
    "related_task_id": "task_002",
    "status": "pending",
    "cron_job_id": "abc12345",
    "created_at": "2026-02-08T11:00:00",
    "created_by": "worker"
}

# 5. notifications.json 저장
notifications_data["notifications"].append(notification)
validate_and_save_notifications(notifications_data)
```

### Step 4: Cron이 대기하다가 시간 되면 전달

**Cron Job 실행 흐름**:
```python
# CronService._on_timer() (2026-02-08T13:00:00에 실행)

# 1. Due jobs 찾기
due_jobs = [job for job in jobs if now >= job.next_run_at_ms]

# 2. Job 실행
await on_cron_job(job)
  → agent.process_direct(job.message)
  → MessageBus.publish_outbound(
      channel="telegram",
      chat_id="123456789",
      content="'React 공부' 작업이 5일째..."
  )

# 3. Notification 상태 업데이트 (Callback)
# (현재 구현에는 callback이 없지만 추가 필요)
notification.status = "delivered"
notification.delivered_at = now()

# 4. Cron Job 삭제 (delete_after_run=True)
cron_service.remove_job(job.id)
```

## 2. Main Agent 동작 방식

### 사용자 메시지 처리

**예시: 사용자가 진행률 업데이트**
```
User: "블로그 80% 완료했어요!"

Main Agent:
1. 메시지 파싱
   - "블로그" → task_001 관련
   - "80%" → progress 업데이트

2. 도구 호출
   update_task(task_id="task_001", progress=80)

3. 응답
   "SILENT"  (Dashboard 업데이트는 조용히)
```

**예시: 사용자가 명시적으로 알림 요청**
```
User: "블로그 마감 전날 저녁 6시에 알림 보내줘"

Main Agent:
1. 메시지 파싱
   - "블로그" → task_001
   - "마감 전날" → 2026-02-09
   - "저녁 6시" → 18:00

2. 기존 알림 확인
   list_notifications(related_task_id="task_001")
   → n_001: 2026-02-09 09:00 (already exists)

3. 중복 체크 후 생성 여부 결정
   - 시간대가 다르므로 추가 생성
   schedule_notification(
       message="블로그 마감이 내일이에요! 저녁까지 마무리 부탁해요.",
       scheduled_at="2026-02-09T18:00:00",
       type="deadline_alert",
       priority="high",
       related_task_id="task_001"
   )

4. 응답
   "✅ 알림 예약했어요. 2월 9일 저녁 6시에 알려드릴게요!"
```

## 3. 프롬프트 구조

### Worker Agent 프롬프트

**System Message (WORKER.md)**:
```markdown
You are the Worker Agent - an autonomous background agent that maintains the Dashboard proactively.

Your Role:
- Analyze the Dashboard state (tasks, questions, notifications, knowledge)
- Maintain task progress tracking and deadline awareness
- Schedule notifications for timely reminders
- Manage the question queue (create, update, remove questions)
- Clean up outdated or redundant data
- Operate autonomously without user interaction

Analysis Framework:
1. Task Progress Analysis
   - Time-based progress
   - Progress stagnation (3+ days)
   - Deadline proximity (24 hours)
   - Blocker status

2. Question Queue Management
   - Duplicate questions
   - Obsolete questions
   - Low-priority clutter
   - Unanswered high-priority

3. Notification Strategy
   - Deadline alerts: 24h before, 2h before
   - Progress checks: No update in 3 days
   - Blocker follow-ups: 48h after blocked
   - Question reminders: High-priority unanswered 2+ days

4. Knowledge Base Maintenance
   - Move completed tasks to history
   - Save insights from patterns

Decision Guidelines:
- High priority: Deadline <24h, Blocked 48h+, High-priority Q 2+ days
- Medium priority: Stagnant 3-5 days, Deadline 2-3 days
- Low priority: On track, no immediate deadlines

Cooldown Periods:
- progress_check: 24h
- deadline_check: 12h
- blocker_check: 48h

Important Constraints:
1. ALWAYS check existing notifications before scheduling
2. Respect cooldown periods
3. Provide clear context
4. Avoid spam
5. Link entities (related_task_id)
6. Clean up aggressively
7. Operate silently
```

**User Message (Dashboard Summary)**:
```markdown
## Current Dashboard State

[Dashboard Summary here - tasks, questions, notifications]

## Your Task

Analyze the Dashboard state and perform necessary maintenance actions:
1. Check for tasks needing notifications (deadlines, stagnant progress, blockers)
2. Manage question queue (create, update, remove as needed)
3. Move completed tasks to history
4. Schedule appropriate notifications (check existing ones first!)
5. Clean up obsolete questions

Use the available tools to make changes. Be proactive but avoid spam.
```

**Tool Schemas**: 13개 도구의 JSON Schema

### Main Agent 프롬프트

**System Message (AGENTS.md + DASHBOARD.md + TOOLS.md + SOUL.md + USER.md)**:
```markdown
[AGENTS.md]
You are a helpful AI assistant...

Dashboard System:
- Main Agent (You): Respond to user messages
- Worker Agent: Autonomous maintenance (runs every 30min)

Notification Guidelines:
- Only schedule when user explicitly requests
- Worker handles automatic notifications
- Check existing: list_notifications()

[DASHBOARD.md]
Core Principles:
1. Dashboard is single source of truth
2. One message = Multiple updates
3. Use specialized tools

Notification System:
- Scheduled reminders via Cron
- Worker creates automatically
- Only create if user requests

[TOOLS.md]
Available Tools:
- Task Management: create_task, update_task, move_to_history
- Question Management: answer_question, create_question, update_question, remove_question
- Notification Management: schedule_notification, update_notification, cancel_notification, list_notifications
- Knowledge: [REMOVED]

[Dashboard Summary]
Active Tasks: ...
Unanswered Questions: ...
```

**User Message**: 사용자가 보낸 실제 메시지

**Tool Schemas**: Main Agent 사용 가능 도구들

## 4. 알림 컨트롤 방법

### Worker가 알림을 생성하는 경우

**자동 생성 조건**:
1. **Deadline Alert**:
   - 24시간 전 (priority: high)
   - 2시간 전 (priority: high)

2. **Progress Check**:
   - 3일 이상 progress 업데이트 없음 (priority: medium)
   - 5일 이상 stagnant (priority: high)

3. **Blocker Follow-up**:
   - Blocked 상태 48시간 경과 (priority: medium)

4. **Question Reminder**:
   - High-priority 질문 2일 이상 미답변 (priority: high)

**중복 방지 메커니즘**:
```python
# Worker는 항상 먼저 확인
existing = list_notifications(related_task_id="task_001", status="pending")

# 같은 타입, 비슷한 시간대 있으면 생성 안 함
for notif in existing:
    if notif.type == "deadline_alert":
        time_diff = abs(notif.scheduled_at - new_scheduled_at)
        if time_diff < 12 hours:
            return  # Skip - already have deadline alert
```

### Main Agent가 알림을 생성하는 경우

**사용자 명시적 요청**:
```
User: "내일 9시에 알림 보내줘"
User: "마감 전날 알려줘"
User: "2시간 후에 리마인더 보내줘"
```

**Main Agent 처리**:
1. 사용자 의도 파악
2. 기존 알림 확인 (`list_notifications`)
3. 중복이 아니면 생성
4. 사용자에게 확인 메시지

### 알림 업데이트

**시간 변경**:
```python
update_notification(
    notification_id="n_001",
    scheduled_at="2026-02-10T10:00:00"
)
# → Cron Job도 자동으로 업데이트됨
```

**메시지 변경**:
```python
update_notification(
    notification_id="n_001",
    message="새로운 메시지 내용"
)
```

### 알림 취소

**Task 완료 시 자동 취소**:
```python
# Worker가 감지
if task.status == "completed":
    related_notifications = list_notifications(
        related_task_id=task.id,
        status="pending"
    )
    for notif in related_notifications:
        cancel_notification(
            notification_id=notif.id,
            reason="Task completed"
        )
```

**사용자 요청 시 취소**:
```
User: "알림 취소해줘"
Main Agent:
  → list_notifications()
  → cancel_notification(n_001, "User requested cancellation")
```

## 5. Race Condition 처리

### 현재 전략: "낙관적 허용"

**확률 계산**:
- Worker 주기: 30분 (1,800초)
- Main Agent 메시지: 평균 1분당 1개
- 충돌 확률: ~0.056% (매우 낮음)

**충돌 시나리오**:
```
T=0s: Worker가 notifications.json 읽음
T=5s: User가 메시지 보냄 → Main Agent가 notifications.json 수정
T=10s: Worker가 notifications.json 쓰기 → Main Agent 수정사항 덮어씀
```

**완화 방법**:
1. **Atomic Writes**: JSON 파일 전체를 한 번에 쓰기
2. **Low Probability**: 30분 주기 + 짧은 Worker 실행 시간
3. **Stateless Design**: Session history 없어서 context 오염 없음

**향후 개선안** (필요 시):
```python
# asyncio.Lock 사용
dashboard_lock = asyncio.Lock()

async def _run_worker():
    async with dashboard_lock:
        await worker.run_cycle()

async def update_task():
    async with dashboard_lock:
        # Update task
```

## 6. 테스트 시나리오

### 시나리오 1: Worker가 마감 알림 생성
```
Given:
  - Task: "블로그 작성", deadline="2026-02-10"
  - Current time: 2026-02-09 08:00
  - No notifications scheduled

When:
  - Worker runs at 2026-02-09 08:30

Then:
  - Worker detects: Deadline in ~16 hours
  - Worker creates notification:
      message="블로그 작성 마감이 내일이에요!"
      scheduled_at="2026-02-09T09:00:00"
      type="deadline_alert"
      priority="high"
  - Cron job created with at_ms=1707451200000
  - At 2026-02-09 09:00, notification delivered to user
```

### 시나리오 2: Main Agent가 사용자 요청으로 알림 생성
```
Given:
  - Task: "운동하기", deadline=None
  - User message: "2시간 후에 운동 알림 보내줘"

When:
  - Main Agent processes message

Then:
  - Main Agent parses: "2시간 후" → 2 hours from now
  - Main Agent checks: list_notifications() → None
  - Main Agent creates:
      schedule_notification(
          message="운동할 시간이에요!",
          scheduled_at="in 2 hours",
          type="reminder"
      )
  - User reply: "✅ 알림 예약했어요. 2시간 후 알려드릴게요!"
```

### 시나리오 3: 중복 방지
```
Given:
  - Task: "블로그", deadline="2026-02-10"
  - Notification n_001: scheduled_at="2026-02-09T09:00", type="deadline_alert"

When:
  - Worker runs at 2026-02-09 08:30 (again)

Then:
  - Worker analyzes: Deadline in ~16 hours
  - Worker checks: list_notifications(related_task_id="task_001")
      → Found n_001 (deadline_alert, scheduled soon)
  - Worker decides: Skip - already have deadline alert
  - No duplicate notification created
```

## 7. 디버깅 방법

### 로그 확인
```bash
# Worker 실행 로그
grep "Worker Agent" ~/.nanobot/logs/gateway.log

# Notification 생성 로그
grep "Notification scheduled" ~/.nanobot/logs/gateway.log

# Cron 실행 로그
grep "Cron: executing job" ~/.nanobot/logs/gateway.log
```

### 수동 테스트
```bash
# Worker 수동 실행
nanobot dashboard worker

# Notification 파일 직접 확인
cat workspace/dashboard/notifications.json

# Cron 작업 목록
nanobot cron list
```

### Dashboard 상태 확인
```bash
# 전체 Dashboard 보기
nanobot dashboard show

# Notification만 보기
nanobot dashboard notifications

# 특정 Task 관련 알림
# (CLI 명령 없음 - notifications.json 직접 확인)
```

## 8. 설정 옵션

### config.json 예시
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "max_tokens": 8192,
      "temperature": 0.7
    },
    "worker": {
      "enabled": true,
      "use_llm": true,
      "fallback_to_rules": true,
      "model": "google/gemini-2.0-flash-exp"
    }
  },
  "heartbeat": {
    "interval_s": 1800
  }
}
```

### Worker 비활성화
```json
{
  "agents": {
    "worker": {
      "enabled": false
    }
  }
}
```

### Rule-based Worker로 전환
```json
{
  "agents": {
    "worker": {
      "use_llm": false,
      "fallback_to_rules": true
    }
  }
}
```

## 9. 성능 및 비용

### Token 사용량

**Worker 1회 실행**:
- Input: ~2,000 tokens (WORKER.md + Dashboard Summary)
- Output: ~500 tokens (Tool calls)
- Total: ~2,500 tokens/cycle

**하루 비용 (48 cycles)**:
- Gemini 2.0 Flash: ~$0.015/day
- Claude Opus: ~$0.60/day
- GPT-4o: ~$0.12/day

### 실행 시간

**Worker 실행 시간**:
- LLM API 호출: ~2-5초
- Tool 실행: ~0.5초
- 총: ~3-6초/cycle

**Cron 정확도**:
- ±1초 이내 (Python asyncio.sleep 기반)

## 요약

1. **Worker Agent**: 30분마다 Dashboard 분석 → 알림 자동 생성
2. **Main Agent**: 사용자 메시지 처리 → 명시적 요청 시만 알림 생성
3. **Notification**: Cron 기반 정확한 시간 전달
4. **중복 방지**: `list_notifications`로 항상 확인
5. **Race Condition**: 0.056% 확률, 허용 가능
6. **프롬프트**: WORKER.md (Worker) / AGENTS.md+DASHBOARD.md (Main)
7. **컨트롤**: 도구 6개 (schedule, update, cancel, list, update_question, remove_question)
