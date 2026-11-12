"""One spoken conversation: audio in → front end → Soniox (or JaiASR) → dialogue → JAI TTS → audio out.

The same loop runs a desk test through the microphone (`mic.py`) and a real phone call through
LiveKit (`telephony.py`); only where the audio comes from and goes to differs.

- Incoming audio (16 kHz mono, any chunk size) is pushed with `feed`. It goes through the front
  end (`audio.py`: echo cancellation, noise suppression, gain control, Silero VAD) and the
  cleaned audio streams to the recogniser.
- The customer's turn ends at the recogniser's end of utterance; open-ended answers get a short
  grace period so a pause mid-thought does not cut them off (`TurnCollector`).
- Barge-in (full duplex only): while the bot speaks, a sustained phrase (VAD speech over 0.7 s, or
  recognised words that are more than "ครับ / อืม"; on computer speakers recognised words only,
  since VAD cannot tell the customer from the bot's own echo) stops the bot, and only what was heard counts
  as delivered. Anything that is just the bot's own voice coming back is dropped (`echo_of`).
- Half duplex (desk test on speakers): the microphone is muted while the bot speaks.
- On a phone call the bot greets as soon as the call is answered (like a person calling); a
  "ฮัลโหล" said over the greeting neither stops it nor counts as the answer to it.
- `hang_up()` (the customer left) or a cancel request stops the bot mid-word and ends the loop.
"""

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from kpi_voicebot.asr import FRAME_BYTES, SpeechStream, TurnCollector
from kpi_voicebot.audio import VoiceFrontEnd, echo_of
from kpi_voicebot.dialogue import Dialogue, plain_acknowledgement
from kpi_voicebot.engine import BaseEngine
from kpi_voicebot.models import Directive
from kpi_voicebot.playback import VoicePlayer
from kpi_voicebot.simulator import Canceled, Sink
from kpi_voicebot.tts_text import speakable

log = logging.getLogger("kpi.voice")

# Seconds of silence before the bot checks the customer is still there. KPI (4 Nov demo): the bot gave up
# too soon on a customer who spoke softly; 7 s became 9 s, and a voice heard without words is never silence.
SILENCE_TIMEOUT = 9.0
UNHEARD_SPEECH = 0.4  # seconds of voice (VAD) with no words recognised: the customer spoke, too softly
MAX_UNHEARD = 2  # "please say that again" in a row before the voice counts as silence after all
ECHO_TAIL = 0.35  # half duplex: keep the mic muted this long after the bot stops (room reverb)
SPOKEN_CHARS_PER_SECOND = 13.0  # JAI TTS pace, to map heard time onto segments
BARGE_IN_SPEECH = 0.7  # seconds of sustained speech that count as cutting in (a "ครับ" is shorter)
ANSWER_SETTLE = 0.3  # phone: let the media path open after the answer, then greet straight away
LINE_READY_WAIT = 2.0  # longest the greeting waits for the customer's audio to start arriving
MAX_RETHINK = 3  # replies started again because the customer was still talking
PICKUP_WINDOW = 1.2  # a hello committed this soon after the greeting was said over it
# After the goodbye has left the worker, LiveKit, the SIP route and the phone network still hold part of it:
# hanging up at once cut "สวัสดีค่ะ" to "สวัส" (2 Nov B2B test).
HANGUP_TAIL = 1.2
# A cut-off with no words recognised this long after it was noise, breath or "อืม": carry on talking.
FALSE_BARGE_WAIT = 1.5
_HELLO = re.compile(r"ฮัลโหล|ฮัลโล|ฮัลโหลว|สวัสดี|ครับผม|ครับ|ค่ะ|คะ|จ้ะ|จ้า|ว่าไง|ใครพูด|ใครคะ|ใครครับ|[\s,.!?…]")


def is_hello(text: str) -> bool:
    """How people pick up the phone: "ฮัลโหล", "สวัสดีครับ", "ครับ" — not an answer to anything."""
    return bool(text.strip()) and not _HELLO.sub("", text)


def without_hello(text: str) -> str:
    """Drop a leading "ฮัลโหล"/"สวัสดีครับ" said over the greeting; keep what follows it."""
    words = text.split()
    while words and is_hello(words[0]):
        words.pop(0)
    return " ".join(words)


def asr_context(engine: BaseEngine) -> str:
    """Names and values this call may hear, so the recogniser spells them right."""
    keys = ("customer_name", "plan_name", "beneficiary", "delivery_target", "payment_channel", "case_id")
    words = [engine.vars[k] for k in keys if engine.vars.get(k)]
    # "ยอม" was heard as "ไม่ยอม" at the KPI demo (4 Nov): the answers to the recording question, spelled out.
    consent = ["ยินยอม", "ไม่ยินยอม"] if engine.campaign.recording_notice else []
    return ", ".join(["น้องเคพีไอ", "กรุงไทยพานิชประกันภัย", *words, *consent])


