# Package Sync Fix Plan

- 작성일: 2026-02-26
- 심각도: Medium (테스트 수집 3개 실패)
- 상태: 미해결

## 문제

`pytest tests/` 실행 시 3개 파일에서 수집 오류(collection error) 발생:

```
ERROR tests/dashboard/unit/test_worker_bootstrap.py
ERROR tests/dashboard/unit/test_reconciler.py
ERROR tests/dashboard/unit/test_utils.py
```

## 원인

설치된 nanobot 패키지(site-packages)가 소스 코드보다 구버전입니다.

최근 `storage.py` 리팩토링에서 추가한 `SaveResult` 등의 심볼이 설치된 패키지에는 존재하지 않아 임포트가 실패합니다:

```
ImportError: cannot import name 'SaveResult' from 'nanobot.dashboard.storage'
  (site-packages/nanobot/dashboard/storage.py)   ← 구버전
  (소스: nanobot/dashboard/storage.py)            ← SaveResult 있음
```

Python이 소스 디렉토리 대신 site-packages의 구버전을 우선 로드하기 때문에 발생합니다.

## 해결

```bash
pip install -e .
```

editable 모드로 재설치하면 site-packages가 소스 디렉토리를 직접 참조하게 되어, 소스 변경이 즉시 반영됩니다.

## 영향 범위

- 수집 실패 3개 파일의 테스트가 전부 스킵됨 (worker bootstrap, reconciler, utils)
- 나머지 242개 테스트는 정상 수집/실행
- 이번 Phase 0 변경과는 무관 (기존 이슈)

## 추가 예방

Docker 배포 환경(`Dockerfile`)에서는 `pip install .`로 설치하므로 이 문제 없음. 로컬 개발 환경에서만 발생.
