"""Role-play suite: the agent, on the production settings, against a customer played by an LLM.

Every scenario is a persona (or a fixed script) and the checks its call must pass. General checks run on
every call: no fallback line, no line said twice in a row, no question left hanging when the call ends,
the bot's name in the introduction and the introduction said once, no "เสียงไม่ค่อยชัด" to a clear
customer, turns of a sane length, and the call ending within the turn limit.

It calls the configured LLM (and Google for the customer), so it is a manual tool, never run in CI:

    kpi-roleplay                 # every scenario
    kpi-roleplay pa_busy sv_na   # the named ones
    kpi-roleplay --repeat 3      # each scenario three times (the model varies)

Timing (silence, barge-in, speech arriving mid-reply) is the voice loop's job and is covered by unit tests;
here a silent customer is a scripted `None`.
"""

import argparse
import asyncio
import datetime as dt
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kpi_voicebot.agent import AgentDialogue, CallAgent
from kpi_voicebot.campaigns import get_profile
from kpi_voicebot.config import get_settings
from kpi_voicebot.engine import estimated_seconds
from kpi_voicebot.llm import llm_client
from kpi_voicebot.models import Directive, Outcome
from kpi_voicebot.simulator import build_engine

OC = Outcome
Check = Callable[["Call"], str | None]

CUSTOMER = (
    "คุณกำลังแสดงเป็นลูกค้าคนไทยที่รับโทรศัพท์จากบริษัทประกัน (ผู้โทรเป็น AI ผู้ช่วย) {persona}\n"
    "พูดแบบคนไทยคุยโทรศัพท์จริง สั้นๆ หนึ่งหรือสองประโยค ใช้ ครับ ตอบเฉพาะสิ่งที่ลูกค้าพูดออกมา "
    "ไม่ต้องมีเครื่องหมายคำพูด ไม่ต้องบรรยาย ถ้าบอทถามสิ่งที่บทบาทไม่ได้บอก ให้ตอบตามปกติแบบคนทั่วไป "
    "คุยไปจนกว่าบอทจะลาเอง ทำตามบทบาทเท่านั้น: ถ้าบทบาทบอกว่าข้อมูลถูกต้อง ห้ามแย้งหรือแต่งว่าข้อมูลผิด"
)


@dataclass
class Call:
    """One played call: the agent after the call, and what was said."""

    scenario: Scenario
    agent: CallAgent
    turns: list[tuple[str, str]] = field(default_factory=list)  # ("bot"|"customer", text)
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    reply_seconds: list[float] = field(default_factory=list)
    ended: bool = False

    @property
    def bot(self) -> list[str]:
        return [t for who, t in self.turns if who == "bot"]

    @property
    def bot_text(self) -> str:
        return " ".join(self.bot)

    def field_status(self, name: str) -> str:
        return next(f.status for f in self.agent.result.policy_fields if f.field == name)

    def score(self, question: str) -> Any:
        return next(a for a in self.agent.result.survey_answers if a.question == question)

    def task_types(self) -> list[str]:
        return [t.type for t in self.agent.result.tasks]


@dataclass
class Scenario:
    id: str
    profile: str
    what: str  # one line for the report
    persona: str = ""  # Thai, for the customer model
    script: list[str | None] | None = None  # fixed customer lines instead of a persona; None = silence
    outcomes: set[Outcome] = field(default_factory=set)
    checks: list[Check] = field(default_factory=list)
    garbled: bool = False  # the customer's words are hard to make out: "เสียงไม่ชัด" is fair
    max_turns: int = 26


# ---- checks ----


def fields_are(**expected: str) -> Check:
    def check(c: Call) -> str | None:
        wrong = {k: c.field_status(k) for k, v in expected.items() if c.field_status(k) != v}
        return f"fields {wrong} (expected {expected})" if wrong else None

    return check


def only_disputed(*names: str) -> Check:
    def check(c: Call) -> str | None:
        disputed = sorted(f.field for f in c.agent.result.policy_fields if f.status in ("disputed", "unclear"))
        return None if disputed == sorted(names) else f"disputed/unclear {disputed}, expected {sorted(names)}"

    return check


def consent_is(value: bool | None) -> Check:
    return lambda c: (
        None
        if c.agent.result.recording_consent is value
        else (f"recording consent {c.agent.result.recording_consent}, expected {value}")
    )


def bot_says(pattern: str, why: str) -> Check:
    return lambda c: None if re.search(pattern, c.bot_text) else f"bot never said {why} ({pattern})"


