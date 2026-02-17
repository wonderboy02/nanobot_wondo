# Worker Agent vs Main Agent - 상세 비교

## 1. 프롬프트 구조

### Worker Agent 프롬프트

```
messages = [
    {
        "role": "system",
        "content": <WORKER.md 전체 내용>
    },
    {
        "role": "user",
        "content": """
## Current Dashboard State

<Dashboard Summary>
- All Active Tasks
- All Unanswered Questions

<Notifications Summary>
- All Scheduled Notifications

## Your Task

Analyze the Dashboard state and perform necessary maintenance actions:
1. Check for tasks needing notifications (deadlines, stagnant progress, blockers)
2. Manage question queue (create, update, remove as needed)
3. Move completed tasks to history
4. Schedule appropriate notifications (check existing ones first!)
5. Clean up obsolete questions

Use the available tools to make changes. Be proactive but avoid spam.
        """
    }
]
```

**특징**:
- **System Message**: WORKER.md 전체 (상세 분석 프레임워크, 의사결정 가이드라인)
- **User Message**: Dashboard 현재 상태 + 작업 지시
- **Dashboard Summary**: 모든 active tasks + 모든 questions + 모든 notifications
- **제한 없음**: max_active_tasks=None, max_unanswered_questions=None

---

### Main Agent 프롬프트

```
messages = [
    {
        "role": "system",
        "content": """
# nanobot 🐈

You are nanobot, a helpful AI assistant...

## Current Time
2026-02-09 15:30 (Sunday)

## Runtime
Windows AMD64, Python 3.11.0

## Workspace
Your workspace is at: C:/Users/wondo/dev/nanobot_wondo/workspace
...

---

## AGENTS.md

<AGENTS.md 내용>

---

## SOUL.md

<SOUL.md 내용>

---

## USER.md

<USER.md 내용>

---

## TOOLS.md

<TOOLS.md 내용>

---

## DASHBOARD.md

<DASHBOARD.md 내용>

---

# Dashboard State

<Dashboard Summary>
- Top 10 Active Tasks
- Top 5 Unanswered Questions

        """
    },
    {
        "role": "user",
        "content": "<사용자가 보낸 실제 메시지>"
    },
    <대화 히스토리...>
]
```

**특징**:
- **System Message**:
  - Core Identity (nanobot 소개)
  - AGENTS.md (Agent 역할)
  - SOUL.md (페르소나)
  - USER.md (사용자 프로파일)
  - TOOLS.md (도구 목록)
  - DASHBOARD.md (Dashboard 사용법)
  - Dashboard State (요약)
- **User Message**: 사용자가 실제로 보낸 메시지
- **Dashboard Summary**: 상위 10개 tasks + 상위 5개 questions (제한 있음)
- **대화 히스토리**: 이전 대화 포함

---

## 2. 실제 프롬프트 예시

### Worker Agent 실제 프롬프트

