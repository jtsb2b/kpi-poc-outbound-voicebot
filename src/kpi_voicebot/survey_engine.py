"""Campaign B: accident-service satisfaction survey, one question at a time."""

import re

from kpi_voicebot.campaigns import Campaign, QuestionSpec
from kpi_voicebot.engine import BaseEngine, EngineState, Interpreter
from kpi_voicebot.models import ConversationResult, Directive, Outcome, Segment, SurveyAnswer, SurveyCase
from kpi_voicebot.thai_parse import Signals, escalation_tags, normalize, strip_particles
from kpi_voicebot.thai_text import thai_date

_SCORE_FILLER = re.compile(
    r"(\d+|ศูนย์|หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ|คะแนน|ให้|เต็ม|มั้ง|ประมาณ|น่าจะ|คิดว่า|เอ่อ|อืม|"
    r"ครับผม|ครับ|ค่ะ|คะ|ค่า|นะ|ละกัน|แล้วกัน|ดีกว่า|ข้อนี้|ก็|เลย|ทั้งสองข้อ|ทั้งคู่|ทุกข้อ|เอาเป็น|ขอเป็น|เปลี่ยนเป็น|"
    r"เป็น|ขอแก้|เปลี่ยน|ข้อแรก|ข้อ|\s|,|\.)"
)
_ORDINALS = {"แรก": 1, "หนึ่ง": 1, "สอง": 2, "สาม": 3, "สี่": 4, "ห้า": 5}


def survey_variables(case: SurveyCase, customer_name: str) -> dict[str, str]:
    return {"customer_name": customer_name, "accident_date": thai_date(case.accident_date), "case_id": case.case_id}


