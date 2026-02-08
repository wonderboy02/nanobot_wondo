# Testing Guide

Dashboard 시스템을 테스트하는 가이드입니다.

## 테스트 환경 설정

### 1. 새로운 테스트 워크스페이스 생성

```bash
# 기존 workspace 백업 (선택)
mv ~/.nanobot/workspace ~/.nanobot/workspace.backup

# 새로 초기화
nanobot onboard
```

### 2. 예제 데이터 로드

```bash
# 예제 Dashboard 복사
cp tests/fixtures/example_dashboard.json ~/.nanobot/workspace/dashboard/
```

예제 데이터를 수동으로 로드하려면:

```python
import json
from pathlib import Path

# 예제 데이터 읽기
with open("tests/fixtures/example_dashboard.json") as f:
    example = json.load(f)

# Dashboard에 복사
dashboard_path = Path.home() / ".nanobot" / "workspace" / "dashboard"

# Tasks
with open(dashboard_path / "tasks.json", "w") as f:
    json.dump({"version": "1.0", "tasks": example["tasks"]}, f, indent=2)

# Questions
with open(dashboard_path / "questions.json", "w") as f:
    json.dump({"version": "1.0", "questions": example["questions"]}, f, indent=2)

# Knowledge
with open(dashboard_path / "knowledge" / "history.json", "w") as f:
    json.dump(example["knowledge"]["history"], f, indent=2)

# ...등등
```

## 테스트 시나리오

### Scenario 1: Dashboard 확인

```bash
# 전체 보기
nanobot dashboard show

# Tasks만
nanobot dashboard tasks

# Someday tasks
nanobot dashboard tasks --someday

# Question Queue
nanobot dashboard questions

# History
nanobot dashboard history
```

**예상 결과:**
- 3개 task (2 active, 1 someday)
- 2개 question
- 1개 completed task in history

### Scenario 2: Worker 실행

```bash
nanobot dashboard worker
```

**Worker가 하는 일:**
1. Task 진행률 체크
   - task_001: 30% 진행, deadline 내일
   - task_002: 0% 진행, deadline 주말
2. Question 생성 가능성:
   - task_002가 시작 안 함 → "시작했어?" 추가
3. Active/Someday 재평가
4. Question Queue 정리

**확인:**
```bash
# Questions 다시 확인
nanobot dashboard questions

# 새로운 question이 추가되었는지 확인
```

### Scenario 3: Question 답변

```bash
# Question 답변
nanobot dashboard answer q_001 "https://youtube.com/watch?v=example"

# 확인
nanobot dashboard questions
```

**예상 결과:**
- q_001이 사라짐 (answered = true)

### Scenario 4: Task 완료 처리

수동으로 task를 완료 처리:

```python
import json
from pathlib import Path
from datetime import datetime

dashboard_path = Path.home() / ".nanobot" / "workspace" / "dashboard"

# tasks.json 읽기
with open(dashboard_path / "tasks.json") as f:
    data = json.load(f)

# task_001 완료 처리
for task in data["tasks"]:
    if task["id"] == "task_001":
        task["status"] = "completed"
        task["completed_at"] = datetime.now().isoformat()
        task["progress"]["percentage"] = 100

# 저장
with open(dashboard_path / "tasks.json", "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

Worker 실행:
```bash
nanobot dashboard worker
```

**예상 결과:**
- task_001이 tasks에서 사라짐
- history에 task_001 추가됨

확인:
```bash
nanobot dashboard tasks
nanobot dashboard history
```

### Scenario 5: 진행률 업데이트

```python
import json
from pathlib import Path
from datetime import datetime

dashboard_path = Path.home() / ".nanobot" / "workspace" / "dashboard"

with open(dashboard_path / "tasks.json") as f:
    data = json.load(f)

# task_002 진행률 업데이트
for task in data["tasks"]:
    if task["id"] == "task_002":
        task["progress"]["percentage"] = 50
        task["progress"]["last_update"] = datetime.now().isoformat()
        task["progress"]["note"] = "초안 작성 완료"

