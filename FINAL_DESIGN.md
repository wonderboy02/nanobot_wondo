# Final Design - Dashboard Sync Manager

**최종 확정 설계 (2026-02-06)**

## 핵심 개념

### Agent의 역할: Dashboard Sync Manager

**Agent는 챗봇이 아니다. 상황판 관리자다.**

```
사용자 메시지 → Agent (조용히 처리) → Dashboard 업데이트 → (끝)
```

- ❌ 직접 답장 안 함
- ✅ Dashboard만 업데이트
- ✅ Question Queue를 통해서만 소통

## 구현된 구조

### 파일 구조

```
workspace/
├── DASHBOARD.md           # Agent 지침
├── AGENTS.md              # (기존)
├── SOUL.md                # (기존)
├── USER.md                # (기존)
├── HEARTBEAT.md           # (기존)
├── memory/
│   └── MEMORY.md
└── dashboard/             # ★ 새로운 Dashboard
    ├── tasks.json         # Task 목록
    ├── questions.json     # Question Queue
    ├── notifications.json # 알림
    └── knowledge/
        ├── history.json   # History (완료 작업, 프로젝트)
        ├── insights.json  # Insights (지식)
        └── people.json    # People (인간관계)
```

### 데이터 스키마

#### tasks.json
```json
{
  "version": "1.0",
  "tasks": [
    {
      "id": "task_001",
      "title": "React 영상 보기",
      "raw_input": "내일까지 React 영상 봐야해",
      "deadline": "2026-02-07T23:59:00",
      "deadline_text": "내일",
      "estimation": {
        "hours": 2,
        "complexity": "medium",
        "confidence": "medium"
      },
      "progress": {
        "percentage": 0,
        "last_update": "2026-02-06T20:00:00",
        "note": "",
        "blocked": false,
        "blocker_note": null
      },
      "status": "active",  // active, someday, completed, cancelled
      "priority": "medium",  // low, medium, high
      "context": "",  // 추가 컨텍스트
      "tags": ["learning", "react"],
      "links": {
        "projects": [],
        "people": [],
        "insights": [],
        "resources": []
      },
      "created_at": "2026-02-06T20:00:00",
      "updated_at": "2026-02-06T20:00:00",
      "completed_at": null
    }
  ]
}
```

#### questions.json
```json
{
  "version": "1.0",
  "questions": [
    {
      "id": "q_001",
      "question": "React 영상 어떤 거야?",
      "context": "Need more info for task_001",
      "priority": "medium",  // low, medium, high
      "type": "info_gather",  // info_gather, progress_check, deadline_check, etc.
      "related_task_id": "task_001",
      "asked_count": 0,
      "last_asked_at": null,
      "created_at": "2026-02-06T20:00:00",
      "cooldown_hours": 24,
      "answered": false,
      "answer": null,
      "answered_at": null
    }
  ]
}
```

#### knowledge/history.json
```json
{
  "version": "1.0",
  "completed_tasks": [
    {
      "id": "task_001",
      "title": "React 영상 보기",
      "completed_at": "2026-02-07T19:00:00",
      "duration_days": 1,
      "progress_note": "완료",
      "links": {},
      "moved_at": "2026-02-07T19:01:00"
    }
  ],
  "projects": [
    {
      "id": "proj_001",
      "name": "React 학습",
      "description": "React 19 새 기능 공부",
      "status": "active",
      "task_ids": ["task_001", "task_002"],
      "created_at": "2026-02-01",
      "updated_at": "2026-02-06"
    }
  ]
}
```

#### knowledge/insights.json
```json
{
  "version": "1.0",
  "insights": [
    {
      "id": "insight_001",
      "category": "tech",  // tech, life, work, learning
      "title": "React Server Components",
      "content": "RSC는...",
      "source": "task_001 영상",
      "tags": ["react", "web"],
      "links": {
        "tasks": ["task_001"],
        "projects": ["proj_001"]
      },
      "created_at": "2026-02-06"
    }
  ]
}
```

#### knowledge/people.json
```json
{
  "version": "1.0",
  "people": [
    {
      "id": "person_001",
      "name": "김멘토",
      "role": "React 멘토",
      "relationship": "온라인 멘토",
      "context": "React 질문할 때 연락",
      "contact": "email@example.com",
      "links": {
        "projects": ["proj_001"],
        "tasks": ["task_003"],
        "insights": ["insight_020"]
      },
      "notes": "주말에 시간 많음",
      "last_contact": "2026-02-01"
    }
  ]
}
```

## 핵심 컴포넌트

### 1. DashboardManager (nanobot/dashboard/manager.py)

Dashboard 로드/저장 담당.

```python
manager = DashboardManager(workspace / "dashboard")
dashboard = manager.load()  # 전체 로드
manager.save(dashboard)     # 전체 저장
```

### 2. WorkerAgent (nanobot/dashboard/worker.py)

