# 구조 리팩토링 계획

> 작성일: 2026-02-25
> 범위: dashboard 도구 컨벤션 통일 + storage validation 구조화
> PR 2개로 실행

## 배경

리뷰마다 끝없이 문제가 나오는 근본 원인 분석 결과:

- **아키텍처는 건전함** (Stateless agent, Phase 1/2 분리, StorageBackend ABC)
- **구현 레벨에서 copy-paste + 일관성 부재가 누적됨**
  - notification 도구 3개에 동일 코드 114줄 복사
  - storage validation이 6곳에 중복
  - 구 도구(task/question)와 신 도구(notification)의 코딩 스타일이 다름
  - `(bool, str)` 튜플 리턴으로 의미 불명확

## 발견된 안티패턴 요약

| 문제 | 위치 | 심각도 |
|------|------|--------|
| notification `__init__`/`set_context`/`_send_telegram` 3곳 복사 | schedule/update/cancel_notification.py | High |
| storage validation 6곳 중복 | storage.py + notion/storage.py | High |
| `(bool, str)` 튜플 리턴 (의미 불명확) | StorageBackend.save_* 전체 | Medium |
| `**kwargs` 있는 도구 / 없는 도구 혼재 | 구 도구 6개 vs 신 도구 6개 | Medium |
| `Optional[str]` vs `str \| None` 혼재 | 신 도구 4개 | Low |
| `parameters` 리턴 타입 `dict` vs `dict[str, Any]` | 신 도구 6개 | Low |
| 성공 메시지 이모지 유/무, 에러 메시지 따옴표 유/무 | 전 도구 | Low |

---

## PR 1: 타입 + 중복 제거 + 컨벤션 통일

### 1a. `SaveResult` NamedTuple 추가

**파일**: `nanobot/dashboard/storage.py`

```python
from typing import NamedTuple

class SaveResult(NamedTuple):
    success: bool
    message: str
```

- `NamedTuple`이므로 기존 `ok, msg = save_tasks(data)` 패턴 그대로 동작 (tuple unpacking 호환)
- `StorageBackend` ABC의 save_* 리턴 타입을 `tuple[bool, str]` → `SaveResult`로 변경
- 새 코드부터 `result.success`, `result.message`로 사용 가능

### 1b. `NotificationToolBase` 베이스 클래스 생성

**새 파일**: `nanobot/agent/tools/dashboard/notification_base.py` (~45줄)

BaseDashboardTool을 상속하고, 3개 notification 도구의 공통 코드를 포함:

```
NotificationToolBase(BaseDashboardTool)
├── __init__(workspace, cron_service, gcal_client, send_callback,
│            notification_chat_id, gcal_timezone, gcal_duration_minutes)
├── set_context(channel, chat_id)
├── _send_telegram(content)
└── _gcal_handle_error(operation, error)  ← GCal 에러 시 log + telegram (현재 3곳에 인라인)
```

### 1c. 3개 notification 도구 마이그레이션

**수정 파일**:
- `nanobot/agent/tools/dashboard/schedule_notification.py`
- `nanobot/agent/tools/dashboard/update_notification.py`
- `nanobot/agent/tools/dashboard/cancel_notification.py`

각 파일에서:
- `BaseDashboardTool` → `NotificationToolBase` 상속 변경
- `__init__`, `set_context`, `_send_telegram` 삭제 (베이스에서 상속)
- `execute()`는 그대로 유지 (각 도구의 고유 로직)
- GCal 에러 처리를 `await self._gcal_handle_error("schedule", e)` 호출로 교체

**결과**: 3개 파일에서 각 ~20줄 삭제, 총 ~60줄 제거

### 1d. Convention 통일

10개 dashboard 도구 파일 전체:

| 변경 | 대상 파일 | 이유 |
|------|-----------|------|
| `**kwargs: Any` 제거 | create_task, update_task, archive_task, answer_question, create_question, save_insight | registry.execute()가 이미 TypeError catch |
| `Optional[str]` → `str \| None` | update_question, list_notifications, schedule_notification, update_notification | PEP 604, Python 3.11+ |
| `parameters` 리턴 `dict` → `dict[str, Any]` | 신 도구 6개 | BaseTool 인터페이스와 일치 |

### PR 1 수정 파일 목록

