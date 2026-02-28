"""LiteLLM provider implementation for multi-provider support."""

import logging
import os
from typing import Any

import litellm
from litellm import acompletion

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

logger = logging.getLogger(__name__)

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
        extra_provider_keys: dict[str, str] | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.num_retries = num_retries
        self.fallback_models = fallback_models or []

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
        if extra_provider_keys:
            for keyword, key in extra_provider_keys.items():
                env_var = _PROVIDER_ENV_MAP.get(keyword)
                if env_var and key:
                    os.environ.setdefault(env_var, key)

        if api_base:
            litellm.api_base = api_base

        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True

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
        fallback_models before returning an error.

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

            # kimi-k2.5 only supports temperature=1.0
            temp = 1.0 if "kimi-k2.5" in candidate.lower() else temperature

            kwargs: dict[str, Any] = {
                "model": resolved,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temp,
                "num_retries": self.num_retries,
            }

            # Pass api_base only for primary model with custom endpoint
            if self.api_base and not is_fallback:
                kwargs["api_base"] = self.api_base

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            try:
                response = await acompletion(**kwargs)
                if is_fallback:
                    logger.info("Fallback succeeded with model: %s", candidate)
                return self._parse_response(response)
            except Exception as e:
                last_error = e
                if idx < len(models_to_try) - 1:
                    logger.warning("Model %s failed (%s), trying next fallback...", candidate, e)
                else:
                    logger.error("All models failed. Last error: %s", e)

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
