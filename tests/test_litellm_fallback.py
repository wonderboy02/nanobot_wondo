"""Tests for LiteLLM provider key rotation and fallback behavior."""

from unittest.mock import AsyncMock, patch

import pytest

from nanobot.config.schema import ProviderConfig
from nanobot.providers.litellm_provider import LiteLLMProvider


# ---------------------------------------------------------------------------
# ProviderConfig.effective_keys
# ---------------------------------------------------------------------------


class TestEffectiveKeys:
    def test_both_api_keys_and_api_key(self):
        """api_keys first, api_key appended as last fallback."""
        config = ProviderConfig(api_key="paid", api_keys=["free1", "free2"])
        assert config.effective_keys == ["free1", "free2", "paid"]

    def test_api_key_only(self):
        """Backward compat: only api_key set."""
        config = ProviderConfig(api_key="single")
        assert config.effective_keys == ["single"]

    def test_api_keys_only(self):
        """Only api_keys, no api_key."""
        config = ProviderConfig(api_keys=["k1", "k2"])
        assert config.effective_keys == ["k1", "k2"]

    def test_empty(self):
        """No keys at all."""
        config = ProviderConfig()
        assert config.effective_keys == []

    def test_dedup(self):
        """api_key already in api_keys is not duplicated."""
        config = ProviderConfig(api_key="k1", api_keys=["k1", "k2"])
        assert config.effective_keys == ["k1", "k2"]

    def test_empty_strings_filtered(self):
        """Empty strings in api_keys are filtered out."""
        config = ProviderConfig(api_keys=["", "k1", ""])
        assert config.effective_keys == ["k1"]


# ---------------------------------------------------------------------------
# LiteLLMProvider._get_keys_for_model
# ---------------------------------------------------------------------------


class TestGetKeysForModel:
    def test_multiple_keys_for_matching_provider(self):
        provider = LiteLLMProvider(extra_provider_keys={"gemini": ["free1", "free2", "paid"]})
        keys, keyword = provider._get_keys_for_model("gemini/gemini-2.0-flash")
        assert keys == ["free1", "free2", "paid"]
        assert keyword == "gemini"

    def test_single_key_returns_none(self):
        """Single key provider should use env var (returns [None], None)."""
        provider = LiteLLMProvider(extra_provider_keys={"gemini": ["only-key"]})
        keys, keyword = provider._get_keys_for_model("gemini/gemini-2.0-flash")
        assert keys == [None]
        assert keyword is None

    def test_no_match_returns_none(self):
        provider = LiteLLMProvider(extra_provider_keys={"gemini": ["k1", "k2"]})
        keys, keyword = provider._get_keys_for_model("anthropic/claude-sonnet")
        assert keys == [None]
        assert keyword is None

    def test_no_extra_keys_returns_none(self):
        provider = LiteLLMProvider()
        keys, keyword = provider._get_keys_for_model("gemini/gemini-2.0-flash")
        assert keys == [None]
        assert keyword is None


# ---------------------------------------------------------------------------
# Key rotation in chat()
# ---------------------------------------------------------------------------


def _make_mock_response(content="ok"):
    """Create a mock LiteLLM response."""
    choice = type(
        "Choice",
        (),
        {
            "message": type("Msg", (), {"content": content, "tool_calls": None})(),
            "finish_reason": "stop",
        },
    )()
    usage = type(
        "Usage",
        (),
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    )()
    return type("Response", (), {"choices": [choice], "usage": usage})()


