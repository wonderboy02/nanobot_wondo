# E2E Tests

실제 Agent를 실행하여 전체 플로우를 검증하는 End-to-End 테스트입니다.

## 테스트 파일

- **test_user_scenarios.py** - 10가지 사용자 시나리오
- **test_contextual_updates.py** - 5가지 맥락 기반 업데이트 (v0.1.4) ⭐ NEW
- **test_error_scenarios.py** - 7가지 에러 케이스
- **test_worker_integration.py** - Worker + Agent 통합
- **test_journey.py** - 1주일 사용자 여정

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
# 모든 E2E 테스트
pytest tests/dashboard/e2e/ -v -s

# 특정 시나리오만
pytest tests/dashboard/e2e/test_user_scenarios.py::test_scenario_01 -v -s

# Journey 테스트 (오래 걸림)
pytest tests/dashboard/e2e/test_journey.py -v -s
```

## 시나리오 목록

### User Scenarios (10개)
1. ✅ Add New Task
2. Update Progress
3. Complete Task
4. Answer Question
5. Cancel Task
6. Change Deadline
7. Block Task
8. Multiple Tasks
9. Natural Language Dates
10. Add Links

### Contextual Updates (5개) ⭐ NEW v0.1.4
1. ✅ Multiple Answers One Message - 한 메시지로 여러 질문 답변
2. ✅ Implicit Blocker Extraction - "어려워요" → blocked
3. ✅ Silent Mode - Regular updates SILENT
4. ✅ Holistic Update - Multiple aspects 동시 업데이트
5. ✅ No Limit on Items - 무제한 tasks/questions

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

### Journey (1개)
- 1주일 전체 사용자 여정 시뮬레이션

## 예상 실행 시간

- User Scenarios: ~3-5분 (LLM 호출 포함)
- Error Scenarios: ~2-3분
- Integration: ~2분
- Journey: ~5-7분

**총 예상**: 12-17분
