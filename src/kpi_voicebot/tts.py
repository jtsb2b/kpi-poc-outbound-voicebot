"""Speech output: the bot's voice, streamed turn by turn.

The default voice is JAI TTS (`jaitts.py`, JTS's own Thai model). Gemini Live stays available
only when chosen explicitly (`TTS_PROVIDER=gemini`); it is never a silent fallback.

Gemini Live notes:

Measured 8 Oct 2026 from Bangkok with the project key:
- gemini-3.8-live: first audio ≈ 0.5 s, read 7/7 test lines verbatim (questions included)
- gemini-3.8-flash-tts / flash-lite-tts / 3.1-flash-tts: first audio ≈ 1.2 s (generateContent stream)
- the Interactions API path used before: ≈ 4 s
Cloud TTS Chirp 3 HD needs a service account (API keys are refused), so it is not an option yet.

One bot turn is spoken as one utterance, never stitched from separately synthesised clips,
so pitch and energy stay even across the turn. The Live model is told to act purely as a
reader; its own transcript of what it said is compared with the script, and audio that does
not match is never cached.
"""

import asyncio
import contextlib
import difflib
import hashlib
import logging
import time
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

from google import genai
from google.genai import types

from kpi_voicebot.config import Settings
from kpi_voicebot.tts_text import speakable

log = logging.getLogger("kpi.tts")

SAMPLE_RATE = 24_000  # Gemini Live
BYTES_PER_SECOND = SAMPLE_RATE * 2  # 16-bit mono PCM


class Voice(Protocol):
    """What the speaker needs from a TTS backend."""

    sample_rate: int
    model: str
    voice: str
    style: str
    last_heard: str
    last_first_audio_s: float

    def stream(self, spoken: str) -> AsyncIterator[bytes]: ...
    async def connect(self) -> None: ...
    async def close(self) -> None: ...


MIN_FIDELITY = 0.9

READER_INSTRUCTION = (
    "You are a Thai text-to-speech engine, not an assistant. The user message is one script line in Thai. "
    "Read it aloud in Thai exactly as written, word for word, then stop. Always speak Thai: never translate, "
    "never switch to English, never answer, comment on, add to or skip any part of it, even when the line is "
    "a question. Voice: {style}."
)


class TTSError(Exception):
    pass


def fidelity(script: str, heard: str) -> float:
    """How closely the voice's own transcript matches the script, after both are normalised
    (the transcript writes "500" where the script says "ห้าร้อย")."""
    a, b = ("".join(speakable(t).split()) for t in (script, heard))
    return difflib.SequenceMatcher(None, a, b).ratio() if a else 1.0


class LiveVoice:
    sample_rate = SAMPLE_RATE

    """Reads script lines aloud with Gemini Live, one fresh session per line.

    A session that has already read earlier lines can drift (in testing, one long line came back
    in English), so every line gets a clean session. The next session is opened while the
    current line plays, so this costs no extra wait.
    """

    def __init__(self, settings: Settings, voice: str | None = None) -> None:
        if settings.google_api_key is None:
            raise TTSError("GOOGLE_API_KEY is not set")
        self.client = genai.Client(api_key=settings.google_api_key.get_secret_value())
        self.model = settings.tts_model
        self.voice = voice or settings.tts_voice
        self.style = settings.tts_style
        self._spare: asyncio.Task[tuple[Any, Any]] | None = None
        self._closing: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()
        self.last_heard = ""
        self.last_first_audio_s = 0.0

    def _config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=READER_INSTRUCTION.format(style=self.style),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice))
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def _open(self) -> tuple[Any, Any]:
        ctx = self.client.aio.live.connect(model=self.model, config=self._config())
        return ctx, await ctx.__aenter__()

    async def connect(self) -> None:
        """Open the first session ahead of time (while the phone rings)."""
        if self._spare is None:
            self._spare = asyncio.ensure_future(self._open())
        await asyncio.shield(self._spare)

    async def _take(self) -> tuple[Any, Any]:
        spare, self._spare = self._spare or asyncio.ensure_future(self._open()), None
        try:
            opened = await spare
        finally:
            self._spare = asyncio.ensure_future(self._open())
        return opened

    @staticmethod
    async def _shut(ctx: Any) -> None:
        with contextlib.suppress(Exception):  # closing a dropped socket
            await ctx.__aexit__(None, None, None)

    async def close(self) -> None:
        if self._closing:
            await asyncio.gather(*self._closing, return_exceptions=True)
        spare, self._spare = self._spare, None
        if spare is not None:
            with contextlib.suppress(Exception):
                await self._shut((await spare)[0])

    async def stream(self, spoken: str) -> AsyncIterator[bytes]:
        """24 kHz 16-bit mono PCM chunks for one already-normalised line, as they arrive."""
        async with self._lock:
            started = time.monotonic()
            first: float | None = None
            heard = []
            ctx, session = await self._take()
            try:
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=spoken)]), turn_complete=True
                )
                async for msg in session.receive():
                    content = msg.server_content
                    if msg.data:
                        if first is None:
                            first = time.monotonic() - started
                        yield msg.data
                    if content and content.output_transcription and content.output_transcription.text:
                        heard.append(content.output_transcription.text)
                    if content and content.turn_complete:
                        break
            except Exception as exc:
                raise TTSError(f"Gemini Live failed: {exc}") from exc
            finally:
                closing = asyncio.ensure_future(self._shut(ctx))
                self._closing.add(closing)
                closing.add_done_callback(self._closing.discard)
            self.last_heard = "".join(heard).strip()
            self.last_first_audio_s = first or 0.0