**System Message (WORKER.md)**:
```markdown
# Worker Agent Instructions

You are the **Worker Agent** - an autonomous background agent that maintains the Dashboard proactively.

## Your Role

- **Analyze** the Dashboard state (tasks, questions, notifications, knowledge)
- **Maintain** task progress tracking and deadline awareness
- **Schedule** notifications for timely reminders
- **Manage** the question queue (create, update, remove questions)
- **Clean up** outdated or redundant data
- **Operate** autonomously without user interaction

## What You See

Every time you run, you receive:
1. **Dashboard Summary**: All active tasks, questions, notifications
2. **Knowledge Base**: Completed tasks, insights, people
3. **Your Tools**: Question management, notification scheduling, task updates

## Analysis Framework

### 1. Task Progress Analysis

For each active task, check:
- **Time-based progress**: How long since task created vs. expected duration
- **Progress stagnation**: No progress updates in 3+ days
- **Deadline proximity**: Deadline within 24 hours
- **Blocker status**: Task marked as blocked

**Actions**:
- If progress is slow: Schedule a progress_check notification
- If deadline is near: Schedule a deadline_alert notification
- If blocked: Schedule a blocker_followup notification
- If stagnant 5+ days: Create a progress_check question

### 2. Question Queue Management

Check for:
- **Duplicate questions**: Same question asked multiple times
- **Obsolete questions**: Related task completed or cancelled
- **Low-priority clutter**: Old low-priority questions (7+ days)
- **Unanswered high-priority**: Questions with priority=high unanswered for 2+ days

**Actions**:
- Remove duplicates (keep most recent)
- Remove obsolete questions (task no longer exists)
- Remove old low-priority questions (if > 10 questions total)
- Escalate high-priority questions by creating notifications

### 3. Notification Strategy

**When to schedule notifications**:
- **Deadline alerts**: 24 hours before deadline, 2 hours before deadline
- **Progress checks**: If no progress update in 3 days
- **Blocker follow-ups**: 48 hours after task marked as blocked
- **Question reminders**: For high-priority unanswered questions (after 2 days)

**Avoid duplicates**:
- ALWAYS call `list_notifications` first to see existing scheduled notifications
- Do NOT schedule if similar notification already exists for same task/timeframe
- Example: Don't schedule "deadline tomorrow" if already scheduled

**Timing guidelines**:
- Morning notifications: 9:00 AM
- Evening notifications: 6:00 PM
- Urgent alerts: Immediate (within 1 hour)

### 4. Knowledge Base Maintenance

Check for:
- **Completed tasks**: Active tasks with progress=100% should be moved to history
- **Cancelled tasks**: Status=cancelled should be moved to history
- **Insights**: Task blockers that reveal patterns should be saved as insights

**Actions**:
- Use `move_to_history` for completed/cancelled tasks
- Use `[REMOVED]

## Decision Guidelines

### Priority Levels

**High priority** (immediate action):
- Deadline within 24 hours
- Task blocked for 48+ hours
- High-priority question unanswered for 2+ days

**Medium priority** (schedule reminder):
- Progress stagnant for 3-5 days
- Deadline within 2-3 days
- Medium-priority question unanswered for 3+ days

**Low priority** (monitor):
- Progress on track
- No immediate deadlines
- Low-priority questions (cleanup if queue > 10)

### Cooldown Periods

Respect question cooldown to avoid spam:
- **progress_check**: 24 hours
- **deadline_check**: 12 hours
- **blocker_check**: 48 hours
- **status_check**: 48 hours

Do NOT create questions if within cooldown period of last_asked_at.

[... 더 많은 지침 ...]
```

**User Message**:
```markdown
## Current Dashboard State

### Active Tasks

**task_001**: 블로그 작성
- Progress: 70%
- Deadline: 2026-02-10 (tomorrow)
- Priority: high
- Last Update: 2026-02-08 (1 day ago)
- Context: React Tutorial 시리즈 3편
- Tags: writing, react

**task_002**: React 공부
- Progress: 50%
- Deadline: None
- Priority: medium
- Last Update: 2026-02-04 (5 days ago)
- ⚠️ Blocked: Hook 이해 어려움
- Context: 유튜브 강의
- Tags: study, react

### Unanswered Questions

**q_001**: Hook 자료 찾아봤어?
- Priority: medium
- Type: info_gather
- Related Task: task_002
- Asked: 1 times
- Last Asked: 2026-02-05 (4 days ago)
- Context: User struggling with React Hooks

### Scheduled Notifications

- **n_001** (deadline_alert, high): 블로그 마감이 내일이에요! 현재 70%입니다. [Scheduled: 2026-02-09 09:00]
  Related Task: task_001

## Your Task

Analyze the Dashboard state and perform necessary maintenance actions:
1. Check for tasks needing notifications (deadlines, stagnant progress, blockers)
2. Manage question queue (create, update, remove as needed)
3. Move completed tasks to history
4. Schedule appropriate notifications (check existing ones first!)
5. Clean up obsolete questions

