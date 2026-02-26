# 구조 리팩토링 계획: Ledger-Based Notification + Reconciler

> 작성일: 2026-02-25 (rev.4)
> 핵심: Notification 리스트가 곧 스케줄. 시간이 되면 보내고, GCal은 Reconciler가 맞춘다.
> Per-notification cron job 제거. PR 2개로 실행.

## 1. 문제

### 1.1 현재 구조: 도구 하나가 3곳을 동시에 씀

notification 도구 3개(schedule, update, cancel)가 각각 Notion(SOT) + Cron + GCal을 직접 조작하며,
각 단계의 실패 조합마다 다른 처리(rollback, best-effort, claim-before-publish)가 필요함.

**schedule_notification.py (245줄)의 execute 흐름:**

```
1. cron_service.add_job()              → Cron 등록
2. _validate_and_save_notifications()  → Notion 저장 (1차)
3. [실패 시] cron_service.remove_job() → Cron 롤백
4. gcal_client.create_event()          → GCal 생성 (best-effort)
5. _validate_and_save_notifications()  → Notion 저장 (2차, gcal_event_id)
6. _send_telegram()                    → 사용자에게 확인 알림
```

**update_notification.py (233줄)의 execute 흐름:**

```
1. _validate_and_save_notifications()  → Notion 저장 (1차)
2. cron_service.add_job()              → 새 Cron 등록
3. cron_service.remove_job()           → 구 Cron 삭제
4. _validate_and_save_notifications()  → Notion 저장 (2차, cron_job_id)
5. gcal_client.update_event()          → GCal 수정 (best-effort)
   또는 gcal_client.create_event()     → GCal 신규 (gcal_event_id 없을 때)
6. _validate_and_save_notifications()  → Notion 저장 (3차, gcal_event_id)
7. _send_telegram()                    → 사용자에게 확인 알림
```

**cancel_notification.py (164줄)의 execute 흐름:**

```
1. _validate_and_save_notifications()  → Notion 저장 (status=cancelled)
2. cron_service.remove_job()           → Cron 삭제 (best-effort)
3. gcal_client.delete_event()          → GCal 삭제 (best-effort)
4. _send_telegram()                    → 사용자에게 확인 알림
```

**commands.py의 notification delivery 흐름 (391-466줄):**

```
1. _load_notifications_data()            → pre-check guard
2. agent.process_direct()                → LLM 처리
3. claim_notification_delivered()        → delivered 마킹 + save (3-tuple 리턴)
     → (True,  gcal_id, False) = 성공
     → (False, None,    True)  = 의도적 skip (cancelled/not found)
     → (False, None,    False) = transient 에러 → 그래도 publish
4. bus.publish_outbound()                → 조건부 발송
5. delete_gcal_event_on_delivery()       → GCal 삭제 (best-effort)
```

### 1.2 이로 인한 문제들

| 문제 | 현재 위치 | CLAUDE.md |
|------|-----------|-----------|
| publish 실패 시 "delivered인데 미발송" | commands.py claim pattern | Known Limitation #10 |
| GCal 삭제 best-effort → orphan event 누적 | 3개 도구 + commands.py | Known Limitation #12 |
| delivered 48h 유지 → LLM 중복 처리 | worker.py | Known Limitation #13 |
| `__init__`/`set_context`/`_send_telegram` 3곳 복사 | 3개 도구 각 lines 23-61 | — |
| save를 2-3회 호출 (외부 ID 역저장) | schedule(2회), update(3회) | — |
| 에러 처리 전략 파일마다 다름 | rollback vs best-effort vs claim | — |
| `_configured_backend` 전역 mutable state | base.py:41 | Known Limitation #2 |

### 1.3 추가 안티패턴 (notification 외)

| 문제 | 위치 | 심각도 |
|------|------|--------|
| storage validation 6곳 중복 | storage.py + notion/storage.py | High |
| `(bool, str)` 튜플 리턴 (의미 불명확) | StorageBackend.save_* 전체 | Medium |
| `**kwargs` 있는 도구 / 없는 도구 혼재 | 구 도구 6개 vs 신 도구 6개 | Medium |
| `Optional[str]` vs `str \| None` 혼재 | 신 도구 4개 | Low |
| 같은 6개 파라미터가 3-4 레이어 관통 | loop→heartbeat→worker→tools | Medium |

### 1.4 근본 원인: per-notification cron job

**현재**: notification마다 CronService에 개별 cron job을 등록하고, cron이 시간에 맞춰 발동.
이로 인해 cron 등록/삭제/롤백/동기화 + delivery 시 claim-before-publish가 필요.

**실제로 필요한 것**: notification 리스트(장부)에 `scheduled_at`이 있다.
시간이 되면 메시지를 보내면 된다. **장부 자체가 스케줄이다.**

Per-notification cron job이 불필요한 복잡성의 원천.

---

## 2. 해결: Ledger-Based Delivery + Reconciler

### 2.1 핵심 아이디어

> **"도구는 장부(Notion)에 쓰기만 한다. 시간이 되면 Scheduler가 보낸다. GCal은 Reconciler가 맞춘다."**

```
현재                                  새 구조
────────────────────────             ────────────────────────
도구 → Notion (저장)                 도구 → Notion (저장, 끝)
     → CronService (per-notif job)
     → GCal (best-effort)           Scheduler → 장부 확인
     → Notion (2차, 외부 ID)                   → 시간 됐으면 발송
     → rollback (실패 시)                      → delivered 마킹
     → _send_telegram (에러 시)
                                    Reconciler → GCal 동기화
commands.py:                                   → 실패 → 다음 사이클에 retry
  → claim-before-publish (3-tuple)
  → LLM 처리 후 발송                Per-notification cron job 없음.
  → GCal 삭제 (best-effort)         cron_job_id 필드 없음.
```

### 2.2 4개 컴포넌트

**Processing Lock** (asyncio.Lock): Worker와 Main Agent의 상호 배제.

```
Main Agent가 메시지 처리 중 → Worker 대기
Worker 사이클 실행 중       → Main Agent 대기
Timer 발동 시              → Worker/Main 끝날 때까지 대기
```

