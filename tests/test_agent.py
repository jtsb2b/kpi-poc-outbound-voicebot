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


def ready(a: CallAgent) -> None:
    """Past the opening: identity confirmed, introduced, available, notice heard, recording agreed."""
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    a.check.consent = "granted"


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


async def test_a_group_is_confirmed_only_after_the_customer_heard_it() -> None:
    a, _ = agent("pa-email", ["SAY: ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาทค่ะ\nUPDATE: money confirmed\nEND: none"])
    a.start()
    ready(a)
    await say(a, "ครับ")
    assert {f.field: f.status for f in a.result.policy_fields}["premium"] == "not_reviewed"  # never read out


async def test_the_policy_is_read_in_groups_and_a_yes_confirms_the_whole_group() -> None:
    a, _ = agent(
        "pa-email",
        [
            "SAY: แผนที่คุณลูกค้าทำไว้ คือแผนประกันอุบัติเหตุ พีเอ เต็มใจ คุ้มครองกรณีเสียชีวิตจากอุบัติเหตุ 300,000 บาท "
            "ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาท และเงินชดเชยรายได้วันละ 500 บาท สูงสุด 30 วันค่ะ\n"
            "SAY: ข้อมูลความคุ้มครองตามนี้ ตรงกับที่คุณลูกค้าทราบไหมคะ\nEND: none",
            "SAY: ส่วนเบี้ยประกันภัย 2,000 บาทต่อปีค่ะ\nEND: none",
        ],
    )
    a.start()
    ready(a)
    turn = await say(a, "ครับ")
    assert "300,000" in turn and "15,000" in turn and "500" in turn  # one turn for the whole coverage group
    await say(a, "ถูกต้องครับ")
    status = {f.field: f.status for f in a.result.policy_fields}
    assert [status[f] for f in ("plan_name", "death_benefit", "medical_per_accident", "daily_hospital")] == [
        "confirmed"
    ] * 4
    assert status["premium"] == "not_reviewed"


async def test_disputing_one_item_notes_it_and_confirms_the_rest_of_the_group() -> None:
    a, _ = agent(
        "pa-email",
        [
            "SAY: แผนที่คุณลูกค้าทำไว้ คือแผนประกันอุบัติเหตุ พีเอ เต็มใจ คุ้มครองกรณีเสียชีวิตจากอุบัติเหตุ 300,000 บาท "
            "ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาท และเงินชดเชยรายได้วันละ 500 บาท สูงสุด 30 วันค่ะ\n"
            "SAY: ข้อมูลความคุ้มครองตามนี้ ตรงกับที่คุณลูกค้าทราบไหมคะ\nEND: none",
            "SAY: ขอบคุณที่แจ้งนะคะ ดิฉันขออนุญาตบันทึกไว้ให้เจ้าหน้าที่ตรวจสอบนะคะ\n"
            "UPDATE: daily_hospital disputed | ผมจำได้ว่าวันละพันบาท\nEND: none",
        ],
    )
    a.start()
    ready(a)
    await say(a, "ครับ")
    await say(a, "ไม่ตรงครับ ผมจำได้ว่าวันละพันบาท")
    status = {f.field: f.status for f in a.result.policy_fields}
    assert status["daily_hospital"] == "disputed"
    assert status["death_benefit"] == status["medical_per_accident"] == "confirmed"
    assert [(t.type, t.field) for t in a.result.tasks] == [("policy_discrepancy", "daily_hospital")]


async def test_no_completed_close_with_items_left_and_the_fallback_never_goes_back() -> None:
    bad_close = "SAY: ขอบคุณค่ะ สวัสดีค่ะ\nEND: completed"
    a, _ = agent("pa-email", [bad_close, bad_close])
    a.start()
    ready(a)
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
            "SAY: ขออภัยที่ต้องรอนานนะคะ ส่วนภาพรวมให้กี่คะแนนดีคะ\n"
            "UPDATE: q3 answered 2 | ให้ 2 เพราะรอพนักงานนานเป็นชั่วโมง\nEND: none",
        ],
    )
    a.start()
    ready(a)
    await say(a, "ให้ 7")
    assert len(model.seen) == 2  # an off-scale score is sent back, never recorded
    await say(a, "ให้ 2 เพราะรอพนักงานนานเป็นชั่วโมง")
    q3 = next(x for x in a.result.survey_answers if x.question == "q3")
    assert q3.value == 2 and q3.feedback_raw and a.check.feedback_pending is None


async def test_a_prepared_reply_to_a_plain_ack_is_used_without_waiting_for_the_model() -> None:
    a, model = agent("pa-email", ["SAY: ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาทค่ะ\nEND: none"])
    a.start()
    ready(a)
    dialogue = AgentDialogue(a)
    dialogue.prepare_next()
    assert dialogue.prepared is not None
    a.report_delivery(1, True)
    text = (await dialogue.reply("ครับ")).text
    assert "15,000" in text and dialogue.events[-1][0] == "reply_prepared" and len(model.seen) == 1


