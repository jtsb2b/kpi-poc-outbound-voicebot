"""Display formatting for Thai wording (amounts and Buddhist-era dates)."""

from datetime import date

THAI_MONTHS = (
    "มกราคม",
    "กุมภาพันธ์",
    "มีนาคม",
    "เมษายน",
    "พฤษภาคม",
    "มิถุนายน",
    "กรกฎาคม",
    "สิงหาคม",
    "กันยายน",
    "ตุลาคม",
    "พฤศจิกายน",
    "ธันวาคม",
)


def format_amount(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def thai_date(value: date) -> str:
    return f"{value.day} {THAI_MONTHS[value.month - 1]} {value.year + 543}"
