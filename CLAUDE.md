# nanobot_wondo — Fork of HKUDS/nanobot

- Dashboard-centric personal AI assistant (Korean workflow)
- Upstream: HKUDS/nanobot | Fork: wonderboy02/nanobot_wondo
- Python 3.11+, version 0.1.4
- Verified: 2026-02-22

## Architecture Snapshot

### Agent Pipeline

- Stateless: `[System Prompt + Dashboard Summary] + [Current Message]`
- `context.py`: identity -> bootstrap files (nanobot/prompts/ + workspace override) -> memory -> skills -> dashboard summary
- `loop.py`: LLM call -> tool execution -> SILENT response with reaction or text reply
- No session history (Dashboard is Single Source of Truth)

### Core Modules

```
nanobot/
├── prompts/                     # Default instruction files (package-level)
├── agent/loop.py            # Core loop (stateless, _processing_lock, _scheduler)
├── agent/context.py         # Prompt builder
├── agent/subagent.py        # Background sub-agent
├── agent/tools/dashboard/   # 13 dashboard tools
├── dashboard/worker.py      # Unified WorkerAgent (Phase 1 + Phase 2)
├── dashboard/storage.py     # StorageBackend ABC
├── dashboard/reconciler.py  # NotificationReconciler + ReconciliationScheduler
├── dashboard/utils.py       # Shared utilities (parse_datetime, normalize_iso_date, cancel_notification)
├── dashboard/helper.py      # Dashboard summary generator
├── channels/telegram.py     # Primary channel (numbered answers, /questions, /tasks)
├── notion/                  # NotionStorageBackend + cache
├── providers/stats.py       # API key usage stats (file-persisted, weekly report)
├── google/calendar.py       # GCal client (sync I/O, _localize for tz-aware datetime)
├── healthcheck/service.py   # Healthchecks.io ping (liveness signal)
├── heartbeat/service.py     # 2-hour periodic Worker execution
├── utils/time.py            # Timezone-aware now() (default Asia/Seoul)
└── config/, session/, cron/, skills/, cli/, utils/
```

### Instruction File Resolution

- Default: `nanobot/prompts/*.md` (package-level, shipped with pip/Docker)
- Override: `workspace/*.md` (user customization, takes priority)
- Pattern: Same as `nanobot/skills/` (builtin + workspace override)
- Used by: `context.py` (bootstrap), `worker.py` (WORKER.md)
- Exception: `HEARTBEAT.md` reads workspace/ directly (runtime writable file)

### Dashboard Tools (13)

**Basic (9)**: create_task, update_task, archive_task, answer_question, create_question, update_question, remove_question, save_insight, set_recurring

**Notification (4)**: schedule_notification, update_notification, cancel_notification, list_notifications

All tools are wrapped with `@with_dashboard_lock` (asyncio.Lock).

**ISO 포맷 규칙**: `deadline` → `YYYY-MM-DD` only, `scheduled_at` → `YYYY-MM-DDTHH:MM:SS` only. 자연어는 LLM이 ISO로 변환 후 전달. Worker R7이 `deadline_text`에서 파싱 가능한 ISO를 `deadline`으로 backfill. Worker R8이 `deadline`만 있고 `deadline_text` 비어있으면 역방향 backfill.

### LLM Provider Key Rotation (`litellm_provider.py`)

- `ProviderConfig.api_keys`: free tier 키 목록 (순서대로 시도)
- `ProviderConfig.api_key`: 단일 키 또는 유료 키 (api_keys 뒤에 마지막 fallback)
- `effective_keys` property: `api_keys` + `api_key` 합산 (중복 제거)
- Rate limit (429) 시 즉시 다음 키로 전환 (`num_retries=0`)
- 마지막 키: `num_retries=3` (exponential backoff)
- Service unavailable (503): 명시적 로깅 후 키 로테이션 스킵, 다음 fallback 모델로
- 기타 에러: 키 로테이션 스킵, 다음 fallback 모델로
- `api_keys` 비어있으면 기존 동작 (env var 사용)

```json
{"providers": {"gemini": {"apiKeys": ["free-1", "free-2"], "apiKey": "paid-last-resort"}}}
```


### API Key Usage Stats (`providers/stats.py`)

