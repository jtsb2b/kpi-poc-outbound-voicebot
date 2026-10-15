import pytest

from kpi_voicebot.phone import InvalidPhone, parse_destination
from kpi_voicebot.thai_parse import callback_time_text, parse_day_month, parse_score, read_signals


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("เอ่อ สี่มั้งครับ", 4),
        ("ห้าคะแนนค่ะ", 5),
        ("๔ ค่ะ", 4),
        ("ห้าเต็มห้า", 5),
        ("ศูนย์ค่ะ", 0),
        ("สามารถติดต่อได้เร็ว ให้ห้า", 5),
        ("ศูนย์รับแจ้งดีมาก ให้สิบ", 10),
        ("เปลี่ยนเป็นสามค่ะ", 3),
        ("ห้าทั้งสองข้อเลย", 5),
        ("8", 8),
    ],
)
def test_scores(text: str, value: int) -> None:
    assert parse_score(text).value == value


def test_score_edge_cases() -> None:
    assert parse_score("ก็โอเคนะ แต่รอนาน").value is None
    assert parse_score("สี่หรือห้าดี").candidates == (4, 5)
    assert parse_score("ให้เต็มเลย").is_max
    assert parse_score("ข้อแรกขอเป็นสี่").question_ref == "แรก"
    assert parse_score("เอ่อ สี่มั้งครับ").hedged


def test_signals() -> None:
    assert read_signals("ใช่ค่ะ").affirm
    assert read_signals("ไม่ใช่ค่ะ").negative and not read_signals("ไม่ใช่ค่ะ").affirm
    assert read_signals("ค่ะ").backchannel
    assert read_signals("อะไรนะคะ").repeat
    assert read_signals("ไม่ต้องโทรมาอีกนะ").dnc
    assert read_signals("ไม่อยากให้บันทึกค่ะ").objection
    assert read_signals("คุณเป็นคนหรือเปล่า").ai_identity
    assert read_signals("ไม่มีพนักงานมาเลย").not_applicable
    assert "complaint" in read_signals("พนักงานพูดจาไม่สุภาพ อยากร้องเรียน").tags
    # "คะ" also starts "คะแนน": particles are only stripped at the end of a word.
    assert parse_score("ห้าคะแนนค่ะ").value == 5


def test_callback_time() -> None:
    assert callback_time_text("ไม่สะดวก พรุ่งนี้บ่ายสองนะครับ") == "พรุ่งนี้บ่ายสอง"
    assert callback_time_text("ไม่ว่างค่ะ") is None


def test_day_month() -> None:
    assert parse_day_month("สิบห้า มีนาคม") == (15, 3)
    assert parse_day_month("วันที่ 3 ต.ค.") == (3, 10)


@pytest.mark.parametrize("raw", ["0812345678", "081-234-5678", "66812345678", "+66 81 234 5678", "0066812345678"])
def test_thai_mobile_formats(raw: str) -> None:
    d = parse_destination(raw)
    assert (d.kind, d.e164, d.sip_destination, d.dialable) == ("thai", "+66812345678", "0812345678", True)


def test_thai_landline() -> None:
    d = parse_destination("02-624-1111")
    assert (d.e164, d.sip_destination) == ("+6626241111", "026241111")


def test_international_is_stored_but_not_dialable() -> None:
    d = parse_destination("+1 650 253 0000")
    assert d.kind == "international" and d.e164 == "+16502530000" and not d.dialable and d.sip_destination is None


def test_extensions_need_flag() -> None:
    with pytest.raises(InvalidPhone):
        parse_destination("3200")
    assert parse_destination("3200", allow_extensions=True).sip_destination == "3200"


@pytest.mark.parametrize("raw", ["", "12", "0812", "abc", "08123456789012"])
def test_invalid_numbers(raw: str) -> None:
    with pytest.raises(InvalidPhone):
        parse_destination(raw)
