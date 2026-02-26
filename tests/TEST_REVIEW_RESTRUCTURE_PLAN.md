# Test Suite Review & Restructure Plan

- 작성일: 2026-02-25 (rev.2: 2026-02-26)
- 작성자 관점: 시니어 테스트 엔지니어/QA
- 범위: `tests/` 전체
- 목적: 테스트 의도 정합성 검토 + 재구성 실행 가이드
- 주의: 본 문서는 **문서화 전용**이며 코드 수정은 포함하지 않음

## 1) Executive Summary

현재 테스트 스위트는 양적 커버리지는 좋지만(270개 수집, 242 unit/28 e2e), 아래 5가지가 신뢰도를 떨어뜨립니다.

1. ~~실행 정책 불일치~~ → **Phase 0에서 해결** (`addopts = "-m 'not e2e'"`)
2. `e2e/` 디렉토리 내 성격 혼재 (notification 3파일은 실제 unit/integration)
3. 일부 테스트가 실패를 숨김 (`assert True`, broad `except`)
4. StorageBackend(JSON/Notion) 계약 동등성 검증 부족
5. E2E 파일 2개에서 `asyncio.run()` 안티패턴 사용

핵심 방향은 "테스트 수 증가"보다 "검증력과 결정론 강화"입니다.

## 2) 주요 진단 결과

### 2.1 실행 정책 불일치 — ✅ 해결됨 (Phase 0)

`pyproject.toml`에 아래 설정 추가로 해결:

```toml
markers = [
    "e2e: End-to-end tests requiring real LLM API (deselected by default)",
]
addopts = "-m 'not e2e'"
```

- `pytest tests/ -v` → e2e 28개 자동 제외, unit 242개만 수집
- `pytest tests/ -v -m e2e` → e2e 28개만 수집
- CLAUDE.md의 `pytest tests/ -v # All (unit only, E2E excluded)` 설명이 사실이 됨

### 2.2 E2E 디렉토리 내 성격 혼재

`tests/dashboard/e2e/`의 notification 3파일은 실제 LLM 없이 도구/워크플로우를 검증하는 성격(사실상 unit/integration)이며 `@pytest.mark.e2e`도 없습니다.

| 파일 | 테스트 수 | LLM 사용 | `@pytest.mark.e2e` | 실제 성격 | 권장 위치 |
|------|-----------|----------|---------------------|-----------|-----------|
| `test_notification_simple.py` | 6 | 없음 | 없음 | Unit | `unit/` |
| `test_notification_realistic.py` | 8 | 없음 | 없음 | Integration | `integration/` |
| `test_notification_workflow.py` | 5 | 없음 | 없음 | Integration | `integration/` |

현재 `addopts`에 의해 기본 실행에 포함되므로 기능적 문제는 없으나, 디렉토리명(`e2e/`)과 실제 성격이 불일치합니다.

### 2.3 실패 탐지력 약한 케이스 존재

`test_error_scenarios.py`의 아래 패턴은 회귀 발생 시 "통과"로 보일 위험이 있습니다:

| 라인 | 패턴 | 위험도 |
|------|------|--------|
| L97, L148, L196, L234, L310, L347 | broad `except Exception` 후 통과 | High |
| L110 | `assert True, "Agent handled ambiguous message"` | High |
| L194 | `assert True, "Agent handled large context"` | High |
| L232 | `assert True, "Agent handled incomplete task data"` | High |

### 2.4 Backend parity 갭

`tests/notion/test_storage.py`는 파일명/의도 대비 실제로는 `JsonStorageBackend` 위주 검증입니다. `StorageBackend ABC` 계약 관점에서 Notion backend parity 검증이 부족합니다.

### 2.5 문서 정합성 — ✅ 해결됨 (Phase 0)

- README.md: 2/25 갱신 완료
- 레거시 문서 3개 삭제 완료 (Phase 0):
  - `tests/dashboard/SUMMARY.md` — 2/8 기준, 47개 테스트 기술 (현재 270개)
  - `tests/dashboard/TEST_PLAN.md` — 2/8 기준, 본 문서로 대체됨
  - `tests/dashboard/TEST_RESULTS.md` — 2/8 기준, 10개 결과만 기록

### 2.6 `asyncio.run()` 안티패턴 (신규)

`pytest-asyncio`의 `asyncio_mode = "auto"` 설정 하에서 `asyncio.run()`을 사용하면 이벤트 루프 충돌 위험이 있습니다.

| 파일 | `asyncio.run()` 호출 수 | `@pytest.mark.e2e` | 비고 |
|------|------------------------|---------------------|------|
| `test_contextual_updates.py` | 6 | 있음 | `async def` 내에서 `asyncio.run()` 호출 |
| `test_journey.py` | 15 | 있음 | 동일 패턴 |
| `test_dashboard_tools_integration.py` | 1 | 없음 (루트) | 동일 패턴 |