Use the available tools to make changes. Be proactive but avoid spam.
```

**Worker의 사고 과정 (LLM 응답 예시)**:
```json
{
  "content": "I'll analyze the dashboard and perform maintenance.\n\n**Analysis**:\n1. Task 001 (블로그): Deadline tomorrow, already has notification n_001 ✓\n2. Task 002 (React): Stagnant 5 days, blocked, needs follow-up\n3. Question q_001: Unanswered 4 days, medium priority\n\n**Actions**: Schedule blocker follow-up for task_002",
  "tool_calls": [
    {
      "id": "call_1",
      "name": "schedule_notification",
      "arguments": {
        "message": "'React 공부' 작업이 5일째 50%에서 막혀있어요. Hook 자료 찾는 거 어떻게 되고 있나요?",
        "scheduled_at": "in 2 hours",
        "type": "blocker_followup",
        "priority": "medium",
        "related_task_id": "task_002"
      }
    }
  ]
}
```

---

### Main Agent 실제 프롬프트

**System Message (축약)**:
```markdown
# nanobot 🐈

You are nanobot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks

## Current Time
2026-02-09 15:30 (Sunday)

## Runtime
Windows AMD64, Python 3.11.0

## Workspace
Your workspace is at: C:/Users/wondo/dev/nanobot_wondo/workspace
- Memory files: C:/Users/wondo/dev/nanobot_wondo/workspace/memory/MEMORY.md
- Daily notes: C:/Users/wondo/dev/nanobot_wondo/workspace/memory/YYYY-MM-DD.md
- Custom skills: C:/Users/wondo/dev/nanobot_wondo/workspace/skills/{skill-name}/SKILL.md

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. When using tools, explain what you're doing.
When remembering something, write to C:/Users/wondo/dev/nanobot_wondo/workspace/memory/MEMORY.md

---

## AGENTS.md

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Core Guidelines

- Explain what you're doing before taking actions
- Ask for clarification when requests are ambiguous
- Use tools to accomplish tasks efficiently
- Remember important information in memory files

## Dashboard System

There are **two agents** managing the Dashboard:

### 1. Main Agent (You)
**Role**: Respond to user messages and update Dashboard based on conversation

**What you do**:
- Parse user messages for task updates, progress, blockers
- Answer questions from the question queue
- Create new tasks based on user requests
- Update task progress and status
- Schedule notifications when user explicitly requests them

### 2. Worker Agent (Background)
**Role**: Autonomous Dashboard maintenance (runs every 30 minutes)

**What Worker does**:
- Analyzes task progress and detects stagnation
- Schedules notifications for deadlines and progress checks
- Manages question queue (create, update, remove)
- Moves completed tasks to history

**Notification Guidelines for Main Agent**:
- Only schedule notifications when user explicitly requests
- Worker handles automatic deadline/progress notifications
- Check existing notifications: `list_notifications(status="pending")`
- Avoid duplicates - Worker is already monitoring deadlines

---

## TOOLS.md

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

## Dashboard Management

### Task Management
```python
create_task(title: str, deadline: str = "", priority: str = "medium",
            context: str = "", tags: list[str] = []) -> str

update_task(task_id: str, progress: int = None, status: str = None,
            blocked: bool = None, blocker_note: str = None, ...) -> str

move_to_history(task_id: str, reflection: str = "") -> str
```

### Question Management
```python
answer_question(question_id: str, answer: str) -> str
create_question(question: str, priority: str = "medium", ...) -> str
```

[... 전체 도구 목록 ...]

---

## DASHBOARD.md

You are a **contextual dashboard manager** that understands full context and updates everything holistically.

## Core Principles

1. **Dashboard is the single source of truth**
2. **One message = Multiple updates**
3. **Use specialized tools**

## Workflow

### 2. Analyze Message Holistically
Extract everything:
- ✅ Answers (explicit or implicit)
- ✅ Progress updates ("50%", "거의 끝")
- ✅ Blockers ("어려워요", "막혔어요")
- ✅ New tasks or context

### 3. Use Tools
**Example: Multiple updates from one message**
```
User: "유튜브로 공부 중인데 50% 완료했어요. Hook이 어려워요"

Actions:
→ answer_question(q_001, "유튜브 강의")  # Answer implicit question
→ update_task(task_001, progress=50, context="유튜브 강의")
→ update_task(task_001, blocked=True, blocker_note="Hook 이해 어려움")
→ create_question("Hook 자료 찾아봤어?", related_task_id=task_001)
```