async def test_an_unanswerable_question_gets_an_honest_answer_never_a_repeated_line() -> None:
    honest = "SAY: เรื่องเอกสารเคลม ดิฉันยังไม่มีข้อมูลยืนยันค่ะ จะให้เจ้าหน้าที่ติดต่อกลับนะคะ\nEND: none"
    broken = "SAY: เอกสารเคลมใช้แค่บัตรประชาชนเท่านั้นค่ะ\nEND: none"  # invented: refused
    a, _ = agent("pa-email", [honest, broken, broken])
    a.start()
    ready(a)
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
    ready(a)
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
    ready(a)
    dialogue = AgentDialogue(a)
    a._say(["มีเรื่องอื่นที่อยากสอบถามเพิ่มเติมไหมคะ"], "turn")
    dialogue.prepare_next()
    await dialogue.prepared  # worked out while the question was being spoken
    a.report_delivery(1, True)
    assert (await dialogue.reply("มีครับ")).text == "ได้เลยค่ะ สอบถามได้เลยนะคะ"


async def test_silence_gets_a_polite_ladder_never_a_bare_question() -> None:
    a, _ = agent("pa-email", [])
    a.start()
    first, second, last = a.handle_silence(), a.handle_silence(), a.handle_silence()
    assert first.text == "ขอโทษนะคะ ไม่ทราบว่าคุณสมชายยังอยู่ในสายไหมคะ"
    assert second.text == "สวัสดีค่ะ คุณสมชายได้ยินเสียงดิฉันชัดไหมคะ หากสัญญาณไม่ชัด รบกวนพูดอีกครั้งได้เลยนะคะ"
    assert last.end_call and last.text.startswith("สัญญาณอาจขัดข้องนะคะ")


async def test_a_blunt_re_ask_or_an_exact_repeat_is_sent_back() -> None:
    a, model = agent(
        "pa-email",
        [
            "SAY: สะดวกคุยไหมคะ\nEND: none",  # the same question again, with nothing to soften it
            "SAY: ขอโทษนะคะ ไม่ทราบว่าตอนนี้สะดวกคุยสักครู่ไหมคะ\nEND: none",
        ],
    )
    a.start()
    a.check.identity, a.check.ai_disclosed = "confirmed", True
    a._say(["ดิฉันน้องเคพีไอ ผู้ช่วย AI ค่ะ", "สะดวกคุยไหมคะ"], "turn")
    assert await say(a, "หือ") == "ขอโทษนะคะ ไม่ทราบว่าตอนนี้สะดวกคุยสักครู่ไหมคะ"
    assert len(model.seen) == 2


def test_casual_or_misspelt_particles_are_made_polite() -> None:
    assert tidy(["รอสักครู่นะค่ะ", "ได้ค่า"]) == ["รอสักครู่นะคะ", "ได้ค่ะ"]


async def test_a_no_to_recording_before_the_notice_is_taken_at_once() -> None:
    a, _ = agent("pa-email", ["SAY: รับทราบค่ะ ดิฉันจะไม่บันทึกเสียงการสนทนานี้นะคะ ไม่ทราบว่าตอนนี้สะดวกคุยไหมคะ\nEND: none"])
    a.start()
    a.check.identity, a.check.ai_disclosed = "confirmed", True
    await say(a, "ไม่ให้อัดเสียงนะครับ")
    assert a.check.notice and a.result.recording_consent is False


async def test_a_value_said_without_its_brackets_still_counts_as_heard() -> None:
    a, _ = agent("pa-email", ["SAY: ผู้รับผลประโยชน์ คือ นางสาวสมใจ ใจดี เป็นบุตร ใช่ไหมคะ\nEND: none", "SAY: ค่ะ\nEND: none"])
    a.start()
    ready(a)
    await say(a, "ครับ")
    await say(a, "ใช่ครับ ลูกสาวผมเอง")
    assert {f.field: f.status for f in a.result.policy_fields}["beneficiary"] == "confirmed"


