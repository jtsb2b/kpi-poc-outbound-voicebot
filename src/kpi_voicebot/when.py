"""Today's date in Thailand and what the customer's "พรุ่งนี้" / "พฤหัสหน้า" / "อีกสองอาทิตย์" mean on it.

KPI asked (11 Nov 2026) for the bot to know the real date and work days out properly: a model guesses at
"วันศุกร์หน้า" and gets the date wrong, so the date is worked out here, by code, and handed to the model as
"คำนวณให้แล้ว", and the result keeps the worked-out date next to the customer's own words.

Everything counts in Thai time (Asia/Bangkok): the containers run in UTC, where 00:00-07:00 in Bangkok is
still yesterday.
"""

import datetime as dt
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from kpi_voicebot.thai_text import THAI_MONTHS
from kpi_voicebot.tts_text import clock_words

if TYPE_CHECKING:
    from kpi_voicebot.models import ConversationResult

BANGKOK = ZoneInfo("Asia/Bangkok")
WEEKDAYS = ("จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์")


def now_th() -> dt.datetime:
    return dt.datetime.now(BANGKOK)


def today_th() -> dt.date:
    return now_th().date()


def day_name(d: dt.date, year: bool = False) -> str:
    """ "วันพฤหัสบดีที่ 12 พฤศจิกายน" (+ " 2569")."""
    text = f"วัน{WEEKDAYS[d.weekday()]}ที่ {d.day} {THAI_MONTHS[d.month - 1]}"
    return f"{text} {d.year + 543}" if year else text


def today_line(now: dt.datetime) -> str:
    return f"วันนี้: {day_name(now.date(), year=True)} เวลา {clock_words(now.hour, now.minute)}"


def calendar_lines(now: dt.datetime) -> list[str]:
    """Today and the days a customer is likely to name, ready to say: the model reads a date off this list
    instead of counting weekdays itself."""
    today = now.date()
    monday_next = today + dt.timedelta(days=7 - today.weekday())
    lines = [
        today_line(now),
        f"พรุ่งนี้: {day_name(today + dt.timedelta(days=1))}",
        f"มะรืนนี้: {day_name(today + dt.timedelta(days=2))}",
    ]
    rest = [today + dt.timedelta(days=i) for i in range(1, (monday_next - today).days)]
    if rest:
        lines.append("สัปดาห์นี้ที่เหลือ: " + ", ".join(day_name(d) for d in rest))
    lines.append("สัปดาห์หน้า: " + ", ".join(day_name(monday_next + dt.timedelta(days=i)) for i in range(7)))
    lines.append(f"สิ้นเดือนนี้: {day_name(_month_end(today))}")
    return lines


def _month_end(d: dt.date) -> dt.date:
    return _add_months(d.replace(day=1), 1) - dt.timedelta(days=1)


def _add_months(d: dt.date, n: int) -> dt.date:
    month = d.month - 1 + n
    year, month = d.year + month // 12, month % 12 + 1
    end = (dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(year, month, min(d.day, end))


# ---- what the customer's words mean ----


@dataclass(frozen=True)
class When:
    words: str  # what the customer said, e.g. "พฤหัสหน้า"
    start: dt.date
    end: dt.date | None = None  # a span: "สัปดาห์หน้า", "ปลายเดือน"
    also: dt.date | None = None  # "พฤหัสหน้า" said early in the week may mean this week's Thursday
    approx: bool = False  # "อีกสองอาทิตย์": about then

    def spoken(self, year: bool = False) -> str:
        if self.end is None:
            return ("ประมาณ" if self.approx else "") + day_name(self.start, year)
        if self.start.month == self.end.month:
            span = f"วันที่ {self.start.day} ถึง {self.end.day} {THAI_MONTHS[self.end.month - 1]}"
        else:
            first = f"{self.start.day} {THAI_MONTHS[self.start.month - 1]}"
            span = f"วันที่ {first} ถึง {self.end.day} {THAI_MONTHS[self.end.month - 1]}"
        return f"ช่วง{span}" + (f" {self.end.year + 543}" if year else "")


_NUM_WORDS = {
    "หนึ่ง": 1,
    "เอ็ด": 1,
    "สอง": 2,
    "สาม": 3,
    "สี่": 4,
    "ห้า": 5,
    "หก": 6,
    "เจ็ด": 7,
    "แปด": 8,
    "เก้า": 9,
}
_TENS = re.compile(r"(สอง|ยี่|สาม)?สิบ(เอ็ด|หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)?")
_ONES = re.compile("|".join(_NUM_WORDS))


def _digits(text: str) -> str:
    """Thai number words as digits: "ยี่สิบห้า" -> "25", "สองอาทิตย์" -> "2อาทิตย์"."""
    t = text.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))
    t = re.sub(r"สองสาม|สามสี่", lambda m: "3" if m.group(0) == "สองสาม" else "4", t)  # "อีกสองสามวัน"
    t = re.sub(r"(\d+)\s*[-–]\s*(\d+)(?=\s*(?:วัน|อาทิตย์|สัปดาห์|เดือน))", r"\2", t)  # "อีก 2-3 วัน": the later one

    def tens(m: re.Match[str]) -> str:
        ten = {"สอง": 2, "ยี่": 2, "สาม": 3}.get(m.group(1) or "", 1)
        return str(ten * 10 + _NUM_WORDS.get(m.group(2) or "", 0))

    t = _TENS.sub(tens, t)
    return _ONES.sub(lambda m: str(_NUM_WORDS[m.group(0)]), t)


