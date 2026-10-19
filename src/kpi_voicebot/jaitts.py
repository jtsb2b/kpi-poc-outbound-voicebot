"""JAI TTS: JTS's own Thai voice (VoxCPM, speaker-adapted female voice), streamed as raw PCM.

Measured 12 Oct 2026 from Bangkok: first audio ≈0.12 s, generation ≈8× faster than real time,
≈13 spoken characters per second at cfg 2.0 / temperature 0.7.

A turn is one request, so its intonation runs on like one breath (separately generated clauses
each restart their melody and sound read off a script). Only text longer than one request should
carry (tested: 600 characters is fine) is split, after a polite particle; the next part is then
requested while the current one streams, so the parts join without a gap.
"""

import asyncio
import contextlib
import re
import time
from collections.abc import AsyncIterator

import httpx

from kpi_voicebot.config import Settings

SAMPLE_RATE = 44_100
MAX_CLAUSE_CHARS = 500
# Break after a polite particle or sentence-like boundary, else at the last space that fits.
_CLAUSE_END = re.compile(r"(?:(?<=ค่ะ)|(?<=คะ)|(?<=ครับ))\s+")  # นะคะ ends in คะ


class JaiTTSError(Exception):
    pass


def clauses(spoken: str, limit: int = MAX_CLAUSE_CHARS) -> list[str]:
    """Normalised text as requests of at most `limit` characters: the whole turn when it fits,
    otherwise pieces cut after a polite particle (or at the last space that fits)."""
    if len(spoken) <= limit:
        return [spoken]
    out: list[str] = []
    for part in (p.strip() for p in _CLAUSE_END.split(spoken)):
        while len(part) > limit:
            cut = part.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            out.append(part)
    # Re-join very short pieces ("ค่ะ") onto their neighbour so each request carries a full phrase.
    merged: list[str] = []
    for piece in out:
        if merged and (len(piece) < 12 or len(merged[-1]) < 12) and len(merged[-1]) + len(piece) < limit:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return merged


class JaiVoice:
    """Reads lines aloud with JAI TTS. Same interface as the Gemini voice in `tts.py`."""

    sample_rate = SAMPLE_RATE
    tags = False
    model = "jaitts"
    voice = "meera"

    def __init__(self, settings: Settings) -> None:
        if settings.jaitts_api_key is None:
            raise JaiTTSError("JAITTS_API_KEY is not set")
        self.base_url = settings.jaitts_base_url.rstrip("/")
        self.style = f"cfg={settings.jaitts_cfg};temp={settings.jaitts_temperature}"
        self.params = {"cfg_value": settings.jaitts_cfg, "temperature": settings.jaitts_temperature}
        self._http = httpx.AsyncClient(
            headers={"X-API-Key": settings.jaitts_api_key.get_secret_value()},
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        self.last_heard = ""  # JAI TTS returns no transcript of what it said
        self.last_first_audio_s = 0.0

    async def connect(self) -> None:
        """Warm the connection (TLS handshake) before the first line is needed."""
        with contextlib.suppress(httpx.HTTPError):
            await self._http.get(f"{self.base_url}/ready")

    async def close(self) -> None:
        await self._http.aclose()

    async def _clause(self, text: str, queue: asyncio.Queue[bytes | Exception | None]) -> None:
        body = {"target_text": text, "response_format": "pcm", **self.params}
        carry = b""
        try:
            async with self._http.stream("POST", f"{self.base_url}/generate", json=body) as res:
                if res.status_code != 200:
                    await res.aread()
                    raise JaiTTSError(f"JAI TTS HTTP {res.status_code}")
                async for chunk in res.aiter_bytes():
                    data = carry + chunk
                    even = len(data) // 2 * 2  # chunks may split a 16-bit sample
                    carry = data[even:]
                    if even:
                        await queue.put(data[:even])
            await queue.put(None)
        except Exception as exc:  # surfaced to the reader in order
            await queue.put(exc if isinstance(exc, JaiTTSError) else JaiTTSError(f"JAI TTS failed: {exc}"))

    async def stream(self, spoken: str) -> AsyncIterator[bytes]:
        """44.1 kHz 16-bit mono PCM for one normalised line, clause by clause, as it arrives."""
        started = time.monotonic()
        first: float | None = None
        pieces = clauses(spoken, MAX_CLAUSE_CHARS)
        queues: list[asyncio.Queue[bytes | Exception | None]] = [asyncio.Queue() for _ in pieces]
        tasks: list[asyncio.Task[None]] = []

        def begin(i: int) -> None:
            if i < len(pieces) and len(tasks) == i:
                tasks.append(asyncio.ensure_future(self._clause(pieces[i], queues[i])))

        try:
            begin(0)
            for i in range(len(pieces)):
                begin(i + 1)  # request the next clause while this one streams
                while (item := await queues[i].get()) is not None:
                    if isinstance(item, Exception):
                        raise item
                    if first is None:
                        first = time.monotonic() - started
                        self.last_first_audio_s = first
                    yield item
        finally:
            for task in tasks:
                task.cancel()
