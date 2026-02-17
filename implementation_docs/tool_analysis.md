# Dashboard Tools - 필요성 분석 및 정리

## 현재 상황

### Worker Agent 도구 (12개)

| 도구 | 카테고리 | 필요성 | 사용 빈도 | 테스트 | 비고 |
|------|---------|--------|----------|--------|------|
| `create_question` | Question | ⚠️ 중간 | 낮음 | ✅ 기존 | Worker가 자동 생성하지만 Main도 생성 가능 |
| `update_question` | Question | ✅ 필수 | 높음 | ✅ 신규 | Priority/Type/Cooldown 조정 - Worker만 |
| `remove_question` | Question | ✅ 필수 | 높음 | ✅ 신규 | 중복/obsolete 제거 - Worker만 |
| `answer_question` | Question | ❌ 불필요 | 거의 없음 | ✅ 기존 | **Worker는 질문에 답하지 않음** |
| `schedule_notification` | Notification | ✅ 필수 | 높음 | ✅ 신규 | Worker 핵심 기능 |
| `update_notification` | Notification | ⚠️ 중간 | 낮음 | ✅ 신규 | 시간 변경 시에만 |
| `cancel_notification` | Notification | ✅ 필수 | 중간 | ✅ 신규 | Task 완료 시 알림 취소 |
| `list_notifications` | Notification | ✅ 필수 | 높음 | ✅ 신규 | 중복 방지 - 매번 호출 |
| `create_task` | Task | ❌ 불필요 | 거의 없음 | ✅ 기존 | **Worker는 Task 생성 안 함** |
| `update_task` | Task | ✅ 필수 | 중간 | ✅ 기존 | Status/Progress 업데이트 |
| `move_to_history` | Task | ✅ 필수 | 중간 | ✅ 기존 | 완료 Task 정리 |
| `[REMOVED]

**문제점**:
1. ❌ `answer_question` - Worker는 질문에 답하지 않음 (Main Agent 역할)
2. ❌ `create_task` - Worker는 Task 생성하지 않음 (Main Agent 역할)
3. ⚠️ `[REMOVED], 실제 사용 사례 불명확

---

### Main Agent 도구 (15개)

| 도구 | 카테고리 | 필요성 | 사용 빈도 | 테스트 | 비고 |
|------|---------|--------|----------|--------|------|
| `read_file` | File | ✅ 필수 | 높음 | ✅ 기존 | 파일 읽기 |
| `write_file` | File | ✅ 필수 | 높음 | ✅ 기존 | 파일 쓰기 |
| `edit_file` | File | ✅ 필수 | 높음 | ✅ 기존 | 파일 편집 |
| `list_dir` | File | ✅ 필수 | 중간 | ✅ 기존 | 디렉토리 목록 |
| `exec` | Shell | ✅ 필수 | 중간 | ✅ 기존 | 쉘 명령 |
| `web_search` | Web | ✅ 필수 | 중간 | ✅ 기존 | 웹 검색 |
| `web_fetch` | Web | ✅ 필수 | 중간 | ✅ 기존 | 웹 페이지 추출 |
| `message` | Messaging | ✅ 필수 | 낮음 | ✅ 기존 | 채널 메시지 전송 |
| `spawn` | Subagent | ✅ 필수 | 낮음 | ✅ 기존 | 서브에이전트 생성 |
| `create_task` | Dashboard | ✅ 필수 | 높음 | ✅ 기존 | Task 생성 |
| `update_task` | Dashboard | ✅ 필수 | 높음 | ✅ 기존 | Task 업데이트 |
| `move_to_history` | Dashboard | ✅ 필수 | 중간 | ✅ 기존 | Task 완료 |
| `answer_question` | Dashboard | ✅ 필수 | 높음 | ✅ 기존 | 질문 답변 |
| `create_question` | Dashboard | ✅ 필수 | 중간 | ✅ 기존 | 질문 생성 |
| `[REMOVED]

**문제점**:
1. ⚠️ `[REMOVED], 실제 사용 사례 불명확
2. ⚠️ Notification 도구 없음 - 사용자 명시적 요청 시 어떻게 처리?

---

## 분석 결과

### 1. 제거해야 할 도구

#### Worker Agent에서 제거
```python
# ❌ answer_question - Worker는 질문에 답하지 않음
# Worker 역할: 질문 생성/업데이트/제거
# Main 역할: 질문 답변

# ❌ create_task - Worker는 Task 생성하지 않음
# Worker 역할: 기존 Task 관리
# Main 역할: 새 Task 생성
```

**이유**:
- Worker는 **분석 및 유지보수** 역할
- 질문에 답변하는 것은 **사용자 대화**가 필요 (Main Agent 역할)
- Task 생성은 **사용자 요청** 기반 (Main Agent 역할)

