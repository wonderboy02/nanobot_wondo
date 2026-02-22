"""Create question tool."""

from typing import Any

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class CreateQuestionTool(BaseDashboardTool):
    """Tool to create a new question in the question queue."""

    @property
    def name(self) -> str:
        return "create_question"

    @property
    def description(self) -> str:
        return (
            "Create a new question in the question queue. "
            "Use this to ask the user for more information about tasks or general questions. "
            "Automatically generates IDs and timestamps. "
            "Use this instead of write_file for creating questions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Question priority (default: medium)",
                },
                "type": {
                    "type": "string",
                    "description": "Question type (e.g., 'info_gather', 'progress_check', 'clarification')",
                },
                "related_task_id": {
                    "type": "string",
                    "description": "Related task ID if this question is about a specific task",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context for the question",
                },
            },
            "required": ["question"],
        }

    @with_dashboard_lock
    async def execute(
        self,
        question: str,
        priority: str = "medium",
        type: str = "info_gather",
        related_task_id: str | None = None,
        context: str = "",
        **kwargs: Any,
    ) -> str:
        try:
            # Load existing questions
            questions_data = await self._load_questions()

            # Generate new question
            question_id = self._generate_id("q")
            now = self._now()

            new_question = {
                "id": question_id,
                "question": question,
                "priority": priority,
                "type": type,
                "related_task_id": related_task_id,
                "context": context,
                "created_at": now,
                "asked_count": 0,
                "last_asked_at": None,
                "cooldown_hours": 24,
                "answered": False,
                "answer": None,
                "answered_at": None,
            }

            # Add to questions list
            questions_data["questions"].append(new_question)

            # Validate and save
            success, message = await self._validate_and_save_questions(questions_data)

            if success:
                return f"Created {question_id}: {question}"
            else:
                return message

        except Exception as e:
            return f"Error creating question: {str(e)}"
