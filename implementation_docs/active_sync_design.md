# Worker Phase 1 — Active Sync 설계서

> 대상: `nanobot/dashboard/worker.py` `_enforce_consistency()`
> 선행 문서: `implementation_docs/worker_rules.md`
> 상태: 부분 구현 (status sync 구현, R1 유지, blocked sync 미구현)

---

## 1. 배경: 현재 방식의 한계

### 현재: 방어적 스킵 (Defensive Skip)

```
유저가 필드 X 변경 → X를 guard로 쓰는 규칙 스킵 → 나머지 필드 방치
```

**문제점 3가지:**

1. **불일치 방치**: 유저가 `status → completed` 변경 → R2a 스킵 → progress 50% 그대로 남음
2. **One-cycle protection**: 해당 cycle에서만 스킵, 다음 cycle에서 변경 없으면 규칙이 강제 적용 → 결국 유저 의도 무시
3. **의도 해석 불가**: "유저가 건드렸다"만 알고, "무엇을 의도했는가"는 추론하지 않음

### 목표: 능동적 싱크 (Active Sync)

```
유저가 필드 X 변경 → X를 SOURCE OF TRUTH로 삼고 → 관련 필드를 sync
```

핵심 전환: **"건드렸으니 보호한다" → "건드린 걸 기준으로 나머지를 맞춘다"**

---

## 2. 설계 원칙

### P1: 변경된 필드가 진실의 근원 (Changed Field = Source of Truth)

유저가 명시적으로 바꾼 필드의 값을 기준으로 다른 필드를 파생한다.

### P2: 의도가 명확한 경우만 sync

변경의 의도가 모호한 조합은 sync하지 않고 현상 유지한다. (아래 매핑 테이블 참조)

### P3: Safe 규칙은 변경 없음

R2b, R3, R4, R7, R8 등 safe 규칙(빈 필드 백필, 경고 로그)은 현재 그대로 유지한다.
이 규칙들은 유저 데이터를 파괴하지 않으므로 sync 대상이 아니다.

### P4: One-cycle 제한 제거

sync 결과는 snapshot에 반영되므로 다음 cycle에서 재보정되지 않는다.
(sync가 만든 상태가 새로운 snapshot이 됨)

---

## 3. Sync 매핑 테이블

### 3.1 status 변경 시

| 변경 | sync 동작 | 근거 |
|------|-----------|------|
| `→ completed` | `progress.percentage = 100`, `completed_at = now` | 완료 의도 명확 |
| `→ active` (from completed/archived) | `completed_at = None`, progress 유지 | 재개 의도. progress는 이어서 할 수 있으므로 유지 |
| `→ someday` (from completed/archived) | `completed_at = None`, progress 유지 | 재개 의도 (나중에). 위와 동일 |
| `→ active` (from someday) | sync 없음 | 이미 정상 상태 |
| `→ someday` (from active) | sync 없음 | 이미 정상 상태 |
| `→ cancelled` | sync 없음 | archive가 처리 |

### 3.2 progress 변경 시

| 변경 | sync 동작 | 근거 |
|------|-----------|------|
| `→ 100%` | **sync 없음** | 의도 모호 — 검토 중일 수 있음, 아직 active 유지하고 싶을 수 있음 |
| `→ < 100%` (from completed) | **sync 없음** | 의도 모호 — "다시 하고 싶다" vs "기록 수정" 구분 불가 |
| `blocked → true` | sync 없음 | blocker_note는 유저가 별도 입력 |
| `blocked → false` | `blocker_note = None` | 해제 의도 명확 |

> **참고**: `progress → 100%`에서 auto-complete를 안 하는 이유:
> 유저가 status는 건드리지 않고 progress만 100%로 올렸다면,
> "아직 완료 처리하기 전에 검토하려는 것"일 수 있다.
> status를 직접 completed로 바꿔야 완료 의도가 명확하다.

### 3.3 completed_at 변경 시

| 변경 | sync 동작 | 근거 |
|------|-----------|------|
| active/someday에서 `completed_at` 설정 | **보존 (R6 스킵)** | 유저가 의도적으로 완료 시점을 기록한 것. status sync는 안 함 (status를 바꾸지 않았으므로) |
| completed에서 `completed_at` 변경 | sync 없음 | 날짜 수정일 뿐 |
| `completed_at` 제거 | sync 없음 | R3이 다시 백필할 것 |

### 3.4 변경 조합

| 변경 조합 | sync 동작 | 근거 |
|-----------|-----------|------|
| `status → completed` + `progress → 80%` | `completed_at = now`, **progress 80% 유지** | 유저가 둘 다 명시적으로 설정 → 각각 존중 |
| `status → active` + `progress → 0%` | `completed_at = None` | 리셋 의도 명확 |
| `status → completed` + `completed_at` 설정 | `progress = 100%`, **completed_at 유저값 유지** | 유저가 완료 시점을 직접 지정 |