async def test_a_named_dispute_is_recorded_even_if_the_model_forgets_to_report_it() -> None:
    # Role-play of 19 Oct: the bot apologised and moved on, but the dispute was never recorded.
    a, _ = agent(
        "pa-email",
        [
            "SAY: ขออนุญาตทวนความคุ้มครองนะคะ แผนที่คุณลูกค้าทำไว้ คือแผนประกันอุบัติเหตุ พีเอ เต็มใจ "
            "คุ้มครองกรณีเสียชีวิตจากอุบัติเหตุ 300,000 บาท ค่ารักษาพยาบาลต่ออุบัติเหตุแต่ละครั้ง 15,000 บาท "
            "และเงินชดเชยรายได้วันละ 500 บาท สูงสุด 30 วันค่ะ\\nSAY: ตรงกับที่คุณลูกค้าทราบไหมคะ\\nEND: none",
            "SAY: ขอบคุณที่แจ้งนะคะ ดิฉันขออนุญาตบันทึกเรื่องเงินชดเชยรายได้ไว้ให้เจ้าหน้าที่ตรวจสอบนะคะ\\nEND: none",
        ],
    )
    a.start()
    ready(a)
    await say(a, "ครับ")
    await say(a, "ไม่ใช่ครับ ชดเชยรายวันต้องวันละ 1,000 บาทครับ")
    status = {f.field: f.status for f in a.result.policy_fields}
    assert status["daily_hospital"] == "disputed" and status["death_benefit"] == "confirmed"
    assert [(t.type, t.field) for t in a.result.tasks] == [("policy_discrepancy", "daily_hospital")]


async def test_the_model_words_the_recording_notice_itself_but_must_ask_for_consent() -> None:
    own_words = (
        "SAY: ขอบพระคุณค่ะ การสนทนานี้มีการบันทึกเสียงไว้เพื่อประโยชน์ของคุณลูกค้านะคะ\nSAY: ไม่ทราบว่าคุณสมชายยินยอมไหมคะ\nEND: none"
    )
    no_consent = "SAY: ขอบพระคุณค่ะ การสนทนานี้มีการบันทึกเสียงไว้นะคะ\nEND: none"
    a, model = agent("pa-email", [no_consent, own_words])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available = "confirmed", True, True
    text = await say(a, "สะดวกครับ")
    assert text == "ขอบพระคุณค่ะ การสนทนานี้มีการบันทึกเสียงไว้เพื่อประโยชน์ของคุณลูกค้านะคะ ไม่ทราบว่าคุณสมชายยินยอมไหมคะ"
    assert len(model.seen) == 2  # the notice without the consent question was sent back
    a.report_delivery(2, True)
    assert a.check.notice


async def test_declining_the_recording_stops_the_audio_and_the_call_goes_on() -> None:
    import asyncio

    stopped: list[str] = []

    async def stop_recording() -> None:
        stopped.append("audio deleted")

    a, _ = agent("pa-email", ["SAY: ไม่เป็นไรค่ะ เรื่องความคุ้มครองของคุณสมชาย แผนพีเอ เต็มใจค่ะ\nEND: none"])
    a.on_recording_declined = stop_recording
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available = "confirmed", True, True
    a._say(["การสนทนานี้มีการบันทึกเสียงนะคะ", "ไม่ทราบว่ายินยอมไหมคะ"], "turn")
    text = await say(a, "ไม่ยินยอมครับ")
    await asyncio.sleep(0)
    assert stopped == ["audio deleted"]
    assert a.result.recording_consent is False and not a.state.finished
    assert text.startswith("รับทราบค่ะ ดิฉันจะไม่บันทึกเสียงการสนทนานี้นะคะ")


async def test_when_the_llm_is_down_the_bot_apologises_and_ends_instead_of_reading_a_script() -> None:
    # 19 Oct test call: every model call failed and fixed lines looped for minutes.
    from kpi_voicebot.llm import LLMError

    class Down:
        calls = 0

        async def chat_text(self, messages: Any, **_: Any) -> Any:
            Down.calls += 1
            raise LLMError("HTTP 400")

    p = get_profile("pa-post")
    assert p is not None
    a = CallAgent(build_engine(p.campaign, p.case, "สมชาย ใจดี"), Down())
    a.start()
    turn = await say(a, "ครับ พูดอยู่ครับ")
    assert turn == "ต้องขออภัยค่ะ ขณะนี้ระบบขัดข้องชั่วคราว ดิฉันขออนุญาตให้เจ้าหน้าที่ติดต่อกลับภายหลังนะคะ ขอบพระคุณค่ะ สวัสดีค่ะ"
    assert a.state.finished and a.outcome is Outcome.TECHNICAL_FAILURE and Down.calls == 2  # one retry


async def test_the_greeting_is_the_models_own_when_prepared_in_time() -> None:
    a, _ = agent("pa-email", ["SAY: สวัสดีค่ะ ขออนุญาตเรียนสายคุณสมชาย ใจดี ค่ะ\nEND: none"])
    await a.prepare_opening()
    assert a.start().text == "สวัสดีค่ะ ขออนุญาตเรียนสายคุณสมชาย ใจดี ค่ะ"