**NotificationReconciler** (sync): 장부를 읽고 GCal 상태를 맞추고, 배달할 것을 알려줌.

```python
def reconcile(self) -> ReconcileResult:
    """장부의 모든 notification을 확인하고 필요한 조치를 리턴."""
    for n in notifications:
        if status == "pending":
            if scheduled_at <= now:   → due 목록에 추가 (배달 대상)
            else:                     → GCal 이벤트 있는지 확인, 없으면 생성
        elif status in ("cancelled", "delivered"):
            → GCal 이벤트 있으면 삭제
    return ReconcileResult(due=[...], next_due_at=datetime, changed=bool)
```

**ReconciliationScheduler** (async): Reconciler를 실행하고, due notification을 발송하고, 다음 타이머를 건다.

```python
async def trigger(self):
    result = await asyncio.to_thread(reconciler.reconcile)
    for n in result.due:
        if await self._deliver(n):              # 발송 성공 시에만
            reconciler.mark_delivered(n["id"])   # 장부에 delivered 마킹
    self._arm_timer(result.next_due_at)         # 다음 배달 시간에 wake-up
```

**도구** (3개): Notion에 desired state만 기록.

```python
schedule → notification 생성 (status="pending", scheduled_at="...")
update   → notification 수정 (scheduled_at 변경 등)
cancel   → notification 상태 변경 (status="cancelled")
# 끝. Cron/GCal/Telegram 코드 없음.
```

### 2.3 Trigger 전략

```
프로세스 시작
  → scheduler.trigger()  (즉시 → 놓친 배달 처리 + 타이머 초기화)

도구 save 완료 (_process_message 끝, lock 안에서)
  → await scheduler.trigger()  (즉시 → GCal 동기화 + 타이머 갱신)

Scheduler 타이머 만료 (lock 획득 후)
  → 다음 pending notification의 scheduled_at에 정확히 wake-up
  → 해당 notification 발송 + delivered 마킹
  → 다음 타이머 갱신

Worker 사이클 (30분 heartbeat, lock 안에서)
  → scheduler.trigger()  (safety net — 놓친 거 있으면 여기서 잡음)
```

**정확도**: per-notification cron과 동등. Scheduler가 `asyncio.sleep(delay)`로
다음 pending notification의 정확한 시간에 깨어남. 30분 heartbeat는 fallback일 뿐.

**동시 실행 방지**: 모든 trigger 호출은 `_processing_lock` 안에서 실행됨.
타이머 만료 시에도 lock 획득 후 실행하므로, Worker/Main과 겹치지 않음.

### 2.4 이 구조가 해결하는 것

| Known Limitation | 해결 방식 |
|------------------|-----------|
| #2 `_configured_backend` 전역 state | Backend DI로 제거 (PR 1, 아래 참조) |
| #9 Worker vs Main Agent race condition | `_processing_lock`으로 상호 배제. 0.056% → 0% |
| #10 claim-before-publish | **구조적 제거.** Scheduler가 발송 → mark_delivered. 3-tuple 없음 |
| #12 GCal orphan event | Reconciler가 매 사이클 cancelled/delivered의 GCal 이벤트 삭제 |
| #13 delivered 48h LLM 중복 | Reconciler가 상태 기반 정리. LLM 의존 없음 |
| 도구 간 코드 복사 | Cron/GCal 코드 자체가 도구에서 없어짐 |
| save 2-3회 호출 | 도구에서 save 1회. Reconciler에서 save 1회 (GCal ID) |
| 에러 처리 불일치 | Reconciler의 단일 전략: "실패 → 다음 사이클에 retry" |
| 6개 파라미터 3-4 레이어 관통 | 도구는 `(workspace, backend)`만. 나머지는 Reconciler 생성 시 1회 |

### 2.5 제거되는 코드/개념

| 제거 대상 | 위치 |
|-----------|------|
| `cron_job_id` 필드 | notification dict, schema |
| Per-notification cron job 생성/삭제/롤백 | schedule/update/cancel 도구 |
| `cron_service` 파라미터 (notification 도구) | 3개 도구 + loop.py + worker.py |
| `set_context(channel, chat_id)` | 3개 도구 |
| `_send_telegram()` | 3개 도구 |
| `claim_notification_delivered()` | commands.py (36-104줄) |
| `delete_gcal_event_on_delivery()` | commands.py (17-33줄) |
| `_load_notifications_data` / `_save_notifications_data` | commands.py |
| `on_cron_job` notification 분기 전체 | commands.py (391-466줄) |
| 3-tuple `(bool, str\|None, bool)` | commands.py |
| `suppress_publish` / `should_publish` 분기 | commands.py |
| `gcal_client`/`gcal_timezone`/`gcal_duration_minutes` (도구) | 3개 도구 + loop.py + worker.py |
| `send_callback`/`notification_chat_id` (도구) | 3개 도구 + loop.py + worker.py |
| Worker/Main race condition (0.056%) | Known Limitation #9 — `_processing_lock`으로 해결 |

---

## 3. PR 구성

### PR 1: SaveResult + Backend DI + 컨벤션 통일

가장 낮은 위험. notification 외 전체 도구의 일관성 확보 + 구조적 개선.

#### 3a. `SaveResult` NamedTuple 추가

**파일**: `nanobot/dashboard/storage.py`

```python
from typing import NamedTuple

class SaveResult(NamedTuple):
    success: bool
    message: str
```

- `NamedTuple`이므로 기존 `ok, msg = save_tasks(data)` 그대로 동작
- `StorageBackend` ABC의 save_* 리턴 타입: `tuple[bool, str]` → `SaveResult`
- `JsonStorageBackend._save_json` 리턴: `SaveResult(True, "Saved successfully")`
- `NotionStorageBackend._save_entity_items` 리턴: `SaveResult(True, ...)` / `SaveResult(False, ...)`

#### 3b. Storage Validation Template Method

**파일**: `nanobot/dashboard/storage.py`, `nanobot/notion/storage.py`

`StorageBackend` ABC에 concrete `save_*()` 추가 → validate → abstract `_persist_*()` 위임:

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
    # save_insights → validation 없이 직접 _persist_insights() (Known Limitation #4)
