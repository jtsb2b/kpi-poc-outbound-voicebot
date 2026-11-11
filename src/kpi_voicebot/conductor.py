"""The pipeline's checklist and checks behind a speech-to-speech engine (engine lab, 5 Nov 2026).

On the 5 Nov test calls the speech-to-speech engines were fast but wrong where the pipeline is right:
Gemini said "ได้ค่ะ สี่คะแนน" after "ก็ได้", pushed a customer who did not want to score, and read the
whole question again on every re-ask; Agni took 1.5 and 2.8 as scores and heard "0" as 4. The pipeline
gets these right because code, not the model, decides what an answer means.

So the engine speaks and listens, and this decides. When the customer answers, the engine calls `record`
before it replies; the answer is read by where the call is (the step), not by the engine's labels (it
called a score "confirmed", "unclear" or "feedback" in testing), checked with the pipeline's own rules
(score parsing, range, half points, either/or, refusals, ask-why, consent, closing comments) on the words
the customer actually said, and recorded through the pipeline's own setters. The reply tells the engine
what to say next. When the engine answers without calling `record`, `interpret` reads the customer's
words from this worker's own transcription the same way, and the engine is told where the call now is.
`end_call` is refused once while the checklist is not done.
"""

from __future__ import annotations

import re
from typing import Any

from kpi_voicebot.agent import (
    _OTHER_PERSON,
    MAX_COMMENT_ROUNDS,
    CallAgent,
    Item,
    _consents,
    _declines_recording,
    _how_to_ask_why,
    _item_fit,
    _more_to_say,
    _sorry,
)
from kpi_voicebot.repair_engine import UNSURE, WHEN
from kpi_voicebot.survey_engine import SurveyEngine
from kpi_voicebot.thai_parse import parse_score, read_signals
from kpi_voicebot.tts_text import speakable

# What `record` may be told: hints only, the step decides.
STATUSES = [
    "answered",
    "confirmed",
    "refused",
    "feedback",
    "wrong_person",
    "not_available",
    "granted",
    "declined",
    "disputed",
    "unclear",
    "done",
    "repaired",
    "in_repair",
    "awaiting_customer",
    "booked",
    "customer_unreachable",
    "not_at_garage",
    "date_given",
    "not_ready",
    "completion",
    "appointment",
    "pickup",
]
END_REASONS = ["completed", "wrong_person", "refused", "do_not_call", "callback"]

# "ไม่ให้คะแนนได้ไหม", "ข้ามข้อนี้", "ไม่อยากตอบ": the customer does not want to score this one.
_NO_SCORE = re.compile(r"ไม่\s*(อยาก|ขอ)?\s*ให้\s*คะแนน|ขอ\s*ไม่\s*ให้|ข้าม|ไม่\s*(อยาก)?\s*ตอบ|ไม่\s*ประเมิน")
# "ไม่ทราบว่ามีคำถามเพิ่มเติมไหมคะ", "มีข้อเสนอแนะเพิ่มเติมไหมคะ" (not the free-look's "แจ้งข้อมูลสำคัญเพิ่มเติม").
_ASKS_MORE = re.compile(r"(คำถาม|สอบถาม|ข้อเสนอแนะ|เรื่องอื่น|ความคิดเห็น|เพิ่มเติม).{0,30}(ไหม|มั้ย|หรือเปล่า|อีกไหม)")
_SHORT_ASK = "ถามสั้นๆ ว่า 'ข้อนี้ให้กี่คะแนนดีคะ' ห้ามอ่านชื่อหัวข้อยาวซ้ำ ห้ามขออภัยซ้ำ"
_PLAIN = "ตอบรับสั้นๆ คำเดียวพอ ห้ามพูดว่าจะบันทึกไว้ให้เจ้าหน้าที่"