def bot_never(pattern: str, why: str) -> Check:
    def check(c: Call) -> str | None:
        hit = next((t for t in c.bot if re.search(pattern, t)), None)
        return f"bot said {why}: {hit[:90]}" if hit else None

    return check


def has_task(kind: str) -> Check:
    return lambda c: None if kind in c.task_types() else f"no {kind} task (tasks {c.task_types()})"


def no_task(kind: str) -> Check:
    return lambda c: None if kind not in c.task_types() else f"unexpected {kind} task"


def scores_are(**expected: Any) -> Check:
    def check(c: Call) -> str | None:
        wrong = {q: c.score(q).value for q, v in expected.items() if c.score(q).value != v}
        return f"scores {wrong} (expected {expected})" if wrong else None

    return check


def follow_up_or_hotline(c: Call) -> str | None:
    """An unanswerable question: noted for staff to call back, or the customer given the hotline."""
    if "question_follow_up" in c.task_types() or "02-624-1111" in c.bot_text:
        return None
    return "neither a follow-up for staff nor the hotline"


def scores_were_said(c: Call) -> str | None:
    """Every recorded score is one the customer actually gave (the simulated customer may drift from its
    script, so this checks the bot against what was said, not against the persona)."""
    from kpi_voicebot.thai_parse import read_signals

    said: set[int] = set()
    for who, text in c.turns:
        if who == "customer":
            sc = read_signals(text).score
            said |= {v for v in (sc.value, *sc.candidates) if v is not None}
            said |= {int(n) for n in re.findall(r"\d+", text)}
    wrong = [
        (a.question, a.value) for a in c.agent.result.survey_answers if a.value is not None and a.value not in said
    ]
    return f"scores the customer never gave: {wrong}" if wrong else None


def callback_time_noted(c: Call) -> str | None:
    return None if c.agent.result.callback.preferred_time_text else "callback time not recorded"


def no_policy_values(c: Call) -> str | None:
    hit = next((t for t in c.bot if re.search(r"300,000|15,000|2,000|สมใจ|somchai|99/9", t)), None)
    return f"policy details told to someone not verified: {hit[:90]}" if hit else None


def nothing_asked_after_stop(c: Call) -> str | None:
    """Once the customer says they want to stop, the next bot turn closes."""
    for i, (who, text) in enumerate(c.turns):
        if who == "customer" and re.search(r"ไม่อยากตอบ|ไม่อยากคุย|วางสาย|พอแล้ว|ไม่ตอบแล้ว|อย่าโทร", text):
            following = [t for w, t in c.turns[i + 1 :] if w == "bot"]
            if len(following) > 1:
                return f"the bot kept talking after '{text[:40]}': {following[1][:80]}"
    return None


GENERAL: list[tuple[str, Callable[[Call], str | None]]] = []


def general(fn: Callable[[Call], str | None]) -> Callable[[Call], str | None]:
    GENERAL.append((fn.__name__, fn))
    return fn


@general
def ended_in_time(c: Call) -> str | None:
    return None if c.ended else f"not finished after {c.scenario.max_turns} turns"


@general
def no_fallback(c: Call) -> str | None:
    n = sum(1 for kind, _ in c.events if kind == "agent_fallback")
    return f"{n} fallback line(s)" if n else None


@general
def no_repeat(c: Call) -> str | None:
    for a, b in zip(c.bot, c.bot[1:], strict=False):
        if a and a == b:
            return f"said twice in a row: {a[:80]}"
    return None


@general
def name_in_introduction(c: Call) -> str | None:
    if "AI" in c.bot_text and "น้องเคพีไอ" not in c.bot_text:
        return "introduced as AI without the name น้องเคพีไอ"
    return None


@general
def introduced_once(c: Call) -> str | None:
    asked = any(re.search(r"AI|เอไอ|หุ่นยนต์|คนจริง|บอท", t) for w, t in c.turns if w == "customer")
    intros = [t for t in c.bot if re.search(r"(ดิฉัน|ดิฉันเป็น|ดิฉันชื่อ)\s*(น้องเคพีไอ)?\s*,?\s*(ผู้ช่วย AI|AI ผู้ช่วย)", t)]
    return None if asked or len(intros) <= 1 else f"introduced {len(intros)} times"


@general
def no_false_bad_line(c: Call) -> str | None:
    if c.scenario.garbled:
        return None
    hit = next((t for t in c.bot if "เสียงไม่ค่อยชัด" in t or "ไม่ค่อยได้ยิน" in t), None)
    return f"blamed the line to a clear customer: {hit[:80]}" if hit else None


