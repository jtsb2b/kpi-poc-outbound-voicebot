"""The conductor behind the speech-to-speech engines: the pipeline's checks on the customer's own words,
replayed on what went wrong in the 5 Nov test calls."""

from kpi_voicebot.agent import CallAgent
from kpi_voicebot.campaigns import load_profiles
from kpi_voicebot.conductor import Conductor
from kpi_voicebot.models import CampaignId, Outcome
from kpi_voicebot.simulator import build_engine


def survey() -> Conductor:
    case = next(p for p in load_profiles() if p.profile_id == "survey-surveyor")
    return Conductor(CallAgent(build_engine(CampaignId.ACCIDENT_SURVEY, case.case, "สมชาย ใจดี"), None))


def pa() -> Conductor:
    case = next(p for p in load_profiles() if p.profile_id == "pa-email")
    return Conductor(CallAgent(build_engine(CampaignId.PA_CONFIRMATION, case.case, "สมชาย ใจดี"), None))


def to_questions(c: Conductor) -> None:
    c.bot_said("สวัสดีค่ะ ขออนุญาตเรียนสายคุณสมชาย ใจดี นะคะ")
    assert c.record("identity", "confirmed", words="ครับ ผมพูดอยู่ครับ")["ok"]
    c.bot_said("ดิฉันน้องเคพีไอ ผู้ช่วย AI จากกรุงไทยพานิชประกันภัย ไม่ทราบว่าตอนนี้สะดวกคุยไหมคะ")
    assert c.record("availability", "available", words="ได้ครับ")["ok"]
    c.bot_said(c.agent.notice_text)
    assert c.record("recording", "granted", words="ยินยอมครับ ตามสบาย")["ok"]


def answers(c: Conductor) -> dict[str, tuple[object, str]]:
    return {a.question: (a.value, a.status) for a in c.agent.result.survey_answers}


def test_the_next_step_is_the_pipelines_own_question() -> None:
    c = survey()
    to_questions(c)
    nxt = c.record("questions", "done")["next"]  # any call returns the next step
    assert "ความสะดวกในการติดต่อศูนย์รับแจ้งอุบัติเหตุ" in nxt and "1 ถึง 5" in nxt


def test_a_score_never_said_is_never_recorded() -> None:
    c = survey()
    to_questions(c)
    # Gemini, 5 Nov: "ก็ได้" → "ได้ค่ะ สี่คะแนน". Our transcription heard no score: nothing is recorded.
    out = c.record("q1", "answered", score=4, words="ให้ 4 คะแนน", heard="ก็ได้")
    assert not out["ok"] and "ห้ามเดา" in out["say"]
    assert answers(c)["q1"] == (None, "not_asked")


def test_half_points_and_out_of_range_are_asked_again() -> None:
    c = survey()
    to_questions(c)
    half = c.record("q1", "answered", score=2, heard="เอาไป 1.5 แล้วกัน")
    assert not half["ok"] and "1 หรือ 2" in half["say"]
    out = c.record("q1", "answered", score=8, heard="8 คะแนน")
    assert not out["ok"] and "1 ถึง 5" in out["say"]
    assert answers(c)["q1"] == (None, "not_asked")
    assert c.record("q1", "answered", score=2, heard="งั้น 2")["ok"]
    assert answers(c)["q1"] == (2, "answered")


def test_a_low_score_asks_why_once_then_moves_on() -> None:
    c = survey()
    to_questions(c)
    out = c.record("q1", "answered", score=1, heard="เอาเป็น 1")
    assert out["ok"] and "ถามเหตุผล" in out["next"]
    out = c.record("q1", "feedback", heard="พนักงานติดต่อยากครับ")
    assert out["ok"] and "ความพึงพอใจโดยรวมต่อการให้บริการของศูนย์" in out["next"]
    assert c.agent.result.survey_answers[0].feedback_raw == "พนักงานติดต่อยากครับ"
    # With the reason in the same breath, no "why" is asked.
    out = c.record("q2", "answered", score=1, heard="1 เพราะรอสายนานมาก")
    assert "ความรวดเร็วในการเดินทาง" in out["next"]


