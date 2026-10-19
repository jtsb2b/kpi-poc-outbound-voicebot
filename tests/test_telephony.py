"""Phone calls without a phone: the worker's live path with a fake LiveKit call, the voice loop
with fake audio, and SIP status mapping. CI never dials."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from kpi_voicebot import voice_session
from kpi_voicebot.asr import ASREvent
from kpi_voicebot.config import Settings
from kpi_voicebot.dialogue import Dialogue
from kpi_voicebot.models import DialResult, Directive
from kpi_voicebot.simulator import build_engine
from kpi_voicebot.store import Store
from kpi_voicebot.telephony import CallEnd, classify_sip
from kpi_voicebot.voice_session import VoiceSession
from kpi_voicebot.worker import Worker

from .conftest import TOKEN


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        operator_token=SecretStr(TOKEN),
        sim_turn_delay_ms=0,
        live_calls_enabled=True,
        calling_start="00:00",
        calling_end="24:00",
        calling_days=list(range(7)),
        livekit_url="wss://example.invalid",
        livekit_api_key=SecretStr("k"),
        livekit_api_secret=SecretStr("s"),
        livekit_sip_outbound_trunk_id="ST_test",
        sip_caller_number="2211",
        jaiasr_api_key=SecretStr("a"),
        soniox_api_key=SecretStr("so"),
        jaitts_api_key=SecretStr("t"),
        google_api_key=SecretStr("g"),
    )


def live_body() -> dict[str, Any]:
    return {
        "campaign": "accident_survey",
        "target_name": "สมชาย ใจดี",
        "phone": "081-234-5678",
        "mode": "live",
        "source": {"type": "profile", "profile_id": "survey-surveyor"},
    }


async def queue_live_call(client: AsyncClient) -> str:
    r = await client.post("/api/v1/calls", json=live_body(), headers={"Idempotency-Key": "live-0001"})
    assert r.status_code == 201, r.text
    return str(r.json()["call_id"])


def test_sip_statuses_map_to_dial_results() -> None:
    assert classify_sip(486) is DialResult.BUSY
    assert classify_sip(480) is DialResult.NO_ANSWER
    assert classify_sip(603) is DialResult.REJECTED
    assert classify_sip(404) is DialResult.UNREACHABLE
    assert classify_sip(503) is DialResult.TECHNICAL_FAILURE
    assert classify_sip(None) is DialResult.TECHNICAL_FAILURE


def test_phone_calls_need_every_setting() -> None:
    bare = Settings(_env_file=None, operator_token=SecretStr(TOKEN))  # type: ignore[call-arg]
    assert "LIVEKIT_SIP_OUTBOUND_TRUNK_ID" in bare.livekit_missing()


class FakePhone:
    """Stands in for `telephony.PhoneCall`; `script` decides what the call does."""

    instances: ClassVar[list[FakePhone]] = []

    def __init__(self, settings: Settings, engine: Any, dialogue: Dialogue, **kw: Any) -> None:
        self.engine, self.kw = engine, kw
        FakePhone.instances.append(self)

    async def run(self) -> CallEnd:
        return await self.script(self)  # type: ignore[attr-defined, no-any-return]


def fake(script: Any) -> type[FakePhone]:
    FakePhone.instances = []
    return type("Scripted", (FakePhone,), {"script": staticmethod(script)})


async def test_live_call_is_queued_without_a_script(client: AsyncClient) -> None:
    call_id = await queue_live_call(client)
    detail = (await client.get(f"/api/v1/calls/{call_id}")).json()
    assert detail["mode"] == "live" and detail["phone"]["sip_destination"] == "0812345678"


async def test_busy_line_is_reported_once_and_never_redialled(
    client: AsyncClient, store: Store, settings: Settings
) -> None:
    call_id = await queue_live_call(client)
    worker = Worker(store, settings, "w1")

    async def busy(phone: FakePhone) -> CallEnd:
        await phone.kw["on_ringing"]()
        return CallEnd(DialResult.BUSY, False, "sip_486", 486, "Busy Here")

    worker.phone_factory = fake(busy)
    assert await worker.process_once()
    assert not await worker.process_once()  # nothing left to dial: no automatic retry
    assert len(FakePhone.instances) == 1
    assert FakePhone.instances[0].kw["sip_call_to"] == "0812345678"
    assert FakePhone.instances[0].kw["room_name"] == f"kpi-{call_id}"
    detail = (await client.get(f"/api/v1/calls/{call_id}")).json()
    assert detail["outcome"] == "not_reached" and detail["dial_result"] == "busy"
    assert "ringing" in [e["type"] for e in detail["events"]]


async def test_failure_after_answer_keeps_what_was_collected(
    client: AsyncClient, store: Store, settings: Settings
) -> None:
    call_id = await queue_live_call(client)
    worker = Worker(store, settings, "w1")

    async def drops(phone: FakePhone) -> CallEnd:
        await phone.kw["on_answered"]()
        phone.engine.start()
        raise ConnectionError("media lost")

    worker.phone_factory = fake(drops)
    await worker.process_once()
    detail = (await client.get(f"/api/v1/calls/{call_id}")).json()
    assert detail["outcome"] == "technical_failure" and detail["dial_result"] == "answered"
    assert not await worker.process_once()


async def test_live_calls_switched_off_after_queueing_are_not_dialled(
    client: AsyncClient, store: Store, settings: Settings
) -> None:
    call_id = await queue_live_call(client)
    worker = Worker(store, settings.model_copy(update={"live_calls_enabled": False}), "w1")
    worker.phone_factory = fake(lambda phone: None)
    await worker.process_once()
    detail = (await client.get(f"/api/v1/calls/{call_id}")).json()
    assert detail["end_reason"] == "live_calls_disabled" and detail["dial_result"] is None
    assert FakePhone.instances == []


# ---- the voice loop, with fake audio in and out ----


class FakePlayer:
    def __init__(self, seconds: float = 0.05) -> None:
        self.seconds = seconds
        self.played: list[str] = []
        self.speaking = False
        self.stopped_at = 0.0
        self.tap: Any = None

    def prefetch(self, prepared: Any) -> None: ...

    def prefetch_directive(self, directive: Directive) -> None: ...

    async def play(self, directive: Directive, n: int, waited_from: float, stop: asyncio.Event | None) -> float:
        self.played.append(directive.text)
        self.speaking = True
        started = time.monotonic()
        try:
            while time.monotonic() - started < self.seconds:
                if stop is not None and stop.is_set():
                    return time.monotonic() - started
                await asyncio.sleep(0.01)
        finally:
            self.speaking, self.stopped_at = False, time.monotonic()
        return self.seconds


class FakeFront:
    speaking = False
    sustained = 0.0  # seconds of speech VAD reports right now

    def capture(self, pcm: bytes) -> bytes:
        return pcm

    def playback(self, pcm: bytes, rate: int) -> None: ...

    def speech_seconds(self) -> float:
        return self.sustained


class FakeASR:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[ASREvent] = asyncio.Queue()

    def say(self, kind: str, text: str) -> None:
        self.queue.put_nowait(ASREvent(kind, text, 0, time.monotonic()))

    async def send(self, pcm: bytes) -> None: ...

    async def events(self) -> AsyncIterator[ASREvent]:
        while True:
            yield await self.queue.get()


class Recorder:
    def __init__(self) -> None:
        self.turns: list[tuple[str, str, bool]] = []

    async def bot(self, directive: Directive, spoken_segments: int, complete: bool) -> None:
        self.turns.append(("bot", directive.key, complete))

    async def customer(self, text: str) -> None:
        self.turns.append(("customer", text, True))

    async def event(self, kind: str, data: dict[str, Any] | None = None) -> None: ...


def phone_session(
    player: FakePlayer, asr: FakeASR, sink: Recorder, front: FakeFront | None = None, **options: Any
) -> tuple[VoiceSession, Any]:
    from kpi_voicebot.campaigns import get_profile

    profile = get_profile("survey-surveyor")
    assert profile is not None
    engine = build_engine(profile.campaign, profile.case, "สมชาย ใจดี")
    session = VoiceSession(
        engine,
        Dialogue(engine),
        player,  # type: ignore[arg-type]
        front or FakeFront(),  # type: ignore[arg-type]
        asr,  # type: ignore[arg-type]
        **{"full_duplex": True, "echo_guard": True, "greet_on_answer": True, **options},
        sink=sink,
        console=False,
    )
    return session, engine


async def wait_until(condition: Any, timeout: float = 3.0) -> None:
    started = time.monotonic()
    while not condition():
        assert time.monotonic() - started < timeout, "timed out"
        await asyncio.sleep(0.01)


def test_picking_up_the_phone_is_not_an_answer() -> None:
    assert voice_session.is_hello("ฮัลโหล")
    assert voice_session.is_hello("สวัสดีครับ")
    assert not voice_session.is_hello("ใช่ครับ")
    assert voice_session.without_hello("ฮัลโหล ใช่ครับ ผมเอง") == "ใช่ครับ ผมเอง"


async def test_bot_greets_at_once_and_a_hello_over_the_greeting_is_set_aside(monkeypatch: Any) -> None:
    monkeypatch.setattr(voice_session, "ANSWER_SETTLE", 0.0)
    player, asr, sink = FakePlayer(seconds=0.3), FakeASR(), Recorder()
    session, engine = phone_session(player, asr, sink)

    async def customer() -> None:
        await wait_until(lambda: player.speaking)
        asr.say("partial", "ฮัลโหล สวัสดีครับ")  # picking up while the bot greets: not cutting in
        await asyncio.sleep(0.05)
        assert player.speaking
        await wait_until(lambda: not player.speaking)
        asr.say("commit", "ฮัลโหล สวัสดีครับ")  # JaiASR commits it just after the greeting ends
        await asyncio.sleep(0.05)
        asr.say("commit", "ใช่ครับ")
        await wait_until(lambda: len(player.played) == 2)
        session.hang_up()

    talk = asyncio.ensure_future(customer())
    started = time.monotonic()
    await asyncio.wait_for(session.run(), 5)
    await talk
    assert sink.turns[0] == ("bot", "greet", True)  # spoken first, whole
    assert sink.turns[1] == ("customer", "ฮัลโหล สวัสดีครับ", True)  # recorded, not taken as the answer
    assert sink.turns[2] == ("customer", "ใช่ครับ", True)
    assert engine.result.identity_result == "confirmed"
    assert time.monotonic() - started < 3


async def test_on_computer_speakers_only_words_cut_in(monkeypatch: Any) -> None:
    """VAD hears the bot's own echo from the speakers, so sustained "speech" alone must not stop it."""
    player, asr, sink, front = FakePlayer(seconds=0.6), FakeASR(), Recorder(), FakeFront()
    session, _engine = phone_session(player, asr, sink, front, greet_on_answer=False, vad_barge_in=False)

    async def echo() -> None:
        await wait_until(lambda: player.speaking)
        front.sustained = 2.0
        asr.say("partial", "ขอเรียนสายคุณสมชาย")  # the bot's own words coming back
        await wait_until(lambda: not player.speaking)
        front.sustained = 0.0
        session.hang_up()

    talk = asyncio.ensure_future(echo())
    await asyncio.wait_for(session.run(), 5)
    await talk
    assert sink.turns[0] == ("bot", "greet", True)