@general
def no_hanging_question(c: Call) -> str | None:
    if c.ended and c.bot and c.agent.state.finished:
        last = c.bot[-1]
        if last.endswith("คะ") and not last.endswith("นะคะ"):
            return f"ended the call on a question: {last[-60:]}"
    return None


@general
def turn_length(c: Call) -> str | None:
    from kpi_voicebot.models import Segment

    long = [t for t in c.bot if estimated_seconds([Segment(text=t)]) > 40]
    return f"{len(long)} turn(s) over 40 s: {long[0][:60]}" if long else None


@general
def reply_time(c: Call) -> str | None:
    slow = [s for s in c.reply_seconds if s > 6]
    return f"{len(slow)} repl(ies) over 6 s (max {max(slow):.1f})" if slow else None


@general
def only_scores_said(c: Call) -> str | None:
    return scores_were_said(c)


@general
def no_markup(c: Call) -> str | None:
    hit = next((t for t in c.bot if re.search(r"[*#`]|https?://|\[|\]|<|>|ครับ|ผม", t)), None)
    return f"markup, tags or male words in a transcript line: {hit[:80]}" if hit else None


# ---- the scenarios ----

PA_OK = {"plan_name": "confirmed", "premium": "confirmed", "beneficiary": "confirmed", "delivery_target": "confirmed"}

