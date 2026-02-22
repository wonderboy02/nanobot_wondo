# nanobot Project Guide

이 문서는 nanobot 프로젝트의 구조와 개발 가이드라인을 설명합니다.

## 프로젝트 개요

**nanobot**은 초경량 개인 AI 어시스턴트 프레임워크입니다.
- **핵심 코드**: ~3,400 라인 (Clawdbot 대비 99% 작은 크기)
- **언어**: Python 3.11+
- **라이선스**: MIT
- **버전**: 0.1.4

## 아키텍처

### 핵심 컴포넌트

```
nanobot/
├── agent/              # 🧠 핵심 에이전트 로직
│   ├── loop.py         # Agent loop (LLM ↔ tool 실행)
│   ├── context.py      # Prompt builder (시스템 프롬프트 구성)
│   ├── memory.py       # 영속적 메모리 관리
│   ├── skills.py       # 스킬 로더
│   ├── subagent.py     # 백그라운드 작업 실행
│   └── tools/          # 빌트인 도구 (파일, 쉘, 웹 등)
│       ├── base.py     # Tool 기본 클래스
│       ├── filesystem.py  # 파일 읽기/쓰기/편집/목록
│       ├── shell.py    # 쉘 명령 실행
│       ├── web.py      # 웹 검색/페치
│       ├── message.py  # 사용자에게 메시지 전송
│       ├── spawn.py    # 서브 에이전트 생성
│       └── cron.py     # 스케줄 작업 관리
├── channels/           # 📱 채팅 플랫폼 통합
│   ├── base.py         # 채널 기본 클래스
│   ├── telegram.py     # Telegram 봇
│   ├── discord.py      # Discord 봇
│   ├── whatsapp.py     # WhatsApp (Baileys 사용)
│   └── feishu.py       # Feishu (飞书) 봇
├── providers/          # 🤖 LLM 프로바이더
│   └── client.py       # LiteLLM 기반 통합 클라이언트
├── bus/                # 🚌 메시지 라우팅
│   ├── events.py       # 이벤트 정의
│   └── queue.py        # 메시지 큐
├── cron/               # ⏰ 스케줄 작업
│   └── scheduler.py    # Cron 스케줄러
├── dashboard/          # 📊 Dashboard 관리 시스템
│   ├── storage.py      # StorageBackend ABC + JsonStorageBackend
│   ├── manager.py      # Dashboard 로드/저장 (레거시, rule worker용)
│   ├── worker.py       # Rule-based Worker Agent
│   ├── llm_worker.py   # LLM Worker Agent (StorageBackend 경유)
│   ├── schema.py       # Pydantic 스키마 (데이터 검증)
│   └── helper.py       # Dashboard 요약 헬퍼 (Context Builder용)
├── notion/             # 🔗 Notion API 통합
│   ├── client.py       # Sync NotionClient (httpx, rate limit, retry)
│   ├── mapper.py       # 내부 dict ↔ Notion 프로퍼티 양방향 매핑
│   └── storage.py      # NotionStorageBackend + MemoryCache
├── heartbeat/          # 💓 주기적 작업 체크 (30분마다)
├── session/            # 💬 대화 세션 관리
├── config/             # ⚙️ 설정 관리
├── skills/             # 🎯 번들 스킬
│   ├── cron/           # Cron 스킬
│   ├── github/         # GitHub 통합
│   ├── weather/        # 날씨 정보
│   ├── tmux/           # tmux 통합
│   ├── summarize/      # 텍스트 요약
│   └── skill-creator/  # 스킬 생성 도구
├── cli/                # 🖥️ CLI 명령어
└── utils/              # 🔧 유틸리티

bridge/                 # WhatsApp 브릿지 (TypeScript)
├── src/
│   ├── index.ts        # 메인 진입점
│   ├── server.ts       # WebSocket 서버
│   ├── whatsapp.ts     # Baileys 통합
│   └── types.d.ts      # TypeScript 타입 정의
└── package.json        # Node.js 의존성

workspace/              # 사용자 워크스페이스
├── AGENTS.md           # 에이전트 지시사항
├── SOUL.md             # 에이전트 페르소나
├── USER.md             # 사용자 프로파일
├── TOOLS.md            # 사용 가능한 도구 설명
├── HEARTBEAT.md        # 주기적 작업 목록
├── DASHBOARD.md        # Dashboard 관리 지침
├── NOTION_SETUP.md     # Notion DB 스키마 및 셋업 가이드
├── memory/             # 에이전트 메모리
│   └── MEMORY.md       # 장기 메모리
└── dashboard/          # Dashboard 데이터 (NEW!)
    ├── tasks.json      # Task 목록
    ├── questions.json  # Question Queue
    ├── notifications.json  # 알림
    └── knowledge/      # 지식베이스
        └── insights.json   # 저장된 지식
```

