"""JaiASR client and turn-taking, against a local fake server that follows the API document."""

import asyncio
import json
import time

import websockets

from kpi_voicebot.asr import ASRError, ASREvent, JaiASRStream, TurnCollector
from kpi_voicebot.config import Settings
from kpi_voicebot.mic import is_barge_in, segments_heard
from kpi_voicebot.models import Directive, Segment


def settings() -> Settings:
    return Settings(operator_token="t" * 16, jaiasr_api_key="k-test", _env_file=None)  # type: ignore[call-arg, arg-type]


async def fake_server(ws: websockets.ServerConnection) -> None:
    assert ws.request is not None and ws.request.headers["Authorization"] == "Bearer k-test"
    start = json.loads(await ws.recv())
    assert start["type"] == "start" and start["language"] == "Thai" and "สมชาย" in start["context"]
    await ws.send(json.dumps({"type": "ready", "session_id": "s1", "vad_silence_sec": 0.5}))
    received = 0
    async for message in ws:
        if isinstance(message, bytes):
            received += len(message)
            if received == 3200:
                await ws.send(json.dumps({"type": "partial", "segment_id": 0, "text": "ใช่ครับ"}))
            if received == 6400:
                await ws.send(json.dumps({"type": "commit", "segment_id": 0, "text": "ใช่ครับ ผมเอง"}))
        elif json.loads(message)["type"] == "finish":
            await ws.send(json.dumps({"type": "final", "segment_id": 1, "text": ""}))


