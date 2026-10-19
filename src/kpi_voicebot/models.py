"""Call, conversation and result models shared by the engine, store, API and exports.

Lifecycle (how far the call got), dial result (what telephony reported) and outcome
(what the conversation achieved) are deliberately separate fields.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class CampaignId(StrEnum):
    PA_CONFIRMATION = "pa_confirmation"
    ACCIDENT_SURVEY = "accident_survey"


class Lifecycle(StrEnum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    DIALING = "dialing"
    RINGING = "ringing"
    IN_CONVERSATION = "in_conversation"
    ENDING = "ending"
    ENDED = "ended"
    RECONCILING = "reconciling"


ACTIVE_LIFECYCLE = frozenset(
    {
        Lifecycle.DISPATCHING,
        Lifecycle.DIALING,
        Lifecycle.RINGING,
        Lifecycle.IN_CONVERSATION,
        Lifecycle.ENDING,
        Lifecycle.RECONCILING,
    }
)


class DialResult(StrEnum):
    ANSWERED = "answered"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    REJECTED = "rejected"
    UNREACHABLE = "unreachable"
    TECHNICAL_FAILURE = "technical_failure"
    CANCELED = "canceled"


class Outcome(StrEnum):
    POLICY_CONFIRMED = "policy_confirmed"
    CONFIRMED_WITH_DISCREPANCY = "confirmed_with_discrepancy"
    POLICY_PARTIAL = "policy_partial"
    SURVEY_COMPLETED = "survey_completed"
    SURVEY_PARTIAL = "survey_partial"
    CALLBACK_REQUESTED = "callback_requested"
    WRONG_PERSON = "wrong_person"
    VERIFICATION_FAILED = "verification_failed"
    REFUSED = "refused"
    DO_NOT_CALL = "do_not_call"
    NOTICE_OBJECTION = "notice_objection"
    NO_RESPONSE = "no_response"
    HUNG_UP_EARLY = "hung_up_early"
    NOT_REACHED = "not_reached"
    CANCELED = "canceled"
    TECHNICAL_FAILURE = "technical_failure"


class CallMode(StrEnum):
    SIMULATION = "simulation"
    LIVE = "live"


IdentityResult = Literal["not_reached", "confirmed", "wrong_person", "unclear", "failed"]
FieldStatus = Literal["not_reviewed", "confirmed", "disputed", "unclear"]
AnswerStatus = Literal["not_asked", "answered", "not_applicable", "skipped", "unanswered"]
TaskType = Literal[
    "callback",
    "policy_discrepancy",
    "question_follow_up",
    "complaint",
    "claim_dispute",
    "safety",
    "urgent",
    "unclear_answer",
]


# ---- campaign case data (mock profiles and Excel rows) ----


class PACase(BaseModel):
    record_id: str
    data_label: str = "MOCK"
    plan_name: str
    plan_code: str | None = None
    death_benefit_thb: float = Field(ge=0)
    medical_per_accident_thb: float | None = Field(default=None, ge=0)
    daily_hospital_thb: float | None = Field(default=None, ge=0)
    daily_hospital_max_days: int | None = Field(default=None, ge=1)
    motorcycle_benefit_thb: float | None = Field(default=None, ge=0)
    public_transport_benefit_thb: float | None = Field(default=None, ge=0)
    premium_thb: float = Field(ge=0)
    billing_period: Literal["ปี", "เดือน"] = "ปี"
    effective_date: date
    effective_time: str = "00.01 น."
    beneficiary: str
    payment_channel: str
    payment_status: str = "ชำระแล้ว"
    delivery_channel: Literal["อีเมล", "ไปรษณีย์"]
    delivery_target: str
    delivery_period_text: str = "7 ถึง 14 วันทำการ"
    verify_birth_date: date | None = None


class SurveyCase(BaseModel):
    record_id: str
    data_label: str = "MOCK"
    case_id: str
    accident_date: date
    surveyor_attended: bool | None = None
    verify_birth_date: date | None = None


class MockProfile(BaseModel):
    profile_id: str
    campaign: CampaignId
    label: str
    case: dict[str, object]


# ---- conversation output ----


class Segment(BaseModel):
    text: str
    facts: list[str] = []
    verbatim: bool = False  # must reach the customer word for word (notice, AI disclosure, free-look)
    voice: str | None = None  # the text as the voice reads it, with audio tags ("<short pause>"); None: `text`


class Directive(BaseModel):
    """One bot turn. Segments are the unit of delivery tracking for interruptions."""

    key: str
    segments: list[Segment]
    expects: str | None = None
    end_call: bool = False
    protected: bool = True

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments)

    @property
    def voice_text(self) -> str:
        """What the voice is given: the text with its audio tags (transcripts keep `text`)."""
        return " ".join(s.voice or s.text for s in self.segments)


class FollowUpTask(BaseModel):
    type: TaskType
    reason: str
    detail_raw: str | None = None
    field: str | None = None


class PolicyFieldResult(BaseModel):
    field: str
    label: str
    expected_value: str
    status: FieldStatus = "not_reviewed"
    delivery: Literal["not_delivered", "full", "resumed_after_interruption"] = "not_delivered"
    customer_statement: str | None = None


class SurveyAnswer(BaseModel):
    question: str
    label: str
    scale_min: int
    scale_max: int
    value: int | None = None
    status: AnswerStatus = "not_asked"
    raw_utterance: str | None = None
    feedback_raw: str | None = None
    feedback_asked: bool = False
    changed_from: list[int] = []


class CallbackRequest(BaseModel):
    requested: bool = False
    preferred_time_text: str | None = None


class ConversationResult(BaseModel):
    identity_result: IdentityResult = "not_reached"
    notice_delivered: bool = False
    # Customer's answer to recording the call's audio (None: not asked). Declined: transcript only.
    recording_consent: bool | None = None
    callback: CallbackRequest = CallbackRequest()
    policy_fields: list[PolicyFieldResult] = []
    free_look_delivery: Literal["not_delivered", "full", "resumed_after_interruption"] | None = None
    survey_answers: list[SurveyAnswer] = []
    final_comment_raw: str | None = None
    final_comment_tags: list[str] = []
    tasks: list[FollowUpTask] = []
    end_reason: str | None = None


class TranscriptTurn(BaseModel):
    seq: int
    speaker: Literal["bot", "customer"]
    at: datetime
    text: str
    generated_text: str | None = None
    spoken_complete: bool | None = None
    interrupted: bool | None = None
    directive_key: str | None = None