async def test_the_19_oct_survey_loop_scores_are_kept_and_never_guessed() -> None:
    # In the 19 Oct call the model wrote "UPDATE: q2 3" (no "answered"): the score was dropped, the
    # checklist kept asking q2, and saying back the customer's earlier "8" was refused as invented.
    a, model = agent(
        "survey-no-surveyor",
        [
            "SAY: ได้ค่ะ 3 คะแนนนะคะ ส่วนประสบการณ์ในภาพรวม จาก 0 ถึง 10 ให้กี่คะแนนดีคะ\nUPDATE: q2 3\nEND: none",
            "SAY: ได้ค่ะ 8 คะแนนนะคะ มีข้อเสนอแนะเพิ่มเติมไหมคะ\nUPDATE: q5 answered 8 | 8 ครับ\nEND: none",
            "SAY: ขอบพระคุณค่ะ ที่ให้ 8 คะแนนนะคะ สวัสดีค่ะ\nUPDATE: q5 answered 10 | ไม่มีครับ\nEND: none",
            "SAY: ขอบพระคุณที่สละเวลานะคะ สวัสดีค่ะ\nUPDATE: final_comment done | ไม่มี\nEND: completed",
        ],
    )
    a.start()
    ready(a)
    a.check.status["q1"] = "4"
    await say(a, "ผมให้สัก 3 คะแนน")
    assert a.check.status["q2"] == "3"
    await say(a, "8 ครับ")
    await say(a, "ไม่มีครับ")  # the guessed 10 is refused; the retry closes
    assert a.check.status["q5"] == "8"
    assert len(model.seen) == 4 and a.state.finished


async def test_a_low_score_reason_is_asked_once() -> None:
    a, _ = agent(
        "survey-no-surveyor",
        [
            "SAY: ขออภัยในความไม่สะดวกค่ะ ไม่ทราบว่าติดขัดตรงไหนคะ\nUPDATE: q1 answered 1 | 1 ครับ\nEND: none",
            "SAY: รับทราบค่ะ ส่วนความพึงพอใจโดยรวม จาก 1 ถึง 5 ให้กี่คะแนนดีคะ\nEND: none",
        ],
    )
    a.start()
    ready(a)
    await say(a, "1 ครับ")
    assert a.check.feedback_pending == "q1"
    await say(a, "ก็ไม่รู้สิครับ")  # whatever is said next is the reason; never asked again
    q1 = next(x for x in a.result.survey_answers if x.question == "q1")
    assert a.check.feedback_pending is None and q1.feedback_raw == "ก็ไม่รู้สิครับ"


async def test_consent_offered_early_still_gets_the_notice_before_the_survey() -> None:
    skips = "SAY: ขอบพระคุณค่ะ ข้อแรก ความสะดวกในการติดต่อศูนย์ ให้กี่คะแนนดีคะ\nUPDATE: recording granted\nEND: none"
    notice = (
        "SAY: ขอบพระคุณค่ะ ขออนุญาตแจ้งว่าการสนทนานี้จะถูกบันทึกเสียง เพื่อรักษาผลประโยชน์ของคุณลูกค้า"
        " และใช้ปรับปรุงคุณภาพการให้บริการนะคะ ไม่ทราบว่ายินยอมให้บันทึกเสียงไหมคะ\nEND: none"
    )
    a, model = agent("survey-no-surveyor", [skips, notice])
    a.start()
    a.check.identity, a.check.ai_disclosed = "confirmed", True
    text = await say(a, "สะดวกครับ บันทึกเสียงได้ครับ")
    assert len(model.seen) == 2 and "บันทึกเสียง" in text


async def test_a_score_is_never_left_hanging_without_the_next_question() -> None:
    hanging = "SAY: ได้ค่ะ 3 คะแนนนะคะ\nUPDATE: q2 answered 3\nEND: none"
    onward = "SAY: ได้ค่ะ 3 คะแนนนะคะ ส่วนภาพรวม จาก 0 ถึง 10 ให้กี่คะแนนดีคะ\nUPDATE: q2 answered 3\nEND: none"
    a, model = agent("survey-no-surveyor", [hanging, onward])
    a.start()
    ready(a)
    a.check.status["q1"] = "4"
    assert "ให้กี่คะแนนดีคะ" in await say(a, "3 ครับ")
    assert len(model.seen) == 2


async def test_a_rejected_reply_still_keeps_the_score_the_customer_gave() -> None:
    invented = "SAY: ได้ค่ะ 3 คะแนน ซึ่งคุ้มครองต่อเนื่องจนครบกำหนดอายุกรมธรรม์นะคะ ส่วนภาพรวมให้กี่คะแนนดีคะ\nUPDATE: q2 answered 3"
    a, _ = agent("survey-no-surveyor", [invented, invented])
    a.start()
    ready(a)
    a.check.status["q1"] = "4"
    text = await say(a, "3 ครับ")
    assert "fallback" in a.last_metrics and a.check.status["q2"] == "3"
    assert "ความพึงพอใจโดยรวม" not in text  # never the question just answered