with open(dashboard_path / "tasks.json", "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

Worker 실행 후 확인:
```bash
nanobot dashboard worker
nanobot dashboard tasks
```

## 자동 테스트 실행

### 방법 1: Bash 스크립트 (빠르고 직관적)

```bash
./scripts/test_dashboard.sh
```

**포함된 테스트:**
- Dashboard 구조 확인
- 예제 데이터 로드
- CLI 명령어 (show, tasks, questions, history)
- Worker 실행
- 스키마 검증 (Pydantic)
- Question 답변

### 방법 2: Python 스크립트 (상세하고 확장 가능)

```bash
python scripts/test_dashboard.py
```

**포함된 테스트:**
- Workspace 생성
- DashboardManager 로드/저장
- Task 추가
- 스키마 검증
- Worker - Question 생성
- Worker - History 이동
- 예제 데이터 검증

### 방법 3: Pytest (단위 테스트)

```bash
# 모든 테스트 실행
pytest tests/test_dashboard.py -v

# 특정 테스트만
pytest tests/test_dashboard.py::test_dashboard_manager_load -v

# Coverage와 함께
pytest tests/test_dashboard.py --cov=nanobot.dashboard --cov-report=html
```

### 스키마 검증

Pydantic으로 데이터 구조 검증:

```python
from nanobot.dashboard.schema import (
    validate_tasks_file,
    validate_questions_file,
    validate_history_file,
)

# JSON 파일 검증
with open("dashboard/tasks.json") as f:
    validated = validate_tasks_file(json.load(f))
    # ValidationError 발생 시 자동으로 상세 에러 표시
```

## 수동 테스트 체크리스트

### ✅ DashboardManager
- [ ] 빈 dashboard 로드 가능
- [ ] Task 추가 후 저장 가능
- [ ] 저장 후 재로드 시 데이터 유지

### ✅ WorkerAgent
- [ ] Task 진행률 체크
- [ ] Question 생성 (7가지 Case)
- [ ] Completed task → History 이동
- [ ] Active/Someday 재평가
- [ ] Question cooldown 동작

### ✅ CLI
- [ ] `dashboard show` 동작
- [ ] `dashboard tasks` 동작
- [ ] `dashboard questions` 동작
- [ ] `dashboard answer` 동작
- [ ] `dashboard history` 동작
- [ ] `dashboard worker` 동작

### ⏳ Agent 통합 (Phase 2)
- [ ] Agent가 메시지 받아서 Dashboard 업데이트
- [ ] Agent가 조용히 동작 (답장 안 함)
- [ ] Question Queue 기반 소통

## 문제 해결

### Dashboard가 비어있음

```bash
# 예제 데이터 다시 로드
python -c "
import json
from pathlib import Path

example = json.loads(Path('tests/fixtures/example_dashboard.json').read_text())
dashboard_path = Path.home() / '.nanobot' / 'workspace' / 'dashboard'

(dashboard_path / 'tasks.json').write_text(json.dumps({'version': '1.0', 'tasks': example['tasks']}, indent=2))
"
```

### Worker가 question을 생성 안 함

- Task의 deadline이 너무 먼가요? (7일 이상)
- Task progress가 예상대로인가요?
- Cooldown 때문일 수 있습니다. questions.json을 직접 확인하세요.

### JSON 파일이 깨짐

```bash
# 백업에서 복구
cp ~/.nanobot/workspace.backup/dashboard/* ~/.nanobot/workspace/dashboard/

# 또는 초기화
rm -rf ~/.nanobot/workspace/dashboard
nanobot onboard
```

## E2E 테스트 (Phase 3)

### 방법 1: E2E 테스트 스크립트

```bash
python scripts/test_agent_e2e.py
```

**포함된 테스트:**
- Agent 생성 및 실행
- Dashboard 업데이트 검증
- Tool call 확인
- 파일 저장 위치 확인

### 방법 2: 실제 Agent CLI 테스트

**1. 설정 확인:**
```bash
# config.json 확인
cat ~/.nanobot/config.json

# Gemini 3 Pro 설정 예시:
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

**2. Dashboard 초기화:**
```bash
nanobot onboard
```

**3. Agent 실행:**
```bash
nanobot agent -m "금요일까지 문서 정리해야 해"
```

**4. Dashboard 확인:**
```bash
# Tasks 확인
cat ~/.nanobot/workspace/dashboard/tasks.json

# Questions 확인
cat ~/.nanobot/workspace/dashboard/questions.json

# CLI로 확인
nanobot dashboard tasks
nanobot dashboard questions
```

### LLM 모델별 테스트 결과

**Gemini 3 Pro (gemini/gemini-3-pro-preview):** ✅ **추천!**
- Tool call 성공률: 100%
- Dashboard 업데이트: 정확함
- 경로 지침 준수: 완벽함
- 비용: 적정

**GPT-4o:** ⚠️
- Tool call 성공률: 불안정
- 지침을 읽지만 실행하지 않음
- "했다"고 말만 하는 경향

**권장:** Gemini 3 Pro 사용을 강력히 추천합니다.

---

## 문제 해결

### Agent가 Dashboard 업데이트를 안 함

**원인:** LLM이 tool call을 하지 않음

**해결:**
1. Gemini 3 Pro로 변경
2. DASHBOARD.md가 최신 버전인지 확인 (간소화된 버전)
3. LiteLLM 최신 버전 확인: `pip install --upgrade litellm`

### Tool call은 하지만 저장이 안 됨

**확인:**
```bash
# 로그 확인
nanobot agent -m "테스트" 2>&1 | grep "Executing tool"

# 파일 권한 확인
ls -la ~/.nanobot/workspace/dashboard/
```

---

**다음 단계**: Docker 테스트 (Phase 4)