**규칙**: 유저가 명시적으로 설정한 필드는 sync로 덮어쓰지 않는다.
sync 대상 필드가 유저 변경 필드에도 포함되면 → 유저 값 우선.

---

## 4. 규칙별 변환 가이드

현재 규칙이 Active Sync에서 어떻게 바뀌는지:

### R6 (stale completed_at 제거) → 조건부 유지

```
현재: active/someday + completed_at → 제거 (유저가 completed_at 변경 시 스킵)
변경: active/someday + completed_at → 제거 (유저가 completed_at 변경 시 보존) [동일]
     + 유저가 status → active/someday 변경 시 completed_at = None sync 추가
```

R6 자체는 거의 동일하지만, status sync에서 `completed_at = None`을 처리하므로 R6이 할 일이 줄어든다.

### R1 (auto-complete) → **유지** (결정: 2026-03-07)

```
현재: progress 100% + active → completed (유저 변경 시 스킵)
구현: 유지 — 유저 변경 없는 task에서 기존대로 동작
     Active Sync는 status 변경 시 progress/completed_at sync만 추가
```

R1을 유지한 이유: Phase 2 LLM이 progress를 100%로 올려서 완료 처리하는 기존 흐름이 있고, 유저가 status를 직접 변경한 경우는 guard로 이미 보호됨. Active Sync와 R1은 서로 다른 시나리오를 커버한다.

### R2a (completed + progress < 100% 보정) → 유지 (guard + sync 병행)

```
현재: completed + progress < 100% → progress 100% (유저 변경 시 스킵)
구현: R2a 유지 + Active Sync가 status→completed 시 progress=100% sync
     유저가 status + progress 둘 다 변경 시 유저 progress 값 우선 (guard)
```

### R5 (orphan blocker_note 제거) → 유지 (blocked sync는 별도 PR)

```
현재: !blocked + blocker_note → 제거 (유저가 progress 변경 시 스킵)
구현: R5 유지 — blocked→false sync는 별도 PR에서 구현 예정
```

### Reevaluate → 변경 없음

```
현재: 유저가 status 변경 시 재평가 스킵
변경: 유저가 status 변경 시 → sync 적용 후 재평가 스킵 [동일 흐름]
     유저가 status 변경하지 않은 경우 → 기존과 동일하게 재평가
```

---

## 5. 실행 순서 변경

```
현재:
1. Bootstrap
2. Snapshot diff → user_changed_fields: { task_id: {field_set} }
3. Consistency (R6→R1→R2a→...R8) — 각 규칙이 guard 체크
4. Archive → Reevaluate → Recurring → Orphan cleanup

구현:
1. Bootstrap
2. Snapshot diff → (user_changed_fields, snapshot) 반환
3. Active Sync — status 변경 기반 sync 적용 (새 단계)
4. Consistency (R6→R1→R2a→R2b→R3→R4→R5→R7→R8) — 기존 규칙 모두 유지
5. Archive → Reevaluate → Recurring → Orphan cleanup
```

### `_detect_user_changes()` 반환값 변경

```python
# 이전: 변경된 필드 set만 반환
user_changed_fields = self._detect_user_changes(tasks)
# { task_id: {"status", "progress"} }

# 구현: 변경된 필드 set + snapshot을 tuple로 반환
user_changed_fields, snapshot = self._detect_user_changes(tasks)
# snapshot은 _apply_active_sync()에 명시적으로 전달 (old_status 판단에 필요)
```

snapshot을 명시적 파라미터로 전달하여 메서드 간 암묵적 순서 의존성을 제거.

---

## 6. 새 메서드: `_apply_active_sync()`

```python
def _apply_active_sync(
    self, tasks_data: dict, user_changes: dict[str, dict[str, Change]]
) -> bool:
    """변경된 필드를 기준으로 관련 필드를 능동적으로 sync한다.

    sync 규칙:
    - status → completed: progress=100%, completed_at=now (유저가 직접 설정 안 한 경우만)
    - status → active/someday (from terminal): completed_at=None
    - blocked → false: blocker_note=None

    유저가 명시적으로 설정한 필드는 sync로 덮어쓰지 않는다.
    """
```

---

## 7. Snapshot 저장 방식 변경

sync 결과가 다음 cycle에서 "유저 변경"으로 오탐되지 않도록:

```
현재: save 성공 후 snapshot 갱신
변경: 동일 — sync 적용 후 save → snapshot 갱신
     sync가 적용한 필드는 snapshot에 반영되므로 다음 cycle에서 diff 없음
```

이 부분은 변경 불필요. 기존 흐름이 자연스럽게 처리한다.

---

## 8. 테스트 케이스

### 핵심 시나리오

