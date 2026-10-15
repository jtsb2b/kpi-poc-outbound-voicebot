"""Natural replies: the model may reword a turn, but never its facts, disclosures or persona."""

from typing import Any

import pytest

from kpi_voicebot.campaigns import get_profile
from kpi_voicebot.dialogue import Dialogue
from kpi_voicebot.engine import BaseEngine
from kpi_voicebot.models import Directive
from kpi_voicebot.responder import Responder, check, misspelling
from kpi_voicebot.simulator import build_engine
from tests.test_llm import client_returning


def pa_engine_at_medical() -> tuple[BaseEngine, Directive]:
    profile = get_profile("pa-email")
    assert profile is not None
    engine = build_engine(profile.campaign, profile.case, "สมชาย ใจดี")
    draft = engine.start()
    while draft.key != "review:medical":
        engine.report_delivery(len(draft.segments), True)
        draft = engine.handle("ครับ")
    return engine, draft


def reply(*segments: str, answered: bool = False) -> dict[str, Any]:
    return {"segments": list(segments), "answered_from_facts": answered}


GOOD = "ส่วนค่ารักษาพยาบาล ต่ออุบัติเหตุแต่ละครั้ง อยู่ที่ 15,000 บาทนะคะ"


def test_a_natural_rewording_with_every_value_passes() -> None:
    engine, draft = pa_engine_at_medical()
    assert check(engine, draft, [GOOD], "ครับ") is None


@pytest.mark.parametrize(
    ("segments", "problem"),
    [
        (["ค่ารักษาพยาบาลต่อครั้ง หนึ่งหมื่นห้าพันบาทนะคะ"], "missing value"),
        (["ค่ารักษาพยาบาลต่อครั้ง 15,000 บาท สูงสุด 3 ครั้งต่อปีนะคะ"], "invented number"),
        (["ค่ารักษาพยาบาลต่อครั้ง 15,000 บาทครับ"], "persona"),
        (["น้องขอแจ้งค่ารักษาพยาบาลต่อครั้ง 15,000 บาทนะคะ"], "persona"),
        (["ค่ารักษาพยาบาลต่อครั้ง 15,000 บาท คุ้มครองทุกกรณีนะคะ"], "unapproved claim"),
        (["ค่ารักษาพยาบาลต่อครั้ง 15,000 บาทนะคะ", "ค่ารักษาพยาบาลต่อครั้ง 15,000 บาทนะคะ"], "repeated"),
        (["ค่ารักษาพยาบาลต่อครั้ง 15,000 บาท ถูกต้องไหมคะ"], "added a question"),
    ],
)
def test_guard_rejects(segments: list[str], problem: str) -> None:
    engine, draft = pa_engine_at_medical()
    found = check(engine, draft, segments, "ครับ")
    assert found is not None and problem in found


def test_disclosures_stay_word_for_word() -> None:
    engine, _ = pa_engine_at_medical()
    notice = engine._seg("notice")
    draft = Directive(key="notice", segments=[*notice, *engine._seg("review_intro")], expects="continue")
    reworded = ["ขอแจ้งว่าสายนี้มีการบันทึกเสียงนะคะ", "ต่อไปขอทวนรายละเอียดกรมธรรม์นะคะ"]
    assert "verbatim" in (check(engine, draft, reworded, "ได้ครับ") or "")
    kept = ["ขอบคุณค่ะ", notice[0].text, "ต่อไปขอทวนรายละเอียดกรมธรรม์ของคุณลูกค้านะคะ"]
    assert check(engine, draft, kept, "ได้ครับ") is None


def test_dropped_thai_marks_are_caught() -> None:
    known = ["ผู้รับผลประโยชน์ที่คุณลูกค้าระบุไว้ คือ นางสาวสมใจ ใจดี (บุตร) ใช่ไหมคะ"]
    assert misspelling(["ผุ้รับผลประโยชน์ที่คณลูกคาระบุไว้ ใชไหมคะ"], known)
    assert misspelling(["ขอบคุณค่ะ ผู้รับผลประโยชน์ที่ระบุไว้ เป็นลูกสาว ใช่ไหมคะ"], known) is None


async def test_rejected_or_failed_generation_falls_back_to_the_approved_draft() -> None:
    engine, draft = pa_engine_at_medical()
    bad = Responder(client_returning([reply("ค่ารักษา หนึ่งหมื่นห้าพันบาทค่ะ")]))
    result = await bad.respond(engine, draft, "ครับ")
    assert not result.generated and result.directive == draft


