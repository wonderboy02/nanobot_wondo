# Dashboard Tests Guide

이 디렉토리는 Dashboard 관련 테스트를 보관합니다.

정책/구조/실행 기준의 단일 소스는 루트 문서인 `tests/README.md`입니다.

## 1) 하위 디렉토리 의미

1. `unit/`
- Worker, Reconciler, Notification/Question 도구 등 결정론 단위 테스트

2. `e2e/`
- Agent/Worker 시나리오 중심 테스트
- 일부 파일은 현재 분류와 성격이 혼재되어 있으며, 재구성 계획은 `tests/TEST_REVIEW_RESTRUCTURE_PLAN.md`를 따릅니다.

## 2) 현재 권장 실행

```bash
# Dashboard 단위 테스트
python -m pytest tests/dashboard/unit -v

# Dashboard E2E 시나리오 (명시적 실행)
python -m pytest tests/dashboard/e2e -v -s
```

## 3) 재구성 메모

다음 파일들은 장기적으로 `unit/integration` 계층으로 이동 권장 대상입니다.

1. `tests/dashboard/e2e/test_notification_simple.py`
2. `tests/dashboard/e2e/test_notification_realistic.py`
3. `tests/dashboard/e2e/test_notification_workflow.py`

상세 근거/계획은 `tests/TEST_REVIEW_RESTRUCTURE_PLAN.md` 참조.
