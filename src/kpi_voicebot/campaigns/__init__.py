"""Campaign definitions loaded from YAML: wording, facts, questions, FAQ and limits.

Campaign content stays out of engine code so wording can be revised and approved
without touching conversation logic. A snapshot hash identifies the exact version
used by each call.
"""

import hashlib
import json
from functools import cache
from importlib import resources
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from kpi_voicebot.models import CampaignId, MockProfile, PACase, SurveyCase

WordingStatus = Literal["poc_approved", "kpi_source", "pending_kpi_approval"]


class SegmentSpec(BaseModel):
    text: str
    facts: list[str] = []
    requires: list[str] = []


class Wording(BaseModel):
    status: WordingStatus
    segments: list[SegmentSpec]
    # Legal or approved disclosure: spoken exactly as written, never rephrased by the model.
    verbatim: bool = False
    # Other approved ways to say a one-line wording, rotated so the bot never repeats itself.
    alternatives: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _plain_segments(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            data["segments"] = [s if isinstance(s, dict) else {"text": s} for s in data.get("segments", [])]
        return data


class ReviewUnit(BaseModel):
    id: str
    short: str
    status: WordingStatus
    segments: list[SegmentSpec]
    confirm: str = ""  # an explicit check question; empty means the fact is said as a statement
    repeat: list[SegmentSpec] = []  # the key values only, for "ขออีกที"


class PolicyFieldSpec(BaseModel):
    field: str
    label: str
    value: str
    keywords: list[str] = []
    requires: list[str] = []


class FaqEntry(BaseModel):
    id: str
    keywords: list[str]
    answer: str
    requires: list[str] = []


class QuestionSpec(BaseModel):
    id: str
    section: int
    label: str
    scale: tuple[int, int]
    feedback_range: tuple[int, int]
    allow_na: bool = False
    ask: str
    short: str
    feedback: str


class Limits(BaseModel):
    max_clarifications: int = 2
    max_silences: int = 3
    max_faq_questions: int = 3


class IdentityConfig(BaseModel):
    second_factor: Literal["birth_day_month"] | None = None


class ReviewGroup(BaseModel):
    """Policy items read together in one turn and confirmed with one question."""

    id: str
    short: str
    units: list[str]
    confirm: str = ""  # the group's check question; empty uses the last unit's own confirm question


class Campaign(BaseModel):
    id: CampaignId
    title: str
    version: str
    persona_name: str
    service_phone: str
    identity: IdentityConfig = IdentityConfig()
    limits: Limits = Limits()
    wording: dict[str, Wording]
    acknowledgements: list[str] = Field(min_length=1)
    feedback_acknowledgements: list[str] = []
    review_units: list[ReviewUnit] = []
    review_groups: list[ReviewGroup] = []
    policy_fields: list[PolicyFieldSpec] = []
    questions: list[QuestionSpec] = []
    faq: list[FaqEntry] = []
    snapshot_id: str = ""

    def text(self, key: str) -> Wording:
        return self.wording[key]

    def pending_approval(self) -> list[str]:
        keys = [k for k, w in self.wording.items() if w.status == "pending_kpi_approval"]
        keys += [f"review:{u.id}" for u in self.review_units if u.status == "pending_kpi_approval"]
        if self.faq:
            keys.append("faq (all demo answers)")
        return keys


_REQUIRED_WORDING = {
    "greet",
    "identity_recheck",
    "intro",
    "availability_short",
    "notice",
    "closing",
    "wrong_person_close",
    "ask_callback_time",
    "callback_close",
    "callback_close_no_time",
    "objection_close",
    "refuse_close",
    "dnc_close",
    "hold_ack",
    "still_there",
    "no_response_close",
    "ai_identity",
    "unknown_answer",
    "second_factor_ask",
    "second_factor_retry",
    "verification_failed_close",
}


def _read(name: str) -> dict[str, Any]:
    raw = resources.files("kpi_voicebot.campaigns").joinpath("data", name).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    assert isinstance(data, dict)
    return data


@cache
def load_campaign(campaign_id: CampaignId) -> Campaign:
    common = _read("common.yaml")
    data = _read(f"{campaign_id.value}.yaml")
    data["wording"] = {**common["wording"], **data.get("wording", {})}
    campaign = Campaign.model_validate(data)
    missing = _REQUIRED_WORDING - set(campaign.wording)
    if missing:
        raise ValueError(f"{campaign_id}: missing wording keys {sorted(missing)}")
    if campaign.id is CampaignId.PA_CONFIRMATION and not campaign.review_units:
        raise ValueError("pa_confirmation needs review_units")
    if campaign.id is CampaignId.ACCIDENT_SURVEY and len(campaign.questions) != 5:
        raise ValueError("accident_survey needs five questions")
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    return campaign.model_copy(update={"snapshot_id": digest[:16]})


@cache
def load_profiles() -> tuple[MockProfile, ...]:
    profiles = tuple(MockProfile.model_validate(p) for p in _read("profiles.yaml")["profiles"])
    for p in profiles:
        validate_case(p.campaign, p.case)
    return profiles


def get_profile(profile_id: str) -> MockProfile | None:
    return next((p for p in load_profiles() if p.profile_id == profile_id), None)


def validate_case(campaign: CampaignId, case: dict[str, object]) -> PACase | SurveyCase:
    if campaign is CampaignId.PA_CONFIRMATION:
        return PACase.model_validate(case)
    return SurveyCase.model_validate(case)
