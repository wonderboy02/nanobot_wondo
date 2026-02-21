"""Remove question tool."""

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class RemoveQuestionTool(BaseDashboardTool):
    """Remove a question from the queue."""

    @property
    def name(self) -> str:
        return "remove_question"

    @property
    def description(self) -> str:
        return (
            "Remove a question from the queue. "
            "Use this when a question is no longer relevant, is a duplicate, "
            "or has been made obsolete by context changes."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "question_id": {
                    "type": "string",
                    "description": "ID of the question to remove"
                },
                "reason": {
                    "type": "string",
                    "default": "",
                    "description": "Optional reason for removal (e.g., 'duplicate', 'obsolete', 'answered elsewhere')"
                }
            },
            "required": ["question_id"]
        }

    @with_dashboard_lock
    async def execute(self, question_id: str, reason: str = "") -> str:
        """Remove a question."""
        try:
            # Load questions
            questions_data = await self._load_questions()
            questions_list = questions_data.get("questions", [])

            # Find question
            question, index = self._find_question(questions_list, question_id)
            if not question:
                return f"Error: Question '{question_id}' not found"

            # Store question info for logging
            question_text = question.get("question", "")

            # Remove question
            questions_list.pop(index)
            questions_data["questions"] = questions_list

            # Save
            success, msg = await self._validate_and_save_questions(questions_data)
            if not success:
                return msg

            result = [f"✅ Question '{question_id}' removed"]
            if question_text:
                result.append(f"Question was: {question_text}")
            if reason:
                result.append(f"Reason: {reason}")

            return "\n".join(result)

        except Exception as e:
            return f"Error removing question: {str(e)}"
