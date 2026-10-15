"""LLM reply interpretation with the rule layer kept as the safety floor.

The model reads the customer's words in context (the question just asked, recent turns)
and fills a strict JSON schema. Code still decides everything, and the model only adds
reading where the rules are weak:
- call-ending signals (do-not-call, objection, wrong person, refusal) come from the rules only;
- scores (numbers and "full marks") come from the rule parser only; the model may add which
  question a correction targets;
- in free-text answers (feedback, final comment, discrepancy detail) the model adds escalation tags only.
Any model failure falls back to the rules for that turn.
"""

import dataclasses
import logging
from typing import Any

from kpi_voicebot.engine import InterpretContext
from kpi_voicebot.llm import LLMClient, LLMError
from kpi_voicebot.thai_parse import Signals, normalize, read_signals, strip_particles

log = logging.getLogger("kpi.llm")

_BOOL_FIELDS = (
    "affirm",
    "negative",
    "question",
    "not_convenient",
    "hold",
    "repeat",
    "not_applicable",
    "skip",
    "ai_identity",
    "no_comment",
    "backchannel",
    "both_questions",
    "correction",
    "hedged",
    "has_question",
    "off_topic",
)
_SAFETY_FIELDS = ("dnc", "objection", "wrong_person", "refuse")
_TAGS = ("complaint", "claim_dispute", "safety", "urgent")

INTENTS = (*_BOOL_FIELDS, "unclear")
_FREE_TEXT_PREFIXES = ("feedback:", "final_comment", "discrepancy_detail")

# Which model intents may count for each pending question. Anything else the model lists
# is ignored: an intent that makes no sense for the question just asked is noise.
_ALLOWED: dict[str, frozenset[str]] = {
    "identity": frozenset(
        {"affirm", "negative", "question", "ai_identity", "hold", "repeat", "backchannel", "not_convenient"}
    ),
    "availability": frozenset(
        {"affirm", "negative", "question", "ai_identity", "hold", "repeat", "backchannel", "not_convenient"}
    ),
    "continue": frozenset(
        {"affirm", "backchannel", "question", "repeat", "hold", "not_convenient", "has_question", "off_topic"}
    ),
    "confirm": frozenset(
        {
            "affirm",
            "negative",
            "question",
            "repeat",
            "hold",
            "backchannel",
            "not_convenient",
            "hedged",
            "has_question",
            "off_topic",
        }
    ),
    "questions": frozenset(
        {"affirm", "negative", "no_comment", "question", "not_convenient", "has_question", "off_topic"}
    ),
    "score": frozenset(
        {
            "skip",
            "not_applicable",
            "correction",
            "both_questions",
            "repeat",
            "hold",
            "backchannel",
            "has_question",
        }
    ),  # not_convenient ends the call: during scores the model read "รอเป็นชั่วโมง" as "call me back"
    "surveyor_check": frozenset({"affirm", "negative", "not_applicable", "repeat", "hold"}),
    "callback_time": frozenset({"negative", "no_comment"}),
}


def _allowed(awaiting: str | None) -> frozenset[str]:
    key = (awaiting or "").split(":", 1)[0]
    return _ALLOWED.get(key, frozenset())


# Compact on purpose: the model lists only the intents that apply, so the reply is a few
# dozen tokens and arrives fast enough for a live turn.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intents": {"type": "array", "items": {"type": "string", "enum": list(INTENTS)}},
        "question_ref": {"type": ["integer", "null"]},
        "callback_time": {"type": ["string", "null"]},
        "tags": {"type": "array", "items": {"type": "string", "enum": list(_TAGS)}},
        "reflection": {"type": ["string", "null"]},
    },
    "required": ["intents", "question_ref", "callback_time", "tags", "reflection"],
    "additionalProperties": False,
}