## 구현 예정 (Planned Features)

다음 기능들은 설계가 완료되어 구현 문서가 준비되어 있습니다:

### 1. Question Queue 번호 매핑 답변 + Dashboard Lock

**문서**: [`implementation_docs/question_answer_numbered_mapping.md`](implementation_docs/question_answer_numbered_mapping.md)

**목적**:
- Question Queue 답변을 위한 **번호 매핑 방식** 구현
- Worker ↔ Main Agent 간 Dashboard 파일 충돌 방지 (asyncio.Lock)

**주요 기능**:
- `/questions` 명령어로 질문 목록 조회 (번호 표시)
- 번호 형식으로 답변 (예: "1. 답변1\n2. 답변2")
- **한 번에 여러 질문 답변** 가능
- Dashboard 도구에 Lock 적용 (충돌 확률 0%)
- Worker Agent에 Retry 로직 (Lock 잡혀있으면 3분 후 재시도)

**기술 스택**:
- 메모리 캐시 (딕셔너리, TTL 1시간, 크기 제한 100개)
- 정규표현식 파싱 (Python `re` 모듈)
- `asyncio.Lock` (전역 Lock)
- Message Bus metadata 활용

**수정 예정 파일**:
- `nanobot/channels/telegram.py` (번호 매핑 시스템, ~120줄)
- `nanobot/agent/loop.py` (Lock + metadata 처리, ~30줄)
- `nanobot/agent/tools/dashboard/base.py` (Lock 통합, ~15줄)
- `nanobot/agent/tools/dashboard/*.py` (6개 도구, 각 ~5줄)
- `nanobot/heartbeat/service.py` (Worker Retry, ~30줄)

**Total: ~280줄 추가** (Inline Keyboard 대비 50% 감소)

---

### 2. Recurring Tasks System

**문서**: [`implementation_docs/recurring-tasks-implementation.md`](implementation_docs/recurring-tasks-implementation.md)

**목적**:
- 매일 반복되는 작업(습관) 관리 시스템 추가
- Streak tracking (연속 달성 일수), 자동 질문 생성
- Dashboard Tools 기반 설계 (v0.1.5 이후)

**주요 기능**:
- Daily recurring tasks (주중/주말 필터 지원)
- 자동 질문 생성 (특정 시간에, e.g., "09:00")
- Streak tracking (연속 달성 일수)
- Statistics (총 완료/누락 횟수)
- Worker에서 자동 관리 (Daily reset, Question generation)

**기술 스택**:
- Pydantic schemas (RecurringConfig, RecurringStatistics)
- Dashboard Tools integration (create_task, update_task)
- Worker Agent (check_recurring_tasks)

**수정 예정 파일**:
- `nanobot/dashboard/schema.py` (RecurringConfig 추가, ~80줄)
- `nanobot/agent/tools/dashboard/create_task.py` (recurring 파라미터, ~30줄)
- `nanobot/agent/tools/dashboard/update_task.py` (recurring 업데이트, ~20줄)
- `nanobot/dashboard/worker.py` (check_recurring_tasks 메서드, ~150줄)
- `nanobot/dashboard/helper.py` (Recurring 정보 표시, ~30줄)
- `workspace/DASHBOARD.md` (Recurring Tasks 섹션, ~80줄)

**Total: ~390줄 추가**

---

## 개발 가이드라인

### 코드 스타일

