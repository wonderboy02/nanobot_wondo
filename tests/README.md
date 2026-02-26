# Tests Directory Guide

이 문서는 `tests/` 디렉토리의 구조와 실행 정책을 정의하는 기준 문서입니다.

## 1) 목적

1. 테스트 실행 계층(Unit/Integration/E2E)을 명확히 분리한다.
2. PR 게이트와 Nightly 실행 범위를 분리한다.
3. 문서와 실제 테스트 구조를 항상 일치시킨다.

## 2) 현재 구조 (2026-02-26 기준)

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

  google/
  notion/
  channels/

  docker/
  _support/
```

> `google/`, `notion/`, `channels/`는 현재 이미 존재하는 디렉토리. Phase 1에서 `unit/`/`integration/` 계층으로 재분류할지 결정.

## 4) 실행 계층 정의

1. `unit`
- 외부 API/실제 LLM 호출 없음
- 100% 결정론

2. `integration`
- 내부 모듈 조합 검증
- LLM은 mock/fake 사용

3. `contract`
- Tool schema, Backend parity, 인터페이스 보장 검증

4. `e2e`
- 실제 LLM/API 연동
- 비용/시간이 큰 시나리오
- Nightly 전용

## 5) 마커 정책

### 현재 등록 (`pyproject.toml`)

- `e2e` — 유일하게 실제 사용 중. `addopts = "-m 'not e2e'"`로 기본 제외.

### 목표 (Phase 1에서 테스트에 부착 시 등록)

1. `unit`
2. `integration`
3. `contract`
4. `e2e`
5. `slow`
6. `docker`

## 6) 실행 커맨드 표준

### PR/로컬 기본 (현재)

```bash
# e2e 자동 제외 (addopts 기반)
pytest tests/ -v
```

### E2E (명시적 실행만)

```bash
# addopts 기본 제외를 -m e2e로 오버라이드
pytest tests/dashboard/e2e/ -v -s -m e2e
```

### 전체 품질 게이트 (목표, Phase 1 이후)

```bash
pytest tests/ -m "unit or integration or contract" \
  --cov=nanobot --cov-branch --cov-report=term
```

> `pytest-cov`는 dev 의존성에 미포함. 커버리지 측정 시 별도 설치 필요: `pip install pytest-cov`

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

> `pytest-cov`는 dev 의존성에 미포함. 별도 설치: `pip install pytest-cov`

## 9) 관련 문서

1. 재구성 실행 문서: `tests/TEST_REVIEW_RESTRUCTURE_PLAN.md`
2. Dashboard 하위 안내: `tests/dashboard/README.md`