_AWAITING_HINT = {
    "identity": "บอทเพิ่งถามว่าใช่ผู้รับสายตามชื่อหรือไม่ (affirm = ใช่ตัวเขา, negative/wrong_person = ไม่ใช่)",
    "availability": "บอทเพิ่งถามว่าสะดวกคุยตอนนี้ไหม (affirm = สะดวก, not_convenient = ไม่สะดวก/ให้โทรใหม่)",
    "continue": "บอทเพิ่งแจ้งข้อมูล ไม่ได้ถามคำถาม คำตอบรับสั้นๆ ให้ถือเป็น affirm/backchannel",
    "discrepancy_detail": "บอทถามว่าข้อมูลส่วนไหนไม่ถูกต้อง ลูกค้ากำลังเล่ารายละเอียด",
    "questions": "บอทถามว่ามีข้อสงสัยไหม (no_comment = ไม่มี, question = ถามเรื่องใหม่)",
    "surveyor_check": "บอทถามว่ามีพนักงานสำรวจภัยไปที่เกิดเหตุไหม (negative/not_applicable = ไม่มี)",
    "callback_time": "บอทถามเวลาที่สะดวกให้ติดต่อกลับ ให้ใส่ callback_time ตามคำพูดลูกค้า",
    "final_comment": "บอทถามความคิดเห็นเพิ่มเติม no_comment = ไม่มี",
    "second_factor": "บอทถามวันและเดือนเกิด",
}

SYSTEM_PROMPT = """คุณคือส่วนทำความเข้าใจคำตอบของลูกค้าในสายโทรออกของบริษัทประกันภัย (ภาษาไทย)
หน้าที่: อ่านคำตอบล่าสุดของลูกค้าโดยอิงคำถามล่าสุดของบอทและบทสนทนาก่อนหน้า แล้วตอบเป็น JSON ตาม schema เท่านั้น
ใส่ใน intents เฉพาะชื่อที่ตรงกับคำตอบ (ไม่ต้องใส่ที่ไม่เกี่ยว) และตอบ JSON บรรทัดเดียว
กฎ:
- ตีความตามบริบท คำตอบสั้นๆ เช่น "ได้ครับ" "ค่ะ" "ก็โอเคนะ" มีความหมายตามคำถามล่าสุด
- affirm = ยอมรับ/ใช่/ถูกต้อง/สะดวก ; negative = ปฏิเสธ/ไม่ใช่/ไม่ถูกต้อง (ถ้ามีทั้งสองอย่าง เช่น "ใช่ แต่เบี้ยไม่ใช่" ให้ negative=true)
- backchannel = แค่รับคำ เช่น "ค่ะ" "อืม" โดยไม่ได้ตอบเนื้อหา
- ไม่ต้องอ่านคะแนนเป็นตัวเลข ระบบจะอ่านตัวเลขเอง
- question_ref = เลขข้อเฉพาะเมื่อลูกค้าเอ่ยถึงข้ออื่นชัดเจน เช่น "ข้อแรกขอเป็นสี่" → 1 ไม่เช่นนั้น null
- correction = ลูกค้าขอเปลี่ยนคำตอบเดิม
- both_questions = ให้คะแนนเดียวกันทุกข้อในส่วนนี้ เช่น "ห้าทั้งสองข้อ"
- not_applicable = ลูกค้าบอกว่าไม่มีพนักงานสำรวจภัยไป/ไม่เกี่ยวข้อง ; skip = ขอไม่ตอบข้อนี้
- not_convenient = ไม่สะดวกตอนนี้/ขอให้โทรมาใหม่ ; callback_time = ช่วงเวลาที่ลูกค้าบอก (ข้อความสั้น) หรือ null
- hold = ขอให้รอสักครู่ ; repeat = ขอให้พูดซ้ำ/ไม่ได้ยิน ; ai_identity = ถามว่าเป็นใคร/เป็นคนหรือ AI ; question = ลูกค้าถามคำถาม
- no_comment = ไม่มีความคิดเห็น/ไม่มีคำถาม
- tags: complaint (ร้องเรียน/ไม่พอใจรุนแรง), claim_dispute (โต้แย้งเรื่องเคลม/การจ่าย), safety (มีผู้บาดเจ็บ/อันตราย), urgent (เร่งด่วน)
- hedged = ตอบแบบไม่แน่ใจ เช่น "มั้ง" "น่าจะใช่" "คิดว่านะ" "ไม่แน่ใจ" "จำไม่ได้"
- has_question = บอกว่ามีคำถามแต่ยังไม่ได้ถาม เช่น "มีครับ" "ขอถามหน่อย" "อยากสอบถามเพิ่มเติม" (ถ้าถามเนื้อหามาแล้วให้ใช้ question)
- off_topic = คำถามหรือเรื่องที่ไม่เกี่ยวกับประกันภัย กรมธรรม์ หรือสายนี้เลย เช่น "1+1 เท่ากับเท่าไหร่" "วันนี้ฝนตกไหม" (ใส่ question ด้วย)
- คำรับสั้นๆ เช่น "ครับ" "อืม" "อ่าฮะ" "โอเค" หลังบอทแจ้งข้อมูล = affirm (ลูกค้ารับว่าข้อมูลถูก)
- unclear = ฟังไม่รู้เรื่อง ไม่เกี่ยวกับคำถาม หรือตีความไม่ได้ (ห้ามเดาว่าเป็น affirm)
- คำแสลงที่แปลว่าถูกต้อง เช่น "ถั่วต้ม" ถือเป็น affirm
- คำบ่นหรือข้อเสนอแนะ ไม่ใช่ no_comment และไม่ใช่ skip
- reflection: เฉพาะเมื่อลูกค้าเล่าปัญหา/ข้อเสนอแนะ ให้สรุปประเด็นของลูกค้าเป็นวลีสั้น (ไม่เกิน 8 คำ) โดยใช้คำของลูกค้าเอง
  เช่น "ก็โอเคนะ แต่รอสายนานมาก" → "รอสายนาน" ; ห้ามมีตัวเลข ห้ามขอโทษ ห้ามสัญญาว่าจะแก้ไข ห้ามมีคำลงท้าย ; กรณีอื่นใส่ null
- ห้ามเดา ถ้าไม่แน่ใจให้ใส่ false/null"""