SCENARIOS: list[Scenario] = [
    # --- PA: the call goes through ---
    Scenario(
        "pa_happy",
        "pa-email",
        "everything correct, agrees to recording",
        "คุณชื่อสมชาย ใจดี เต็มใจคุย ยินยอมให้บันทึกเสียง ข้อมูลทุกข้อถูกต้อง",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[consent_is(True), fields_are(**PA_OK)],
    ),
    Scenario(
        "pa_post",
        "pa-post",
        "policy sent by post: the address is read and confirmed",
        "คุณชื่อสมชาย ใจดี ยินยอมให้บันทึกเสียง ข้อมูลทุกข้อถูกต้อง",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[bot_says(r"99/9", "the address"), fields_are(delivery_target="confirmed")],
    ),
    Scenario(
        "pa_minimal",
        "pa-email",
        "answers only ครับ / อือ / ได้",
        "คุณชื่อสมชาย ตอบแค่คำเดียวทุกครั้ง เช่น ครับ อือ ได้ ใช่ ไม่พูดอย่างอื่นเลย",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[consent_is(True)],
    ),
    Scenario(
        "pa_english",
        "pa-email",
        "mixes English: OK, yes, correct",
        "คุณชื่อสมชาย พูดไทยปนอังกฤษ เช่น OK ครับ, yes, correct ครับ ยินยอมให้บันทึกเสียง ข้อมูลถูกต้อง",
        outcomes={OC.POLICY_CONFIRMED},
    ),
    Scenario(
        "pa_hello",
        "pa-email",
        "starts with ฮัลโหล ได้ยินไหม",
        "คุณชื่อสมชาย ประโยคแรกให้พูดว่า 'ฮัลโหล ฮัลโหล ได้ยินไหมครับ' จากนั้นคุยตามปกติ ยินยอมบันทึกเสียง ข้อมูลถูกต้อง",
        outcomes={OC.POLICY_CONFIRMED},
    ),
    Scenario(
        "pa_hold",
        "pa-email",
        "asks the bot to hold a moment",
        "คุณชื่อสมชาย ตอนบอทเริ่มทวนข้อมูล ให้พูดว่า 'รอสักครู่นะครับ' แล้วตาต่อไปพูดว่า 'โอเค ว่าต่อได้ครับ' ยินยอมบันทึกเสียง ข้อมูลถูกต้อง",
        outcomes={OC.POLICY_CONFIRMED},
    ),
    Scenario(
        "pa_offtopic",
        "pa-email",
        "chit-chat off topic in the middle",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อมูลถูกต้อง แต่กลางสายให้ถามเรื่องนอกเรื่องหนึ่งครั้ง เช่น 'วันนี้ฝนจะตกไหมครับ'",
        outcomes={OC.POLICY_CONFIRMED},
    ),
    Scenario(
        "pa_garbled",
        "pa-email",
        "speech recognition garbles some answers",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อมูลถูกต้อง แต่สองครั้งในสายให้พูดเป็นคำเพี้ยนไม่มีความหมาย เหมือนระบบฟังผิด "
        "เช่น 'ชื่อว่า ตม. ครับ' หรือ 'ส่งครับ ส่ง' แล้วตาต่อไปพูดให้ชัด",
        outcomes={OC.POLICY_CONFIRMED},
        garbled=True,
        checks=[only_disputed()],
    ),
    # --- PA: identity ---
    Scenario(
        "pa_wrong_person",
        "pa-email",
        "wrong person picks up",
        "คุณชื่อสมศักดิ์ ไม่รู้จักคนชื่อสมชาย บอกว่าโทรผิดแล้ว",
        outcomes={OC.WRONG_PERSON},
        checks=[no_policy_values],
    ),
    Scenario(
        "pa_relative",
        "pa-email",
        "a relative answers for the customer",
        "คุณเป็นลูกชายของสมชาย คุณสมชายไม่อยู่ ออกไปทำงาน ถ้าบอทถามเวลาให้บอกว่าพ่อกลับบ้านหกโมงเย็น",
        outcomes={OC.WRONG_PERSON, OC.CALLBACK_REQUESTED},
        checks=[no_policy_values],
    ),
    # --- PA: availability, refusal ---
    Scenario(
        "pa_busy",
        "pa-email",
        "busy now, gives a call-back time",
        "คุณชื่อสมชาย ตอนนี้ขับรถอยู่ ไม่สะดวกคุย ถ้าบอทถามเวลาให้ตอบว่า 'พรุ่งนี้บ่ายสองครับ'",
        outcomes={OC.CALLBACK_REQUESTED},
        checks=[callback_time_noted, no_policy_values],
    ),
    Scenario(
        "pa_busy_no_time",
        "pa-email",
        "busy, does not know when",
        "คุณชื่อสมชาย ไม่สะดวกคุยตอนนี้ ถ้าถามเวลาให้บอกว่า 'ยังไม่รู้ครับ ไว้ค่อยโทรมาใหม่'",
        outcomes={OC.CALLBACK_REQUESTED},
    ),
    Scenario(
        "pa_refuse",
        "pa-email",
        "not interested, will not talk",
        "คุณชื่อสมชาย ไม่สนใจ ไม่อยากคุย บอกตรงๆ ว่าไม่สะดวกคุยเรื่องนี้ ไม่ต้องการให้ทวน",
        outcomes={OC.REFUSED, OC.CALLBACK_REQUESTED},
        checks=[nothing_asked_after_stop],
    ),
    Scenario(
        "pa_dnc",
        "pa-email",
        "asks never to be called again",
        "คุณชื่อสมชาย รำคาญ บอกว่า 'อย่าโทรมาอีกนะครับ' ตั้งแต่ตาแรกหรือตาที่สอง",
        outcomes={OC.DO_NOT_CALL, OC.WRONG_PERSON},  # "ไม่ใช่สมชาย อย่าโทรมาอีก": a wrong number either way
        checks=[nothing_asked_after_stop],
    ),
    Scenario(
        "pa_angry_stop",
        "pa-email",
        "gets annoyed halfway and wants to hang up",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง หลังบอททวนข้อมูลไปหนึ่งกลุ่ม ให้เริ่มหงุดหงิด พูดว่า 'ยาวจัง ไม่อยากคุยแล้ว วางสายเถอะ'",
        outcomes={OC.REFUSED, OC.POLICY_PARTIAL},
        checks=[nothing_asked_after_stop],
    ),
    # --- PA: the recording ---
    Scenario(
        "pa_decline_recording",
        "pa-email",
        "declines the recording, call goes on",
        "คุณชื่อสมชาย ไม่ยินยอมให้บันทึกเสียง ถ้าถูกถามให้ตอบว่าไม่ยินยอม นอกนั้นคุยปกติ ข้อมูลถูกต้อง",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[consent_is(False)],
    ),
    Scenario(
        "pa_consent_why",
        "pa-email",
        "asks why it is recorded, then agrees",
        "คุณชื่อสมชาย เมื่อถูกขอบันทึกเสียง ให้ถามก่อนว่า 'บันทึกไปทำอะไรครับ' แล้วตาต่อไปตอบว่ายินยอม ข้อมูลถูกต้อง",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[consent_is(True)],
    ),
    Scenario(
        "pa_early_consent",
        "pa-email",
        "says 'record it, fine' before being asked",
        "คุณชื่อสมชาย ประโยคแรกให้พูดว่า 'ครับ ผมเอง บันทึกเสียงได้เลยนะครับ' จากนั้นคุยปกติ ข้อมูลถูกต้อง",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[consent_is(True), bot_says(r"บันทึกเสียง", "the recording notice")],
    ),
    Scenario(
        "pa_early_objection",
        "pa-email",
        "says 'don't record this' at the start",
        "คุณชื่อสมชาย ประโยคแรกให้พูดว่า 'ครับ ผมเอง แต่อย่าอัดเสียงนะครับ' จากนั้นคุยปกติ ข้อมูลถูกต้อง",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[consent_is(False)],
    ),
    # --- PA: disputes and doubt ---
    Scenario(
        "pa_dispute_daily",
        "pa-email",
        "the daily benefit should be 1,000",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง จำได้ว่าเงินชดเชยรายวันคือวันละ 1,000 บาท ไม่ใช่ 500 ให้แย้งเรื่องนี้ นอกนั้นถูกต้อง",
        outcomes={OC.CONFIRMED_WITH_DISCREPANCY},
        checks=[only_disputed("daily_hospital"), has_task("policy_discrepancy")],
    ),
    Scenario(
        "pa_dispute_beneficiary",
        "pa-email",
        "the beneficiary should be his wife",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ผู้รับผลประโยชน์ควรเป็นภรรยา ชื่อนางสมศรี ไม่ใช่ลูกสาว นอกนั้นถูกต้อง",
        outcomes={OC.CONFIRMED_WITH_DISCREPANCY},
        checks=[only_disputed("beneficiary")],
    ),
    Scenario(
        "pa_dispute_email",
        "pa-email",
        "the e-mail address is wrong",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง อีเมลที่ถูกคือ somchai.real@gmail.com ไม่ใช่อันที่บอทอ่าน นอกนั้นถูกต้อง",
        outcomes={OC.CONFIRMED_WITH_DISCREPANCY},
        checks=[only_disputed("delivery_target")],
    ),
    Scenario(
        "pa_unsure",
        "pa-email",
        "unsure about the premium (มั้ง)",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ตอนทวนเบี้ยประกันให้ตอบว่า 'น่าจะใช่มั้งครับ ไม่แน่ใจ' ถ้าบอททวนอีกครั้งให้ตอบว่า 'ใช่ครับ ถูกแล้ว'",
        outcomes={OC.POLICY_CONFIRMED, OC.CONFIRMED_WITH_DISCREPANCY},
    ),
    Scenario(
        "pa_question_not_dispute",
        "pa-email",
        "a question about an item is not a dispute",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อมูลถูกต้องทุกข้อ ตอนทวนความคุ้มครองให้ถามว่า 'ค่ารักษา 15,000 นับรวมกับชดเชยรายวันไหมครับ'",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[only_disputed()],
    ),
    # --- PA: questions ---
    Scenario(
        "pa_repeat",
        "pa-email",
        "asks to repeat a number and the e-mail",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อมูลถูกต้อง ขอให้ทวนค่ารักษาพยาบาลอีกครั้ง และขอให้ทวนอีเมลอีกครั้ง",
        outcomes={OC.POLICY_CONFIRMED},
    ),
    Scenario(
        "pa_unknown_question",
        "pa-email",
        "asks something the knowledge does not cover",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อมูลถูกต้อง ระหว่างคุยให้ถามว่า 'ถ้าจะเคลมต้องใช้เอกสารอะไรบ้างครับ'",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[follow_up_or_hotline],
    ),
    Scenario(
        "pa_motorcycle",
        "pa-email",
        "asks whether riding a motorcycle is covered",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อมูลถูกต้อง ระหว่างคุยให้ถามว่า 'ขี่มอเตอร์ไซค์คุ้มครองไหมครับ'",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[bot_says(r"90,000", "the motorcycle benefit")],
    ),
    Scenario(
        "pa_freelook_date",
        "pa-email",
        "asks the last day to cancel for a full refund",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อมูลถูกต้อง เมื่อบอทแจ้งสิทธิยกเลิก 30 วัน ให้ถามว่า "
        "'ถ้าได้รับกรมธรรม์วันที่ 1 พฤศจิกายน ยกเลิกได้ช้าสุดวันไหนครับ' แล้วถามต่อว่า 'ถ้ายกเลิกวันที่ 5 ธันวาคมได้เงินคืนไหมครับ'",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[bot_says(r"1 ธันวาคม", "the deadline 1 ธันวาคม"), no_task("question_follow_up")],
    ),
    Scenario(
        "pa_ai_question",
        "pa-email",
        "asks whether it is a real person",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อมูลถูกต้อง ตอนต้นสายให้ถามว่า 'นี่คนจริงหรือ AI ครับ'",
        outcomes={OC.POLICY_CONFIRMED},
        checks=[bot_says(r"AI", "that it is an AI")],
    ),
    Scenario(
        "pa_question_at_end",
        "pa-email",
        "has a question when asked for questions at the end",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อมูลถูกต้อง ตอนท้ายเมื่อบอทถามว่ามีคำถามไหม ให้ถามว่า 'จ่ายเบี้ยปีหน้ายังไงครับ' แล้วค่อยบอกว่าไม่มีแล้ว",
        outcomes={OC.POLICY_CONFIRMED},
    ),
    Scenario(
        "pa_cancel_now",
        "pa-email",
        "wants to cancel the policy during the call",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง หลังทวนความคุ้มครอง ให้บอกว่า 'ผมอยากยกเลิกกรมธรรม์นี้ครับ ทำยังไง'",
        outcomes={OC.POLICY_CONFIRMED, OC.POLICY_PARTIAL, OC.CONFIRMED_WITH_DISCREPANCY, OC.REFUSED},
    ),
    # --- PA: silence (scripted) ---
    Scenario(
        "pa_silent", "pa-email", "never says anything", script=[None, None, None, None, None], outcomes={OC.NO_RESPONSE}
    ),
    Scenario(
        "pa_silence_then_answer",
        "pa-email",
        "silent once, then talks",
        script=[
            None,
            "ครับ ผมเอง",
            "สะดวกครับ",
            "ยินยอมครับ",
            "ถูกต้องครับ",
            "ถูกครับ",
            "ใช่ครับ",
            "ถูกต้องครับ",
            "รับทราบครับ",
            "ไม่มีครับ",
            "ครับ",
            "ครับ",
        ],
        outcomes={OC.POLICY_CONFIRMED},
    ),
    # --- survey ---
    Scenario(
        "sv_happy",
        "survey-surveyor",
        "all five scores, surveyor came",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ตอบคะแนน 5, 4, 4, 5 และภาพรวม 9 ข้อเสนอแนะ: ไม่มี",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[scores_are(q1=5, q2=4, q3=4, q4=5, q5=9)],
    ),
    Scenario(
        "sv_no_surveyor",
        "survey-no-surveyor",
        "no surveyor: q3 and q4 never asked",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ตอบคะแนน 4, 4 และภาพรวม 9 ข้อเสนอแนะ: ไม่มี",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[bot_never(r"พนักงานสำรวจ", "the surveyor questions")],
    ),
    Scenario(
        "sv_unknown_surveyor",
        "survey-unknown",
        "unknown whether a surveyor came; he did not",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ศูนย์รับแจ้งให้ 4 กับ 4 ถ้าถามเรื่องพนักงานสำรวจภัย ให้บอกว่าไม่มีพนักงานมา ภาพรวม 8 ข้อเสนอแนะไม่มี",
        outcomes={OC.SURVEY_COMPLETED},
    ),
    Scenario(
        "sv_out_of_scale",
        "survey-no-surveyor",
        "gives 7 on a 1-5 question",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อแรกตอบว่า 7 พอบอทบอกช่วงคะแนนให้ตอบ 4 ข้อสอง 5 ภาพรวม 9 ข้อเสนอแนะไม่มี",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[scores_are(q1=4, q2=5, q5=9)],
    ),
    Scenario(
        "sv_change",
        "survey-no-surveyor",
        "changes the first score",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อแรกตอบ 3 แล้วตาต่อไปพูดว่า 'เปลี่ยนข้อแรกเป็น 4 ครับ' ก่อนตอบข้อสอง 5 ภาพรวม 9 ไม่มีข้อเสนอแนะ",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[scores_are(q1=4)],
    ),
    Scenario(
        "sv_words",
        "survey-no-surveyor",
        "scores in words: ห้า, เต็ม, แปด",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ตอบคะแนนเป็นคำ ข้อแรก 'ห้าครับ' ข้อสอง 'ให้เต็มเลย' ภาพรวม 'แปดครับ' ไม่มีข้อเสนอแนะ",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[scores_are(q1=5, q2=5, q5=8)],
    ),
    Scenario(
        "sv_how_to_score",
        "survey-no-surveyor",
        "asks how to score first",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อแรกถามก่อนว่า 'ต้องให้คะแนนยังไงครับ' แล้วตอบ 3 ข้อสอง 4 ภาพรวม 7 ไม่มีข้อเสนอแนะ",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[scores_are(q1=3, q2=4, q5=7)],
    ),
    Scenario(
        "sv_low_reason",
        "survey-surveyor",
        "low score, gives the reason when asked",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ศูนย์รับแจ้งให้ 5 กับ 4 พนักงานสำรวจภัยมาช้ามาก ให้ 1 ถ้าถามเหตุผลให้ตอบว่า 'รอเกือบสองชั่วโมง' "
        "ข้อสี่ 2 ภาพรวม 6 ข้อเสนอแนะ: อยากให้มาเร็วกว่านี้",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[scores_are(q3=1), lambda c: None if c.score("q3").feedback_raw else "no reason recorded for q3"],
    ),
    Scenario(
        "sv_two_at_once",
        "survey-no-surveyor",
        "answers two questions in one breath",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง เมื่อถูกถามข้อแรก ให้ตอบว่า 'ข้อนี้ 5 ข้อต่อไปก็ 5 ครับ' ภาพรวม 10 ไม่มีข้อเสนอแนะ",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[scores_were_said],
    ),
    Scenario(
        "sv_hedged",
        "survey-no-surveyor",
        "hedged score (น่าจะสี่มั้ง)",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ข้อแรกตอบว่า 'น่าจะสี่มั้งครับ' ถ้าถามย้ำให้ตอบว่า 'สี่ครับ' ข้อสอง 4 ภาพรวม 8 ไม่มีข้อเสนอแนะ",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[scores_are(q1=4)],
    ),
    Scenario(
        "sv_decline_recording",
        "survey-no-surveyor",
        "declines the recording, survey goes on",
        "คุณชื่อสมชาย ไม่ยินยอมให้บันทึกเสียง แต่ยอมตอบแบบสอบถาม ตอบ 4, 5 ภาพรวม 9 ไม่มีข้อเสนอแนะ",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[consent_is(False)],
    ),
    Scenario(
        "sv_busy",
        "survey-surveyor",
        "busy, call back this evening",
        "คุณชื่อสมชาย ไม่สะดวกตอนนี้ ติดประชุม ถ้าถามเวลาให้ตอบว่า 'ทุ่มนึงครับ'",
        outcomes={OC.CALLBACK_REQUESTED},
        checks=[callback_time_noted],
    ),
    Scenario(
        "sv_refuse",
        "survey-surveyor",
        "will not do the survey",
        "คุณชื่อสมชาย บอกว่าไม่อยากตอบแบบสอบถาม ไม่สะดวกทำ",
        outcomes={OC.REFUSED, OC.CALLBACK_REQUESTED, OC.DO_NOT_CALL},
        checks=[nothing_asked_after_stop],
    ),
    Scenario(
        "sv_angry",
        "survey-no-surveyor",
        "rude and abusive after the first score",
        "คุณชื่อสมชาย อารมณ์เสีย ยินยอมบันทึกเสียง ให้คะแนนข้อแรก 1 แล้วเริ่มพูดหยาบ เช่น 'ถามอะไรนักหนา ไม่อยากตอบแล้ว'",
        outcomes={OC.REFUSED, OC.SURVEY_PARTIAL},
        checks=[nothing_asked_after_stop],
    ),
    Scenario(
        "sv_complaint",
        "survey-surveyor",
        "complains the surveyor was rude",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ศูนย์รับแจ้ง 4 กับ 4 พนักงานสำรวจภัยพูดจาไม่สุภาพ ตะคอกใส่ ให้ 1 และ 1 พร้อมเล่าว่าโดนตะคอก "
        "อยากให้มีคนติดต่อกลับเรื่องนี้ ภาพรวม 3",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[
            lambda c: (
                None
                if {"complaint", "callback", "question_follow_up"} & set(c.task_types())
                else f"no follow-up task for the complaint ({c.task_types()})"
            )
        ],
    ),
    Scenario(
        "sv_already_answered",
        "survey-no-surveyor",
        "complains when a score is asked again",
        "คุณชื่อสมชาย ยินยอมบันทึกเสียง ตอบ 3, 3 ภาพรวม 7 ถ้าบอทถามคะแนนข้อที่ตอบไปแล้ว ให้บ่นว่า 'ตอบไปแล้วครับ' ไม่มีข้อเสนอแนะ",
        outcomes={OC.SURVEY_COMPLETED},
        checks=[scores_were_said],
    ),
]