async def test_stream_follows_the_documented_protocol() -> None:
    async with websockets.serve(fake_server, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        stream = JaiASRStream(settings(), url=f"ws://127.0.0.1:{port}/stream?model=m")
        await stream.open(context="สมชาย ใจดี")
        assert stream.ready["type"] == "ready"
        await stream.send(b"\x00" * 3200)
        await stream.send(b"\x00" * 3200)
        await stream.finish()
        events = [e async for e in stream.events()]
        await stream.close()
    assert [(e.type, e.text) for e in events] == [("partial", "ใช่ครับ"), ("commit", "ใช่ครับ ผมเอง"), ("final", "")]


async def test_a_refused_stream_says_why() -> None:
    async def refuse(ws: websockets.ServerConnection) -> None:
        await ws.close()

    def reject(connection: object, request: object) -> object:
        return connection.respond(403, "forbidden")  # type: ignore[attr-defined]

    async with websockets.serve(refuse, "127.0.0.1", 0, process_request=reject) as server:
        port = server.sockets[0].getsockname()[1]
        stream = JaiASRStream(settings(), url=f"ws://127.0.0.1:{port}/stream")
        try:
            await stream.open()
        except ASRError as exc:
            assert "403" in str(exc)
        else:
            raise AssertionError("expected a refusal")


def event(kind: str, text: str) -> ASREvent:
    return ASREvent(kind, text, 0, time.monotonic())


async def test_short_answer_ends_at_the_commit() -> None:
    collector = TurnCollector()

    async def speak() -> None:
        await asyncio.sleep(0.05)
        collector.feed(event("partial", "ครับ"))
        collector.feed(event("commit", "ครับ"))

    task = asyncio.ensure_future(speak())
    started = time.monotonic()
    assert await collector.next_turn("confirm:medical", silence_timeout=3) == "ครับ"
    assert time.monotonic() - started < 0.5
    await task


async def test_open_answer_waits_for_more_and_joins_the_pieces() -> None:
    collector = TurnCollector(grace=0.4)

    async def speak() -> None:
        collector.feed(event("commit", "ก็โอเคนะครับ"))
        await asyncio.sleep(0.2)  # a short pause mid-thought
        collector.feed(event("partial", "แต่รอสาย"))
        collector.feed(event("commit", "แต่รอสายนานไปหน่อย"))

    task = asyncio.ensure_future(speak())
    assert await collector.next_turn("feedback:q1", silence_timeout=3) == "ก็โอเคนะครับ แต่รอสายนานไปหน่อย"
    await task


async def test_silence_is_reported_as_no_turn() -> None:
    assert await TurnCollector().next_turn("confirm:medical", silence_timeout=0.2) is None


def test_listening_noises_are_not_a_barge_in() -> None:
    assert not is_barge_in("ครับ")
    assert not is_barge_in("อืม")
    assert is_barge_in("เดี๋ยวนะครับ ไม่ใช่")


def test_only_segments_actually_heard_count_after_a_cut() -> None:
    turn = Directive(
        key="t",
        segments=[Segment(text="ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง"), Segment(text="15,000 บาทค่ะ")],
    )
    assert segments_heard(turn, 1.0) == 0
    assert segments_heard(turn, 3.2) == 1
    assert segments_heard(turn, 10.0) == 2


async def test_front_end_cleans_audio_and_hears_speech_start_and_end() -> None:
    """Real WebRTC processing and Silero VAD on a short Thai phrase (JAI TTS, fictional words)."""
    import wave
    from pathlib import Path

    from kpi_voicebot.audio import FRAME_BYTES, VoiceFrontEnd

    with wave.open(str(Path(__file__).parent / "fixtures" / "speech_th_16k.wav")) as w:
        speech = w.readframes(w.getnframes())
    signal = b"\x00\x00" * 8000 + speech + b"\x00\x00" * 16000  # silence, phrase, silence
    events: list[bool] = []
    front = VoiceFrontEnd(echo_cancellation=False, on_speech=events.append)
    await front.start()
    cleaned = bytearray()
    for i in range(0, len(signal), FRAME_BYTES):
        cleaned += front.capture(signal[i : i + FRAME_BYTES])
        await asyncio.sleep(0.001)
    for _ in range(40):
        if events[-1:] == [False]:
            break
        await asyncio.sleep(0.05)
    await front.close()
    assert len(cleaned) == len(signal) // FRAME_BYTES * FRAME_BYTES
    assert events[:1] == [True] and events[-1] is False


def test_the_bots_own_voice_coming_back_is_not_the_customer() -> None:
    from kpi_voicebot.audio import echo_of

    bot = "ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง หนึ่งหมื่นห้าพันบาทค่ะ"
    assert echo_of("ค่ารักษาพยาบาลต่ออุบัติเหตุ", bot)
    assert not echo_of("ไม่ใช่ครับ ผมได้สามหมื่น", bot)
    assert not echo_of("ครับ", bot)  # too short to judge: treated as the customer


async def soniox_server(ws: websockets.ServerConnection) -> None:
    config = json.loads(await ws.recv())
    assert config["api_key"] == "so-test" and config["audio_format"] == "pcm_s16le"
    assert config["enable_endpoint_detection"] and "th" in config["language_hints"]
    assert "สมชาย ใจดี" in config["context"]["terms"]  # biases recognition; never transcribed
    await ws.recv()  # audio
    send = ws.send
    await send(json.dumps({"tokens": [{"text": "ใช่", "is_final": True}, {"text": "ครับ", "is_final": False}]}))
    await send(json.dumps({"tokens": [{"text": "ครับ", "is_final": True}, {"text": "<end>", "is_final": True}]}))
    await send(json.dumps({"tokens": [{"text": "ผม", "is_final": False}]}))
    assert await ws.recv() == ""  # an empty frame ends the stream
    await send(json.dumps({"tokens": [{"text": "ผมเอง", "is_final": True}], "finished": True}))


async def test_soniox_stream_turns_tokens_into_partials_and_commits() -> None:
    from pydantic import SecretStr

    from kpi_voicebot.soniox_asr import SonioxStream

    async with websockets.serve(soniox_server, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        s = settings().model_copy(update={"soniox_api_key": SecretStr("so-test")})
        stream = SonioxStream(s, url=f"ws://127.0.0.1:{port}")
        await stream.open(context="น้องเคพีไอ, สมชาย ใจดี")
        await stream.send(b"\x00" * 3200)
        events: list[tuple[str, str]] = []

        async def read() -> None:
            async for e in stream.events():
                events.append((e.type, e.text))
                if e.type == "partial" and e.text == "ผม":
                    await stream.finish()

        await asyncio.wait_for(read(), 3)
        await stream.close()
    assert events == [
        ("partial", "ใช่ครับ"),
        ("commit", "ใช่ครับ"),
        ("partial", "ผม"),
        ("final", "ผมเอง"),
    ]