- `ApiKeyStats`: 매 LLM 호출 성공/rate-limit 시 즉시 `workspace/api_stats.json`에 기록
- Atomic write (temp file + rename) → 컨테이너 재시작 시 데이터 유실 0
- `record(provider, tier, event, tokens)`: free/paid 성공 횟수 + 토큰 누적
- `get_weekly_summary()`: 7일 경과 시 포맷된 리포트 반환
- `mark_reported()`: 카운터 리셋 + 새 기간 시작
- Heartbeat `_tick()` 끝에서 주간 리포트 체크 → Telegram 전송
- tier 판별: 단일 키(rotation 없음) → stats 스킵, 마지막 키 → `"paid"`, 그 외 → `"free"`

### StorageBackend

ABC -> JsonStorageBackend (default, local JSON) | NotionStorageBackend (Notion API + 5-min TTL cache)

### Worker Agent (dashboard/worker.py)

- **Phase 1** (deterministic, always): bootstrap manually-added items, field-level snapshot guard (each destructive rule checks only its guard fields — R6: `{completed_at}`, R1/R2a: `{status, progress}`, R5: `{progress}`, reevaluate: `{status}`), Active Sync (user status change → sync progress/completed_at), enforce data consistency (R1-R8 including deadline backfill + deadline_text backfill), archive completed/cancelled tasks, re-evaluate active/someday, process recurring tasks (completed tasks stay completed until next day, then reset)
- **Extract** (always): extract answered questions (read-only snapshot for Phase 2)
- **Phase 2** (LLM, when provider/model configured): notifications, question generation, answered question processing (update tasks, save insights), delivered notification follow-up (completion_check), data cleanup
- **Cleanup** (always, after Phase 2): remove stale questions; answered questions only removed if Phase 2 succeeded (preserved for retry otherwise)
- Runs automatically every 2 hours via Heartbeat
- **Notification delivery**: Ledger-Based Delivery via `ReconciliationScheduler` — tools write to ledger only; Reconciler handles GCal sync, due detection, and delivery via `send_callback`. See WORKER.md for follow-up instructions

### Ledger-Based Delivery (reconciler.py)

**핵심 원칙**: 도구는 ledger(JSON)에만 쓰고, 외부 동기화(GCal, 전송)는 Reconciler가 처리.

```
Tool (write) → Ledger (notifications.json) ← Reconciler (read + sync)
                                              ├── GCal: _ensure_gcal / _remove_gcal
                                              ├── Delivery: send_callback
                                              └── Timer: _arm_timer(next_due_at)
```

**동기화 패턴 (Sync Targets)**:

| 대상 | 방식 | 트리거 | 위치 |
|------|------|--------|------|
| **Notion** | StorageBackend ABC (정교한 R/W) | 매 save() 호출 시 | `storage.py`, `notion/storage.py` |
| **GCal** | Reconciler 멱등 루프 | trigger() 호출 시 | `reconciler.py` |
| **Telegram** | send_callback 단방향 push | due notification 감지 시 | `reconciler.py` |

**Telegram 전송 포맷**: `"🔔 알림이 도착했습니다.\n- {message}"` 래핑 (notification message는 짧은 명사형: "팀 미팅", "운동하기")

**trigger() 호출 시점** (모두 `_processing_lock` 안에서):

1. `loop.py:run()` — 에이전트 시작 시 (overdue 처리)
2. `loop.py:_process_message()` 종료 시 — 매 메시지 처리 후
3. `reconciler.py:_timer_fire()` — 타이머 만료 시 (다음 due)
4. `worker.py:run_cycle()` — Phase 1 + Phase 2 이후

**Processing Lock 흐름**:

```
AgentLoop 생성 → _processing_lock = asyncio.Lock()
                 ├── _scheduler (ReconciliationScheduler) — trigger 시 lock 필요
                 ├── HeartbeatService — worker.run_cycle() 감싸기
                 └── _process_message() — 전체 메시지 처리 중 lock 보유
```

**새 Sync Target 추가 시** (예: Slack, SMS):

1. Notification dict에 `{target}_event_id: None` 필드 추가 (`schema.py`)
2. `NotificationReconciler`에 `_ensure_{target}()` / `_remove_{target}()` 구현
3. `reconcile()` 루프에 hook 추가 (pending → ensure, cancelled/delivered → remove)
4. 기존 도구 코드 변경 불필요 (ledger-only 원칙)

