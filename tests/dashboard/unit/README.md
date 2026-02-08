# Unit Tests

Dashboard 컴포넌트의 단위 테스트입니다.

## 테스트 파일

- **test_manager.py** - DashboardManager CRUD 작업
- **test_worker_cases.py** - Worker의 7가지 진행률 체크 Case
- **test_schema.py** - Pydantic 스키마 검증
- **test_links.py** - Link 시스템 검증
- **test_edge_cases.py** - Edge cases 처리

## 실행

```bash
# 모든 단위 테스트
pytest tests/dashboard/unit/ -v

# 특정 파일만
pytest tests/dashboard/unit/test_worker_cases.py -v

# Coverage와 함께
pytest tests/dashboard/unit/ --cov=nanobot.dashboard --cov-report=term
```

## 목표

- 90%+ code coverage
- 모든 Worker Cases 검증
- Edge cases 처리 확인
