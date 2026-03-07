# Worker Phase 1 — Consistency Rules Reference

> Source of truth: `nanobot/dashboard/worker.py`
> Last updated: 2026-03-07

## Execution Order

`_run_maintenance()` 실행 순서:

```
1. Bootstrap       — 새 아이템에 ID/timestamp 부여
2. Snapshot diff   — 이전 cycle 대비 유저 변경 필드 감지
3. Active Sync     — 유저 status 변경 기반 관련 필드 sync
4. Consistency     — R6 → R1 → R2a → R2b → R3 → R4 → R5 → R7 → R8 (per task)
5. Archive         — completed/cancelled → archived
6. Reevaluate      — active ↔ someday 재평가
7. Recurring       — 습관 리셋/미완료 기록
8. Orphan cleanup  — 종료된 task의 pending notification 취소
```

Steps 2-7은 단일 `load_tasks()` 호출을 공유한다.
Snapshot은 save 성공 후에만 저장된다.

---

## Field-Level Snapshot Guard

### 원리

매 cycle 종료 시 task 상태를 snapshot 파일에 저장한다.
다음 cycle 시작 시 현재 task를 snapshot과 비교하여 **어떤 필드가 변경됐는지** 감지한다.

```
_detect_user_changes() → { task_id: {changed_field_1, changed_field_2, ...} }
```

각 destructive 규칙은 **자신의 guard 필드**와 intersection이 있을 때만 스킵한다.
guard 필드에 해당하지 않는 변경(예: title)은 규칙 실행을 막지 않는다.

### 추적 필드 (`_TRACKED_FIELDS`)

```
status, priority, deadline, deadline_text, title, context,
tags, progress, estimation, completed_at, reflection, recurring
```

모든 필드가 guard에 쓰이진 않는다. 일부(title, priority, estimation 등)는 diff 로깅용으로만 추적된다.

### 특수 케이스

| 케이스 | 동작 |
|--------|------|
| 첫 실행 (snapshot 없음) | `{}` 반환 → 모든 규칙 적용 |
| 새 task (snapshot에 없음) | 결과에 포함 안 됨 → 모든 규칙 적용 |
| snapshot 파손 | 첫 실행과 동일 처리 |
| save 실패 | snapshot 갱신 안 함 → 다음 cycle에서 동일 diff 재감지 |

---

## Active Sync

### 원리

유저가 `status`를 변경하면, 관련 필드를 source of truth 기준으로 능동적으로 sync한다.
`_apply_active_sync()`은 `_enforce_consistency()` 전에 실행되어 sync 결과가 후속 규칙에 자연스럽게 반영된다.

### Sync 규칙

| 유저 변경 | Sync 동작 | 조건 |
|-----------|-----------|------|
| `status → completed` | `progress=100%`, `completed_at=now` | 유저가 해당 필드도 변경했으면 유저 값 우선 |
| `status → active/someday` (from completed/archived) | `completed_at=None` | 유저가 completed_at도 변경했으면 유저 값 우선 |
| `status → active` (from someday), `→ cancelled`, 기타 | sync 없음 | 이미 정상 상태이거나 archive가 처리 |

### 기존 규칙과 상호작용

| 시나리오 | 동작 |
|----------|------|
| Sync(completed) → R1 | status=completed이므로 R1 조건 불일치 → 안 뜸 |
| Sync(completed) → R2a | progress=100%이므로 R2a 조건 불일치 → 안 뜸 |
| Sync(completed) → Archive | completed → archived 전환 (같은 cycle, 의도한 동작) |
| Sync(active) → R6 | completed_at=None이므로 R6 조건 불일치 → 안 뜸 |
| 유저 변경 없음 | Sync 안 뜸, R1/R2a 등 기존대로 동작 |
| 새 task (snapshot 없음) | Sync 안 뜸, 모든 규칙 정상 적용 |

### 유저 값 우선 원칙

