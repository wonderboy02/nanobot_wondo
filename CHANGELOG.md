# Changelog

## [Unreleased]

### Added

- **Snapshot-based User Change Detection (Worker Phase 1)**: Field-level snapshot guard — each destructive rule (R6, R1, R2a, R5, reevaluate) checks only its guard fields against the previous cycle's snapshot. User-changed fields are preserved, non-guard changes (e.g. title) don't block rules.
- **Active Sync (Worker Phase 1)**: When user changes task `status`, related fields are actively synced — `status → completed` syncs `progress=100%` and `completed_at=now`; `status → active/someday` (from completed/archived) clears `completed_at`. User-set values are always preserved. Runs before consistency rules so sync results feed into R1-R8 naturally.
- **R7/R8 deadline backfill (Worker Phase 1)**: R7 backfills `deadline` from parseable ISO in `deadline_text`; R8 reverse-backfills `deadline_text` from `deadline` when empty.
- **Notion Integration (StorageBackend)**: `StorageBackend` ABC with `JsonStorageBackend` (default) and `NotionStorageBackend` (Notion API + 5-min TTL memory cache). Dashboard tools unchanged — backend swap only.
- **Notification Tools (4)**: `schedule_notification`, `update_notification`, `cancel_notification`, `list_notifications` — always registered (ledger-only). Dashboard tools: 6 -> 12.
- **Numbered Answer System**: Telegram `/questions` returns numbered list; user replies `"1. answer\n2. answer"` format. Full auto-process skips LLM call (token savings). Cache: TTL 1h, max 100.
- **Reaction Mode**: Replaces plain SILENT — sends emoji reaction to original message on dashboard updates. Implementation in `loop.py` `_reaction_message()` and each channel's reaction guard.
- **CI/CD Pipeline**: GH Actions (`deploy.yml`) -> SSH -> `deploy.sh` with first-run config bootstrap and `docker compose up --build --force-recreate -d`.
- **Dashboard Lock**: `@with_dashboard_lock` decorator (asyncio.Lock) on all 12 dashboard tools to prevent race conditions.
- **Question Management Tools (2)**: `update_question`, `remove_question` — completes CRUD for question queue.

### Changed

- **Worker Unification**: Merged `worker.py` (rule-based) + `llm_worker.py` into single `WorkerAgent` with Phase 1 (deterministic) + Phase 2 (LLM). Removed `llm_worker.py`.
- **TYPE_CHECKING Guards**: Type-hint-only imports moved inside `if TYPE_CHECKING:` blocks. Relaxed ruff lint rules to critical only (`E9, F63, F7, F82`).
- **CLAUDE.md Overhaul**: 884 lines -> ~220 lines. Converted from general project guide to fork operation snapshot + enforced rules document. Previous version archived in `CLAUDE.archive.md`.
- **Copilot Instructions**: Moved from `.github/workflows/copilot-instruction.md` to `.github/copilot-instructions.md` (correct GitHub path).

### Removed

- `nanobot/dashboard/llm_worker.py` — merged into `worker.py`
- Dead code, unused files, and stale references (commit `37e3e8d`)

---

## [0.1.5] - 2026-02-08

### Added - Dashboard Tools System

**Problem**: Agent가 `read_file`/`write_file`로 Dashboard JSON을 직접 조작하면서 발생한 문제들:
- ❌ 잘못된 JSON 구조 생성 (배열 대신 객체)
- ❌ 검증 없음 → malformed data 위험
- ❌ 복잡한 지시사항 (300+ 줄)
- ❌ Agent가 JSON 수동 구성 → 높은 오류율
- ❌ E2E 테스트 실패

**Solution**: Dashboard 전용 도구 6개 생성

#### New Tools

1. **`create_task`** - Task 생성
   - 자동 ID 생성 (`task_xxxxxxxx`)
   - 자동 timestamp 처리
   - 올바른 JSON 구조 보장

2. **`update_task`** - Task 업데이트
   - Progress, status, blocker, context 업데이트
   - Schema validation

3. **`answer_question`** - 질문 답변
   - 질문을 answered로 마킹
   - Answer + timestamp 저장

4. **`create_question`** - 질문 생성
   - Question queue에 추가
   - Priority, type, related_task_id 설정

5. **`save_insight`** - 지식 저장
   - Knowledge base에 insight 저장
   - Category, tags로 분류

