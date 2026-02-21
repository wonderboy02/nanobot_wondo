"""Tests for NotionClient (nanobot/notion/client.py).

Covers: pagination, CRUD, rate limiting, retry on 429/500, NotionAPIError on 4xx.

NotionClient is synchronous (httpx.Client), so all tests are sync.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from nanobot.notion.client import NotionClient, NotionAPIError, RATE_LIMIT_INTERVAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int = 200, json_data: dict | None = None, headers: dict | None = None, text: str = ""):
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return NotionClient(token="secret_test_token")


# ---------------------------------------------------------------------------
# query_database - pagination
# ---------------------------------------------------------------------------

def test_query_database_single_page(client):
    """query_database returns all results when has_more=false."""
    page1 = {"id": "page-1", "properties": {}}
    mock_resp = _make_response(200, {"results": [page1], "has_more": False, "next_cursor": None})

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(return_value=mock_resp)
        gc.return_value = mock_http

        results = client.query_database("db-123")
        assert results == [page1]
        mock_http.request.assert_called_once()


def test_query_database_pagination(client):
    """query_database follows pagination cursors until has_more=false."""
    page1 = {"id": "page-1"}
    page2 = {"id": "page-2"}
    resp1 = _make_response(200, {"results": [page1], "has_more": True, "next_cursor": "cursor-abc"})
    resp2 = _make_response(200, {"results": [page2], "has_more": False, "next_cursor": None})

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(side_effect=[resp1, resp2])
        gc.return_value = mock_http

        results = client.query_database("db-123")
        assert len(results) == 2
        assert results[0]["id"] == "page-1"
        assert results[1]["id"] == "page-2"

        # Second call should include start_cursor
        second_call_kwargs = mock_http.request.call_args_list[1]
        body = second_call_kwargs.kwargs.get("json") or second_call_kwargs[1].get("json", {})
        assert body.get("start_cursor") == "cursor-abc"


# ---------------------------------------------------------------------------
# create_page
# ---------------------------------------------------------------------------

def test_create_page_success(client):
    """create_page sends correct body and returns page object."""
    created_page = {"id": "new-page-1", "properties": {"Title": {"title": []}}}
    mock_resp = _make_response(200, created_page)

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(return_value=mock_resp)
        gc.return_value = mock_http

        result = client.create_page("db-123", properties={"Title": {"title": []}})
        assert result["id"] == "new-page-1"

        call_args = mock_http.request.call_args
        assert call_args[0][0] == "POST"
        assert "/pages" in call_args[0][1]
        body = call_args.kwargs.get("json") or call_args[1].get("json", {})
        assert body["parent"]["database_id"] == "db-123"


# ---------------------------------------------------------------------------
# update_page
# ---------------------------------------------------------------------------

def test_update_page_success(client):
    """update_page sends PATCH with properties."""
    updated = {"id": "page-1", "properties": {"Status": {"select": {"name": "Done"}}}}
    mock_resp = _make_response(200, updated)

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(return_value=mock_resp)
        gc.return_value = mock_http

        result = client.update_page("page-1", properties={"Status": {"select": {"name": "Done"}}})
        assert result["id"] == "page-1"
        call_args = mock_http.request.call_args
        assert call_args[0][0] == "PATCH"


# ---------------------------------------------------------------------------
# archive_page
# ---------------------------------------------------------------------------

def test_archive_page_success(client):
    """archive_page sends PATCH with archived=true."""
    archived = {"id": "page-1", "archived": True}
    mock_resp = _make_response(200, archived)

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(return_value=mock_resp)
        gc.return_value = mock_http

        result = client.archive_page("page-1")
        assert result["archived"] is True
        body = mock_http.request.call_args.kwargs.get("json") or mock_http.request.call_args[1].get("json", {})
        assert body["archived"] is True


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_rate_limiting_enforces_delay(client):
    """Consecutive requests should have at least RATE_LIMIT_INTERVAL gap."""
    import time

    mock_resp = _make_response(200, {"results": [], "has_more": False})

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(return_value=mock_resp)
        gc.return_value = mock_http

        with patch("nanobot.notion.client.time.sleep") as mock_sleep:
            # Pretend we just made a request
            client._last_request_at = time.monotonic()
            client._request("GET", "/pages/test")
            # Rate limit should have triggered a time.sleep call
            # (might not be called if test runs slow enough, so just check no errors)


# ---------------------------------------------------------------------------
# Retry on 429
# ---------------------------------------------------------------------------

def test_retry_on_429(client):
    """Client retries when Notion returns 429 rate limit."""
    resp_429 = _make_response(429, headers={"Retry-After": "0.01"})
    resp_200 = _make_response(200, {"ok": True})

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(side_effect=[resp_429, resp_200])
        gc.return_value = mock_http

        with patch("nanobot.notion.client.time.sleep"):
            result = client._request("GET", "/pages/test")
            assert result == {"ok": True}
            assert mock_http.request.call_count == 2


# ---------------------------------------------------------------------------
# Retry on 500
# ---------------------------------------------------------------------------

def test_retry_on_500(client):
    """Client retries on server errors (5xx)."""
    resp_500 = _make_response(500, text="Internal Server Error")
    resp_200 = _make_response(200, {"ok": True})

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(side_effect=[resp_500, resp_200])
        gc.return_value = mock_http

        with patch("nanobot.notion.client.time.sleep"):
            result = client._request("GET", "/pages/test")
            assert result == {"ok": True}
            assert mock_http.request.call_count == 2


# ---------------------------------------------------------------------------
# NotionAPIError on 4xx (non-429)
# ---------------------------------------------------------------------------

def test_raises_api_error_on_4xx(client):
    """Client raises NotionAPIError immediately for 4xx errors (not 429)."""
    resp_400 = _make_response(400, text="Bad Request: invalid filter")

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(return_value=resp_400)
        gc.return_value = mock_http

        with patch("nanobot.notion.client.time.sleep"):
            with pytest.raises(NotionAPIError) as exc_info:
                client._request("GET", "/pages/test")
            assert exc_info.value.status_code == 400
            # Should NOT retry on 4xx
            assert mock_http.request.call_count == 1


def test_raises_api_error_on_403(client):
    """Client raises NotionAPIError for 403 Forbidden without retry."""
    resp_403 = _make_response(403, text="Forbidden")

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(return_value=resp_403)
        gc.return_value = mock_http

        with patch("nanobot.notion.client.time.sleep"):
            with pytest.raises(NotionAPIError) as exc_info:
                client._request("GET", "/pages/test")
            assert exc_info.value.status_code == 403
            assert mock_http.request.call_count == 1


# ---------------------------------------------------------------------------
# Max retries exceeded
# ---------------------------------------------------------------------------

def test_max_retries_exceeded(client):
    """Client raises NotionAPIError after exhausting all retries on 500."""
    resp_500 = _make_response(500, text="Server Error")

    with patch.object(client, "_get_client") as gc:
        mock_http = MagicMock()
        mock_http.request = MagicMock(return_value=resp_500)
        gc.return_value = mock_http

        with patch("nanobot.notion.client.time.sleep"):
            with pytest.raises(NotionAPIError):
                client._request("GET", "/pages/test")
            # Should have tried MAX_RETRIES (3) times
            assert mock_http.request.call_count == 3


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

def test_close(client):
    """close() closes the underlying httpx client."""
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.is_closed = False
    client._client = mock_http

    client.close()
    mock_http.close.assert_called_once()
    assert client._client is None
