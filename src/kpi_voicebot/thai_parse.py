"""Deterministic Thai reply parsing.

This is the rule-based interpreter used by the text simulator, and later the safety
layer that runs alongside the LLM interpreter (stop, do-not-call, wrong person and
notice objection must never depend on a model). It favours precision: anything it is
unsure of comes back as unclear so the engine can ask a short clarifying question.
"""

import re
from dataclasses import dataclass, field

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
# Only trailing particles: "คะ" also starts "คะแนน".
_PARTICLES = re.compile(r"(ครับผม|ครับ|ค่ะ|คะ|ค่า|จ้ะ|จ้า|นะ|น่ะ|ฮะ)(?=[\s,.!?]|$)")

# Words that contain number words but are not numbers.
_NUMBER_FALSE_FRIENDS = (
    "สามารถ",
    "ห้าม",
    "เก้าอี้",
    "ศูนย์รับ",
    "ศูนย์บริการ",
    "ศูนย์ฯ",
    "ศูนย์ซ่อม",
    "ศูนย์กลาง",
    "หนึ่งใน",
    "สองสามวัน",
    "สิบล้อ",
    "ทั้งสอง",
    "ทั้ง 2",
    "สองข้อ",
    "2 ข้อ",
)
_NUMBER_WORDS = {
    "ศูนย์": 0,
    "หนึ่ง": 1,
    "สอง": 2,
    "สาม": 3,
    "สี่": 4,
    "ห้า": 5,
    "หก": 6,
    "เจ็ด": 7,
    "แปด": 8,
    "เก้า": 9,
    "สิบ": 10,
}
_NUMBER_TOKEN = re.compile(r"\d+|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)))
_OUT_OF = re.compile(rf"({_NUMBER_TOKEN.pattern})\s*เต็ม\s*({_NUMBER_TOKEN.pattern})")
_CHANGE_TO = re.compile(rf"(?:เป็น|เอา|ขอ|แก้เป็น)\s*({_NUMBER_TOKEN.pattern})")
_QUESTION_REF = re.compile(r"ข้อ\s*(?:ที่)?\s*(แรก|สุดท้าย|\d+|หนึ่ง|สอง|สาม|สี่|ห้า)")
_HEDGE = ("มั้ง", "ประมาณ", "น่าจะ", "คิดว่า", "ราวๆ", "ราว ๆ")
_MAX_WORDS = ("เต็มเลย", "ให้เต็ม", "เต็มที่", "เต็มๆ", "เต็ม ๆ")
_BOTH = ("ทั้งสองข้อ", "ทั้ง 2 ข้อ", "ทั้งคู่", "ทุกข้อ", "เหมือนกันทั้งสอง", "เท่ากันทั้งสอง")
_CORRECTION = ("เปลี่ยน", "ขอแก้", "แก้เป็น", "เอาใหม่", "ขอเปลี่ยน", "เอ้ย", "ไม่ใช่ๆ")

_DNC = ("อย่าโทรมาอีก", "ไม่ต้องโทรมาอีก", "ห้ามโทร", "เลิกโทร", "ไม่ต้องโทรมา", "อย่าโทรมา")
_OBJECTION = (
    "ไม่อยากให้บันทึก",
    "ไม่ให้บันทึก",
    "ห้ามบันทึก",
    "ไม่อนุญาตให้บันทึก",
    "ไม่ยินยอมให้บันทึก",
    "อย่าบันทึก",
    "ไม่ยินยอม",
)
_WRONG_PERSON = (
    "ผิดคน",
    "โทรผิด",
    "ไม่ใช่คนนี้",
    "ไม่มีคนชื่อ",
    "ไม่รู้จัก",
    "ไม่ใช่เจ้าของ",
    "ไม่ใช่เขา",
    "ไม่ใช่ค่ะ คนละคน",
    "คนละคน",
)
_REFUSE = (
    "ไม่สนใจ",
    "ไม่อยากคุย",
    "ไม่ทำแบบสอบถาม",
    "ไม่อยากตอบแบบสอบถาม",
    "ไม่คุยแล้ว",
    "พอแค่นี้",
    "ขอวางสาย",
    "จะวางสายแล้ว",
    "ไม่อยากตอบแล้ว",
    "ไม่ตอบแล้ว",
)
_SKIP = ("ขอไม่ตอบ", "ไม่ขอตอบ", "ข้ามไป", "ขอข้าม", "ขอผ่าน", "ไม่อยากตอบข้อนี้", "ไม่ตอบข้อนี้")
_NOT_CONVENIENT = (
    "ไม่สะดวก",
    "ไม่ว่าง",
    "ติดประชุม",
    "ขับรถอยู่",
    "ขับรถ",
    "โทรมาใหม่",
    "โทรกลับ",
    "ทีหลัง",
    "ไว้ก่อน",
    "ค่อยโทร",
    "อีกสักพัก",
    "ยุ่งอยู่",
    "ทำงานอยู่",
    "ติดธุระ",
    "ไว้วันหลัง",
    "ไว้คราวหลัง",
)
_HOLD = ("รอสักครู่", "รอแป๊บ", "แป๊บนึง", "แป๊บนะ", "เดี๋ยวนะ", "สักครู่นะ", "รอเดี๋ยว", "รอก่อน", "แปปนึง")
_REPEAT = (
    "ขออีกที",
    "อีกทีได้ไหม",
    "อีกรอบ",
    "ทวนอีกที",
    "ขอฟังอีกที",
    "อะไรนะ",
    "ว่าไงนะ",
    "พูดอีกที",
    "ไม่ได้ยิน",
    "ฟังไม่ทัน",
    "ขอฟังอีก",
    "ทวนอีก",
    "พูดใหม่",
    "ว่าอะไรนะ",
    "ฟังไม่ชัด",
    "ไม่ค่อยได้ยิน",
)
_NOT_APPLICABLE = (
    "ไม่มีพนักงาน",
    "ไม่ได้มา",
    "ไม่มีใครมา",
    "ไม่มีคนมา",
    "ไม่ได้เรียก",
    "ไม่ได้ใช้",
    "ไม่มีเจ้าหน้าที่",
    "ไม่เกี่ยว",
    "ตอบไม่ได้",
    "ไม่มีคนไป",
    "ไม่ได้ไป",
    "ไม่มีพนักงานสำรวจ",
    "เคลียร์กันเอง",
)
_AI_IDENTITY = (
    "เป็นคนหรือเปล่า",
    "เป็นคนไหม",
    "เป็นคนจริง",
    "หุ่นยนต์",
    "เป็นเอไอ",
    "เป็น ai",
    "ใช่ ai",
    "ใช่เอไอ",
    "คุณเป็นใคร",
    "ใครโทรมา",
    "โทรจากไหน",
    "ใครพูด",
    "บอท",
)
_QUESTION = (
    "?",
    "ไหม",
    "มั้ย",
    "อะไร",
    "ยังไง",
    "อย่างไร",
    "เท่าไหร่",
    "เท่าไร",
    "เมื่อไหร่",
    "เมื่อไร",
    "ทำไม",
    "หรือเปล่า",
    "รึเปล่า",
    "ที่ไหน",
    "กี่วัน",
    "แบบไหน",
    "หรือยัง",
    "สงสัย",
    "สอบถาม",
    "อยากถาม",
    "ขอถาม",
)
_NEGATIVE = (
    "ไม่ใช่",
    "ไม่ถูก",
    "ผิด",
    "ไม่ตรง",
    "ไม่โอเค",
    "ไม่เอา",
    "ยังไม่ได้",
    "ไม่ได้รับ",
    "ไม่ได้ชำระ",
    "ไม่ได้จ่าย",
    "ไม่ค่อยถูก",
    "คลาดเคลื่อน",
    "เปลี่ยนแล้ว",
    "ไม่ได้ทำ",
    "แก้ด้วย",
)
_NO_COMMENT = (
    "ไม่มี",
    "ไม่มีค่ะ",
    "ไม่มีครับ",
    "ไม่มีอะไร",
    "ไม่มีแล้ว",
    "ไม่มีเพิ่ม",
    "พอแล้ว",
    "ไม่มีคำถาม",
    "ไม่สงสัย",
    "โอเคแล้ว",
    "เข้าใจแล้ว",
    "ชัดเจนแล้ว",
    "ไม่มีข้อเสนอแนะ",
)
_AFFIRM_START = (
    "ใช่",
    "ครับ",
    "ค่ะ",
    "คะ",
    "ค่า",
    "จ้า",
    "จ้ะ",
    "ถูก",
    "ได้",
    "โอเค",
    "ok",
    "สะดวก",
    "ยืนยัน",
    "เชิญ",
    "ว่ามา",
    "พูดอยู่",
    "แม่น",
    "เออ",
    "อือ",
    "อืม",
    "ฮะ",
    "ถูกต้อง",
    "เรียบร้อย",
    "มีค่ะ",
    "มีครับ",
    "ว่าง",
    "คุยได้",
    "พูดได้",
    "เป็นผม",
    "เป็นดิฉัน",
    "ผมเอง",
    "ดิฉันเอง",
    "ฉันเอง",
    "หนูเอง",
)
# "ถั่วต้ม" is common Thai wordplay for "ถูกต้อง".
_AFFIRM_ANY = ("ถูกต้อง", "ใช่แล้ว", "ถูกแล้ว", "ได้เลย", "สะดวกค่ะ", "สะดวกครับ", "ตามนั้น", "ครบถ้วน", "ถั่วต้ม")
_WH = ("อะไร", "ยังไง", "อย่างไร", "เท่าไหร่", "เท่าไร", "เมื่อไหร่", "เมื่อไร", "ทำไม", "ใคร", "ที่ไหน", "กี่")
# Unsure answers: a human operator re-checks these instead of taking them as a firm yes.
_UNSURE = ("ไม่แน่ใจ", "จำไม่ได้", "ไม่ชัวร์", "ไม่ค่อยแน่ใจ", "ไม่รู้สิ", "ไม่รู้เหมือนกัน")
# "I have a question" without the question itself.
_HAS_QUESTION = (
    "มีคำถาม",
    "ขอถามหน่อย",
    "ขอถามนิดนึง",
    "ขอสอบถาม",
    "อยากสอบถาม",
    "อยากถาม",
    "มีเรื่องจะถาม",
    "มีเรื่องอยากถาม",
    "สงสัยนิดนึง",
    "มีข้อสงสัย",
    "ขอถามอะไรหน่อย",
    "ถามหน่อย",
)
_META_FILLER = re.compile(
    r"(มีคำถาม|ขอถามอะไรหน่อย|ขอถามหน่อย|ขอถามนิดนึง|ขอสอบถาม|อยากสอบถาม|อยากถาม|มีเรื่องอยากถาม|มีเรื่องจะถาม|"
    r"สงสัยนิดนึง|มีข้อสงสัย|ถามหน่อย|เพิ่มเติม|หน่อย|นิดนึง|ครับผม|ครับ|ค่ะ|คะ|นะ|ผม|ดิฉัน|หนู|มี|ได้ไหม|ได้มั้ย|"
    r"เรื่อง|ด้วย|อีก|\s|,)"
)
_BACKCHANNEL = {
    "อืม",
    "อือ",
    "อื้อ",
    "อื้ม",
    "อึม",
    "อืมม",
    "ฮะ",
    "ฮับ",
    "ครับ",
    "ค่ะ",
    "คะ",
    "เออ",
    "อ่า",
    "อ้อ",
    "ค่า",
    "ฮึ",
    "จ้ะ",
    "จ้า",
    "อ่าฮะ",
    "อ่าห้ะ",
    "อะฮะ",
    "อ่าฮ่ะ",
    "อือฮึ",
    "อืมฮึ",
    "อ๋อ",
    "โอเค",
    "ok",
}
_TIME_WORDS = (
    "พรุ่งนี้",
    "มะรืน",
    "วันจันทร์",
    "วันอังคาร",
    "วันพุธ",
    "วันพฤหัส",
    "วันศุกร์",
    "วันเสาร์",
    "วันอาทิตย์",
    "จันทร์",
    "อังคาร",
    "พุธ",
    "พฤหัส",
    "ศุกร์",
    "เสาร์",
    "อาทิตย์",
    "เช้า",
    "บ่าย",
    "เย็น",
    "ค่ำ",
    "โมง",
    "ทุ่ม",
    "นาฬิกา",
    "สัปดาห์หน้า",
    "อาทิตย์หน้า",
    "เที่ยง",
    "ชั่วโมง",
    "นาที",
    "คืนนี้",
    "วันนี้",
)
_TIME_DIGITS = re.compile(r"\d{1,2}[:.]\d{2}")

ESCALATION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "complaint": (
        "ร้องเรียน",
        "แย่มาก",
        "ไม่พอใจมาก",
        "หยาบคาย",
        "พูดจาไม่ดี",
        "ไม่สุภาพ",
        "ผิดหวังมาก",
        "ห่วยมาก",
        "แย่ที่สุด",
        "ไม่ประทับใจเลย",
    ),
    "claim_dispute": (
        "เคลมไม่ได้",
        "ไม่จ่าย",
        "ปฏิเสธเคลม",
        "ปฏิเสธการเคลม",
        "ไม่ยอมจ่าย",
        "จ่ายไม่ครบ",
        "ไม่อนุมัติ",
        "ค่าซ่อมไม่ครบ",
        "ไม่รับผิดชอบ",
        "โกง",
    ),
    "safety": ("บาดเจ็บ", "เจ็บ", "โรงพยาบาล", "อันตราย", "ไม่ปลอดภัย", "เลือด", "รถชน", "ทำร้าย"),
    "urgent": ("ด่วน", "ฉุกเฉิน", "ตอนนี้เลย", "ช่วยด้วย", "รีบ"),
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_THAI_DIGITS).strip().lower())