def test_exclamations_and_quotes_are_not_spoken() -> None:
    assert tidy(["โอ้โห ขออภัยด้วยนะคะ", 'ดิฉัน "น้องเคพีไอ" ค่ะ']) == ["ขออภัยด้วยนะคะ", "ดิฉัน น้องเคพีไอ ค่ะ"]


async def test_a_customer_who_wants_to_stop_is_let_go_even_with_questions_left() -> None:
    close = "SAY: ไม่เป็นไรค่ะ ขอบพระคุณที่สละเวลานะคะ สวัสดีค่ะ\nEND: completed"
    a, _ = agent("survey-no-surveyor", [close])
    a.start()
    ready(a)
    await say(a, "ไม่อยากตอบแล้ว จะวางสายได้หรือยัง")
    assert a.state.finished and a.outcome is Outcome.REFUSED


async def test_words_said_while_the_reply_is_worked_out_are_answered_together() -> None:
    # 19 Oct call: "ก็ครับ" was answered as consent while "เอ่อ ไม่ครับ" was still being said; the
    # "ไม่ครับ" waited 34 s and was taken as disputing the next policy group.
    import asyncio

    from kpi_voicebot.asr import ASREvent, TurnCollector
    from kpi_voicebot.voice_session import VoiceSession

    a, model = agent(
        "pa-email",
        [
            "SAY: ขอบพระคุณค่ะ ขออนุญาตทวนความคุ้มครองนะคะ\nUPDATE: recording granted\nEND: none",
            "SAY: ได้ค่ะ ดิฉันจะไม่บันทึกเสียงนะคะ ขออนุญาตทวนความคุ้มครองนะคะ\nUPDATE: recording declined\nEND: none",
        ],
    )
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    dialogue = AgentDialogue(a)
    session = object.__new__(VoiceSession)
    session.dialogue, session.collector, session.sink = dialogue, TurnCollector(), None
    session.gone, session.console, session.engine = asyncio.Event(), False, a
    real_reply = dialogue.reply

    async def reply_while_customer_talks(text: str):  # type: ignore[no-untyped-def]
        directive = await real_reply(text)
        if text == "ก็ครับ":
            session.collector.feed(ASREvent("commit", "เอ่อ ไม่ครับ", 1, 0.0))
        return directive

    dialogue.reply = reply_while_customer_talks  # type: ignore[method-assign]
    directive = await session._reply("ก็ครับ")
    assert a.check.consent == "declined" and "ไม่บันทึกเสียง" in directive.text
    assert "ก็ครับ เอ่อ ไม่ครับ" in model.seen[-1][1]["content"]


async def test_audio_tags_go_to_the_voice_but_not_the_transcript() -> None:
    a, _ = agent("pa-email", ["SAY: ได้ค่ะ <short pause> ขออนุญาตทวนความคุ้มครองนะคะ <chuckle>\nEND: none"])
    a.start()
    ready(a)
    directive = await a.reply("ครับ")
    assert directive.text == "ได้ค่ะ ขออนุญาตทวนความคุ้มครองนะคะ"
    assert directive.voice_text == "ได้ค่ะ <short pause> ขออนุญาตทวนความคุ้มครองนะคะ"  # a trailing tag does nothing
    assert a.last_reply == ["ได้ค่ะ ขออนุญาตทวนความคุ้มครองนะคะ"]


async def test_the_free_look_deadline_is_worked_out_and_may_be_said() -> None:
    # 19 Oct calls: "ได้รับ 1 พฤศจิกายน ยกเลิกได้ถึงวันไหน" got the rule again and again, never a date.
    answer = "SAY: ถ้าได้รับวันที่ 1 พฤศจิกายน แจ้งยกเลิกได้ถึงวันที่ 1 ธันวาคมค่ะ มีอะไรสอบถามเพิ่มเติมไหมคะ\nEND: none"
    a, model = agent("pa-email", [answer])
    a.start()
    ready(a)
    a.check.free_look = True
    text = await say(a, "ถ้าผมได้รับกรมธรรม์วันที่ 1 พฤศจิกายน แจ้งยกเลิกวันที่ 5 ธันวาคม ได้เงินคืนไหมครับ")
    assert "1 ธันวาคม" in text and len(model.seen) == 1
    hint = model.seen[0][1]["content"]
    assert "ถึงวันที่ 1 ธันวาคม" in hint and "วันที่ 5 ธันวาคม เกินกำหนดแล้ว" in hint


async def test_no_hanging_up_in_the_turn_that_answers_a_question() -> None:
    hang_up = "SAY: ได้ค่ะ ยกเลิกได้ภายใน 30 วันนะคะ ขอบพระคุณค่ะ สวัสดีค่ะ\nEND: completed"
    a, model = agent("pa-email", [hang_up, "SAY: ได้ค่ะ มีอะไรสอบถามเพิ่มเติมไหมคะ\nEND: none"])
    a.start()
    ready(a)
    await say(a, "ยกเลิกได้กี่วันครับ")
    assert len(model.seen) == 2 and not a.state.finished


