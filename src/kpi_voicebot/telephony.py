"""Phone calls over LiveKit Cloud SIP: one room per call, the bot in it, the customer dialled in.

Order of a call:
1. Create a room `{LIVEKIT_ROOM_PREFIX}{call id}` and join it as the bot; publish the bot's voice
   track and open the recogniser (Soniox) and JAI TTS, all before dialling, so nothing waits once they answer.
2. Dial once through the project's outbound trunk (`CreateSIPParticipant`, From = the caller
   extension, Krisp noise cancellation at the SIP edge). The SIP participant's `sip.callStatus`
   attribute reports ringing; a cancel request during ringing deletes the room, which hangs up.
3. Answered: the customer's audio (16 kHz) feeds the voice session; the bot's voice goes out
   through an `rtc.AudioSource`. A hang-up (the SIP participant leaving) stops the bot at once.
4. The end: the room is deleted, which hangs up the phone leg.

A call is dialled at most once. A failure, busy line or uncertain error is reported as it is and
never retried here; the operator decides whether to call again.
"""

import asyncio
import contextlib
import logging
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from livekit import api, rtc

from kpi_voicebot import recording
from kpi_voicebot.asr import SpeechStream, speech_stream, tls_context
from kpi_voicebot.audio import VoiceFrontEnd
from kpi_voicebot.config import Settings
from kpi_voicebot.dialogue import AsyncInterpreter, Dialogue
from kpi_voicebot.engine import BaseEngine
from kpi_voicebot.models import DialResult, Outcome
from kpi_voicebot.playback import VoicePlayer
from kpi_voicebot.recording import CallRecorder
from kpi_voicebot.responder import Responder
from kpi_voicebot.simulator import Canceled, Sink
from kpi_voicebot.voice_session import VoiceSession, asr_context

log = logging.getLogger("kpi.phone")

BOT_IDENTITY = "kpi-bot"
CUSTOMER_IDENTITY = "customer"
OUT_QUEUE_MS = 400  # audio queued ahead in LiveKit; small, so a barge-in silences the bot quickly
LINE_DELAY_MS = 120  # starting guess of the echo path for the echo canceller (it adapts)


def quiet_released_handles() -> None:
    """Drop one known-harmless message: after a room disconnects, LiveKit's native side has already
    released its handles, and Python's garbage collector then fails an assertion releasing them
    again ("Exception ignored ... FfiHandle.__del__ ... assert dropped"). Everything else is shown."""
    default = sys.unraisablehook

    def hook(unraisable: sys.UnraisableHookArgs) -> None:
        where = f"{unraisable.err_msg or ''} {getattr(unraisable.object, '__qualname__', '')}"
        if isinstance(unraisable.exc_value, AssertionError) and "FfiHandle.__del__" in where:
            return
        default(unraisable)

    sys.unraisablehook = hook


def link_report(stats: Any) -> str:
    """One line from `Room.get_rtc_stats()`: what our voice met on the way out, and the caller's on the way in."""
    rtt, out, inn = None, "", ""
    for side in (stats.publisher_stats, stats.subscriber_stats):
        for st in side:
            kind = st.WhichOneof("stats")
            if kind == "candidate_pair" and st.candidate_pair.candidate_pair.nominated:
                rtt = st.candidate_pair.candidate_pair.current_round_trip_time * 1000
            elif kind == "remote_inbound_rtp" and st.remote_inbound_rtp.stream.kind == "audio":
                r = st.remote_inbound_rtp.received
                out = f"bot→LiveKit lost {r.packets_lost} jitter {r.jitter * 1000:.0f}ms"
            elif kind == "inbound_rtp" and st.inbound_rtp.stream.kind == "audio":
                r, ib = st.inbound_rtp.received, st.inbound_rtp.inbound
                filled = ib.concealed_samples / max(1, ib.total_samples_received) * 100
                inn = f"caller→bot lost {r.packets_lost} jitter {r.jitter * 1000:.0f}ms filled-in {filled:.1f}%"
    return f"📶 RTT {rtt:.0f}ms · {out} · {inn}" if rtt is not None else f"📶 {out} · {inn}"