sync 대상 필드가 유저 변경 필드에도 포함되면 유저 값을 우선한다.
예: `status → completed` + `progress → 80%` 동시 변경 → progress 80% 유지, completed_at만 sync.

---

## Rules

### Destructive Rules (guard 있음)

스킵 조건: 유저가 해당 guard 필드를 변경했을 때.

#### R6: stale completed_at 제거

| | |
|---|---|
| **조건** | `status ∈ {active, someday}` AND `completed_at is not None` |
| **동작** | `completed_at = None` |
| **Guard** | `{completed_at}` |
| **스킵 시** | 유저가 의도적으로 completed_at을 설정한 것으로 간주 → 보존 |

#### R1: auto-complete

| | |
|---|---|
| **조건** | `status ∈ {active, someday}` AND `progress.percentage >= 100` |
| **동작** | `status = "completed"`, `completed_at = (기존값 or now)` |
| **Guard** | `{status, progress}` |
| **스킵 시** | 유저가 100%로 올렸지만 active로 유지 중일 수 있음 (검토 중 등) |
| **참고** | `completed_at or now` — R6 스킵으로 유저가 설정한 completed_at이 남아있으면 보존 |

#### R2a: completed인데 progress < 100% 보정

| | |
|---|---|
| **조건** | `status == "completed"` AND `progress.percentage < 100` |
| **동작** | `progress.percentage = 100`, `progress.last_update = now` |
| **Guard** | `{status, progress}` |
| **스킵 시** | 유저가 status나 progress를 직접 변경한 것이므로 강제 보정 안 함 |

#### R5: orphan blocker_note 제거

| | |
|---|---|
| **조건** | `status ∈ {active, someday}` AND `blocked == false` AND `blocker_note` 존재 |
| **동작** | `progress.blocker_note = None` |
| **Guard** | `{progress}` |
| **스킵 시** | 유저가 progress(blocker 포함)를 변경한 것이므로 보존 |

---

### Safe Rules (guard 없음 — 항상 적용)

유저 변경 여부와 무관하게 항상 실행된다. 빈 필드를 채우거나 경고만 하므로 유저 데이터를 파괴하지 않는다.

#### R2b: cancelled + 100% 경고

| | |
|---|---|
| **조건** | `status == "cancelled"` AND `progress.percentage >= 100` |
| **동작** | 로그 경고만 (데이터 변경 없음) |

#### R3: completed_at 백필

| | |
|---|---|
| **조건** | `status ∈ {completed, archived}` AND `completed_at is None` |
| **동작** | `completed_at = now` |

#### R4: blocked인데 note 없음 경고

| | |
|---|---|
| **조건** | `status ∈ {active, someday}` AND `blocked == true` AND blocker_note 비어있음 |
| **동작** | 로그 경고만 (데이터 변경 없음) |

#### R7: deadline 백필 (deadline_text → deadline)

| | |
|---|---|
| **조건** | `deadline` 비어있음 AND `deadline_text`에 파싱 가능한 ISO 날짜 존재 |
| **동작** | `deadline = normalize_iso_date(deadline_text)` |

#### R8: deadline_text 역백필 (deadline → deadline_text)

| | |
|---|---|
| **조건** | `deadline` 있음 AND `deadline_text` 비어있음 |
| **동작** | `deadline_text = deadline` |

---

### Archive (guard 없음)

`_archive_completed_tasks()` — consistency 이후 실행.

| | |
|---|---|
| **조건** | `status ∈ {completed, cancelled}` |
| **동작** | `status = "archived"`, `completed_at` 백필, `progress.percentage = 100` (cancelled 제외) |
| **예외** | `completed` + `recurring.enabled == true` → 아카이브 안 함 (recurring 리셋 대상) |
| **Guard** | 없음 — 유저가 직접 completed/cancelled로 바꿨어도 아카이브 진행 |

---

### Reevaluate (guard 있음)

`_reevaluate_active_status()` — archive 이후 실행.

