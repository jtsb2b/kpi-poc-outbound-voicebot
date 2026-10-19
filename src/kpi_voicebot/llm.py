"""OpenAI-compatible chat client for the self-hosted LLM (OpenThai 2.0 27B, Qwen 3.8 base, on vLLM).

No hosted fallback provider: when the model is slow, rate-limited or wrong, callers fall
back to the deterministic rule layer and record that they did.
"""

import asyncio
import json
import time
from collections import deque
from typing import Any

import httpx

from kpi_voicebot.config import Settings


class LLMError(Exception):
    pass


WHITESPACE_LOOP = 24  # this many whitespace characters in a row is the decoder looping, not text


class RateLimiter:
    """Sliding one-minute window over requests and tokens; waits rather than overrunning the quota."""

    def __init__(self, requests_per_minute: int, tokens_per_minute: int) -> None:
        self.rpm = requests_per_minute
        self.tpm = tokens_per_minute
        self._events: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0][0] >= 60:
            self._events.popleft()

    def wait_seconds(self, tokens: int, now: float) -> float:
        self._prune(now)
        over_requests = self.rpm and len(self._events) >= self.rpm
        used = sum(t for _, t in self._events)
        over_tokens = self.tpm and self._events and used + tokens > self.tpm
        if not (over_requests or over_tokens):
            return 0.0
        return max(0.0, 60 - (now - self._events[0][0]))

    async def acquire(self, tokens: int, max_wait: float) -> None:
        async with self._lock:
            delay = self.wait_seconds(tokens, time.monotonic())
            if delay > max_wait:
                raise LLMError(f"rate limit: would wait {delay:.1f}s")
            if delay:
                await asyncio.sleep(delay)
            self._events.append((time.monotonic(), tokens))

    def record_actual(self, tokens: int) -> None:
        if self._events:
            at, _ = self._events.pop()
            self._events.append((at, tokens))


def estimate_tokens(messages: list[dict[str, str]], max_tokens: int) -> int:
    # Thai runs roughly 2-3 characters per token on Qwen tokenizers; stay on the high side.
    return sum(len(m["content"]) for m in messages) // 2 + max_tokens


class LLMClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not (settings.llm_base_url and settings.llm_api_key and settings.llm_model):
            raise LLMError("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL must be set")
        self.model = settings.llm_model
        self.timeout = settings.llm_timeout_seconds
        self.max_queue = settings.llm_max_queue_seconds
        self.limiter = RateLimiter(settings.llm_requests_per_minute, settings.llm_tokens_per_minute)
        self._http = httpx.AsyncClient(
            base_url=settings.llm_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"},
            timeout=self.timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def chat_text(
        self, messages: list[dict[str, str]], *, max_tokens: int = 260, temperature: float = 0.0
    ) -> tuple[str, dict[str, Any]]:
        """Plain text, no grammar: for replies in a line format the caller parses and checks."""
        await self.limiter.acquire(estimate_tokens(messages, max_tokens), max_wait=self.max_queue)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        started = time.monotonic()
        try:
            res = await self._http.post("/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"request failed: {type(exc).__name__}") from exc
        if res.status_code != 200:
            raise LLMError(f"HTTP {res.status_code}")
        try:
            data = res.json()
            text = str(data["choices"][0]["message"]["content"] or "")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("malformed response") from exc
        usage = data.get("usage") or {}
        if usage.get("total_tokens"):
            self.limiter.record_actual(int(usage["total_tokens"]))
        return text, {
            "latency_ms": round((time.monotonic() - started) * 1000),
            "total_tokens": usage.get("total_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }

    async def stream_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        max_tokens: int = 300,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Like `chat_json`, streamed, with compact JSON. Grammar-constrained decoding sometimes
        pads JSON with endless whitespace until the token limit (seen on the OpenThai gateway, even
        with whitespace disabled): the stream is cut the moment that starts, instead of after seconds."""
        await self.limiter.acquire(estimate_tokens(messages, max_tokens), max_wait=self.max_queue)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False},
            "structured_outputs": {"json": schema, "disable_any_whitespace": True},
        }
        started = time.monotonic()
        content: list[str] = []
        usage: dict[str, Any] = {}
        whitespace = 0
        first_token_ms: int | None = None
        try:
            async with self._http.stream("POST", "/chat/completions", json=body) as res:
                if res.status_code != 200:
                    await res.aread()
                    raise LLMError(f"HTTP {res.status_code}")
                async for line in res.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    chunk = json.loads(line[6:])
                    usage = chunk.get("usage") or usage
                    for choice in chunk.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content") or ""
                        if piece and first_token_ms is None:
                            first_token_ms = round((time.monotonic() - started) * 1000)
                        content.append(piece)
                        for ch in piece:
                            whitespace = whitespace + 1 if ch in " \n\t\r" else 0
                        if whitespace > WHITESPACE_LOOP:
                            raise LLMError("whitespace loop")
        except httpx.HTTPError as exc:
            raise LLMError(f"request failed: {type(exc).__name__}") from exc
        except ValueError as exc:
            raise LLMError("malformed stream") from exc
        try:
            parsed = json.loads("".join(content))
        except ValueError as exc:
            raise LLMError("malformed response") from exc
        if usage.get("total_tokens"):
            self.limiter.record_actual(int(usage["total_tokens"]))
        metrics = {
            "latency_ms": round((time.monotonic() - started) * 1000),
            "first_token_ms": first_token_ms,
            "total_tokens": usage.get("total_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }
        return parsed, metrics

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        name: str,
        max_tokens: int = 200,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (parsed JSON, metrics). Structured output is enforced server-side by json_schema."""
        # On a call, a long wait for quota is worse than the approved wording: give up quickly.
        await self.limiter.acquire(estimate_tokens(messages, max_tokens), max_wait=self.max_queue)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        }
        started = time.monotonic()
        try:
            res = await self._http.post("/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"request failed: {type(exc).__name__}") from exc
        latency_ms = round((time.monotonic() - started) * 1000)
        if res.status_code != 200:
            raise LLMError(f"HTTP {res.status_code}")
        try:
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("malformed response") from exc
        usage = data.get("usage") or {}
        if usage.get("total_tokens"):
            self.limiter.record_actual(int(usage["total_tokens"]))
        return parsed, {"latency_ms": latency_ms, "total_tokens": usage.get("total_tokens")}


def llm_client(settings: Settings) -> Any:
    """The LLM named by LLM_PROVIDER: Gemini, or the self-hosted model on the JTS gateway."""
    if settings.llm_provider == "gemini":
        from kpi_voicebot.gemini import GeminiClient

        return GeminiClient(settings)
    return LLMClient(settings)


async def check_llm(client: Any) -> str | None:
    """Before dialling: does the LLM answer at all? None when it does, else the reason it does not.
    A call whose every turn falls back to fixed lines is worse than no call (19 Oct test call)."""
    try:
        await client.chat_text([{"role": "user", "content": "ตอบคำเดียวว่า พร้อม"}], max_tokens=10)
    except LLMError as exc:
        return str(exc)
    return None