### 4. Reply
- **Regular updates**: `SILENT` (no message to user)
- **Commands** (`/questions`, `/tasks`): Show results
- **Conversations**: Natural response

---

# Dashboard State

## Active Tasks (Top 10)

**task_001**: 블로그 작성
- Progress: 70%
- Deadline: 2026-02-10 (tomorrow)
- Priority: high
- Context: React Tutorial 시리즈 3편

**task_002**: React 공부
- Progress: 50%
- Priority: medium
- ⚠️ Blocked: Hook 이해 어려움

## Unanswered Questions (Top 5)

**q_001**: Hook 자료 찾아봤어?
- Priority: medium
- Type: info_gather
- Related Task: task_002
```

**User Message**:
```
블로그 80% 완료했어요!
```

**Main Agent 응답 예시**:
```json
{
  "content": "SILENT",
  "tool_calls": [
    {
      "id": "call_1",
      "name": "update_task",
      "arguments": {
        "task_id": "task_001",
        "progress": 80
      }
    }
  ]
}
```

---

## 3. 도구 비교

### Worker Agent 사용 도구 (13개)

| 카테고리 | 도구 | 목적 |
|---------|------|------|
| **Question Management** | `create_question` | 질문 생성 |
| | `update_question` | 질문 업데이트 (priority, type, cooldown) |
| | `remove_question` | 질문 제거 (중복/obsolete) |
| | `answer_question` | 질문 답변 (거의 안 씀) |
| **Notification Management** | `schedule_notification` | 알림 스케줄 + Cron Job 생성 |
| | `update_notification` | 알림 수정 + Cron Job 업데이트 |
| | `cancel_notification` | 알림 취소 + Cron Job 제거 |
| | `list_notifications` | 알림 목록 (중복 방지) |
| **Task Management** | `create_task` | Task 생성 (거의 안 씀) |
| | `update_task` | Task 업데이트 |
| | `move_to_history` | History로 이동 |
| **Knowledge Management** | `[REMOVED]

**특징**:
- ✅ **Full Question Lifecycle**: create, update, remove
- ✅ **Full Notification Lifecycle**: schedule, update, cancel, list
- ✅ **Read-only 아님**: 모든 CRUD 작업 가능
- ✅ **Autonomous**: 사용자 입력 없이 자동 실행

---

### Main Agent 사용 도구 (14개)

| 카테고리 | 도구 | 목적 |
|---------|------|------|
| **File Operations** | `read_file` | 파일 읽기 |
| | `write_file` | 파일 쓰기 |
| | `edit_file` | 파일 편집 |
| | `list_dir` | 디렉토리 목록 |
| **Shell** | `exec` | 쉘 명령 실행 |
| **Web** | `web_search` | 웹 검색 (Brave) |
| | `web_fetch` | 웹 페이지 추출 |
| **Messaging** | `message` | 채널에 메시지 전송 |
| **Subagent** | `spawn` | 서브에이전트 생성 |
| **Question Management** | `answer_question` | 질문 답변 |
| | `create_question` | 질문 생성 |
| **Task Management** | `create_task` | Task 생성 |
| | `update_task` | Task 업데이트 |
| | `move_to_history` | History로 이동 |
| **Knowledge** | `[REMOVED]

**특징**:
- ✅ **Conversational**: 사용자와 대화
- ✅ **File/Shell Access**: 파일 읽기/쓰기, 쉘 명령
- ✅ **Web Access**: 검색, 페치
- ❌ **Notification Tools 없음**: 사용자 명시적 요청 시 Worker에 의존
- ❌ **Question Update/Remove 없음**: Worker가 관리

---

## 4. 역할 비교

| 구분 | Worker Agent | Main Agent |
|------|--------------|------------|
| **실행 주기** | 30분마다 자동 | 사용자 메시지 도착 시 |
| **트리거** | Heartbeat | 사용자 입력 |
| **입력** | Dashboard 전체 상태 | 사용자 메시지 |
| **목적** | Dashboard 유지보수 | 사용자 대화 처리 |
| **자율성** | 완전 자율 (사용자 없음) | 사용자 주도 |
| **의사결정** | 로직 + LLM (분석 프레임워크) | 맥락 + LLM (대화 이해) |
| **응답** | Tool 호출 결과만 (Silent) | 사용자에게 답변 |
| **알림 생성** | 자동 감지 및 생성 | 사용자 명시적 요청 |
| **Question 관리** | Create, Update, Remove | Create, Answer |
| **Task 관리** | Update, Move to History | Create, Update, Move to History |
| **파일 접근** | ❌ (Dashboard 도구만) | ✅ (모든 파일) |
| **쉘 실행** | ❌ | ✅ |
| **웹 검색** | ❌ | ✅ |
| **Subagent** | ❌ | ✅ |

---

## 5. 실행 예시

### Worker Agent 실행

**입력** (Dashboard 상태):
```
Active Tasks:
- task_001: 블로그 (70%, deadline tomorrow)
- task_002: React 공부 (50%, stagnant 5 days, blocked)