| # | 유저 변경 | 기대 sync | 검증 |
|---|----------|-----------|------|
| S1 | `status → completed` | progress=100%, completed_at=now | status=completed, progress=100, completed_at 존재 |
| S2 | `status → completed` + `progress → 80%` | completed_at=now, progress=80 유지 | 유저가 설정한 progress 존중 |
| S3 | `status → completed` + `completed_at` 설정 | progress=100%, completed_at=유저값 | 유저가 설정한 completed_at 존중 |
| S4 | `status → active` (from completed) | completed_at=None | 재개 시 completed_at 정리 |
| S5 | `progress → 100%` (status 미변경) | sync 없음, status=active 유지 | auto-complete 안 함 |
| S6 | `blocked → false` | blocker_note=None | 해제 시 note 정리 |
| S7 | `status → active` (from someday) | sync 없음 | 불필요한 sync 안 함 |
| S8 | 변경 없음 | safe 규칙만 적용 | R3, R7, R8 등 정상 동작 |
| S9 | 새 task (snapshot 없음) | safe 규칙만 적용 | sync 대상 아님 |

### 기존 테스트 영향

- `tests/dashboard/unit/test_worker_maintenance.py` — R1/R2a/R5 guard 테스트 수정 필요
- `tests/dashboard/unit/test_worker_snapshot.py` — `_detect_user_changes` 반환값 변경 반영
- 새 테스트 파일: `tests/dashboard/unit/test_worker_active_sync.py`

---

## 9. R1 제거에 대한 논의 포인트

R1(progress 100% → auto-complete)을 제거하면:

**장점:**
- Active Sync 철학에 부합 ("status를 안 바꿨다 = 완료 의도 아님")
- 검토 중인 task가 강제 완료되는 문제 해결

**단점:**
- 기존에 progress 100%로 완료 처리하던 유저 습관이 깨짐
- Phase 2 LLM이 progress를 100%로 올려서 완료 처리하는 흐름에 영향

**대안:**
1. **R1 유지 + sync 병행**: progress 100% → auto-complete는 유지하되, 유저가 status를 변경한 cycle에서만 sync 적용
2. **R1 지연**: progress 100% 상태가 2 cycle 이상 유지되면 auto-complete (즉각 반응 안 함)
3. **R1 완전 제거**: status 변경만 완료 트리거로 사용

> 구현 전에 결정 필요. 현재 Phase 2 LLM의 task 수정 패턴을 확인해야 함.

**결정 (2026-03-07)**: R1 유지. Active Sync는 status 변경 기반 sync만 추가하고, progress 100% → auto-complete(R1)은 기존대로 동작. 유저가 status를 변경하지 않고 progress만 100%로 올린 경우 R1이 auto-complete 처리. blocked sync(R5 대체)는 별도 PR에서 처리.

---

## 10. 마이그레이션 체크리스트

- [ ] `_detect_user_changes()` 반환값에 old/new 값 추가
- [ ] `_apply_active_sync()` 메서드 구현
- [ ] `_run_maintenance()`에서 sync 단계 추가 (consistency 전)
- [ ] `_enforce_consistency()`에서 R1 처리 결정 (제거/유지/지연)
- [ ] `_enforce_consistency()`에서 R2a, R5의 guard 로직 → sync로 이동
- [ ] R6 조건 조정 (status sync가 completed_at을 처리하므로)
- [ ] 기존 테스트 수정 (guard → sync 동작 검증으로 전환)
- [ ] 새 테스트 작성 (Section 8 시나리오)
- [ ] `implementation_docs/worker_rules.md` 업데이트
- [ ] `CLAUDE.md` Worker 섹션 업데이트

---

## 11. 규칙 최종 구조 (변경 후)

```
_run_maintenance() 실행 순서 (구현):

1. Bootstrap
2. Snapshot diff → (user_changed_fields, snapshot) 반환
3. Active Sync (status 변경 기반 — progress/completed_at sync)
4. Consistency (R6→R1→R2a→R2b→R3→R4→R5→R7→R8) — 기존 규칙 모두 유지
5. Archive
6. Reevaluate (유저 status 변경 시 스킵 — 기존과 동일)
7. Recurring
8. Orphan cleanup
```

| 규칙 | 이전 | 이후 |
|------|------|------|
| R1 (auto-complete) | guard 기반 destructive | **유지** (guard 기반 destructive) |
| R2a (progress 보정) | guard 기반 destructive | **유지** (Active Sync와 병행) |
| R2b (cancelled 경고) | safe | 변경 없음 |
| R3 (completed_at 백필) | safe | 변경 없음 |
| R4 (blocked 경고) | safe | 변경 없음 |
| R5 (blocker_note 제거) | guard 기반 destructive | **유지** (blocked sync는 별도 PR) |
| R6 (stale completed_at) | guard 기반 destructive | **유지** (Active Sync와 역할 분담) |
| R7 (deadline 백필) | safe | 변경 없음 |
| R8 (deadline_text 백필) | safe | 변경 없음 |
| **Active Sync** | — | **신규** (status/blocked 변경 → 관련 필드 sync) |