30분마다 실행되는 관리자:

**주요 작업:**
1. Task 진행률 체크
2. Question 생성 (7가지 Case)
3. 완료된 Task → History 이동
4. Active/Someday 재평가
5. Question Queue 정리

**진행률 체크 로직:**
- Case 1: 시작 안 함 (0% & 시간 지남)
- Case 2: 많이 늦음 (20%+ gap)
- Case 3: 약간 늦음 (10-20% gap)
- Case 4: 오래 업데이트 없음 (48h+)
- Case 5: Deadline 임박 (2일 이내)
- Case 6: 거의 완료 (80%+)
- Case 7: 정상 진행 (주기적 체크)

### 3. Heartbeat Service (수정됨)

30분마다:
1. **Worker 실행** (Dashboard 체크)
2. HEARTBEAT.md 체크 (기존)

### 4. CLI 명령어

```bash
nanobot dashboard show       # 전체 보기
nanobot dashboard tasks      # Task 목록
nanobot dashboard questions  # Question Queue
nanobot dashboard answer q_001 "답변"  # 질문 답변
nanobot dashboard history    # 완료 작업
nanobot dashboard worker     # Worker 수동 실행
```

## Agent 동작 방식

### 일반 메시지 처리

```
User: "내일까지 React 영상 봐야해"
  ↓
Agent:
  1. read_file("dashboard/tasks.json")
  2. 새 task 추가:
     - title: "React 영상 보기"
     - deadline: "2026-02-07T23:59:00"
     - status: "active" (deadline 가까우니까)
     - progress: 0%
  3. read_file("dashboard/questions.json")
  4. Question 추가:
     - "React 영상 어떤 거야?"
     - priority: "medium"
     - related_task_id: "task_001"
  5. write_file("dashboard/tasks.json")
  6. write_file("dashboard/questions.json")
  ↓
(조용... 아무 답장 없음)
```

### Question 답변 처리

```
User: "React 영상은 이거야: https://..."
  ↓
Agent:
  1. read_file("dashboard/questions.json")
  2. 질문 찾기 (React 관련)
  3. read_file("dashboard/tasks.json")
  4. task_001에 link 추가
  5. Question 답변 처리:
     - answered: true
     - answer: "https://..."
  6. write_file (tasks, questions)
  ↓
(조용...)
```

### Worker 실행 (30분마다)

```
Worker:
  1. dashboard 로드
  2. 모든 active task 체크
     - task_001: 0% & 24시간 지남
       → Question 추가: "시작했어?"
  3. Completed task → History 이동
  4. Active/Someday 재평가
  5. Question Queue 정리 (중복 제거)
  6. dashboard 저장
  ↓
(조용...)
```

## Context 구성

Agent의 Context에 포함되는 것:

```
System Prompt:
  - Identity
  - Current Time ★
  - Workspace Path
  - DASHBOARD.md 지침 ★
  - AGENTS.md
  - SOUL.md
  - USER.md
  - TOOLS.md
  - Memory (MEMORY.md)
  - Skills
  - Active Tasks ★ (자동 포함)
  - Question Queue ★ (자동 포함)
```

## 구현 상태

### ✅ 완료된 것

**Phase 1: 핵심 인프라**
- ✅ dashboard/ 디렉토리 구조
- ✅ DashboardManager (nanobot/dashboard/manager.py)
- ✅ WorkerAgent (nanobot/dashboard/worker.py) - 진행률 체크 로직
- ✅ Pydantic 스키마 (nanobot/dashboard/schema.py)
- ✅ Heartbeat 통합 (Worker 자동 실행)
- ✅ CLI 명령어 (dashboard show, tasks, questions, answer, history, worker)
- ✅ DASHBOARD.md (Agent 지침)
- ✅ 테스트 인프라 (pytest, bash, python 스크립트)
- ✅ 예제 데이터 (tests/fixtures/example_dashboard.json)

**Phase 2: Agent 통합**
- ✅ Context Builder 수정 (DASHBOARD.md 포함)
- ✅ Dashboard Helper (nanobot/dashboard/helper.py) - Dashboard 요약 생성
- ✅ Dashboard State를 Context에 자동 포함 (Active tasks + Questions)
- ✅ 통합 테스트 (scripts/test_context_dashboard.py, scripts/test_agent_dashboard.py)
- ✅ Agent가 DASHBOARD.md 지침을 자동으로 따름

**Phase 3: LLM 테스트 및 최적화**
- ✅ DASHBOARD.md 대폭 간소화 (8.3KB → 4KB)
- ✅ Tool call 유도를 위한 구체적 예제 추가
- ✅ Gemini 3 Pro 통합 및 테스트
- ✅ LiteLLM 업데이트 (1.72.0 → 1.81.9)
- ✅ 실제 Agent 실행 검증 (Dashboard 업데이트 성공)
- ✅ Tool call 동작 확인 (read_file + write_file)
- ✅ E2E 테스트 스크립트 (scripts/test_agent_e2e.py)

