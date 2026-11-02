"""Claims follow-up (KPI script of 29 Oct 2026): the garage call and the customer appointment call."""

from kpi_voicebot.excel_io import parse_workbook, template_workbook
from kpi_voicebot.models import CampaignId, Outcome
from kpi_voicebot.repair_engine import car_status
from kpi_voicebot.tts_text import speakable
from tests.test_agent import agent, say

NEXT = "SAY: รับทราบค่ะ\nEND: none"


def garage_ready(profile: str = "garage-three-cars", replies: list[str] | None = None):  # type: ignore[no-untyped-def]
    a, model = agent(profile, replies or [NEXT] * 8)
    a.start()
    a.check.identity, a.check.ai_disclosed = "confirmed", True
    return a, model


def test_a_garage_answer_gives_the_car_its_status() -> None:
    assert car_status("ซ่อมเสร็จแล้วครับ", "not_asked") == "repaired"
    assert car_status("ยังซ่อมไม่เสร็จครับ รออะไหล่", "not_asked") == "in_repair"
    assert car_status("ลูกค้ายังไม่เอารถมาจอดเลยครับ", "not_asked") == "awaiting_customer"
    assert car_status("ยังไม่เอารถมาจอด แต่โทรนัดแล้ว วันที่ 5", "not_asked") == "booked"
    assert car_status("โทรไปแล้วลูกค้าไม่รับสายครับ", "awaiting_customer") == "customer_unreachable"
    assert car_status("ที่อู่ไม่มีรถคันนี้ครับ", "not_asked") == "not_at_garage"
    assert car_status("ครับ", "not_asked") is None


def test_a_plate_is_read_digit_by_digit_with_letter_names() -> None:
    assert speakable("รถทะเบียน 1กข 1234 กรุงเทพมหานคร") == "รถทะเบียน หนึ่ง กอ ขอ หนึ่ง สอง สาม สี่ กรุงเทพมหานคร"
    assert speakable("แจ้งภายใน 30 วัน") == "แจ้งภายใน สามสิบ วัน"  # not a plate without ทะเบียน


def test_the_garage_call_skips_the_recording_notice_and_records_no_consent() -> None:
    a, _ = garage_ready()
    assert a.check.notice and a.check.available
    assert a.result.recording_consent is None
    assert "บันทึกเสียง" not in a.checklist_text()
    assert "car1" in a.next_step() and "1กข 1234" in a.next_step()


async def test_a_plain_answer_settles_the_car_just_asked_whatever_the_model_reports() -> None:
    a, _ = garage_ready()
    a.last_reply = ["รบกวนตรวจสอบรถทะเบียน 1กข 1234 กรุงเทพมหานคร ให้หน่อยนะคะ ว่าขณะนี้ซ่อมเสร็จเรียบร้อยแล้วหรือยังคะ"]
    await a.reply("เสร็จแล้วครับ")
    assert a.result.vehicles[0].status == "repaired"
    assert "car2" in a.next_step()


async def test_a_car_in_repair_needs_its_completion_date_and_unknown_is_an_answer() -> None:
    a, _ = garage_ready()
    a.last_reply = ["รบกวนตรวจสอบรถทะเบียน 1กข 1234 กรุงเทพมหานคร ให้หน่อยนะคะ ว่าขณะนี้ซ่อมเสร็จเรียบร้อยแล้วหรือยังคะ"]
    await a.reply("ยังซ่อมอยู่ครับ")
    assert a.result.vehicles[0].status == "in_repair" and "car1" in a.next_step()
    a.last_reply = ["ไม่ทราบว่าคาดว่าจะซ่อมแล้วเสร็จประมาณวันที่เท่าไรคะ"]
    await a.reply("ยังไม่แน่ใจครับ ต้องรออะไหล่")
    assert a.result.vehicles[0].completion_text == "ไม่ระบุ" and "car2" in a.next_step()


async def test_a_garage_that_cannot_reach_the_customer_leaves_a_task_for_the_company() -> None:
    a, _ = garage_ready()
    a.last_reply = ["รบกวนตรวจสอบรถทะเบียน 1กข 1234 กรุงเทพมหานคร ให้หน่อยนะคะ ว่าขณะนี้ซ่อมเสร็จเรียบร้อยแล้วหรือยังคะ"]
    await a.reply("ลูกค้ายังไม่เอารถเข้ามาครับ")
    assert a.result.vehicles[0].status == "awaiting_customer"
    a.last_reply = ["ไม่ทราบว่าทางอู่ได้โทรติดตามลูกค้าเพื่อนัดหมายเข้าซ่อมแล้วหรือยังคะ"]
    await a.reply("โทรไปแล้วครับ แต่ติดต่อไม่ได้")
    assert a.result.vehicles[0].status == "customer_unreachable"
    assert [t.type for t in a.result.tasks] == ["customer_contact"]


