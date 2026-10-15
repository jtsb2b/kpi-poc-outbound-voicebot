"""Deterministic conversation control shared by both campaigns.

The engine owns every decision: identity gate, availability, notice, callbacks, stop and
do-not-call handling, silence, interruptions, required fields and the final outcome.
An Interpreter turns a customer utterance into Signals (rule-based in the simulator; an
LLM with the same rule-based safety layer later). The engine emits Directives made of
segments; the transport reports how many segments were actually played, so interrupted
speech is never recorded as delivered.
"""

import copy
import re
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

from kpi_voicebot.campaigns import Campaign
from kpi_voicebot.models import (
    ConversationResult,
    Directive,
    FollowUpTask,
    Outcome,
    Segment,
)
from kpi_voicebot.thai_parse import Signals, contains_any, normalize, parse_day_month, read_signals


class InterpretContext(BaseModel):
    awaiting: str | None
    last_question: str | None
    recent_turns: list[tuple[str, str]]


class Interpreter(Protocol):
    def interpret(self, text: str, context: InterpretContext) -> Signals: ...


class RuleInterpreter:
    def interpret(self, text: str, context: InterpretContext) -> Signals:
        return read_signals(text)


class EngineState(BaseModel):
    stage: str = "greet"
    awaiting: str | None = None
    last_question: str | None = None
    last_directive: Directive | None = None
    last_delivery_complete: bool = True
    pending_remainder: list[Segment] = []
    delivered_facts: dict[str, str] = {}
    history: list[tuple[str, str]] = []
    clarify_count: int = 0
    silence_count: int = 0
    faq_count: int = 0
    turn: int = 0
    last_ack: str | None = None
    recent_acks: list[str] = []
    question_directive: Directive | None = None
    hedge_count: int = 0
    invite_count: int = 0
    reflected: list[str] = []  # survey questions whose feedback was already reflected back
    second_factor_attempts: int = 0
    body_started: bool = False
    finished: bool = False
    outcome: Outcome | None = None
    # campaign A
    review_index: int = 0
    # campaign B
    question_index: int = 0
    section: int = 0
    feedback_queue: list[str] = []


# Bot turns that answer a side request rather than ask the pending question themselves.
_NOT_RE_ASKABLE = frozenset(
    {"hold_ack", "hold_ack_again", "ai_identity", "invite_question", "invite_question_again", "clarify"}
)
_QUESTION_ENDINGS = ("ไหม", "มั้ย", "ใช่ไหม", "อะไร", "ยังไง", "อย่างไร", "เท่าไหร่", "เท่าไร", "ไหน", "เมื่อไหร่", "หรือเปล่า", "กี่")


# Measured 8 Oct 2026: the Gemini Live voice reads normalised Thai at ~11 characters per second with the
# brisk call-centre style, plus ~0.2 s between segments. Numbers count as their spoken words.
SPEECH_CHARS_PER_SECOND = 11.0
SEGMENT_GAP_SECONDS = 0.2


def estimated_seconds(segments: list[Segment]) -> float:
    from kpi_voicebot.tts_text import speakable

    spoken = sum(len(speakable(seg.text).replace(" ", "")) for seg in segments)
    return spoken / SPEECH_CHARS_PER_SECOND + SEGMENT_GAP_SECONDS * max(0, len(segments) - 1)


_GREETINGS = re.compile(r"^(สวัสดี|หวัดดี|ดี|ฮัลโหล|ฮัลโล|hello|hi)(ครับผม|ครับ|ค่ะ|คะ|จ้า|จ้ะ)?$")


def is_greeting(text: str) -> bool:
    return bool(_GREETINGS.match(normalize(text).replace(" ", "")))


