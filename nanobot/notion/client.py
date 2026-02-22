"""Synchronous Notion API client with rate limiting and retry."""

import threading
import time
from typing import Any

import httpx
from loguru import logger

# Notion API base URL
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Rate limit: 3 requests per second
RATE_LIMIT_INTERVAL = 1.0 / 3.0

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0  # 1s, 2s, 4s


class NotionClient:
    """Synchronous Notion API wrapper with rate limiting and exponential backoff retry.

    DESIGN: Uses httpx.Client (sync) intentionally to avoid async/sync bridge issues
    (event loop cross-thread sharing). All callers use asyncio.to_thread() to dispatch
    sync I/O to the thread pool, keeping the event loop unblocked.
    See CLAUDE.md "Known Limitations #1" for async migration plan.

    Rate limiting uses time.sleep() which blocks the calling thread — safe because
    callers dispatch via asyncio.to_thread(), so only the worker thread sleeps.

    Usage:
        client = NotionClient(token="secret_xxx")
        pages = client.query_database("db_id", filter={...})
        page = client.create_page("db_id", properties={...})
        client.update_page("page_id", properties={...})
        client.archive_page("page_id")
    """

    def __init__(self, token: str, timeout: float = 30.0):
        self._token = token
        self._timeout = timeout
        self._last_request_at = 0.0
        self._rate_lock = threading.Lock()
        self._client: httpx.Client | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=NOTION_API_BASE,
                headers=self._headers,
                timeout=self._timeout,
            )
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()
            self._client = None

    def _rate_limit(self) -> None:
        """Enforce rate limit of 3 req/s."""
        with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if elapsed < RATE_LIMIT_INTERVAL:
                time.sleep(RATE_LIMIT_INTERVAL - elapsed)
            self._last_request_at = time.monotonic()

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
    ) -> dict[str, Any]:
        """Make an API request with rate limiting and retry."""
        client = self._get_client()

        for attempt in range(MAX_RETRIES):
            self._rate_limit()
            try:
                response = client.request(method, path, json=json_body)

                if response.is_success:  # 2xx (covers 200, 201, 204, etc.)
                    return response.json()

                if response.status_code == 429:
                    retry_after = float(
                        response.headers.get("Retry-After", RETRY_BACKOFF_BASE * (2 ** attempt))
                    )
                    logger.warning(f"Notion rate limited, retrying in {retry_after:.1f}s")
                    time.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        f"Notion server error {response.status_code}, retrying in {backoff:.1f}s"
                    )
                    time.sleep(backoff)
                    continue

                # Client error (4xx except 429) — don't retry
                error_body = response.text
                logger.error(f"Notion API error {response.status_code}: {error_body[:200]}")
                raise NotionAPIError(response.status_code, error_body)

            except httpx.TimeoutException:
                if attempt < MAX_RETRIES - 1:
                    backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(f"Notion request timeout, retrying in {backoff:.1f}s")
                    time.sleep(backoff)
                else:
                    raise NotionAPIError(0, "Request timed out after all retries")

            except httpx.HTTPError as e:
                if attempt < MAX_RETRIES - 1:
                    backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(f"Notion HTTP error: {e}, retrying in {backoff:.1f}s")
                    time.sleep(backoff)
                else:
                    raise NotionAPIError(0, f"HTTP error: {e}")

        raise NotionAPIError(0, "Max retries exceeded")

    def query_database(
        self,
        database_id: str,
        filter: dict | None = None,
        sorts: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """Query a Notion database with automatic pagination."""
        all_pages: list[dict] = []
        has_more = True
        start_cursor: str | None = None

        while has_more:
            body: dict[str, Any] = {}
            if filter:
                body["filter"] = filter
            if sorts:
                body["sorts"] = sorts
            if start_cursor:
                body["start_cursor"] = start_cursor

            result = self._request(
                "POST", f"/databases/{database_id}/query", json_body=body
            )

            all_pages.extend(result.get("results", []))
            has_more = result.get("has_more", False)
            start_cursor = result.get("next_cursor")

        return all_pages

    def create_page(
        self,
        database_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a page in a Notion database."""
        body = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        return self._request("POST", "/pages", json_body=body)

    def update_page(
        self,
        page_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a Notion page's properties."""
        body = {"properties": properties}
        return self._request("PATCH", f"/pages/{page_id}", json_body=body)

    def archive_page(self, page_id: str) -> dict[str, Any]:
        """Archive (soft-delete) a Notion page."""
        body = {"archived": True}
        return self._request("PATCH", f"/pages/{page_id}", json_body=body)



class NotionAPIError(Exception):
    """Notion API error with status code and response body."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Notion API error ({status_code}): {message}")