async def test_generated_turn_keeps_fact_tracking() -> None:
    engine, draft = pa_engine_at_medical()
    result = await Responder(client_returning([reply("ได้เลยค่ะ", GOOD)])).respond(engine, draft, "ครับ")
    assert result.generated
    assert result.directive.segments[1].facts == ["medical_per_accident"]
    assert result.directive.expects == draft.expects


async def test_question_answered_from_the_facts_needs_no_call_back() -> None:
    profile = get_profile("pa-email")
    assert profile is not None
    engine = build_engine(profile.campaign, profile.case, "สมชาย ใจดี")
    engine.state.stage, engine.state.awaiting = "questions", "questions"
    answer = reply("เบี้ยประกันภัย 2,000 บาทต่อปีค่ะ", "มีเรื่องอื่นที่อยากสอบถามเพิ่มเติมไหมคะ", answered=True)
    dialogue = Dialogue(engine, responder=Responder(client_returning([answer])))
    directive = await dialogue.reply("ผมจ่ายเบี้ยเท่าไหร่นะ")
    assert "2,000" in directive.text
    assert not [t for t in engine.result.tasks if t.type == "question_follow_up"]


async def test_plain_acknowledgement_uses_the_turn_prepared_in_advance() -> None:
    engine, _ = pa_engine_at_medical()
    engine.report_delivery(99, True)
    calls: list[dict[str, Any]] = []
    prepared = reply("แล้วก็มีเงินชดเชยรายได้ระหว่างนอนโรงพยาบาล วันละ 500 บาท สูงสุด 30 วันนะคะ")
    dialogue = Dialogue(engine, responder=Responder(client_returning([prepared], calls)))
    dialogue.prepare_next()
    directive = await dialogue.reply("ครับ")
    assert len(calls) == 1 and "นอนโรงพยาบาล" in directive.text
    assert ("reply_prepared", {}) in dialogue.events


def test_knowledge_base_facts_may_be_used_but_not_stretched() -> None:
    engine, draft = pa_engine_at_medical()
    ok = [GOOD, "ถ้าต้องการยกเลิก แจ้งได้ภายใน 30 วันนับจากวันที่ได้รับกรมธรรม์ค่ะ"]
    assert check(engine, draft, ok, "ยกเลิกได้กี่วันครับ") is None
    stretched = [GOOD, "เคลมได้สูงสุด 3 ครั้งต่อปีค่ะ"]  # "3" exists in the knowledge only as "3 ถึง 5 นาที"
    assert (check(engine, draft, stretched, "ครับ") or "").startswith("invented number")


def test_a_limiting_word_passes_only_as_an_approved_phrase() -> None:
    engine, draft = pa_engine_at_medical()
    approved = [GOOD, "ส่วนการแก้ไขข้อมูล ดิฉันแก้ในสายไม่ได้ค่ะ"]
    assert check(engine, draft, approved, "แก้ที่อยู่ได้ไหมครับ") is None
    invented = [GOOD, "แผนนี้ส่งทางอีเมลเท่านั้นค่ะ"]
    assert (check(engine, draft, invented, "ครับ") or "").startswith("unapproved claim")


def test_links_and_markdown_are_never_spoken() -> None:
    engine, draft = pa_engine_at_medical()
    assert check(engine, draft, [GOOD, "ดูได้ที่ [www.kpi.co.th](https://www.kpi.co.th) ค่ะ"], "ครับ") == "markup"


def test_a_disclosure_is_not_moved_behind_what_follows_it() -> None:
    from kpi_voicebot.models import Directive, Segment

    engine, _ = pa_engine_at_medical()
    notice = "ขอแจ้งให้ทราบว่า การสนทนานี้จะถูกบันทึกเสียง เพื่อรักษาผลประโยชน์ของคุณลูกค้า และใช้ปรับปรุงคุณภาพการให้บริการนะคะ"
    lead = "ต่อไปขออนุญาตทวนรายละเอียดกรมธรรม์ที่คุณลูกค้าทำไว้นะคะ"
    draft = Directive(
        key="notice", segments=[Segment(text=notice, verbatim=True), Segment(text=lead)], expects="continue"
    )
    assert check(engine, draft, ["ได้ค่ะ", notice, lead], "สะดวกครับ") is None
    assert check(engine, draft, [f"ได้ค่ะ {lead}", notice], "สะดวกครับ") == "disclosure moved"