def _expected(awaiting: str | None) -> str:
    if not awaiting:
        return "ไม่มีคำถามค้าง"
    if awaiting.startswith("score:"):
        q = awaiting.split(":", 1)[1]
        scale = "0 ถึง 10" if q == "q5" else "1 ถึง 5"
        return f"บอทถามคะแนนข้อ {q.upper()} (ช่วงคะแนน {scale})"
    if awaiting.startswith("feedback:"):
        return f"บอทถามข้อเสนอแนะเพิ่มเติมของข้อ {awaiting.split(':', 1)[1].upper()} ลูกค้ากำลังเล่าเหตุผล"
    if awaiting.startswith("confirm:"):
        return "บอทเพิ่งแจ้งข้อมูลกรมธรรม์หนึ่งรายการให้ลูกค้ายืนยัน (คำรับสั้นๆ = affirm, ทักท้วง/บอกว่าไม่ตรง = negative)"
    return _AWAITING_HINT.get(awaiting, awaiting)


def build_messages(text: str, context: InterpretContext) -> list[dict[str, str]]:
    history = "\n".join(f"{'บอท' if who == 'bot' else 'ลูกค้า'}: {said}" for who, said in context.recent_turns[-6:])
    user = (
        f"สถานการณ์: {_expected(context.awaiting)}\n"
        f"คำถามล่าสุดของบอท: {context.last_question or '-'}\n"
        f"บทสนทนาก่อนหน้า:\n{history or '-'}\n\n"
        f"คำตอบล่าสุดของลูกค้า: {text}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


_BANNED_IN_REFLECTION = (
    "สัญญา",
    "รับประกัน",
    "จะแก้",
    "แก้ไขให้",
    "ชดเชย",
    "คืนเงิน",
    "ขอโทษ",
    "ขออภัย",
    "ภายใน",
    "ดำเนินการ",
    "ครับ",
    "ค่ะ",
    "คะ",
    "นะ",
)


def safe_reflection(phrase: object, customer_text: str) -> str | None:
    """Accept the model's echo of the customer's point only if it is short, plain Thai, promises
    nothing, and is built from the customer's own words."""
    if not isinstance(phrase, str):
        return None
    phrase = phrase.strip().removeprefix("เรื่อง").strip()
    if not 2 <= len(phrase) <= 30 or any(ch.isdigit() for ch in phrase):
        return None
    if not all("\u0e00" <= ch <= "\u0e7f" or ch == " " for ch in phrase):
        return None
    if any(word in phrase for word in _BANNED_IN_REFLECTION):
        return None
    compact = customer_text.replace(" ", "")
    pieces = [p for p in phrase.split() if p]
    if not pieces or not all(_shares_words(p, compact) for p in pieces):
        return None
    return phrase


def _shares_words(piece: str, text: str) -> bool:
    """At least half of the phrase appears verbatim in the customer's words (3-character windows)."""
    if len(piece) < 3:
        return piece in text
    windows = [piece[i : i + 3] for i in range(len(piece) - 2)]
    return sum(w in text for w in windows) * 2 >= len(windows)


def merge(rules: Signals, model: dict[str, Any], awaiting: str | None = None) -> Signals:
    """Combine the rule reading with the model reading under the limits in the module docstring."""
    model_tags = {t for t in model.get("tags") or [] if t in _TAGS}
    reflection = safe_reflection(model.get("reflection"), rules.text)
    if awaiting and awaiting.startswith(_FREE_TEXT_PREFIXES):
        return dataclasses.replace(rules, tags=sorted(set(rules.tags) | model_tags), reflection=reflection)

    raw_intents = set(model.get("intents") or [])
    intents = raw_intents & _allowed(awaiting)
    if "unclear" in raw_intents:
        # The model abstained: it may not turn the reply into a yes or no on its own.
        intents -= {"affirm", "negative", "backchannel"}
    # The model adds recall the keyword rules lack; it cannot remove what the rules saw.
    updates: dict[str, Any] = {f: getattr(rules, f) or f in intents for f in _BOOL_FIELDS}
    if updates["has_question"] and not rules.question:
        updates["question"] = False
    if "unclear" in raw_intents and not (rules.affirm or rules.negative):
        updates["unclear"] = True
    score = rules.score
    ref = model.get("question_ref")
    if score.value is not None and isinstance(ref, int) and score.question_ref is None:
        score = dataclasses.replace(score, question_ref=str(ref))
    updates["score"] = score
    updates["callback_time"] = model.get("callback_time") or rules.callback_time
    if awaiting and awaiting.startswith("score:"):
        updates["reflection"] = reflection
    return dataclasses.replace(rules, **updates)


# Short replies whose meaning does not depend on context beyond the pending question.
_CLEAR_AWAITING = ("identity", "availability", "continue", "confirm", "questions")
_OTHER_SIGNALS = (
    "dnc",
    "objection",
    "wrong_person",
    "refuse",
    "not_convenient",
    "hold",
    "repeat",
    "question",
    "hedged",
    "has_question",
    "skip",
    "not_applicable",
    "ai_identity",
    "correction",
)


def clear_without_model(rules: Signals, awaiting: str | None) -> bool:
    if not awaiting or not awaiting.startswith(_CLEAR_AWAITING):
        return False
    if any(getattr(rules, f) for f in _OTHER_SIGNALS):
        return False
    bare = strip_particles(normalize(rules.text)).replace(" ", "")
    if rules.backchannel or (rules.affirm and len(bare) <= 8):
        return True
    return awaiting == "questions" and rules.no_comment and len(bare) <= 8


class LLMInterpreter:
    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self.last_metrics: dict[str, Any] = {}

    async def interpret(self, text: str, context: InterpretContext) -> Signals:
        rules = read_signals(text)
        if clear_without_model(rules, context.awaiting):
            # "ครับ" / "ใช่ครับ" / "ไม่มีครับ": the rules are certain, and waiting ~0.5–3 s for the
            # model would only lengthen the silence before the bot speaks.
            self.last_metrics = {"skipped": "clear reply"}
            return rules
        try:
            model, metrics = await self.client.chat_json(
                build_messages(text, context), SCHEMA, name="customer_turn", max_tokens=120
            )
        except LLMError as exc:
            log.warning("LLM interpretation fell back to rules: %s", exc)
            self.last_metrics = {"fallback": str(exc)}
            return rules
        self.last_metrics = metrics
        return merge(rules, model, context.awaiting)