6. **`move_to_history`** - 완료 Task 아카이빙
   - Task를 history로 이동
   - Reflection 추가

#### Implementation Details

**New Files**:
- `nanobot/agent/tools/dashboard/__init__.py`
- `nanobot/agent/tools/dashboard/base.py` - BaseDashboardTool (공통 유틸리티)
- `nanobot/agent/tools/dashboard/create_task.py`
- `nanobot/agent/tools/dashboard/update_task.py`
- `nanobot/agent/tools/dashboard/answer_question.py`
- `nanobot/agent/tools/dashboard/create_question.py`
- `nanobot/agent/tools/dashboard/save_insight.py`
- `nanobot/agent/tools/dashboard/move_to_history.py`

**Modified Files**:
- `nanobot/agent/loop.py`
  - `_register_default_tools()`: Dashboard 도구 6개 자동 등록

- `nanobot/agent/tools/filesystem.py`
  - Dashboard JSON 파일들을 READ_ONLY_PATTERNS에 추가
  - `tasks.json`, `questions.json`, `history.json`, `insights.json`, etc.
  - 명확한 에러 메시지: "Use dashboard tools instead of write_file"

- `workspace/DASHBOARD.md`
  - 305 lines → 248 lines (18% 감소)
  - JSON 예제 제거, 도구 기반 인터페이스로 전환
  - 명확한 사용 예시 및 시나리오 추가

#### Benefits

✅ **올바른 JSON 구조** - 도구가 자동 보장
✅ **Pydantic 검증** - 데이터 무결성 보장
✅ **간소화된 지시사항** - 18% 감소
✅ **명확한 인터페이스** - 도구 이름으로 의도 표현
✅ **보안 강화** - Dashboard 파일 read-only 보호
✅ **E2E 테스트 통과** - 올바른 구조 생성

#### Usage Example

**Before** (복잡하고 오류 발생 가능):
```python
dashboard = read_file("dashboard/tasks.json")
data = json.loads(dashboard)
data["tasks"].append({
    "id": "task_" + random_id(),
    "title": "블로그 작성",
    "created_at": datetime.now().isoformat(),
    # ... 20+ 필드 수동 구성 ...
})
write_file("dashboard/tasks.json", json.dumps(data))
```

**After** (간단하고 안전):
```python
create_task(title="블로그 작성", deadline="금요일", priority="medium")
```

---

## [0.1.4] - 2026-02-08

### Version Bump

- `pyproject.toml`: 0.1.3.post4 → 0.1.4

### Changed - Stateless Agent Architecture

**Dashboard System - Major Redesign**

Dashboard 시스템을 완전한 Stateless 아키텍처로 재설계하여 효율성과 맥락 이해를 대폭 개선했습니다.

#### 핵심 변경사항

**1. Session History 제거**
- ❌ 기존: Session history (최대 50개 메시지)가 매번 LLM context에 포함
- ✅ 현재: Session history 완전 제거, Dashboard Summary만으로 맥락 제공
- 📊 효과: ~5,000 tokens 절감 per request

**2. Dashboard Summary 강화** (`nanobot/dashboard/helper.py`)
- ❌ 기존: Active tasks 10개 제한, Questions 5개 제한
- ✅ 현재: 모든 active tasks, 모든 unanswered questions 표시
- 📝 추가 정보: context, blocker, tags, asked_count, last_asked_at, type 등

**3. 맥락 기반 업데이트** (`workspace/DASHBOARD.md` 재작성)
- 하나의 메시지가 여러 질문에 동시 답변 가능
- Agent가 전체 Dashboard 상태를 홀리스틱하게 업데이트
- 암시적 정보 추출 ("어려워요" = blocker)

**4. Silent 모드 구현** (`nanobot/agent/loop.py`)
- Agent가 "SILENT" 응답 → 메시지 전송 안 함
- Dashboard 업데이트 시 불필요한 확인 메시지 방지
- Session에는 여전히 기록됨 (디버깅용)
- `_process_message()` docstring에 None 반환 케이스 명시
- `agent.run()`에서 이미 None 체크 존재 (안전함)

#### 기술적 세부사항

**Modified Files**:
- `nanobot/dashboard/helper.py`
  - `get_dashboard_summary()`: 제한 제거, 상세 정보 추가
  - 모든 task/question 메타데이터 포함