def classify_sip(status: int | None) -> DialResult:
    """What a failed dial's SIP status means. Anything unclear counts as a technical failure."""
    if status in (486, 600):
        return DialResult.BUSY
    if status in (408, 480, 487):  # timed out ringing / temporarily unavailable / ring timeout hit
        return DialResult.NO_ANSWER
    if status in (603, 607):
        return DialResult.REJECTED
    if status in (404, 410, 484, 485, 604):
        return DialResult.UNREACHABLE
    return DialResult.TECHNICAL_FAILURE


@dataclass
class CallEnd:
    """How a phone call went, for the worker to record."""

    dial_result: DialResult
    answered: bool = False
    end_reason: str = ""
    sip_status: int | None = None
    sip_reason: str | None = None
    timings: list[float] = field(default_factory=list)
    recording_key: str | None = None  # where the call's audio was uploaded (Tencent COS)
    recording_declined: bool = False  # the customer declined: no audio kept, transcript kept
    recording_failed: bool = False  # it should have been recorded but the file could not be made or stored


class RoomOut:
    """The bot's voice as a LiveKit audio track."""

    def __init__(self, rate: int) -> None:
        self.source = rtc.AudioSource(rate, 1, queue_size_ms=OUT_QUEUE_MS)
        self.rate = rate
        self.latency = OUT_QUEUE_MS / 1000
        self.recorder: CallRecorder | None = None  # set while the call is recorded

    async def write(self, pcm: bytes) -> None:
        samples = len(pcm) // 2
        if samples:
            if self.recorder is not None:
                # Heard once the audio already queued ahead of it has played.
                self.recorder.bot(pcm, self.rate, time.monotonic() + float(self.source.queued_duration))
            await self.source.capture_frame(rtc.AudioFrame(pcm[: samples * 2], self.rate, 1, samples))

    def unplayed_seconds(self) -> float:
        return float(self.source.queued_duration)

    async def interrupt(self) -> None:
        self.source.clear_queue()
        if self.recorder is not None:
            self.recorder.cut_bot(time.monotonic())  # what was still queued was never heard

    async def drain(self) -> None:
        await self.source.wait_for_playout()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.source.aclose()


@contextlib.asynccontextmanager
async def livekit_api(settings: Settings) -> AsyncIterator[api.LiveKitAPI]:
    """LiveKit server API over an HTTP session that trusts certifi's roots (see `tls_context`)."""
    assert settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=tls_context())) as session:
        yield api.LiveKitAPI(
            settings.livekit_url,
            settings.livekit_api_key.get_secret_value(),
            settings.livekit_api_secret.get_secret_value(),
            session=session,
        )


def _token(settings: Settings, room_name: str) -> str:
    assert settings.livekit_api_key and settings.livekit_api_secret
    return (
        api.AccessToken(settings.livekit_api_key.get_secret_value(), settings.livekit_api_secret.get_secret_value())
        .with_identity(BOT_IDENTITY)
        .with_name("น้องเคพีไอ")
        .with_kind("agent")
        .with_grants(api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True))
        .to_jwt()
    )