async def test_a_question_about_an_item_is_not_a_dispute() -> None:
    a, _ = agent(
        "pa-email",
        ["SAY: แยกกันค่ะ ค่ารักษาเป็นต่อครั้ง ส่วนชดเชยเป็นรายวันนะคะ\nUPDATE: coverage unclear | นับรวมกันไหม\nEND: none"],
    )
    a.start()
    ready(a)
    a.check.heard_values.add("coverage")
    await say(a, "ค่ารักษา 15,000 มันนับรวมกับชดเชยวันละ 500 ไหมครับ")
    assert all(f.status == "not_reviewed" for f in a.result.policy_fields) and not a.result.tasks


async def test_asking_when_to_call_back_keeps_the_line_open_for_the_answer() -> None:
    # 19 Oct call: "ไม่ทราบว่าสะดวกให้ติดต่อกลับช่วงเวลาไหนดีคะ" + END: callback, then the bot hung up.
    a, model = agent(
        "pa-email",
        [
            "SAY: ไม่เป็นไรค่ะ ต้องขออภัยที่รบกวนนะคะ ไม่ทราบว่าสะดวกให้ติดต่อกลับช่วงเวลาไหนดีคะ\nEND: callback",
            "SAY: รับทราบค่ะ พรุ่งนี้บ่ายสองโมงนะคะ ขอบพระคุณค่ะ สวัสดีค่ะ\nEND: callback | พรุ่งนี้บ่ายสองโมง",
        ],
    )
    a.start()
    await say(a, "ขับรถอยู่ครับ ไม่สะดวกคุย")
    assert not a.state.finished and len(model.seen) == 1
    await say(a, "พรุ่งนี้บ่ายสองครับ")
    assert a.outcome is Outcome.CALLBACK_REQUESTED
    assert a.result.callback.preferred_time_text == "พรุ่งนี้บ่ายสองโมง"


async def test_a_plain_score_to_the_question_just_asked_is_kept_even_unreported() -> None:
    a, _ = agent("survey-no-surveyor", ["SAY: ได้ค่ะ ส่วนภาพรวม จาก 0 ถึง 10 ให้กี่คะแนนดีคะ\nEND: none"])
    a.start()
    ready(a)
    a.check.status["q1"] = "4"
    a.last_reply = ["แล้วความพึงพอใจโดยรวมต่อศูนย์รับแจ้งอุบัติเหตุ ให้กี่คะแนนดีคะ"]
    await a.reply("ให้ 3 ครับ")  # the model forgot to UPDATE
    assert a.check.status["q2"] == "3"


async def test_no_surveyor_makes_the_surveyor_questions_not_applicable() -> None:
    a, _ = agent("survey-unknown", ["SAY: รับทราบค่ะ ส่วนภาพรวม จาก 0 ถึง 10 ให้กี่คะแนนดีคะ\nEND: none"])
    a.start()
    ready(a)
    a.check.status.update(q1="4", q2="4")
    await a.reply("ไม่มีพนักงานมาครับ")
    assert a.check.status["q3"] == a.check.status["q4"] == "N/A"


async def test_a_score_said_in_words_may_be_said_back_in_digits() -> None:
    a, model = agent(
        "survey-no-surveyor", ["SAY: ได้ค่ะ 8 คะแนนนะคะ มีข้อเสนอแนะเพิ่มเติมไหมคะ\nUPDATE: q5 answered 8\nEND: none"]
    )
    a.start()
    ready(a)
    a.check.status.update(q1="4", q2="4")
    await a.reply("แปดครับ")
    assert len(model.seen) == 1 and a.check.status["q5"] == "8"


async def test_a_customer_who_will_not_go_on_is_let_go_at_once() -> None:
    keeps_asking = "SAY: ขออภัยค่ะ แล้วความพึงพอใจโดยรวมให้กี่คะแนนดีคะ\nEND: none"
    a, model = agent("survey-no-surveyor", [keeps_asking, "SAY: ขออภัยที่รบกวนนะคะ ขอบพระคุณค่ะ สวัสดีค่ะ\nEND: refused"])
    a.start()
    ready(a)
    await a.reply("ถามอะไรนักหนา ไม่อยากตอบแล้ว")
    assert len(model.seen) == 2 and a.outcome is Outcome.REFUSED