> **TODO**: Sync target이 3개 이상이면 `SyncTarget` ABC 도입 검토 (현재는 GCal 1개로 인라인 충분)

**주요 타입** (`reconciler.py`):

| 타입 | 설명 |
|------|------|
| `ReconcileResult` | `due: list[dict]`, `next_due_at: datetime | None`, `changed: bool` |
| `NotificationReconciler` | Sync 클래스. `reconcile()`, `mark_delivered(id)` |
| `ReconciliationScheduler` | Async 래퍼. `trigger()`, `stop()` |

## Non-Negotiable Rules

### Dashboard Data

- `dashboard/*.json`, `dashboard/knowledge/*.json` -> use dedicated tools only (write_file/edit_file forbidden)
- All tools have asyncio.Lock applied (`with_dashboard_lock` decorator)

### Protected Files (write_file/edit_file read-only)

- `AGENTS.md, SOUL.md, USER.md, TOOLS.md, DASHBOARD.md, HEARTBEAT.md, IDENTITY.md`
- `config.json, .env`
- `dashboard/*.json, dashboard/knowledge/*.json`

### Reaction Mode (replaces SILENT mode)

- Normal messages (dashboard updates): response = `SILENT` -> sends reaction emoji to original message
- Fully auto-processed numbered answers: LLM call skipped + reaction
- Commands (`/questions`, `/tasks`): text output
- Insufficient info: `create_question()` to add to question queue
- Implementation: `loop.py` `_reaction_message()`, each channel's reaction guard

### Numbered Answer System (Telegram)

- `/questions` -> numbered list, user replies in "1. answer\n2. answer" format
- If all numbered answers auto-processed: LLM call skipped (token savings) + reaction
- Cache: TTL 1 hour, max 100 entries

### Code Style

- `ruff format/check`, line-length=100, Python 3.11+
- ruff lint: critical rules only (`select = ["E9", "F63", "F7", "F82"]`)
- TYPE_CHECKING guard: type-hint-only imports inside `if TYPE_CHECKING:` block
- Logging: `from loguru import logger` 사용 (stdlib `logging` 사용 금지). 포맷: `logger.info("message {}", var)` (%-style 금지)

## Testing

### Structure

```
tests/
├── dashboard/unit/        # Worker unit (maintenance, LLM cycle, questions, notifications, recurring, snapshot)
├── dashboard/e2e/         # E2E scenarios (@pytest.mark.e2e, requires LLM API)
├── notion/                # Notion client, mapper, cache, storage
├── channels/              # Telegram notification manager
├── fixtures/              # example_dashboard.json
├── test_dashboard_tools.py          # Individual tool tests
├── test_dashboard_tools_integration.py  # AgentLoop integration (no LLM)
├── test_filesystem_access_control.py    # File protection rules
├── test_numbered_answers.py             # Numbered answer parsing
├── test_tool_validation.py              # Tool schema validation
├── test_cross_platform_paths.py         # Windows/Linux paths
├── test_litellm_fallback.py             # LLM key rotation + fallback
├── test_api_key_stats.py               # API key usage stats (file persistence, weekly report)
├── test_time.py                         # Timezone utility (now(), app_tz)
├── test_healthcheck.py                  # Healthcheck ping service
├── test_instruction_resolution.py       # Instruction file resolution (prompts/ + workspace/)
└── test_docker.sh                       # Docker image build/run test
```

### Commands

```bash
pytest tests/ -v                           # All (unit only, E2E excluded)
pytest tests/ -v -m "not e2e"              # Unit only explicit
pytest tests/dashboard/unit/ -v            # Worker unit tests
pytest tests/dashboard/e2e/ -v -s -m e2e   # E2E (API key required)
bash tests/dashboard/run_tests.sh          # Dashboard-specific runner
bash tests/dashboard/run_tests.sh --all    # Unit + E2E
bash tests/test_docker.sh                  # Docker integration test
```

### Config (`pyproject.toml`)

- `asyncio_mode = "auto"` (all async tests auto-handled)
- `testpaths = ["tests"]`
- dev dependencies: `pytest>=7.0.0`, `pytest-asyncio>=0.21.0`, `ruff>=0.1.0`

