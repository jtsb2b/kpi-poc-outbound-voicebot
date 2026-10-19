"""Speaking bot turns: TTS audio streamed to an output as it arrives.

The output is this computer's speakers (`SpeakerOut`, for desk tests) or a phone call's LiveKit
audio track (`telephony.RoomOut`). Either way a turn is one utterance, the prepared next turn is
read ahead by a second voice session, a barge-in stops the voice within 0.2 s, and `play`
returns how much audio the customer actually heard.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Protocol

from kpi_voicebot.dialogue import Prepared
from kpi_voicebot.models import Directive

SLICE_SECONDS = 0.2  # audio is written in slices this long, so a barge-in stops the voice promptly


def console_note(text: str) -> None:
    print(f"\033[90m   · {text}\033[0m")


class AudioOut(Protocol):
    latency: float  # seconds from write to sound (the echo canceller needs it)

    async def write(self, pcm: bytes) -> None:
        """Queue 16-bit mono PCM; returns at roughly real-time pace."""

    def unplayed_seconds(self) -> float:
        """Audio written but not heard yet."""

    async def interrupt(self) -> None:
        """Drop audio not heard yet."""

    async def drain(self) -> None:
        """Wait until everything written has been heard."""

    async def close(self) -> None: ...


class SpeakerOut:
    """This computer's speakers. Writes block at playback pace, so nothing piles up unheard."""

    def __init__(self, rate: int) -> None:
        import sounddevice  # type: ignore[import-untyped]

        self._out = sounddevice.RawOutputStream(samplerate=rate, channels=1, dtype="int16")
        self._out.start()
        self.latency = float(self._out.latency)

    async def write(self, pcm: bytes) -> None:
        await asyncio.to_thread(self._out.write, pcm)

    def unplayed_seconds(self) -> float:
        return 0.0

    async def interrupt(self) -> None:
        return None

    async def drain(self) -> None:
        return None

    async def close(self) -> None:
        self._out.stop()


class _Ahead:
    """Audio for a prepared turn, read aloud in the background while the current turn plays."""

    def __init__(self) -> None:
        self.text: str | None = None
        self.chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None