class SurveyEngine(BaseEngine):
    def __init__(
        self,
        campaign: Campaign,
        case: SurveyCase,
        customer_name: str,
        interpreter: Interpreter | None = None,
        state: EngineState | None = None,
        result: ConversationResult | None = None,
    ) -> None:
        birth = (case.verify_birth_date.day, case.verify_birth_date.month) if case.verify_birth_date else None
        self.case = case
        super().__init__(campaign, survey_variables(case, customer_name), interpreter, state, result, birth)

    def _initial_result(self) -> ConversationResult:
        return ConversationResult(
            survey_answers=[
                SurveyAnswer(question=q.id, label=q.label, scale_min=q.scale[0], scale_max=q.scale[1])
                for q in self.campaign.questions
            ]
        )

    # ---- lookup ----

    @property
    def questions(self) -> list[QuestionSpec]:
        return self.campaign.questions

    def _answer(self, qid: str) -> SurveyAnswer:
        return next(a for a in self.result.survey_answers if a.question == qid)

    def _spec(self, qid: str) -> QuestionSpec:
        return next(q for q in self.questions if q.id == qid)

    @property
    def _current(self) -> QuestionSpec:
        return self.questions[self.state.question_index]

    # ---- question flow ----

    def _ask(self, index: int, prefix: list[Segment]) -> Directive:
        """Ask question `index`, adding section framing and skipping questions already settled."""
        while index < len(self.questions) and self._answer(self.questions[index].id).status in {
            "answered",
            "not_applicable",
            "skipped",
        }:
            index += 1
        if index >= len(self.questions):
            return self._final_comment(prefix)
        q = self.questions[index]
        self.state.question_index = index
        self.state.clarify_count = 0
        segments = list(prefix)
        if q.section == 2 and self.state.section != 2:
            if self.case.surveyor_attended is False:
                self._mark_not_applicable("ข้อมูลเคส: ไม่มีพนักงานสำรวจภัย")
                return self._ask(index, prefix)
            if self.case.surveyor_attended is None and self.state.stage != "surveyor_check_done":
                self.state.stage = "surveyor_check"
                return self._directive(
                    "surveyor_check", [*segments, *self._seg("surveyor_check")], expects="surveyor_check"
                )
            segments += self._seg("section2")
        elif q.section == 3 and self.state.section != 3:
            segments += self._seg("section3")
        self.state.section = q.section
        self.state.stage = "question"
        answer = self._answer(q.id)
        if answer.status == "not_asked":
            answer.status = "unanswered"
        segments.append(Segment(text=q.ask))
        return self._directive(f"ask:{q.id}", segments, expects=f"score:{q.id}")

    def _mark_not_applicable(self, reason: str) -> None:
        for q in self.questions:
            if q.allow_na:
                a = self._answer(q.id)
                a.status, a.value, a.raw_utterance = "not_applicable", None, a.raw_utterance or reason

    def _after_answer(self, prefix: list[Segment]) -> Directive:
        if self.state.feedback_queue:
            qid = self.state.feedback_queue.pop(0)
            self._answer(qid).feedback_asked = True
            self.state.stage = "feedback"
            self.state.awaiting = f"feedback:{qid}"
            return self._directive(
                f"feedback:{qid}", [*prefix, Segment(text=self._spec(qid).feedback)], expects=f"feedback:{qid}"
            )
        return self._ask(self.state.question_index + 1, prefix)

    def _final_comment(self, prefix: list[Segment]) -> Directive:
        self.state.stage = "final_comment"
        return self._directive("final_comment", [*prefix, *self._seg("final_comment")], expects="final_comment")

    def _needs_feedback(self, q: QuestionSpec, value: int) -> bool:
        low, high = q.feedback_range
        return low <= value <= high

    def _record(self, q: QuestionSpec, value: int, raw: str, note: str | None) -> None:
        a = self._answer(q.id)
        if a.value is not None and a.value != value:
            a.changed_from = [*a.changed_from, a.value]
        a.value, a.status, a.raw_utterance = value, "answered", raw.strip()
        if note:
            a.feedback_raw = note
            self._tag(note, q.label)
        if self._needs_feedback(q, value) and not a.feedback_raw and q.id not in self.state.feedback_queue:
            self.state.feedback_queue.append(q.id)
        if not self._needs_feedback(q, value) and q.id in self.state.feedback_queue:
            self.state.feedback_queue.remove(q.id)

    def _tag(self, text: str, where: str) -> list[str]:
        tags = escalation_tags(text)
        for tag in tags:
            self._task(tag, f"{tag} ใน{where}", text.strip())
        return tags

    @staticmethod
    def _note(text: str) -> str | None:
        """Free-text content volunteered alongside (or instead of) a score."""
        residue = _SCORE_FILLER.sub("", normalize(text))
        return text.strip() if len(residue) >= 4 else None

    def _question_ref(self, ref: str | None) -> QuestionSpec | None:
        if ref is None:
            return None
        if ref == "สุดท้าย":
            return self.questions[-1]
        number = int(ref) if ref.isdigit() else _ORDINALS.get(ref)
        if number and 1 <= number <= len(self.questions):
            return self.questions[number - 1]
        return None

    # ---- body ----

    def _case_facts(self) -> list[str]:
        return [f"- วันที่เกิดเหตุ: {self.vars['accident_date']}", f"- เลขที่เคส: {self.vars['case_id']}"]

    def _notice_followup(self) -> list[Segment]:
        return self._seg("scale_intro")

    def _begin_body(self) -> Directive:
        self.state.body_started = True
        self.state.stage = "intro_scale"
        return self._ask(0, self._seg("section1"))

    def _continue(self) -> Directive:
        if self.state.stage == "notice":
            return self._begin_body()
        raise RuntimeError(f"no continuation from stage {self.state.stage}")

    def _reprompt_body(self) -> list[Segment]:
        match self.state.stage:
            case "question":
                return [Segment(text=self._current.short)]
            case "surveyor_check":
                return self._seg("surveyor_check")
            case "feedback":
                qid = (self.state.awaiting or ":").split(":")[1]
                return [Segment(text=self._spec(qid).feedback)]
            case "final_comment":
                return self._seg("final_comment")
        return self._seg("still_there")

    def _partial_outcome(self) -> Outcome:
        return Outcome.SURVEY_PARTIAL

    def _body(self, s: Signals) -> Directive:
        match self.state.stage:
            case "question":
                return self._score(s)
            case "surveyor_check":
                return self._surveyor_check(s)
            case "feedback":
                return self._feedback(s)
            case "final_comment":
                return self._comment(s)
        raise RuntimeError(f"unexpected stage {self.state.stage}")

    def _surveyor_check(self, s: Signals) -> Directive:
        if s.not_applicable or s.negative:
            self._mark_not_applicable(s.text)
            return self._ask(self.state.question_index, self._seg("section2_na"))
        if s.affirm:
            self.state.stage = "surveyor_check_done"
            return self._ask(self.state.question_index, [self._ack()])

        def give_up() -> Directive:
            self.state.stage = "surveyor_check_done"
            return self._ask(self.state.question_index, [])

        return self._clarify_or(give_up)

    def _score(self, s: Signals) -> Directive:
        q = self._current
        target = self._question_ref(s.score.question_ref)
        if target is not None and target.id != q.id and s.score.value is not None:
            return self._correction(target, s)

        if s.not_applicable and q.allow_na:
            self._mark_not_applicable(s.text)
            return self._ask(self.state.question_index + 1, self._seg("section2_na"))
        if s.skip:
            self._answer(q.id).status = "skipped"
            self._answer(q.id).raw_utterance = s.text
            return self._after_answer([self._ack()])

        low, high = q.scale
        value = high if s.score.is_max else s.score.value
        note = self._note(s.text)
        if value is not None:
            if not low <= value <= high:
                return self._out_of_range(q, s)
            self._record(q, value, s.text, note)
            if s.both_questions:
                pair = [
                    p
                    for p in self.questions
                    if p.section == q.section
                    and p.id != q.id
                    and self._answer(p.id).status in {"not_asked", "unanswered"}
                ]
                for p in pair:
                    self._record(p, value, s.text, None)
            heard_feedback = bool(self._answer(q.id).feedback_raw) and self._needs_feedback(q, value)
            if heard_feedback and q.id in self.state.reflected:
                return self._after_answer([self._ack()])
            if heard_feedback:
                return self._after_answer(self._feedback_ack(s))
            if s.score.hedged:
                # "สี่มั้งคะ": echo the number back so the customer can correct it, as an operator would.
                return self._after_answer(self._seg("score_echo", value=value))
            return self._after_answer([self._ack()])
        if s.score.ambiguous:
            options = " หรือ ".join(str(c) for c in s.score.candidates)
            return self._retry(s, "score_ambiguous", options=options)
        if s.question:
            answer = self._answer_question(s.text, off_topic=s.off_topic)
            return self._directive(
                "question_answer",
                [*answer, *self._seg("return_prefix"), Segment(text=q.short)],
                expects=f"score:{q.id}",
            )
        if note:
            # e.g. "ก็โอเคนะ แต่รอนาน": keep what was said, acknowledge it, then ask for the number.
            a = self._answer(q.id)
            a.feedback_raw = note
            self._tag(note, q.label)
            if s.reflection and self.state.clarify_count < self.campaign.limits.max_clarifications:
                self.state.reflected = [*self.state.reflected, q.id]
                retry = self._retry(s, "score_clarify")
                return retry.model_copy(
                    update={"segments": [*self._seg("reflect_note", reflection=s.reflection), *retry.segments]}
                )
        return self._retry(s, "score_clarify")

    def _out_of_range(self, q: QuestionSpec, s: Signals) -> Directive:
        return self._retry(s, "score_out_of_range", scale_min=q.scale[0], scale_max=q.scale[1])

    def _retry(self, s: Signals, key: str, **extra: object) -> Directive:
        """Ask a clarifying question, or record the question as unanswered once the budget is spent."""
        q = self._current
        if self.state.clarify_count >= self.campaign.limits.max_clarifications:
            a = self._answer(q.id)
            a.status, a.raw_utterance = "unanswered", s.text
            self._task("unclear_answer", f"ไม่ได้คะแนนที่ชัดเจนสำหรับ{q.label}", s.text, q.id)
            return self._after_answer([self._ack()])
        self.state.clarify_count += 1
        values = {"scale_min": q.scale[0], "scale_max": q.scale[1], **extra}
        return self._directive(key, self._seg(key, **values), expects=f"score:{q.id}")

    def _correction(self, target: QuestionSpec, s: Signals) -> Directive:
        value = s.score.value
        assert value is not None
        q = self._current
        if not target.scale[0] <= value <= target.scale[1]:
            return self._out_of_range(target, s)
        self._record(target, value, s.text, None)
        prefix = self._seg("correction_ack", question_label=target.label, value=value)
        if self.state.feedback_queue and self.state.feedback_queue[0] == target.id:
            return self._after_answer(prefix)
        return self._directive(f"ask:{q.id}", [*prefix, Segment(text=q.short)], expects=f"score:{q.id}")

    def _feedback(self, s: Signals) -> Directive:
        qid = (self.state.awaiting or ":").split(":")[1]
        q = self._spec(qid)
        if s.correction and s.score.value is not None and q.scale[0] <= s.score.value <= q.scale[1]:
            self._record(q, s.score.value, s.text, None)
            if not self._needs_feedback(q, s.score.value):
                return self._after_answer(self._seg("correction_ack", question_label=q.label, value=s.score.value))
        a = self._answer(qid)
        if s.no_comment or (s.negative and len(strip_particles(normalize(s.text))) <= 6):
            return self._after_answer([self._ack()])
        a.feedback_raw = s.text.strip()
        self._tag(s.text, f"ข้อเสนอแนะ{q.label}")
        return self._after_answer(self._feedback_ack(s))

    def _feedback_ack(self, s: Signals) -> list[Segment]:
        """Reflect the customer's own point back briefly when the model offered a safe phrase."""
        if s.reflection:
            return self._seg("reflect_feedback", reflection=s.reflection)
        return [self._ack(self.campaign.feedback_acknowledgements)]

    def _repeat_short(self) -> list[Segment] | None:
        if self.state.stage == "question":
            return [Segment(text=self._current.short)]
        if self.state.stage == "feedback":
            qid = (self.state.awaiting or ":").split(":")[1]
            return [Segment(text=self._spec(qid).feedback)]
        return None

    def _comment(self, s: Signals) -> Directive:
        prefix: list[Segment] = []
        if not (s.no_comment or (s.negative and len(strip_particles(normalize(s.text))) <= 6)):
            self.result.final_comment_raw = s.text.strip()
            tags = self._tag(s.text, "ความคิดเห็นเพิ่มเติม")
            self.result.final_comment_tags = tags
            if tags and s.reflection:
                prefix += self._seg("reflect_escalation", reflection=s.reflection)
            elif tags:
                prefix += self._seg("escalation_ack")
            elif s.reflection:
                prefix += self._seg("reflect_feedback", reflection=s.reflection)
            if {"safety", "urgent"} & set(tags):
                prefix += self._seg("safety_advice")
        return self._close_with(prefix)

    def _close_with(self, prefix: list[Segment]) -> Directive:
        directive = self._close(Outcome.SURVEY_COMPLETED, "closing", "completed")
        return Directive(key=directive.key, segments=[*prefix, *directive.segments], end_call=True)