| 파일 | 변경 유형 |
|------|-----------|
| `nanobot/dashboard/storage.py` | SaveResult 추가, ABC 리턴 타입 변경 |
| `nanobot/agent/tools/dashboard/notification_base.py` | **새 파일** (NotificationToolBase) |
| `nanobot/agent/tools/dashboard/schedule_notification.py` | 상속 변경, 중복 삭제, Optional 통일 |
| `nanobot/agent/tools/dashboard/update_notification.py` | 동일 |
| `nanobot/agent/tools/dashboard/cancel_notification.py` | 동일 |
| `nanobot/agent/tools/dashboard/create_task.py` | kwargs 제거 |
| `nanobot/agent/tools/dashboard/update_task.py` | kwargs 제거 |
| `nanobot/agent/tools/dashboard/archive_task.py` | kwargs 제거 |
| `nanobot/agent/tools/dashboard/answer_question.py` | kwargs 제거 |
| `nanobot/agent/tools/dashboard/create_question.py` | kwargs 제거 |
| `nanobot/agent/tools/dashboard/save_insight.py` | kwargs 제거 |
| `nanobot/agent/tools/dashboard/update_question.py` | Optional 통일 |
| `nanobot/agent/tools/dashboard/list_notifications.py` | Optional 통일 |

### PR 1 검증

```bash
ruff format . && ruff check .
pytest tests/ -v -m "not e2e"

# notification 테스트 집중 (64개)
pytest tests/dashboard/unit/test_notification_tools.py tests/dashboard/unit/test_notification_gcal.py -v

# 전체 도구 테스트
pytest tests/test_dashboard_tools.py tests/test_dashboard_tools_integration.py tests/test_tool_validation.py -v
```

---

## PR 2: Storage Validation Template Method

### 변경 내용

**StorageBackend ABC** (`nanobot/dashboard/storage.py`):

save_*를 concrete 메서드로 변경 → validate → abstract `_persist_*()` 위임:

```python
class StorageBackend(ABC):
    def save_tasks(self, data: dict) -> SaveResult:
        try:
            from nanobot.dashboard.schema import validate_tasks_file
            validate_tasks_file(data)
        except Exception as e:
            return SaveResult(False, f"Validation error: {e}")
        return self._persist_tasks(data)

    @abstractmethod
    def _persist_tasks(self, data: dict) -> SaveResult: ...

    # save_questions, save_notifications 동일 패턴
    # save_insights → validation 없이 직접 _persist_insights() 호출 (Known Limitation #4)
```

**JsonStorageBackend** (`nanobot/dashboard/storage.py`):
- `save_tasks()` → `_persist_tasks()` rename, validation 블록 삭제
- `save_questions()` → `_persist_questions()` 동일
- `save_notifications()` → `_persist_notifications()` 동일
- `save_insights()` → `_persist_insights()` 동일

**NotionStorageBackend** (`nanobot/notion/storage.py`):
- 동일하게 `save_*()` → `_persist_*()` rename, validation 삭제

**외부 인터페이스 변경 없음**: `storage_backend.save_tasks(data)` 호출이 그대로 동작

### PR 2 수정 파일 목록

| 파일 | 변경 유형 |
|------|-----------|
| `nanobot/dashboard/storage.py` | save_* → concrete validate + abstract _persist_* |
| `nanobot/notion/storage.py` | save_* → _persist_* rename, validation 삭제 |

### PR 2 검증

```bash
ruff format . && ruff check .
pytest tests/ -v -m "not e2e"

# storage + worker 테스트 집중
pytest tests/dashboard/ tests/test_dashboard_tools.py -v
```

---

## 안전성 근거

| 변경 | 왜 안전한가 |
|------|-------------|
| `SaveResult` (NamedTuple) | tuple unpacking 호환 — `ok, msg = save_tasks(data)` 그대로 동작 |
| `NotificationToolBase` 추출 | 64개 테스트가 concrete 클래스 직접 테스트, 상속 구조 변경에 무관 |
| `**kwargs` 제거 | `ToolRegistry.execute()`가 TypeError catch → 에러 문자열로 LLM 반환 |
| Storage template method | 외부 시그니처 `save_tasks(data) -> SaveResult` 불변 |
| 0개 테스트가 `_configured_backend` fixture 설정 | 베이스 클래스 변경에 영향 없음 |

---

## 이번 범위 밖 — 향후 기능 개발 시 정리

| 항목 | 트리거 (언제) | 방법 |
|------|--------------|------|
| `loop.py` LLM 루프 중복 제거 | loop.py에 기능 추가할 때 | `_run_tool_loop()` private 메서드 추출 |
| `loop.py` tool context 설정 중복 | 새 context-aware 도구 추가 시 | `_set_tool_contexts()` 메서드 추출 |
| `context.py` temporal coupling | context 빌드 로직 변경 시 | `_precomputed_dashboard` 제거, 생성자에서 주입 |
| `worker.py` constructor 파라미터 축소 | worker에 기능 추가 시 | notification config 객체로 묶기 |
| `telegram.py` `_on_message` 분리 | 새 미디어 타입 추가 시 | `_build_content_from_update()` 추출 |
| `telegram.py` NotificationManager 위치 | 두 번째 채널 추가 시 | `channels/notification_manager.py`로 이동 |
| Error message 통일 (이모지, 따옴표) | 각 도구 수정 시 | NotificationToolBase 패턴 따르기 |
