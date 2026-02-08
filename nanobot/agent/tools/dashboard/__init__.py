"""Dashboard-specific tools for task and question management."""

from nanobot.agent.tools.dashboard.create_task import CreateTaskTool
from nanobot.agent.tools.dashboard.update_task import UpdateTaskTool
from nanobot.agent.tools.dashboard.answer_question import AnswerQuestionTool
from nanobot.agent.tools.dashboard.create_question import CreateQuestionTool
from nanobot.agent.tools.dashboard.save_insight import SaveInsightTool
from nanobot.agent.tools.dashboard.move_to_history import MoveToHistoryTool

__all__ = [
    "CreateTaskTool",
    "UpdateTaskTool",
    "AnswerQuestionTool",
    "CreateQuestionTool",
    "SaveInsightTool",
    "MoveToHistoryTool",
]