def test_a_customer_who_will_not_score_is_not_pushed() -> None:
    c = survey()
    to_questions(c)
    out = c.record("q1", "refused", heard="ไม่ให้คะแนนได้ไหม")
    assert out["ok"] and "ห้ามโน้มน้าว" in out["say"] and "ความพึงพอใจโดยรวมต่อการให้บริการของศูนย์" in out["next"]
    assert answers(c)["q1"] == (None, "skipped")


def test_scores_land_on_the_question_being_asked() -> None:
    c = survey()
    to_questions(c)
    c.record("q3", "answered", score=5, heard="5 ครับ")  # the engine names the wrong question
    assert answers(c)["q1"] == (5, "answered") and answers(c)["q3"] == (None, "not_asked")


def test_q5_takes_0_to_10_and_asks_why_up_to_8() -> None:
    c = survey()
    to_questions(c)
    for q in ("q1", "q2", "q3", "q4"):
        c.record(q, "answered", heard="5")
    assert not c.record("q5", "answered", heard="11")["ok"]
    out = c.record("q5", "answered", heard="ศูนย์ละกัน")
    assert out["ok"] and answers(c)["q5"] == (0, "answered") and "ถามเหตุผล" in out["next"]


def test_closing_comments_are_heard_out_and_the_call_may_not_end_early() -> None:
    c = survey()
    to_questions(c)
    ok, out = c.end_call("completed")
    assert not ok and "ถามข้อถัดไป" in out["next"]  # refused once while questions are left
    for q in ("q1", "q2", "q3", "q4"):
        c.record(q, "answered", heard="5")
    c.record("q5", "answered", heard="9")  # above 8: no "why"
    assert "ข้อเสนอแนะ" in c.record("questions", "done")["next"]
    out = c.record("final_comment", "done", heard="อยากให้ทีม AI ช่วยให้พูดเป็นธรรมชาติกว่านี้")
    assert "เพิ่มเติมอีกไหม" in out["say"]
    out = c.record("final_comment", "done", heard="ไม่มีแล้วครับ")
    assert "end_call" in out["say"]
    ok, _ = c.end_call("completed")
    assert ok and c.agent.outcome is Outcome.SURVEY_COMPLETED
    assert c.agent.result.final_comment_raw == "อยากให้ทีม AI ช่วยให้พูดเป็นธรรมชาติกว่านี้"


def test_consent_is_read_from_the_customers_words() -> None:
    c = survey()
    c.record("identity", "confirmed", heard="ครับ")
    out = c.record("recording", "granted", heard="ไม่สะดวกให้บันทึกเสียงนะ")  # the engine got it wrong
    assert c.agent.result.recording_consent is False and "หยุดบันทึกเสียงแล้ว" in out["say"]


def test_policy_groups_and_the_free_look_close_a_pa_call() -> None:
    c = pa()
    to_questions(c)
    nxt = c.record("questions", "done")["next"]
    assert "ความคุ้มครอง" in nxt and "สามแสน" in nxt  # read in spoken form
    for group in ("coverage", "money", "beneficiary", "delivery"):
        assert c.record(group, "confirmed", heard="ถูกต้องครับ")["ok"]
    assert "ยกเลิก" in c.next_instruction()  # the free-look notice, word for word
    c.bot_said("หากไม่ตรงกับความต้องการ สามารถแจ้งยกเลิกได้ภายใน 30 วัน โดยจะได้รับเงินคืนเต็มจำนวนค่ะ")
    c.record("questions", "done", heard="ไม่มีครับ")
    ok, _ = c.end_call("completed")
    assert ok and c.agent.outcome is Outcome.POLICY_CONFIRMED
    assert all(f.status == "confirmed" for f in c.agent.result.policy_fields)


def test_a_wrong_person_ends_the_call() -> None:
    c = survey()
    out = c.record("identity", "confirmed", heard="ไม่ใช่ครับ พ่อไม่อยู่")
    assert "wrong_person" in out["say"]
    ok, _ = c.end_call("wrong_person")
    assert ok and c.agent.outcome is Outcome.WRONG_PERSON


def test_the_step_decides_not_the_engines_label() -> None:
    # In testing Gemini called a score "confirmed", "unclear" and "feedback", and named the wrong question.
    c = survey()
    to_questions(c)
    assert c.record("q1", "confirmed", score=3, heard="สามครับ")["ok"]
    assert c.record("q2", "feedback", score=2, heard="งั้นสองครับ")["ok"]  # a score, not a reason
    assert answers(c)["q1"] == (3, "answered") and answers(c)["q2"] == (2, "answered")
    assert c.record("q2", "answered", heard="รอสายนานครับ")["ok"]  # 2 asks why: this is the reason
    assert c.agent.result.survey_answers[1].feedback_raw == "รอสายนานครับ"
    assert c.record("q3", "unclear", heard="ไม่ให้คะแนนได้ไหมครับ")["ok"]  # a refusal in any label
    assert answers(c)["q3"] == (None, "skipped")


