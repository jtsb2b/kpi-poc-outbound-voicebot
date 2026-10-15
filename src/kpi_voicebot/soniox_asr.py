"""Speech recognition: Soniox real-time (stt-rt-v5) over WebSocket, chosen with ASR_PROVIDER=soniox.

Same interface as `asr.JaiASRStream`, so the turn-taking (`TurnCollector`) and the voice loop do
not change: `partial` events carry everything heard in the current utterance (final tokens plus
the still-changing tail); a `commit` is sent when Soniox detects the end of the utterance (its
`<end>` token, semantic endpoint detection); `final` after `finish`.

Protocol (Soniox WebSocket API, as used by livekit-plugins-soniox): send one JSON config, then raw
16 kHz s16le audio frames; each response carries `tokens` (`text`, `is_final`); an empty text frame
ends the stream. A keepalive JSON keeps the session open while no audio flows.

The per-call context (customer name, plan, beneficiary, e-mail) goes in as `terms`: Soniox uses
them to bias recognition, it does not transcribe them.
"""

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import websockets

from kpi_voicebot.asr import ASRError, ASREvent, tls_context
from kpi_voicebot.config import Settings

URL = "wss://stt-rt.soniox.com/transcribe-websocket"
END_TOKEN = "<end>"
FINALIZED_TOKEN = "<fin>"
KEEPALIVE = json.dumps({"type": "keepalive"})


class SonioxStream:
    """One streaming recognition session (one per call)."""

    def __init__(self, settings: Settings, url: str = URL) -> None:
        if settings.soniox_api_key is None:
            raise ASRError("SONIOX_API_KEY is not set")
        self.settings = settings
        self.url = url
        self._ws: websockets.ClientConnection | None = None
        self._keepalive: asyncio.Task[None] | None = None
        self._last_audio = 0.0
        self.ready: dict[str, object] = {}

    def config(self, context: str, language: str | None) -> dict[str, Any]:
        s = self.settings
        assert s.soniox_api_key is not None
        terms = [t.strip() for t in context.split(",") if t.strip()]
        config: dict[str, Any] = {
            "api_key": s.soniox_api_key.get_secret_value(),
            "model": s.soniox_model,
            "audio_format": "pcm_s16le",
            "sample_rate": 16_000,
            "num_channels": 1,
            "language_hints": ["th", "en"] if language in (None, "Thai") else [language],
            "enable_endpoint_detection": True,
            "max_endpoint_delay_ms": s.soniox_max_endpoint_delay_ms,
            "context": {
                "general": [
                    {"key": "domain", "value": "insurance customer service phone call"},
                    {"key": "language", "value": "Thai"},
                ],
                "terms": terms,
            },
        }
        return config

    async def open(self, context: str = "", language: str | None = "Thai") -> None:
        try:
            self._ws = await websockets.connect(
                self.url,
                ssl=tls_context() if self.url.startswith("wss://") else None,
                open_timeout=10,
                ping_interval=20,
            )
        except websockets.InvalidStatus as exc:
            raise ASRError(f"Soniox refused the stream (HTTP {exc.response.status_code})") from exc
        except OSError as exc:
            raise ASRError(f"Soniox unreachable: {exc}") from exc
        await self._ws.send(json.dumps(self.config(context, language)))
        self.ready = {"type": "ready", "provider": "soniox", "model": self.settings.soniox_model}
        self._last_audio = time.monotonic()
        self._keepalive = asyncio.ensure_future(self._keep_alive())

    async def _keep_alive(self) -> None:
        while self._ws is not None:
            await asyncio.sleep(5)
            if self._ws is not None and time.monotonic() - self._last_audio > 5:
                with contextlib.suppress(Exception):
                    await self._ws.send(KEEPALIVE)

    async def send(self, pcm: bytes) -> None:
        if self._ws is not None:
            self._last_audio = time.monotonic()
            await self._ws.send(pcm)

    async def events(self) -> AsyncIterator[ASREvent]:
        assert self._ws is not None
        final: list[str] = []  # final tokens of the current utterance
        segment = 0
        async for raw in self._ws:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            if msg.get("error_code") or msg.get("error_message"):
                raise ASRError(f"Soniox error: {msg.get('error_code')} {msg.get('error_message')}")
            tail: list[str] = []
            now = time.monotonic()
            for token in msg.get("tokens") or []:
                text = str(token.get("text") or "")
                if text == FINALIZED_TOKEN:
                    continue
                if text == END_TOKEN:
                    yield ASREvent("commit", "".join(final).strip(), segment, now)
                    final, tail = [], []
                    segment += 1
                    continue
                (final if token.get("is_final") else tail).append(text)
            if msg.get("finished"):
                yield ASREvent("final", "".join(final).strip(), segment, now)
                return
            heard = "".join(final + tail).strip()
            if heard:
                yield ASREvent("partial", heard, segment, now)

    async def finish(self) -> None:
        if self._ws is not None:
            await self._ws.send("")  # an empty frame ends the audio stream

    async def close(self) -> None:
        if self._keepalive is not None:
            self._keepalive.cancel()
        if self._ws is not None:
            ws, self._ws = self._ws, None
            with contextlib.suppress(Exception):
                await ws.close()