| | |
|---|---|
| **대상** | `status ∈ {active, someday}` (terminal 상태 제외) |
| **동작** | `_determine_status()` 결과로 active ↔ someday 전환 |
| **Guard** | `{status}` |
| **스킵 시** | 유저가 status를 직접 변경한 것이므로 재평가 안 함 |
| **예외** | recurring task는 guard 무시하고 항상 `active`로 승격 |

`_determine_status()` 판단 기준 (우선순위 순):
1. deadline 임박 (≤ 7일) → active
2. priority == "high" → active
3. progress > 0% → active
4. 최근 업데이트 (≤ 7일) → active
5. 그 외 → someday

---

### Recurring (guard 없음)

`_check_recurring_tasks()` — reevaluate 이후 실행.

| | |
|---|---|
| **대상** | `recurring.enabled == true` AND `status ∉ {archived, cancelled}` |
| **완료 감지** | completed + completed_at이 오늘 → stats 기록, `last_completed_date = today` |
| **리셋** | completed + completed_at이 오늘 이전 → `status = active`, `progress = 0%`, `completed_at = None` |
| **미완료** | 유효 요일인데 미완료 → `last_miss_date = today` |
| **Guard** | 없음 |

---

### Orphan Notification Cleanup (guard 없음)

`_cancel_orphaned_notifications()` — 별도 load/save cycle.

| | |
|---|---|
| **조건** | pending notification의 `related_task_id`가 completed/cancelled/archived task를 가리킴 |
| **동작** | notification status를 cancelled로 변경 |

---

## Guard Field Summary

| 규칙 | Guard 필드 | 유저가 바꾸면 스킵 | 분류 |
|------|-----------|-------------------|------|
| R6 | `{completed_at}` | completed_at | destructive |
| R1 | `{status, progress}` | status 또는 progress | destructive |
| R2a | `{status, progress}` | status 또는 progress | destructive |
| R5 | `{progress}` | progress | destructive |
| Reevaluate | `{status}` | status | destructive |
| R2b | — | 항상 실행 (경고만) | safe |
| R3 | — | 항상 실행 | safe |
| R4 | — | 항상 실행 (경고만) | safe |
| R7 | — | 항상 실행 | safe |
| R8 | — | 항상 실행 | safe |
| Archive | — | 항상 실행 | safe |
| Recurring | — | 항상 실행 | safe |
| Orphan cleanup | — | 항상 실행 | safe |
| **Active Sync** | `{status}` (+ snapshot old_status) | status 변경 시 관련 필드 sync | sync |

---

## 유저 변경 시나리오별 동작

| 변경된 필드 | R6 | R1 | R2a | R5 | Reevaluate | Safe 규칙 |
|------------|----|----|-----|----|------------|----------|
| `title` | 실행 | 실행 | 실행 | 실행 | 실행 | 실행 |
| `status` | 실행 | **skip** | **skip** | 실행 | **skip** | 실행 |
| `progress` | 실행 | **skip** | **skip** | **skip** | 실행 | 실행 |
| `completed_at` | **skip** | 실행 | 실행 | 실행 | 실행 | 실행 |
| `status` + `progress` | 실행 | **skip** | **skip** | **skip** | **skip** | 실행 |
| 변경 없음 | 실행 | 실행 | 실행 | 실행 | 실행 | 실행 |
| 새 task | 실행 | 실행 | 실행 | 실행 | 실행 | 실행 |

---

## 알려진 제약 (Known Limitations)

1. **progress dict coarse 비교** — `progress` 필드는 dict 전체로 비교. `percentage`만 바꿔도 `blocker_note` 변경과 구분 불가.
2. **One-cycle protection** — guard는 해당 cycle에서만 작동. 다음 cycle에서 추가 변경이 없으면 정상 규칙 적용.
3. **Phase 2 tool 수정** — Phase 2(LLM)가 task를 수정하면 다음 cycle에서 해당 필드가 user-changed로 감지됨. 의도한 동작.
