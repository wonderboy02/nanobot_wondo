"""Tests for LiteLLMProvider fallback model chain."""

from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


@pytest.fixture
def provider():
    """Provider with two fallback models."""
    return LiteLLMProvider(
        api_key="test-key",
        default_model="gemini/gemini-2.0-flash-exp",
        fallback_models=["gemini/gemini-2.0-flash", "deepseek/deepseek-chat"],
    )


@pytest.fixture
def provider_no_fallback():
    """Provider without fallback models (original behaviour)."""
    return LiteLLMProvider(api_key="test-key", default_model="gemini/gemini-2.0-flash-exp")


# ------------------------------------------------------------------
# _resolve_model
# ------------------------------------------------------------------


class TestResolveModel:
    def test_gemini_prefix_added(self, provider):
        assert provider._resolve_model("gemini-2.0-flash") == "gemini/gemini-2.0-flash"

    def test_gemini_prefix_not_duplicated(self, provider):
        assert provider._resolve_model("gemini/gemini-2.0-flash") == "gemini/gemini-2.0-flash"

    def test_openrouter_prefix_skipped_for_fallback(self):
        p = LiteLLMProvider(api_key="sk-or-test", default_model="anthropic/claude-opus-4-5")
        assert p.is_openrouter
        # Primary: prefix applied
        assert p._resolve_model("some-model", is_fallback=False).startswith("openrouter/")
        # Fallback: prefix skipped
        assert not p._resolve_model("gemini/gemini-2.0-flash", is_fallback=True).startswith(
            "openrouter/"
        )

    def test_vllm_prefix_skipped_for_fallback(self):
        p = LiteLLMProvider(
            api_key="test", api_base="http://localhost:8000", default_model="my-model"
        )
        assert p.is_vllm
        assert p._resolve_model("my-model", is_fallback=False).startswith("hosted_vllm/")
        assert not p._resolve_model("gemini/gemini-2.0-flash", is_fallback=True).startswith(
            "hosted_vllm/"
        )

    def test_deepseek_passthrough(self, provider):
        """deepseek/deepseek-chat has no special prefix rule — passed through."""
        assert provider._resolve_model("deepseek/deepseek-chat") == "deepseek/deepseek-chat"


# ------------------------------------------------------------------
# chat() fallback behaviour
# ------------------------------------------------------------------


def _fake_response(content="ok"):
    """Build a minimal mock response matching acompletion's return shape."""
    msg = AsyncMock()
    msg.content = content
    msg.tool_calls = None
    choice = AsyncMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = AsyncMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


class TestChatFallback:
    @pytest.mark.asyncio
    async def test_primary_succeeds_no_fallback_attempted(self, provider):
        with patch("nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock) as m:
            m.return_value = _fake_response("hello")
            result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

        assert result.content == "hello"
        assert result.finish_reason == "stop"
        # Only one call (primary model)
        assert m.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self, provider):
        with patch("nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock) as m:
            m.side_effect = [
                Exception("503 UNAVAILABLE"),
                _fake_response("from fallback"),
            ]
            result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

        assert result.content == "from fallback"
        assert result.finish_reason == "stop"
        assert m.call_count == 2

    @pytest.mark.asyncio
    async def test_second_fallback_on_two_failures(self, provider):
        with patch("nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock) as m:
            m.side_effect = [
                Exception("503"),
                Exception("429 rate limit"),
                _fake_response("third try"),
            ]
            result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

        assert result.content == "third try"
        assert m.call_count == 3

    @pytest.mark.asyncio
    async def test_all_models_fail_returns_error(self, provider):
        with patch("nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock) as m:
            m.side_effect = Exception("all down")
            result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

        assert result.finish_reason == "error"
        assert "all down" in result.content
        # primary + 2 fallbacks = 3
        assert m.call_count == 3

    @pytest.mark.asyncio
    async def test_no_fallback_models_single_attempt(self, provider_no_fallback):
        with patch("nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock) as m:
            m.side_effect = Exception("503 UNAVAILABLE")
            result = await provider_no_fallback.chat(messages=[{"role": "user", "content": "hi"}])

        assert result.finish_reason == "error"
        assert m.call_count == 1

    @pytest.mark.asyncio
    async def test_fallback_uses_correct_model_names(self, provider):
        """Verify each attempt passes the correctly resolved model name."""
        models_called = []

        async def track_model(**kwargs):
            models_called.append(kwargs["model"])
            if len(models_called) < 3:
                raise Exception("fail")
            return _fake_response("ok")

        with patch("nanobot.providers.litellm_provider.acompletion", side_effect=track_model):
            await provider.chat(messages=[{"role": "user", "content": "hi"}])

        assert models_called == [
            "gemini/gemini-2.0-flash-exp",
            "gemini/gemini-2.0-flash",
            "deepseek/deepseek-chat",
        ]

    @pytest.mark.asyncio
    async def test_api_base_not_passed_for_fallback(self):
        """api_base should only be sent for the primary model (custom endpoint)."""
        p = LiteLLMProvider(
            api_key="test",
            api_base="http://localhost:8000",
            default_model="my-model",
            fallback_models=["gemini/gemini-2.0-flash"],
        )
        calls_kwargs = []

        async def track(**kwargs):
            calls_kwargs.append(kwargs)
            if len(calls_kwargs) < 2:
                raise Exception("fail")
            return _fake_response("ok")

        with patch("nanobot.providers.litellm_provider.acompletion", side_effect=track):
            await p.chat(messages=[{"role": "user", "content": "hi"}])

        # Primary call should include api_base
        assert "api_base" in calls_kwargs[0]
        # Fallback call should NOT include api_base
        assert "api_base" not in calls_kwargs[1]


# ------------------------------------------------------------------
# extra_provider_keys
# ------------------------------------------------------------------


class TestExtraProviderKeys:
    def test_sets_env_vars(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        LiteLLMProvider(
            api_key="test",
            default_model="gemini/gemini-2.0-flash",
            extra_provider_keys={"deepseek": "dk-123", "groq": "gk-456"},
        )

        import os

        assert os.environ["DEEPSEEK_API_KEY"] == "dk-123"
        assert os.environ["GROQ_API_KEY"] == "gk-456"

    def test_does_not_overwrite_existing(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "existing")

        LiteLLMProvider(
            api_key="test",
            default_model="gemini/gemini-2.0-flash",
            extra_provider_keys={"deepseek": "dk-new"},
        )

        import os

        assert os.environ["DEEPSEEK_API_KEY"] == "existing"


# ------------------------------------------------------------------
# dedup: primary == fallback should not retry same model
# ------------------------------------------------------------------


class TestFallbackDedup:
    @pytest.mark.asyncio
    async def test_duplicate_fallback_is_skipped(self):
        """If primary model appears in fallback_models, it should only be tried once."""
        p = LiteLLMProvider(
            api_key="test-key",
            default_model="gemini/gemini-2.0-flash",
            fallback_models=["gemini/gemini-2.0-flash", "deepseek/deepseek-chat"],
        )
        with patch("nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock) as m:
            m.side_effect = Exception("fail")
            await p.chat(messages=[{"role": "user", "content": "hi"}])

        # gemini-2.0-flash (deduped) + deepseek = 2, not 3
        assert m.call_count == 2

    def test_empty_strings_filtered_from_fallback(self):
        """Empty or whitespace-only fallback entries are silently dropped."""
        p = LiteLLMProvider(
            api_key="test-key",
            default_model="gemini/gemini-2.0-flash",
            fallback_models=["", "  ", "deepseek/deepseek-chat"],
        )
        assert p.fallback_models == ["deepseek/deepseek-chat"]
