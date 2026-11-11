"""The engine lab (5 Nov 2026): the lab key, the engine choice, the speech-to-speech prompt, and the
result read back from a lab call's transcript."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from kpi_voicebot.agent import CallAgent
from kpi_voicebot.api import create_app
from kpi_voicebot.campaigns import load_profiles
from kpi_voicebot.config import Settings
from kpi_voicebot.models import CampaignId, Outcome
from kpi_voicebot.realtime import instructions, read_result
from kpi_voicebot.simulator import build_engine
from kpi_voicebot.store import Store
from tests.conftest import TOKEN
from tests.test_api import call_body

LAB = "test-lab-operator-token"


@pytest.fixture
async def lab(store: Store) -> AsyncIterator[AsyncClient]:
    settings = Settings(operator_token=TOKEN, lab_operator_token=LAB, _env_file=None)  # type: ignore[call-arg]
    app = create_app(settings, store)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": "key-00000001"}


async def test_the_lab_key_unlocks_the_engine_selector(lab: AsyncClient) -> None:
    operator = (await lab.get("/api/v1/system/status", headers=auth(TOKEN))).json()
    assert operator["role"] == "operator" and operator["engines"] is None
    status = (await lab.get("/api/v1/system/status", headers=auth(LAB))).json()
    assert status["role"] == "lab"
    assert [e["id"] for e in status["engines"]] == ["pipeline", "gemini_live", "agni"]
    assert {e["id"]: e["ready"] for e in status["engines"]} == {"pipeline": True, "gemini_live": False, "agni": False}
    # The lab key is an operator key too.
    assert (await lab.get("/api/v1/calls", headers=auth(LAB))).status_code == 200


async def test_only_the_lab_key_picks_an_engine(lab: AsyncClient) -> None:
    r = await lab.post("/api/v1/calls", json=call_body(engine="agni"), headers=auth(TOKEN))
    assert r.status_code == 403
    # Speech-to-speech is for live calls only; the simulation has no audio to give an engine.
    r = await lab.post("/api/v1/calls", json=call_body(engine="gemini_live"), headers=auth(LAB))
    assert r.status_code == 422
    r = await lab.post("/api/v1/calls", json=call_body(), headers=auth(LAB))
    assert r.status_code == 201 and r.json()["engine"] == "pipeline"


async def test_without_a_lab_key_there_is_no_lab(client: AsyncClient) -> None:
    status = (await client.get("/api/v1/system/status")).json()
    assert status["role"] == "operator" and status["engines"] is None


def survey_agent() -> CallAgent:
    case = next(p for p in load_profiles() if p.profile_id == "survey-surveyor")
    return CallAgent(build_engine(CampaignId.ACCIDENT_SURVEY, case.case, "สมชาย ใจดี"), None)


@pytest.mark.parametrize("engine", ["gemini_live", "agni"])
def test_the_engine_prompt_has_the_call_without_the_pipeline_codes(engine: Any) -> None:
    agent = survey_agent()
    text = instructions(agent, engine)
    for code in ("SAY:", "UPDATE", "FOLLOW_UP", "END:", "หมายเหตุ"):
        assert code not in text
    assert agent.notice_text in text  # the recording notice word for word
    assert "คุณสมชาย ใจดี" in text and "CLM-MOCK" in text  # this call's facts
    assert "q5" in text and "ถ้าได้ไม่เกิน 8 ให้ถามเหตุผล" in text  # the survey and its ask-why rule
    assert "ถ้าลูกค้าพูดแทรก" in text  # the interruption manners survive the filter
    assert "end_call" in text  # Gemini's tool, Agni's dashboard function: both named
    # Agni has its own speed setting and was "too fast" with ours on top (5 Nov); Gemini keeps it.
    assert ("เร็วกว่าปกติ" in text) == (engine == "gemini_live")
    assert "ห้ามเติมรายละเอียดที่ไม่ได้เขียนไว้" in text  # "ไม่จำกัดจำนวนครั้งต่อปี" was made up (5 Nov)
    assert 'อ่านว่า "สามแสน' not in text  # the survey has no amounts; see the PA test for spoken forms


def test_facts_come_with_how_they_are_said() -> None:
    case = next(p for p in load_profiles() if p.profile_id == "pa-email")
    agent = CallAgent(build_engine(CampaignId.PA_CONFIRMATION, case.case, "สมชาย ใจดี"), None)
    text = instructions(agent, "gemini_live")
    assert 'อ่านว่า "สามแสน บาท"' in text
    assert "เที่ยงคืนหนึ่งนาที" in text
    assert "เอส โอ เอ็ม ซี เอช" in text  # the e-mail, letter by letter
    assert 'ชื่อ "สมชาย" นามสกุล "ใจดี"' in text


def test_agni_goodbye_is_recognised() -> None:
    from kpi_voicebot.realtime import FAREWELL

    assert FAREWELL.search("ขอบพระคุณมากนะคะ ขอให้มีวันที่ดีนะคะ สวัสดีค่ะ")
    assert FAREWELL.search("ที่สละเวลา รับสาย สวัสดีค่ะ")
    assert not FAREWELL.search("สวัสดีค่ะ ขออนุญาตเรียนสายกับคุณสมชาย ใจดี ค่ะ")  # the greeting is not a goodbye


class Reader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.messages: list[dict[str, str]] = []

    async def chat_text(self, messages: list[dict[str, str]], **_: Any) -> tuple[str, dict[str, Any]]:
        self.messages = messages
        return self.text, {}


async def test_the_result_is_read_from_the_transcript(settings: Settings) -> None:
    agent = survey_agent()
    history = [
        ("bot", "สวัสดีค่ะ ขออนุญาตเรียนสายกับคุณสมชาย ใจดี ค่ะ"),
        ("customer", "ครับ"),
        ("bot", f"ดิฉันน้องเคพีไอ ผู้ช่วย AI ค่ะ {agent.notice_text}"),
        ("customer", "ได้ครับ"),
        ("customer", "ข้อแรกให้ 2 เพราะโทรติดยาก ข้อสองสี่ ข้อสามห้า ข้อสี่ห้า ข้อห้าเก้า"),
        ("customer", "ไม่มีแล้วครับ"),
        ("bot", "ขอบพระคุณค่ะ สวัสดีค่ะ"),
    ]
    reader = Reader(
        "UPDATE: identity confirmed | ครับ\n"
        "UPDATE: recording granted | ได้ครับ\n"
        "UPDATE: q1 answered 2 | ให้ 2 เพราะโทรติดยาก\n"
        "UPDATE: q1 feedback | โทรติดยาก\n"
        "UPDATE: q2 answered 4 | สี่\nUPDATE: q3 answered 5 | ห้า\nUPDATE: q4 answered 5 | ห้า\n"
        "UPDATE: q5 answered 9 | เก้า\n"
        "UPDATE: final_comment done | ไม่มีแล้วครับ\n"
        "END: completed"
    )
    await read_result(settings, agent, history, ended_by="completed", client=reader)
    assert "บทถอดเสียง" in reader.messages[1]["content"]
    assert agent.result.identity_result == "confirmed" and agent.result.recording_consent is True
    answers = {a.question: a for a in agent.result.survey_answers}
    assert [answers[q].value for q in ("q1", "q2", "q3", "q4", "q5")] == [2, 4, 5, 5, 9]
    assert answers["q1"].feedback_raw == "โทรติดยาก"
    assert agent.outcome is Outcome.SURVEY_COMPLETED and agent.result.end_reason == "completed"


async def test_a_declined_recording_read_afterwards_still_drops_the_audio(settings: Settings) -> None:
    agent = survey_agent()
    dropped: list[bool] = []

    async def discard() -> None:
        dropped.append(True)

    agent.on_recording_declined = discard
    history = [("bot", f"น้องเคพีไอค่ะ {agent.notice_text}"), ("customer", "ไม่ยินยอมครับ")]
    reader = Reader("UPDATE: identity confirmed | ครับ\nUPDATE: recording declined | ไม่ยินยอมครับ\nEND: none")
    await read_result(settings, agent, history, ended_by="customer_hung_up", client=reader)
    assert agent.result.recording_consent is False and dropped == [True]
    assert agent.outcome is Outcome.SURVEY_PARTIAL and agent.result.end_reason == "customer_hung_up"


async def test_a_call_with_no_customer_words_is_not_sent_to_the_reader(settings: Settings) -> None:
    agent = survey_agent()
    reader = Reader("END: completed")
    await read_result(settings, agent, [("bot", "สวัสดีค่ะ")], ended_by="customer_hung_up", client=reader)
    assert reader.messages == [] and agent.outcome is Outcome.HUNG_UP_EARLY


def test_each_engine_gets_its_own_wording_rules_on_one_politeness_core() -> None:
    agent = survey_agent()
    agni, gemini = instructions(agent, "agni"), instructions(agent, "gemini_live")
    # Both: the 19 Oct Thai phone politeness research, beyond what the pipeline's prompt says.
    for text in (agni, gemini):
        assert "มารยาทภาษาไทยทางโทรศัพท์" in text and "ห้ามซ้อนเกินสองคำ" in text
    # Agni: no checks after it, harsh words on 5-11 Nov ("พอดี…", "…เลยนะคะ", bare questions): words to avoid
    # and the line to say at each step.
    assert "คำที่ห้ามใช้" in agni and '"พอดี…"' in agni and "ตัวอย่างประโยค" in agni
    assert "ไม่ทราบว่าคุณสมชายให้กี่คะแนนคะ" in agni
    assert "record" not in agni.split("ข้อมูลของสายนี้")[0]  # no tool it cannot call
    # Gemini: the conductor gives it the steps; its rules are about not sounding scripted.
    assert "ไม่แข็งเหมือนอ่านสคริปต์" in gemini and "เรียก record ก่อนพูดตอบ" in gemini
    assert "คำที่ห้ามใช้" not in gemini


def test_agni_calls_a_garage_tang_oo_and_never_khun() -> None:
    case = next(p for p in load_profiles() if p.profile_id == "garage-three-cars")
    agent = CallAgent(build_engine(CampaignId.GARAGE_FOLLOWUP, case.case, "ช่างเอก"), None)
    text = instructions(agent, "agni")
    examples = text[text.index("ตัวอย่างประโยค") : text.index("การปิดสาย")]
    assert "ขอบพระคุณทางอู่มากค่ะ" in examples and "สะดวก" not in examples
    assert "ขอบพระมาก" not in text  # a crude "คุณ" removal once cut ขอบพระคุณ in half