- `nanobot/agent/context.py`
  - `build_messages()`: Session history 제거
  - Stateless 설계로 전환
  - Dashboard Summary가 단일 진실 공급원

- `nanobot/agent/loop.py`
  - Silent 모드 체크 로직 추가
  - `SILENT_RESPONSE_KEYWORD` 상수 정의 (유지보수성 개선)
  - `final_content == "SILENT"` → `return None`
  - Session 저장은 유지 (로깅용)
  - `_process_message()` docstring 개선

- `workspace/DASHBOARD.md`
  - 완전히 재작성 (맥락 기반 프롬프트)
  - 홀리스틱 업데이트 지침
  - 상세한 예시 포함

**Architecture Changes**:
```
Before (v0.1.3):
System Prompt + Session History (50개) + Current Message
→ Token 사용 많음, Context 희석

After (v0.1.4):
System Prompt + Dashboard Summary (전체 상태) + Current Message
→ Token 절감, 명확한 맥락
```

**Benefits**:
1. ✅ **Token 효율성**: ~5,000 tokens 절감 per request
2. ✅ **맥락 이해**: Dashboard 상태가 완전하고 명확함
3. ✅ **Stateless 순수성**: 각 요청이 독립적
4. ✅ **디버깅 용이**: Session 로그는 여전히 유지
5. ✅ **UX 개선**: Silent 모드로 불필요한 응답 제거

**Trade-offs**:
- Race condition 허용 (Worker vs Main Agent, 0.056% 확률)
- Session history 접근 불가 (Dashboard가 대체)

### Removed

- **Cron Tool 제거** (`nanobot/agent/loop.py`)
  - Agent tool 목록에서 제거 (Recurring Task 시스템으로 대체 예정)
  - Dashboard 중심 설계 강화
  - CLI cron 명령어는 여전히 사용 가능

### Added

