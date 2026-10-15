"""Audio front end for everything the bot hears: clean the signal, then know when someone speaks.

Every 10 ms of microphone (later: telephone) audio passes through:
1. WebRTC audio processing (LiveKit's APM): echo cancellation against what the bot is playing,
   noise suppression, a high-pass filter for rumble and hum, and automatic gain control so quiet
   and loud callers reach the recogniser at a similar level.
2. Silero VAD (voice activity detection) on the cleaned audio: when speech starts and stops.

The cleaned audio is what the recogniser receives. VAD drives the human parts of turn-taking: a barge-in
is a sustained phrase, not a cough or a quick "ครับ"; silence timers run on real silence, not on
the absence of transcripts. For phone calls the same front end sits behind LiveKit, where LiveKit
Cloud's telephony noise cancellation can be added in front of it.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable

from livekit import rtc

log = logging.getLogger("kpi.audio")

SAMPLE_RATE = 16_000
FRAME_SAMPLES = SAMPLE_RATE // 100  # 10 ms, what the audio processor requires
FRAME_BYTES = FRAME_SAMPLES * 2


class VoiceFrontEnd:
    """Cleans 16 kHz mono audio in 10 ms frames and tracks speech with Silero VAD."""

    def __init__(
        self,
        *,
        echo_cancellation: bool = True,
        noise_suppression: bool = True,
        gain_control: bool = True,
        vad_threshold: float = 0.5,
        min_silence: float = 0.55,
        min_speech: float = 0.05,
        on_speech: Callable[[bool], None] | None = None,
    ) -> None:
        # Silero's defaults, as in the inbound voicebot: activation 0.5, 0.55 s of silence ends
        # speech, 0.05 s starts it.
        self.processing = echo_cancellation or noise_suppression or gain_control
        self.apm = rtc.AudioProcessingModule(
            echo_cancellation=echo_cancellation,
            noise_suppression=noise_suppression,
            high_pass_filter=noise_suppression or gain_control,
            auto_gain_control=gain_control,
        )
        self.echo_cancellation = echo_cancellation
        self._min_speech = min_speech
        self._vad_threshold = vad_threshold
        self._min_silence = min_silence
        self._on_speech = on_speech
        self._vad_stream: object | None = None
        self._vad_task: asyncio.Task[None] | None = None
        self._resamplers: dict[int, rtc.AudioResampler] = {}
        self._reverse_buf = bytearray()
        self._capture_buf = bytearray()
        self.speaking = False
        self.speech_started_at = 0.0
        self.speech_ended_at = 0.0

    # ---- VAD ----

    async def start(self, delay_ms: int = 60) -> None:
        """Load Silero VAD (needs the running event loop) and tell the echo canceller the
        playback-to-capture delay."""
        from livekit.agents import vad as agents_vad
        from livekit.plugins import silero

        model = silero.VAD.load(
            min_speech_duration=self._min_speech,
            min_silence_duration=self._min_silence,
            activation_threshold=self._vad_threshold,
            sample_rate=16000,
        )
        stream = model.stream()
        self._vad_stream = stream
        if self.echo_cancellation:
            self.apm.set_stream_delay_ms(delay_ms)

        async def watch() -> None:
            async for event in stream:
                if event.type == agents_vad.VADEventType.START_OF_SPEECH:
                    self.speaking, self.speech_started_at = True, time.monotonic()
                    if self._on_speech:
                        self._on_speech(True)
                elif event.type == agents_vad.VADEventType.END_OF_SPEECH:
                    self.speaking, self.speech_ended_at = False, time.monotonic()
                    if self._on_speech:
                        self._on_speech(False)

        self._vad_task = asyncio.ensure_future(watch())

    async def close(self) -> None:
        if self._vad_task is not None:
            self._vad_task.cancel()
        stream = self._vad_stream
        if stream is not None:
            with contextlib.suppress(Exception):
                await stream.aclose()  # type: ignore[attr-defined]
        # Release the native audio handles now, while LiveKit's runtime is still up; left to the
        # garbage collector at interpreter exit they fail noisily.
        for handle_owner in (self.apm, *self._resamplers.values()):
            with contextlib.suppress(Exception):
                handle_owner._ffi_handle.dispose()  # type: ignore[attr-defined]
        self._resamplers.clear()

    def speech_seconds(self) -> float:
        """How long the current stretch of speech has lasted (0 when nobody is speaking)."""
        return time.monotonic() - self.speech_started_at if self.speaking else 0.0

    # ---- audio ----

    def capture(self, pcm: bytes) -> bytes:
        """Clean microphone audio (any length); returns the cleaned audio processed so far."""
        self._capture_buf += pcm
        out = bytearray()
        while len(self._capture_buf) >= FRAME_BYTES:
            frame = rtc.AudioFrame(bytes(self._capture_buf[:FRAME_BYTES]), SAMPLE_RATE, 1, FRAME_SAMPLES)
            del self._capture_buf[:FRAME_BYTES]
            if self.processing:  # a phone call's audio is already cleaned upstream: leave it as it is
                self.apm.process_stream(frame)
            if self._vad_stream is not None:
                self._vad_stream.push_frame(frame)  # type: ignore[attr-defined]
            out += bytes(frame.data)
        return bytes(out)

    def playback(self, pcm: bytes, rate: int) -> None:
        """Tell the echo canceller what the bot is playing, as it is written to the speakers."""
        if not self.echo_cancellation or not pcm:
            return
        if rate != SAMPLE_RATE:
            resampler = self._resamplers.setdefault(rate, rtc.AudioResampler(rate, SAMPLE_RATE))
            samples = len(pcm) // 2
            frames = resampler.push(rtc.AudioFrame(pcm[: samples * 2], rate, 1, samples))
            pcm = b"".join(bytes(f.data) for f in frames)
        self._reverse_buf += pcm
        while len(self._reverse_buf) >= FRAME_BYTES:
            frame = rtc.AudioFrame(bytes(self._reverse_buf[:FRAME_BYTES]), SAMPLE_RATE, 1, FRAME_SAMPLES)
            del self._reverse_buf[:FRAME_BYTES]
            self.apm.process_reverse_stream(frame)


def echo_of(heard: str, bot_said: str, threshold: float = 0.6) -> bool:
    """The recogniser picked up the bot's own voice: most of what was "heard" is in the bot's turn."""
    import difflib

    a, b = heard.replace(" ", ""), bot_said.replace(" ", "")
    if len(a) < 8 or not b:
        return False  # short replies ("ครับ", "ไม่ใช่") are the customer's; letters match by chance
    blocks = difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    longest = max((block.size for block in blocks), default=0)
    matched = sum(block.size for block in blocks if block.size >= 3)
    return longest >= 6 and matched / len(a) >= threshold