async def test_the_recording_notice_and_a_policy_reading_are_separate_turns() -> None:
    both = (
        "SAY: การสนทนานี้จะถูกบันทึกเสียงเพื่อรักษาผลประโยชน์ของคุณลูกค้านะคะ ขอบพระคุณที่ยินยอมค่ะ"
        " ขออนุญาตทวนความคุ้มครองนะคะ แผนประกันอุบัติเหตุ พีเอ เต็มใจ กรณีเสียชีวิตจากอุบัติเหตุ 300,000 บาทค่ะ\nEND: none"
    )
    a, model = agent("pa-email", [both, both])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available = "confirmed", True, True
    a.consent_offered = True
    await a.reply("ครับ บันทึกได้เลย")
    assert "fallback" in a.last_metrics and len(model.seen) == 2


async def test_changing_an_earlier_score_by_its_number_is_kept() -> None:
    a, _ = agent("survey-no-surveyor", ["SAY: ได้ค่ะ ข้อแรกเป็น 4 คะแนนนะคะ ส่วนภาพรวมให้กี่คะแนนดีคะ\nEND: none"])
    a.start()
    ready(a)
    a.check.status.update(q1="3", q2="5")
    next(x for x in a.result.survey_answers if x.question == "q1").value = 3
    await a.reply("เปลี่ยนข้อแรกเป็น 4 ครับ")  # the model forgot to UPDATE
    q1 = next(x for x in a.result.survey_answers if x.question == "q1")
    assert q1.value == 4 and q1.changed_from == [3]


async def test_a_misheard_answer_never_disputes_a_group() -> None:
    a, _ = agent(
        "pa-email",
        ["SAY: ขอบคุณที่แจ้งนะคะ ดิฉันขออนุญาตบันทึกไว้ให้เจ้าหน้าที่ตรวจสอบนะคะ\nUPDATE: coverage unclear | ส่งครับ ส่ง\nEND: none"],
    )
    a.start()
    ready(a)
    a.check.heard_values.add("coverage")
    await a.reply("ส่งครับ ส่ง")
    assert all(f.status == "not_reviewed" for f in a.result.policy_fields) and not a.result.tasks


async def test_call_me_later_is_never_taken_as_do_not_call() -> None:
    a, _ = agent("pa-email", ["SAY: รับทราบค่ะ ขอบพระคุณที่สละเวลานะคะ สวัสดีค่ะ\nEND: do_not_call"])
    a.start()
    await a.reply("ยังไม่รู้ครับ ไว้ค่อยโทรมาใหม่ ไม่สะดวกตอนนี้")
    assert a.outcome is Outcome.CALLBACK_REQUESTED


async def test_do_not_call_is_recorded_whatever_reason_the_model_gives() -> None:
    a, _ = agent("pa-email", ["SAY: ขออภัยที่รบกวนนะคะ ขอบพระคุณค่ะ สวัสดีค่ะ\nEND: refused"])
    a.start()
    await a.reply("ไม่ใช่ครับ อย่าโทรมาอีกนะครับ")
    assert a.outcome is Outcome.DO_NOT_CALL


async def test_a_correction_without_no_disputes_the_named_item() -> None:
    a, _ = agent("pa-email", ["SAY: ขอบคุณที่แจ้งนะคะ จะให้เจ้าหน้าที่ตรวจสอบนะคะ มีคำถามเพิ่มเติมไหมคะ\nEND: none"])
    a.start()
    ready(a)
    a.check.heard_values.add("delivery")
    a.check.heard.update(next(i for i in a.items if i.id == "delivery").values)
    a.last_reply = ["บริษัทจะส่งเอกสารกรมธรรม์ทางอีเมล somchai.demo@example.com ภายใน 7 ถึง 14 วันทำการ ถูกต้องไหมคะ"]
    await a.reply("อีเมลที่ถูกคือ somchai.real@gmail.com ครับ รบกวนแก้ให้ด้วย")
    statuses = {f.field: f.status for f in a.result.policy_fields}
    assert statuses["delivery_target"] == "disputed" and statuses["delivery_channel"] == "confirmed"


async def test_a_mangled_email_is_never_read_out() -> None:
    a, model = agent(
        "pa-email",
        [
            "SAY: อีเมลจัดส่งคือ somchai.demo.example.com นะคะ ถูกต้องไหมคะ\nEND: none",
            "SAY: อีเมลจัดส่งคือ somchai.demo@example.com นะคะ ถูกต้องไหมคะ\nEND: none",
        ],
    )
    a.start()
    ready(a)
    assert "somchai.demo@example.com" in (await a.reply("ทวนอีเมลอีกทีครับ")).text and len(model.seen) == 2


async def test_declining_politely_is_never_met_with_recording_is_required() -> None:
    pressure = "SAY: ขออภัยค่ะ การสนทนานี้มีความจำเป็นต้องบันทึกเสียงนะคะ ไม่ทราบว่ายินยอมไหมคะ\nEND: none"
    accept = "SAY: ได้ค่ะ ดิฉันจะไม่บันทึกเสียงนะคะ ขออนุญาตเริ่มสอบถามเลยนะคะ ข้อแรกให้กี่คะแนนดีคะ\nEND: none"
    a, model = agent("survey-no-surveyor", [pressure, accept])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available = "confirmed", True, True
    await a.reply("สะดวกครับ แต่ขอความกรุณาไม่ต้องบันทึกเสียงสนทนานะครับ")
    assert a.check.consent == "declined" and len(model.seen) == 2