```

JsonStorageBackend / NotionStorageBackend:
- `save_tasks()` → `_persist_tasks()` rename, validation 블록 삭제
- `save_questions()` → `_persist_questions()` 동일
- `save_notifications()` → `_persist_notifications()` 동일
- `save_insights()` → `_persist_insights()` 동일

외부 인터페이스 변경 없음: `storage_backend.save_tasks(data)` 호출이 그대로 동작.

#### 3c. Backend DI (Known Limitation #2 해결)

**`_configured_backend` 전역 mutable state를 제거**하고 생성자 주입으로 변경.

**파일**: `nanobot/agent/tools/dashboard/base.py`

```python
# 현재 (전역 state)
class BaseDashboardTool(Tool):
    _configured_backend = None  # 클래스 변수 — 모든 인스턴스가 공유

    @classmethod
    def configure_backend(cls, backend): ...

    @property
    def _backend(self):
        if BaseDashboardTool._configured_backend is not None:
            return BaseDashboardTool._configured_backend
        ...

# 변경 후 (생성자 주입)
class BaseDashboardTool(Tool):
    def __init__(self, workspace: Path, backend: StorageBackend | None = None):
        self.workspace = workspace
        if backend is not None:
            self._backend_instance = backend
        else:
            from nanobot.dashboard.storage import JsonStorageBackend
            self._backend_instance = JsonStorageBackend(workspace)

    @property
    def _backend(self) -> StorageBackend:
        return self._backend_instance
```

**왜 안전한가**:
- `AgentLoop.__init__`에서 `_configure_storage_backend()`가 `_register_default_tools()` **전에** 실행됨
- 따라서 backend가 이미 존재하는 상태에서 도구가 생성됨
- `configure_backend()` 클래스 메서드, `_configured_backend` 클래스 변수 삭제

**파일**: `nanobot/agent/loop.py`

```python
# 현재
BaseDashboardTool.configure_backend(backend)
...
self.tools.register(CreateTaskTool(workspace=self.workspace))

# 변경 후
self.tools.register(CreateTaskTool(self.workspace, self._storage_backend))
self.tools.register(UpdateTaskTool(self.workspace, self._storage_backend))
# ... 모든 dashboard 도구에 backend 전달
```

**파일**: `nanobot/dashboard/worker.py`

```python
# 현재
self.tools.register(CreateQuestionTool(self.workspace))