_DAY = r"(จันทร์|อังคาร|พุธ|พฤหัส(?:บดี)?|ศุกร์|เสาร์|อาทิตย์)"
_MONTH_WORDS = {
    "มกรา": 1,
    "กุมภา": 2,
    "มีนา": 3,
    "เมษา": 4,
    "พฤษภา": 5,
    "มิถุนา": 6,
    "กรกฎา": 7,
    "สิงหา": 8,
    "กันยา": 9,
    "ตุลา": 10,
    "พฤศจิกา": 11,
    "ธันวา": 12,
    "ม.ค": 1,
    "ก.พ": 2,
    "มี.ค": 3,
    "เม.ย": 4,
    "พ.ค": 5,
    "มิ.ย": 6,
    "ก.ค": 7,
    "ส.ค": 8,
    "ก.ย": 9,
    "ต.ค": 10,
    "พ.ย": 11,
    "ธ.ค": 12,
}
_MONTH = "(" + "|".join(re.escape(k) for k in sorted(_MONTH_WORDS, key=len, reverse=True)) + ")"
_PATTERNS = [
    ("relative", re.compile(r"(เมื่อวานซืน|เมื่อวาน|วันนี้|พรุ่งนี้|มะรืน(?:นี้)?)")),
    ("in", re.compile(r"(?:อีก|ภายใน)\s*(\d{1,2})?\s*(วัน|อาทิตย์|สัปดาห์|เดือน)|(\d{1,2})\s*(วัน|อาทิตย์|สัปดาห์|เดือน)ข้างหน้า")),
    ("weekday_week", re.compile(rf"(?:วัน)?{_DAY}\s*(?:ของ)?\s*(?:สัปดาห์|อาทิตย์)\s*(นี้|หน้า)")),
    ("weekday_date", re.compile(rf"(?:วัน)?{_DAY}\s*ที่\s*(\d{{1,2}})(?!\s*\d)")),
    ("weekend", re.compile(r"เสาร์\s*อาทิตย์\s*(นี้|หน้า)?")),
    ("week", re.compile(r"(?<!วัน)(?:สัปดาห์|อาทิตย์)\s*(นี้|หน้า)")),
    ("weekday", re.compile(rf"(?:วัน)?{_DAY}\s*(นี้|หน้า|ถัดไป)?")),
    ("day_month", re.compile(rf"(?:วันที่\s*)?(\d{{1,2}})\s*(?:เดือน\s*)?{_MONTH}\S*")),
    ("day", re.compile(r"วันที่\s*(\d{1,2})(?!\s*\d)")),
    ("month_part", re.compile(r"(ต้น|กลาง|ปลาย|สิ้น)\s*เดือน\s*(นี้|หน้า)?|เดือนหน้า")),
]


def _year_for(today: dt.date, day: int, month: int) -> dt.date | None:
    """A day and month named in a call is the next one to come; within a month back it is a recent date
    (the accident date, "ได้รับกรมธรรม์ 1 พ.ย.")."""
    for year in (today.year, today.year + 1):
        try:
            d = dt.date(year, month, day)
        except ValueError:
            return None
        if d >= today - dt.timedelta(days=31):
            return d
    return None


def _day_of_month(n: int, today: dt.date) -> dt.date | None:
    """ "วันที่ 25" with no month: this month's if still to come, else next month's."""
    for month_start in (today.replace(day=1), _add_months(today.replace(day=1), 1)):
        try:
            d = month_start.replace(day=n)
        except ValueError:
            continue
        if d >= today:
            return d
    return None


def resolve(text: str, today: dt.date) -> list[When]:
    """Every day the words name, in the order said. "พฤหัสหน้า" is next week's Thursday; when this week's
    Thursday is still to come it is kept in `also`, so the bot reads the date back for the customer to
    confirm instead of picking one silently."""
    t = _digits(text)
    taken: list[tuple[int, int]] = []
    out: list[tuple[int, When]] = []

    def free(m: re.Match[str]) -> bool:
        return not any(m.start() < b and a < m.end() for a, b in taken)

    monday_next = today + dt.timedelta(days=7 - today.weekday())
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(t):
            if not free(m):
                continue
            w = _one(kind, m, today, monday_next)
            if w is not None:
                taken.append((m.start(), m.end()))
                out.append((m.start(), w))
    return [w for _, w in sorted(out, key=lambda p: p[0])]