이 파일들은 `async def` 테스트 함수 내에서 `asyncio.run()`을 호출하는데, 이미 실행 중인 이벤트 루프 안에서 새 루프를 만들려는 시도입니다. 현재 동작하는 이유는 pytest-asyncio가 각 테스트에 새 루프를 제공하기 때문이지만, 향후 버전에서 깨질 수 있습니다.

**수정 방향** (Phase 2): `asyncio.run(coro)` → `await coro`로 변경.

## 3) 결정 항목 (본 문서에서 확정)

1. `tests/dashboard/e2e/test_notification_*` 3개는 `unit/integration`으로 재분류
2. `error_scenarios`는 관찰형(no-crash)에서 실패검출형으로 전환
3. 표준 실행 커맨드는 `python -m pytest`로 통일
4. 마커 체계:
   - **현재 등록** (`pyproject.toml`): `e2e` — 유일하게 실제 사용 중인 마커
   - **목표** (Phase 1에서 테스트에 부착 시 등록): `unit`, `integration`, `contract`, `e2e` (→ `e2e_real` 개명 검토), `slow`, `docker`
5. PR 게이트는 `unit + integration + contract`만, 실제 E2E는 nightly
6. 커버리지 기준은 초기값으로 `line >= 90%`, `branch >= 80%`
7. `StorageBackend` parity 테스트를 이번 재구성 범위에 포함

## 4) 권장 최종 구조

```text
tests/
  README.md
  TEST_REVIEW_RESTRUCTURE_PLAN.md

  unit/
    agent/
    dashboard/
    channels/
    storage/
    tools/

  integration/
    agent_dashboard/
    worker_agent/
    storage_backend/

  e2e/
    real/
    smoke/

  google/
  notion/
  channels/

  docker/

  _support/
```

> `google/`, `notion/`, `channels/`는 현재 이미 존재하는 디렉토리로, 목표 구조에서 유지합니다. Phase 1에서 내부 파일을 `unit/`/`integration/` 계층으로 재분류할지 결정합니다.

## 5) 현재 파일 → 재배치 권장 매핑 (전체 인벤토리)

### Dashboard E2E → 재분류

| # | 현재 경로 | 권장 대상 | 사유 |
|---|-----------|-----------|------|
| 1 | `dashboard/e2e/test_notification_simple.py` | `unit/dashboard/test_notification_tools_basic.py` | LLM 없음, e2e 마커 없음 |
| 2 | `dashboard/e2e/test_notification_realistic.py` | `integration/worker_agent/test_notification_tools_integration.py` | LLM 없음, e2e 마커 없음 |
| 3 | `dashboard/e2e/test_notification_workflow.py` | `integration/worker_agent/test_worker_notification_workflow_mock.py` | LLM 없음, e2e 마커 없음 |
| 4 | `dashboard/e2e/test_worker_integration.py` | `integration/agent_dashboard/test_agent_worker_integration_mock.py` | 혼합 성격 (일부 e2e) |
| 5 | `dashboard/e2e/test_error_scenarios.py` | 재작성 대상 | broad `except` 제거, 실패 조건 명시 |

### Dashboard E2E → 유지 (실제 E2E)

| # | 현재 경로 | 비고 |
|---|-----------|------|
| 6 | `dashboard/e2e/test_user_scenarios.py` | 10개 시나리오, `@pytest.mark.e2e` 있음 |
| 7 | `dashboard/e2e/test_contextual_updates.py` | 5개 시나리오, `asyncio.run()` 수정 필요 |
| 8 | `dashboard/e2e/test_journey.py` | 3개 여정, `asyncio.run()` 수정 필요 |

### Dashboard Unit → 유지

| # | 현재 경로 | 비고 |
|---|-----------|------|
| 9 | `dashboard/unit/test_worker_maintenance.py` | Worker Phase 1 |
| 10 | `dashboard/unit/test_worker_bootstrap.py` | Worker bootstrap (수집 오류 3건 존재) |
| 11 | `dashboard/unit/test_worker_llm_cycle.py` | Worker Phase 2 |
| 12 | `dashboard/unit/test_question_management.py` | Question 도구 |
| 13 | `dashboard/unit/test_notification_tools.py` | Notification 도구 |
| 14 | `dashboard/unit/test_utils.py` | 유틸리티 |
| 15 | `dashboard/unit/test_reconciler.py` | Reconciler 단위 테스트 |

### 루트 테스트 파일

