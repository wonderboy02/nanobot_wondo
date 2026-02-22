# Dashboard Test Plan

Dashboard Sync Manager의 상세 테스트 계획입니다.

## 📊 현재 상태 (2026-02-08)

### 기존 테스트
- ✅ `tests/dashboard/unit/` - 단위 테스트
- ✅ `tests/dashboard/e2e/` - E2E 시나리오
- ✅ `scripts/test_agent_e2e.py` - 1개 E2E 시나리오
- ✅ `scripts/test_context_dashboard.py` - Context 통합
- ✅ `scripts/test_agent_dashboard.py` - Agent 통합

### 문제점
1. **Worker의 7가지 Case 중 1개만 테스트**
2. **E2E 시나리오 부족** (1개 → 15개 필요)
3. **Edge Case 미테스트**
4. **Link 시스템 미검증**
5. **에러 처리 미테스트**

## 🎯 목표

### Phase 1: 단위 테스트 완성
**목표**: Worker 7 Cases 전체 + Edge Cases
**기간**: 1-2시간
**결과물**: 18개 단위 테스트

### Phase 2: E2E 테스트 확장
**목표**: 10가지 사용자 시나리오 + 5가지 에러 케이스
**기간**: 2-3시간
**결과물**: 15개 E2E 테스트

### Phase 3: 통합 시나리오
**목표**: 1주일 사용자 여정 시뮬레이션
**기간**: 1시간
**결과물**: 1개 통합 테스트 (내부 7단계)

### Phase 4: 성능 테스트
**목표**: 대량 데이터 처리 검증
**기간**: 1시간
**결과물**: 3개 성능 테스트

**총 예상**: 37개 테스트 (기존 5개 → 42개)

## 📋 상세 테스트 케이스

### Unit Tests (18개)

#### test_worker_cases.py (7개)
모든 진행률 체크 Case 테스트:

1. ✅ **Case 1: Not Started**
2. ➕ **Case 2: Far Behind (20%+ gap)**
3. ➕ **Case 3: Slightly Behind (10-20% gap)**
4. ➕ **Case 4: No Update for 48h**
5. ➕ **Case 5: Deadline Approaching**
6. ➕ **Case 6: Nearly Complete (80%+)**
7. ➕ **Case 7: On Track**

### E2E Tests (20개)

#### test_user_scenarios.py (10개)

**Scenario 1: Add New Task** ✅
**Scenario 2: Update Progress**
**Scenario 3: Complete Task**
**Scenario 4: Answer Question**
**Scenario 5: Cancel Task**
**Scenario 6: Change Deadline**
**Scenario 7: Block Task**
**Scenario 8: Multiple Tasks**
**Scenario 9: Natural Language Dates**
**Scenario 10: Add Links**

#### test_contextual_updates.py (5개) - ⭐ NEW v0.1.4

**Contextual 1: Multiple Answers One Message** ✅
- 한 메시지로 여러 질문 동시 답변
- "유튜브로 50% 완료, Hook 어려워요" → 3개 질문 답변

**Contextual 2: Implicit Blocker Extraction** ✅
- "어려워요", "막혔어요" → blocked: true
- 암시적 언어에서 blocker 추출

**Contextual 3: Silent Mode** ✅
- Regular updates → SILENT response
- Commands (/questions) → Show results

**Contextual 4: Holistic Update** ✅
- 한 메시지로 multiple aspects 업데이트
- Progress + Context + Blocker + Questions

**Contextual 5: No Limit on Items** ✅
- v0.1.4: 제한 없음 (기존 10개 → 무제한)
- 15개 tasks 중 task_014 접근 가능

#### test_error_scenarios.py (7개)
1. Invalid JSON from LLM
2. Tool Call Failure
3. Ambiguous Message
4. Context Too Large
5. File Corruption
6. Invalid Date Format
7. Extremely Long Message

---

**Status**: Phase 1 - Setup Complete
**Next**: Unit Tests - Worker 7 Cases