def test_answers_the_engine_did_not_record_are_read_from_our_transcription() -> None:
    c = survey()
    to_questions(c)
    out = c.interpret("เอาเป็น 4 ละกันครับ")
    assert out is not None and answers(c)["q1"] == (4, "answered")
    assert c.interpret("คะแนนมันอยู่ในช่วงไหนครับ") is None  # a question: nothing to record
    assert c.interpret("หนึ่งครึ่ง") is None and answers(c)["q2"] == (None, "not_asked")


def test_no_code_is_ever_given_to_the_engine_to_say() -> None:
    import re

    c = survey()
    to_questions(c)
    said = [c.next_instruction()]
    for heard in ["1", "ยาก", "1.5", "8", "ก็ได้", "2", "ไม่ให้คะแนน", "5", "11", "0", "แย่", "อยากให้ดีกว่านี้นะ", "ไม่มี"]:
        out = c.record("q?", "answered", heard=heard)
        said += [out["say"], out["next"]]
    assert not [s for s in said if re.search(r"\bq\d|_", s)], said


def test_an_answer_the_engine_asked_for_again_is_left_for_the_customer_to_repeat() -> None:
    c = survey()
    to_questions(c)
    reask = "ขอโทษนะคะ ในเรื่องความสะดวกในการติดต่อศูนย์รับแจ้งอุบัติเหตุ คุณลูกค้าให้กี่คะแนนดีคะ"
    assert c.interpret("ห้า", reask) is None and answers(c)["q1"] == (None, "not_asked")
    moved = "ได้ค่ะ 5 คะแนนนะคะ แล้วความพึงพอใจโดยรวมต่อการให้บริการของศูนย์รับแจ้งอุบัติเหตุ ให้กี่คะแนนดีคะ"
    assert c.interpret("ห้า", moved) is not None and answers(c)["q1"] == (5, "answered")


def test_a_group_agreed_to_is_confirmed_when_the_engine_moved_on_without_recording() -> None:
    c = pa()
    to_questions(c)
    first = "ถูกต้องครับ แต่ค่ารักษาหนึ่งหมื่นห้าพันนี่ต่อครั้งหรือต่อปีครับ"
    same = "เป็นค่ารักษาต่ออุบัติเหตุแต่ละครั้งค่ะ ข้อมูลความคุ้มครองตามนี้ถูกต้องไหมคะ"
    assert c.interpret(first, same) is None  # still on the coverage group
    moved = "เป็นต่อครั้งค่ะ ขออนุญาตทวนเบี้ยประกันภัย สองพันบาทต่อปีค่ะ ส่วนนี้ถูกต้องไหมคะ"
    assert c.interpret(first, moved) is not None
    fields = {f.field: f.status for f in c.agent.result.policy_fields}
    assert fields["death_benefit"] == "confirmed" and fields["premium"] == "not_reviewed"
    assert c.interpret("ไม่ใช่ครับ ผิด", moved.replace("สองพัน", "สามพัน")) is None  # a "no" is the engine's


def test_a_close_after_asking_for_more_questions_is_allowed() -> None:
    c = pa()
    to_questions(c)
    for group in ("coverage", "money", "beneficiary", "delivery"):
        c.record(group, "confirmed", heard="ถูกต้องครับ")
    c.bot_said("สามารถแจ้งยกเลิกได้ภายใน 30 วัน โดยจะได้รับเงินคืนเต็มจำนวนค่ะ")
    c.bot_said("ไม่ทราบว่ามีคำถามเพิ่มเติมไหมคะ")
    ok, _ = c.end_call("completed")
    assert ok and c.agent.outcome is Outcome.POLICY_CONFIRMED