Questions:
- q_001: Hook 자료? (unanswered 4 days)

Notifications:
- n_001: 블로그 마감 알림 (scheduled tomorrow 9am)
```

**LLM 분석**:
```
1. task_001: Has notification ✓
2. task_002: Stagnant 5 days + blocked → Need blocker follow-up
3. q_001: Unanswered 4 days → Keep monitoring
```

**도구 호출**:
```python
schedule_notification(
    message="'React 공부' 작업이 5일째 막혀있어요. Hook 자료 찾는 거 어떻게 되고 있나요?",
    scheduled_at="in 2 hours",
    type="blocker_followup",
    related_task_id="task_002"
)
```

**결과**: Notification 생성 → Cron Job 생성 → 2시간 후 전달

---

### Main Agent 실행

**입력** (사용자 메시지):
```
User: "블로그 80% 완료했어요!"
```

**LLM 분석**:
```
- "블로그" → task_001
- "80%" → progress update
```

**도구 호출**:
```python
update_task(task_id="task_001", progress=80)
```

**응답**: `SILENT` (Dashboard 업데이트는 조용히)

---

**입력** (사용자 명시적 알림 요청):
```
User: "블로그 마감 전날 저녁 6시에 알림 보내줘"
```

**LLM 분석**:
```
- 사용자가 명시적으로 알림 요청
- "전날 저녁 6시" → 2026-02-09T18:00:00
```

**도구 호출**:
```python
# 먼저 기존 알림 확인
list_notifications(related_task_id="task_001")