- **Formatter**: ruff
- **Line length**: 100자
- **Python version**: 3.11+
- **Type hints**: 권장

```bash
# 코드 포맷팅
ruff format .

# 린팅
ruff check .
```

### 의존성 관리

**Python 의존성** (pyproject.toml):
- `typer`: CLI 프레임워크
- `litellm`: 통합 LLM 클라이언트
- `pydantic`: 데이터 검증
- `websockets`: WebSocket 통신
- `python-telegram-bot`: Telegram 통합
- `lark-oapi`: Feishu 통합
- `croniter`: Cron 표현식 파싱
- `loguru`: 로깅
- `rich`: 터미널 출력 포맷팅
- `httpx`: HTTP 클라이언트
- `readability-lxml`: 웹 콘텐츠 추출

**TypeScript 의존성** (bridge/package.json):
- `@whiskeysockets/baileys`: WhatsApp 클라이언트
- `ws`: WebSocket 서버
- `qrcode-terminal`: QR 코드 출력
- `pino`: 로깅

### 설치 및 개발

```bash
# 소스에서 설치 (개발용)
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .

# 또는 uv 사용
uv tool install nanobot-ai

# 또는 PyPI에서 설치
pip install nanobot-ai

# WhatsApp 브릿지 빌드
cd bridge
npm install
npm run build
```

### 테스트

```bash
# 전체 테스트 실행
pytest

# 특정 테스트 실행
pytest tests/test_agent.py

# 비동기 테스트 (pytest-asyncio 사용)
pytest tests/test_async.py
```

### 코드 라인 수 확인

```bash
bash core_agent_lines.sh
```

## 핵심 기능

### 1. Agent Loop (agent/loop.py)

에이전트의 핵심 실행 루프:
1. 사용자 메시지 수신
2. Context 생성 (시스템 프롬프트 + 대화 히스토리)
3. LLM에 요청
4. Tool 호출 처리
5. 응답 반환
6. 반복

### 2. Tools System (agent/tools/)

도구는 `Tool` 기본 클래스를 상속:
```python
class Tool:
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> dict: ...

    async def execute(self, **kwargs) -> str: ...
```

**주요 도구**:
- `read_file`, `write_file`, `edit_file`, `list_dir`: 파일 조작
- `exec`: 쉘 명령 실행 (보안 제한 있음)
- `web_search`: Brave Search API 사용
- `web_fetch`: URL 콘텐츠 추출
- `message`: 사용자에게 메시지 전송
- `spawn`: 백그라운드 서브에이전트 생성

### 3. Skills System (agent/skills.py)

스킬은 확장 가능한 기능 모듈:
- 각 스킬은 `SKILL.md` 파일을 포함
- `SKILL.md`는 에이전트의 컨텍스트에 자동으로 포함됨
- 스킬은 추가 도구나 지시사항을 제공

**스킬 생성**:
```bash
nanobot skill create my-skill
```

### 4. Channels (channels/)

여러 채팅 플랫폼 지원:
- **Telegram**: 가장 쉬운 설정 (토큰만 필요)
- **Discord**: 봇 토큰 + 인텐트 설정
- **WhatsApp**: QR 스캔 필요 (Baileys 사용)
- **Feishu**: 앱 ID + Secret (WebSocket long connection)

모든 채널은 `allowFrom` 설정으로 접근 제어 가능.

### 5. Scheduled Tasks (cron/)

Cron 표현식 또는 간격으로 작업 스케줄:
```bash
# 매일 9시에 실행
nanobot cron add --name "morning" --message "Good morning!" --cron "0 9 * * *"

# 2시간마다 실행
nanobot cron add --name "reminder" --message "Take a break" --every 7200

# 특정 시간에 한 번 실행
nanobot cron add --name "meeting" --message "Meeting!" --at "2026-02-07T15:00:00"
```

### 6. Heartbeat (heartbeat/)

`workspace/HEARTBEAT.md` 파일을 30분마다 체크하여 주기적 작업 실행.
또한 30분마다 Worker Agent를 실행하여 Dashboard 진행률 체크 및 질문 생성.