async def test_cutting_in_stops_the_bot_and_counts_only_what_was_heard() -> None:
    player, asr, sink = FakePlayer(seconds=2.0), FakeASR(), Recorder()
    session, _engine = phone_session(player, asr, sink, greet_on_answer=False)

    async def customer() -> None:
        await wait_until(lambda: player.speaking)
        asr.say("partial", "ครับ")  # listening, not cutting in
        await asyncio.sleep(0.1)
        assert player.speaking
        asr.say("partial", "เดี๋ยวนะครับ ไม่ใช่")
        await wait_until(lambda: not player.speaking)
        session.hang_up()

    talk = asyncio.ensure_future(customer())
    started = time.monotonic()
    await asyncio.wait_for(session.run(), 5)
    await talk
    assert time.monotonic() - started < 1.5  # did not talk over the customer for the full 2 s
    assert sink.turns[0] == ("bot", "greet", False)


async def test_a_number_that_asked_not_to_be_called_is_not_called_again(
    client: AsyncClient, store: Store, settings: Settings
) -> None:
    from kpi_voicebot.models import Outcome

    first = await queue_live_call(client)
    await store.finish(
        first, outcome=Outcome.DO_NOT_CALL, dial_result=DialResult.ANSWERED, result=None, end_reason="dnc"
    )
    r = await client.post("/api/v1/calls", json=live_body(), headers={"Idempotency-Key": "live-dnc-02"})
    assert (r.status_code, r.json()["detail"]) == (409, "ลูกค้าเบอร์นี้ขอไม่ให้ติดต่อกลับ (ภายใน 6 เดือน)")
