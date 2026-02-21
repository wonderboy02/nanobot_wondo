"""Notion-specific storage backend and caching utilities.

- MemoryCache: TTL-based in-memory cache for Notion reads.
- NotionStorageBackend: Notion API storage with cache + ID mapping.

The StorageBackend ABC and JsonStorageBackend live in nanobot.dashboard.storage.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from loguru import logger

from nanobot.dashboard.storage import StorageBackend


# ============================================================================
# Memory Cache
# ============================================================================

class MemoryCache:
    """Simple TTL-based in-memory cache using a dict.

    NOT thread-safe — caller must hold a lock when accessing from multiple
    threads. In this codebase, NotionStorageBackend._lock guards all access.

    Usage:
        cache = MemoryCache(ttl_s=300)
        cache.set("tasks", data)
        result = cache.get("tasks")  # Returns data or None if expired
        cache.invalidate("tasks")     # Invalidate on write
        cache.invalidate_all()        # Invalidate all (e.g., on message start)
    """

    def __init__(self, ttl_s: int = 300):
        self._ttl_s = ttl_s
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        """Get cached value if not expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        data, cached_at = entry
        if time.monotonic() - cached_at > self._ttl_s:
            del self._store[key]
            return None
        return data

    def set(self, key: str, data: Any) -> None:
        """Cache a value with current timestamp."""
        self._store[key] = (data, time.monotonic())

    def invalidate(self, key: str) -> None:
        """Invalidate a specific cache entry."""
        self._store.pop(key, None)

    def invalidate_all(self) -> None:
        """Invalidate all cache entries."""
        self._store.clear()


# ============================================================================
# Notion Storage Backend
# ============================================================================