def tidy_particles(segments: list[Segment]) -> list[Segment]:
    """Speak like a person: คะ (rising) rather than ค่ะ on a question, and no ค่ะ on a fact that
    runs straight into its own check question ("300,000 บาท ถูกต้องไหมคะ", not "บาทค่ะ ถูกต้องไหมคะ")."""
    texts = [seg.text.rstrip() for seg in segments]
    for i, text in enumerate(texts):
        for ending in _QUESTION_ENDINGS:
            if text.endswith(ending + "ค่ะ"):
                texts[i] = text = text[: -len("ค่ะ")] + "คะ"
    for i in range(len(texts) - 1):
        nxt = texts[i + 1]
        is_fact = bool(segments[i].facts)
        if is_fact and texts[i].endswith("ค่ะ") and nxt.endswith("คะ") and not nxt.endswith("นะคะ"):
            texts[i] = texts[i][: -len("ค่ะ")].rstrip()
    return [seg.model_copy(update={"text": t}) for seg, t in zip(segments, texts, strict=True)]


# Stages where the customer speaks freely; keyword overrides that could misfire on
# ordinary complaint text ("พนักงานไม่สนใจ", "ขับรถมา") are not applied there.
FREE_TEXT_STAGES = frozenset({"feedback", "final_comment", "review_detail"})
_STRONG_CALLBACK = ("ไม่สะดวก", "โทรมาใหม่", "ค่อยโทร", "โทรกลับ", "ไว้ก่อนนะ", "ขอวางก่อน")
_GENERIC_DENIAL = re.compile(
    r"(ไม่ใช่|ไม่ถูกต้อง|ไม่ถูก|ไม่ค่อยถูก|ไม่ตรง|ผิด|ครับผม|ครับ|ค่ะ|คะ|ค่า|นะ|เลย|อ่ะ|อะ|จ้ะ|จ้า|ข้อมูล|ส่วนนี้|\s|,)"
)


