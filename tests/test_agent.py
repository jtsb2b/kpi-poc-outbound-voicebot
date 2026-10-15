"""The LLM-led agent with a scripted fake model: the rules the code keeps, whatever the model says."""

from typing import Any

from kpi_voicebot.agent import AgentDialogue, CallAgent, parse_turn, tidy
from kpi_voicebot.campaigns import get_profile
from kpi_voicebot.models import Outcome
from kpi_voicebot.simulator import build_engine


class FakeModel:
    """Answers each turn with the next canned reply (the line format the agent asks for)."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.seen: list[list[dict[str, str]]] = []

    async def chat_text(self, messages: list[dict[str, str]], **_: Any) -> tuple[str, dict[str, Any]]:
        self.seen.append(messages)
        return self.replies.pop(0), {"latency_ms": 1}


def agent(profile: str, replies: list[str]) -> tuple[CallAgent, FakeModel]:
    p = get_profile(profile)
    assert p is not None
    model = FakeModel(replies)
    return CallAgent(build_engine(p.campaign, p.case, "สมชาย ใจดี"), model), model  # type: ignore[arg-type]


async def say(a: CallAgent, customer: str) -> str:
    previous = a.state.last_directive
    if previous is not None:
        a.report_delivery(len(previous.segments), True)
    return (await a.reply(customer)).text


def test_the_line_format_is_parsed_and_tidied() -> None:
    out = parse_turn(
        "SAY: ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาทครับ\n"
        "UPDATE: plan_coverage confirmed\nUPDATE: q1 answered 4 | ให้สี่\nFOLLOW_UP: complaint | รอนาน\nEND: none"
    )
    assert out["updates"][1] == {"item": "q1", "status": "answered", "score": 4, "note": "ให้สี่"}
    assert out["follow_up"] == {"type": "complaint", "detail": "รอนาน"} and not out["end_call"]
    assert tidy(out["reply"]) == ["ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาทค่ะ"]  # female voice
    assert tidy(["สะดวกให้โทรกลับช่วงไหนดีค่ะ"]) == ["สะดวกให้โทรกลับช่วงไหนดีคะ"]  # a question rises
    assert tidy(["ไม่เป็นอะไรค่ะ"]) == ["ไม่เป็นอะไรค่ะ"]  # "it's nothing" is a statement
    assert tidy(["ดูได้ที่ [www.kpi.co.th](https://www.kpi.co.th)"]) == ["ดูได้ที่ www.kpi.co.thค่ะ"]


async def test_a_plain_yes_settles_identity_and_the_intro_must_say_ai() -> None:
    a, model = agent(
        "pa-email",
        [
            "SAY: ดิฉันโทรจากกรุงไทยพานิชประกันภัยค่ะ สะดวกคุยไหมคะ\nEND: none",  # no AI disclosure
            "SAY: ดิฉันน้องเคพีไอ AI ผู้ช่วยของกรุงไทยพานิชประกันภัยค่ะ\nSAY: สะดวกคุยสักครู่ไหมคะ\nEND: none",
        ],
    )
    a.start()
    text = await say(a, "ครับ พูดอยู่ครับ")
    assert a.check.identity == "confirmed" and a.result.identity_result == "confirmed"
    assert "AI" in text and len(model.seen) == 2  # the first reply was sent back once


async def test_paraphrased_notice_is_replaced_with_the_approved_words() -> None:
    a, _ = agent("pa-email", ["SAY: ได้ค่ะ แจ้งก่อนนะคะว่าเราอัดเสียงการคุยนี้ไว้ บันทึกเพื่อคุณภาพค่ะ\nEND: none"])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available = "confirmed", True, True
    text = await say(a, "ได้ครับ ใช้เวลานานไหม")  # a question: the model answers, the notice is fixed up
    assert a.notice_text in text and "อัดเสียง" not in text
    a.report_delivery(len(a.last_reply), True)
    assert a.check.notice and a.result.notice_delivered


async def test_an_item_is_confirmed_only_after_the_customer_heard_it() -> None:
    a, _ = agent("pa-email", ["SAY: ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาทค่ะ\nUPDATE: daily confirmed\nEND: none"])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    await say(a, "ครับ")
    assert a.check.status["daily"] == "pending"  # never read out: the model cannot tick it off


async def test_a_plain_ack_after_a_fact_confirms_it_even_if_the_model_forgets() -> None:
    a, _ = agent(
        "pa-email",
        [
            "SAY: แผนที่คุณลูกค้าทำไว้ คือแผนประกันอุบัติเหตุ พีเอ เต็มใจ คุ้มครองกรณีเสียชีวิตจากอุบัติเหตุ 300,000 บาทค่ะ\nEND: none",
            "SAY: ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาทค่ะ\nEND: none",
        ],
    )
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    await say(a, "ครับ")
    await say(a, "อือ")
    assert a.check.status["plan_coverage"] == "confirmed"
    assert {f.field: f.status for f in a.result.policy_fields}["death_benefit"] == "confirmed"


async def test_no_completed_close_with_items_left_and_the_fallback_never_goes_back() -> None:
    bad_close = "SAY: ขอบคุณค่ะ สวัสดีค่ะ\nEND: completed"
    a, _ = agent("pa-email", [bad_close, bad_close])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    text = await say(a, "ไม่มีอะไรแล้วครับ")
    assert not a.state.finished
    assert "แผนประกันอุบัติเหตุ" in text  # the approved line for the next item, not the identity check
    assert "fallback" in a.last_metrics


async def test_invented_numbers_and_closing_while_asking_are_refused() -> None:
    a, model = agent(
        "pa-email",
        [
            "SAY: เบี้ยประกันภัย 1,500 บาทต่อปีค่ะ\nEND: none",
            "SAY: ได้ค่ะ สะดวกให้โทรกลับช่วงไหนคะ\nEND: callback",
        ],
    )
    a.start()
    text = await say(a, "เบี้ยเท่าไหร่ครับ")
    assert "1,500" not in text and len(model.seen) == 2


async def test_callback_close_records_the_time() -> None:
    a, _ = agent("pa-email", ["SAY: รับทราบค่ะ พรุ่งนี้บ่ายสองโมง ขอบคุณค่ะ สวัสดีค่ะ\nEND: callback | พรุ่งนี้บ่ายสองโมง"])
    a.start()
    await say(a, "พรุ่งนี้บ่ายสองโมงครับ")
    assert a.outcome is Outcome.CALLBACK_REQUESTED
    assert a.result.callback.preferred_time_text == "พรุ่งนี้บ่ายสองโมง"
    assert [t.type for t in a.result.tasks] == ["callback"]


async def test_survey_scores_are_kept_on_the_scale_and_a_reason_counts_as_feedback() -> None:
    a, model = agent(
        "survey-surveyor",
        [
            "SAY: ข้อนี้ให้คะแนน 1 ถึง 5 นะคะ ให้กี่คะแนนดีคะ\nUPDATE: q3 answered 7\nEND: none",
            "SAY: ข้อนี้ให้คะแนน 1 ถึง 5 นะคะ ให้กี่คะแนนดีคะ\nEND: none",
            "SAY: ขออภัยที่ต้องรอนานนะคะ\nUPDATE: q3 answered 2 | ให้ 2 เพราะรอพนักงานนานเป็นชั่วโมง\nEND: none",
        ],
    )
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    await say(a, "ให้ 7")
    assert len(model.seen) == 2  # an off-scale score is sent back, never recorded
    await say(a, "ให้ 2 เพราะรอพนักงานนานเป็นชั่วโมง")
    q3 = next(x for x in a.result.survey_answers if x.question == "q3")
    assert q3.value == 2 and q3.feedback_raw and a.check.feedback_pending is None


async def test_a_prepared_reply_to_a_plain_ack_is_used_without_waiting_for_the_model() -> None:
    a, model = agent("pa-email", ["SAY: ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาทค่ะ\nEND: none"])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    dialogue = AgentDialogue(a)
    dialogue.prepare_next()
    assert dialogue.prepared is not None
    a.report_delivery(1, True)
    text = (await dialogue.reply("ครับ")).text
    assert "15,000" in text and dialogue.events[-1][0] == "reply_prepared" and len(model.seen) == 1


async def test_a_due_statement_after_a_plain_yes_needs_no_model() -> None:
    a, model = agent("pa-email", [])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available = "confirmed", True, True
    text = await say(a, "สะดวกครับ")
    assert a.notice_text in text and model.seen == []


async def test_an_unanswerable_question_gets_an_honest_answer_never_a_repeated_line() -> None:
    honest = "SAY: เรื่องเอกสารเคลม ดิฉันยังไม่มีข้อมูลยืนยันค่ะ จะให้เจ้าหน้าที่ติดต่อกลับนะคะ\nEND: none"
    broken = "SAY: เอกสารเคลมใช้แค่บัตรประชาชนเท่านั้นค่ะ\nEND: none"  # invented: refused
    a, _ = agent("pa-email", [honest, broken, broken])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    assert "ไม่มีข้อมูลยืนยัน" in await say(a, "เคลมต้องใช้เอกสารอะไรครับ")  # an honest limitation passes
    first = await say(a, "แล้วใช้เอกสารอะไรบ้างครับ")
    assert "ยังไม่มีข้อมูลที่ยืนยันได้" in first and "เท่านั้น" not in first
    assert any(t.type == "question_follow_up" for t in a.result.tasks)


async def test_a_policy_claim_with_no_approved_source_is_not_spoken() -> None:
    # Said in the 15 Oct live call: nothing in the call data or the knowledge says it.
    invented = "SAY: ค่ะ คุ้มครองต่อเนื่องไปจนกว่าจะครบกำหนดอายุของกรมธรรม์นะคะ\nEND: none"
    grounded = "SAY: ใช่ค่ะ เริ่มคุ้มครองวันที่ 15 ตุลาคม 2569 เวลา 00.01 น. เป็นต้นไปนะคะ\nEND: none"
    a, model = agent("pa-email", [invented, grounded])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    text = await say(a, "เป็นต้นไปเหรอครับ")
    assert text == "ใช่ค่ะ เริ่มคุ้มครองวันที่ 15 ตุลาคม 2569 เวลา 00.01 น. เป็นต้นไปนะคะ"
    assert len(model.seen) == 2


async def test_yes_i_have_a_question_is_not_answered_with_the_reply_prepared_for_ok() -> None:
    a, _ = agent(
        "pa-email",
        [
            "SAY: ผู้รับผลประโยชน์ คือ นางสาวสมใจ ใจดี (บุตร) ใช่ไหมคะ\nEND: none",  # prepared for a plain "ครับ"
            "SAY: ได้เลยค่ะ สอบถามได้เลยนะคะ\nEND: none",
        ],
    )
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    dialogue = AgentDialogue(a)
    a._say(["มีเรื่องอื่นที่อยากสอบถามเพิ่มเติมไหมคะ"], "turn")
    dialogue.prepare_next()
    await dialogue.prepared  # worked out while the question was being spoken
    a.report_delivery(1, True)
    assert (await dialogue.reply("มีครับ")).text == "ได้เลยค่ะ สอบถามได้เลยนะคะ"