---

### 2. 추가해야 할 도구

#### Main Agent에 추가 (선택적)
```python
# ⚠️ schedule_notification (선택)
# 사용자가 "내일 9시에 알림 보내줘" 같은 명시적 요청 시 필요
# 현재는 Worker가 모두 처리

# ⚠️ list_notifications (선택)
# 사용자가 "예약된 알림 보여줘" 요청 시 필요
```

**판단**:
- **추가 안 해도 됨**: Worker가 자동으로 처리
- **추가하면 좋음**: 사용자 명시적 요청 지원

---

### 3. 테스트 추가 필요

#### [REMOVED]
```python
# tests/dashboard/unit/test_[REMOVED]
# tests/dashboard/e2e/test_insight_workflow.py (없음)
```

**문제**:
- 구현은 되어있지만 테스트가 없음
- 실제 사용 시나리오 불명확
- Worker가 언제 insight를 저장하는지 정의되지 않음

**옵션**:
1. 테스트 추가 + Worker에서 insight 저장 로직 구현
2. [REMOVED]

---

## 권장 조치

### Option 1: 최소 변경 (안전)

**제거**:
```python
# Worker Agent에서만 제거
- answer_question  # Main이 처리
- create_task      # Main이 처리
```

**유지**:
```python
# 나머지 모두 유지
- [REMOVED]
```

**결과**: Worker 도구 12개 → 10개

---

### Option 2: 적극 정리 (권장)

**제거**:
```python
# Worker Agent에서 제거
- answer_question  # Main이 처리
- create_task      # Main이 처리
- [REMOVED], 테스트 없음

# Main Agent에서 제거
- [REMOVED], 테스트 없음
```

**추가**:
```python
# Main Agent에 추가 (사용자 요청 지원)
+ schedule_notification  # "내일 알림 보내줘"
+ list_notifications     # "알림 목록 보여줘"
```

**결과**:
- Worker: 12개 → 9개
- Main: 15개 → 16개 ([REMOVED], notification 2개 추가)

---

### Option 3: [REMOVED]

**조치**:
1. [REMOVED]
2. Worker에서 insight 저장 로직 구체화
3. WORKER.md에 insight 저장 시나리오 추가

**시나리오**:
```markdown
## Knowledge Base Maintenance

### When to save insights

1. **Recurring Blockers**: Same blocker appears in multiple tasks
   → [REMOVED], category="learning", tags=["react", "blocker"])

2. **Successful Solutions**: Task completed after blocker resolved
   → [REMOVED], category="tech", tags=["react", "solution"])

3. **Patterns**: User's work patterns
   → [REMOVED], category="life", tags=["productivity"])
```

**결과**: [REMOVED]

---

## 최종 권장: Option 2 (적극 정리)

### 이유

1. **명확한 역할 분리**:
   - Worker: 자동 유지보수 (notification, question 관리)
   - Main: 사용자 대화 (task 생성, question 답변)

2. **불필요한 도구 제거**:
   - Worker의 answer_question, create_task (실제로 사용 안 함)
   - [REMOVED], 사용 시나리오 불명확)

3. **사용자 경험 개선**:
   - Main에 notification 도구 추가 → 사용자 명시적 요청 지원
   - "내일 9시에 알림 보내줘" 같은 요청 처리 가능

4. **테스트 커버리지**:
   - 사용하지 않는 도구에 테스트 작성할 필요 없음
   - 필수 도구에만 집중

---

## 구현 계획

### 1단계: Worker Agent 정리

**파일**: `nanobot/dashboard/llm_worker.py`

```python
def _register_worker_tools(self):
    """Register all tools available to Worker Agent."""
    # Question management (2 tools)
    from nanobot.agent.tools.dashboard.update_question import UpdateQuestionTool
    from nanobot.agent.tools.dashboard.remove_question import RemoveQuestionTool
    from nanobot.agent.tools.dashboard.create_question import CreateQuestionTool

    self.tools.register(CreateQuestionTool(self.workspace))
    self.tools.register(UpdateQuestionTool(self.workspace))
    self.tools.register(RemoveQuestionTool(self.workspace))
    # ❌ answer_question 제거

    # Notification management (4 tools)
    from nanobot.agent.tools.dashboard.schedule_notification import ScheduleNotificationTool
    from nanobot.agent.tools.dashboard.update_notification import UpdateNotificationTool
    from nanobot.agent.tools.dashboard.cancel_notification import CancelNotificationTool
    from nanobot.agent.tools.dashboard.list_notifications import ListNotificationsTool

    self.tools.register(ScheduleNotificationTool(self.workspace, self.cron_service))
    self.tools.register(UpdateNotificationTool(self.workspace, self.cron_service))
    self.tools.register(CancelNotificationTool(self.workspace, self.cron_service))
    self.tools.register(ListNotificationsTool(self.workspace))

    # Task management (2 tools)
    from nanobot.agent.tools.dashboard.update_task import UpdateTaskTool
    from nanobot.agent.tools.dashboard.move_to_history import MoveToHistoryTool

    self.tools.register(UpdateTaskTool(self.workspace))
    self.tools.register(MoveToHistoryTool(self.workspace))
    # ❌ create_task 제거
    # ❌ [REMOVED]
```