def strip_particles(text: str) -> str:
    previous = None
    while previous != text:
        previous, text = text, _PARTICLES.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" ,.")


def contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(p in text for p in phrases)


def _number_value(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


@dataclass(frozen=True)
class ScoreParse:
    value: int | None = None
    candidates: tuple[int, ...] = ()
    is_max: bool = False
    hedged: bool = False
    question_ref: str | None = None

    @property
    def ambiguous(self) -> bool:
        return self.value is None and len(self.candidates) > 1


def parse_score(text: str) -> ScoreParse:
    t = normalize(text)
    hedged = contains_any(t, _HEDGE)
    ref_match = _QUESTION_REF.search(t)
    question_ref = ref_match.group(1) if ref_match else None
    if ref_match:
        t = t[: ref_match.start()] + " " + t[ref_match.end() :]
    for phrase in _NUMBER_FALSE_FRIENDS:
        t = t.replace(phrase, " ")

    out_of = _OUT_OF.search(t)
    if out_of:
        return ScoreParse(_number_value(out_of.group(1)), hedged=hedged, question_ref=question_ref)

    if contains_any(t, _MAX_WORDS) or re.search(r"เต็ม\s*$", t):
        return ScoreParse(is_max=True, hedged=hedged, question_ref=question_ref)

    tokens = [_number_value(m.group(0)) for m in _NUMBER_TOKEN.finditer(t)]
    if not tokens:
        return ScoreParse(hedged=hedged, question_ref=question_ref)

    if contains_any(t, _CORRECTION) or len(set(tokens)) > 1:
        change = list(_CHANGE_TO.finditer(t))
        if change:
            return ScoreParse(_number_value(change[-1].group(1)), hedged=hedged, question_ref=question_ref)

    unique = tuple(dict.fromkeys(tokens))
    if len(unique) == 1:
        return ScoreParse(unique[0], hedged=hedged, question_ref=question_ref)
    return ScoreParse(candidates=unique, hedged=hedged, question_ref=question_ref)


def callback_time_text(text: str) -> str | None:
    t = strip_particles(normalize(text))
    starts = [t.find(w) for w in _TIME_WORDS if w in t]
    digits = _TIME_DIGITS.search(t)
    if digits:
        starts.append(digits.start())
    if not starts:
        return None
    cleaned = t[min(starts) :]
    for tail in ("ได้ไหม", "ได้มั้ย", "แล้วกัน", "ดีกว่า", "นะ"):
        cleaned = cleaned.removesuffix(tail).strip()
    return cleaned.strip(" ,.") or None


def escalation_tags(text: str) -> list[str]:
    t = normalize(text)
    return [tag for tag, words in ESCALATION_KEYWORDS.items() if contains_any(t, words)]


@dataclass(frozen=True)
class Signals:
    """Everything the rule layer can see in one utterance; the interpreter decides what wins."""

    text: str
    dnc: bool = False
    objection: bool = False
    wrong_person: bool = False
    refuse: bool = False
    skip: bool = False
    not_convenient: bool = False
    hold: bool = False
    repeat: bool = False
    not_applicable: bool = False
    ai_identity: bool = False
    question: bool = False
    negative: bool = False
    no_comment: bool = False
    affirm: bool = False
    backchannel: bool = False
    both_questions: bool = False
    correction: bool = False
    hedged: bool = False
    has_question: bool = False
    unclear: bool = False
    off_topic: bool = False  # only the model sets this: a question with nothing to do with the call
    callback_time: str | None = None
    score: ScoreParse = field(default_factory=ScoreParse)
    tags: list[str] = field(default_factory=list)
    reflection: str | None = None


def _has_question_only(t: str) -> bool:
    """'มีครับ', 'อยากสอบถามเพิ่มเติมครับ': the customer announces a question but has not asked it yet."""
    bare = strip_particles(t)
    if bare in {"มี", "มีครับผม", "มีค่ะ", "มีครับ"}:
        return True
    return contains_any(t, _HAS_QUESTION) and len(_META_FILLER.sub("", t)) < 3


def read_signals(text: str) -> Signals:
    t = normalize(text)
    bare = strip_particles(t)
    unsure = contains_any(t, _UNSURE)
    negative = not unsure and (contains_any(t, _NEGATIVE) or bare.startswith("ไม่"))
    has_question = _has_question_only(t)
    no_comment = bare in {strip_particles(p) for p in _NO_COMMENT} or contains_any(t, _NO_COMMENT[3:])
    # "ค่ารักษาเท่าไหร่" / "ได้รับเมื่อไหร่" start like "ค่า" / "ได้" but ask something: not a yes.
    wh_question = contains_any(t, _WH)
    affirm = not negative and (
        (not wh_question and any(bare.startswith(p) or t.startswith(p) for p in _AFFIRM_START))
        or contains_any(t, _AFFIRM_ANY)
    )
    return Signals(
        text=text.strip(),
        dnc=contains_any(t, _DNC),
        objection=contains_any(t, _OBJECTION),
        wrong_person=contains_any(t, _WRONG_PERSON),
        refuse=contains_any(t, _REFUSE),
        skip=contains_any(t, _SKIP),
        not_convenient=contains_any(t, _NOT_CONVENIENT),
        hold=contains_any(t, _HOLD),
        repeat=contains_any(t, _REPEAT),
        not_applicable=contains_any(t, _NOT_APPLICABLE),
        ai_identity=contains_any(t, _AI_IDENTITY),
        question=(contains_any(t, _QUESTION) or contains_any(t, _WH)) and not has_question,
        negative=negative,
        no_comment=no_comment,
        affirm=affirm,
        backchannel=t.strip(" .,") in _BACKCHANNEL or bare.replace(" ", "") in _BACKCHANNEL,
        both_questions=contains_any(t, _BOTH),
        correction=contains_any(t, _CORRECTION),
        hedged=unsure or contains_any(t, _HEDGE),
        has_question=has_question,
        callback_time=callback_time_text(text),
        score=parse_score(text),
        tags=escalation_tags(text),
    )


_THAI_MONTHS = {
    "มกรา": 1,
    "ม.ค": 1,
    "กุมภา": 2,
    "ก.พ": 2,
    "มีนา": 3,
    "มี.ค": 3,
    "เมษา": 4,
    "เม.ย": 4,
    "พฤษภา": 5,
    "พ.ค": 5,
    "มิถุนา": 6,
    "มิ.ย": 6,
    "กรกฎา": 7,
    "ก.ค": 7,
    "สิงหา": 8,
    "ส.ค": 8,
    "กันยา": 9,
    "ก.ย": 9,
    "ตุลา": 10,
    "ต.ค": 10,
    "พฤศจิกา": 11,
    "พ.ย": 11,
    "ธันวา": 12,
    "ธ.ค": 12,
}
_TENS_WORDS = re.compile(r"(สาม|ยี่)?สิบ(เอ็ด|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)?")


def _thai_word_number(t: str) -> int | None:
    m = _TENS_WORDS.search(t)
    if m:
        tens = {"สาม": 3, "ยี่": 2, None: 1}[m.group(1)]
        unit = {"เอ็ด": 1, None: 0}.get(m.group(2), _NUMBER_WORDS.get(m.group(2) or "", 0))
        return tens * 10 + unit
    for word, value in sorted(_NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        if word in t and value > 0:
            return value
    return None


def parse_day_month(text: str) -> tuple[int, int] | None:
    """Parse a spoken day and month such as '15 มีนาคม' or 'สิบห้า มีนา'."""
    t = normalize(text)
    month = next((v for k, v in _THAI_MONTHS.items() if k in t), None)
    if month is None:
        numeric = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", t)
        if numeric:
            return int(numeric.group(1)), int(numeric.group(2))
        return None
    digits = re.search(r"\d{1,2}", t)
    day = int(digits.group(0)) if digits else _thai_word_number(t.split(next(k for k in _THAI_MONTHS if k in t))[0])
    if day is None or not 1 <= day <= 31:
        return None
    return day, month