# 중복 아니면 생성
schedule_notification(
    message="블로그 마감이 내일이에요! 저녁까지 마무리 부탁해요.",
    scheduled_at="2026-02-09T18:00:00",
    related_task_id="task_001"
)
```

**응답**: "✅ 알림 예약했어요. 2월 9일 저녁 6시에 알려드릴게요!"

---

## 6. 핵심 차이점 요약

### Context Size

| Agent | System Message | User Message | Total |
|-------|---------------|--------------|-------|
| Worker | ~2,000 tokens (WORKER.md) | ~1,500 tokens (Dashboard) | ~3,500 tokens |
| Main | ~5,000 tokens (All bootstrap files) | ~200 tokens (User msg) | ~5,200 tokens |

### Temperature

| Agent | Temperature | 이유 |
|-------|-------------|------|
| Worker | 0.3 | 일관성 중요 (매번 같은 판단) |
| Main | 0.7 | 대화 자연스러움 |

### Max Iterations

| Agent | Max Iterations | 이유 |
|-------|---------------|------|
| Worker | 10 | Tool 호출 제한 (무한 루프 방지) |
| Main | 20 | 복잡한 작업 지원 |

### Model

| Agent | Default Model | 이유 |
|-------|--------------|------|
| Worker | `google/gemini-2.0-flash-exp` | 빠르고 저렴 (자주 실행) |
| Main | `anthropic/claude-opus-4-5` | 고품질 대화 |

---

## 7. 언제 어떤 Agent를 사용하나?

### Worker Agent가 처리하는 경우

✅ **자동 감지 및 처리**:
- Task 진행률 정체 (3일+)
- 마감 임박 (24시간 이내)
- Blocker 장기화 (48시간+)
- Question Queue 정리 (중복/obsolete)
- 완료 Task History 이동

**예시**:
- "Task가 5일째 50%야" → Worker가 progress_check notification 생성
- "Deadline이 내일이야" → Worker가 deadline_alert notification 생성
- "Question이 중복이야" → Worker가 remove_question 호출

---

### Main Agent가 처리하는 경우

✅ **사용자 대화 기반**:
- 진행률 업데이트
- Task 생성/완료
- Question 답변
- 사용자 명시적 알림 요청
- 일반 대화

**예시**:
- User: "블로그 80% 완료" → Main이 update_task
- User: "내일 9시에 알림 보내줘" → Main이 schedule_notification
- User: "Hook 자료 찾았어" → Main이 answer_question

---

## 8. 협업 방식

### 시나리오: Deadline 임박 Task

**T=0 (사용자가 Task 생성)**:
```
User: "블로그 내일까지 작성해야 해"
Main Agent: create_task(title="블로그 작성", deadline="tomorrow")
→ task_001 생성
```

**T=30분 (Worker 첫 실행)**:
```
Worker: "Deadline이 ~16시간 남았네. 알림 스케줄해야겠다"
Worker: schedule_notification(
    message="블로그 마감이 내일이에요!",
    scheduled_at="tomorrow 9am",
    type="deadline_alert"
)
→ n_001 생성 (Cron Job 생성)
```

**T=1시간 (Worker 두 번째 실행)**:
```
Worker: "Deadline 알림 이미 있네 (n_001). 중복 생성 안 함"
Worker: list_notifications(related_task_id="task_001")
→ n_001 발견 → Skip
```

**T=내일 9시 (Cron 실행)**:
```
Cron: "n_001 실행 시간이야"
Cron: MessageBus → Telegram → User
User receives: "블로그 마감이 내일이에요!"
```

**T=내일 오전 (사용자 진행 업데이트)**:
```
User: "블로그 80% 완료"
Main Agent: update_task(task_001, progress=80)
```

**T=내일 오후 (사용자 완료)**:
```
User: "블로그 다 썼어!"
Main Agent: update_task(task_001, progress=100, status="completed")
```

**T=내일 오후+30분 (Worker 실행)**:
```
Worker: "task_001이 completed네. History로 옮기고 알림 취소해야지"
Worker: move_to_history(task_001)
Worker: cancel_notification(n_001, reason="Task completed")
```

---

## 9. 테스트 시 확인사항

### Worker Agent 테스트
```bash
# Worker 수동 실행
nanobot dashboard worker

# 확인사항:
# 1. Dashboard 상태 분석
# 2. Notification 생성 여부
# 3. Question 관리 (update/remove)
# 4. Task History 이동
# 5. Duplicate 방지
```

### Main Agent 테스트
```bash
# Gateway 실행
nanobot gateway

# Telegram에서 메시지:
"블로그 50% 완료"

# 확인사항:
# 1. Dashboard 업데이트 (SILENT)
# 2. Question 답변
# 3. 사용자 응답 (대화)
```

---

## 요약

| 항목 | Worker Agent | Main Agent |
|------|-------------|------------|
| **역할** | Dashboard 자동 유지보수 | 사용자 대화 처리 |
| **실행** | 30분마다 자동 | 메시지 도착 시 |
| **프롬프트** | WORKER.md + Dashboard 전체 | Bootstrap files + 사용자 메시지 |
| **도구** | 13개 (Question/Notification 전체) | 14개 (File/Shell/Web 포함) |
| **자율성** | 완전 자율 | 사용자 주도 |
| **알림** | 자동 생성 | 명시적 요청 시만 |
| **Question** | Create, Update, Remove | Create, Answer |
| **응답** | Silent (Tool 결과만) | 사용자에게 답변 |
| **Model** | Gemini Flash (빠름) | Claude Opus (고품질) |
| **Temperature** | 0.3 (일관성) | 0.7 (자연스러움) |
