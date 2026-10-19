"""Gemini as the conversation LLM, chosen with LLM_PROVIDER=gemini (never a silent fallback).

The same interface as `llm.LLMClient` (`chat_text`, `chat_json`), so the agent, the scripted mode and
the CLIs need no change. Chosen on 19 Oct 2026 for Thai politeness, on the PM's request:
`gemini-3.5-flash-lite`, generally available, with thinking at its floor (`minimal`; Gemini 3.x
cannot switch thinking off, and models whose floor is `low` take 4.5-13 s to answer). Measured from
Bangkok with the real ~6k-token prompt: first token ≈1.2 s, full reply ≈1.4 s. The system prompt is
identical every turn, so Google's implicit prompt caching applies. A paid API key is required: the
free tier may use requests to improve Google's products, and calls carry customer data.
"""

import asyncio
import json
import time
from typing import Any

from google import genai
from google.genai import errors, types

from kpi_voicebot.config import Settings
from kpi_voicebot.llm import LLMError, RateLimiter, estimate_tokens

THINKING_ROOM = 256  # thinking tokens count against max_output_tokens even at the minimal level
# Google rejects a request deadline under 10 s (HTTP 400 "Minimum allowed deadline is 10s"; every turn of
# the 19 Oct test call failed this way with our 8 s timeout). Our own, shorter limit is kept client-side.
GOOGLE_MIN_DEADLINE_S = 10.0


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        if settings.google_api_key is None:
            raise LLMError("GOOGLE_API_KEY must be set for LLM_PROVIDER=gemini")
        self.model = settings.gemini_llm_model
        self.thinking = settings.gemini_thinking_level
        self.max_queue = settings.llm_max_queue_seconds
        self.timeout = settings.llm_timeout_seconds
        self.deadline_s = max(GOOGLE_MIN_DEADLINE_S, settings.llm_timeout_seconds)
        self.limiter = RateLimiter(settings.llm_requests_per_minute, settings.llm_tokens_per_minute)
        self._client = genai.Client(
            api_key=settings.google_api_key.get_secret_value(),
            http_options=types.HttpOptions(timeout=int(self.deadline_s * 1000)),
        )

    async def aclose(self) -> None:
        await self._client.aio.aclose()

    async def chat_text(
        self, messages: list[dict[str, str]], *, max_tokens: int = 260, temperature: float = 0.0
    ) -> tuple[str, dict[str, Any]]:
        """Plain text (the agent's line format). Temperature is ignored by Gemini 3.x Flash-Lite."""
        return await self._generate(messages, max_tokens)

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        name: str,
        max_tokens: int = 200,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        text, metrics = await self._generate(messages, max_tokens, schema)
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise LLMError("malformed response") from exc
        if not isinstance(parsed, dict):
            raise LLMError("malformed response")
        return parsed, metrics

    async def _generate(
        self, messages: list[dict[str, str]], max_tokens: int, schema: dict[str, Any] | None = None
    ) -> tuple[str, dict[str, Any]]:
        await self.limiter.acquire(estimate_tokens(messages, max_tokens), max_wait=self.max_queue)
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [
            types.Content(role="model" if m["role"] == "assistant" else "user", parts=[types.Part(text=m["content"])])
            for m in messages
            if m["role"] != "system"
        ]
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens + THINKING_ROOM,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel(self.thinking.upper())),
            response_mime_type="application/json" if schema else None,
            response_json_schema=schema,
        )
        started = time.monotonic()
        try:
            res = await asyncio.wait_for(
                self._client.aio.models.generate_content(model=self.model, contents=contents, config=config),
                self.timeout,
            )
        except TimeoutError as exc:
            raise LLMError("timeout") from exc
        except errors.APIError as exc:
            raise LLMError(f"HTTP {exc.code}: {(exc.message or '')[:120]}") from exc
        except Exception as exc:  # network errors and timeouts
            raise LLMError(f"request failed: {type(exc).__name__}") from exc
        text = res.text or ""
        usage = res.usage_metadata
        total = usage.total_token_count if usage else None
        if total:
            self.limiter.record_actual(int(total))
        return text, {
            "latency_ms": round((time.monotonic() - started) * 1000),
            "total_tokens": total,
            "output_tokens": usage.candidates_token_count if usage else None,
            "cached_tokens": usage.cached_content_token_count if usage else None,
        }