# 변경 후
self.tools.register(CreateQuestionTool(self.workspace, self.storage_backend))
```

**효과**:
- Known Limitation #2 완전 해결
- 테스트에서 `BaseDashboardTool.configure_backend(None)` reset 불필요
- 각 도구 인스턴스가 자신의 backend 참조를 명확히 소유

#### 3d. Convention 통일

12개 dashboard 도구 파일:

| 변경 | 대상 | 이유 |
|------|------|------|
| `**kwargs: Any` 제거 | create_task, update_task, archive_task, answer_question, create_question, save_insight | registry.execute()가 TypeError catch → LLM에 에러 반환 → retry |
| `Optional[str]` → `str \| None` | update_question, list_notifications | PEP 604, Python 3.11+ |
| `parameters` 리턴 `dict` → `dict[str, Any]` | 신 도구 6개 | BaseTool 인터페이스와 일치 |

#### PR 1 수정 파일

| 파일 | 변경 유형 |
|------|-----------|
| `nanobot/dashboard/storage.py` | SaveResult 추가, ABC template method, JsonStorageBackend rename |
| `nanobot/notion/storage.py` | save_* → _persist_* rename, validation 삭제 |
| `nanobot/agent/tools/dashboard/base.py` | _configured_backend 제거, 생성자 DI |
| `nanobot/agent/loop.py` | configure_backend 호출 삭제, 도구 생성 시 backend 전달 |
| `nanobot/dashboard/worker.py` | 도구 생성 시 backend 전달 |
| `nanobot/agent/tools/dashboard/create_task.py` | kwargs 제거, super().__init__ 시그니처 변경 |
| `nanobot/agent/tools/dashboard/update_task.py` | kwargs 제거, 동일 |
| `nanobot/agent/tools/dashboard/archive_task.py` | kwargs 제거, 동일 |
| `nanobot/agent/tools/dashboard/answer_question.py` | kwargs 제거, 동일 |
| `nanobot/agent/tools/dashboard/create_question.py` | kwargs 제거, 동일 |
| `nanobot/agent/tools/dashboard/save_insight.py` | kwargs 제거, 동일 |
| `nanobot/agent/tools/dashboard/update_question.py` | Optional 통일, 동일 |
| `nanobot/agent/tools/dashboard/list_notifications.py` | Optional 통일, 동일 |

#### PR 1 검증

```bash
ruff format . && ruff check .
pytest tests/ -v -m "not e2e"
pytest tests/test_dashboard_tools.py tests/test_tool_validation.py -v
```

---

### PR 2: Reconciler + Scheduler + 도구 간소화

핵심 구조 변경. Per-notification cron 제거, Reconciler/Scheduler 도입, 도구 간소화.

#### 4a. ReconcileResult + NotificationReconciler

**새 파일**: `nanobot/dashboard/reconciler.py`

```python
"""Notification Reconciler — 장부(Notion) 기반으로 GCal 동기화 + 배달 대상 판별.

원칙:
- Notification 리스트(장부)가 Single Source of Truth.
- GCal은 파생 상태. Reconciler가 장부에 맞춘다.
- Per-notification cron job 없음. 장부의 scheduled_at이 곧 스케줄.
- 모든 연산은 멱등(idempotent). 같은 입력에 같은 결과.
- 실패 시 다음 사이클에 자동 retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.dashboard.storage import StorageBackend
    from nanobot.google.calendar import GoogleCalendarClient


@dataclass
class ReconcileResult:
    """reconcile() 호출 결과."""
    due: list[dict] = field(default_factory=list)   # 배달 대상 (scheduled_at <= now)
    next_due_at: datetime | None = None              # 다음 배달 시간 (타이머용)
    changed: bool = False                            # storage 변경 여부


class NotificationReconciler:

    def __init__(
        self,
        storage_backend: StorageBackend,
        gcal_client: GoogleCalendarClient | None = None,
        gcal_timezone: str = "Asia/Seoul",
        gcal_duration_minutes: int = 30,
        default_chat_id: str | None = None,
        default_channel: str = "telegram",
    ):
        self.storage = storage_backend
        self.gcal = gcal_client
        self.gcal_timezone = gcal_timezone
        self.gcal_duration_minutes = gcal_duration_minutes
        self.default_chat_id = default_chat_id
        self.default_channel = default_channel

    # ---- Public API ----

    def reconcile(self) -> ReconcileResult:
        """장부의 모든 notification을 확인하고 조치할 내역을 리턴.

        sync 함수. 호출자가 asyncio.to_thread()로 감싼다.
        """
        data = self.storage.load_notifications()
        notifications = data.get("notifications", [])
        now = datetime.now()  # naive (서버 TZ=Asia/Seoul, parse_datetime도 naive 리턴)
        result = ReconcileResult()

        for n in notifications:
            status = n.get("status", "")

            if status == "pending":
                scheduled = self._parse_scheduled(n)
                if scheduled is None:
                    continue

                if scheduled <= now:
                    result.due.append(n)
                else:
                    result.changed |= self._ensure_gcal(n)
                    if result.next_due_at is None or scheduled < result.next_due_at:
                        result.next_due_at = scheduled

            elif status in ("cancelled", "delivered"):
                result.changed |= self._remove_gcal(n)

        if result.changed:
            self.storage.save_notifications(data)

        return result

    def mark_delivered(self, notif_id: str) -> bool:
        """notification을 delivered로 마킹. GCal 정리는 다음 reconcile에서.

        sync 함수. 호출자가 asyncio.to_thread()로 감싼다.
        """
        data = self.storage.load_notifications()
        notifications = data.get("notifications", [])
        target = next((n for n in notifications if n.get("id") == notif_id), None)
        if not target or target.get("status") != "pending":
            return False
        target["status"] = "delivered"
        target["delivered_at"] = datetime.now().isoformat()
        ok, _ = self.storage.save_notifications(data)
        return ok

    # ---- GCal 동기화 (멱등) ----

    def _ensure_gcal(self, n: dict) -> bool:
        """pending인데 GCal 없으면 생성."""
        if not self.gcal or n.get("gcal_event_id"):
            return False
        try:
            event_id = self.gcal.create_event(
                summary=n["message"],
                start_iso=n["scheduled_at"],
                timezone=self.gcal_timezone,
                duration_minutes=self.gcal_duration_minutes,
            )
            n["gcal_event_id"] = event_id
            return True
        except Exception as e:
            logger.warning(f"Reconcile: GCal create failed for {n.get('id')}: {e}")
            return False

    def _remove_gcal(self, n: dict) -> bool:
        """cancelled/delivered인데 GCal 있으면 삭제."""
        gcal_event_id = n.get("gcal_event_id")
        if not self.gcal or not gcal_event_id:
            return False
        try:
            self.gcal.delete_event(event_id=gcal_event_id)
        except Exception:
            pass  # 이미 삭제된 것 — 멱등
        n["gcal_event_id"] = None
        return True

    # ---- helpers ----

    @staticmethod
    def _parse_scheduled(n: dict) -> datetime | None:
        try:
            from nanobot.dashboard.utils import parse_datetime
            return parse_datetime(n["scheduled_at"])
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Reconcile: invalid scheduled_at for {n.get('id')}: {e}")
            return None
```

> **`parse_datetime` 위치**: `nanobot/dashboard/worker.py`에서 `nanobot/dashboard/utils.py`로 이동.
> worker.py와 reconciler.py가 서로 import하면 순환 참조이므로, 공유 유틸로 분리한다.
> worker.py의 기존 호출부는 `from nanobot.dashboard.utils import parse_datetime`으로 변경.
>
> **naive datetime 규칙**: `parse_datetime`은 항상 **naive datetime** (timezone 정보 없음)을 리턴한다.
> `reconcile()`의 `datetime.now()`도 naive. 서버가 `TZ=Asia/Seoul`로 실행되므로 (Docker 설정)
> 둘 다 서울 시간 기준으로 일치한다. timezone-aware datetime이 입력되면 `.replace(tzinfo=None)`으로 변환.
> 이 규칙이 깨지면 `TypeError: can't compare offset-naive and offset-aware datetimes` 발생.

**핵심 설계 결정**:
- `reconcile()`은 **sync** 함수. StorageBackend 메서드가 모두 sync이므로.
- Cron 관련 코드 **전혀 없음**. `cron_job_id` 필드 없음. 장부의 `scheduled_at`이 곧 스케줄.
- `reconcile()`은 due notification을 직접 발송하지 않음. `ReconcileResult.due`로 리턴만 함.
  발송은 async인 `ReconciliationScheduler`가 담당 (sync/async 분리).
- GCal update는 하지 않음 (create/delete만). `scheduled_at` 변경 시 update 도구가
  `gcal_event_id = None`으로 리셋 → Reconciler가 다음 사이클에서 신규 생성.
  **구 GCal 이벤트는 orphan으로 남는다** — 단일 사용자 개인 도구이므로 수용.
  Google Calendar에서 시간 지나면 자연 소멸. (Known Limitation, CLAUDE.md에 기록)

#### 4b. ReconciliationScheduler

**파일**: `nanobot/dashboard/reconciler.py` (같은 파일)

```python
import asyncio

from nanobot.bus.events import OutboundMessage


class ReconciliationScheduler:
    """Reconciler를 실행하고, due notification을 발송하고, 다음 타이머를 건다.

    async 컴포넌트. event loop 위에서 동작.

    동시 실행 방지:
    - trigger()는 항상 _processing_lock 안에서 호출되어야 한다.
    - _process_message, Worker._run_maintenance: 이미 lock 안에서 await trigger() 호출.
    - _arm_timer의 _wake(): lock 획득 후 trigger() 호출.
    - _running 플래그는 추가 방어 (같은 lock 안에서 재진입 방지).
    """

    def __init__(
        self,
        reconciler: NotificationReconciler,
        send_callback,        # async (OutboundMessage) -> None
        processing_lock: asyncio.Lock,
    ):
        self.reconciler = reconciler
        self.send_callback = send_callback
        self._processing_lock = processing_lock
        self._timer: asyncio.Task | None = None
        self._running = False   # 재진입 방지 플래그

    async def trigger(self) -> None:
        """reconcile 실행 + due 발송 + 타이머 갱신.

        호출자가 _processing_lock을 잡고 있어야 한다 (또는 _wake가 잡음).
        _running 플래그로 재진입 방지.
        """
        if self._running:
            return
        self._running = True
        try:
            result = await asyncio.to_thread(self.reconciler.reconcile)

            for n in result.due:
                if await self._deliver(n):
                    try:
                        await asyncio.to_thread(
                            self.reconciler.mark_delivered, n["id"]
                        )
                    except Exception:
                        logger.exception(f"Failed to mark {n.get('id')} delivered")
                # _deliver가 False → mark_delivered 스킵 → 다음 reconcile에서 재시도

            self._arm_timer(result.next_due_at)

        except Exception:
            logger.exception("Reconciliation failed")
        finally:
            self._running = False

    async def _deliver(self, notification: dict) -> bool:
        """notification 메시지를 Telegram으로 발송. 성공 시 True."""
        chat_id = self.reconciler.default_chat_id
        channel = self.reconciler.default_channel
        if not chat_id or not self.send_callback:
            logger.warning(f"Cannot deliver {notification.get('id')}: no chat_id")
            return False

        try:
            await self.send_callback(
                OutboundMessage(
                    channel=channel, chat_id=chat_id,
                    content=notification["message"],
                )
            )
            return True
        except Exception:
            logger.exception(f"Failed to deliver {notification.get('id')}")
            return False

    def _arm_timer(self, next_due_at: datetime | None) -> None:
        """다음 pending notification 시간에 wake-up 타이머 설정."""
        if self._timer:
            self._timer.cancel()
            self._timer = None

        if next_due_at is None:
            return

        delay = max(0, (next_due_at - datetime.now()).total_seconds())

        async def _wake():
            await asyncio.sleep(delay)
            async with self._processing_lock:
                await self.trigger()

        self._timer = asyncio.create_task(_wake())

    def stop(self) -> None:
        """타이머 정리 (shutdown 시)."""
        if self._timer:
            self._timer.cancel()
            self._timer = None
```

**발송 실패 처리**: `_deliver`가 `False` 리턴 → `mark_delivered` 스킵 →
다음 `trigger()` 호출 시 다시 due 목록에 포함 → 자동 재시도.

**동시 실행 방지**: `_processing_lock`이 Worker ↔ Main ↔ Timer 세 경로를 직렬화.
asyncio.Lock은 비재진입이므로, lock 안에서 호출되는 trigger()는 lock을 다시 잡지 않고
`_running` 플래그로만 재진입을 방지한다. `_wake()`만 lock을 직접 획득한다.

#### 4c. Notification 스키마 변경

**`cron_job_id` 필드 제거**. `channel`/`chat_id`는 스키마에 넣지 않음.

```python
notification = {
    "id": "n_abc12345",
    "message": "회의 시작",
    "scheduled_at": "2026-02-26T15:00:00",
    "scheduled_at_text": "내일 3시",       # 원본 표현 (optional)
    "type": "reminder",
    "priority": "medium",
    "related_task_id": "task_xyz",
    "related_question_id": None,
    "status": "pending",                   # pending → delivered / cancelled
    # "cron_job_id": 삭제됨
    # channel/chat_id 없음 — Reconciler의 default_chat_id 사용
    "created_at": "2026-02-25T10:00:00",
    "delivered_at": None,
    "cancelled_at": None,
    "context": "진행 상황 확인용",
    "created_by": "worker",
    "gcal_event_id": None,                # Reconciler가 채움
}
```

**배달 대상 결정**: Reconciler의 `default_chat_id` / `default_channel` 사용.
현재 단일 Telegram 채널이므로 notification별 channel/chat_id 필드는 불필요.
멀티 채널이 필요해지면 그때 스키마에 추가하면 됨 (YAGNI).

**수정 파일**: `nanobot/dashboard/schema.py` (Pydantic 모델에서 `cron_job_id` 제거),
`nanobot/notion/mapper.py` (`cron_job_id` 매핑 제거)

#### 4d. Notification 도구 간소화

3개 도구에서 Cron/GCal/Telegram 코드 전부 제거. Notion 저장만 남김.

**schedule_notification.py** — 현재 245줄 → ~60줄:

```python
class ScheduleNotificationTool(BaseDashboardTool):
    """Schedule a notification for future delivery."""

    # __init__: (workspace, backend)만. cron_service/gcal_client/send_callback 없음.
    # set_context, _send_telegram: 없음.

    @with_dashboard_lock
    async def execute(self, message: str, scheduled_at: str, ...) -> str:
        scheduled_dt = self._parse_datetime(scheduled_at)
        if not scheduled_dt:
            return f"Error: Could not parse scheduled_at '{scheduled_at}'"

        notification_id = self._generate_id("n")
        notifications_data = await self._load_notifications()
        notifications_list = notifications_data.get("notifications", [])

        notification = {
            "id": notification_id,
            "message": message,
            "scheduled_at": scheduled_dt.isoformat(),
            "type": type,
            "priority": priority,
            "related_task_id": related_task_id,
            "status": "pending",
            "created_at": self._now(),
            "delivered_at": None,
            "cancelled_at": None,
            "context": context,
            "created_by": created_by,
            "gcal_event_id": None,   # Reconciler가 채움
        }

        notifications_list.append(notification)
        notifications_data["notifications"] = notifications_list

        result = await self._validate_and_save_notifications(notifications_data)
        if not result.success:
            return result.message

        return (
            f"Notification scheduled: {notification_id}\n"
            f"Message: {message}\n"
            f"Scheduled at: {scheduled_dt.strftime('%Y-%m-%d %H:%M:%S')}"
        )
```

**cancel_notification.py** — 현재 164줄 → ~40줄:

```python
@with_dashboard_lock
async def execute(self, notification_id: str, reason: str = "") -> str:
    notifications_data = await self._load_notifications()
    notifications_list = notifications_data.get("notifications", [])

    notification, index = self._find_notification(notifications_list, notification_id)
    if not notification:
        return f"Error: Notification '{notification_id}' not found"
    if notification.get("status") == "cancelled":
        return f"Notification '{notification_id}' is already cancelled"
    if notification.get("status") == "delivered":
        return f"Error: Cannot cancel delivered notification '{notification_id}'"

    notification["status"] = "cancelled"
    notification["cancelled_at"] = self._now()
    if reason:
        notification["context"] = f"{notification.get('context', '')}\nCancellation reason: {reason}".strip()

    notifications_list[index] = notification
    notifications_data["notifications"] = notifications_list

    result = await self._validate_and_save_notifications(notifications_data)
    if not result.success:
        return result.message

    return f"Notification '{notification_id}' cancelled"
```

**update_notification.py** — 현재 233줄 → ~45줄:

```python
@with_dashboard_lock
async def execute(self, notification_id: str, message=None, scheduled_at=None, priority=None) -> str:
    notifications_data = await self._load_notifications()
    notifications_list = notifications_data.get("notifications", [])

    notification, index = self._find_notification(notifications_list, notification_id)
    if not notification:
        return f"Error: Notification '{notification_id}' not found"
    if notification.get("status") in ["delivered", "cancelled"]:
        return f"Error: Cannot update {notification['status']} notification"

    if message is not None:
        notification["message"] = message
    if priority is not None:
        notification["priority"] = priority
    if scheduled_at is not None:
        scheduled_dt = self._parse_datetime(scheduled_at)
        if not scheduled_dt:
            return f"Error: Could not parse scheduled_at '{scheduled_at}'"
        notification["scheduled_at"] = scheduled_dt.isoformat()
        notification["gcal_event_id"] = None  # Reconciler가 GCal 재생성

    notifications_list[index] = notification
    notifications_data["notifications"] = notifications_list

    result = await self._validate_and_save_notifications(notifications_data)
    if not result.success:
        return result.message

    return f"Notification '{notification_id}' updated"
```

**핵심: 도구는 desired state만 기록한다.**
- `scheduled_at` 변경 → `gcal_event_id = None`으로 리셋 → Reconciler가 다음 사이클에서 신규 생성.
  **구 GCal 이벤트는 orphan으로 남는다** — pending 상태에서 `gcal_event_id`가 None이 되면
  Reconciler의 `_remove_gcal`은 cancelled/delivered만 처리하므로 구 이벤트를 찾을 수 없다.
  단일 사용자 개인 도구이므로 수용. (Known Limitation, CLAUDE.md에 기록)
- Cron 관련 코드 없음. `cron_job_id` 필드 자체가 없으므로 신경 쓸 것 없음.

#### 4e. on_cron_job 정리

**파일**: `nanobot/cli/commands.py`

Per-notification cron job이 없으므로 `on_cron_job`에서 notification 분기 전체를 삭제.
`claim_notification_delivered`, `delete_gcal_event_on_delivery`,
`_load_notifications_data`, `_save_notifications_data` 모두 삭제.

```python
# 변경 후: notification 로직 완전 제거
async def on_cron_job(job: CronJob) -> str | None:
    """Execute a cron job through the agent (non-notification only)."""
    response = await agent.process_direct(
        job.payload.message,
        session_key=f"cron:{job.id}",
        channel=job.payload.channel or "cli",
        chat_id=job.payload.to or "direct",
    )

    if job.payload.deliver and job.payload.to:
        from nanobot.bus.events import OutboundMessage
        await bus.publish_outbound(
            OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=response or "",
            )
        )

    return response
```

Notification 배달은 `ReconciliationScheduler._deliver()`가 전담.
cron은 이제 notification과 완전히 무관.

#### 4f. Worker + HeartbeatService 연동

**파일**: `nanobot/dashboard/worker.py`

constructor에서 notification 관련 파라미터 대부분 제거.
`reconciler`(또는 `scheduler`) 하나만 받음.

```python
class WorkerAgent:
    def __init__(
        self,
        workspace: Path,
        storage_backend: StorageBackend,
        provider: Any | None = None,
        model: str | None = None,
        scheduler: ReconciliationScheduler | None = None,
        # 삭제: cron_service, bus, send_callback, notification_chat_id,
        #        gcal_client, gcal_timezone, gcal_duration_minutes
    ):
        self.workspace = workspace
        self.storage_backend = storage_backend
        self.provider = provider
        self.model = model
        self.scheduler = scheduler
```

`_run_maintenance()`에 reconcile 호출 추가:

```python
async def _run_maintenance(self) -> None:
    # 기존: bootstrap, consistency, archive, reevaluate
    ...
    # 추가: notification reconciliation + delivery
    if self.scheduler:
        try:
            await self.scheduler.trigger()
        except Exception:
            logger.exception("[Worker] Notification reconciliation error")
```

`_register_worker_tools()`에서 notification 도구 생성 간소화:

```python
def _register_worker_tools(self) -> None:
    ...
    # 현재: ScheduleNotificationTool(workspace, cron_service, **notif_kwargs) — 6개 파라미터
    # 변경: ScheduleNotificationTool(workspace, backend)
    self.tools.register(ScheduleNotificationTool(self.workspace, self.storage_backend))
    self.tools.register(UpdateNotificationTool(self.workspace, self.storage_backend))
    self.tools.register(CancelNotificationTool(self.workspace, self.storage_backend))
    self.tools.register(ListNotificationsTool(self.workspace, self.storage_backend))

    # set_context 블록 삭제 (도구에 set_context 없음)
```

**파일**: `nanobot/heartbeat/service.py`

constructor 간소화 + `_processing_lock` 수신 (**required**):

```python
class HeartbeatService:
    def __init__(
        self,
        workspace: Path,
        processing_lock: asyncio.Lock,    # required — None이면 async with에서 crash
        on_heartbeat=None,
        interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S,
        enabled: bool = True,
        provider=None,
        model: str | None = None,
        storage_backend: StorageBackend | None = None,
        scheduler: ReconciliationScheduler | None = None,
        # 삭제: cron_service, bus, send_callback, notification_chat_id,
        #        gcal_client, gcal_timezone, gcal_duration_minutes
    ):
        ...
        self._processing_lock = processing_lock
```

`_run_worker()`에서 `_processing_lock` 획득 후 Worker 실행:

```python
async def _run_worker(self) -> None:
    async with self._processing_lock:
        worker = WorkerAgent(
            workspace=self.workspace,
            storage_backend=backend,
            provider=self.provider,
            model=self.model,
            scheduler=self.scheduler,
        )
        await worker.run_cycle()
```

> Worker 전체 사이클이 lock 안에서 실행됨 → Main Agent와 절대 동시 실행 안 됨.
> Worker._run_maintenance에서 `await scheduler.trigger()`도 이미 lock 안이므로 안전.
>
> **Trade-off**: Worker Phase 2 (LLM 호출)가 30-60초 걸리면 그동안 사용자 메시지가 대기.
> 단일 사용자이고 Worker가 30분 간격이므로 수용 가능. 체감 지연이 문제되면
> Phase 1만 lock 안에서 실행하고 Phase 2는 lock 밖으로 빼는 최적화 가능 (향후).

#### 4g. loop.py 정리

**파일**: `nanobot/agent/loop.py`

1. `_processing_lock` 생성 + Reconciler/Scheduler 초기화:

```python
class AgentLoop:
    def __init__(self, ...):
        ...
        # Processing lock: Worker ↔ Main 상호 배제
        self._processing_lock = asyncio.Lock()

        # Reconciler + Scheduler 생성
        self._scheduler = None
        if self._storage_backend:
            from nanobot.dashboard.reconciler import (
                NotificationReconciler, ReconciliationScheduler
            )
            reconciler = NotificationReconciler(
                storage_backend=self._storage_backend,
                gcal_client=self._gcal_client,
                gcal_timezone=self._gcal_timezone,
                gcal_duration_minutes=self._gcal_duration_minutes,
                default_chat_id=self._notification_chat_id,
            )
            self._scheduler = ReconciliationScheduler(
                reconciler=reconciler,
                send_callback=self.bus.publish_outbound,
                processing_lock=self._processing_lock,
            )

        # HeartbeatService에 lock 전달
        # heartbeat = HeartbeatService(..., processing_lock=self._processing_lock)
```

2. Notification 도구 항상 등록 (조건 분기 제거):

```python
# 현재 (loop.py:247-270)
if self.cron_service:
    notif_kwargs = dict(gcal_client=..., send_callback=..., ...)  # 5개 파라미터
    self.tools.register(ScheduleNotificationTool(workspace, cron_service, **notif_kwargs))
    ...

# 변경 후 — 항상 등록. 도구는 Notion 저장만 하므로 안전.
self.tools.register(ScheduleNotificationTool(self.workspace, self._storage_backend))
self.tools.register(UpdateNotificationTool(self.workspace, self._storage_backend))
self.tools.register(CancelNotificationTool(self.workspace, self._storage_backend))
self.tools.register(ListNotificationsTool(self.workspace, self._storage_backend))
```

3. `set_context` 블록 삭제 (`loop.py:360-367`, `519-526`):

```python
# 삭제 대상 (2곳):
for notif_tool_name in ("schedule_notification", "update_notification", "cancel_notification"):
    notif_tool = self.tools.get(notif_tool_name)
    if notif_tool and hasattr(notif_tool, "set_context"):
        notif_tool.set_context(msg.channel, msg.chat_id)
```

4. `_process_message`를 `_processing_lock`으로 감싸고, 완료 후 trigger:

```python
async def _process_message(self, msg) -> OutboundMessage | None:
    async with self._processing_lock:
        ...
        # 기존 로직 (LLM loop + tool execution)
        ...
        # 메시지 처리 완료 후 reconciliation trigger (아직 lock 안)
        if self._scheduler:
            await self._scheduler.trigger()
        ...
```

5. 시작 시 즉시 trigger (놓친 배달 처리 + 타이머 초기화):

```python
# AgentLoop.run() 또는 start() 시작 부분:
if self._scheduler:
    async with self._processing_lock:
        await self._scheduler.trigger()
```

> 프로세스 재시작 시 타이머가 메모리에서 유실되므로, 시작 즉시 trigger로
> 놓친 배달을 처리하고 다음 타이머를 설정한다. HeartbeatService 첫 tick(30분)까지
> 기다리지 않아도 됨.

#### 4h. 파라미터 전파 문제 해결 (부수 효과)

PR 2 전후 비교:

```
현재 (6개 파라미터 × 3-4 레이어):
AgentLoop(gcal_client, gcal_tz, gcal_dur, send_cb, notif_chat_id, cron_service)
  → HeartbeatService(gcal_client, gcal_tz, gcal_dur, send_cb, notif_chat_id, cron_service)
    → WorkerAgent(gcal_client, gcal_tz, gcal_dur, send_cb, notif_chat_id, cron_service)
      → ScheduleNotificationTool(cron_service, gcal_client, send_cb, notif_chat_id, gcal_tz, gcal_dur)

변경 후 (scheduler 1개):
AgentLoop → scheduler 생성 (gcal/chat_id 파라미터는 여기서만)
  → HeartbeatService(scheduler)
    → WorkerAgent(scheduler)
      → ScheduleNotificationTool(workspace, backend)  # 외부 서비스 파라미터 없음
```

#### PR 2 수정 파일

| 파일 | 변경 유형 |
|------|-----------|
| `nanobot/dashboard/reconciler.py` | **새 파일** — ReconcileResult, NotificationReconciler, ReconciliationScheduler |
| `nanobot/dashboard/utils.py` | **새 파일** — `parse_datetime` 이동 (worker.py에서 분리, 순환 참조 방지) |
| `nanobot/dashboard/schema.py` | notification에서 `cron_job_id` 제거 |
| `nanobot/notion/mapper.py` | `cron_job_id` 매핑 제거 |
| `nanobot/agent/tools/dashboard/schedule_notification.py` | 간소화 (245줄 → ~60줄) |
| `nanobot/agent/tools/dashboard/update_notification.py` | 간소화 (233줄 → ~45줄) |
| `nanobot/agent/tools/dashboard/cancel_notification.py` | 간소화 (164줄 → ~40줄) |
| `nanobot/cli/commands.py` | notification 관련 함수/분기 전부 삭제 (~100줄 제거) |
| `nanobot/dashboard/worker.py` | constructor 간소화 (12→5 파라미터), scheduler.trigger(), parse_datetime import 변경 |
| `nanobot/agent/loop.py` | `_processing_lock` 생성, scheduler 생성, 도구 간소화, set_context 삭제, startup trigger |
| `nanobot/heartbeat/service.py` | constructor 간소화 (14→8 파라미터), `_processing_lock` 수신, scheduler 전달 |

#### PR 2 검증

```bash
ruff format . && ruff check .
pytest tests/ -v -m "not e2e"

# notification 도구 테스트 (Cron/GCal 관련 삭제 → Notion 저장만 확인)
pytest tests/dashboard/unit/test_notification_tools.py -v

# reconciler 테스트 (신규)
pytest tests/dashboard/unit/test_reconciler.py -v

# GCal 테스트 → reconciler 테스트로 이관
# tests/dashboard/unit/test_notification_gcal.py → test_reconciler.py에 통합
```

**테스트 영향**: 기존 64개 notification 테스트 중:
- Cron/GCal 관련 → reconciler 테스트로 이관
- 도구 테스트 → "Notion 저장만 확인"으로 대폭 간소화 (cron mock, gcal mock 불필요)

---

### PR 3: 선택 사항

PR 2에서 도구의 `_send_telegram()`이 삭제되므로,
"일정 추가됨/수정됨/취소됨" 즉시 확인 알림이 사라짐.

복원 방법:

**A. 도구 리턴값 기반 (간단, 추천)**
- 도구 execute()의 리턴 문자열에 "Notification scheduled: ..." 포함
- Agent의 reaction mode가 처리 (이미 존재하는 흐름)
- 추가 코드 없음

**B. Reconciler에서 알림 (정교)**
- Reconciler가 GCal 동기화 성공 시 Telegram 알림
- Notion에서 직접 추가한 notification도 알림 가능

A 방식이면 PR 3 자체가 불필요.

---

## 4. 실행 순서

```
PR 1: SaveResult + Backend DI + Validation Template + 컨벤션 통일
  ↓ (머지 후)
PR 2: Reconciler/Scheduler 도입 + 도구 간소화 + delivery 재설계
```

**대안**: PR 1과 PR 2를 동시 진행 가능.
notification 도구는 PR 2에서 다시 쓰므로, PR 1의 Optional 통일은 schedule/update/cancel에 적용하지 않아도 됨.

---

## 5. 안전성 근거

| 변경 | 왜 안전한가 |
|------|-------------|
| `SaveResult` (NamedTuple) | tuple unpacking 호환 — `ok, msg = save()` 그대로 동작 |
| Storage template method | 외부 시그니처 `save_tasks(data) -> SaveResult` 불변 |
| Backend DI | `configure_backend()` 전에 `_register_default_tools()` 없음 — 순서 보장됨 |
| `**kwargs` 제거 | `ToolRegistry.execute()`가 TypeError catch → LLM에 에러 문자열 반환 → retry |
| Notification 도구 간소화 | Notion 저장 로직 동일. Cron/GCal 코드만 삭제 |
| Per-notification cron 제거 | Scheduler 타이머가 동일한 정확도 보장. `asyncio.sleep(delay)` |
| Reconciler 신규 | 기존 코드에 영향 없음 (새 파일). 삭제된 코드를 대체 |
| on_cron_job 변경 | notification 분기 제거. 기존 non-notification cron은 그대로 동작 |
| `_deliver` 실패 시 | `_deliver`가 `False` 리턴 → mark_delivered 스킵 → 다음 reconcile에서 재시도 |
| `_processing_lock` | asyncio.Lock — Worker/Main/Timer 직렬화. Known Limitation #9 완전 해결 |
| `_processing_lock` 중 메시지 대기 | Worker Phase 2 (30-60s) 동안 사용자 메시지 지연. 30분 간격이므로 수용 |
| GCal orphan on update | `gcal_event_id = None` 리셋 시 구 이벤트 orphan. 단일 사용자 수용 |
| naive datetime | `parse_datetime` → naive 리턴 보장, `datetime.now()` naive. TZ=Asia/Seoul 전제 |

---

## 6. 해결되는 Known Limitations

| # | 설명 | 해결 |
|---|------|------|
| #2 | `_configured_backend` 전역 state | PR 1: Backend DI로 제거 |
| #9 | Worker vs Main Agent race condition (0.056%) | PR 2: `_processing_lock` 상호 배제 |
| #10 | claim-before-publish "delivered인데 미발송" | PR 2: 구조적 제거. Scheduler가 발송 → mark |
| #12 | GCal orphan event 누적 | PR 2: Reconciler가 매 사이클 정리 |
| #13 | delivered 48h LLM 중복 처리 | PR 2: Reconciler가 상태 기반 정리 |

**신규 Known Limitation (PR 2에서 발생)**:
| # | 설명 | 심각도 |
|---|------|--------|
| NEW | Update 시 GCal orphan event: `gcal_event_id = None` 리셋 → 구 이벤트 삭제 안 됨 | Low |

---

## 7. 향후 정리 대기 (PR 1-2 이후)

해당 파일을 건드리는 기능 개발 시 함께 정리:

| 항목 | 트리거 | 방법 |
|------|--------|------|
| `loop.py` LLM 루프 중복 | loop.py 기능 추가 시 | `_run_tool_loop()` 추출 |
| `context.py` temporal coupling | context 빌드 로직 변경 시 | `_precomputed_dashboard` 제거 |
| `telegram.py` NotificationManager 위치 | 두 번째 채널 추가 시 | `channels/notification_manager.py`로 이동 |
| Reconciler에 LLM 처리 옵션 | context-aware 알림 필요 시 | `_deliver`에서 agent.process_direct 옵션 |