### 7. Dashboard System (v0.1.5 Updated)

**맥락 기반 Task 관리 시스템 with Dashboard Tools**

#### **핵심 설계 변경사항**

**v0.1.6 (Notion 통합 + Storage Backend)**:
- ✅ **StorageBackend 추상화** - JSON/Notion을 동일 인터페이스로 사용
- ✅ **Notion 일원화 모드** - Notion이 Single Source of Truth (설정 시)
- ✅ **인메모리 캐시** - 5분 TTL, 메시지/Worker 시작 시 무효화
- ✅ **13개 Dashboard Tool 변경 없음** - Backend만 교체
- ✅ **Fallback** - `notion.enabled=false`면 기존 JSON 방식 유지

**Storage Backend 아키텍처**:
```
Dashboard Tools (13개, 인터페이스 변경 없음)
       │
  StorageBackend (추상화 레이어)
       ├── JsonStorageBackend (기본, 로컬 JSON)
       └── NotionStorageBackend (Notion API + MemoryCache)
              ├── NotionClient (sync httpx, retry + rate limit)
              └── NotionMapper (스키마 양방향 매핑)
```

**Notion 설정** (`~/.nanobot/config.json`):
```json
{
  "notion": {
    "enabled": true,
    "token": "secret_xxx",
    "databases": {
      "tasks": "db_id",
      "questions": "db_id",
      "notifications": "db_id",
      "insights": "db_id"
    },
    "cache_ttl_s": 300
  }
}
```

**v0.1.5 (Dashboard Tools System)**:
- ✅ **6개의 전용 도구** 추가 (create_task, update_task, answer_question, etc.)
- ✅ **자동 ID/Timestamp 생성** - Agent가 수동으로 생성할 필요 없음
- ✅ **Pydantic 검증** - 모든 Dashboard 업데이트에서 schema 검증
- ✅ **파일 보호 강화** - Dashboard JSON 파일들이 write_file로부터 보호됨
- ✅ **DASHBOARD.md 간소화** - 305줄 → 248줄 (18% 감소)
- ✅ **에러 방지** - 잘못된 JSON 구조 생성 불가능

**v0.1.4 (Stateless Architecture)**

**Stateless Agent 아키텍처**:
- ✅ Session history를 LLM context에서 **완전 제거**
- ✅ Dashboard Summary가 모든 맥락 제공 (Single Source of Truth)
- ✅ Token 절감 (~5,000 tokens per request)
- ✅ Context 희석 방지

**이전 구조 (v0.1.3)**:
```
[System Prompt] + [Session History 50개] + [Current Message]
```

**현재 구조 (v0.1.4)**:
```
[System Prompt + Dashboard Summary (전체 상태)] + [Current Message]
```

#### **Dashboard Summary 강화**

**제한 제거**:
- Active Tasks: 10개 → **무제한 (모든 active tasks)**
- Unanswered Questions: 5개 → **무제한 (모든 unanswered)**

**상세 정보 추가**:
```markdown
**task_001**: React 공부
- Progress: 50%
- Deadline: 내일
- Priority: high
- Context: 유튜브 강의로 학습 중
- ⚠️ Blocked: Hook 부분 어려움
- Tags: react, study

**q_001**: 어떤 자료로 공부할 거야?
- Priority: medium
- Type: info_gather
- Related Task: task_001
- Asked: 1 times
- Last Asked: 2026-02-08
- Context: Task progress check
```

#### **맥락 기반 업데이트**

**핵심 원리**:
- 하나의 메시지가 여러 정보 포함 가능
- Agent가 전체 맥락 이해
- Dashboard 전체를 원자적으로 업데이트

**예시**:
```
User: "유튜브로 공부하고 있는데 50% 완료했어요. Hook이 어려워요."

Agent 분석:
├─ "유튜브" → q_001 ("어떤 자료?") 답변
├─ "50%" → q_002 ("진행률?") 답변
├─ "Hook 어려워" → q_003 ("막히는 부분?") 답변 + blocker 추가
└─ 새 질문 생성: "Hook 자료 찾아봤어?"

Dashboard 업데이트:
├─ task_001: progress=50%, blocker=true
├─ q_001, q_002, q_003: answered=true
└─ q_004 추가 (Hook 관련)
```