# ---- running ----


async def play(scenario: Scenario) -> Call:
    profile = get_profile(scenario.profile)
    assert profile is not None, scenario.profile
    settings = get_settings()  # exactly production: no overrides (an override hid the 19 Oct bug)
    bot, customer = llm_client(settings), llm_client(settings)
    agent = CallAgent(build_engine(profile.campaign, profile.case, "สมชาย ใจดี"), bot)
    dialogue = AgentDialogue(agent)
    call = Call(scenario, agent)
    script = list(scenario.script) if scenario.script is not None else None
    try:
        await dialogue.prepare_opening()
        directive: Directive = dialogue.start()
        for _ in range(scenario.max_turns):
            agent.report_delivery(len(directive.segments), True)
            call.turns.append(("bot", directive.text))
            if directive.end_call or agent.state.finished:
                call.ended = True
                break
            dialogue.prepare_next()
            if script is not None:
                said = script.pop(0) if script else "ครับ"
            else:
                talk = "\n".join(f"{'บอท' if w == 'bot' else 'ลูกค้า'}: {t}" for w, t in call.turns)
                text, _ = await customer.chat_text(
                    [
                        {"role": "system", "content": CUSTOMER.format(persona=scenario.persona)},
                        {"role": "user", "content": f"บทสนทนา:\n{talk}\n\nลูกค้าพูดว่า:"},
                    ],
                    max_tokens=90,
                )
                said = (text.strip().splitlines() or ["ครับ"])[0].strip().strip('"')
            started = time.monotonic()
            if said is None:
                call.turns.append(("customer", "(เงียบ)"))
                directive = agent.handle_silence()
            else:
                call.turns.append(("customer", said))
                directive = await dialogue.reply(said)
                call.reply_seconds.append(time.monotonic() - started)
            call.events.extend(dialogue.events)
            dialogue.events.clear()
        else:
            call.ended = agent.state.finished
    finally:
        for client in (bot, customer):
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()
    return call


