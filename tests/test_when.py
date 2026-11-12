"""Real-world dates (KPI, 11 Nov 2026): the bot knows today in Thai time and the days customers name are
worked out by code, not counted by a model."""

import datetime as dt

import pytest

from kpi_voicebot.models import CallbackRequest, ConversationResult, VehicleResult
from kpi_voicebot.when import BANGKOK, calendar_lines, fill_dates, hint, worked_out

WED = dt.date(2026, 11, 11)  # a Wednesday


@pytest.mark.parametrize(
    ("said", "day"),
    [
        ("พรุ่งนี้เช้า", "วันพฤหัสบดีที่ 12 พฤศจิกายน 2569 ช่วงเช้า"),
        ("ช่วงเย็น ๆ วันนี้ก็ได้ครับ", "วันพุธที่ 11 พฤศจิกายน 2569 ช่วงเย็น"),
        ("มะรืนนี้ตอนบ่าย", "วันศุกร์ที่ 13 พฤศจิกายน 2569 ช่วงบ่าย"),
        ("วันศุกร์นี้", "วันศุกร์ที่ 13 พฤศจิกายน 2569"),
        ("วันพุธ", "วันพุธที่ 18 พฤศจิกายน 2569"),  # said on a Wednesday: next week's
        ("จันทร์หน้า", "วันจันทร์ที่ 16 พฤศจิกายน 2569"),
        ("อีกสองอาทิตย์", "ประมาณวันพุธที่ 25 พฤศจิกายน 2569"),
        ("น่าจะอีก 2-3 วันครับ", "วันเสาร์ที่ 14 พฤศจิกายน 2569"),
        ("อาทิตย์หน้า", "ช่วงวันที่ 16 ถึง 22 พฤศจิกายน 2569"),  # a week, not a Sunday
        ("วันอาทิตย์นี้", "วันอาทิตย์ที่ 15 พฤศจิกายน 2569"),
        ("ต้นเดือนหน้า", "ช่วงวันที่ 1 ถึง 10 ธันวาคม 2569"),
        ("ปลายเดือน", "ช่วงวันที่ 21 ถึง 30 พฤศจิกายน 2569"),
        ("วันที่ 5", "วันเสาร์ที่ 5 ธันวาคม 2569"),  # the 5th has passed this month
        ("วันที่ยี่สิบห้าธันวา", "วันศุกร์ที่ 25 ธันวาคม 2569"),
        ("ไม่ใช่พรุ่งนี้ เป็นวันศุกร์", "วันศุกร์ที่ 13 พฤศจิกายน 2569"),  # the last one said stands
        ("พฤหัสอาทิตย์หน้าครับ ช่วงบ่าย", "วันพฤหัสบดีที่ 19 พฤศจิกายน 2569 ช่วงบ่าย"),
        ("วันพฤหัสที่ 19", "วันพฤหัสบดีที่ 19 พฤศจิกายน 2569"),
    ],
)
def test_the_days_customers_name(said: str, day: str) -> None:
    assert worked_out(said, WED) == day


def test_next_thursday_said_early_in_the_week_is_read_back_both_ways() -> None:
    assert worked_out("พฤหัสหน้า", WED) == ("วันพฤหัสบดีที่ 19 พฤศจิกายน 2569 (หรือวันพฤหัสบดีที่ 12 พฤศจิกายน ถ้าหมายถึงสัปดาห์นี้)")
    assert "ทวนวันที่ให้ลูกค้ายืนยัน" in hint("พฤหัสหน้าครับ", WED)


def test_words_without_a_day_give_none() -> None:
    for said in ("อาทิตย์ละครั้ง", "ไม่ทราบครับ", "ห้าคะแนน", ""):
        assert worked_out(said, WED) is None and hint(said, WED) == ""


def test_the_calendar_given_to_the_engines() -> None:
    lines = calendar_lines(dt.datetime(2026, 11, 11, 14, 45, tzinfo=BANGKOK))
    assert lines[0] == "วันนี้: วันพุธที่ 11 พฤศจิกายน 2569 เวลา บ่ายสองโมงสี่สิบห้านาที"
    assert "พรุ่งนี้: วันพฤหัสบดีที่ 12 พฤศจิกายน" in lines
    assert any(line.startswith("สัปดาห์หน้า: วันจันทร์ที่ 16 พฤศจิกายน") for line in lines)


def test_the_result_keeps_the_worked_out_day_next_to_the_words() -> None:
    result = ConversationResult(
        callback=CallbackRequest(requested=True, preferred_time_text="พรุ่งนี้เช้า"),
        vehicles=[VehicleResult(plate="1กข1234", appointment_text="จันทร์หน้า", completion_text="ไม่ทราบ")],
    )
    fill_dates(result, WED)
    assert result.callback.preferred_date == "วันพฤหัสบดีที่ 12 พฤศจิกายน 2569 ช่วงเช้า"
    car = result.vehicles[0]
    assert car.appointment_date == "วันจันทร์ที่ 16 พฤศจิกายน 2569" and car.completion_date is None