#### **Dashboard Tools (v0.1.5)**

Agent는 Dashboard 전용 도구를 사용하여 안전하고 검증된 방식으로 Dashboard를 업데이트합니다:

**Task 관리**:
- `create_task(title, deadline, priority, context, tags)` - Task 생성
- `update_task(task_id, progress, status, blocked, blocker_note, ...)` - Task 업데이트
- `archive_task(task_id, reflection)` - 완료 Task를 아카이브 (status='archived')

**Question 관리**:
- `answer_question(question_id, answer)` - 질문 답변
- `create_question(question, priority, type, related_task_id)` - 질문 생성

**Knowledge 관리**:
- `save_insight(content, category, title, tags)` - 지식 저장

**장점**:
```python
# Before (복잡, 오류 발생 가능)
dashboard = read_file("dashboard/tasks.json")
data = json.loads(dashboard)
data["tasks"].append({"id": "task_...", ...})  # 20+ 필드 수동 구성
write_file("dashboard/tasks.json", json.dumps(data))

# After (간단, 안전)
create_task(title="블로그 작성", deadline="금요일", priority="medium")
```

**자동 처리**:
- ✅ ID 생성 (`task_xxxxxxxx`, `q_xxxxxxxx`)
- ✅ Timestamp 처리 (`created_at`, `updated_at`, `answered_at`)
- ✅ Schema 검증 (Pydantic)
- ✅ 올바른 JSON 구조 보장

#### **파일 접근 제어 (v0.1.5 Updated)**

지침 파일과 Dashboard 데이터 파일을 Agent 수정으로부터 보호:

**보호 대상 (Read-only for write_file/edit_file)**:
- `DASHBOARD.md`, `TOOLS.md`, `AGENTS.md`, `SOUL.md`, `USER.md`
- `IDENTITY.md`, `HEARTBEAT.md`
- `config.json`, `.env`
- `dashboard/*.json` (tasks, questions, notifications) - **Dashboard 도구 사용 필수**
- `dashboard/knowledge/*.json` (insights) - **Dashboard 도구 사용 필수**

**허용 대상 (Read/Write)**:
- `memory/*.md`
- 기타 workspace 파일

**에러 처리**:
```python
# Agent가 DASHBOARD.md 쓰기 시도
PermissionError: "DASHBOARD.md is a read-only instruction file."

# Agent가 dashboard/tasks.json 쓰기 시도
PermissionError: "Use dashboard tools (create_task, update_task, etc.)
instead of write_file."

# Agent가 올바른 도구 사용
create_task(title="블로그 작성", deadline="금요일")  # ✅ 성공
```

#### **Silent 모드**

Dashboard 업데이트 시 불필요한 응답 방지:
```python
# Agent가 "SILENT" 응답 → 메시지 전송 안 함
# Session에는 기록됨 (디버깅용)
```

**응답 규칙**:
- 일반 메시지 (Task/답변): `SILENT`
- 명령어 (`/questions`, `/tasks`): 결과 표시
- 시스템 메시지: `SILENT`

#### **Worker Agent 통합**

**실행**: Heartbeat에서 30분마다 자동 실행

**역할**:
- Task 진행률 분석 (시간 기반 예상 vs 실제)
- 자동 질문 생성 (진행 느림, deadline 임박 등)
- 완료된 Task를 History로 이동
- Active/Someday 상태 재평가
- Question Queue 정리 (중복 제거, 오래된 거 삭제)

**Main Agent와의 차이**:
- Worker: **로직 기반** (자동화된 체크)
- Main Agent: **맥락 기반** (사용자 메시지 이해)

#### **Race Condition 처리**

**현황**:
- Main Agent: Queue로 순차 처리 (안전)
- Worker Agent: 파일 직접 수정 (충돌 가능성 0.056%)

**전략**:
- 충돌 허용 (확률 매우 낮음)
- Session history 제거로 context 오염 문제 해결
- Worker 메시지도 Queue에 쌓이지만 영향 없음