class Conductor:
    """One call's checklist, fed by what was said and by the engine's `record` and `end_call` calls."""

    def __init__(self, agent: CallAgent) -> None:
        self.agent = agent
        self.items = {i.id: i for i in agent.items}
        self.close_refused = False
        self.recorded: list[dict[str, Any]] = []  # every `record` and `interpret`, for the call's events

    # ---- what was said ----

    def bot_said(self, text: str) -> None:
        """A bot turn as the engine transcribed it: marks the notice, the AI disclosure, the free-look
        notice and the policy values the customer has now heard, as the pipeline does after a turn."""
        a = self.agent
        a.last_reply = [text]
        a.report_delivery(1, True)
        if re.search(r"เคพีไอ|เอไอ|\bAI\b", text):
            a.check.ai_disclosed = True  # the transcript may write "เอไอ" where the pipeline looks for "AI"
        if a.free_look_text and re.search(r"ยกเลิก", text) and re.search(r"30|สามสิบ", text):
            a.check.free_look = True  # "สามสิบ วัน" in words, where the pipeline looks for "30"
            a.result.free_look_delivery = "full"
        if a.check.notice:
            a.state.body_started = True

    def customer_said(self, text: str) -> None:
        self.agent.history.append(("customer", text))

    # ---- where the call is ----

    def step(self) -> str:
        a, c = self.agent, self.agent.check
        if c.identity == "pending":
            return "identity"
        if not c.available and a.campaign.party != "garage":
            return "availability"
        if a.campaign.recording_notice and c.consent == "pending":
            return "recording"
        if c.feedback_pending:
            return "feedback"
        pending = self._pending()
        if pending is not None:
            return pending.kind  # score / fact / status
        if a.free_look_text and not c.free_look:
            return "free_look"
        if isinstance(a.base, SurveyEngine):
            return "done" if c.final_comment else "final_comment"
        if a.campaign.party == "garage":
            return "done"  # KPI's garage script: every car asked, thank them and hang up (no "any questions?")
        return "done" if c.questions_asked else "questions"

    def _pending(self) -> Item | None:
        return next((i for i in self.agent.items if not self.agent._done(i)), None)

    # ---- the engine's calls ----

    def record(self, item: str, status: str, score: Any = None, words: str = "", heard: str = "") -> dict[str, Any]:
        """Check one answer and record it. `words` is the customer's answer as the engine passes it;
        `heard` is what this worker's own transcription heard since the bot last spoke, which wins when
        the two disagree (the engine may "hear" a score that was never said)."""
        out = self._record(item.strip(), status.strip(), score, words.strip(), heard.strip())
        self.recorded.append({"item": item, "status": status, "score": score, "heard": heard[:80], "ok": out["ok"]})
        out["next"] = self.next_instruction()
        return out

    def interpret(self, text: str, reply: str = "") -> dict[str, Any] | None:
        """The customer answered and the engine did not call `record`: read it here, by the step. None
        when there was nothing to read (a question, a pleasantry, the call already done), or when the
        engine's `reply` asked the same thing again: it did not catch the answer, the customer is about to
        give it again, and recording it now would put the next answer on the wrong question (testing:
        "ห้า" recorded here, Gemini asked again, "สี่" then landed on the next question)."""
        step = self.step()
        if step in ("done", "free_look") or not text.strip():
            return None
        if step == "status":
            out = self._car(None, "", text, rules_only=True)
            if not out["ok"]:
                return None
            self.recorded.append({"item": "car", "status": "interpreted", "heard": text[:80], "ok": True})
            out["next"] = self.next_instruction()
            return out
        if step == "fact":
            return self._group_moved_on(text, reply)
        if step == "questions" and (read_signals(text).question or read_signals(text).has_question):
            return None  # "ต้องเอารถเข้าไปเลยไหมครับ" is a question, not "no more questions" (9 Nov)
        if step in ("questions", "final_comment") and not _ASKS_MORE.search(self._asked()):
            return None  # "ครับ" to the free-look notice is not "no more questions" (testing)
        if self._asks_again(step, reply):
            return None
        out = self._record(step, "answered", None, "", text.strip())
        self.recorded.append({"item": step, "status": "interpreted", "heard": text[:80], "ok": out["ok"]})
        if not out["ok"]:
            return None
        out["next"] = self.next_instruction()
        return out

    def _group_moved_on(self, text: str, reply: str) -> dict[str, Any] | None:
        """A policy group the customer agreed to ("ถูกต้องครับ แต่…ต่อครั้งหรือต่อปี") while the engine
        answered and went on to the next group without `record` (testing): confirmed, as the pipeline
        does, once the reply reads the next group. A "no" or a correction is left for the engine."""
        a = self.agent
        current = self._pending()
        signals = read_signals(text)
        if current is None or not signals.affirm or signals.negative or signals.correction:
            return None
        later = [i for i in a.items if i.kind == "fact" and i is not current and not a._done(i)]
        nxt = later[0] if later else None
        keywords = [k for f in a.campaign.policy_fields if nxt and f.field in nxt.fields for k in f.keywords]
        moved = bool(keywords and any(k in reply for k in keywords)) or (
            nxt is None and bool(re.search(r"ยกเลิก", reply))
        )
        if not moved:
            return None
        a.check.heard_values.add(current.id)
        a._apply_item(current, "confirmed", -1, text)
        self.recorded.append({"item": current.id, "status": "interpreted", "heard": text[:80], "ok": True})
        return {"ok": True, "say": f"ลูกค้ายืนยัน{current.label}แล้ว", "next": self.next_instruction()}

    def _asked(self) -> str:
        """The bot's line before the customer's latest words: what the customer was answering."""
        history = self.agent.history
        last_customer = max((i for i, (who, _) in enumerate(history) if who == "customer"), default=len(history))
        return next((t for who, t in reversed(history[:last_customer]) if who == "bot"), "")

    def _asks_again(self, step: str, reply: str) -> bool:
        """The engine's reply asks for what the step is still waiting for."""
        if not reply:
            return False
        a = self.agent
        if step == "identity":
            first = (a.vars.get("customer_name") or " ").split()[0]
            return first in reply and bool(re.search(r"ใช่|ไหม|เรียนสาย", reply)) and "เคพีไอ" not in reply
        if step == "availability":
            return "สะดวก" in reply and not re.search(r"บันทึกเสียง", reply)
        if step == "recording":
            return bool(re.search(r"ยินยอม|บันทึกเสียง", reply))
        if step == "score":
            if not re.search(r"กี่คะแนน|ให้กี่|เท่าไหร่|เท่าไร|คะแนน.{0,12}ดีคะ", reply):
                return False  # it went on to something else (a reason, the comments)
            current = self._pending()
            later = [i for i in a.items if i.kind == "score" and i is not current and not a._done(i)]
            return not any(_item_fit(i, reply)[0] >= 0.75 for i in later)  # not moved on to the next question
        return False

    def _record(self, item: str, status: str, score: Any, words: str, heard: str) -> dict[str, Any]:
        a, c = self.agent, self.agent.check
        text = heard or words
        step = self.step()
        if item == "identity" or (step == "identity" and item not in ("availability", "recording")):
            someone_else = _OTHER_PERSON.search(text) and not read_signals(text).affirm
            if status == "wrong_person" or someone_else or read_signals(text).wrong_person:
                c.identity = "wrong_person"
                a.result.identity_result = "wrong_person"
                return ok("ไม่ใช่ลูกค้า: ขออภัยที่รบกวนสั้นๆ ไม่ต้องให้ข้อมูลใดๆ แล้วเรียก end_call (wrong_person)")
            c.identity = "confirmed"
            a.result.identity_result = "confirmed"
            return ok("ยืนยันตัวตนแล้ว")
        if item == "availability" or (step == "availability" and item not in ("recording",)):
            signals = read_signals(text)
            if status == "not_available" or signals.not_convenient or signals.refuse:
                return ok(
                    "ลูกค้าไม่สะดวก: 'ไม่เป็นไรค่ะ ต้องขออภัยที่รบกวนนะคะ' แล้วถามเวลาที่สะดวกให้โทรกลับ"
                    " เมื่อได้เวลาแล้วขอบพระคุณ แล้วเรียก end_call (callback) พร้อมเวลา"
                )
            c.available = True
            return ok("สะดวกคุย")
        if item == "recording" or step == "recording":
            return self._consent(status, text)
        if item == "notice":
            c.notice = True
            a.result.notice_delivered = True
            a.state.body_started = True
            return ok("แจ้งการบันทึกเสียงแล้ว")
        if item == "free_look":
            c.free_look = True
            a.result.free_look_delivery = "full"
            return ok("แจ้งสิทธิยกเลิกแล้ว")
        if item == "questions" or (step == "questions" and item not in self.items):
            c.questions_asked = True
            return ok("ลูกค้าไม่มีคำถามเพิ่ม")
        if item == "final_comment" or (step == "final_comment" and item not in self.items):
            return self._comment(text)
        spec = self.items.get(item)
        if step in ("score", "feedback") and (spec is None or spec.kind == "score"):
            return self._score(status, score, words, heard)
        if spec is not None and spec.kind == "fact":
            if status not in ("confirmed", "disputed", "unclear"):
                status = "disputed" if read_signals(text).negative else "confirmed"
            c.heard_values.add(spec.id)  # the engine read the group to the customer itself
            a._apply_item(spec, status, -1, text)
            if status == "confirmed":
                return ok(f"ลูกค้ายืนยัน{spec.label}แล้ว")
            return ok(
                "ลูกค้าแจ้งว่าข้อมูลไม่ตรง: ขอบคุณที่แจ้ง บอกว่าจะให้เจ้าหน้าที่ตรวจสอบ ห้ามเถียง ห้ามยืนยันว่าข้อมูลในระบบถูก ห้ามทวนทั้งกลุ่มใหม่"
            )
        if step == "status" or (spec is not None and spec.kind == "status"):
            return self._car(spec if spec is not None and spec.kind == "status" else None, status, text)
        return fail("ตอนนี้ไม่มีคำถามที่รอคำตอบเรื่องนี้ ทำตามขั้นถัดไป")

    def _car(self, spec: Item | None, status: str, text: str, rules_only: bool = False) -> dict[str, Any]:
        """A car's answer, read first by the pipeline's own rules on the garage's (or customer's) words
        (`_settle_car`), then by the engine's status for the car it names. A date is taken only when the
        words hold one: Agni made up "วันที่ 1 ธันวาคม" for a car the garage said was done (5 Nov).
        The reply carries the approved KPI line for each car now settled."""
        a = self.agent

        def state() -> list[tuple[Any, ...]]:
            return [(v.status, v.completion_text, v.appointment_text, v.pickup_text) for v in a.result.vehicles]

        before = state()
        a.rule_cars.clear()
        a.car_acks = []
        # The car being asked is the conductor's current one; the engine's line may say its plate in words
        # ("หนึ่ง กอ ขอ…"), which the pipeline's matching does not read: give it the written question.
        current = self._pending()
        asked = self._asked()
        if current is not None and current.kind == "status" and a._car_in_question(asked) is None:
            asked = a._car_line(current)
        spec = spec or (current if current is not None and current.kind == "status" else None)
        a._settle_car(text, asked)
        if state() == before and not rules_only and spec is not None and status:
            dated = bool(WHEN.search(text) or UNSURE.search(text))
            if status in ("completion", "appointment", "pickup", "date_given") and not dated:
                return fail(
                    f"ยังไม่ได้ยินวันที่ (ได้ยินว่า '{text}'): ห้ามเดาหรือพูดวันที่เอง ถามวันที่อีกครั้งสั้นๆ"
                    " ถ้าอีกฝ่ายไม่ทราบ ให้เรียก record ด้วยคำของเขาอีกครั้ง"
                )
            a._set_car(spec, status, text, by_model=True)
        if state() == before:
            return fail("ยังไม่ได้คำตอบเรื่องรถคันนี้: ถามคำถามเดิมอีกครั้งสั้นๆ ไม่ต้องอ่านทะเบียนซ้ำทั้งหมด")
        acks, a.car_acks = a.car_acks, []
        if acks:
            said = " ".join(dict.fromkeys(acks))
            return ok(f'พูดตามนี้ (ใจความต้องครบ): "{speakable(said)}" ห้ามถามวันที่ของรถคันที่จบแล้ว')
        return ok("รับทราบแล้ว: ถามต่อตามขั้นถัดไป ห้ามพูดประโยคตั้งเบิกเคลมจนกว่าระบบจะบอก")

    def _consent(self, status: str, text: str) -> dict[str, Any]:
        a = self.agent
        no, yes = _declines_recording(text), _consents(text)
        if no or (status == "declined" and not yes):
            a._set_consent("declined")
            return ok(f"ลูกค้าไม่ยินยอม (หยุดบันทึกเสียงแล้ว): พูดว่า '{a._peek_line('recording_declined')}' แล้วคุยต่อ")
        if yes or (status == "granted" and not text):
            a._set_consent("granted")
            return ok("ลูกค้ายินยอมให้บันทึกเสียง: ขอบพระคุณสั้นๆ แล้วไปต่อ")
        return fail(f"ยังไม่ชัดว่ายินยอมไหม (ได้ยินว่า '{text}'): ถามอีกครั้งอย่างสุภาพว่ายินยอมให้บันทึกเสียงไหมคะ")

    def _score(self, status: str, score: Any, words: str, heard: str) -> dict[str, Any]:
        a, c = self.agent, self.agent.check
        said = heard or words
        if c.feedback_pending:
            # The reason for a low score: whatever the customer said is it (they may decline to give one).
            item = self.items[c.feedback_pending]
            a._apply_item(item, "feedback", -1, said)
            return ok(f"ได้เหตุผลแล้ว: {_PLAIN} แล้วไปข้อถัดไป")
        current = self._pending()
        if current is None or current.kind != "score":
            return fail("ตอนนี้ไม่มีคำถามคะแนนที่รอคำตอบ")
        if status == "refused" or _NO_SCORE.search(said):
            answer = next(x for x in a.result.survey_answers if x.question == current.id)
            answer.status = "skipped"
            answer.raw_utterance = said
            c.status[current.id] = "skipped"
            return ok("ลูกค้าไม่ประสงค์ให้คะแนนข้อนี้: 'ได้ค่ะ ไม่เป็นไรค่ะ' ห้ามโน้มน้าว ห้ามถามซ้ำ ไปข้อถัดไปเลย")
        given = self._heard_score(current, score, words, heard)
        if isinstance(given, dict):
            return given
        a._apply_item(current, "answered", given, said)
        if c.feedback_pending == current.id:
            return ok(f"ได้ {given} คะแนน: ทวนคะแนนสั้นๆ แล้ว{_how_to_ask_why(current, given)} (ถามครั้งเดียว)")
        sorry = "ขออภัยสั้นๆ " if given <= current.feedback_below and _sorry(current, given) else "ไม่ต้องขออภัย "
        return ok(f"ได้ {given} คะแนน (ลูกค้าบอกเหตุผลมาแล้ว ไม่ต้องถาม) : ทวนคะแนนสั้นๆ {sorry}แล้วไปข้อถัดไป")

    def _heard_score(self, item: Item, score: Any, words: str, heard: str) -> int | dict[str, Any]:
        """The score the customer said, or what to ask instead. Our own transcription wins: a score the
        engine passes that the customer's words do not contain is never recorded."""
        lo, hi = item.scale
        said = heard or words
        parsed = parse_score(said)
        if parsed.half is not None:
            n = int(parsed.half)
            if lo <= n and n + 1 <= hi:
                return fail(
                    f"ลูกค้าให้ {parsed.half:g} คะแนน แต่คะแนนเป็นจำนวนเต็ม: ห้ามบันทึกเอง ห้ามปัด"
                    f" ถามสั้นๆ ว่า 'คะแนนเป็นจำนวนเต็มนะคะ ข้อนี้จะให้ {n} หรือ {n + 1} คะแนนดีคะ'"
                )
        if parsed.candidates and parsed.value is None:
            options = " หรือ ".join(str(x) for x in parsed.candidates)
            return fail(f"ลูกค้าให้มาสองค่า: ถามสั้นๆ ว่า 'ข้อนี้จะให้ {options} คะแนนดีคะ'")
        value = hi if parsed.is_max else parsed.value
        if value is None and not heard:
            value = score if isinstance(score, int) and not isinstance(score, bool) else None
        if value is None:
            return fail(
                f"ลูกค้ายังไม่ได้ให้คะแนน (ได้ยินว่า '{said}'): ห้ามเดาหรือพูดคะแนนเอง"
                f" ถ้าลูกค้าถามช่วงคะแนน ตอบว่าตั้งแต่ {lo} ถึง {hi} คะแนน แล้ว{_SHORT_ASK}"
                " ถ้าลูกค้าไม่อยากให้คะแนน ให้เรียก record ด้วย status refused"
            )
        if not lo <= value <= hi:
            return fail(f"{value} อยู่นอกช่วง: บอกสั้นๆ ว่าข้อนี้ให้ได้ตั้งแต่ {lo} ถึง {hi} คะแนน แล้ว{_SHORT_ASK}")
        return value

    def _comment(self, text: str) -> dict[str, Any]:
        a, c = self.agent, self.agent.check
        if text and _more_to_say(text):
            a.result.final_comment_raw = " / ".join(x for x in (a.result.final_comment_raw, text) if x)
            c.comment_rounds += 1
            if c.comment_rounds < MAX_COMMENT_ROUNDS:
                c.comment_open = True
                return ok(
                    "ลูกค้าให้ความคิดเห็น: ขอบพระคุณหรือขออภัยสั้นๆ ประโยคเดียว ไม่สรุป ไม่รับปาก"
                    " แล้วถามว่า 'มีเรื่องอื่นเพิ่มเติมอีกไหมคะ' ห้ามปิดสายจนกว่าลูกค้าจะบอกว่าไม่มีแล้ว"
                )
        c.final_comment = True
        c.comment_open = False
        return ok("ไม่มีความคิดเห็นเพิ่ม: ขอบพระคุณสั้นๆ ประโยคเดียว กล่าวสวัสดี แล้วเรียก end_call (completed)")

    def end_call(self, reason: str, callback_time: str = "") -> tuple[bool, dict[str, Any]]:
        """May the call end now? Once, a "completed" close with the checklist not done is refused."""
        a, c = self.agent, self.agent.check
        reason = reason if reason in END_REASONS else "completed"
        asked = " ".join(t for who, t in a.history[-3:] if who == "bot")
        if self.step() == "questions" and _ASKS_MORE.search(asked):
            c.questions_asked = True  # "any more questions?" asked and answered: the close is the answer
        # Comments heard out and "anything more?" asked: ending is the customer's "ไม่มีแล้ว" (testing).
        heard_out = self.step() == "final_comment" and c.comment_rounds > 0
        if (
            reason == "completed"
            and self.step() != "done"
            and not heard_out
            and not self.close_refused
            and c.identity == "confirmed"
        ):
            self.close_refused = True
            return False, fail("ยังไม่ครบ ห้ามวางสาย ทำต่อ", self.next_instruction())
        if c.comment_open:
            c.final_comment = True
        self.recorded.append({"item": "end_call", "status": reason, "ok": True})
        a._close(reason, callback_time)
        return True, ok("วางสายได้")

    def next_instruction(self) -> str:
        """What the engine says next, in the pipeline's own words for the step (never its codes: Gemini
        read "ในส่วนของ q1" aloud in testing)."""
        a, c = self.agent, self.agent.check
        step = self.step()
        if step == "identity":
            return "รอให้ลูกค้ายืนยันว่าเป็นคุณ" + a.vars.get("customer_name", "")
        if step == "availability":
            if not c.ai_disclosed:
                return "แนะนำตัวสั้นๆ ว่า ดิฉันน้องเคพีไอ ผู้ช่วย AI จากกรุงไทยพานิชประกันภัย บอกว่าโทรมาเรื่องอะไร แล้วถามว่าสะดวกคุยไหม"
            return "ถามว่าตอนนี้สะดวกคุยไหม แล้วรอคำตอบ"
        if step == "recording":
            if c.notice:
                return "รอคำตอบว่ายินยอมให้บันทึกเสียงไหม"
            return f'พูดตามนี้ทุกคำ: "{speakable(a.notice_text)}" แล้วรอคำตอบ'
        if step == "feedback":
            item = self.items[str(c.feedback_pending)]
            return f"ถามเหตุผลของคะแนนข้อ{item.label}: {_how_to_ask_why(item, c.status[item.id])} (ถามครั้งเดียว)"
        pending = self._pending()
        if step == "score" and pending is not None:
            lo, hi = pending.scale
            first = all(s == "pending" for s in c.status.values()) or pending.scale != (1, 5)
            scale = f" บอกช่วงสั้นๆ ว่าตั้งแต่ {lo} ถึง {hi} คะแนน" if first else ""
            return f'ถามข้อถัดไป: "{speakable(pending.approved)}"{scale} แล้วรอคำตอบ'
        if step == "fact" and pending is not None:
            return f'ทวน{pending.label}ทั้งกลุ่มในตาเดียวตามคำอ่านนี้: "{speakable(pending.approved)}" แล้วรอคำยืนยัน'
        if step == "status" and pending is not None:
            first = all(v.status == "not_asked" for v in a.result.vehicles)
            lead = f"{a._peek_line('intro')} " if first and a.campaign.party == "garage" else ""
            line = speakable(lead + a._car_line(pending))
            return f'ถามตามนี้แล้วรอคำตอบ: "{line}"'
        if step == "free_look":
            return f'พูดตามนี้ทุกคำ: "{speakable(a.free_look_text)}"'
        if step == "final_comment":
            if c.comment_open:
                return "รอฟังลูกค้าให้จบ แล้วเรียก record (final_comment) ด้วยคำของลูกค้า"
            return "ถามสั้นๆ ว่ามีข้อเสนอแนะเพิ่มเติมไหมคะ แล้วรอคำตอบ"
        if step == "questions":
            return "ถามว่ามีคำถามเพิ่มเติมไหมคะ แล้วรอคำตอบ"
        return "ครบแล้ว: ขอบพระคุณสั้นๆ ประโยคเดียว กล่าวสวัสดี แล้วเรียก end_call (completed) ไม่ต้องบอกเบอร์ศูนย์บริการ"


def ok(say: str, next_step: str = "") -> dict[str, Any]:
    return {"ok": True, "say": say, **({"next": next_step} if next_step else {})}


def fail(say: str, next_step: str = "") -> dict[str, Any]:
    return {"ok": False, "say": say, **({"next": next_step} if next_step else {})}
