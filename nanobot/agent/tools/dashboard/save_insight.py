"""Save insight tool."""

from typing import Any

from nanobot.agent.tools.dashboard.base import BaseDashboardTool, with_dashboard_lock


class SaveInsightTool(BaseDashboardTool):
    """Tool to save an insight or learning to the knowledge base."""

    @property
    def name(self) -> str:
        return "save_insight"

    @property
    def description(self) -> str:
        return (
            "Save an insight, learning, or knowledge to the knowledge base. "
            "Use this to store important information learned during conversations. "
            "Automatically generates IDs and timestamps."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The insight content",
                },
                "category": {
                    "type": "string",
                    "description": "Category (e.g., 'tech', 'life', 'work', 'learning')",
                },
                "title": {
                    "type": "string",
                    "description": "Optional title for the insight",
                },
                "source": {
                    "type": "string",
                    "description": "Source of the insight (e.g., 'conversation', 'task_123')",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization",
                },
            },
            "required": ["content"],
        }

    @with_dashboard_lock
    async def execute(
        self,
        content: str,
        category: str = "general",
        title: str = "",
        source: str = "",
        tags: list[str] | None = None,
    ) -> str:
        try:
            # Load existing insights via backend
            insights_data = await self._load_insights()

            # Generate new insight
            insight_id = self._generate_id("insight")
            now = self._now()

            new_insight = {
                "id": insight_id,
                "title": title or content[:50],
                "content": content,
                "category": category,
                "source": source,
                "tags": tags or [],
                "created_at": now,
                "updated_at": now,
            }

            # Add to insights list
            insights_data["insights"].append(new_insight)

            # Save via backend
            success, message = await self._validate_and_save_insights(insights_data)
            if not success:
                return message

            return f"Saved {insight_id}: {title or content[:50]}"

        except Exception as e:
            return f"Error saving insight: {str(e)}"
