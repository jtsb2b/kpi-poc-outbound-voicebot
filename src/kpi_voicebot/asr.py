"""Speech recognition: JaiASR-Flash-v1.0 (JTS), streaming over WebSocket.

Protocol (JaiASR API doc): send `start`, wait for `ready`, stream 16 kHz 16-bit mono PCM in
0.1–0.5 s frames, receive `partial` (replaces the previous partial of the same segment),
`commit` (0.5 s of silence ends a segment: append it) and, after `finish`, `final`.

Each call passes its own context (customer name, plan, beneficiary, amounts) so names and
numbers transcribe correctly. The file endpoint is kept for tests and benchmarks.
"""

import asyncio
import contextlib
import json
import ssl
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import certifi
import httpx
import websockets

from kpi_voicebot.config import Settings

SAMPLE_RATE = 16_000
FRAME_BYTES = 3_200  # 0.1 s


class ASRError(Exception):
    pass


@dataclass
class ASREvent:
    type: str  # partial | commit | final
    text: str
    segment_id: int
    at: float  # monotonic time it arrived
    audio_seconds: float = 0.0


def tls_context() -> ssl.SSLContext:
    # python.org / uv builds on macOS miss common roots (api.jasgpu.com, LiveKit Cloud); certifi has them.
    return ssl.create_default_context(cafile=certifi.where())


class JaiASRStream:
    """One streaming recognition session (one per call)."""

    def __init__(self, settings: Settings, url: str | None = None) -> None:
        if settings.jaiasr_api_key is None:
            raise ASRError("JAIASR_API_KEY is not set")
        self.settings = settings
        self.url = url or f"{settings.jaiasr_stream_url}?model={settings.jaiasr_model}"
        self._ws: websockets.ClientConnection | None = None
        self.ready: dict[str, object] = {}

    async def open(self, context: str = "", language: str | None = "Thai") -> None:
        key = self.settings.jaiasr_api_key
        assert key is not None
        try:
            self._ws = await websockets.connect(
                self.url,
                additional_headers=[("Authorization", f"Bearer {key.get_secret_value()}")],
                ssl=tls_context() if self.url.startswith("wss://") else None,
                open_timeout=10,
            )
        except websockets.InvalidStatus as exc:
            code = exc.response.status_code
            raise ASRError(f"JaiASR refused the stream (HTTP {code}); check the key, model and session") from exc
        except OSError as exc:
            raise ASRError(f"JaiASR unreachable: {exc}") from exc
        await self._ws.send(
            json.dumps(
                {
                    "type": "start",
                    "language": language,
                    "context": context,
                    "chunk_size_sec": self.settings.asr_chunk_seconds,
                }
            )
        )
        reply = json.loads(await asyncio.wait_for(self._ws.recv(), 10))
        if reply.get("type") != "ready":
            raise ASRError(f"JaiASR did not start: {reply.get('message') or reply.get('type')}")
        self.ready = reply

    async def send(self, pcm: bytes) -> None:
        if self._ws is not None:
            await self._ws.send(pcm)

    async def events(self) -> AsyncIterator[ASREvent]:
        assert self._ws is not None
        async for raw in self._ws:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "error":
                raise ASRError(f"JaiASR error: {msg.get('code')} {msg.get('message')}")
            if kind in ("partial", "commit", "final"):
                yield ASREvent(
                    kind,
                    str(msg.get("text") or ""),
                    int(msg.get("segment_id", 0)),
                    time.monotonic(),
                    float(msg.get("audio_seconds") or 0.0),
                )
                if kind == "final":
                    return

    async def finish(self) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps({"type": "finish"}))

    async def close(self) -> None:
        if self._ws is not None:
            ws, self._ws = self._ws, None
            with contextlib.suppress(Exception):
                await ws.send(json.dumps({"type": "cancel"}))
            with contextlib.suppress(Exception):
                await ws.close()


async def transcribe_file(settings: Settings, path: Path, language: str = "Thai") -> str:
    """Whole-file recognition (benchmarks and tests)."""
    if settings.jaiasr_api_key is None:
        raise ASRError("JAIASR_API_KEY is not set")
    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post(
            settings.jaiasr_http_url,
            headers={"Authorization": f"Bearer {settings.jaiasr_api_key.get_secret_value()}"},
            files={"file": (path.name, path.read_bytes())},
            data={"model": settings.jaiasr_model, "language": language},
        )
    if res.status_code != 200:
        raise ASRError(f"JaiASR HTTP {res.status_code}")
    return str(res.json().get("text") or "")


# Awaiting states where the customer talks freely and may pause mid-thought.
OPEN_ENDED = ("feedback:", "final_comment", "discrepancy_detail", "questions")


class TurnCollector:
    """Assembles what the customer says into turns, the way a listener would.

    A commit (0.5 s of silence) ends a short answer at once. For open-ended answers the
    listener waits a little longer (`grace`) and joins the next commit if they carry on.
    """

    def __init__(self, grace: float = 1.2) -> None:
        self.grace = grace
        self.committed: list[str] = []
        self.partial = ""
        self.last_commit_at = 0.0
        self.last_speech_at = 0.0
        self._changed = asyncio.Event()

    def feed(self, event: ASREvent) -> None:
        if event.type == "partial":
            self.partial = event.text
            if event.text.strip():
                self.last_speech_at = event.at
        elif event.text.strip():
            self.committed.append(event.text.strip())
            self.partial = ""
            self.last_commit_at = self.last_speech_at = event.at
        else:
            self.partial = ""
        self._changed.set()

    @property
    def heard(self) -> str:
        """Everything said so far in this turn, including words still being recognised."""
        return " ".join([*self.committed, self.partial]).strip()

    def reset(self) -> None:
        self.committed, self.partial = [], ""

    async def next_turn(self, awaiting: str | None, silence_timeout: float) -> str | None:
        """The customer's next complete turn, or None when they stay silent. Speech already heard
        (a customer who cut in while the bot was talking) is part of this turn."""
        open_ended = bool(awaiting) and str(awaiting).startswith(OPEN_ENDED)
        started = time.monotonic()
        while True:
            self._changed.clear()
            now = time.monotonic()
            if self.committed and not self.partial.strip():
                waited = now - self.last_commit_at
                if not open_ended or waited >= self.grace:
                    text = " ".join(self.committed)
                    self.reset()
                    return text
                timeout = self.grace - waited
            elif not self.committed and not self.partial.strip() and now - started >= silence_timeout:
                return None
            else:
                timeout = silence_timeout if not (self.committed or self.partial) else 0.25
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), max(0.05, timeout))


class SpeechStream(Protocol):
    """A streaming recogniser: JaiASR (`JaiASRStream`) or Soniox (`soniox_asr.SonioxStream`)."""

    ready: dict[str, object]

    async def open(self, context: str = "", language: str | None = "Thai") -> None: ...

    async def send(self, pcm: bytes) -> None: ...

    def events(self) -> AsyncIterator[ASREvent]: ...

    async def finish(self) -> None: ...

    async def close(self) -> None: ...


def speech_stream(settings: Settings) -> SpeechStream:
    """The recogniser named by ASR_PROVIDER. There is no fallback to the other one."""
    if settings.asr_provider == "soniox":
        from kpi_voicebot.soniox_asr import SonioxStream

        return SonioxStream(settings)
    return JaiASRStream(settings)
