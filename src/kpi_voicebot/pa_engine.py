"""Campaign A: review of a (mock) PA policy purchase, unit by unit."""

from kpi_voicebot.campaigns import Campaign
from kpi_voicebot.engine import BaseEngine, EngineState, Interpreter
from kpi_voicebot.models import (
    ConversationResult,
    Directive,
    Outcome,
    PACase,
    PolicyFieldResult,
    Segment,
)
from kpi_voicebot.thai_parse import Signals, normalize, read_signals, strip_particles
from kpi_voicebot.thai_text import format_amount, thai_date

# "How much / what was that?" about the item just read, without naming it.
_ASKS_AGAIN = ("เท่าไหร่", "เท่าไร", "กี่บาท", "กี่วัน", "อะไรนะ", "ว่าไงนะ", "ยังไงนะ", "ไหนนะ", "ว่าอะไร", "ใครนะ")
_ASKING = (*_ASKS_AGAIN, "ใคร", "อะไร", "ยังไง", "เมื่อไหร่", "ที่ไหน")


def _is_backchannel_only(s: Signals) -> bool:
    return s.backchannel or len(strip_particles(normalize(s.text))) <= 3


def pa_variables(case: PACase, customer_name: str) -> dict[str, str]:
    def amount(v: float | None) -> str:
        return format_amount(v) if v is not None else ""

    return {
        "customer_name": customer_name,
        "plan_name": case.plan_name,
        "death_benefit": amount(case.death_benefit_thb),
        "medical": amount(case.medical_per_accident_thb),
        "daily": amount(case.daily_hospital_thb),
        "daily_max_days": str(case.daily_hospital_max_days or ""),
        "motorcycle_benefit": amount(case.motorcycle_benefit_thb),
        "public_transport_benefit": amount(case.public_transport_benefit_thb),
        "premium": amount(case.premium_thb),
        "billing_period": case.billing_period,
        "effective_date": thai_date(case.effective_date),
        "effective_time": case.effective_time,
        "beneficiary": case.beneficiary,
        "payment_channel": case.payment_channel,
        "payment_status": case.payment_status,
        "delivery_channel": case.delivery_channel,
        "delivery_target": case.delivery_target,
        "delivery_target_label": "อีเมล" if case.delivery_channel == "อีเมล" else "ที่อยู่จัดส่ง",
        "delivery_period": case.delivery_period_text,
    }


