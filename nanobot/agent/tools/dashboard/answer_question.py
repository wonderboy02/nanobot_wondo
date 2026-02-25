"""Answer question tool."""

from typing import Any

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class AnswerQuestionTool(BaseDashboardTool):
    """Tool to answer a question in the question queue."""

    @property
    def name(self) -> str:
        return "answer_question"

    @property
    def description(self) -> str:
        return (
            "Answer a question in the question queue. "
            "Marks the question as answered with the provided answer and timestamp. "
            "Use this instead of write_file for answering questions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question_id": {
                    "type": "string",
                    "description": "Question ID (e.g., 'q_12345678')",
                },
                "answer": {"type": "string", "description": "The answer to the question"},
            },
            "required": ["question_id", "answer"],
        }

    @with_dashboard_lock
    async def execute(self, question_id: str, answer: str) -> str:
        try:
            # Load existing questions
            questions_data = await self._load_questions()

            # Find question
            question, index = self._find_question(questions_data["questions"], question_id)

            if question is None:
                return f"Error: Question {question_id} not found"

            # Mark as answered
            now = self._now()
            question["answered"] = True
            question["answer"] = answer
            question["answered_at"] = now

            # Replace question in list
            questions_data["questions"][index] = question

            # Validate and save
            success, message = await self._validate_and_save_questions(questions_data)

            if success:
                return f"Answered {question_id}"
            else:
                return message

        except Exception as e:
            return f"Error answering question: {str(e)}"
