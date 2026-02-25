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
├── agent/loop.py          # Core loop (stateless)
├── agent/context.py       # Prompt builder
├── agent/subagent.py      # Background sub-agent
├── agent/tools/dashboard/ # 12 dashboard tools
├── dashboard/worker.py    # Unified WorkerAgent (Phase 1 + Phase 2)
├── dashboard/storage.py   # StorageBackend ABC
├── dashboard/helper.py    # Dashboard summary generator
├── channels/telegram.py   # Primary channel (numbered answers, /questions, /tasks)
├── notion/                # NotionStorageBackend + cache
├── heartbeat/service.py   # 30-min periodic Worker execution
└── config/, session/, cron/, skills/, cli/, utils/
```

### Dashboard Tools (12)

**Basic (8)**: create_task, update_task, archive_task, answer_question, create_question, update_question, remove_question, save_insight

**Conditional (4, requires cron_service)**: schedule_notification, update_notification, cancel_notification, list_notifications

All tools are wrapped with `@with_dashboard_lock` (asyncio.Lock).

### StorageBackend

ABC -> JsonStorageBackend (default, local JSON) | NotionStorageBackend (Notion API + 5-min TTL cache)

### Worker Agent (dashboard/worker.py)

- **Phase 1** (deterministic, always): archive completed tasks, re-evaluate active/someday
- **Extract** (always): extract answered questions (read-only snapshot for Phase 2)
- **Phase 2** (LLM, when provider/model configured): notifications, question generation, answered question processing (update tasks, save insights), delivered notification follow-up (completion_check), data cleanup
- **Cleanup** (always, after Phase 2): remove stale questions; answered questions only removed if Phase 2 succeeded (preserved for retry otherwise)
- Runs automatically every 30 minutes via Heartbeat
- **Notification delivery**: claim-before-publish pattern (mark delivered → save → publish → GCal delete). See WORKER.md for follow-up instructions

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
| 9 | Worker vs Main Agent | Dashboard file race condition (~0.056% probability, accepted trade-off) | Low |
| 10 | `cli/commands.py` | Claim-before-publish: publish 실패 시 "delivered인데 미발송" 상태 가능. 반대(publish-first)는 cron one-shot 삭제로 notification loss 더 심각하여 claim-first 선택 | Medium |
| 11 | `storage.py:18` | `load_json_file` 파싱 오류를 빈 default로 삼킴 → delivery guard가 notification 못 찾을 수 있음. 빈 리스트 감지로 완화했으나 부분 손상(일부 항목 누락)은 감지 불가 | Low |
| 12 | `cli/commands.py` | GCal 이벤트 삭제 best-effort: 실패 시 warning 로그만, 재시도/정리 없음 → orphan event 누적 가능. cancel_notification과 동일 패턴 | Low |
| 13 | `worker.py` | delivered notification 48h 유지: LLM이 completion_check 중복 생성 가능. WORKER.md 지침으로 완화하나 LLM 준수에 의존 | Low |

**Changes from previous doc**:
- Removed: old #3 "Rule Worker not using StorageBackend" — resolved by Worker unification
- Added: #8 OutboundMessage type field (tech debt from commit `8981642`)
- Added: #10-13 Notification delivery pipeline trade-offs

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
| Deploy pipeline change | `deploy.sh`, `docker-compose.yml`, `.github/workflows/deploy.yml` |
| New Known Limitation | This doc Section 7 |
| Feature release | `CHANGELOG.md` (no history in this doc) |
| Test structure change | This doc Section 4 |
| CLAUDE.md content change | `AGENTS.md` (sync project sections below "---" separator) |

## Document Map

- `README.md` — Installation, usage, channel setup
- `CHANGELOG.md` — Version history
- `SECURITY.md` — Security model
- `TEST_GUIDE.md` — Detailed test guide (manual scenarios, per-model results)
- `workspace/DASHBOARD.md` — Agent dashboard instructions
- `workspace/NOTION_SETUP.md` — Notion DB schema
- `CLAUDE.archive.md` — Previous CLAUDE.md (884-line version, archived for reference)
- `implementation_docs/` — Design documents (4 files)