### ⏳ 다음 단계

**Phase 4: 프로덕션 준비**
- [ ] Docker 테스트
- [ ] E2E 테스트 개선
- [ ] Link 시스템 검증

**Phase 5: 고급 기능** (Future)
- [ ] Subtask 지원
- [ ] YouTube Summary Tool
- [ ] Project 관리 개선
- [ ] 웹 UI (선택)

## Phase 3 주요 학습 내용

### LLM별 Tool Call 성능

**GPT-4o:**
- ❌ DASHBOARD.md가 길면 tool call 안 함
- ❌ 지침을 읽고 "했다"고 말만 함
- ⚠️ Tool call 유도가 어려움

**Gemini 3 Pro (gemini-3-pro-preview):**
- ✅ DASHBOARD.md 간소화 후 tool call 성공
- ✅ 구체적 예제를 잘 따라함
- ✅ 모든 tool (read_file, write_file) 정확히 호출
- ✅ 경로 지침 (dashboard/ prefix) 잘 따름

### DASHBOARD.md 최적화

**실패한 접근 (8.3KB):**
- 장황한 설명
- 여러 섹션과 규칙
- LLM이 혼란스러워함

**성공한 접근 (4KB):**
- 짧고 명확한 지침
- 구체적인 JSON 형식 tool call 예제
- "YOU MUST CALL THESE TOOLS" 강조
- Step-by-step 워크플로우

### 권장 모델

Dashboard 작업에 최적화된 모델:
1. **Gemini 3 Pro** (gemini/gemini-3-pro-preview) - 추천! ⭐
2. Gemini 2.0 Flash Thinking
3. Claude Opus 4.5 (테스트 예정)

## 설계 원칙

1. **Event-Driven**: 이벤트 발생 → Agent 실행
2. **Silent Agent**: 답장 안 함, Dashboard만 업데이트
3. **Queue-Based Communication**: Question Queue 통한 소통
4. **Worker-Based Maintenance**: 주기적 자동 관리
5. **Natural Language Data**: 자연어 기반 유연한 속성
6. **Link System**: 모든 항목 간 연결 가능
7. **No Over-Engineering**: 단순하고 유지보수 쉽게

## 사용 시나리오

### Scenario 1: 새 Task 추가

```
1. User: "이번 주말에 블로그 글 써야지"
2. Agent: Dashboard 업데이트 (조용)
   - Task 추가 (title: "블로그 글 쓰기", deadline: "주말")
   - Question 추가 ("주제는?")
3. User: (나중에 Question Queue 확인)
   "주제는 React Server Components"
4. Agent: Task 업데이트 (조용)
```

### Scenario 2: 진행 상황 업데이트

```
1. User: "블로그 글 50% 완료"
2. Agent: Dashboard 업데이트 (조용)
   - task.progress.percentage = 50
   - task.progress.note = "50% 완료"
```

### Scenario 3: Worker 자동 체크

```
[30분 후]
1. Worker: Task 체크
   - "블로그 글" 50%, deadline 2일 남음
   - 예상 진행률 대비 괜찮음
   - 48시간 업데이트 없으면 Question 추가
```

### Scenario 4: Task 완료

```
1. User: "블로그 글 다 썼어"
2. Agent: Dashboard 업데이트 (조용)
   - task.status = "completed"
   - task.completed_at = now
3. Worker: (다음 사이클)
   - Task → History 이동
```

## 테스트 방법

### 1. 수동 테스트

```bash
# Dashboard 생성
nanobot onboard

# 상태 확인
nanobot dashboard show

# Worker 실행
nanobot dashboard worker

# Agent에게 메시지 (TODO: Phase 2)
nanobot agent -m "내일까지 React 영상 봐야해"

# Dashboard 다시 확인
nanobot dashboard tasks
nanobot dashboard questions
```

### 2. 통합 테스트 (예정)

```python
# tests/test_dashboard_integration.py
async def test_task_creation():
    # Given: 사용자 메시지
    message = "내일까지 React 영상 봐야해"

    # When: Agent 처리
    await agent.process(message)

    # Then: Dashboard 업데이트 확인
    dashboard = manager.load()
    assert len(dashboard['tasks']) == 1
    assert dashboard['tasks'][0]['title'] == "React 영상 보기"
    assert len(dashboard['questions']) > 0
```

## 다음 단계

1. **Context Builder 수정**: Dashboard를 Context에 포함
2. **Agent 테스트**: 실제로 Dashboard 업데이트하는지 확인
3. **통합 테스트**: 전체 플로우 검증
4. **문서화**: 사용 가이드 작성

---

**Note**: DESIGN_PROPOSAL.md와 IMPLEMENTATION_PLAN.md는 초기 설계 문서입니다. 최종 확정된 설계는 이 문서(FINAL_DESIGN.md)를 참고하세요.