class PhoneCall:
    """Places one outbound call and runs the conversation on it."""

    def __init__(
        self,
        settings: Settings,
        engine: BaseEngine,
        dialogue: Dialogue,
        *,
        room_name: str,
        sip_call_to: str,
        recording_key: str | None = None,
        sink: Sink | None = None,
        console: bool = False,
        is_canceled: Callable[[], Awaitable[bool]] | None = None,
        on_ringing: Callable[[], Awaitable[None]] | None = None,
        on_answered: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        missing = settings.livekit_missing()
        if missing:
            raise RuntimeError(f"phone calls need: {', '.join(missing)}")
        self.settings = settings
        self.engine = engine
        self.dialogue = dialogue
        self.room_name = room_name
        self.sip_call_to = sip_call_to
        self.recording_key = recording_key
        self.recorder: CallRecorder | None = None
        self._lk: api.LiveKitAPI | None = None
        self._end: CallEnd | None = None
        if hasattr(engine, "on_recording_declined"):
            engine.on_recording_declined = self._discard_recording
        self.sink = sink
        self.console = console
        self.is_canceled = is_canceled
        self.on_ringing = on_ringing
        self.on_answered = on_answered
        self.room = rtc.Room()
        self.customer_track: asyncio.Future[rtc.Track] = asyncio.get_running_loop().create_future()
        self.customer_left = asyncio.Event()
        self.ringing = asyncio.Event()
        self.session: VoiceSession | None = None

    # ---- room events ----

    def _watch_room(self) -> None:
        def on_attributes(changed: dict[str, str], participant: rtc.Participant) -> None:
            if participant.identity == CUSTOMER_IDENTITY and changed.get("sip.callStatus") == "ringing":
                self.ringing.set()

        def on_track(track: rtc.Track, _pub: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
            if (
                participant.identity == CUSTOMER_IDENTITY
                and track.kind == rtc.TrackKind.KIND_AUDIO
                and not self.customer_track.done()
            ):
                self.customer_track.set_result(track)

        def on_left(participant: rtc.RemoteParticipant) -> None:
            if participant.identity == CUSTOMER_IDENTITY:
                self.customer_left.set()
                if self.session is not None:
                    self.session.hang_up()

        def on_disconnected(*_: object) -> None:
            self.customer_left.set()
            if self.session is not None:
                self.session.hang_up()

        self.room.on("participant_attributes_changed", on_attributes)
        self.room.on("track_subscribed", on_track)
        self.room.on("participant_disconnected", on_left)
        self.room.on("disconnected", on_disconnected)

    # ---- the call ----

    async def run(self) -> CallEnd:
        async with livekit_api(self.settings) as lk:
            return await self._run(lk)

    async def _run(self, lk: api.LiveKitAPI) -> CallEnd:
        settings = self.settings
        assert settings.livekit_url
        # As in the inbound voicebot: one enhancer on the caller's audio (`_pump`) and nothing on top.
        # Echo cancellation, suppression and gain control here clipped and blurred speech.
        front = VoiceFrontEnd(echo_cancellation=False, noise_suppression=False, gain_control=False)
        player = VoicePlayer(make_out=RoomOut, report=self._note)
        asr = speech_stream(settings)
        try:
            await lk.room.create_room(
                api.CreateRoomRequest(
                    name=self.room_name,
                    empty_timeout=30,
                    departure_timeout=5,
                    max_participants=4,
                )
            )
            self._watch_room()
            await self.room.connect(settings.livekit_url, _token(settings, self.room_name))
            out = player.out
            assert isinstance(out, RoomOut)
            track = rtc.LocalAudioTrack.create_audio_track("bot-voice", out.source)
            await self.room.local_participant.publish_track(
                track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            )
            opening = getattr(self.dialogue, "prepare_opening", None)
            await asyncio.gather(
                asr.open(context=asr_context(self.engine)),
                player.prepare(),
                front.start(delay_ms=LINE_DELAY_MS),
                *([opening()] if opening else []),  # the model's greeting, before the phone rings
            )
            end = await self._dial(lk)
            if not end.answered:
                return end
            if self.on_answered is not None:
                await self.on_answered()
            self._lk, self._end = lk, end
            self._start_recording(out)
            return await self._converse(end, front, player, asr)
        finally:
            await self._hang_up(lk)
            await asyncio.gather(front.close(), asr.close(), player.close(), return_exceptions=True)
            with contextlib.suppress(Exception):
                await self.room.disconnect()
            await self._save_recording()

    async def _dial(self, lk: api.LiveKitAPI) -> CallEnd:
        settings = self.settings
        request = api.CreateSIPParticipantRequest(
            sip_trunk_id=settings.livekit_sip_outbound_trunk_id,
            sip_call_to=self.sip_call_to,
            sip_number=settings.sip_caller_number,
            room_name=self.room_name,
            participant_identity=CUSTOMER_IDENTITY,
            participant_name="ลูกค้า",
            krisp_enabled=settings.phone_noise_cancellation == "krisp",
            wait_until_answered=True,
            play_dialtone=False,
        )
        request.ringing_timeout.FromSeconds(settings.sip_ringing_timeout_seconds)
        request.max_call_duration.FromSeconds(settings.max_call_seconds)
        self._note(f"กำลังโทรออก (trunk {settings.livekit_sip_outbound_trunk_id}, จาก {settings.sip_caller_number})")
        dial = asyncio.ensure_future(lk.sip.create_sip_participant(request))
        ring_reported = False
        try:
            while not dial.done():
                await asyncio.wait({dial}, timeout=0.5)
                if self.ringing.is_set() and not ring_reported:
                    ring_reported = True
                    self._note("ปลายสายกำลังดัง")
                    if self.on_ringing is not None:
                        await self.on_ringing()
                if not dial.done() and self.is_canceled is not None and await self.is_canceled():
                    dial.cancel()
                    raise Canceled
            dial.result()
        except api.SipCallError as exc:
            result = classify_sip(exc.sip_status_code)
            self._note(f"โทรไม่ติด: SIP {exc.sip_status_code} {exc.sip_status or ''} → {result.value}")
            return CallEnd(result, False, f"sip_{exc.sip_status_code}", exc.sip_status_code, exc.sip_status)
        except api.TwirpError as exc:
            self._note(f"โทรไม่ติด: LiveKit {exc.code}")
            return CallEnd(DialResult.TECHNICAL_FAILURE, False, f"livekit_{exc.code}")
        except (TimeoutError, OSError) as exc:
            # Uncertain: the phone may or may not have rung. Reported as it is, never redialled.
            self._note(f"โทรไม่ติด: {type(exc).__name__}")
            return CallEnd(DialResult.TECHNICAL_FAILURE, False, f"dial_{type(exc).__name__}")
        self._note("ลูกค้ารับสายแล้ว")
        return CallEnd(DialResult.ANSWERED, True)

    async def _converse(self, end: CallEnd, front: VoiceFrontEnd, player: VoicePlayer, asr: SpeechStream) -> CallEnd:
        session = self.session = VoiceSession(
            self.engine,
            self.dialogue,
            player,
            front,
            asr,
            full_duplex=True,
            # No echo on the phone line (tested); the text echo guard was dropping real replies
            # ("สะดวกครับ" right after the bot said "สะดวกคุยไหมคะ").
            echo_guard=False,
            greet_on_answer=True,
            sink=self.sink,
            console=self.console,
            is_canceled=self.is_canceled,
        )
        if self.customer_left.is_set():
            session.hang_up()
        try:
            track = await asyncio.wait_for(asyncio.shield(self.customer_track), 5)
        except TimeoutError:
            end.end_reason = "no_customer_audio"
            log.warning("answered but no audio track from the customer within 5 s")
            session.hang_up()
            track = None
        pump = asyncio.ensure_future(self._pump(track, session)) if track is not None else None
        tape = asyncio.ensure_future(self._record_customer(track)) if track is not None and self.recorder else None
        watch = asyncio.ensure_future(self._watch_link())
        tasks = [t for t in (pump, tape, watch) if t is not None]
        try:
            await session.run()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        end.timings = session.turn_timings
        if not end.end_reason:
            end.end_reason = "customer_hung_up" if self.customer_left.is_set() else "conversation_complete"
        return end

    async def _watch_link(self, every: float = 5.0) -> None:
        """Every few seconds, the bot's own leg to LiveKit: round trip, and loss/jitter both ways.
        A clean line here while the customer hears choppy audio puts the fault on the LiveKit-PBX leg."""
        while True:
            await asyncio.sleep(every)
            with contextlib.suppress(Exception):
                self._note(link_report(await self.room.get_rtc_stats()))

    async def _pump(self, track: rtc.Track, session: VoiceSession) -> None:
        stream = rtc.AudioStream(
            track,
            sample_rate=16_000,
            num_channels=1,
            frame_size_ms=10,
            noise_cancellation=self._enhancer(),
        )
        try:
            async for event in stream:
                session.feed(bytes(event.frame.data))
        finally:
            await stream.aclose()

    async def _record_customer(self, track: rtc.Track) -> None:
        """The customer's side as it came down the line (before noise reduction, which is only for the
        recogniser), into the recording."""
        stream = rtc.AudioStream(track, sample_rate=recording.RATE, num_channels=1, frame_size_ms=20)
        try:
            async for event in stream:
                if self.recorder is not None:
                    self.recorder.customer(bytes(event.frame.data))
        finally:
            await stream.aclose()

    async def _discard_recording(self) -> None:
        """The customer declined the recording: keep no audio from here on or before; the call goes on."""
        if self._end is not None:
            self._end.recording_declined = True
        if self.recorder is not None:
            self.recorder.discard()
        self._note("ลูกค้าไม่ยินยอมให้บันทึกเสียง: ไม่เก็บไฟล์เสียง (ยังบันทึกข้อความ)")

    def _start_recording(self, out: RoomOut) -> None:
        """Record from the answer on, in this worker (both sides are already here)."""
        if not self.recording_key or not self.settings.recording_enabled:
            return
        self.recorder = out.recorder = CallRecorder()
        self._note("บันทึกเสียงการสนทนา (อัปโหลดไป COS เมื่อจบสาย)")

    async def _save_recording(self) -> None:
        """After hang-up: mix, encode and upload. A failure is marked on the call, never silent."""
        recorder, end = self.recorder, self._end
        if recorder is None or end is None or recorder.discarded or not self.recording_key:
            return
        try:
            data = await asyncio.to_thread(recorder.encode)
            await recording.upload(self.settings, self.recording_key, data)
        except Exception as exc:
            log.exception("could not store the recording %s", self.recording_key)
            end.recording_failed = True
            self._note(f"บันทึกเสียงไม่สำเร็จ: {type(exc).__name__}")
            return
        end.recording_key = self.recording_key
        self._note(f"บันทึกเสียงไปที่ COS: {self.recording_key} ({recorder.seconds:.0f} วินาที, {len(data) // 1024} KB)")

    def _enhancer(self) -> rtc.FrameProcessor[rtc.AudioFrame] | None:
        """ai-coustics QUAIL_VF_S, the inbound voicebot's setting (LiveKit Cloud authorises it with the
        room's own token, which the SDK hands over when the stream is attached to the track)."""
        if self.settings.phone_noise_cancellation != "ai_coustics":
            return None
        from livekit.plugins import ai_coustics

        enhancer: rtc.FrameProcessor[rtc.AudioFrame] = ai_coustics.audio_enhancement(
            model=ai_coustics.EnhancerModel.QUAIL_VF_S
        )
        return enhancer

    async def _hang_up(self, lk: api.LiveKitAPI) -> None:
        """Deleting the room ends the phone leg (and anything still ringing)."""
        with contextlib.suppress(Exception):
            await lk.room.delete_room(api.DeleteRoomRequest(room=self.room_name))

    def _note(self, text: str) -> None:
        if self.console:
            print(f"\033[90m   · {text}\033[0m")
        log.info("%s %s", self.room_name, text)


# ---- CLI: one live test call from the terminal (no queue, nothing stored) ----


def main() -> None:
    import argparse
    import uuid

    from kpi_voicebot.campaigns import get_profile
    from kpi_voicebot.config import get_settings
    from kpi_voicebot.phone import InvalidPhone, parse_destination
    from kpi_voicebot.service import within_calling_hours
    from kpi_voicebot.simulator import _summary, _with_llm, build_engine

    parser = argparse.ArgumentParser(prog="kpi-call", description="Place one live test call (asks before dialling)")
    parser.add_argument("profile", help="mock profile id (kpi-sim list)")
    parser.add_argument("--to", required=True, help="number to call: 08x-xxx-xxxx, +66…, or an internal extension")
    parser.add_argument("--name", default="สมชาย ใจดี", help="name the bot asks for")
    parser.add_argument("--llm", action="store_true", help="self-hosted LLM reads replies and words turns")
    args = parser.parse_args()

    quiet_released_handles()
    settings = get_settings()
    if not settings.live_calls_enabled:
        sys.exit("LIVE_CALLS_ENABLED is false in .env")
    if missing := settings.livekit_missing():
        sys.exit(f"not configured: {', '.join(missing)}")
    if not within_calling_hours(settings):
        sys.exit(f"outside calling hours ({settings.calling_window})")
    profile = get_profile(args.profile)
    if profile is None:
        sys.exit(f"unknown profile {args.profile}")
    try:
        destination = parse_destination(args.to, allow_extensions=settings.allow_internal_extensions)
    except InvalidPhone as exc:
        sys.exit(str(exc))
    if not destination.dialable or destination.sip_destination is None:
        sys.exit(destination.reason or "not dialable")
    shown = settings.public_caller_id or settings.sip_caller_number
    answer = input(f"โทรจริงไปที่ {destination.display} (แสดงเบอร์ {shown}) แคมเปญ {profile.campaign}? [y/N] ")
    if answer.strip().lower() not in {"y", "yes"}:
        sys.exit("ยกเลิก")

    engine = build_engine(profile.campaign, profile.case, args.name)
    room = f"{settings.livekit_room_prefix}test-{uuid.uuid4().hex[:8]}"
    sip_call_to = destination.sip_destination

    async def place(interpreter: AsyncInterpreter | None, responder: Responder | None) -> None:
        from kpi_voicebot.agent import make_dialogue
        from kpi_voicebot.llm import check_llm

        problem = await check_llm(responder.client) if responder is not None else None
        if problem:
            print(f"\033[31m   · LLM ใช้งานไม่ได้ ({problem}): ไม่โทรออก\033[0m")
            return

        talk, dialogue = make_dialogue(engine, interpreter, responder, settings.conversation_mode)
        call = PhoneCall(
            settings,
            talk,
            dialogue,
            room_name=room,
            sip_call_to=sip_call_to,
            recording_key=recording.object_key(settings, room, args.name, profile.campaign.value),
            console=True,
        )
        end = await call.run()
        if end.recording_key and engine.outcome is Outcome.NOTICE_OBJECTION:
            await recording.delete(settings, end.recording_key)
            print("\033[90m   · ลูกค้าไม่ยินยอมให้บันทึกเสียง: ลบไฟล์เสียงแล้ว\033[0m")
        print(f"\033[90m   · จบสาย: {end.dial_result.value} · {end.end_reason}\033[0m")
        if end.timings:
            avg = sum(end.timings) / len(end.timings)
            print(f"\033[90m   · ⏱ คำตอบพร้อมหลังลูกค้าพูดจบ: เฉลี่ย {avg:.2f}s, ช้าสุด {max(end.timings):.2f}s\033[0m")

    try:
        asyncio.run(_with_llm(args.llm, place))
    except KeyboardInterrupt:
        print("\n   · วางสาย (Ctrl-C)")
    print(_summary(engine))
