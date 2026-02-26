"""Unit tests for dashboard tools."""

import json
import pytest
from pathlib import Path
import tempfile
import shutil

from nanobot.agent.tools.dashboard import (
    CreateTaskTool,
    UpdateTaskTool,
    AnswerQuestionTool,
    CreateQuestionTool,
    SaveInsightTool,
    ArchiveTaskTool,
)


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for testing."""
    temp_dir = Path(tempfile.mkdtemp())
    dashboard_dir = temp_dir / "dashboard"
    dashboard_dir.mkdir(parents=True)
    knowledge_dir = dashboard_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)

    # Initialize empty dashboard files
    tasks_data = {"version": "1.0", "tasks": []}
    questions_data = {"version": "1.0", "questions": []}

    (dashboard_dir / "tasks.json").write_text(json.dumps(tasks_data, indent=2), encoding="utf-8")
    (dashboard_dir / "questions.json").write_text(
        json.dumps(questions_data, indent=2), encoding="utf-8"
    )

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.mark.asyncio
async def test_create_task_tool(temp_workspace):
    """Test CreateTaskTool creates valid task."""
    tool = CreateTaskTool(workspace=temp_workspace)

    result = await tool.execute(title="Test task", deadline="내일", priority="high", tags=["test"])

    # Should return success message
    assert "Created task_" in result

    # Verify task exists in dashboard
    tasks_path = temp_workspace / "dashboard" / "tasks.json"
    tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))

    assert len(tasks_data["tasks"]) == 1
    task = tasks_data["tasks"][0]
    assert task["title"] == "Test task"
    assert task["priority"] == "high"
    assert task["deadline_text"] == "내일"
    assert "test" in task["tags"]
    assert task["id"].startswith("task_")


@pytest.mark.asyncio
async def test_update_task_tool(temp_workspace):
    """Test UpdateTaskTool updates progress."""
    # Create a task first
    create_tool = CreateTaskTool(workspace=temp_workspace)
    result = await create_tool.execute(title="Test task", priority="medium")

    # Extract task_id from result
    task_id = result.split("Created ")[1].split(":")[0]

    # Update the task
    update_tool = UpdateTaskTool(workspace=temp_workspace)
    result = await update_tool.execute(
        task_id=task_id, progress=50, blocked=True, blocker_note="Hook 어려움"
    )

    assert f"Updated {task_id}" in result

    # Verify update
    tasks_path = temp_workspace / "dashboard" / "tasks.json"
    tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))

    task = tasks_data["tasks"][0]
    assert task["progress"]["percentage"] == 50
    assert task["progress"]["blocked"] is True
    assert task["progress"]["blocker_note"] == "Hook 어려움"


@pytest.mark.asyncio
async def test_answer_question_tool(temp_workspace):
    """Test AnswerQuestionTool marks question answered."""
    # Create a question first
    create_tool = CreateQuestionTool(workspace=temp_workspace)
    result = await create_tool.execute(question="어떤 자료로 공부해?", priority="medium")

    # Extract question_id
    question_id = result.split("Created ")[1].split(":")[0]

    # Answer the question
    answer_tool = AnswerQuestionTool(workspace=temp_workspace)
    result = await answer_tool.execute(question_id=question_id, answer="유튜브 강의")

    assert f"Answered {question_id}" in result

    # Verify answer
    questions_path = temp_workspace / "dashboard" / "questions.json"
    questions_data = json.loads(questions_path.read_text(encoding="utf-8"))

    question = questions_data["questions"][0]
    assert question["answered"] is True
    assert question["answer"] == "유튜브 강의"
    assert question["answered_at"] is not None


@pytest.mark.asyncio
async def test_create_question_tool(temp_workspace):
    """Test CreateQuestionTool creates valid question."""
    tool = CreateQuestionTool(workspace=temp_workspace)

    result = await tool.execute(
        question="진행 상황은?",
        priority="high",
        type="progress_check",
        related_task_id="task_123",
    )

    assert "Created q_" in result

    # Verify question
    questions_path = temp_workspace / "dashboard" / "questions.json"
    questions_data = json.loads(questions_path.read_text(encoding="utf-8"))

    assert len(questions_data["questions"]) == 1
    question = questions_data["questions"][0]
    assert question["question"] == "진행 상황은?"
    assert question["priority"] == "high"
    assert question["type"] == "progress_check"
    assert question["related_task_id"] == "task_123"


@pytest.mark.asyncio
async def test_save_insight_tool(temp_workspace):
    """Test SaveInsightTool saves insight."""
    tool = SaveInsightTool(workspace=temp_workspace)

    result = await tool.execute(
        content="React Hook은 함수형 컴포넌트에서 state를 사용할 수 있게 해준다",
        category="tech",
        title="React Hook 개념",
        tags=["react", "hook"],
    )

    assert "Saved insight_" in result

    # Verify insight
    insights_path = temp_workspace / "dashboard" / "knowledge" / "insights.json"
    insights_data = json.loads(insights_path.read_text(encoding="utf-8"))

    assert len(insights_data["insights"]) == 1
    insight = insights_data["insights"][0]
    assert insight["title"] == "React Hook 개념"
    assert insight["category"] == "tech"
    assert "react" in insight["tags"]


@pytest.mark.asyncio
async def test_archive_task_tool(temp_workspace):
    """Test ArchiveTaskTool archives completed task."""
    # Create a task first
    create_tool = CreateTaskTool(workspace=temp_workspace)
    result = await create_tool.execute(title="Completed task", priority="medium")

    # Extract task_id
    task_id = result.split("Created ")[1].split(":")[0]

    # Archive the task
    archive_tool = ArchiveTaskTool(workspace=temp_workspace)
    result = await archive_tool.execute(task_id=task_id, reflection="Task completed successfully")

    assert f"Archived {task_id}" in result

    # Verify task stays in tasks list with archived status
    tasks_path = temp_workspace / "dashboard" / "tasks.json"
    tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert len(tasks_data["tasks"]) == 1
    task = tasks_data["tasks"][0]
    assert task["id"] == task_id
    assert task["status"] == "archived"
    assert task["reflection"] == "Task completed successfully"
    assert task["progress"]["percentage"] == 100
    assert task["completed_at"] is not None


@pytest.mark.asyncio
async def test_json_structure_validation(temp_workspace):
    """Test that tools create correct JSON structure."""
    # Create multiple tasks
    tool = CreateTaskTool(workspace=temp_workspace)

    await tool.execute(title="Task 1", priority="high")
    await tool.execute(title="Task 2", priority="medium")
    await tool.execute(title="Task 3", priority="low")

    # Verify JSON structure
    tasks_path = temp_workspace / "dashboard" / "tasks.json"
    tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))

    # Must have version and tasks keys
    assert "version" in tasks_data
    assert "tasks" in tasks_data
    assert tasks_data["version"] == "1.0"
    assert isinstance(tasks_data["tasks"], list)
    assert len(tasks_data["tasks"]) == 3

    # Each task must have required fields
    for task in tasks_data["tasks"]:
        assert "id" in task
        assert "title" in task
        assert "created_at" in task
        assert "updated_at" in task
        assert "progress" in task
        assert "status" in task

    # links should not contain "people" field
    for task in tasks_data["tasks"]:
        assert "people" not in task.get("links", {}), (
            "links should not contain removed 'people' field"
        )


@pytest.mark.asyncio
async def test_archive_task_preserves_existing_reflection(temp_workspace):
    """Test ArchiveTaskTool preserves existing reflection when none provided."""
    create_tool = CreateTaskTool(workspace=temp_workspace)
    result = await create_tool.execute(title="Task with reflection", priority="medium")
    task_id = result.split("Created ")[1].split(":")[0]

    # Manually set reflection on the task
    tasks_path = temp_workspace / "dashboard" / "tasks.json"
    tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks_data["tasks"][0]["reflection"] = "Existing reflection"
    tasks_path.write_text(json.dumps(tasks_data, indent=2), encoding="utf-8")

    # Archive without providing reflection
    archive_tool = ArchiveTaskTool(workspace=temp_workspace)
    result = await archive_tool.execute(task_id=task_id)

    assert f"Archived {task_id}" in result

    # Existing reflection should be preserved
    tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert tasks_data["tasks"][0]["reflection"] == "Existing reflection"


@pytest.mark.asyncio
async def test_archive_task_missing_progress_key(temp_workspace):
    """Test ArchiveTaskTool handles task with no progress key."""
    # Create a task and remove progress key to simulate legacy data
    tasks_path = temp_workspace / "dashboard" / "tasks.json"
    tasks_data = {
        "version": "1.0",
        "tasks": [
            {
                "id": "task_legacy",
                "title": "Legacy task",
                "status": "completed",
                "priority": "medium",
                "context": "",
                "tags": [],
                "links": {"projects": [], "insights": [], "resources": []},
                "created_at": "2026-02-20T00:00:00",
                "updated_at": "2026-02-20T00:00:00",
                "completed_at": "2026-02-20T00:00:00",
                "reflection": "",
                # No "progress" key
            }
        ],
    }
    tasks_path.write_text(json.dumps(tasks_data, indent=2), encoding="utf-8")

    archive_tool = ArchiveTaskTool(workspace=temp_workspace)
    result = await archive_tool.execute(task_id="task_legacy", reflection="Done")

    assert "Archived task_legacy" in result

    tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))
    task = tasks_data["tasks"][0]
    assert task["status"] == "archived"
    assert task["progress"]["percentage"] == 100
    assert task["reflection"] == "Done"


@pytest.mark.asyncio
async def test_archive_task_not_found(temp_workspace):
    """Test ArchiveTaskTool with non-existent task ID."""
    archive_tool = ArchiveTaskTool(workspace=temp_workspace)
    result = await archive_tool.execute(task_id="task_nonexistent")

    assert "Error" in result
    assert "not found" in result
