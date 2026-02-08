# Dashboard Test Suite

Dashboard Sync Manager의 종합 테스트 스위트입니다.

## 📋 테스트 구조

### Unit Tests (`unit/`)
DashboardManager, Worker, Schema의 개별 기능을 테스트합니다.

- **test_manager.py** - DashboardManager CRUD
- **test_worker_cases.py** - Worker의 7가지 진행률 체크 Case
- **test_schema.py** - Pydantic 스키마 검증
- **test_links.py** - Link 시스템 (Task ↔ Project/Person/Insight)
- **test_edge_cases.py** - Edge cases (손상된 데이터, 중복 ID 등)

### E2E Tests (`e2e/`)
실제 Agent를 실행하여 전체 플로우를 검증합니다.

- **test_user_scenarios.py** - 10가지 사용자 시나리오
  1. 새 Task 추가
  2. Task 진행률 업데이트
  3. Task 완료 처리
  4. Question 답변
  5. Task 취소/삭제
  6. Deadline 변경
  7. Blocked task 처리
  8. 여러 Task 한 번에 추가
  9. 자연어 날짜 처리
  10. Link 추가/제거

- **test_error_scenarios.py** - 에러 케이스
  1. LLM이 잘못된 JSON 생성
  2. Tool call 실패 복구
  3. 파일 쓰기 실패
  4. 애매한 사용자 메시지
  5. Context 너무 큼

- **test_worker_integration.py** - Worker + Agent 통합
  - Agent 추가 → Worker 질문 생성 → Agent 답변

- **test_journey.py** - 1주일 사용자 여정 시뮬레이션

### Performance Tests (`performance/`)
대량 데이터 및 성능 테스트입니다.

- **test_load.py** - 100개 tasks, 50개 questions

## 🚀 실행 방법

### 모든 테스트 실행
```bash
# Pytest로 전체 실행
pytest tests/dashboard/ -v

# 카테고리별 실행
pytest tests/dashboard/unit/ -v
pytest tests/dashboard/e2e/ -v
pytest tests/dashboard/performance/ -v
```

### 특정 테스트만 실행
```bash
# Worker Cases만
pytest tests/dashboard/unit/test_worker_cases.py -v

# E2E 시나리오만
pytest tests/dashboard/e2e/test_user_scenarios.py -v

# 특정 테스트 함수
pytest tests/dashboard/e2e/test_user_scenarios.py::test_scenario_01_add_task -v
```

### Coverage와 함께 실행
```bash
pytest tests/dashboard/ --cov=nanobot.dashboard --cov-report=html --cov-report=term
```

## 📊 테스트 결과

테스트 실행 결과는 `reports/` 디렉토리에 저장됩니다.
- `TEST_RESULTS.md` - 최신 실행 결과 요약
- `coverage.html` - Coverage 리포트

## 🎯 테스트 목표

- **Unit Tests**: 90%+ coverage
- **E2E Tests**: 주요 시나리오 100% 커버
- **Performance**: 100 tasks 처리 < 5초

## 📚 문서

- `TEST_PLAN.md` - 상세한 테스트 계획
- 각 디렉토리의 `README.md` - 카테고리별 설명

## ⚙️ 요구사항

- Python 3.11+
- pytest
- pytest-asyncio
- pytest-cov (coverage용)

## 🐛 문제 해결

### E2E 테스트 실패
E2E 테스트는 실제 LLM API를 사용합니다.
- `~/.nanobot/config.json`에 API 키 설정 필요
- Gemini 3 Pro 권장 (`gemini/gemini-3-pro-preview`)

### Worker 테스트 타임아웃
Worker 테스트는 async로 실행됩니다.
- `pytest-asyncio` 설치 확인
- `@pytest.mark.asyncio` 데코레이터 확인

---

**Created**: 2026-02-08
**Last Updated**: 2026-02-08
**Status**: In Progress (Phase 1)