def verdict(call: Call) -> list[str]:
    s = call.scenario
    problems = []
    if s.outcomes and call.agent.outcome not in s.outcomes:
        problems.append(f"outcome {call.agent.outcome}, expected {sorted(o.value for o in s.outcomes)}")
    for check in s.checks:
        if (msg := check(call)) is not None:
            problems.append(msg)
    for name, check in GENERAL:
        if (msg := check(call)) is not None:
            problems.append(f"[{name}] {msg}")
    return problems


async def run(names: list[str], repeat: int, parallel: int) -> int:
    chosen = [s for s in SCENARIOS if not names or s.id in names]
    if names and len(chosen) != len(set(names)):
        unknown = set(names) - {s.id for s in chosen}
        sys.exit(f"unknown scenario(s): {', '.join(sorted(unknown))}")
    gate = asyncio.Semaphore(parallel)
    results: list[tuple[Scenario, int, Call | None, list[str]]] = []

    async def one(s: Scenario, n: int) -> None:
        async with gate:
            try:
                call = await play(s)
                problems = verdict(call)
            except Exception as exc:  # a crash is a failure to report, not a reason to stop the suite
                call, problems = None, [f"crashed: {type(exc).__name__}: {exc}"]
            results.append((s, n, call, problems))
            mark = "\033[32m✓\033[0m" if not problems else "\033[31m✗\033[0m"
            print(f"{mark} {s.id}{f' #{n + 1}' if repeat > 1 else ''}  {s.what}")
            for p in problems:
                print(f"     · {p}")

    await asyncio.gather(*(one(s, n) for s in chosen for n in range(repeat)))
    failed = [r for r in results if r[3]]
    out = Path(".local/roleplay") / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    for s, n, call, problems in sorted(results, key=lambda r: (r[0].id, r[1])):
        lines = [f"# {s.id} #{n + 1}: {s.what}", f"outcome: {call.agent.outcome if call else '-'}", ""]
        lines += [f"- PROBLEM: {p}" for p in problems] + [""]
        if call is not None:
            lines += [f"{'🤖' if w == 'bot' else '👤'} {t}" for w, t in call.turns]
            lines += ["", "events:"] + [f"- {k} {json.dumps(d, ensure_ascii=False)}" for k, d in call.events]
            lines += [
                "",
                "```json",
                json.dumps(call.agent.result.model_dump(mode="json"), ensure_ascii=False, indent=1),
                "```",
            ]
        (out / f"{s.id}-{n + 1}.md").write_text("\n".join(lines), encoding="utf-8")
    times = sorted(t for _, _, c, _ in results if c for t in c.reply_seconds)
    if times:
        median, p90 = times[len(times) // 2], times[int(len(times) * 0.9)]
        print(f"\nreply time: median {median:.2f}s · p90 {p90:.2f}s · max {times[-1]:.2f}s")
    print(f"{len(results) - len(failed)}/{len(results)} passed · transcripts in {out}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="kpi-roleplay", description=__doc__.split("\n\n")[0])
    parser.add_argument("scenarios", nargs="*", help="scenario ids (default: all)")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=5)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        for s in SCENARIOS:
            print(f"{s.id:26} {s.what}")
        return
    sys.exit(asyncio.run(run(args.scenarios, args.repeat, args.parallel)))