### Notes

- E2E tests make real LLM API calls (12-17 min, API key required)
- No `conftest.py` — fixtures defined directly in each test file (duplication exists)
- `pytest-cov` not included — install separately for coverage

## Docker Deployment

**Pipeline**: `push to main` -> GH Actions (`deploy.yml`) -> SSH -> `deploy.sh`

**Files**:
- `Dockerfile`: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, includes WhatsApp bridge build
- `docker-compose.yml`: `nanobot gateway`, `TZ=Asia/Seoul`
- `deploy.sh`: first run bootstraps config, subsequent runs `git pull -> docker compose up --build --force-recreate -d`
- `.github/workflows/deploy.yml`: `appleboy/ssh-action` SSH to server, runs `deploy.sh`

**Volumes**:

| Local | Container | Content |
|-------|-----------|---------|
| `./data/` | `/app/data/` | config.json, sessions/ |
| `./workspace/` | `/app/workspace/` | Runtime data: dashboard/*.json, memory/, HEARTBEAT.md |

- `NANOBOT_DATA_DIR=/app/data` (locally `~/.nanobot/`)
- `.dockerignore`: excludes workspace/, data/, .git, node_modules/

## Fork Deltas (vs upstream)

| Area | Upstream (HKUDS/nanobot) | This fork (nanobot_wondo) |
|------|--------------------------|---------------------------|
| Worker | Rule + LLM separate | Unified WorkerAgent (Phase 1 + 2) |
| History | history.json separate | In-place archive in tasks.json |
| Agent | Session history included | Stateless (Dashboard Summary only) |
| Storage | JSON only | StorageBackend ABC (JSON + Notion) |
| Dashboard tools | 6 | 13 (+notification tools) |
| Telegram | Basic | Numbered answer parsing, LLM skip, reaction |
| Deploy | Manual Docker | CI/CD (GH Actions + deploy.sh) |
| Response mode | Plain text | Reaction (replaces SILENT) |

## Known Limitations

| # | Location | Description | Severity |
|---|----------|-------------|----------|
| 1 | `notion/client.py` | Sync I/O blocking (intentional, single-user) | Low |
| 2 | `dashboard/base.py:41` | Class-level `_configured_backend` shared state | Low |
| 3 | `telegram.py:90` | TelegramNotificationManager created but send path not wired | Medium |
| 4 | `storage.py` | insights have no Pydantic validation | Low |
| 5 | `config/schema.py` | NotificationPolicyConfig has no range validation | Low |
| 6 | `archive_task.py` | Archived tasks accumulate in tasks.json indefinitely | Medium |
| 7 | — | ~~server timezone~~ resolved: `nanobot/utils/time.py` `now()` defaults to Asia/Seoul | — |
| 8 | `bus/events.py` | OutboundMessage has no explicit type field (reaction uses metadata convention) | Low |
| 9 | `storage.py:18` | `load_json_file` 파싱 오류를 빈 default로 삼킴 → 빈 리스트 감지로 완화했으나 부분 손상은 감지 불가 | Low |
| 10 | `worker.py` | delivered notification 48h 유지: LLM이 completion_check 중복 생성 가능. WORKER.md 지침으로 완화하나 LLM 준수에 의존 | Low |
| 11 | `reconciler.py` | update_notification으로 scheduled_at 변경 시 gcal_event_id=None으로 리셋 → 이전 GCal 이벤트 ID 유실로 Reconciler가 삭제 불가 (영구 orphan). 빈도 낮고 GCal 자체 피해 경미하나, 해결하려면 Reconciler에 old_gcal_event_id 추적 로직 필요 | Low |
| 12 | `notifications.json` | delivered/cancelled notification 영구 보존 — archival 정책 없음. tasks.json과 동일 패턴 (#6). Worker Phase 1에 cleanup 추가 검토 | Low |
| 13 | `reconciler.py` | SyncTarget 추상화 없음 — GCal 하드코딩. target 3개 이상 시 SyncTarget ABC 도입 필요 | Low |
| 14 | `reconciler.py` | `reconcile()`에서 GCal create/delete 후 ledger save 실패 시 다음 reconcile에서 중복 GCal 이벤트 생성 가능. `_ensure_gcal()` 멱등성이 gcal_event_id 존재 여부에 의존하므로, save 안 된 상태에서 재실행 시 ID 없음 → 재생성. save 실패 자체가 극히 드물어 실질적 영향 미미 | Low |
| 15 | `worker.py` | Field-level snapshot guard는 one-cycle protection만 제공. 각 규칙은 관련 guard 필드가 변경됐을 때만 스킵 (title만 변경 시 모든 규칙 정상 동작). 다음 cycle에서 추가 변경 없으면 정상 규칙 적용. Phase 2 tool이 task 수정하면 다음 cycle에서 해당 필드가 user-changed로 감지됨 (의도한 동작) | Low |
| 16 | `worker.py` | f-string 로깅이 12개 잔존 (bootstrap, archive, recurring, cleanup/LLM 영역). 새 코드는 loguru `{}` 포맷 사용. 별도 커밋으로 일괄 전환 필요 | Low |

**Changes from previous doc**:
- Removed: old #9 "Dashboard file race condition" — resolved by `_processing_lock` (in-process asyncio.Lock; single-worker assumption)
- Removed: old #10 "Claim-before-publish" — resolved by Ledger-Based Delivery (send-first + mark retry)
- Removed: old #12 "GCal 삭제 best-effort in cli" — resolved by Reconciler (멱등 GCal sync)
- Renumbered: old #11→#9, old #13→#10
- Added: #11 GCal orphan on notification update (Low)
- Added: #14 GCal duplicate on reconcile save failure (Low)
- Added: #15 Field-level snapshot guard one-cycle protection (Low)
- Removed: #15 workspace .md/data 혼재 — resolved by `nanobot/prompts/` separation
- Resolved: #7 server timezone — resolved by `nanobot/utils/time.py` centralized `now()` (default Asia/Seoul)
- Added: #16 f-string logging残存 in worker.py (Low)

## Dev Runbook

```bash
# Lint
ruff format . && ruff check .

# Test
pytest tests/ -v                           # All unit
pytest tests/dashboard/unit/ -v            # Worker unit
pytest tests/dashboard/e2e/ -v -s -m e2e   # E2E (API key required)
bash tests/test_docker.sh                  # Docker test

# Operations
nanobot dashboard worker                   # Manual Worker run
nanobot notion validate                    # Notion connection check
bash core_agent_lines.sh                   # Core line count
docker compose up --build -d               # Local Docker run
docker compose logs -f nanobot             # Logs
```

## Update Checklist

| Change | Also update |
|--------|-------------|
| Dashboard tool add/remove | `__init__.py` exports, `loop.py` registration, this doc Section 2 |
| Protected file list change | `filesystem.py` READ_ONLY_PATTERNS |
| Worker logic change | `worker.py` docstring, this doc Section 2 |
| Storage interface change | JsonStorageBackend + NotionStorageBackend both |
| Instruction 파일 내용 변경 | `nanobot/prompts/*.md` |
| Notion schema change | `notion/mapper.py` + `nanobot/prompts/NOTION_SETUP.md` |
| New sync target | `reconciler.py` ensure/remove, `schema.py` event_id field, this doc Ledger section |
| Deploy pipeline change | `deploy.sh`, `docker-compose.yml`, `.github/workflows/deploy.yml` |
| New Known Limitation | This doc Section 7 |
| Feature release | `CHANGELOG.md` (no history in this doc) |
| Test structure change | This doc Section 4 |
| CLAUDE.md content change | `nanobot/prompts/AGENTS.md` (sync project sections below "---" separator) |

## Document Map

- `README.md` — Installation, usage, channel setup
- `CHANGELOG.md` — Version history
- `SECURITY.md` — Security model
- `tests/README.md` — Test directory structure, execution policy, marker conventions
- `TEST_GUIDE.md` — Detailed test guide (manual scenarios, per-model results)
- `nanobot/prompts/DASHBOARD.md` — Agent dashboard instructions (package default)
- `nanobot/prompts/NOTION_SETUP.md` — Notion DB schema (package default)
- `CLAUDE.archive.md` — Previous CLAUDE.md (884-line version, archived for reference)
- `implementation_docs/` — Design documents
