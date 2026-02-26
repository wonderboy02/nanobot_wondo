# E2E Tests

실제 Agent를 실행하여 전체 플로우를 검증하는 End-to-End 테스트입니다.

## 테스트 파일

### 실제 E2E (`@pytest.mark.e2e`, LLM API 필요)

- **test_user_scenarios.py** - 10가지 사용자 시나리오
- **test_contextual_updates.py** - 5가지 맥락 기반 업데이트 (v0.1.4)
- **test_error_scenarios.py** - 7가지 에러 케이스
- **test_worker_integration.py** - Worker + Agent 통합 (3개 테스트, 혼합 성격)
- **test_journey.py** - 사용자 여정 (3개 시나리오)

### 재분류 예정 (LLM 없음, `@pytest.mark.e2e` 없음)

> 아래 파일은 실제로는 unit/integration 성격이며, Phase 1에서 이동 예정입니다.
> 현재 `addopts`에 의해 기본 실행에 포함되므로 기능적 문제는 없습니다.

- **test_notification_simple.py** - 6개 notification 도구 기본 테스트 (실제 Unit)
- **test_notification_realistic.py** - 8개 notification 통합 테스트 (실제 Integration)
- **test_notification_workflow.py** - 5개 notification 워크플로우 테스트 (실제 Integration)

## ⚠️ 주의사항

E2E 테스트는 **실제 LLM API**를 사용합니다.

### 요구사항
1. `~/.nanobot/config.json`에 API 키 설정
2. Gemini 3 Pro 권장 (`gemini/gemini-3-pro-preview`)
3. API 크레딧 필요 (테스트 1회당 ~$0.01)

### 설정 예시
```json
{
  "agents": {
    "defaults": {
      "model": "gemini/gemini-3-pro-preview"
    }
  },
  "providers": {
    "gemini": {
      "apiKey": "YOUR_API_KEY"
    }
  }
}
```

## 실행

```bash
# 모든 E2E 테스트 (-m e2e로 addopts 기본 제외 오버라이드)
pytest tests/dashboard/e2e/ -v -s -m e2e

# 특정 시나리오만
pytest tests/dashboard/e2e/test_user_scenarios.py::test_scenario_01 -v -s -m e2e

# Journey 테스트 (오래 걸림)
pytest tests/dashboard/e2e/test_journey.py -v -s -m e2e
```

## 시나리오 목록

### User Scenarios (10개)
1. Add New Task
2. Update Progress
3. Complete Task
4. Answer Question
5. Cancel Task
6. Change Deadline
7. Block Task
8. Multiple Tasks
9. Natural Language Dates
10. Add Links

### Contextual Updates (5개, v0.1.4)
1. Multiple Answers One Message - 한 메시지로 여러 질문 답변
2. Implicit Blocker Extraction - "어려워요" → blocked
3. Silent Mode - Regular updates SILENT
4. Holistic Update - Multiple aspects 동시 업데이트
5. No Limit on Items - 무제한 tasks/questions

### Error Scenarios (7개)
1. Invalid JSON from LLM
2. Tool Call Failure
3. Ambiguous Message
4. Context Too Large
5. File Corruption
6. Invalid Date Format
7. Extremely Long Message

### Integration (3개)
1. Agent Add → Worker Ask
2. Worker Ask → Agent Answer
3. Complete → History

### Journey (3개)
1. 1주일 학습자 여정
2. 프로젝트 개발자 여정
3. 멀티태스킹 여정

### Notification (재분류 예정, 19개)
- Simple: 6개 기본 도구 테스트
- Realistic: 8개 통합 시나리오
- Workflow: 5개 워크플로우 시나리오

## 예상 실행 시간

- User Scenarios: ~3-5분 (LLM 호출 포함)
- Error Scenarios: ~2-3분
- Integration: ~2분
- Journey: ~5-7분

**총 예상** (E2E만): 12-17분