#### **사용 방법**

**CLI**:
```bash
nanobot dashboard show       # 전체 보기
nanobot dashboard tasks      # Task 목록
nanobot dashboard questions  # Question Queue
nanobot dashboard answer q_001 "답변"  # 질문 답변
nanobot dashboard history    # 완료 작업
nanobot dashboard worker     # Worker 수동 실행
```

**Telegram**:
```
/questions  → Question Queue 조회
/tasks      → Active Tasks 조회

일반 메시지 → Dashboard 업데이트 (Silent)
```

## 보안 (SECURITY.md)

### 주요 보안 기능

1. **Path Traversal 방지**: 파일 작업에서 경로 검증
2. **위험 명령어 차단**: `rm -rf /`, fork bomb 등 차단
3. **출력 제한**: 명령어 출력 10KB로 제한
4. **타임아웃**: 명령어 실행 60초 타임아웃
5. **접근 제어**: 채널별 `allowFrom` 화이트리스트
6. **Workspace 제한**: `restrictToWorkspace: true` 설정 가능
7. **지침 파일 보호**: DASHBOARD.md, config.json 등 read-only 패턴 기반 차단

### 설정 예시 (config.json)

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "tools": {
    "restrictToWorkspace": true,  // 워크스페이스로 제한
    "web": {
      "search": {
        "apiKey": "BSA-xxx"
      }
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["123456789"]  // 사용자 ID 화이트리스트
    }
  }
}
```

## 커스터마이징

### 1. 에이전트 페르소나 변경

`workspace/SOUL.md` 파일을 편집하여 에이전트의 성격을 정의:
```markdown
# Soul

I am your helpful assistant.

## Personality
- Friendly and professional
- Detail-oriented
- Proactive

## Communication Style
- Clear and concise
- Use examples when helpful
```

### 2. 사용자 프로파일 설정

`workspace/USER.md`에 사용자 정보를 추가:
```markdown
## Basic Information
- **Name**: Your Name
- **Timezone**: UTC+9
- **Language**: Korean

## Preferences
- Brief and concise responses
- Technical explanations preferred
```

### 3. 커스텀 도구 추가

`nanobot/agent/tools/` 디렉토리에 새 도구 추가:
```python
from nanobot.agent.tools.base import Tool

class MyCustomTool(Tool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Description of my tool"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "Parameter description"}
            },
            "required": ["param"]
        }

    async def execute(self, param: str) -> str:
        # 도구 로직 구현
        return f"Result: {param}"
```

`agent/loop.py`의 `_register_default_tools()`에 등록:
```python
def _register_default_tools(self):
    # ... 기존 도구들 ...
    self.register_tool(MyCustomTool(self.config))
```

### 4. 커스텀 스킬 추가

```bash
nanobot skill create my-skill
```

`nanobot/skills/my-skill/SKILL.md` 파일을 편집하여 스킬 정의.

## 배포

### Docker

```bash
# 이미지 빌드
docker build -t nanobot .

# 초기화 (최초 1회)
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# 설정 편집
vim ~/.nanobot/config.json

# Gateway 실행
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# 단일 명령 실행
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "Hello!"
```

### 프로덕션 배포

1. **전용 사용자 생성**:
```bash
sudo useradd -m -s /bin/bash nanobot
```

2. **권한 설정**:
```bash
chmod 700 ~/.nanobot
chmod 600 ~/.nanobot/config.json
```

3. **Systemd 서비스** (선택):
```ini
[Unit]
Description=nanobot Gateway
After=network.target

[Service]
Type=simple
User=nanobot
WorkingDirectory=/home/nanobot
ExecStart=/usr/local/bin/nanobot gateway
Restart=always

[Install]
WantedBy=multi-user.target
```

## CLI 명령어

```bash
# 기본 명령어
nanobot onboard           # 초기 설정
nanobot agent -m "..."    # 일회성 채팅
nanobot agent             # 대화형 모드
nanobot gateway           # Gateway 시작 (채널 연결)
nanobot status            # 상태 확인