- **파일 접근 제어 시스템** (`nanobot/agent/tools/filesystem.py`)
  - 지침 파일(DASHBOARD.md, TOOLS.md 등) 쓰기 차단
  - Read-only 파일 패턴 기반 필터링
  - 명확한 에러 메시지로 Agent 자동 복구 유도
  - 보호 대상: DASHBOARD.md, TOOLS.md, AGENTS.md, SOUL.md, USER.md, IDENTITY.md, HEARTBEAT.md, config.json, .env
  - 허용 대상: dashboard/*.json, dashboard/knowledge/*.json, memory/*.md

- **Docker Compose 지원** (`docker-compose.yml`)
  - 간편한 Docker 환경 설정
  - README에 사용 가이드 추가
  - 로컬 config 자동 마운트

- **Configuration Template** (`config.example.json`)
  - 새 사용자를 위한 설정 예제
  - README에서 참조

### Documentation

- `README.md` 대폭 개선:
  - Dashboard System 섹션 추가 (사용법, 예제)
  - Docker Compose 가이드 추가
  - Docker 직접 사용 가이드 개선
  - config.example.json 참조 추가
- `.gitignore` 개인 데이터 보호 강화:
  - Dashboard JSON 파일 (.json)
  - Memory 파일 (.md)
  - 템플릿 파일은 유지 (!workspace/*.md)
  - 설정 파일 보호 (config.json, *.secret)
- `CLAUDE.md`: Dashboard System v0.1.4 섹션 추가
- `CHANGELOG.md`: 상세한 변경 이력 추가

---

## [Unreleased] - Dashboard Sync Manager

**Status**: Phase 3 완료 (LLM 테스트 및 최적화)

### Added
- **Dashboard System**: 완전히 새로운 Dashboard 관리 시스템
  - Task 관리 (active/someday 자동 분류)
  - Question Queue (비동기 소통)
  - Knowledge Base (History, Insights, People)
  - Link System (모든 항목 간 연결)

- **Core Components**:
  - `DashboardManager` - Dashboard 로드/저장
  - `WorkerAgent` - 30분마다 자동 실행
    - 진행률 체크 (7가지 Case)
    - Question 생성 (중복 방지, Cooldown)
    - Completed task → History 이동
    - Active/Someday 재평가
  - `schema.py` - Pydantic 스키마 검증

- **CLI Commands**:
  - `nanobot dashboard show` - Dashboard 전체 보기
  - `nanobot dashboard tasks` - Task 목록
  - `nanobot dashboard questions` - Question Queue
  - `nanobot dashboard answer` - 질문 답변
  - `nanobot dashboard history` - 완료 작업
  - `nanobot dashboard worker` - Worker 수동 실행

- **Testing Infrastructure**:
  - `tests/dashboard/unit/` - Pytest 단위 테스트
  - `tests/dashboard/e2e/` - E2E 통합 테스트
  - `scripts/test_context_dashboard.py` - Context 통합 테스트
  - `scripts/test_agent_dashboard.py` - Agent 통합 테스트
  - `tests/fixtures/example_dashboard.json` - 예제 데이터

- **Documentation**:
  - `FINAL_DESIGN.md` - 최종 확정 설계 문서
  - `TEST_GUIDE.md` - 테스트 가이드
  - `DASHBOARD.md` - Agent 지침 (workspace/)

- **Agent Integration (Phase 2)**:
  - `nanobot/dashboard/helper.py` - Dashboard 요약 헬퍼
  - Context Builder 수정 - DASHBOARD.md 자동 포함
  - Dashboard State 자동 포함 (Active tasks + Questions)
  - Agent가 자동으로 Dashboard 지침 따름

- **LLM Optimization (Phase 3)**:
  - DASHBOARD.md 대폭 간소화 (8.3KB → 4KB)
  - Tool call 유도를 위한 구체적 JSON 예제 추가
  - "YOU MUST CALL THESE TOOLS" 강조 추가
  - Step-by-step 워크플로우 명시
  - `scripts/test_agent_e2e.py` - E2E 테스트 스크립트

### Changed
- **Heartbeat Service**: Worker Agent 자동 실행 추가
- **Onboard Command**: Dashboard 디렉토리 자동 생성

### Removed
- `DESIGN_PROPOSAL.md` - 초기 설계 (deprecated)
- `IMPLEMENTATION_PLAN.md` - 초기 계획 (deprecated)

### Technical Details

**Agent 동작 방식 변경**:
- 기존: 직접 답장
- 신규: 조용히 Dashboard 업데이트 → Question Queue로만 소통

**데이터 구조**:
```
workspace/dashboard/
├── tasks.json           # Task 목록
├── questions.json       # Question Queue
├── notifications.json   # 알림
└── knowledge/
    ├── history.json     # 완료 작업, 프로젝트
    ├── insights.json    # 지식
    └── people.json      # 인간관계
```

**Worker Logic**:
- 시간 기반 vs 실제 진행률 비교
- 7가지 Case 기반 Question 생성
- Cooldown 시스템 (중복 방지)
- 우선순위 자동 조정

### Migration Guide

기존 사용자:
```bash
# 1. 최신 버전으로 업데이트
pip install --upgrade nanobot-ai

# 2. Dashboard 초기화
nanobot onboard

# 3. 기존 데이터 마이그레이션 (수동)
# TODO: 마이그레이션 스크립트 작성 예정
```

### Completed Phases

- ✅ **Phase 1**: 핵심 인프라 (DashboardManager, Worker, CLI, 스키마)
- ✅ **Phase 2**: Agent 통합 (Context Builder 수정, Dashboard State 포함)
- ✅ **Phase 3**: LLM 테스트 및 최적화
  - DASHBOARD.md 간소화
  - Gemini 3 Pro 통합 (`gemini/gemini-3-pro-preview`)
  - LiteLLM 1.81.9 업데이트
  - Tool call 성공 (read_file + write_file)
  - Dashboard 업데이트 검증 완료

### Next Steps (Phase 4)

- [ ] Docker 테스트 및 배포
- [ ] E2E 테스트 개선
- [ ] Link 시스템 검증
- [ ] CI/CD 파이프라인

### Future (Phase 5)

- [ ] Subtask 기능
- [ ] YouTube Summary Tool
- [ ] 웹 UI (선택)
- [ ] 다국어 지원

### LLM 호환성

**테스트 완료:**
- ✅ Gemini 3 Pro (gemini/gemini-3-pro-preview) - **추천!**
- ⚠️ GPT-4o - Tool call이 불안정함

**권장 설정:**
```json
{
  "agents": {
    "defaults": {
      "model": "gemini/gemini-3-pro-preview"
    }
  },
  "providers": {
    "gemini": {
      "apiKey": "YOUR_API_KEY"
    }
  }
}
```

---

**Note**: 이 버전은 아직 릴리스되지 않았습니다. Phase 2 완료 후 정식 릴리스 예정.