class PAEngine(BaseEngine):
    def __init__(
        self,
        campaign: Campaign,
        case: PACase,
        customer_name: str,
        interpreter: Interpreter | None = None,
        state: EngineState | None = None,
        result: ConversationResult | None = None,
    ) -> None:
        birth = (case.verify_birth_date.day, case.verify_birth_date.month) if case.verify_birth_date else None
        super().__init__(campaign, pa_variables(case, customer_name), interpreter, state, result, birth)
        self.units = [u for u in campaign.review_units if self._unit_segments_for(u.id)]

    def _initial_result(self) -> ConversationResult:
        fields = []
        for spec in self.campaign.policy_fields:
            if any(not self.vars.get(r) for r in spec.requires):
                continue
            fields.append(
                PolicyFieldResult(field=spec.field, label=spec.label, expected_value=spec.value.format_map(self.vars))
            )
        return ConversationResult(policy_fields=fields)

    # ---- units ----

    def _unit_segments_for(self, unit_id: str) -> list[Segment]:
        unit = next(u for u in self.campaign.review_units if u.id == unit_id)
        return [
            Segment(text=spec.text.format_map(self.vars), facts=spec.facts)
            for spec in unit.segments
            if all(self.vars.get(r) for r in spec.requires)
        ]

    def _unit_directive(self, index: int, prefix: list[Segment]) -> Directive:
        unit = self.units[index]
        self.state.review_index = index
        self.state.clarify_count = 0
        self.state.stage = "review"
        segments = [*prefix, *self._unit_segments_for(unit.id), *self._confirm(unit.confirm)]
        return self._directive(f"review:{unit.id}", segments, expects=f"confirm:{unit.id}")

    @staticmethod
    def _confirm(question: str) -> list[Segment]:
        return [Segment(text=question)] if question else []

    def _unit_fields(self) -> list[str]:
        unit_id = self.units[self.state.review_index].id
        known = {f.field for f in self.result.policy_fields}
        return [f for seg in self._unit_segments_for(unit_id) for f in seg.facts if f in known]

    def _field(self, name: str) -> PolicyFieldResult:
        return next(f for f in self.result.policy_fields if f.field == name)

    def _on_delivered(self, directive: Directive, spoken: list[Segment]) -> None:
        for segment in spoken:
            for fact in segment.facts:
                if any(f.field == fact for f in self.result.policy_fields):
                    self._field(fact).delivery = self.state.delivered_facts[fact]  # type: ignore[assignment]
                if fact == "free_look":
                    self.result.free_look_delivery = self.state.delivered_facts[fact]  # type: ignore[assignment]

    def _mark_unit(self, status: str, statement: str | None = None, fields: list[str] | None = None) -> None:
        names = fields if fields is not None else self._unit_fields()
        if status == "confirmed":
            # A field can only be confirmed once the customer has actually heard it.
            names = [n for n in names if n in self.state.delivered_facts]
        for name in names:
            f = self._field(name)
            f.status = status  # type: ignore[assignment]
            if statement:
                f.customer_statement = statement

    def _next_unit(self, prefix: list[Segment]) -> Directive:
        remainder = [s for s in self.state.pending_remainder if s.facts]
        if remainder:
            # The customer reacted before hearing everything in this unit: finish it first.
            unit = self.units[self.state.review_index]
            return Directive(
                key=f"review:{unit.id}:resume",
                segments=[*prefix, *remainder, *self._confirm(unit.confirm)],
                expects=f"confirm:{unit.id}",
            )
        nxt = self.state.review_index + 1
        if nxt < len(self.units):
            return self._unit_directive(nxt, prefix)
        if len(prefix) > 1 or (prefix and prefix[0].text not in self.campaign.acknowledgements):
            # Let the customer react to the discrepancy note before the free-look notice starts.
            self.state.stage = "before_free_look"
            return self._directive("discrepancy_ack", prefix, expects="continue")
        # "ขออนุญาตแจ้งข้อมูลสำคัญเพิ่มเติม" already acknowledges; a "ค่ะ" before it only lengthens the turn.
        return self._free_look([])

    def _free_look(self, prefix: list[Segment]) -> Directive:
        self.state.stage = "free_look"
        return self._directive("free_look", [*prefix, *self._seg("free_look")], expects="continue")

    # ---- body ----

    def _case_facts(self) -> list[str]:
        return [f"- {f.label}: {f.expected_value}" for f in self.result.policy_fields]

    def _notice_followup(self) -> list[Segment]:
        return self._seg("review_intro")

    def _begin_body(self) -> Directive:
        self.state.body_started = True
        return self._unit_directive(0, [])

    def _continue(self) -> Directive:
        if self.state.stage == "notice":
            return self._begin_body()
        if self.state.stage == "before_free_look":
            return self._free_look([])
        if self.state.stage == "free_look":
            if self.state.pending_remainder:
                return Directive(
                    key="free_look:resume",
                    segments=[*self._seg("resume_prefix"), *self.state.pending_remainder],
                    expects="continue",
                )
            self.state.stage = "questions"
            return self._directive("questions", self._seg("questions"), expects="questions")
        raise RuntimeError(f"no continuation from stage {self.state.stage}")

    def _reprompt_body(self) -> list[Segment]:
        if self.state.stage == "review":
            unit = self.units[self.state.review_index]
            return self._seg("confirm_clarify", unit_short=unit.short)
        if self.state.stage == "review_detail":
            return self._seg("discrepancy_ask")
        if self.state.stage == "questions":
            return self._seg("more_questions") if self.state.faq_count else self._seg("questions")
        return self._seg("still_there")

    def _partial_outcome(self) -> Outcome:
        return Outcome.POLICY_PARTIAL

    def _body(self, s: Signals) -> Directive:
        match self.state.stage:
            case "review":
                return self._review(s)
            case "review_detail":
                return self._discrepancy(s.text)
            case "questions":
                return self._questions(s)
        raise RuntimeError(f"unexpected stage {self.state.stage}")

    def _repeat_short(self, question: list[Segment] | None = None) -> list[Segment] | None:
        if self.state.stage != "review":
            return None
        unit = self.units[self.state.review_index]
        values = [
            Segment(text=spec.text.format_map(self.vars))
            for spec in unit.repeat
            if all(self.vars.get(r) for r in spec.requires)
        ]
        if not values:
            return None
        tail = question if question is not None else self._confirm(unit.confirm) or self._seg("repeat_tag")
        return [*values, *tail]

    def _review(self, s: Signals) -> Directive:
        if s.hedged and not s.negative:
            return self._hedged_confirmation(s)
        if s.negative:
            if self.denial_detail(s.text):
                return self._discrepancy(s.text)
            self.state.stage = "review_detail"
            return self._directive("discrepancy_ask", self._seg("discrepancy_ask"), expects="discrepancy_detail")
        if s.affirm or s.backchannel:
            # After a fact said as a statement, "ครับ / อืม / อ่าฮะ" is the customer accepting it.
            self._mark_unit("confirmed")
            self.state.hedge_count = 0
            # An operator goes straight on after a bare "ครับ"; a fuller answer gets a "ค่ะ" first.
            return self._next_unit([] if _is_backchannel_only(s) else [self._ack(["ค่ะ"])])
        asks_item = bool(self._fields_asked(s.text)) and any(w in normalize(s.text) for w in _ASKING)
        if s.question or asks_item:
            unit = self.units[self.state.review_index]
            if self._asks_about_current(s.text):
                # "วันละเท่าไหร่นะครับ" right after the daily benefit: say it again, then carry on.
                again = self._repeat_short()
                if again:
                    return self._directive(f"repeat:{unit.id}", again, expects=f"confirm:{unit.id}")
            answer = self._answer_question(s.text, off_topic=s.off_topic)
            return self._directive(
                "review_answer",
                [*answer, *self._seg("confirm_clarify", unit_short=unit.short)],
                expects=f"confirm:{unit.id}",
            )

        def give_up() -> Directive:
            self._mark_unit("unclear", s.text)
            self._task("unclear_answer", "ยืนยันข้อมูลไม่ได้ชัดเจน", s.text, self.units[self.state.review_index].id)
            return self._next_unit([self._ack(["ค่ะ"])])

        return self._clarify_or(give_up)

    def _fields_asked(self, text: str) -> list[str]:
        t = normalize(text)
        known = {f.field for f in self.result.policy_fields}
        return [f.field for f in self.campaign.policy_fields if f.field in known and any(k in t for k in f.keywords)]

    def _asks_about_current(self, text: str) -> bool:
        """A question about the item just read: it names one of its fields, or asks "how much /
        what was that" without naming any other."""
        asked = self._fields_asked(text)
        if asked:
            return any(f in self._unit_fields() for f in asked)
        return any(w in normalize(text) for w in _ASKS_AGAIN)

    def _case_answer(self, text: str) -> list[Segment] | None:
        for unit in self.units:
            fields = {f for seg in unit.segments for f in seg.facts}
            if fields & set(self._fields_asked(text)):
                values = [
                    spec.text.format_map(self.vars)
                    for spec in unit.repeat
                    if all(self.vars.get(r) for r in spec.requires)
                ]
                if values:
                    return [Segment(text=f"{' '.join(values)}ค่ะ")]
        return None

    def _hedged_confirmation(self, s: Signals) -> Directive:
        """'มั้งครับ' / 'น่าจะใช่': check once more with just the values; if still unsure, note it and move on."""
        unit = self.units[self.state.review_index]
        if self.state.hedge_count == 0:
            self.state.hedge_count = 1
            short = self._repeat_short(self._seg("hedge_check")) or self._seg("confirm_clarify", unit_short=unit.short)
            return self._directive(
                f"hedge_recheck:{unit.id}", [*self._seg("hedge_recheck"), *short], expects=f"confirm:{unit.id}"
            )
        self.state.hedge_count = 0
        self._mark_unit("unclear", s.text)
        self._task("unclear_answer", f"ลูกค้าไม่แน่ใจข้อมูล{unit.short}", s.text, unit.id)
        return self._next_unit(self._seg("hedge_unresolved"))

    def _discrepancy(self, text: str) -> Directive:
        if self.state.stage == "review_detail" and read_signals(text).affirm:
            self._mark_unit("confirmed")
            self.state.stage = "review"
            return self._next_unit([self._ack(["ค่ะ"])])
        unit_fields = self._unit_fields()
        t = normalize(text)
        specs = {s.field: s for s in self.campaign.policy_fields}
        matched = [f for f in unit_fields if any(k in t for k in specs[f].keywords)]
        fields = matched or unit_fields
        if matched:
            # Naming one wrong item implies the rest of what they heard in this unit is right.
            self._mark_unit("confirmed", fields=[f for f in unit_fields if f not in matched])
        self._mark_unit("disputed", text.strip(), fields)
        for name in fields:
            self._task("policy_discrepancy", f"ลูกค้าแจ้งว่า{specs[name].label}ไม่ตรง", text.strip(), name)
        self.state.stage = "review"
        return self._next_unit(self._seg("discrepancy_ack"))

    def _questions(self, s: Signals) -> Directive:
        remainder = [seg for seg in self.state.pending_remainder if seg.facts]
        if (s.no_comment or (s.negative and not s.question)) and not remainder:
            return self._finish()
        if s.affirm and not s.question and len(s.text) <= 12:
            return self._directive("invite_question", self._seg("invite_question"), expects="questions")
        if not s.question and not s.text.strip():
            return self._directive("clarify", self._seg("more_questions"), expects="questions")
        self.state.faq_count += 1
        answer = self._answer_question(s.text, off_topic=s.off_topic)
        if self.state.faq_count >= self.campaign.limits.max_faq_questions:
            directive = self._finish()
            return Directive(key=directive.key, segments=[*answer, *directive.segments], end_call=True)
        return self._directive("faq_answer", [*answer, *self._seg("more_questions")], expects="questions")

    def _finish(self) -> Directive:
        disputed = any(f.status == "disputed" for f in self.result.policy_fields)
        outcome = Outcome.CONFIRMED_WITH_DISCREPANCY if disputed else Outcome.POLICY_CONFIRMED
        return self._close(outcome, "closing", "completed")
