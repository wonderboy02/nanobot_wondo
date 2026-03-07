"""LiteLLM provider implementation for multi-provider support."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.providers.stats import ApiKeyStats

import litellm
from litellm import acompletion
from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

# Maps provider keywords to environment variable names for API keys.
_PROVIDER_ENV_MAP: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "zhipu": "ZHIPUAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
}


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.

    Supports OpenRouter, Anthropic, OpenAI, Gemini, and many other providers through
    a unified interface.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        num_retries: int = 3,
        fallback_models: list[str] | None = None,
        extra_provider_keys: dict[str, list[str]] | None = None,
        api_key_stats: ApiKeyStats | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.num_retries = num_retries
        self.fallback_models = fallback_models or []
        self._api_key_stats = api_key_stats

        # Store provider key lists for key rotation (keyword -> [key1, key2, ...])
        self._provider_keys: dict[str, list[str]] = extra_provider_keys or {}

        # Detect OpenRouter by api_key prefix or explicit api_base
        self.is_openrouter = (api_key and api_key.startswith("sk-or-")) or (
            api_base and "openrouter" in api_base
        )

        # Track if using custom endpoint (vLLM, etc.)
        self.is_vllm = bool(api_base) and not self.is_openrouter

        # Configure LiteLLM based on provider
        if api_key:
            if self.is_openrouter:
                # OpenRouter mode - set key
                os.environ["OPENROUTER_API_KEY"] = api_key
            elif self.is_vllm:
                # vLLM/custom endpoint - uses OpenAI-compatible API
                os.environ["OPENAI_API_KEY"] = api_key
            elif "deepseek" in default_model:
                os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
            elif "anthropic" in default_model:
                os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
            elif "openai" in default_model or "gpt" in default_model:
                os.environ.setdefault("OPENAI_API_KEY", api_key)
            elif "gemini" in default_model.lower():
                os.environ.setdefault("GEMINI_API_KEY", api_key)
            elif "zhipu" in default_model or "glm" in default_model or "zai" in default_model:
                os.environ.setdefault("ZHIPUAI_API_KEY", api_key)
            elif "groq" in default_model:
                os.environ.setdefault("GROQ_API_KEY", api_key)
            elif "moonshot" in default_model or "kimi" in default_model:
                os.environ.setdefault("MOONSHOT_API_KEY", api_key)
                os.environ.setdefault("MOONSHOT_API_BASE", api_base or "https://api.moonshot.cn/v1")

        # Set env vars for extra providers (needed for fallback models)
        # Use first key from each provider list for env var (enables single-key fallback)
        if self._provider_keys:
            for keyword, keys in self._provider_keys.items():
                env_var = _PROVIDER_ENV_MAP.get(keyword)
                first_key = keys[0] if keys else None
                if env_var and first_key:
                    os.environ.setdefault(env_var, first_key)

        if api_base:
            litellm.api_base = api_base

        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True

    def _get_keys_for_model(self, model: str) -> tuple[list[str | None], str | None]:
        """Get API key rotation list for a model.

        Returns (keys, provider_keyword) tuple.
        If no rotation keys are configured, returns ([None], None).
        """
        model_lower = model.lower()
        for keyword, keys in self._provider_keys.items():
            if keyword in model_lower and len(keys) > 1:
                return keys, keyword
        return [None], None  # Use env var (existing behavior)

    @staticmethod
    def _get_key_tier(keys: list[str | None], key_idx: int) -> str | None:
        """Determine key tier for stats. None means skip stats (single key)."""
        if len(keys) <= 1:
            return None
        return "paid" if key_idx == len(keys) - 1 else "free"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM.

        Tries the primary model first; on failure, iterates through
        fallback_models before returning an error. For models with multiple
        API keys configured, rotates through keys on rate limit errors
        (free keys with no retry, last key with full retries).

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'anthropic/claude-sonnet-4-5').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        primary = model or self.default_model
        models_to_try = [primary, *self.fallback_models]

        last_error: Exception | None = None
        for idx, candidate in enumerate(models_to_try):
            is_fallback = idx > 0
            resolved = self._resolve_model(candidate, is_fallback=is_fallback)

            # Some models only support temperature=1.0
            candidate_lower = candidate.lower()
            if "kimi-k2.5" in candidate_lower:
                temp = 1.0
            elif "gpt-5" in candidate_lower:
                temp = 1.0
            else:
                temp = temperature

            # Key rotation: get list of keys for this model
            keys, provider_keyword = self._get_keys_for_model(candidate)

            for key_idx, key in enumerate(keys):
                is_last_key = key_idx == len(keys) - 1
                # Free keys: no retries (switch immediately on 429)
                # Last key (paid): full retries with exponential backoff
                num_retries = self.num_retries if is_last_key else 0

                kwargs: dict[str, Any] = {
                    "model": resolved,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temp,
                    "num_retries": num_retries,
                }

                if key is not None:
                    kwargs["api_key"] = key

                # Pass api_base only for primary model with custom endpoint
                if self.api_base and not is_fallback:
                    kwargs["api_base"] = self.api_base

                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                try:
                    response = await acompletion(**kwargs)
                    tier = self._get_key_tier(keys, key_idx)
                    total_tokens = (
                        response.usage.total_tokens
                        if hasattr(response, "usage") and response.usage
                        else 0
                    )
                    logger.info(
                        "LLM ok: model={} tier={} key={}/{} tokens={}",
                        candidate,
                        tier or "default",
                        key_idx + 1,
                        len(keys),
                        total_tokens,
                    )
                    if self._api_key_stats and tier and provider_keyword:
                        self._api_key_stats.record(provider_keyword, tier, "success", total_tokens)
                    if is_fallback:
                        logger.info("Fallback succeeded with model: {}", candidate)
                    if key_idx > 0:
                        logger.info(
                            "Key rotation succeeded on key index {} for {}", key_idx, candidate
                        )
                    return self._parse_response(response)
                except litellm.exceptions.RateLimitError as e:
                    last_error = e
                    tier = self._get_key_tier(keys, key_idx)
                    logger.warning(
                        "LLM rate_limited: model={} tier={} key={}/{}",
                        candidate,
                        tier or "default",
                        key_idx + 1,
                        len(keys),
                    )
                    if self._api_key_stats and tier and provider_keyword:
                        self._api_key_stats.record(provider_keyword, tier, "rate_limited", 0)
                    if is_last_key:
                        # Last key exhausted, move to next model
                        logger.warning(
                            "Model {} rate limited on all keys, trying next fallback...",
                            candidate,
                        )
                        break
                    else:
                        # Rotate to next key immediately
                        continue
                except litellm.exceptions.ServiceUnavailableError as e:
                    last_error = e
                    logger.warning(
                        "LLM service_unavailable (503): model={} key={}/{}",
                        candidate,
                        key_idx + 1,
                        len(keys),
                    )
                    if idx < len(models_to_try) - 1:
                        logger.info("Model {} unavailable, trying next fallback...", candidate)
                    else:
                        logger.error("All models failed. Last error (503): {}", e)
                    break  # Server-side issue: skip key rotation, try next model
                except Exception as e:
                    last_error = e
                    if idx < len(models_to_try) - 1:
                        logger.warning(
                            "Model {} failed ({}), trying next fallback...", candidate, e
                        )
                    else:
                        logger.error("All models failed. Last error: {}", e)
                    break  # Non-rate-limit error: skip key rotation, try next model

        # All models exhausted
        return LLMResponse(
            content=f"Error calling LLM: {last_error}",
            finish_reason="error",
        )

    def _resolve_model(self, model: str, *, is_fallback: bool = False) -> str:
        """Apply provider-specific model name prefixes.

        For fallback models, instance-level flags (is_openrouter, is_vllm)
        are skipped since those apply only to the primary provider setup.
        """
        # OpenRouter prefix (instance-level, skip for fallback)
        if not is_fallback and self.is_openrouter and not model.startswith("openrouter/"):
            return f"openrouter/{model}"

        # Zhipu/Z.ai prefix (model-name based)
        if ("glm" in model.lower() or "zhipu" in model.lower()) and not (
            model.startswith("zhipu/")
            or model.startswith("zai/")
            or model.startswith("openrouter/")
        ):
            return f"zai/{model}"

        # Moonshot/Kimi prefix (model-name based)
        if ("moonshot" in model.lower() or "kimi" in model.lower()) and not (
            model.startswith("moonshot/") or model.startswith("openrouter/")
        ):
            return f"moonshot/{model}"

        # Gemini prefix (model-name based)
        if "gemini" in model.lower() and not model.startswith("gemini/"):
            return f"gemini/{model}"

        # vLLM prefix (instance-level, skip for fallback)
        if not is_fallback and self.is_vllm:
            return f"hosted_vllm/{model}"

        return model

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse LiteLLM response into our standard format."""
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                # Parse arguments from JSON string if needed
                args = tc.function.arguments
                if isinstance(args, str):
                    import json

                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}

                tool_calls.append(
                    ToolCallRequest(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