def test_an_acknowledgement_is_not_the_answer_to_a_question_not_yet_asked() -> None:
    c = pa()
    to_questions(c)
    for group in ("coverage", "money", "beneficiary", "delivery"):
        c.record(group, "confirmed", heard="ถูกต้องครับ")
    c.bot_said("ขออนุญาตแจ้งข้อมูลสำคัญเพิ่มเติมนะคะ สามารถแจ้งยกเลิกได้ภายใน 30 วัน โดยจะได้รับเงินคืนเต็มจำนวนค่ะ")
    c.customer_said("ครับ")
    assert c.interpret("ครับ", "ไม่ทราบว่ามีคำถามเพิ่มเติมไหมคะ") is None
    assert not c.agent.check.questions_asked


def garage() -> Conductor:
    case = next(p for p in load_profiles() if p.profile_id == "garage-three-cars")
    return Conductor(CallAgent(build_engine(CampaignId.GARAGE_FOLLOWUP, case.case, "ช่างเอก"), None))


def ask(c: Conductor, heard: str, item: str = "car?", status: str = "") -> dict[str, object]:
    """The bot says the next step's line, then the garage answers."""
    line = c.next_instruction().split('"')[1] if '"' in c.next_instruction() else c.next_instruction()
    c.bot_said(line)
    c.customer_said(heard)
    return c.record(item, status, heard=heard)


def test_garage_cars_are_read_by_the_pipelines_rules_with_the_approved_lines() -> None:
    # The 5 Nov Agni garage call, replayed.
    c = garage()
    c.bot_said("สวัสดีค่ะ ดิฉันน้องเคพีไอ ผู้ช่วย AI จากบริษัท กรุงไทยพานิชประกันภัยค่ะ ไม่ทราบว่าใช่อู่ช.ทวีการช่างไหมคะ")
    c.customer_said("ใช่ครับ")
    assert c.record("identity", "confirmed", heard="ใช่ครับ")["ok"]
    assert c.step() == "status"  # no recording notice, no "สะดวกไหม" in KPI's garage script
    first = c.next_instruction()
    assert "ขอสอบถามข้อมูลรถจำนวน" in first and "ทะเบียน" in first
    out = ask(c, "ยังไม่เสร็จครับ กำลังซ่อมอยู่ครับ")
    assert out["ok"] and "ซ่อมแล้วเสร็จประมาณวันที่เท่าไร" in str(out["next"])
    out = ask(c, "วันที่ 31 ธันวาคม")
    assert out["ok"] and "ตั้งเบิกเคลม" in str(out["say"])  # the approved line, after the date
    assert c.agent.result.vehicles[0].completion_text == "วันที่ 31 ธันวาคม"
    out = ask(c, "ส่งคืนลูกค้าแล้วครับ ตั้งเบิกเคลมไปแล้วด้วยครับ", "car2", "repaired")
    assert out["ok"] and c.agent.result.vehicles[1].status == "repaired"
    out = ask(c, "เสร็จแล้ว")
    assert out["ok"] and c.agent.result.vehicles[2].status == "repaired"
    assert c.step() == "done" and "end_call" in c.next_instruction()  # no "any questions?" for a garage
    ok_, _ = c.end_call("completed")
    assert ok_ and c.agent.outcome is Outcome.FOLLOWUP_COMPLETED


def test_a_date_the_garage_never_said_is_not_recorded() -> None:
    c = garage()
    c.record("identity", "confirmed", heard="ใช่ครับ")
    ask(c, "กำลังซ่อมอยู่ครับ")
    out = ask(c, "ไม่แน่ใจเหมือนกัน เดี๋ยวถามช่างก่อน", "car1", "completion")  # "ไม่แน่ใจ" = unknown, kept
    assert out["ok"]
    c2 = garage()
    c2.record("identity", "confirmed", heard="ใช่ครับ")
    ask(c2, "กำลังซ่อมอยู่ครับ")
    out = ask(c2, "ครับ", "car1", "completion")  # the engine claims a date; the words hold none
    assert not out["ok"] and c2.agent.result.vehicles[0].completion_text is None


def test_a_rough_completion_time_in_words_is_a_date() -> None:
    c = garage()
    c.record("identity", "confirmed", heard="ใช่ครับ")
    ask(c, "กำลังซ่อมอยู่ครับ เพิ่งเริ่ม")
    out = ask(c, "น่าจะอีกสองสามวันครับ", "car1", "completion")
    assert out["ok"] and c.agent.result.vehicles[0].completion_text == "น่าจะอีกสองสามวันครับ"
