"""Every scripted scenario must reach its expected outcome and structured result."""

from typing import Any

import pytest

from kpi_voicebot.campaigns import get_profile
from kpi_voicebot.models import Directive
from kpi_voicebot.simulator import build_engine, load_scenarios, run_script

POLICY_SPECIFIC = ("พีเอ เต็มใจ", "300,000", "2,000", "ผู้รับผลประโยชน์", "somchai", "สมใจ", "บัตรเครดิต")


class RecordingSink:
    def __init__(self) -> None:
        self.bot_spoken: list[str] = []
        self.directives: list[Directive] = []

    async def bot(self, directive: Directive, spoken_segments: int, complete: bool) -> None:
        self.directives.append(directive)
        self.bot_spoken.append(" ".join(s.text for s in directive.segments[:spoken_segments]))

    async def customer(self, text: str) -> None:
        return None

    async def event(self, kind: str, data: dict[str, Any] | None = None) -> None:
        return None


@pytest.mark.parametrize("scenario", load_scenarios(), ids=lambda s: s.id)
async def test_scenario(scenario: Any) -> None:
    profile = get_profile(scenario.profile)
    assert profile is not None and profile.campaign == scenario.campaign
    engine = build_engine(scenario.campaign, profile.case, "สมชาย ใจดี")
    sink = RecordingSink()
    await run_script(engine, scenario.customer, sink)
    check_expectations(scenario, engine, sink)


def check_expectations(scenario: Any, engine: Any, sink: RecordingSink) -> None:
    expect = scenario.expect
    result = engine.result

    assert engine.state.finished
    assert engine.outcome == expect["outcome"], sink.bot_spoken
    for name, status in expect.get("fields", {}).items():
        assert next(f for f in result.policy_fields if f.field == name).status == status, name
    for name, delivery in expect.get("delivery", {}).items():
        assert next(f for f in result.policy_fields if f.field == name).delivery == delivery, name
    if "free_look" in expect:
        assert result.free_look_delivery == expect["free_look"]
    for qid, (status, value) in expect.get("answers", {}).items():
        answer = next(a for a in result.survey_answers if a.question == qid)
        assert (answer.status, answer.value) == (status, value), qid
    for qid, text in expect.get("feedback", {}).items():
        assert next(a for a in result.survey_answers if a.question == qid).feedback_raw == text, qid
    for qid, history in expect.get("changed_from", {}).items():
        assert next(a for a in result.survey_answers if a.question == qid).changed_from == history
    task_types = {t.type for t in result.tasks}
    assert set(expect.get("tasks", [])) <= task_types, task_types
    assert not set(expect.get("no_tasks", [])) & task_types, task_types
    keys = [d.key for d in sink.directives]
    for wanted in expect.get("directives", []):
        assert any(k == wanted or k.startswith(wanted + ":") for k in keys), (wanted, keys)
    spoken_all = " ".join(sink.bot_spoken)
    for phrase in expect.get("says", []):
        assert phrase in spoken_all, phrase
    if "callback_time" in expect:
        assert result.callback.preferred_time_text == expect["callback_time"]
    if expect.get("no_disclosure"):
        spoken = " ".join(sink.bot_spoken)
        assert not any(term in spoken for term in POLICY_SPECIFIC), spoken
    # No bot turn may use the male particle; the voice is female.
    assert not any("ครับ" in text for text in sink.bot_spoken)


async def _pa_call(replies: list[str]) -> tuple[Any, RecordingSink]:
    profile = get_profile("pa-email")
    assert profile is not None
    engine = build_engine(profile.campaign, profile.case, "สมชาย ใจดี")
    sink = RecordingSink()
    await run_script(engine, replies, sink)
    return engine, sink


async def test_policy_facts_are_read_like_an_operator_not_a_checklist() -> None:
    """Facts are statements the customer acknowledges; only details they must check are asked."""
    engine, sink = await _pa_call(["ใช่ครับ", "ได้ครับ", "ครับ", *["ครับ"] * 9, "อ่าห้ะ", "ไม่มีครับ"])
    assert engine.outcome.value == "policy_confirmed"
    review = [t for d, t in zip(sink.directives, sink.bot_spoken, strict=True) if d.key.startswith("review:")]
    asked = [t for t in review if t.endswith(("ไหมคะ", "ใช่ไหมคะ"))]
    assert len(asked) == 2, asked  # beneficiary and the e-mail address
    assert sum("ถูกต้องไหมคะ" in t for t in sink.bot_spoken) == 1
    # After a bare "ครับ" the next fact follows directly, with no "ค่ะ / รับทราบค่ะ" in front.
    assert not any(t.startswith(("ค่ะ", "รับทราบ", "ขอบคุณค่ะ")) for t in review)


async def test_a_question_mid_explanation_does_not_become_a_call_back() -> None:
    engine, sink = await _pa_call(["ใช่ครับ", "ได้ครับ", "รายละเอียดอะไรครับ", "ครับ"])
    assert not engine.result.tasks
    assert sink.directives[-1].key == "review:medical"


async def test_off_topic_question_gets_a_polite_no_without_a_task() -> None:
    import dataclasses

    from kpi_voicebot.thai_parse import read_signals

    profile = get_profile("pa-email")
    assert profile is not None
    engine = build_engine(profile.campaign, profile.case, "สมชาย ใจดี")
    engine.state.stage, engine.state.awaiting = "questions", "questions"
    signals = dataclasses.replace(read_signals("1+1 เท่ากับเท่าไหร่"), off_topic=True, question=True)
    directive = engine.handle("1+1 เท่ากับเท่าไหร่", signals)
    assert "เฉพาะเรื่องกรมธรรม์" in directive.text and not engine.result.tasks


def test_asking_about_a_value_already_read_gets_the_value_not_a_callback() -> None:
    from kpi_voicebot.campaigns import get_profile

    profile = get_profile("pa-email")
    assert profile is not None
    engine = build_engine(profile.campaign, profile.case, "สมชาย ใจดี")
    turn = engine.start()
    replies = ["ใช่ครับ", "สะดวกครับ", "ครับ", "ครับ", "ครับ", "วันละเท่าไหร่นะครับ", "ครับ", "ผู้รับผลประโยชน์ใครนะ"]
    said = []
    for text in replies:
        engine.report_delivery(len(turn.segments), True)
        turn = engine.handle(text)
        said.append(turn.text)
    assert "วันละ 500 บาท สูงสุด 30 วัน" in said[5]
    assert "นางสาวสมใจ ใจดี (บุตร)" in said[7]
    assert engine.result.tasks == []  # nothing parked for a call-back


def test_a_question_starting_like_a_yes_is_still_a_question() -> None:
    from kpi_voicebot.thai_parse import read_signals

    for text in ("ค่ารักษาเท่าไหร่นะ", "ได้รับกรมธรรม์เมื่อไหร่"):
        s = read_signals(text)
        assert s.question and not s.affirm
    assert read_signals("ได้ครับ").affirm
