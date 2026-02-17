"""Save insight tool."""

import json
from pathlib import Path
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
        **kwargs: Any,
    ) -> str:
        try:
            # Load existing insights
            insights_path = self.workspace / "dashboard" / "knowledge" / "insights.json"
            insights_path.parent.mkdir(parents=True, exist_ok=True)

            if insights_path.exists():
                insights_data = json.loads(insights_path.read_text(encoding="utf-8"))
            else:
                insights_data = {"version": "1.0", "insights": []}

            # Generate new insight
            insight_id = self._generate_id("insight")
            now = self._now()

            new_insight = {
                "id": insight_id,
                "title": title or content[:50],  # Use first 50 chars as title if not provided
                "content": content,
                "category": category,
                "source": source,
                "tags": tags or [],
                "created_at": now,
                "updated_at": now,
            }

            # Add to insights list
            insights_data["insights"].append(new_insight)

            # Save
            insights_path.write_text(
                json.dumps(insights_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            return f"Saved {insight_id}: {title or content[:50]}"

        except Exception as e:
            return f"Error saving insight: {str(e)}"