class VoicePlayer:
    """Speaks bot turns as the audio streams in (JAI TTS by default).

    After each turn `report` gets how long the customer waited for the first sound and how long
    the turn ran: the two numbers that decide whether it feels human.
    """

    def __init__(
        self,
        make_out: Callable[[int], AudioOut] = SpeakerOut,
        report: Callable[[str], None] = console_note,
    ) -> None:
        from kpi_voicebot.config import get_settings
        from kpi_voicebot.tts import speaker

        self.speaker = speaker(get_settings())
        self.reader = speaker(get_settings())  # for turns read ahead
        self.ahead = _Ahead()
        self.pinned: _Ahead | None = None  # a known turn read ahead (the greeting)
        self.speaking = False
        self.stopped_at = 0.0
        self.tap: Callable[[bytes, int], None] | None = None  # sees every sample played (echo canceller)
        self.report = report
        self.rate = self.speaker.sample_rate
        self.out = make_out(self.rate)
        self.last_first_audio = 0.0

    async def prepare(self) -> None:
        # Opened while the phone rings.
        await asyncio.gather(self.speaker.voice.connect(), self.reader.voice.connect())

    def prefetch(self, prepared: asyncio.Task[Prepared | None]) -> None:
        self._cancel_ahead()
        ahead = self.ahead = _Ahead()

        async def read() -> None:
            try:
                ready = await prepared
            except asyncio.CancelledError, Exception:
                ready = None
            if ready is None:
                await ahead.chunks.put(None)
                return
            ahead.text = ready.directive.voice_text
            try:
                async for chunk in self.reader.speak(ahead.text):
                    await ahead.chunks.put(chunk)
            finally:
                await ahead.chunks.put(None)

        ahead.task = asyncio.ensure_future(read())

    def prefetch_directive(self, directive: Directive) -> None:
        """Read a known turn ahead (the greeting, while the phone rings). Kept apart from the
        prepared-turn read-ahead, which starts as soon as the greeting begins."""
        pinned = self.pinned = _Ahead()
        pinned.text = directive.voice_text

        async def read() -> None:
            try:
                async for chunk in self.reader.speak(directive.voice_text):
                    await pinned.chunks.put(chunk)
            finally:
                await pinned.chunks.put(None)

        pinned.task = asyncio.ensure_future(read())

    def _cancel_ahead(self) -> None:
        if self.ahead.task is not None and not self.ahead.task.done():
            self.ahead.task.cancel()

    def _cancel_pinned(self) -> None:
        pinned, self.pinned = self.pinned, None
        if pinned is not None and pinned.task is not None and not pinned.task.done():
            pinned.task.cancel()

    async def _audio(self, text: str) -> AsyncIterator[bytes]:
        pinned, self.pinned = self.pinned, None
        if pinned is not None and pinned.text == text:
            while (chunk := await pinned.chunks.get()) is not None:
                yield chunk
            return
        if pinned is not None and pinned.task is not None:
            pinned.task.cancel()
        ahead = self.ahead
        if ahead.text == text:
            while (chunk := await ahead.chunks.get()) is not None:
                yield chunk
            return
        self._cancel_ahead()
        async for chunk in self.speaker.speak(text):
            yield chunk

    async def play(
        self, directive: Directive, spoken_segments: int, waited_from: float, stop: asyncio.Event | None = None
    ) -> float:
        """Speak the turn; returns how many seconds were actually heard (less when `stop` cuts it off)."""
        text = " ".join(s.voice or s.text for s in directive.segments[:spoken_segments])
        read_ahead = self.ahead.text == text or (self.pinned is not None and self.pinned.text == text)
        rate = self.rate
        slice_bytes = int(rate * SLICE_SECONDS) * 2
        first: float | None = None
        size = 0
        unheard = 0.0
        stopped = False
        self.speaking = True
        try:
            async for chunk in self._audio(text):
                if first is None:
                    first = time.monotonic() - waited_from
                for i in range(0, len(chunk), slice_bytes):
                    if stop is not None and stop.is_set():
                        stopped = True
                        break
                    piece = chunk[i : i + slice_bytes]
                    size += len(piece)
                    if self.tap is not None:
                        self.tap(piece, rate)
                    await self.out.write(piece)
                if stopped or (stop is not None and stop.is_set()):
                    stopped = True
                    break
            if not stopped:
                await self._drain_unless(stop)
                stopped = stop is not None and stop.is_set()
        finally:
            unheard = self.out.unplayed_seconds()
            if stopped:
                self._cancel_ahead()
                await self.out.interrupt()
            self.speaking = False
            self.stopped_at = time.monotonic()
        length = max(0.0, size / (2 * rate) - unheard)
        self.last_first_audio = first or 0.0
        self._report(read_ahead, first or 0.0, length, stopped)
        return length

    async def _drain_unless(self, stop: asyncio.Event | None) -> None:
        """Wait for the queued audio to be heard, unless the customer cuts in first."""
        if stop is None:
            await self.out.drain()
            return
        drain = asyncio.ensure_future(self.out.drain())
        cut = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait({drain, cut}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (drain, cut):
                task.cancel()

    def _report(self, read_ahead: bool, first: float, length: float, cut: bool) -> None:
        used = self.reader if read_ahead else self.speaker
        fid = used.last_fidelity
        drift = "" if fid is None or fid >= 0.9 else f"  ⚠ อ่านไม่ตรงบท ({fid:.2f})"
        source = (
            "เตรียมไว้ล่วงหน้า"
            if read_ahead
            else "cache"
            if used.last_cached
            else "live, พูดซ้ำ"
            if used.last_retried
            else "live"
        )
        self.report(f"🔊 รอเสียง {first:.2f}s · พูด {length:.1f}s ({source}){drift}{'  ⟂ ถูกพูดแทรก' if cut else ''}")

    async def close(self) -> None:
        self._cancel_ahead()
        self._cancel_pinned()
        await asyncio.gather(self.speaker.voice.close(), self.reader.voice.close())
        await self.out.close()
