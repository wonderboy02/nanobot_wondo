"""Unit tests for question management tools."""

import json
import pytest
from pathlib import Path

from nanobot.agent.tools.dashboard.update_question import UpdateQuestionTool
from nanobot.agent.tools.dashboard.remove_question import RemoveQuestionTool


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace with dashboard structure."""
    dashboard_path = tmp_path / "dashboard"
    dashboard_path.mkdir(parents=True)

    # Initialize questions.json
    questions_file = dashboard_path / "questions.json"
    questions_file.write_text(json.dumps({"version": "1.0", "questions": []}), encoding="utf-8")

    return tmp_path


class TestUpdateQuestionTool:
    """Test update_question tool."""

    @pytest.mark.asyncio
    async def test_update_question_priority(self, temp_workspace):
        """Test updating question priority."""
        # Create existing question
        questions_file = temp_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Test question?",
                    "priority": "low",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": "2026-02-08T10:00:00",
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_001", priority="high")

        assert "✅" in result
        assert "priority: low → high" in result

        # Verify update
        data = json.loads(questions_file.read_text())
        question = data["questions"][0]
        assert question["priority"] == "high"

    @pytest.mark.asyncio
    async def test_update_question_type(self, temp_workspace):
        """Test updating question type."""
        questions_file = temp_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Test question?",
                    "priority": "medium",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": "2026-02-08T10:00:00",
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_001", type="progress_check")

        assert "✅" in result
        assert "type: info_gather → progress_check" in result

        data = json.loads(questions_file.read_text())
        question = data["questions"][0]
        assert question["type"] == "progress_check"

    @pytest.mark.asyncio
    async def test_update_question_cooldown(self, temp_workspace):
        """Test updating question cooldown period."""
        questions_file = temp_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Test question?",
                    "priority": "medium",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": "2026-02-08T10:00:00",
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_001", cooldown_hours=12)

        assert "✅" in result
        assert "cooldown: 24h → 12h" in result

        data = json.loads(questions_file.read_text())
        question = data["questions"][0]
        assert question["cooldown_hours"] == 12

    @pytest.mark.asyncio
    async def test_update_question_context(self, temp_workspace):
        """Test updating question context."""
        questions_file = temp_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Test question?",
                    "priority": "medium",
                    "type": "info_gather",
                    "context": "Old context",
                    "answered": False,
                    "created_at": "2026-02-08T10:00:00",
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_001", context="New context with additional info")

        assert "✅" in result
        assert "context updated" in result

        data = json.loads(questions_file.read_text())
        question = data["questions"][0]
        assert question["context"] == "New context with additional info"

    @pytest.mark.asyncio
    async def test_update_question_multiple_fields(self, temp_workspace):
        """Test updating multiple fields at once."""
        questions_file = temp_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Test question?",
                    "priority": "low",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": "2026-02-08T10:00:00",
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateQuestionTool(temp_workspace)

        result = await tool.execute(
            question_id="q_001", priority="high", type="progress_check", cooldown_hours=12
        )

        assert "✅" in result
        assert "priority: low → high" in result
        assert "type: info_gather → progress_check" in result
        assert "cooldown: 24h → 12h" in result

        data = json.loads(questions_file.read_text())
        question = data["questions"][0]
        assert question["priority"] == "high"
        assert question["type"] == "progress_check"
        assert question["cooldown_hours"] == 12

    @pytest.mark.asyncio
    async def test_update_question_not_found(self, temp_workspace):
        """Test updating non-existent question."""
        tool = UpdateQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_nonexistent", priority="high")

        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_update_question_already_answered(self, temp_workspace):
        """Test updating already answered question."""
        questions_file = temp_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Test question?",
                    "priority": "medium",
                    "type": "info_gather",
                    "answered": True,
                    "answer": "Test answer",
                    "answered_at": "2026-02-09T10:00:00",
                    "created_at": "2026-02-08T10:00:00",
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_001", priority="high")

        assert "Warning" in result
        assert "already answered" in result

    @pytest.mark.asyncio
    async def test_update_question_no_changes(self, temp_workspace):
        """Test updating question with no fields specified."""
        questions_file = temp_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Test question?",
                    "priority": "medium",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": "2026-02-08T10:00:00",
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data), encoding="utf-8")

        tool = UpdateQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_001")

        assert "No fields to update" in result


class TestRemoveQuestionTool:
    """Test remove_question tool."""

    @pytest.mark.asyncio
    async def test_remove_question(self, temp_workspace):
        """Test removing question."""
        questions_file = temp_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Test question?",
                    "priority": "medium",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": "2026-02-08T10:00:00",
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data), encoding="utf-8")

        tool = RemoveQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_001", reason="duplicate")

        assert "✅" in result
        assert "removed" in result
        assert "Test question?" in result
        assert "duplicate" in result

        # Verify question removed
        data = json.loads(questions_file.read_text())
        assert len(data["questions"]) == 0

    @pytest.mark.asyncio
    async def test_remove_question_from_multiple(self, temp_workspace):
        """Test removing one question from multiple."""
        questions_file = temp_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Question 1?",
                    "priority": "medium",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": "2026-02-08T10:00:00",
                    "cooldown_hours": 24,
                },
                {
                    "id": "q_002",
                    "question": "Question 2?",
                    "priority": "medium",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": "2026-02-08T11:00:00",
                    "cooldown_hours": 24,
                },
            ],
        }
        questions_file.write_text(json.dumps(data), encoding="utf-8")

        tool = RemoveQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_001")

        assert "✅" in result

        # Verify only q_001 removed
        data = json.loads(questions_file.read_text())
        assert len(data["questions"]) == 1
        assert data["questions"][0]["id"] == "q_002"

    @pytest.mark.asyncio
    async def test_remove_question_not_found(self, temp_workspace):
        """Test removing non-existent question."""
        tool = RemoveQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_nonexistent")

        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_remove_question_with_reason(self, temp_workspace):
        """Test removing question with specific reason."""
        questions_file = temp_workspace / "dashboard" / "questions.json"
        data = {
            "version": "1.0",
            "questions": [
                {
                    "id": "q_001",
                    "question": "Old question?",
                    "priority": "low",
                    "type": "info_gather",
                    "answered": False,
                    "created_at": "2026-01-01T10:00:00",
                    "cooldown_hours": 24,
                }
            ],
        }
        questions_file.write_text(json.dumps(data), encoding="utf-8")

        tool = RemoveQuestionTool(temp_workspace)

        result = await tool.execute(question_id="q_001", reason="obsolete - related task completed")

        assert "✅" in result
        assert "obsolete - related task completed" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
