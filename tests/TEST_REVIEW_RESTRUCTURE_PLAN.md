# Test Suite Review & Restructure Plan

- 작성일: 2026-02-25
- 작성자 관점: 시니어 테스트 엔지니어/QA
- 범위: `tests/` 전체
- 목적: 테스트 의도 정합성 검토 + 재구성 실행 가이드
- 주의: 본 문서는 **문서화 전용**이며 코드 수정은 포함하지 않음

## 1) Executive Summary

현재 테스트 스위트는 양적 커버리지는 좋지만, 아래 4가지가 신뢰도를 떨어뜨립니다.

1. 실행 계층(Unit/Integration/E2E) 경계가 혼재됨
2. `e2e` 마커/실행 정책이 문서와 실제가 불일치함
3. 일부 테스트가 실패를 숨김 (`assert True`, broad `except`)
4. StorageBackend(JSON/Notion) 계약 동등성 검증이 부족함

핵심 방향은 "테스트 수 증가"보다 "검증력과 결정론 강화"입니다.

## 2) 주요 진단 결과

### 2.1 실행 정책 불일치

`CLAUDE.md`에는 `pytest tests/ -v`가 unit only로 설명되어 있으나, 실제 설정(`pyproject.toml`)에는 `e2e` 마커 등록/기본 제외 정책이 없습니다. 따라서 E2E 성격 테스트가 기본 실행에 섞일 수 있습니다.

### 2.2 E2E 디렉토리 내 성격 혼재

`tests/dashboard/e2e/`의 일부 파일은 실제 LLM 없이 도구/워크플로우를 검증하는 성격(사실상 unit/integration)이며 `@pytest.mark.e2e`도 누락되어 있습니다.

### 2.3 실패 탐지력 약한 케이스 존재

`test_error_scenarios.py` 일부 케이스는 broad `except` 후 통과하거나 `assert True` 패턴을 사용합니다. 회귀 발생 시 "통과"로 보일 수 있어 위험합니다.

### 2.4 Backend parity 갭

`tests/notion/test_storage.py` 파일명/의도 대비 실제로는 `JsonStorageBackend` 위주 검증입니다. `StorageBackend ABC` 계약 관점에서 Notion backend parity 검증이 부족합니다.

### 2.5 문서 정합성 저하

`tests/dashboard/README.md`, `tests/dashboard/unit/README.md`에 현재 존재하지 않는 파일/구조가 다수 명시되어 있습니다.

## 3) 결정 항목에 대한 권장안 (본 문서에서 확정)

아래 항목은 "권장"이 아니라 이 계획의 기본 정책으로 확정합니다.

1. `tests/dashboard/e2e/test_notification_*` 3개는 `unit/integration`로 재분류
2. `error_scenarios`는 관찰형(no-crash)에서 실패검출형으로 전환
3. 표준 실행 커맨드는 `python -m pytest`로 통일
4. `pyproject.toml`에 마커 체계 명시 (`unit`, `integration`, `contract`, `e2e_real`, `slow`, `docker`)
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

  docker/

  _support/
```

## 5) 현재 파일 재배치 권장 매핑

1. `tests/dashboard/e2e/test_notification_simple.py`
- 대상: `tests/unit/dashboard/test_notification_tools_basic.py`

2. `tests/dashboard/e2e/test_notification_realistic.py`
- 대상: `tests/integration/worker_agent/test_notification_tools_integration.py`

3. `tests/dashboard/e2e/test_notification_workflow.py`
- 대상: `tests/integration/worker_agent/test_worker_notification_workflow_mock.py`

4. `tests/dashboard/e2e/test_worker_integration.py`
- 대상: `tests/integration/agent_dashboard/test_agent_worker_integration_mock.py`

5. `tests/dashboard/e2e/test_error_scenarios.py`
- 재작성 대상: broad `except` 제거, 실패 조건 명시

## 6) 커버리지 확장 우선순위

1. Agent stateless 계약
- 이전 메시지 히스토리 비의존성
- 동일 dashboard 상태에서 입력 재현성 검증

2. Reaction mode + Numbered answer skip 계약
- auto-processed numbered answers 시 LLM 호출 생략 경로 검증
- 명령(`/questions`, `/tasks`)과 일반 메시지 반응 모드 분리 검증

3. StorageBackend parity
- 동일 데이터 save/load 동작 동등성
- bootstrap register/unregister 롤백 시퀀스 동등성

4. Reconciler 경계조건
- 타이머 교체/중복 전달/mark 실패 재시도/타임존 경계

5. Filesystem 보안 경계
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

### Phase 0 (0.5일)
- 마커/실행 정책 합의
- 문서 기준선 확정

### Phase 1 (1~2일)
- 파일 재분류(Unit/Integration/E2E 분리)
- 이름 정리

### Phase 2 (2~3일)
- 실패 은닉 테스트 재작성 (`error_scenarios`, 일부 contextual)

### Phase 3 (2~4일)
- 계약 테스트 확장 (stateless/reaction/parity)

### Phase 4 (1일)
- CI 게이트 적용 (PR vs nightly 분리, coverage threshold)

## 9) 완료 기준 (Definition of Done)

1. `python -m pytest tests -m "unit or integration or contract"` 안정 통과
2. `e2e_real`는 기본 실행에서 제외되고 nightly에서만 실행
3. `assert True`/broad except 은닉 패턴 제거
4. 문서(`tests/README.md`)와 실제 구조/실행 커맨드 일치
5. 커버리지 기준 충족 (line 90, branch 80)