def segments_heard(directive: Directive, played_seconds: float) -> int:
    """How many whole segments fit into the audio actually heard before a cut-off."""
    budget = played_seconds * SPOKEN_CHARS_PER_SECOND
    used = 0.0
    for i, seg in enumerate(directive.segments):
        used += len(speakable(seg.text).replace(" ", ""))
        if used > budget:
            return i
    return len(directive.segments)


def is_barge_in(text: str) -> bool:
    """A real phrase while the bot speaks; "ครับ / อืม / อ่าฮะ" is the customer listening."""
    t = text.strip()
    return len(t) >= 2 and not plain_acknowledgement(t)


class VoiceSession:
    def __init__(
        self,
        engine: BaseEngine,
        dialogue: Dialogue,
        player: VoicePlayer,
        front: VoiceFrontEnd,
        asr: SpeechStream,
        *,
        full_duplex: bool,
        echo_guard: bool,
        vad_barge_in: bool = True,
        greet_on_answer: bool = False,
        line_ready: asyncio.Event | None = None,
        sink: Sink | None = None,
        console: bool = True,
        is_canceled: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self.engine = engine
        self.dialogue = dialogue
        self.player = player
        self.unheard = 0  # "please say that again" in a row, for a voice heard without words
        self.wait_started = 0.0
        self.front = front
        self.asr = asr
        self.full_duplex = full_duplex
        self.echo_guard = echo_guard
        self.vad_barge_in = vad_barge_in
        self.greet_on_answer = greet_on_answer
        self.line_ready = line_ready  # set when the customer's audio starts arriving (phone)
        self.greeting = False  # the opening line is playing
        self.closing = False  # the goodbye is playing: never cut ("ขอบคุณครับ" over it stopped it mid-word)
        self.greeting_ended_at = 0.0
        self.sink = sink
        self.console = console
        self.is_canceled = is_canceled
        player.tap = front.playback
        self.collector = TurnCollector()
        self.frames: asyncio.Queue[bytes] = asyncio.Queue(maxsize=400)
        self.outgoing = bytearray()
        self.barge = asyncio.Event()  # stops the bot's voice: a barge-in, a hang-up or a cancel
        self.gone = asyncio.Event()  # the customer hung up (or the call was canceled)
        self.canceled = False
        self.speaking_text = ""
        self.previous_text = ""
        self.turn_timings: list[float] = []

    # ---- input ----

    def feed(self, pcm: bytes) -> None:
        """16 kHz mono 16-bit audio from the customer (thread-safe callers use call_soon_threadsafe)."""
        with contextlib.suppress(asyncio.QueueFull):
            self.frames.put_nowait(pcm)

    def hang_up(self) -> None:
        """The customer is gone: stop talking and end the loop."""
        self.gone.set()
        self.barge.set()

    # ---- output helpers ----

    def _note(self, text: str) -> None:
        if self.console:
            print(f"\033[90m   · {text}\033[0m")
        else:
            log.info(text)

    async def _event(self, kind: str, data: dict[str, Any] | None = None) -> None:
        if self.sink is not None:
            await self.sink.event(kind, data)
        self._note(f"{kind} {data or ''}")

    # ---- workers ----

    def _muted(self) -> bool:
        if self.full_duplex:
            return False
        return self.player.speaking or time.monotonic() - self.player.stopped_at < ECHO_TAIL

    async def _send_audio(self) -> None:
        silence = b"\x00" * FRAME_BYTES
        while True:
            raw = await self.frames.get()
            self.outgoing += self.front.capture(raw)  # 10 ms frames in, cleaned
            while len(self.outgoing) >= FRAME_BYTES:
                frame = bytes(self.outgoing[:FRAME_BYTES])
                del self.outgoing[:FRAME_BYTES]
                # Muted frames still go out as silence: recognisers drop streams that go quiet too long.
                await self.asr.send(silence if self._muted() else frame)

    async def _watch_barge_in(self) -> None:
        """Sustained speech while the bot talks means the customer is cutting in. Off where the bot's
        own voice can reach the microphone (computer speakers): there, only recognised words count."""
        while True:
            await asyncio.sleep(0.05)
            if (
                self.full_duplex
                and self.vad_barge_in
                and not self.greeting  # "ฮัลโหล สวัสดีครับ" over the greeting is not cutting in
                and not self.closing
                and self.player.speaking
                and self.front.speech_seconds() >= BARGE_IN_SPEECH
            ):
                self.barge.set()

    def _voice_without_words(self) -> bool:
        """The VAD heard the customer's voice while we waited, though no words were recognised. The first
        half second is left out: the tail of the bot's own voice on the line."""
        f = self.front
        start = f.speech_started_at
        if start < self.wait_started + 0.5:
            return False
        end = time.monotonic() if f.speaking else f.speech_ended_at
        return end - start >= UNHEARD_SPEECH

    def _is_echo(self, heard: str) -> bool:
        return self.echo_guard and (echo_of(heard, self.speaking_text) or echo_of(heard, self.previous_text))

    async def _receive(self) -> None:
        async for event in self.asr.events():
            self.collector.feed(event)
            if self.console and event.type == "partial" and event.text.strip():
                print(f"\r\033[90m   … {self.collector.heard}\033[0m\033[K", end="", flush=True)
            heard = self.collector.heard
            if self.greeting:
                heard = without_hello(heard)
            # The bot's own voice coming back down the line never cuts it off (the echo guard proper stays off
            # on the phone: it dropped real replies; here it only stops a false barge-in).
            own_voice = echo_of(heard, self.speaking_text)
            if (
                self.full_duplex
                and self.player.speaking
                and not self.closing
                and is_barge_in(heard)
                and not self._is_echo(heard)
                and not own_voice
            ):
                self.barge.set()

    async def _only_noise(self) -> bool:
        """After a cut-off: True when no real words follow within `FALSE_BARGE_WAIT` (nothing, the bot's own
        echo, or just "ครับ / อืม"); False as soon as the customer is saying something."""
        deadline = time.monotonic() + FALSE_BARGE_WAIT
        while time.monotonic() < deadline:
            if self.gone.is_set():
                return False
            heard = self.collector.heard
            if is_barge_in(heard) and not self._is_echo(heard) and not echo_of(heard, self.speaking_text):
                return False
            await asyncio.sleep(0.05)
        return not self.gone.is_set() and not is_barge_in(self.collector.heard)

    async def _watch_cancel(self) -> None:
        if self.is_canceled is None:
            return
        while not self.gone.is_set():
            await asyncio.sleep(1.0)
            if await self.is_canceled():
                self.canceled = True
                self.hang_up()

    # ---- the conversation ----

    async def run(self) -> None:
        """Talk until the conversation ends or the customer hangs up. Raises `Canceled`."""
        workers = [
            asyncio.ensure_future(self._send_audio()),
            asyncio.ensure_future(self._receive()),
            asyncio.ensure_future(self._watch_barge_in()),
            asyncio.ensure_future(self._watch_cancel()),
        ]
        try:
            await self._loop()
        finally:
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        if self.canceled:
            raise Canceled

    async def _pickup_words(self, turn: str | None) -> str | None:
        """The first turn after the greeting, without the "ฮัลโหล" the customer said while it played.
        A bare hello said after the greeting has ended is kept: they did not hear it, and the
        engine asks again."""
        ended, self.greeting_ended_at = self.greeting_ended_at, 0.0
        while ended and turn is not None and time.monotonic() - ended < PICKUP_WINDOW:
            rest = without_hello(turn)
            if rest == turn:
                return turn
            hello = turn[: len(turn) - len(rest)].strip() if rest else turn
            if self.sink is not None:
                await self.sink.customer(hello)
            if self.console:
                print(f"\r\033[K\033[32m👤 ลูกค้า:\033[0m {hello}  \033[90m(รับสาย)\033[0m")
            if rest:
                return rest
            turn = await self._next_turn()
        return turn

    async def _next_turn(self) -> str | None:
        """The customer's next turn, None on silence; returns early (None) when they hang up."""
        self.wait_started = time.monotonic()
        turn = asyncio.ensure_future(self.collector.next_turn(self.engine.state.awaiting, SILENCE_TIMEOUT))
        gone = asyncio.ensure_future(self.gone.wait())
        try:
            await asyncio.wait({turn, gone}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            gone.cancel()
            if not turn.done():
                turn.cancel()
        return None if self.gone.is_set() or turn.cancelled() else turn.result()

    async def _reply(self, turn: str) -> Directive:
        """The reply to this turn. If the customer carries on while it is worked out ("ก็ครับ… เอ่อ ไม่ครับ"),
        it answers only the first half: start again from the same point with all of it (19 Oct call,
        where "ไม่ครับ" to the recording waited 34 s and was then taken as an answer to the next question)."""
        dialogue = self.dialogue
        snapshot = getattr(dialogue, "snapshot", None)  # the LLM-led agent; the scripted engine has none
        restore = getattr(dialogue, "restore", None)
        for _ in range(MAX_RETHINK):
            before = snapshot() if snapshot is not None and restore is not None else None
            directive = await dialogue.reply(turn)
            if before is None or restore is None or not self.collector.heard:
                return directive
            more = await self._next_turn()
            if not more or self.gone.is_set():
                return directive
            self._note(f"(ลูกค้าพูดต่อระหว่างคิดคำตอบ: {more} — คิดใหม่ทั้งประโยค)")
            if self.sink is not None:
                await self.sink.customer(more)
            restore(before)
            turn = f"{turn} {more}"
        return directive

    async def _loop(self) -> None:
        engine, dialogue = self.engine, self.dialogue
        directive = dialogue.start()
        if self.greet_on_answer:
            # Like a person calling: speak first, at once. The greeting was read ahead while ringing.
            self.player.prefetch_directive(directive)
            if self.line_ready is not None:
                # Greet once audio flows both ways, not on a fixed timer: the first words were the choppiest.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.line_ready.wait(), LINE_READY_WAIT)
            await asyncio.sleep(ANSWER_SETTLE)
            self.greeting = True
        waited_from = time.monotonic()
        while not self.gone.is_set():
            dialogue.prepare_next()
            if dialogue.prepared is not None:
                self.player.prefetch(dialogue.prepared)
            if self.console:
                print(f"\r\033[K\033[34m🤖 น้องเคพีไอ:\033[0m {directive.text}")
            self.barge.clear()
            if self.gone.is_set():
                self.barge.set()
            self.speaking_text = directive.text
            self.closing = directive.end_call
            if not self.full_duplex:
                self.collector.reset()  # nothing the speakers fed back belongs to the next turn
            played = await self.player.play(directive, len(directive.segments), waited_from, self.barge)
            if self.greeting:
                self.greeting = False
                self.greeting_ended_at = time.monotonic()
            self.previous_text = directive.text
            cut = self.barge.is_set()
            heard = segments_heard(directive, played) if cut else len(directive.segments)
            if cut and not self.gone.is_set() and heard < len(directive.segments) and await self._only_noise():
                # Stopped for something that was not the customer talking (a noise, a breath, "อืม"): the
                # bot went quiet and the caller, who heard half a sentence, asked "ว่ายังไงนะครับ" (2 Nov B2B
                # test, five times in one call). Say the rest, once, from the sentence that was cut.
                await self._event("false_interruption", {"after_segments": heard})
                self.collector.reset()
                rest = directive.model_copy(update={"segments": directive.segments[heard:]})
                self.barge.clear()
                played = await self.player.play(rest, len(rest.segments), time.monotonic(), self.barge)
                cut = self.barge.is_set()
                heard += segments_heard(rest, played) if cut else len(rest.segments)
            engine.report_delivery(heard, not cut)
            if self.sink is not None:
                await self.sink.bot(directive, heard, not cut)
            if self.gone.is_set():
                break
            if directive.end_call:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.gone.wait(), HANGUP_TAIL)  # let the goodbye reach the caller
                return
            turn = await self._pickup_words(await self._next_turn())
            while turn is not None and self._is_echo(turn):
                # The bot's own words came back down the line: not something the customer said.
                self._note(f"(ตัดเสียงสะท้อนของบอท: {turn})")
                turn = await self._next_turn()
            if self.console:
                print("\r\033[K", end="")
            if self.gone.is_set():
                break
            if turn is None:
                waited_from = time.monotonic()
                if self._voice_without_words() and self.unheard < MAX_UNHEARD:
                    # Someone spoke, too softly for words: ask again; never a step towards hanging up.
                    self.unheard += 1
                    await self._event("customer_unheard")
                    unheard = getattr(engine, "handle_unheard", None)
                    directive = unheard() if unheard is not None else engine.handle_silence()
                    continue
                self.unheard = 0
                await self._event("customer_silence")
                directive = engine.handle_silence()
                continue
            self.unheard = 0
            stopped = self.collector.last_commit_at or time.monotonic()
            if self.console:
                print(f"\033[32m👤 ลูกค้า:\033[0m {turn}")
            if self.sink is not None:
                await self.sink.customer(turn)
            directive = await self._reply(turn)
            ready = time.monotonic() - stopped
            self.turn_timings.append(ready)
            for kind, data in dialogue.events:
                await self._event(kind, data)
            dialogue.events.clear()
            self._note(f"⏱ ASR ยืนยันคำพูด → คำตอบพร้อม {ready:.2f}s")
            waited_from = stopped
        if not self.canceled:
            await self._event("customer_hung_up")
            engine.handle_hangup()
