"""Dashboard-specific tools for task and question management."""

from nanobot.agent.tools.dashboard.create_task import CreateTaskTool
from nanobot.agent.tools.dashboard.update_task import UpdateTaskTool
from nanobot.agent.tools.dashboard.answer_question import AnswerQuestionTool
from nanobot.agent.tools.dashboard.create_question import CreateQuestionTool
from nanobot.agent.tools.dashboard.update_question import UpdateQuestionTool
from nanobot.agent.tools.dashboard.remove_question import RemoveQuestionTool
from nanobot.agent.tools.dashboard.archive_task import ArchiveTaskTool
from nanobot.agent.tools.dashboard.save_insight import SaveInsightTool
from nanobot.agent.tools.dashboard.schedule_notification import ScheduleNotificationTool
from nanobot.agent.tools.dashboard.update_notification import UpdateNotificationTool
from nanobot.agent.tools.dashboard.cancel_notification import CancelNotificationTool
from nanobot.agent.tools.dashboard.list_notifications import ListNotificationsTool

__all__ = [
    "CreateTaskTool",
    "UpdateTaskTool",
    "AnswerQuestionTool",
    "CreateQuestionTool",
    "UpdateQuestionTool",
    "RemoveQuestionTool",
    "ArchiveTaskTool",
    "SaveInsightTool",
    "ScheduleNotificationTool",
    "UpdateNotificationTool",
    "CancelNotificationTool",
    "ListNotificationsTool",
]