class BaseEngine:
    """Shared opening, gates and exits. Subclasses implement the campaign body."""

    def __init__(
        self,
        campaign: Campaign,
        variables: dict[str, str],
        interpreter: Interpreter | None = None,
        state: EngineState | None = None,
        result: ConversationResult | None = None,
        birth_day_month: tuple[int, int] | None = None,
    ) -> None:
        self.campaign = campaign
        self.vars = {"persona_name": campaign.persona_name, "service_phone": campaign.service_phone, **variables}
        self.interpreter = interpreter or RuleInterpreter()
        self.state = state or EngineState()
        self.result = result or self._initial_result()
        self.birth_day_month = birth_day_month

    # ---- public API ----

    def start(self) -> Directive:
        self.state.stage = "greet"
        return self._emit(self._directive("greet", self._seg("greet"), expects="identity"))

    def report_delivery(self, spoken_segments: int, complete: bool) -> None:
        directive = self.state.last_directive
        if directive is None:
            return
        spoken = directive.segments if complete else directive.segments[:spoken_segments]
        kind = "resumed_after_interruption" if directive.key.endswith(":resume") else "full"
        for segment in spoken:
            for fact in segment.facts:
                self.state.delivered_facts.setdefault(fact, kind)
        self.state.last_delivery_complete = complete
        self.state.pending_remainder = [] if complete else directive.segments[spoken_segments:]
        if complete and directive.expects and directive.expects != "continue":
            self.state.last_question = directive.segments[-1].text
        self._on_delivered(directive, spoken)

    def handle(self, text: str, signals: Signals | None = None) -> Directive:
        """Advance on a customer turn. `signals` comes from an async interpreter (the LLM) when present."""
        if self.state.finished:
            raise RuntimeError("conversation already finished")
        self.state.turn += 1
        self.state.silence_count = 0
        if signals is None:
            signals = self.interpreter.interpret(text, self.context())
        self.state.history = [*self.state.history, ("customer", text)][-12:]
        directive = self._overrides(signals) or self._resume_if_backchannel(signals) or self._stage(signals)
        return self._emit(directive)

    def handle_silence(self) -> Directive:
        if self.state.finished:
            raise RuntimeError("conversation already finished")
        self.state.turn += 1
        if self.state.awaiting == "continue":
            return self._emit(self._continue())
        if self.state.stage == "callback_time":
            return self._emit(self._close_callback(None))
        self.state.silence_count += 1
        if self.state.silence_count >= self.campaign.limits.max_silences:
            return self._emit(self._close(Outcome.NO_RESPONSE, "no_response_close", "silence"))
        segments = self._reprompt()
        if self.state.silence_count > 1:
            segments = [*self._seg("still_there"), *segments]
        return self._emit(self._directive("reprompt", segments, expects=self.state.awaiting))

    def peek(self, text: str, signals: Signals | None = None) -> Directive | None:
        """The turn this reply would lead to, without changing this call (for preparing it early)."""
        if self.state.finished:
            return None
        return self.fork().handle(text, signals)

    def fork(self) -> BaseEngine:
        """An independent copy of this call's state (campaign data is shared, read-only)."""
        clone = copy.copy(self)
        clone.state = self.state.model_copy(deep=True)
        clone.result = self.result.model_copy(deep=True)
        return clone

    def adopt(self, directive: Directive) -> None:
        """Replace the turn just emitted with the version actually spoken (same flow, new wording)."""
        if self.state.question_directive is self.state.last_directive or (
            directive.expects not in (None, "continue") and directive.key.split(":")[0] not in _NOT_RE_ASKABLE
        ):
            self.state.question_directive = directive
        self.state.last_directive = directive
        self.state.awaiting = directive.expects
        self.state.finished = directive.end_call
        if self.state.history and self.state.history[-1][0] == "bot":
            self.state.history = [*self.state.history[:-1], ("bot", directive.text)]

    def withdraw_follow_up(self, question: str) -> None:
        """The question was answered from the call's own facts after all: no call-back needed."""
        for i in range(len(self.result.tasks) - 1, -1, -1):
            task = self.result.tasks[i]
            if task.type == "question_follow_up" and task.detail_raw == question:
                del self.result.tasks[i]
                return

    def fact_sheet(self) -> list[str]:
        """What the bot may say when answering in its own words: approved facts for this call only."""
        lines = [
            f"- ชื่อลูกค้า: คุณ{self.vars.get('customer_name', '')}",
            f"- ศูนย์บริการลูกค้า: {self.vars['service_phone']} หรือเว็บไซต์ www.kpi.co.th",
        ]
        for entry in self.campaign.faq:
            if all(self.vars.get(r) for r in entry.requires):
                lines.append(f"- {entry.answer.format_map(self.vars)}")
        return lines + self._case_facts()

    def _case_facts(self) -> list[str]:
        return []

    def _case_answer(self, text: str) -> list[Segment] | None:
        """This call's own value the question asks about ("วันละเท่าไหร่นะ"), said again; None if none."""
        return None

    def handle_hangup(self) -> None:
        if self.state.finished:
            return
        self.state.finished = True
        self.result.end_reason = "customer_hung_up"
        self.state.outcome = self._partial_outcome() if self.state.body_started else Outcome.HUNG_UP_EARLY

    @property
    def outcome(self) -> Outcome | None:
        return self.state.outcome

    # ---- subclass hooks ----

    def _initial_result(self) -> ConversationResult:
        return ConversationResult()

    def _begin_body(self) -> Directive:
        raise NotImplementedError

    def _body(self, signals: Signals) -> Directive:
        raise NotImplementedError

    def _continue(self) -> Directive:
        raise NotImplementedError

    def _reprompt_body(self) -> list[Segment]:
        raise NotImplementedError

    def _partial_outcome(self) -> Outcome:
        raise NotImplementedError

    def _on_delivered(self, directive: Directive, spoken: list[Segment]) -> None:
        return None

    def _answer_question(self, text: str, *, off_topic: bool = False, follow_up: bool = True) -> list[Segment]:
        """Approved FAQ answer; otherwise an honest limitation plus a recorded follow-up. Off-topic
        questions ("1+1 เท่าไหร่") get a polite no and no follow-up. Without `follow_up`, an
        unanswerable question gets nothing, so the caller simply carries on."""
        t = normalize(text)
        best, hits = None, 0
        for entry in self.campaign.faq:
            if any(not self.vars.get(r) for r in entry.requires):
                continue
            n = sum(1 for k in entry.keywords if k.lower() in t)
            if n > hits:
                best, hits = entry, n
        if best is not None:
            return [Segment(text=best.answer.format_map(self.vars))]
        case = self._case_answer(text)
        if case:
            return case
        if off_topic:
            return self._seg("off_topic")
        if not follow_up:
            return []
        self._task("question_follow_up", "คำถามที่ยังไม่มีคำตอบที่อนุมัติ", text)
        return self._seg("unknown_answer")

    # ---- helpers ----

    def context(self) -> InterpretContext:
        return InterpretContext(
            awaiting=self.state.awaiting,
            last_question=self.state.last_question,
            recent_turns=self.state.history[-6:],
        )

    def _seg(self, key: str, **extra: object) -> list[Segment]:
        values = {**self.vars, **{k: str(v) for k, v in extra.items()}}
        wording = self.campaign.text(key)
        return [
            Segment(text=spec.text.format_map(values), facts=spec.facts, verbatim=wording.verbatim)
            for spec in wording.segments
            if all(values.get(r) for r in spec.requires)
        ]

    def _ack(self, pool: list[str] | None = None) -> Segment:
        """A short acknowledgement that does not repeat either of the last two used."""
        choices = pool or self.campaign.acknowledgements
        options = [a for a in choices if a not in self.state.recent_acks[-2:]] or choices
        ack = options[self.state.turn % len(options)]
        self.state.last_ack = ack
        self.state.recent_acks = [*self.state.recent_acks, ack][-4:]
        return Segment(text=ack)

    def _directive(
        self, key: str, segments: list[Segment], *, expects: str | None = None, end_call: bool = False
    ) -> Directive:
        return Directive(key=key, segments=segments, expects=expects, end_call=end_call)

    def _emit(self, directive: Directive) -> Directive:
        directive = directive.model_copy(update={"segments": tidy_particles(directive.segments)})
        if directive.expects not in (None, "continue") and directive.key.split(":")[0] not in _NOT_RE_ASKABLE:
            self.state.question_directive = directive
        self.state.last_directive = directive
        self.state.awaiting = directive.expects
        self.state.last_delivery_complete = True
        self.state.pending_remainder = []
        self.state.history = [*self.state.history, ("bot", directive.text)][-12:]
        if directive.end_call:
            self.state.finished = True
        return directive

    def _task(self, type_: str, reason: str, detail: str | None = None, field: str | None = None) -> None:
        self.result.tasks.append(
            FollowUpTask.model_validate({"type": type_, "reason": reason, "detail_raw": detail, "field": field})
        )

    def _close(self, outcome: Outcome, key: str, reason: str, **extra: object) -> Directive:
        self.state.outcome = outcome
        self.result.end_reason = reason
        return self._directive(key, self._seg(key, **extra), end_call=True)

    def _close_callback(self, time_text: str | None) -> Directive:
        self.result.callback.requested = True
        self.result.callback.preferred_time_text = time_text
        self._task("callback", "ลูกค้าขอให้ติดต่อกลับ", time_text)
        if time_text:
            return self._close(Outcome.CALLBACK_REQUESTED, "callback_close", "callback", callback_time=time_text)
        return self._close(Outcome.CALLBACK_REQUESTED, "callback_close_no_time", "callback")

    def _reprompt(self) -> list[Segment]:
        match self.state.stage:
            case "greet":
                return self._seg("identity_recheck")
            case "second_factor":
                return self._seg("second_factor_ask")
            case "availability":
                return self._seg("availability_short")
            case "callback_time":
                return self._seg("ask_callback_time")
            case _:
                return self._reprompt_body()

    def _clarify_or(self, give_up: Callable[[], Directive]) -> Directive:
        """A short reprompt, or the give-up directive once the clarification budget is spent."""
        self.state.clarify_count += 1
        if self.state.clarify_count > self.campaign.limits.max_clarifications:
            self.state.clarify_count = 0
            return give_up()
        return self._directive("clarify", self._reprompt(), expects=self.state.awaiting)

    def _stop_outcome(self) -> Outcome:
        return self._partial_outcome() if self.state.body_started else Outcome.REFUSED

    # ---- shared flow ----

    def _overrides(self, s: Signals) -> Directive | None:
        free_text = self.state.stage in FREE_TEXT_STAGES
        if s.dnc:
            self.state.outcome = Outcome.DO_NOT_CALL
            self.result.end_reason = "do_not_call"
            return self._directive("dnc_close", self._seg("dnc_close"), end_call=True)
        if s.objection:
            return self._close(Outcome.NOTICE_OBJECTION, "objection_close", "notice_objection")
        if not free_text and s.wrong_person and self.state.stage in {"greet", "second_factor", "availability"}:
            self.result.identity_result = "wrong_person"
            return self._close(Outcome.WRONG_PERSON, "wrong_person_close", "wrong_person")
        if not free_text and s.refuse:
            self.state.outcome = self._stop_outcome()
            self.result.end_reason = "customer_stopped"
            return self._directive("refuse_close", self._seg("refuse_close"), end_call=True)
        callback = s.not_convenient and (not free_text or contains_any(normalize(s.text), _STRONG_CALLBACK))
        if callback and self.state.stage not in {"greet", "callback_time"}:
            if s.callback_time:
                return self._close_callback(s.callback_time)
            self.state.stage = "callback_time"
            return self._directive("ask_callback_time", self._seg("ask_callback_time"), expects="callback_time")
        if s.hold and not free_text:
            last_key = self.state.last_directive.key if self.state.last_directive else ""
            key = "hold_ack_again" if last_key.startswith("hold_ack") else "hold_ack"
            return self._directive(key, self._seg(key), expects=self.state.awaiting)
        if s.repeat and self.state.last_directive is not None:
            return self._repeat()
        if s.has_question and not free_text and self.state.stage != "callback_time":
            self.state.invite_count += 1
            key = "invite_question" if self.state.invite_count == 1 else "invite_question_again"
            return self._directive(key, self._seg(key), expects=self.state.awaiting)
        if s.ai_identity and not free_text:
            return self._directive(
                "ai_identity", [*self._seg("ai_identity"), *self._reprompt()], expects=self.state.awaiting
            )
        return None

    def _repeat(self) -> Directive:
        """Repeat like a person: only the key values of what is being asked, not the whole turn."""
        short = self._repeat_short()
        if short:
            return Directive(
                key=f"{self.state.question_directive.key if self.state.question_directive else 'repeat'}:repeat",
                segments=[*self._seg("repeat_prefix"), *short],
                expects=self.state.awaiting,
            )
        last = self.state.question_directive or self.state.last_directive
        assert last is not None
        return Directive(key=f"{last.key}:repeat", segments=last.segments, expects=last.expects)

    def _repeat_short(self) -> list[Segment] | None:
        return None

    def _notice_followup(self) -> list[Segment]:
        """A short lead-in into the body, said with the notice so the first body turn stays short."""
        return []

    def _resume_if_backchannel(self, s: Signals) -> Directive | None:
        """After an interruption, a bare 'ค่ะ/อืม' means 'go on', not an answer to unheard speech."""
        remainder = self.state.pending_remainder
        last = self.state.last_directive
        if not remainder or last is None or not (s.backchannel or (s.affirm and len(s.text) <= 12)):
            return None
        if all(not seg.facts for seg in remainder) and self.state.awaiting not in {None, "continue"}:
            # Every fact was heard; only the question itself was cut off. Treat as an answer.
            return None
        key = last.key if last.key.endswith(":resume") else f"{last.key}:resume"
        return Directive(key=key, segments=[*self._seg("resume_prefix"), *remainder], expects=last.expects)

    def _stage(self, s: Signals) -> Directive:
        if self.state.awaiting == "continue":
            if s.question and not s.affirm:
                # Mid-explanation ("รายละเอียดอะไรครับ"): what comes next usually answers it, so an
                # unknown question is not parked for a call-back; the bot just carries on.
                answer = self._answer_question(s.text, off_topic=s.off_topic, follow_up=False)
                nxt = self._continue()
                return Directive(
                    key=nxt.key, segments=[*answer, *nxt.segments], expects=nxt.expects, end_call=nxt.end_call
                )
            return self._continue()
        match self.state.stage:
            case "greet":
                return self._identity(s)
            case "second_factor":
                return self._second_factor(s)
            case "availability":
                return self._availability(s)
            case "callback_time":
                if s.callback_time:
                    return self._close_callback(s.callback_time)
                if s.negative or s.no_comment:
                    return self._close_callback(None)
                return self._clarify_or(lambda: self._close_callback(None))
            case _:
                return self._body(s)

    def _identity(self, s: Signals) -> Directive:
        if is_greeting(s.text) and not read_signals(s.text).affirm:
            # "ดีครับ" / "สวัสดีครับ" answers the hello, not "is this Khun Somchai?": ask, like an operator would.
            return self._clarify_or(
                lambda: self._close(Outcome.VERIFICATION_FAILED, "wrong_person_close", "identity_unclear")
            )
        if s.affirm:
            self.result.identity_result = "confirmed"
            self.state.clarify_count = 0
            if self.campaign.identity.second_factor and self.birth_day_month:
                self.state.stage = "second_factor"
                return self._directive("second_factor_ask", self._seg("second_factor_ask"), expects="second_factor")
            return self._intro()
        if s.negative:
            self.result.identity_result = "wrong_person"
            return self._close(Outcome.WRONG_PERSON, "wrong_person_close", "wrong_person")
        self.result.identity_result = "unclear"
        return self._clarify_or(
            lambda: self._close(Outcome.VERIFICATION_FAILED, "wrong_person_close", "identity_unclear")
        )

    def _second_factor(self, s: Signals) -> Directive:
        parsed = parse_day_month(s.text)
        if parsed is not None and parsed == self.birth_day_month:
            return self._intro()
        self.state.second_factor_attempts += 1
        if self.state.second_factor_attempts >= 2:
            self.result.identity_result = "failed"
            return self._close(Outcome.VERIFICATION_FAILED, "verification_failed_close", "verification_failed")
        return self._directive("second_factor_retry", self._seg("second_factor_retry"), expects="second_factor")

    def _intro(self) -> Directive:
        self.state.stage = "availability"
        self.state.clarify_count = 0
        return self._directive("intro", self._seg("intro"), expects="availability")

    def _availability(self, s: Signals) -> Directive:
        if s.affirm:
            self.state.clarify_count = 0
            self.state.stage = "notice"
            self.result.notice_delivered = True
            return self._directive("notice", [*self._seg("notice"), *self._notice_followup()], expects="continue")
        if s.negative:
            self.state.stage = "callback_time"
            return self._directive("ask_callback_time", self._seg("ask_callback_time"), expects="callback_time")
        if s.question:
            answer = self._answer_question(s.text, off_topic=s.off_topic)
            return self._directive(
                "availability_answer", [*answer, *self._seg("availability_short")], expects="availability"
            )
        return self._clarify_or(lambda: self._close(Outcome.NO_RESPONSE, "no_response_close", "availability_unclear"))

    @staticmethod
    def denial_detail(text: str) -> str:
        """What remains of a denial once generic words are removed ('' for a bare 'ไม่ถูกค่ะ')."""
        return _GENERIC_DENIAL.sub("", normalize(text))
