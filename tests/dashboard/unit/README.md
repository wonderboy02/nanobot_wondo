# Dashboard Unit Tests

이 디렉토리는 Dashboard 영역의 결정론 단위 테스트를 포함합니다.

## 1) 포함 범위

1. Worker deterministic phase (`maintenance`, `bootstrap`, `llm_cycle`의 mock 기반 경로)
2. Reconciler / Scheduler 단위 동작
3. Notification / Question 도구 단위 검증
4. 공통 유틸리티 (`utils`) 검증

## 2) 실행

```bash
python -m pytest tests/dashboard/unit -v
```

특정 파일 실행 예시:

```bash
python -m pytest tests/dashboard/unit/test_worker_maintenance.py -v
```

## 3) 품질 규칙

1. 외부 API/실제 LLM 호출 금지
2. 실패 은닉 금지 (`assert True`, broad except 후 pass)
3. 상태 검증 우선 (문자열 응답 검증만으로 통과 금지)

## 4) 문서 참조

1. 전체 테스트 구조/정책: `tests/README.md`
2. 재구성 실행 계획: `tests/TEST_REVIEW_RESTRUCTURE_PLAN.md`
