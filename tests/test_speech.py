"""Speech-facing behaviour: Thai normalisation, greetings, holds, audio cache and length checks."""

from collections.abc import AsyncIterator
from pathlib import Path

from kpi_voicebot.campaigns import get_profile
from kpi_voicebot.simulator import build_engine
from kpi_voicebot.tts import Speaker, TurnCache, fidelity
from kpi_voicebot.tts_text import number_words, speakable


def test_thai_numbers() -> None:
    assert [number_words(n) for n in (0, 11, 21, 101, 2000, 15000, 300000, 2569, 1_250_000)] == [
        "ศูนย์",
        "สิบเอ็ด",
        "ยี่สิบเอ็ด",
        "หนึ่งร้อยเอ็ด",
        "สองพัน",
        "หนึ่งหมื่นห้าพัน",
        "สามแสน",
        "สองพันห้าร้อยหกสิบเก้า",
        "หนึ่งล้านสองแสนห้าหมื่น",
    ]


def test_speakable_reads_like_a_thai_agent() -> None:
    assert speakable("วงเงิน 300,000 บาท") == "วงเงิน สามแสน บาท"
    assert speakable("เวลา 00.01 น. เป็นต้นไป") == "เวลา เที่ยงคืนหนึ่งนาที เป็นต้นไป"
    assert speakable("โทร 02-624-1111") == "โทร ศูนย์สอง หกสองสี่ หนึ่งหนึ่งหนึ่งหนึ่ง"
    assert speakable("โทร 02 624 1111") == "โทร ศูนย์สอง หกสองสี่ หนึ่งหนึ่งหนึ่งหนึ่ง"
    assert speakable("somchai.demo@example.com") == "เอส โอ เอ็ม ซี เอช เอ ไอ ดอท ดี อี เอ็ม โอ แอท เอ็กแซมเปิล ดอท คอม"
    assert speakable("nida_99@gmail.com") == "เอ็น ไอ ดี เอ อันเดอร์สกอร์ เก้า เก้า แอท จีเมล ดอท คอม"
    assert speakable("เว็บไซต์ www.kpi.co.th ค่ะ") == "เว็บไซต์ เคพีไอ ดอท ซีโอ ดอท ทีเอช ค่ะ"
    assert speakable("จำกัด (มหาชน) ค่ะ") == "จำกัด มหาชน ค่ะ"
    assert speakable("เป็น AI ผู้ช่วย ชำระผ่าน QR Code") == "เป็น เอไอ ผู้ช่วย ชำระผ่าน คิวอาร์โค้ด"


def test_greeting_is_not_identity_confirmation() -> None:
    profile = get_profile("pa-email")
    assert profile is not None
    engine = build_engine(profile.campaign, profile.case, "สมชาย ใจดี")
    engine.start()
    engine.report_delivery(1, True)
    reply = engine.handle("ดีครับ")
    assert reply.key == "clarify" and "ใช่ไหมคะ" in reply.text
    engine.report_delivery(len(reply.segments), True)
    assert engine.handle("ใช่ครับ").key.startswith("intro")


def test_second_hold_sounds_different() -> None:
    profile = get_profile("pa-email")
    assert profile is not None
    engine = build_engine(profile.campaign, profile.case, "สมชาย ใจดี")
    for text in ["ใช่ครับ", "ได้ครับ", "ครับ"]:
        d = engine.start() if text == "ใช่ครับ" and engine.state.turn == 0 else None
        if d:
            engine.report_delivery(len(d.segments), True)
        d = engine.handle(text)
        engine.report_delivery(len(d.segments), True)
    first = engine.handle("รอแป๊บนะครับ")
    engine.report_delivery(len(first.segments), True)
    second = engine.handle("เดี๋ยวนะครับ")
    assert first.text != second.text


def test_fidelity_spots_a_voice_that_left_the_script() -> None:
    script = "ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง หนึ่งหมื่นห้าพัน บาทค่ะ"
    assert fidelity(script, script.replace(" ", "")) == 1.0
    assert fidelity(script, "หนึ่งบวกหนึ่งเท่ากับสองค่ะ") < 0.9


def test_turn_cache_round_trip(tmp_path: Path) -> None:
    cache = TurnCache(tmp_path, "m", "v", "style")
    assert cache.get("สวัสดี") is None
    cache.put("สวัสดี", b"\x01\x02")
    assert cache.get("สวัสดี") == b"\x01\x02"
    assert TurnCache(tmp_path, "m", "v", "other style").get("สวัสดี") is None


class _FakeVoice:
    sample_rate = 24_000

    def __init__(self, heard: str, seconds: list[float] | None = None) -> None:
        self.heard = heard
        self.seconds = seconds or [3.0]
        self.calls = 0
        self.last_heard = ""

    async def stream(self, spoken: str) -> AsyncIterator[bytes]:
        length = self.seconds[min(self.calls, len(self.seconds) - 1)]
        self.calls += 1
        yield b"\x01\x00" * int(24_000 * length)
        self.last_heard = self.heard or spoken