| # | 현재 경로 | 권장 대상 | 비고 |
|---|-----------|-----------|------|
| 16 | `test_dashboard_tools.py` | `unit/tools/` | 개별 도구 테스트 |
| 17 | `test_dashboard_tools_integration.py` | `integration/agent_dashboard/` | AgentLoop 통합, `asyncio.run()` 수정 필요 |
| 18 | `test_filesystem_access_control.py` | `unit/agent/` | 파일 보호 규칙 |
| 19 | `test_numbered_answers.py` | `unit/channels/` | Numbered answer 파싱 |
| 20 | `test_tool_validation.py` | `unit/tools/` 또는 `contract/` | Tool schema 검증 |
| 21 | `test_cross_platform_paths.py` | `unit/agent/` | Windows/Linux 경로 |

### 비-Dashboard 디렉토리

| # | 현재 경로 | 비고 |
|---|-----------|------|
| 22 | `notion/test_client.py` | Notion API 클라이언트 |
| 23 | `notion/test_mapper.py` | Notion 데이터 매퍼 |
| 24 | `notion/test_memory_cache.py` | Notion 캐시 |
| 25 | `notion/test_storage.py` | StorageBackend (실제로는 JSON 위주) |
| 26 | `channels/test_telegram_notifications.py` | Telegram notification manager |
| 27 | `google/test_calendar.py` | GCal 클라이언트 |

## 6) 커버리지 확장 우선순위

### 1. Agent stateless 계약

- 이전 메시지 히스토리 비의존성
- 동일 dashboard 상태에서 입력 재현성 검증

### 2. Reaction mode + Numbered answer skip 계약

- auto-processed numbered answers 시 LLM 호출 생략 경로 검증
- 명령(`/questions`, `/tasks`)과 일반 메시지 반응 모드 분리 검증

### 3. StorageBackend parity

- 동일 데이터 save/load 동작 동등성
- bootstrap register/unregister 롤백 시퀀스 동등성

### 4. Reconciler 경계조건

**기존 커버리지** (`dashboard/unit/test_reconciler.py` 존재):
- 기본 reconcile 루프, mark_delivered, 타이머 동작 등 단위 테스트 완료

**남은 갭**:
- 타이머 교체/중복 전달/mark 실패 재시도
- 타임존 경계 (서울 자정 전후)
- GCal orphan 시나리오 (update 후 reconcile 전 구간)

### 5. Filesystem 보안 경계

- path traversal, `~` 확장, 절대경로 우회, read-only 패턴 우회

## 7) 테스트 작성 규칙 (강제)

1. 금지
   - `assert True`
   - broad `except Exception` 후 통과
   - 검증 없는 print 중심 테스트

2. 필수
   - Arrange/Act/Assert 구조
   - 결과 문자열 + 파일 상태(혹은 객체 상태) 동시 검증
   - 타임 기반 로직은 mock/freeze 사용

3. 환경
   - `tmp_path` fixture 사용
   - 임시 디렉토리 수동 정리(`mkdtemp` + `rmtree`) 지양

## 8) 단계별 실행 계획

### Phase 0 (완료) ✅

- [x] `pyproject.toml`에 `e2e` 마커 등록 + `addopts` 기본 제외
- [x] 레거시 문서 3개 삭제 (`SUMMARY.md`, `TEST_PLAN.md`, `TEST_RESULTS.md`)
- [x] 본 문서 재작성 (현재 상태 기준)
- [x] `tests/README.md` 현재/목표 분리, 커맨드 수정
- [x] `tests/dashboard/README.md` e2e 실행 커맨드 보완
- [x] `tests/dashboard/e2e/README.md` notification 파일 추가

### Phase 1 (1~2일)

- 파일 재분류 (Unit/Integration/E2E 분리)
- 이름 정리
- `run_tests.py`/`run_tests.sh` 정리

### Phase 2 (2~3일)

- `test_error_scenarios.py` 재작성 (broad `except` 제거, 실패 조건 명시)
- `asyncio.run()` 안티패턴 수정 (`await`로 변환)

### Phase 3 (2~4일)

- 계약 테스트 확장 (stateless/reaction/parity)

### Phase 4 (1일)

- CI 게이트 적용 (PR vs nightly 분리, coverage threshold)

## 9) 완료 기준 (Definition of Done)

1. `pytest tests/ -v` 안정 통과 (e2e 자동 제외, `addopts` 기반)
2. `pytest tests/ -v -m e2e` E2E만 수집 (nightly 실행)
3. `assert True`/broad except 은닉 패턴 제거 (Phase 2)
4. 문서(`tests/README.md`)와 실제 구조/실행 커맨드 일치
5. 커버리지 기준 충족 (line 90, branch 80) — `pytest-cov` 별도 설치 필요
