# Tests Directory Guide

이 문서는 `tests/` 디렉토리의 구조와 실행 정책을 정의하는 기준 문서입니다.

## 1) 목적

1. 테스트 실행 계층(Unit/Integration/E2E)을 명확히 분리한다.
2. PR 게이트와 Nightly 실행 범위를 분리한다.
3. 문서와 실제 테스트 구조를 항상 일치시킨다.

## 2) 현재 구조 (2026-02-25 기준)

```text
tests/
  channels/
  dashboard/
    e2e/
    unit/
  fixtures/
  google/
  notion/
  test_*.py (루트 단위 테스트들)
```

## 3) 목표 구조 (권장)

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

## 4) 실행 계층 정의

1. `unit`
- 외부 API/실제 LLM 호출 없음
- 100% 결정론

2. `integration`
- 내부 모듈 조합 검증
- LLM은 mock/fake 사용

3. `contract`
- Tool schema, Backend parity, 인터페이스 보장 검증

4. `e2e_real`
- 실제 LLM/API 연동
- 비용/시간이 큰 시나리오
- Nightly 전용

## 5) 마커 정책 (권장 표준)

아래 마커를 표준으로 사용합니다.

1. `unit`
2. `integration`
3. `contract`
4. `e2e_real`
5. `slow`
6. `docker`

## 6) 실행 커맨드 표준

### PR/로컬 기본

```bash
python -m pytest tests -m "unit or integration or contract" -v
```

### E2E (명시적 실행만)

```bash
python -m pytest tests/e2e/real -m e2e_real -v -s
```

### 전체 품질 게이트 (권장)

```bash
python -m pytest tests -m "unit or integration or contract" \
  --cov=nanobot --cov-branch --cov-report=term
```

## 7) 작성 규칙

1. 금지
- `assert True`
- broad `except Exception` 후 통과 처리
- 검증 없는 print 중심 테스트

2. 필수
- Arrange / Act / Assert 구조
- 문자열 검증 + 상태 검증 동시 수행
- 시간 로직은 `sleep`보다 mock/freeze 우선

3. 환경
- `tmp_path` fixture 우선 사용
- `tempfile.mkdtemp()` + 수동 `rmtree()` 패턴 지양

## 8) 커버리지 목표

1. 전역: line 90% 이상
2. 전역: branch 80% 이상
3. 핵심 모듈(AgentLoop/Worker/Reconciler/Filesystem): branch 90% 목표

## 9) 관련 문서

1. 재구성 실행 문서: `tests/TEST_REVIEW_RESTRUCTURE_PLAN.md`
2. Dashboard 하위 안내: `tests/dashboard/README.md`