class TestKeyRotation:
    @pytest.mark.asyncio
    async def test_first_key_succeeds(self):
        """No rotation needed when first key works."""
        provider = LiteLLMProvider(extra_provider_keys={"gemini": ["free1", "free2", "paid"]})

        with patch(
            "nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock
        ) as mock:
            mock.return_value = _make_mock_response()
            result = await provider.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="gemini/gemini-2.0-flash",
            )

        assert result.content == "ok"
        assert mock.call_count == 1
        # First key should be used with num_retries=0 (not last key)
        call_kwargs = mock.call_args.kwargs
        assert call_kwargs["api_key"] == "free1"
        assert call_kwargs["num_retries"] == 0

    @pytest.mark.asyncio
    async def test_rotate_on_rate_limit(self):
        """Rate limit on free key rotates to next key."""
        import litellm.exceptions

        provider = LiteLLMProvider(extra_provider_keys={"gemini": ["free1", "free2", "paid"]})

        rate_limit_err = litellm.exceptions.RateLimitError(
            message="Rate limit exceeded",
            model="gemini/gemini-2.0-flash",
            llm_provider="gemini",
        )

        with patch(
            "nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock
        ) as mock:
            mock.side_effect = [rate_limit_err, _make_mock_response()]
            result = await provider.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="gemini/gemini-2.0-flash",
            )

        assert result.content == "ok"
        assert mock.call_count == 2
        # First call: free1 (num_retries=0), second call: free2 (num_retries=0)
        assert mock.call_args_list[0].kwargs["api_key"] == "free1"
        assert mock.call_args_list[0].kwargs["num_retries"] == 0
        assert mock.call_args_list[1].kwargs["api_key"] == "free2"
        assert mock.call_args_list[1].kwargs["num_retries"] == 0

    @pytest.mark.asyncio
    async def test_last_key_has_retries(self):
        """Last key (paid) uses full num_retries."""
        import litellm.exceptions

        provider = LiteLLMProvider(extra_provider_keys={"gemini": ["free1", "paid"]})

        rate_limit_err = litellm.exceptions.RateLimitError(
            message="Rate limit exceeded",
            model="gemini/gemini-2.0-flash",
            llm_provider="gemini",
        )

        with patch(
            "nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock
        ) as mock:
            mock.side_effect = [rate_limit_err, _make_mock_response()]
            result = await provider.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="gemini/gemini-2.0-flash",
            )

        assert result.content == "ok"
        assert mock.call_count == 2
        # Last key should have num_retries=3 (default)
        assert mock.call_args_list[1].kwargs["api_key"] == "paid"
        assert mock.call_args_list[1].kwargs["num_retries"] == 3

    @pytest.mark.asyncio
    async def test_all_keys_exhausted_falls_to_next_model(self):
        """All keys rate limited -> try fallback model."""
        import litellm.exceptions

        provider = LiteLLMProvider(
            fallback_models=["anthropic/claude-sonnet"],
            extra_provider_keys={"gemini": ["free1", "paid"]},
        )

        rate_limit_err = litellm.exceptions.RateLimitError(
            message="Rate limit exceeded",
            model="gemini/gemini-2.0-flash",
            llm_provider="gemini",
        )

        with patch(
            "nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock
        ) as mock:
            mock.side_effect = [rate_limit_err, rate_limit_err, _make_mock_response()]
            result = await provider.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="gemini/gemini-2.0-flash",
            )

        assert result.content == "ok"
        assert mock.call_count == 3
        # Third call should be fallback model (no api_key since anthropic has no rotation keys)
        assert "api_key" not in mock.call_args_list[2].kwargs

    @pytest.mark.asyncio
    async def test_non_rate_limit_error_skips_rotation(self):
        """Non-rate-limit errors skip key rotation, go to next model."""
        provider = LiteLLMProvider(
            fallback_models=["anthropic/claude-sonnet"],
            extra_provider_keys={"gemini": ["free1", "free2", "paid"]},
        )

        with patch(
            "nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock
        ) as mock:
            mock.side_effect = [ValueError("bad request"), _make_mock_response()]
            result = await provider.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="gemini/gemini-2.0-flash",
            )

        assert result.content == "ok"
        assert mock.call_count == 2
        # Should skip free2 and paid, go directly to fallback model

    @pytest.mark.asyncio
    async def test_no_rotation_keys_uses_env_var(self):
        """Without rotation keys, existing behavior is preserved (no api_key param)."""
        provider = LiteLLMProvider()

        with patch(
            "nanobot.providers.litellm_provider.acompletion", new_callable=AsyncMock
        ) as mock:
            mock.return_value = _make_mock_response()
            result = await provider.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="gemini/gemini-2.0-flash",
            )

        assert result.content == "ok"
        # No api_key should be in kwargs (uses env var)
        assert "api_key" not in mock.call_args.kwargs
