"""Update question tool."""

from typing import Optional

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class UpdateQuestionTool(BaseDashboardTool):
    """Update an existing question in the queue."""

    @property
    def name(self) -> str:
        return "update_question"

    @property
    def description(self) -> str:
        return (
            "Update an existing question's priority, type, cooldown period, or context. "
            "Use this to adjust question importance or modify follow-up behavior."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "question_id": {
                    "type": "string",
                    "description": "ID of the question to update"
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "New priority level (optional)"
                },
                "type": {
                    "type": "string",
                    "enum": [
                        "info_gather",
                        "progress_check",
                        "deadline_check",
                        "start_check",
                        "blocker_check",
                        "status_check",
                        "completion_check",
                        "routine_check"
                    ],
                    "description": "New question type (optional)"
                },
                "cooldown_hours": {
                    "type": "integer",
                    "description": "New cooldown period in hours (optional)"
                },
                "context": {
                    "type": "string",
                    "description": "New or additional context (optional)"
                }
            },
            "required": ["question_id"]
        }

    @with_dashboard_lock
    async def execute(
        self,
        question_id: str,
        priority: Optional[str] = None,
        type: Optional[str] = None,
        cooldown_hours: Optional[int] = None,
        context: Optional[str] = None
    ) -> str:
        """Update a question."""
        try:
            # Load questions
            questions_data = await self._load_questions()
            questions_list = questions_data.get("questions", [])

            # Find question
            question, index = self._find_question(questions_list, question_id)
            if not question:
                return f"Error: Question '{question_id}' not found"

            # Check if already answered
            if question.get("answered"):
                return f"Warning: Question '{question_id}' is already answered. Consider removing instead."

            # Update fields
            updated_fields = []

            if priority is not None:
                old_priority = question.get("priority")
                question["priority"] = priority
                updated_fields.append(f"priority: {old_priority} → {priority}")

            if type is not None:
                old_type = question.get("type")
                question["type"] = type
                updated_fields.append(f"type: {old_type} → {type}")

            if cooldown_hours is not None:
                old_cooldown = question.get("cooldown_hours")
                question["cooldown_hours"] = cooldown_hours
                updated_fields.append(f"cooldown: {old_cooldown}h → {cooldown_hours}h")

            if context is not None:
                question["context"] = context
                updated_fields.append("context updated")

            if not updated_fields:
                return f"No fields to update for question '{question_id}'"

            # Save
            questions_list[index] = question
            questions_data["questions"] = questions_list

            success, msg = await self._validate_and_save_questions(questions_data)
            if not success:
                return msg

            updates = ", ".join(updated_fields)
            return f"✅ Question '{question_id}' updated: {updates}"

        except Exception as e:
            return f"Error updating question: {str(e)}"