async def test_consent_is_never_assumed_and_can_be_withdrawn() -> None:
    a, _ = agent(
        "survey-no-surveyor",
        [
            "SAY: รับทราบค่ะ ขอบพระคุณที่ยินยอมนะคะ ข้อแรกให้กี่คะแนนดีคะ\nUPDATE: recording granted\nEND: none",
            "SAY: ได้ค่ะ ดิฉันจะไม่บันทึกเสียงนะคะ ขอโทษนะคะ ไม่ทราบว่าข้อแรกให้กี่คะแนนดีคะ\nEND: none",
        ],
    )
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available, a.check.notice = "confirmed", True, True, True
    await a.reply("ผมไม่อินกับพวกบันทึกเสียงอะไรนี่นะ")  # not a yes: the model's "granted" is ignored
    assert a.check.consent != "granted"
    a.check.consent = "granted"
    await a.reply("เดี๋ยวครับ ผมบอกแล้วนะว่าไม่ให้บันทึกเสียง")
    assert a.check.consent == "declined"


async def test_a_relative_saying_yes_is_never_taken_as_the_customer() -> None:
    # 19 Oct suite: "พ่อไม่อยู่ครับ" then "สะดวกครับ โทรมาได้เลยครับ" confirmed identity, and the coverage was read.
    reads = "SAY: ขอบพระคุณค่ะ ขออนุญาตทวนความคุ้มครอง กรณีเสียชีวิตจากอุบัติเหตุ 300,000 บาทนะคะ\nEND: none"
    a, _ = agent("pa-email", [reads] * 4)
    a.start()
    a.report_delivery(1, True)
    await a.reply("พ่อไม่อยู่ครับ ออกไปทำงาน")
    await a.reply("สะดวกครับ โทรมาได้เลยครับ")
    assert a.check.identity != "confirmed"
    assert not any("300,000" in t for who, t in a.history if who == "bot")


async def test_a_score_left_hanging_twice_gets_the_next_question_added() -> None:
    hanging = "SAY: ได้ค่ะ 5 คะแนนนะคะ\nUPDATE: q1 answered 5\nEND: none"
    a, _ = agent("survey-no-surveyor", [hanging, hanging])
    a.start()
    ready(a)
    text = await say(a, "ให้ 5 คะแนนครับ")
    assert a.check.status["q1"] == "5" and text.startswith("ได้ค่ะ 5 คะแนนนะคะ") and text.endswith("คะ")
    assert "ความพึงพอใจโดยรวม" in text  # q2, in the approved words


async def test_a_dispute_counts_even_when_part_of_the_group_was_not_read() -> None:
    a, _ = agent(
        "pa-email",
        [
            "SAY: ขอบคุณที่แจ้งนะคะ จะให้เจ้าหน้าที่ตรวจสอบนะคะ ไม่ทราบว่ามีคำถามไหมคะ\n"
            "UPDATE: beneficiary disputed | ต้องเป็นนางสมศรี ภรรยา\nEND: none"
        ],
    )
    a.start()
    ready(a)
    a.history.append(("bot", "ผู้รับผลประโยชน์ที่ระบุไว้ คือ นางสาวสมใจ ใจดี ใช่ไหมคะ"))  # "(บุตร)" left out
    a.last_reply = ["ผู้รับผลประโยชน์ที่ระบุไว้ คือ นางสาวสมใจ ใจดี ใช่ไหมคะ"]
    await a.reply("ไม่ใช่ครับ ผู้รับผลประโยชน์ต้องเป็นนางสมศรี ภรรยาครับ")
    assert next(f.status for f in a.result.policy_fields if f.field == "beneficiary") == "disputed"


async def test_the_model_confirming_never_overwrites_a_no() -> None:
    a, _ = agent(
        "pa-email",
        ["SAY: ขอบคุณที่แจ้งนะคะ ขออนุญาตทวนการจัดส่งต่อนะคะ ถูกต้องไหมคะ\nUPDATE: beneficiary confirmed\nEND: none"],
    )
    a.start()
    ready(a)
    line = "ผู้รับผลประโยชน์ที่ระบุไว้ คือ นางสาวสมใจ ใจดี เป็นบุตร ใช่ไหมคะ"
    a.last_reply = [line]
    a.report_delivery(1, True)
    await a.reply("ไม่ใช่ครับ ผู้รับผลประโยชน์เป็นภรรยา ชื่อนางสมศรีครับ")
    assert next(f.status for f in a.result.policy_fields if f.field == "beneficiary") == "disputed"