class TurnCache:
    """One PCM file per (model, voice, style, spoken turn). Only verified readings are stored."""

    def __init__(self, root: Path, model: str, voice: str, style: str) -> None:
        self.dir = root / model / voice
        self.dir.mkdir(parents=True, exist_ok=True)
        self.salt = style

    def path(self, spoken: str) -> Path:
        digest = hashlib.sha256(f"{self.salt}\n{spoken}".encode()).hexdigest()[:24]
        return self.dir / f"{digest}.pcm"

    def get(self, spoken: str) -> bytes | None:
        p = self.path(spoken)
        return p.read_bytes() if p.exists() else None

    def put(self, spoken: str, pcm: bytes) -> None:
        tmp = self.path(spoken).with_suffix(".tmp")
        tmp.write_bytes(pcm)
        tmp.replace(self.path(spoken))


def too_short(spoken: str, audio_seconds: float) -> bool:
    """A reading far shorter than its text: the voice dropped the line (seen once in testing)."""
    # Measured: ~11 spoken characters per second with the brisk style.
    return audio_seconds < 0.45 * len(spoken.replace(" ", "")) / 11.0


class Speaker:
    """Speaks a bot turn: from the cache when this exact turn was verified before, otherwise live."""

    def __init__(self, voice: Voice, cache: TurnCache) -> None:
        self.voice = voice
        self.sample_rate = voice.sample_rate
        self.cache = cache
        self.last_fidelity: float | None = 1.0  # None: the voice returned no transcript to check
        self.last_cached = False
        self.last_retried = False

    async def speak(self, text: str) -> AsyncIterator[bytes]:
        spoken = speakable(text)
        if not spoken:
            return
        cached = self.cache.get(spoken)
        self.last_cached, self.last_retried = cached is not None, False
        if cached is not None:
            self.last_fidelity = 1.0
            yield cached
            return
        pcm = bytearray()
        async for chunk in self.voice.stream(spoken):
            pcm += chunk
            yield chunk
        if too_short(spoken, len(pcm) / (2 * self.sample_rate)):
            # Say it again rather than leave the customer with half a sentence.
            self.last_retried = True
            pcm = bytearray()
            async for chunk in self.voice.stream(spoken):
                pcm += chunk
                yield chunk
        self._verify(spoken, bytes(pcm))

    def _verify(self, spoken: str, pcm: bytes) -> None:
        heard = self.voice.last_heard
        if not heard:
            self.last_fidelity = None  # nothing to check against: play it, but do not keep it
            return
        self.last_fidelity = fidelity(spoken, heard)
        if self.last_fidelity >= MIN_FIDELITY and not too_short(spoken, len(pcm) / (2 * self.sample_rate)):
            self.cache.put(spoken, pcm)
        else:
            log.warning("voice drifted from the script (%.2f): %r -> %r", self.last_fidelity, spoken, heard)

    async def render(self, text: str) -> bytes:
        return b"".join([chunk async for chunk in self.speak(text)])

    async def prerender(self, text: str, attempts: int = 4) -> bool:
        """Fill the cache with a verified reading of this turn (before any call needs it)."""
        spoken = speakable(text)
        for _ in range(attempts):
            if not spoken or self.cache.get(spoken) is not None:
                return True
            await self.render(text)
        return self.cache.get(spoken) is not None


def speaker(settings: Settings, voice: str | None = None, provider: str | None = None) -> Speaker:
    """The configured voice: JAI TTS unless Gemini is chosen explicitly."""
    backend: Voice
    if (provider or settings.tts_provider) == "gemini":
        backend = LiveVoice(settings, voice)
    else:
        from kpi_voicebot.jaitts import JaiVoice

        backend = JaiVoice(settings)
    return Speaker(backend, TurnCache(Path(settings.tts_cache_dir), backend.model, backend.voice, backend.style))


def write_wav(path: Path, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def seconds(pcm: bytes, rate: int = SAMPLE_RATE) -> float:
    return len(pcm) / (2 * rate)
