# nanobot_wondo — Fork of HKUDS/nanobot

- Dashboard-centric personal AI assistant (Korean workflow)
- Upstream: HKUDS/nanobot | Fork: wonderboy02/nanobot_wondo
- Python 3.11+, version 0.1.4
- Verified: 2026-02-22

## Architecture Snapshot

### Agent Pipeline

- Stateless: `[System Prompt + Dashboard Summary] + [Current Message]`
- `context.py`: identity -> bootstrap files -> memory -> skills -> dashboard summary
- `loop.py`: LLM call -> tool execution -> SILENT response with reaction or text reply
- No session history (Dashboard is Single Source of Truth)

### Core Modules

```
nanobot/
├── agent/loop.py            # Core loop (stateless, _processing_lock, _scheduler)
├── agent/context.py         # Prompt builder
├── agent/subagent.py        # Background sub-agent
├── agent/tools/dashboard/   # 12 dashboard tools
├── dashboard/worker.py      # Unified WorkerAgent (Phase 1 + Phase 2)
├── dashboard/storage.py     # StorageBackend ABC
├── dashboard/reconciler.py  # NotificationReconciler + ReconciliationScheduler
├── dashboard/utils.py       # Shared utilities (parse_datetime)
├── dashboard/helper.py      # Dashboard summary generator
├── channels/telegram.py     # Primary channel (numbered answers, /questions, /tasks)
├── notion/                  # NotionStorageBackend + cache
├── heartbeat/service.py     # 30-min periodic Worker execution
└── config/, session/, cron/, skills/, cli/, utils/
```

### Dashboard Tools (12)

**Basic (8)**: create_task, update_task, archive_task, answer_question, create_question, update_question, remove_question, save_insight

**Notification (4)**: schedule_notification, update_notification, cancel_notification, list_notifications

All tools are wrapped with `@with_dashboard_lock` (asyncio.Lock).

### StorageBackend

ABC -> JsonStorageBackend (default, local JSON) | NotionStorageBackend (Notion API + 5-min TTL cache)

### Worker Agent (dashboard/worker.py)

- **Phase 1** (deterministic, always): bootstrap manually-added items, enforce data consistency, archive completed/cancelled tasks, re-evaluate active/someday
- **Extract** (always): extract answered questions (read-only snapshot for Phase 2)
- **Phase 2** (LLM, when provider/model configured): notifications, question generation, answered question processing (update tasks, save insights), delivered notification follow-up (completion_check), data cleanup
- **Cleanup** (always, after Phase 2): remove stale questions; answered questions only removed if Phase 2 succeeded (preserved for retry otherwise)
- Runs automatically every 30 minutes via Heartbeat
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

## Testing

### Structure

```
tests/
├── dashboard/unit/        # Worker unit (maintenance, LLM cycle, questions, notifications)
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
| `./workspace/` | `/app/workspace/` | AGENTS.md, dashboard/*.json, memory/ etc |

- `NANOBOT_DATA_DIR=/app/data` (locally `~/.nanobot/`)
- `.dockerignore`: excludes workspace/, data/, .git, node_modules/

## Fork Deltas (vs upstream)

| Area | Upstream (HKUDS/nanobot) | This fork (nanobot_wondo) |
|------|--------------------------|---------------------------|
| Worker | Rule + LLM separate | Unified WorkerAgent (Phase 1 + 2) |
| History | history.json separate | In-place archive in tasks.json |
| Agent | Session history included | Stateless (Dashboard Summary only) |
| Storage | JSON only | StorageBackend ABC (JSON + Notion) |
| Dashboard tools | 6 | 12 (+notification tools) |
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
| 7 | `telegram.py` | `_is_quiet_hours()` depends on server timezone (mitigated by Docker TZ=Asia/Seoul) | Low |
| 8 | `bus/events.py` | OutboundMessage has no explicit type field (reaction uses metadata convention) | Low |
| 9 | `storage.py:18` | `load_json_file` 파싱 오류를 빈 default로 삼킴 → 빈 리스트 감지로 완화했으나 부분 손상은 감지 불가 | Low |
| 10 | `worker.py` | delivered notification 48h 유지: LLM이 completion_check 중복 생성 가능. WORKER.md 지침으로 완화하나 LLM 준수에 의존 | Low |
| 11 | `reconciler.py` | update_notification으로 scheduled_at 변경 시 gcal_event_id=None으로 리셋 → 이전 GCal 이벤트 ID 유실로 Reconciler가 삭제 불가 (영구 orphan). 빈도 낮고 GCal 자체 피해 경미하나, 해결하려면 Reconciler에 old_gcal_event_id 추적 로직 필요 | Low |
| 12 | `notifications.json` | delivered/cancelled notification 영구 보존 — archival 정책 없음. tasks.json과 동일 패턴 (#6). Worker Phase 1에 cleanup 추가 검토 | Low |
| 13 | `reconciler.py` | SyncTarget 추상화 없음 — GCal 하드코딩. target 3개 이상 시 SyncTarget ABC 도입 필요 | Low |
| 14 | `reconciler.py` | `reconcile()`에서 GCal create/delete 후 ledger save 실패 시 다음 reconcile에서 중복 GCal 이벤트 생성 가능. `_ensure_gcal()` 멱등성이 gcal_event_id 존재 여부에 의존하므로, save 안 된 상태에서 재실행 시 ID 없음 → 재생성. save 실패 자체가 극히 드물어 실질적 영향 미미 | Low |

**Changes from previous doc**:
- Removed: old #9 "Dashboard file race condition" — resolved by `_processing_lock` (in-process asyncio.Lock; single-worker assumption)
- Removed: old #10 "Claim-before-publish" — resolved by Ledger-Based Delivery (send-first + mark retry)
- Removed: old #12 "GCal 삭제 best-effort in cli" — resolved by Reconciler (멱등 GCal sync)
- Renumbered: old #11→#9, old #13→#10
- Added: #11 GCal orphan on notification update (Low)
- Added: #14 GCal duplicate on reconcile save failure (Low)

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
| Notion schema change | `notion/mapper.py` + `workspace/NOTION_SETUP.md` |
| New sync target | `reconciler.py` ensure/remove, `schema.py` event_id field, this doc Ledger section |
| Deploy pipeline change | `deploy.sh`, `docker-compose.yml`, `.github/workflows/deploy.yml` |
| New Known Limitation | This doc Section 7 |
| Feature release | `CHANGELOG.md` (no history in this doc) |
| Test structure change | This doc Section 4 |
| CLAUDE.md content change | `AGENTS.md` (sync project sections below "---" separator) |

## Document Map

- `README.md` — Installation, usage, channel setup
- `CHANGELOG.md` — Version history
- `SECURITY.md` — Security model
- `tests/README.md` — Test directory structure, execution policy, marker conventions
- `TEST_GUIDE.md` — Detailed test guide (manual scenarios, per-model results)
- `workspace/DASHBOARD.md` — Agent dashboard instructions
- `workspace/NOTION_SETUP.md` — Notion DB schema
- `CLAUDE.archive.md` — Previous CLAUDE.md (884-line version, archived for reference)
- `implementation_docs/` — Design documents (4 files)