async def test_the_garage_call_cannot_close_with_a_car_left() -> None:
    close = "SAY: ขอบคุณมากค่ะ สวัสดีค่ะ\nEND: completed"
    a, model = garage_ready("garage-one-car", [close, close])
    await say(a, "ครับ")
    assert len(model.seen) == 2  # the first close was sent back: car1 was never asked


async def test_a_wrong_number_is_never_closed_as_completed() -> None:
    a, _ = agent("garage-one-car", ["SAY: ขออภัยที่รบกวนค่ะ สวัสดีค่ะ\nEND: completed"])
    a.start()
    await say(a, "ไม่ใช่ครับ ที่นี่ร้านข้าวมันไก่")
    assert a.state.outcome is Outcome.WRONG_PERSON


async def test_a_status_from_the_other_campaign_is_ignored() -> None:
    a, _ = garage_ready(replies=["SAY: รับทราบค่ะ\nUPDATE: car1 not_ready\nEND: none"])
    await a.reply("ยังไม่แน่ใจครับ")
    assert a.result.vehicles[0].status == "not_asked"


async def test_the_customer_names_a_day_or_only_a_month() -> None:
    a, _ = agent("repair-honda-city", [NEXT] * 4)
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available = "confirmed", True, True
    a.check.notice, a.check.consent = True, "granted"
    a.last_reply = ["ไม่ทราบว่าลูกค้าสะดวกนำรถเข้าซ่อมในช่วงวันไหนคะ"]
    await a.reply("น่าจะเดือนธันวาคมครับ")
    row = a.result.vehicles[0]
    assert row.status == "not_ready" and row.appointment_text == "น่าจะเดือนธันวาคมครับ"
    a.last_reply = ["ไม่ทราบว่าพอจะสะดวกวันไหนคะ"]
    await a.reply("งั้นวันศุกร์ที่ 12 ธันวาครับ")
    assert row.status == "date_given" and row.appointment_text == "งั้นวันศุกร์ที่ 12 ธันวาครับ"
    assert [t.type for t in a.result.tasks] == ["garage_notify"]


async def test_a_question_is_not_taken_as_an_answer_about_the_car() -> None:
    a, _ = agent("repair-yaris", ["SAY: เรื่องนี้ให้เจ้าหน้าที่ติดต่อกลับนะคะ\nUPDATE: car1 not_ready\nEND: none"])
    a.start()
    a.check.identity, a.check.ai_disclosed, a.check.available = "confirmed", True, True
    a.check.notice, a.check.consent = True, "granted"
    await a.reply("ต้องจ่ายค่าเสียหายส่วนแรกไหมครับ")
    assert a.result.vehicles[0].status == "not_asked"
    assert "question_follow_up" in [t.type for t in a.result.tasks]  # the promise of a call-back is kept


def test_the_partner_garage_is_not_a_promise() -> None:
    a, _ = agent("repair-yaris", [])
    reply = {"reply": ["อู่คู่สัญญาแจ้งว่ายังไม่สามารถติดต่อลูกค้าได้ค่ะ"]}
    assert not (a.problem(reply, "") or "").startswith("ต้องพูดแบบผู้หญิง")


def test_the_excel_template_round_trips_for_both_campaigns() -> None:
    garage = parse_workbook(CampaignId.GARAGE_FOLLOWUP, template_workbook(CampaignId.GARAGE_FOLLOWUP))[0]
    assert not garage["errors"] and len(garage["record"]["vehicles"]) == 3
    car = parse_workbook(CampaignId.REPAIR_APPOINTMENT, template_workbook(CampaignId.REPAIR_APPOINTMENT))[0]
    assert not car["errors"] and car["record"]["vehicle"]["plate"] == "2ขค 5678 นนทบุรี"


def test_a_yes_to_the_recording_still_counts_when_a_question_follows() -> None:
    from kpi_voicebot.agent import _consents

    assert _consents("ยินยอมครับ ขี่มอเตอร์ไซค์คุ้มครองไหมครับ")
    assert not _consents("บันทึกเสียงทำไมครับ")