def _one(kind: str, m: re.Match[str], today: dt.date, monday_next: dt.date) -> When | None:
    words = m.group(0).strip()
    days = dt.timedelta
    if kind == "relative":
        shift = {"เมื่อวานซืน": -2, "เมื่อวาน": -1, "วันนี้": 0, "พรุ่งนี้": 1}.get(m.group(1), 2)
        return When(words, today + days(shift))
    if kind == "in":
        n = int(m.group(1) or m.group(3) or 1)
        unit = m.group(2) or m.group(4)
        if unit == "เดือน":
            return When(words, _add_months(today, n), approx=True)
        return When(words, today + days(n * (1 if unit == "วัน" else 7)), approx=unit != "วัน")
    if kind == "weekend":
        saturday = (monday_next + days(5)) if m.group(1) == "หน้า" else today + days((5 - today.weekday()) % 7)
        return When(words, saturday, saturday + days(1))
    if kind == "week":
        if m.group(1) == "หน้า":
            return When(words, monday_next, monday_next + days(6))
        return When(words, today, monday_next - days(1))
    if kind == "weekday_week":  # "พฤหัสอาทิตย์หน้า", "ศุกร์สัปดาห์นี้": no doubt which week
        target = next(i for i, name in enumerate(WEEKDAYS) if name.startswith(m.group(1)[:4]))
        monday = monday_next if m.group(2) == "หน้า" else monday_next - days(7)
        return When(words, monday + days(target))
    if kind == "weekday_date":  # "วันพฤหัสที่ 19": the date is what counts
        d = _day_of_month(int(m.group(2)), today)
        return When(words, d) if d else None
    if kind == "weekday":
        if m.group(1) == "อาทิตย์" and not words.startswith("วัน"):
            return None  # a bare "อาทิตย์" is a week ("อาทิตย์ละครั้ง"); Sunday is "วันอาทิตย์"
        target = next(i for i, name in enumerate(WEEKDAYS) if name.startswith(m.group(1)[:4]))
        if m.group(2) in ("หน้า", "ถัดไป"):
            this_week = today + days(target - today.weekday())
            return When(words, monday_next + days(target), also=this_week if this_week > today else None)
        ahead = (target - today.weekday()) % 7
        if ahead == 0 and m.group(2) != "นี้":
            ahead = 7  # "วันพุธ" said on a Wednesday is next Wednesday; "พุธนี้" is today
        return When(words, today + days(ahead))
    if kind == "day_month":
        d = _year_for(today, int(m.group(1)), _MONTH_WORDS[m.group(2)])
        return When(words, d) if d else None
    if kind == "day":
        d = _day_of_month(int(m.group(1)), today)
        return When(words, d) if d else None
    # parts of a month
    if m.group(0) == "เดือนหน้า":
        first = _add_months(today.replace(day=1), 1)
        return When(words, first, _month_end(first))
    part, which = m.group(1), m.group(2)
    first = today.replace(day=1)
    span = {"ต้น": (1, 10), "กลาง": (11, 20)}.get(part)
    if which == "หน้า" or (which is None and span is not None and today.day > span[1]):
        first = _add_months(first, 1)
    if span is None:  # ปลายเดือน / สิ้นเดือน: from the 21st, or from today when that is later
        return When(words, max(first.replace(day=21), today), _month_end(first))
    return When(words, first.replace(day=span[0]), first.replace(day=span[1]))


_PART_OF_DAY = re.compile(r"(?:ตอน|ช่วง)(สาย)|(เช้า|เที่ยง|บ่าย|เย็น|หัวค่ำ|ค่ำ)")


def worked_out(text: str | None, today: dt.date) -> str | None:
    """The worked-out date to keep next to the words in a call result:
    "พรุ่งนี้ช่วงเย็น" -> "วันพฤหัสบดีที่ 12 พฤศจิกายน 2569 ช่วงเย็น"."""
    if not text:
        return None
    named = resolve(text, today)
    if not named:
        return None
    when = named[-1]  # "ไม่ใช่พรุ่งนี้ เป็นวันศุกร์": the last one said stands
    part = _PART_OF_DAY.search(text)
    tail = f" ช่วง{part.group(1) or part.group(2)}" if part else ""
    alt = f" (หรือ{day_name(when.also)} ถ้าหมายถึงสัปดาห์นี้)" if when.also else ""
    return when.spoken(year=True) + tail + alt


def hint(text: str, today: dt.date) -> str:
    """For the model, this turn: what the days the customer named are, worked out by code."""
    named = resolve(text, today)
    if not named:
        return ""
    lines = []
    for w in named:
        line = f'"{w.words}" คือ {w.spoken()}'
        if w.also:
            line += f" (ถ้าหมายถึงสัปดาห์นี้ คือ {day_name(w.also)}: ทวนวันที่ให้ลูกค้ายืนยัน)"
        lines.append(line)
    return "คำนวณให้แล้ว (วันที่ลูกค้าพูดถึง ใช้ได้เลย ห้ามนับวันเอง): " + " / ".join(lines)


def fill_dates(result: ConversationResult, today: dt.date) -> None:
    """The worked-out day next to every time the other side named, for the people who act on the result."""
    result.callback.preferred_date = worked_out(result.callback.preferred_time_text, today)
    for car in result.vehicles:
        car.completion_date = worked_out(car.completion_text, today)
        car.appointment_date = worked_out(car.appointment_text, today)
        car.pickup_date = worked_out(car.pickup_text, today)