class NotionStorageBackend(StorageBackend):
    """Notion API-based storage with in-memory cache.

    Notion is the single source of truth:
    - Write: Tool → Notion API → cache invalidate
    - Read: cache hit → return / miss → Notion query → cache set → return
    - User edits in Notion are picked up on next cache miss

    The nanobot_id ↔ notion_page_id mapping is built on first query
    per entity type and kept in memory.
    """

    def __init__(
        self,
        client,
        databases,
        cache_ttl_s: int = 300,
    ):
        self._client = client
        self._dbs = databases
        self._cache = MemoryCache(ttl_s=cache_ttl_s)

        # nanobot_id → notion_page_id mapping per entity type
        self._id_maps: dict[str, dict[str, str]] = {}

        # Thread safety: asyncio.to_thread() dispatches to a thread pool,
        # while other paths (context builder, telegram handlers) may call
        # backend methods directly from the main thread.
        self._lock = threading.Lock()

    def close(self) -> None:
        """Close the underlying Notion HTTP client."""
        if self._client:
            self._client.close()

    def invalidate_cache(self) -> None:
        """Force-invalidate all caches and ID maps.

        Call at the start of message processing and worker cycles
        so that user edits in Notion are picked up.
        Clearing _id_maps forces a rebuild on next load, picking up
        items the user added directly in Notion UI.
        """
        with self._lock:
            self._cache.invalidate_all()
            self._id_maps.clear()

    # ---- helpers ----

    def _build_id_map(self, entity_type: str, pages: list[dict]) -> dict[str, str]:
        """Build nanobot_id → notion_page_id mapping from query results."""
        from nanobot.notion.mapper import _extract_rich_text, _get_prop

        id_map: dict[str, str] = {}
        for page in pages:
            props = page.get("properties", {})
            nanobot_id = _extract_rich_text(_get_prop(props, "NanobotID"))
            if nanobot_id:
                id_map[nanobot_id] = page["id"]
        self._id_maps[entity_type] = id_map
        return id_map

    def _get_page_id(self, entity_type: str, nanobot_id: str) -> str | None:
        """Look up Notion page ID for a given nanobot ID."""
        id_map = self._id_maps.get(entity_type, {})
        return id_map.get(nanobot_id)

    # ---- Generic load/save ----

    def _load_entity(
        self,
        entity_type: str,
        db_id: str,
        converter,
        list_key: str,
        default_data: dict,
    ) -> dict:
        """Generic load: cache → Notion query → convert → cache.

        DESIGN: Returns default_data when db_id is empty (partial Notion config).
        Only tasks/questions DB IDs are required at startup (loop.py validates).
        Other DBs (notifications, insights) are optional —
        reads return empty, writes return error message. This allows users to
        start with just tasks+questions and add more DBs later.
        """
        if not db_id:
            return default_data

        with self._lock:
            cached = self._cache.get(entity_type)
            if cached is not None:
                return cached

            try:
                pages = self._client.query_database(db_id)
                self._build_id_map(entity_type, pages)

                items = [converter(page) for page in pages if not page.get("archived")]
                result = {"version": "1.0", list_key: items}
                self._cache.set(entity_type, result)
                return result

            except Exception as e:
                logger.error(f"Notion load {entity_type} failed: {e}")
                # DESIGN: Returns default_data on Notion failure (intentional resilience).
                # Dashboard summary and context building must not crash the agent.
                # Trade-off: temporary outage shows "empty" state to agent.
                # Mitigated by: clearing stale id_map prevents mass-archiving on next save,
                # and cache invalidation at message start ensures retry on next request.
                self._id_maps.pop(entity_type, None)
                return default_data

    def _save_entity_items(
        self,
        entity_type: str,
        db_id: str,
        items: list[dict],
        to_notion_fn,
    ) -> tuple[bool, str]:
        """Generic save: create/update/archive items in Notion → invalidate cache.

        Items present in the list are created or updated.
        Items that exist in Notion (id_map) but are missing from the list
        are archived (soft-deleted) so that deletions propagate correctly.

        DESIGN: Lock held during network I/O (intentional for single-user).
        With asyncio.to_thread(), at most 2-3 concurrent callers exist
        (message processing + heartbeat worker). The ~6s worst case for 20 items
        is acceptable vs. the complexity of lock-scope narrowing (split read/write
        phases would risk id_map races). Revisit if multi-user support is added.
        """
        if not db_id:
            return (False, f"No Notion database configured for {entity_type}")

        with self._lock:
            try:
                id_map = self._id_maps.get(entity_type, {})
                incoming_ids = {item.get("id", "") for item in items if item.get("id")}

                # DESIGN: Order matters — create/update first, archive last.
                # If create fails mid-batch, existing items are preserved in Notion.
                # Archive only runs if all creates/updates succeed (no partial deletion).
                for item in items:
                    nanobot_id = item.get("id", "")
                    # DESIGN: Skip items without NanobotID to prevent duplicate creation.
                    # Schema allows empty string IDs (auto-generated on create), but Notion
                    # save requires a stable ID for idempotent upsert. Caller is responsible
                    # for assigning IDs before save; skipped items are logged as warnings.
                    if not nanobot_id:
                        logger.warning(f"Skipping {entity_type} item with empty NanobotID")
                        continue
                    notion_props = to_notion_fn(item)
                    existing_page_id = id_map.get(nanobot_id)

                    if existing_page_id:
                        self._client.update_page(existing_page_id, notion_props)
                    else:
                        result = self._client.create_page(db_id, notion_props)
                        if result.get("id"):
                            id_map[nanobot_id] = result["id"]

                # Archive items removed from the list
                for nanobot_id, page_id in list(id_map.items()):
                    if nanobot_id not in incoming_ids:
                        self._client.archive_page(page_id)
                        del id_map[nanobot_id]

                self._id_maps[entity_type] = id_map
                self._cache.invalidate(entity_type)
                return (True, f"{entity_type} saved to Notion")

            except Exception as e:
                self._cache.invalidate(entity_type)
                logger.error(f"Notion save {entity_type} failed: {e}")
                return (False, f"Notion error: {e}")

    # ---- Tasks ----

    def load_tasks(self) -> dict:
        from nanobot.notion.mapper import notion_to_task
        return self._load_entity(
            "tasks", self._dbs.tasks, notion_to_task, "tasks",
            {"version": "1.0", "tasks": []},
        )

    def save_tasks(self, data: dict) -> tuple[bool, str]:
        try:
            from nanobot.dashboard.schema import validate_tasks_file
            validate_tasks_file(data)
        except Exception as e:
            return (False, f"Validation error: {e}")
        from nanobot.notion.mapper import task_to_notion
        tasks = data.get("tasks", [])
        return self._save_entity_items("tasks", self._dbs.tasks, tasks, task_to_notion)

    # ---- Questions ----

    def load_questions(self) -> dict:
        from nanobot.notion.mapper import notion_to_question
        return self._load_entity(
            "questions", self._dbs.questions, notion_to_question, "questions",
            {"version": "1.0", "questions": []},
        )

    def save_questions(self, data: dict) -> tuple[bool, str]:
        try:
            from nanobot.dashboard.schema import validate_questions_file
            validate_questions_file(data)
        except Exception as e:
            return (False, f"Validation error: {e}")
        from nanobot.notion.mapper import question_to_notion
        questions = data.get("questions", [])
        return self._save_entity_items(
            "questions", self._dbs.questions, questions, question_to_notion
        )

    # ---- Notifications ----

    def load_notifications(self) -> dict:
        from nanobot.notion.mapper import notion_to_notification
        return self._load_entity(
            "notifications", self._dbs.notifications, notion_to_notification,
            "notifications", {"version": "1.0", "notifications": []},
        )

    def save_notifications(self, data: dict) -> tuple[bool, str]:
        try:
            from nanobot.dashboard.schema import validate_notifications_file
            validate_notifications_file(data)
        except Exception as e:
            return (False, f"Validation error: {e}")
        from nanobot.notion.mapper import notification_to_notion
        notifications = data.get("notifications", [])
        return self._save_entity_items(
            "notifications", self._dbs.notifications, notifications,
            notification_to_notion,
        )

    # ---- Insights ----

    def load_insights(self) -> dict:
        from nanobot.notion.mapper import notion_to_insight
        return self._load_entity(
            "insights", self._dbs.insights, notion_to_insight, "insights",
            {"version": "1.0", "insights": []},
        )

    def save_insights(self, data: dict) -> tuple[bool, str]:
        from nanobot.notion.mapper import insight_to_notion
        insights = data.get("insights", [])
        return self._save_entity_items(
            "insights", self._dbs.insights, insights, insight_to_notion
        )

