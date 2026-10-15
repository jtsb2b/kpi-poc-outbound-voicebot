"""Talk to the bot through this computer's microphone: the phone call's loop, testable at a desk.

The conversation itself is `voice_session.VoiceSession`; this module only wires the microphone
in and the speakers out. Barge-in is allowed with `--headphones`, or on speakers with `--aec`
(echo cancellation plus a guard that drops the bot's own voice coming back). By default on
speakers the microphone is muted while the bot speaks.
"""

import asyncio
from typing import Any

from kpi_voicebot.asr import SAMPLE_RATE, ASRError, speech_stream
from kpi_voicebot.audio import FRAME_SAMPLES, VoiceFrontEnd
from kpi_voicebot.config import get_settings
from kpi_voicebot.dialogue import Dialogue
from kpi_voicebot.engine import BaseEngine
from kpi_voicebot.playback import VoicePlayer
from kpi_voicebot.voice_session import VoiceSession, asr_context, is_barge_in, segments_heard

__all__ = ["MicChat", "is_barge_in", "segments_heard"]


class MicChat:
    def __init__(self, engine: BaseEngine, dialogue: Dialogue, headphones: bool, aec: bool = False) -> None:
        self.engine = engine
        self.headphones = headphones
        self.aec = aec
        self.front = VoiceFrontEnd(echo_cancellation=not headphones)
        self.player = VoicePlayer()
        self.asr = speech_stream(get_settings())
        self.session = VoiceSession(
            engine,
            dialogue,
            self.player,
            self.front,
            self.asr,
            full_duplex=headphones or aec,  # the customer may talk over the bot
            echo_guard=aec,
            vad_barge_in=headphones,  # on speakers VAD hears the bot's echo too: words only
        )

    async def run(self) -> None:
        import sounddevice  # type: ignore[import-untyped]

        loop = asyncio.get_running_loop()
        session = self.session

        def on_audio(data: Any, frames: int, t: Any, status: Any) -> None:
            loop.call_soon_threadsafe(session.feed, bytes(data))

        try:
            await self.asr.open(context=asr_context(self.engine))
        except ASRError as exc:
            print(f"\033[31m   · {exc}\033[0m")
            return
        mic = sounddevice.RawInputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME_SAMPLES, callback=on_audio
        )
        mic.start()
        # Playback-to-capture delay for the echo canceller: what the two audio devices report.
        await self.front.start(delay_ms=int((float(mic.latency) + self.player.out.latency) * 1000))
        await self.player.prepare()
        mode = (
            "ใส่หูฟัง: พูดแทรกได้"
            if self.headphones
            else "ลำโพง + ตัดเสียงสะท้อน: พูดแทรกได้"
            if self.aec
            else "ไมค์ปิดระหว่างบอทพูด (--headphones หรือ --aec เพื่อพูดแทรก)"
        )
        print(f"\033[90m   · พูดได้เลย · ตัดเสียงรบกวน + VAD · {mode} · Ctrl-C เพื่อวางสาย\033[0m")
        try:
            await session.run()
        finally:
            mic.stop()
            mic.close()
            await self.front.close()
            await self.asr.close()
            await self.player.close()