**결과**: 12개 → 9개

---

### 2단계: Main Agent 정리 및 추가

**파일**: `nanobot/agent/loop.py`

```python
def _register_default_tools(self) -> None:
    """Register the default set of tools."""
    # ... 기존 파일/쉘/웹/메시지/스폰 도구 유지 ...

    # Dashboard tools
    from nanobot.agent.tools.dashboard import (
        CreateTaskTool,
        UpdateTaskTool,
        AnswerQuestionTool,
        CreateQuestionTool,
        MoveToHistoryTool,
        # Notification tools 추가
        ScheduleNotificationTool,
        ListNotificationsTool,
    )

    self.tools.register(CreateTaskTool(workspace=self.workspace))
    self.tools.register(UpdateTaskTool(workspace=self.workspace))
    self.tools.register(AnswerQuestionTool(workspace=self.workspace))
    self.tools.register(CreateQuestionTool(workspace=self.workspace))
    self.tools.register(MoveToHistoryTool(workspace=self.workspace))

    # Notification tools (사용자 명시적 요청)
    if self.cron_service:
        self.tools.register(ScheduleNotificationTool(workspace=self.workspace, cron_service=self.cron_service))
        self.tools.register(ListNotificationsTool(workspace=self.workspace))

    # ❌ [REMOVED]
```

**결과**: 15개 → 16개 ([REMOVED], notification +2)

---

### 3단계: 문서 업데이트

**WORKER.md**:
```markdown
## Available Tools (9 tools)

### Question Management (3 tools)
- create_question: 새 질문 생성
- update_question: 우선순위/타입 조정
- remove_question: 중복/obsolete 제거

### Notification Management (4 tools)
- schedule_notification: 알림 스케줄
- update_notification: 알림 수정
- cancel_notification: 알림 취소
- list_notifications: 알림 목록 (중복 방지)

### Task Management (2 tools)
- update_task: Task 업데이트
- move_to_history: 완료 Task 정리

❌ 제거된 도구:
- answer_question (Main Agent가 처리)
- create_task (Main Agent가 처리)
- [REMOVED]
```

**TOOLS.md**:
```markdown
## Dashboard Management

### Task Management
- create_task: Task 생성
- update_task: Task 업데이트
- move_to_history: 완료

### Question Management
- answer_question: 질문 답변
- create_question: 질문 생성

### Notification Management (NEW!)
- schedule_notification: 알림 예약
- list_notifications: 알림 목록

❌ 제거된 도구:
- [REMOVED]
```

---

### 4단계: 테스트 업데이트

**기존 테스트 유지**:
- test_notification_tools.py ✅
- test_question_management.py ✅
- test_notification_workflow.py ✅

**추가 테스트 (선택)**:
- test_main_agent_notifications.py (Main Agent의 notification 도구 사용)

---

## 요약

### 변경사항

| Agent | Before | After | 변경 |
|-------|--------|-------|------|
| Worker | 12 tools | 9 tools | -3 (answer_question, create_task, [REMOVED]
| Main | 15 tools | 16 tools | +1 ([REMOVED], notification +2) |

### 장점

1. ✅ **명확한 역할**: Worker는 유지보수, Main은 대화
2. ✅ **불필요한 도구 제거**: 사용 안 하는 도구 정리
3. ✅ **사용자 경험 개선**: Main이 notification 요청 처리
4. ✅ **테스트 집중**: 필수 도구에만 테스트 작성

### 단점

1. ⚠️ [REMOVED]
2. ⚠️ Main에 cron_service 의존성 추가 필요

---

## 결론

**권장**: Option 2 (적극 정리)
- Worker에서 불필요한 도구 3개 제거
- Main에 notification 도구 2개 추가
- [REMOVED]

**다음 단계**:
1. llm_worker.py 수정 (도구 제거)
2. loop.py 수정 (notification 도구 추가)
3. 문서 업데이트 (WORKER.md, TOOLS.md, AGENTS.md)
4. 테스트 실행 (기존 테스트 통과 확인)