# Dashboard 명령어 (NEW!)
nanobot dashboard show       # Dashboard 전체 보기
nanobot dashboard tasks      # Task 목록
nanobot dashboard questions  # Question Queue
nanobot dashboard answer <id> "답변"  # 질문 답변
nanobot dashboard history    # 완료 작업
nanobot dashboard worker     # Worker 수동 실행

# 채널 관리
nanobot channels login    # WhatsApp QR 스캔
nanobot channels status   # 채널 상태 확인

# Cron 관리
nanobot cron add          # Cron 작업 추가
nanobot cron list         # Cron 작업 목록
nanobot cron remove <id>  # Cron 작업 삭제

# Notion 관리
nanobot notion validate   # Notion DB 연결 검증
```

## 기여 가이드

1. **Fork** 저장소
2. **Feature branch** 생성: `git checkout -b feature/my-feature`
3. **Commit**: `git commit -m "Add my feature"`
4. **Push**: `git push origin feature/my-feature`
5. **Pull Request** 생성

### 코드 리뷰 체크리스트

- [ ] 코드가 100자 이내로 포맷됨
- [ ] Type hints 추가됨
- [ ] Docstring 작성됨
- [ ] 테스트 추가됨
- [ ] SECURITY.md 가이드라인 준수
- [ ] 코어 라인 수 제한 유지 (~4,000 라인 이내)

## 문제 해결

### 일반적인 문제

1. **ModuleNotFoundError**:
```bash
pip install -e .
```

2. **API Key 에러**:
`~/.nanobot/config.json`에서 API 키 확인

3. **WhatsApp 연결 실패**:
```bash
# Terminal 1
nanobot channels login