async def test_only_verbatim_readings_are_cached(tmp_path: Path) -> None:
    cache = TurnCache(tmp_path, "m", "v", "s")
    good = Speaker(_FakeVoice(""), cache)  # type: ignore[arg-type]
    await good.render("เบี้ยประกันภัย 2,000 บาทต่อปีค่ะ")
    assert cache.get(speakable("เบี้ยประกันภัย 2,000 บาทต่อปีค่ะ")) is not None

    drifted = Speaker(_FakeVoice("ได้เลยค่ะ ยินดีช่วยเหลือค่ะ"), cache)  # type: ignore[arg-type]
    await drifted.render("ผู้รับผลประโยชน์ คือ นางสาวสมใจ ใจดี ใช่ไหมคะ")
    assert drifted.last_fidelity is not None and drifted.last_fidelity < 0.9
    assert cache.get(speakable("ผู้รับผลประโยชน์ คือ นางสาวสมใจ ใจดี ใช่ไหมคะ")) is None


async def test_a_dropped_reading_is_said_again(tmp_path: Path) -> None:
    line = "เมื่อคุณลูกค้าได้รับกรมธรรม์แล้ว หากตรวจสอบแล้วไม่ตรงกับความต้องการ สามารถแจ้งยกเลิกได้ภายใน 30 วัน"
    voice = _FakeVoice("", seconds=[0.8, 9.0])
    speaker = Speaker(voice, TurnCache(tmp_path, "m", "v", "s"))  # type: ignore[arg-type]
    await speaker.render(line)
    assert voice.calls == 2 and speaker.last_retried


def test_turns_go_to_jai_tts_whole_and_only_very_long_ones_are_split() -> None:
    from kpi_voicebot.jaitts import clauses

    turn = speakable(
        "ดิฉัน น้องเคพีไอ เป็น AI ผู้ช่วย ติดต่อจาก บริษัท กรุงไทยพานิชประกันภัย จำกัด (มหาชน) ค่ะ "
        "วันนี้โทรมาเพื่อขอบคุณ และยืนยันความคุ้มครองกรมธรรม์ที่คุณลูกค้าได้ตกลงทำไว้ค่ะ รบกวนเวลาประมาณ 3 ถึง 5 นาที สะดวกไหมคะ"
    )
    assert clauses(turn) == [turn]  # one request: one continuous melody
    parts = clauses(turn, limit=120)
    assert len(parts) == 3 and parts[-1].endswith("สะดวกไหมคะ")
    assert " ".join(parts) == turn
    assert all(len(p) <= 160 for p in clauses("ก" * 400, limit=160))


async def test_jai_voice_joins_split_samples_and_streams_clauses_in_order() -> None:
    import httpx

    from kpi_voicebot.config import Settings
    from kpi_voicebot.jaitts import JaiVoice

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        seen.append(body["target_text"])
        assert request.headers["X-API-Key"] == "k" and body["response_format"] == "pcm"
        return httpx.Response(200, stream=httpx.ByteStream(b"\x01\x00\x02\x00\x03\x00\x04\x00"))

    settings = Settings(operator_token="t" * 16, jaitts_api_key="k", _env_file=None)  # type: ignore[call-arg, arg-type]
    voice = JaiVoice(settings)
    voice._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"X-API-Key": "k"})
    from kpi_voicebot import jaitts

    jaitts.MAX_CLAUSE_CHARS = 20  # force several requests to check they stream in order
    try:
        pcm = b"".join([c async for c in voice.stream("สวัสดีค่ะ คุณสมชาย ขอเรียนสายค่ะ ตอนนี้สะดวกไหมคะ")])
    finally:
        jaitts.MAX_CLAUSE_CHARS = 500
    assert len(pcm) % 2 == 0 and len(pcm) == 8 * len(seen)
    assert seen[0].startswith("สวัสดีค่ะ") and seen[-1].endswith("สะดวกไหมคะ")
    await voice.close()


def test_times_are_read_the_way_thai_people_say_them() -> None:
    from kpi_voicebot.tts_text import clock_words

    assert [
        clock_words(h, m) for h, m in [(0, 1), (0, 0), (3, 0), (8, 30), (12, 0), (13, 0), (14, 0), (17, 0), (19, 15)]
    ] == [
        "เที่ยงคืนหนึ่งนาที",
        "เที่ยงคืน",
        "ตีสาม",
        "แปดโมงครึ่ง",
        "เที่ยงวัน",
        "บ่ายโมง",
        "บ่ายสองโมง",
        "ห้าโมงเย็น",
        "หนึ่งทุ่มสิบห้านาที",
    ]


def test_no_latin_script_reaches_the_thai_voice() -> None:
    import re

    assert not re.search(r"[A-Za-z]", speakable("ดาวน์โหลด Excel หรือแอด LINE ได้ค่ะ ZX9"))