# Terminal 2
nanobot gateway
```

4. **Permission Denied**:
```bash
chmod 600 ~/.nanobot/config.json
chmod 700 ~/.nanobot
```

## 로드맵

- [x] Voice Transcription (Groq Whisper)
- [ ] Multi-modal (이미지, 음성, 비디오)
- [ ] Long-term memory
- [ ] Better reasoning (multi-step planning)
- [ ] More integrations (Slack, email, calendar)
- [ ] Self-improvement

## 리소스

- **GitHub**: https://github.com/HKUDS/nanobot
- **PyPI**: https://pypi.org/project/nanobot-ai/
- **Discord**: https://discord.gg/MnCvHqpUGB
- **Documentation**: README.md, SECURITY.md

## Known Limitations & Technical Debt (Notion 통합)

Notion 통합 작업 중 발견된 알려진 제약사항/안티패턴입니다. 수정 시 참고하세요.

### 1. 동기 I/O 블로킹 (의도적 설계)
- **위치**: `nanobot/notion/client.py` — `httpx.Client` (sync)
- **설명**: NotionClient가 동기 HTTP를 사용하여 async 이벤트 루프를 블로킹함
- **영향**: 대량 저장 시 (20개 task → ~6초) 봇 응답성 저하 가능
- **이유**: async/sync 브릿지 문제(`_run_async` + `ThreadPoolExecutor` → 이벤트 루프 교차 공유)를 피하기 위해 의도적으로 sync 채택. 단일 유저 환경에서 Notion ~300ms는 LLM 2-10s 대비 무시 가능
- **개선안**: `asyncio.to_thread()` 래핑 또는 `httpx.AsyncClient`를 단일 루프에서만 사용하도록 보장

### 2. 클래스 레벨 전역 상태 (`_configured_backend`)
- **위치**: `nanobot/agent/tools/dashboard/base.py:32`
- **설명**: `BaseDashboardTool._configured_backend`가 클래스 변수로 모든 인스턴스가 공유
- **영향**: 테스트 병렬 실행 시 격리 위험, 동일 프로세스에서 AgentLoop 재생성 시 잠재적 오염
- **현재 대응**: AgentLoop 초기화 시 `configure_backend(None)` 명시적 reset 추가됨
- **개선안**: 의존성 주입 패턴으로 전환 (Tool 생성자에 backend 직접 전달)

### 3. Rule Worker가 StorageBackend 미사용
- **위치**: `nanobot/dashboard/worker.py` — `WorkerAgent`
- **설명**: Rule-based Worker가 `DashboardManager`를 직접 사용하여 로컬 JSON만 읽기/쓰기
- **영향**: Notion 모드에서 LLM Worker 실패 시 rule worker 폴백이 로컬 JSON과 Notion 상태를 분리시킴
- **현재 대응**: Notion 모드 시 rule worker 폴백 건너뜀 (`heartbeat/service.py`)
- **개선안**: `WorkerAgent`를 `StorageBackend` 경유로 리팩토링

### 4. TelegramNotificationManager 미연결
- **위치**: `nanobot/channels/telegram.py:84`
- **설명**: 스마트 알림 매니저 (야간모드, 중복제거, 배치)가 생성만 되고 실제 전송 경로에 연결 안 됨
- **현재 상태**: 인스턴스만 존재 (`self.notifications`), Worker/Heartbeat에서 알림 배칭 호출 미구현
- **개선안**: Heartbeat Worker에서 알림 생성 시 `notifications.should_send()` → Telegram 전송 플로우 연결

### 5. insights Pydantic 검증 없음
- **위치**: `nanobot/dashboard/storage.py` (JsonStorageBackend), `nanobot/notion/storage.py` (NotionStorageBackend)
- **설명**: tasks/questions/notifications는 Pydantic 검증 후 저장하지만, insights는 검증 없이 저장
- **이유**: 기존 JSON 백엔드에서도 검증 없었고, 이 엔티티는 스키마가 유연함
- **개선안**: `dashboard/schema.py`에 validate_insights_file 등 추가

### 6. NotificationPolicyConfig 범위 검증 없음
- **위치**: `nanobot/config/schema.py` — `NotificationPolicyConfig`
- **설명**: `quiet_hours_start/end`, `daily_limit` 등에 값 범위 검증 없음 (예: hour가 0-23인지)
- **개선안**: Pydantic `Field(ge=0, le=23)` 등 validator 추가

### 7. tasks.json 무한 증가 (Archived Tasks)
- **위치**: `nanobot/agent/tools/dashboard/archive_task.py`, `nanobot/dashboard/worker.py`
- **설명**: 이전 설계에서는 완료된 task가 history.json으로 이동되어 tasks.json은 active task만 유지했지만, 현재는 archived task가 tasks.json에 계속 누적됨
- **영향**: 수백 개 task가 쌓이면 파일 크기 증가, DashboardManager.load() 메모리/성능 저하, Notion 모드에서 전체 query 비용 증가
- **현재 대응**: Dashboard Summary는 active tasks만 필터링하므로 LLM context에는 영향 없음
- **개선안**: 주기적 pruning (예: 3개월 이상 archived task 삭제) 또는 별도 archive 파일로 이동

### 8. TelegramNotificationManager 서버 timezone 의존
- **위치**: `nanobot/channels/telegram.py` — `_is_quiet_hours()`
- **설명**: `datetime.now().hour`로 서버 로컬 시간 사용. 서버가 UTC 클라우드에 배포되면 quiet hours가 의도대로 동작하지 않음
- **현재 대응**: 단일 사용자 + 로컬 실행 환경에서는 문제없음
- **개선안**: timezone-aware datetime 사용 또는 config에 timezone 설정 추가

### 9. OutboundMessage에 명시적 type 필드 없음
- **위치**: `nanobot/bus/events.py` — `OutboundMessage`
- **설명**: reaction 기능 추가로 `OutboundMessage`가 텍스트 외 메시지 타입(reaction)도 전달하게 되었으나, 메시지 종류를 `metadata` 딕셔너리의 convention(`"reaction"` 키 존재 여부)으로 구분하고 있음
- **현재 대응**: 각 채널 `send()`에서 `not msg.content and msg.metadata.get("reaction")` guard로 처리. 현재 reaction 하나뿐이므로 충분함
- **개선안**: 메시지 타입이 늘어나면 (edit, button, image 등) `OutboundMessage`에 `type: str = "text"` 필드를 추가하여 명시적으로 구분

## 라이선스

MIT License - 자세한 내용은 LICENSE 파일 참조
