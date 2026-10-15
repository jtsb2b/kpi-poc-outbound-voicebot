"""LLM interpreter: request shape, merge rules, safety floor, fallback and rate limiting (no network)."""

import json
from typing import Any

import httpx
import pytest

from kpi_voicebot.campaigns import get_profile
from kpi_voicebot.config import Settings
from kpi_voicebot.engine import InterpretContext
from kpi_voicebot.llm import LLMClient, LLMError, RateLimiter
from kpi_voicebot.llm_interpreter import SCHEMA, LLMInterpreter, build_messages, merge
from kpi_voicebot.simulator import build_engine, run_script
from kpi_voicebot.thai_parse import read_signals


def blank(**overrides: Any) -> dict[str, Any]:
    """A model reply; boolean keyword arguments become entries in `intents`."""
    out: dict[str, Any] = {
        "intents": [],
        "score": None,
        "score_candidates": [],
        "question_ref": None,
        "callback_time": None,
        "tags": [],
    }
    for key, value in overrides.items():
        if isinstance(value, bool):
            if value:
                out["intents"].append(key)
        else:
            out[key] = value
    return out


def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        operator_token="test-operator-token",
        llm_base_url="https://llm.test/v1",
        llm_api_key="sk-test",
        llm_model="qwen-test",
        _env_file=None,
    )


def client_returning(payloads: list[dict[str, Any]], seen: list[dict[str, Any]] | None = None) -> LLMClient:
    queue = list(payloads)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        assert request.headers["Authorization"] == "Bearer sk-test"
        payload = queue.pop(0) if queue else blank()
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"total_tokens": 300}}
        )

    return LLMClient(settings(), transport=httpx.MockTransport(handler))


async def test_request_disables_thinking_and_enforces_schema() -> None:
    seen: list[dict[str, Any]] = []
    client = client_returning([blank()], seen)
    ctx = InterpretContext(awaiting="score:q1", last_question="ให้กี่คะแนนดีคะ", recent_turns=[("bot", "x")])
    signals = await LLMInterpreter(client).interpret("เอ่อ สี่มั้งครับ", ctx)
    assert signals.score.value == 4  # numbers come from the rule parser
    body = seen[0]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "ข้อ Q1" in body["messages"][1]["content"] and "ให้กี่คะแนนดีคะ" in body["messages"][1]["content"]


def test_call_ending_signals_come_from_rules_only() -> None:
    assert merge(read_signals("ไม่ต้องโทรมาอีกนะ"), blank(affirm=True)).dnc
    complaint = read_signals("พนักงานรับแจ้งพูดจาไม่สุภาพ อยากร้องเรียนค่ะ")
    merged = merge(complaint, {**blank(no_comment=True), "intents": ["no_comment", "objection", "dnc"]})
    assert not (merged.dnc or merged.objection)


def test_free_text_answers_take_only_tags_from_the_model() -> None:
    text = "พนักงานรับแจ้งพูดจาไม่สุภาพ อยากร้องเรียนค่ะ"
    merged = merge(read_signals(text), blank(no_comment=True, tags=["complaint", "urgent"]), "final_comment")
    assert not merged.no_comment
    assert set(merged.tags) == {"complaint", "urgent"}


def test_model_reads_context_the_rules_cannot() -> None:
    assert merge(read_signals("ก็ดูบ้างครับ"), blank(affirm=True), "availability").affirm
    merged = merge(read_signals("เอาเป็นสี่ละกัน ข้อนั้น"), blank(question_ref=1, correction=True), "score:q2")
    assert (merged.score.value, merged.score.question_ref, merged.correction) == (4, "1", True)


def test_model_intents_must_fit_the_question() -> None:
    merged = merge(read_signals("พรุ่งนี้บ่ายสองโมงครับ"), blank(ai_identity=True), "callback_time")
    assert not merged.ai_identity and merged.callback_time
    merged = merge(read_signals("ก็โอเคนะ แต่รอสายนานมาก"), blank(question=True, affirm=True), "score:q2")
    assert not merged.question and not merged.affirm


def test_model_never_invents_a_score() -> None:
    merged = merge(read_signals("ก็โอเคนะ แต่รอสายนานมาก"), blank(affirm=True), "score:q2")
    assert merged.score.value is None and not merged.score.candidates and not merged.score.is_max
    assert "is_max" not in SCHEMA["properties"]["intents"]["items"]["enum"]


async def test_errors_fall_back_to_rules() -> None:
    client = LLMClient(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    interpreter = LLMInterpreter(client)
    signals = await interpreter.interpret(
        "ใช่ค่ะ คุณสมชายพูดอยู่ค่ะ", InterpretContext(awaiting="identity", last_question=None, recent_turns=[])
    )
    assert signals.affirm and "fallback" in interpreter.last_metrics


async def test_rate_limiter_refuses_to_wait_past_budget() -> None:
    limiter = RateLimiter(requests_per_minute=1, tokens_per_minute=0)
    await limiter.acquire(100, max_wait=1)
    with pytest.raises(LLMError):
        await limiter.acquire(100, max_wait=1)
    assert RateLimiter(0, 500).wait_seconds(400, now=0.0) == 0.0


async def test_scenario_runs_end_to_end_through_llm_interpreter() -> None:
    profile = get_profile("survey-surveyor")
    assert profile is not None
    replies = [
        blank(affirm=True),
        blank(affirm=True),
        blank(backchannel=True, affirm=True),
        blank(score=5),
        blank(score=5),
        blank(score=4),
        blank(score=5),
        blank(score=10),
        blank(no_comment=True),
    ]
    engine = build_engine(profile.campaign, profile.case, "สมชาย ใจดี")

    class Sink:
        def __init__(self) -> None:
            self.events: list[str] = []

        async def bot(self, *a: Any) -> None: ...
        async def customer(self, text: str) -> None: ...
        async def event(self, kind: str, data: Any = None) -> None:
            self.events.append(kind)

    sink = Sink()
    lines = ["ใช่ครับ", "ได้ครับ", "ครับ", "เต็มห้า", "ห้า", "สี่", "ห้า", "สิบ", "ไม่มีครับ"]
    await run_script(engine, lines, sink, interpreter=LLMInterpreter(client_returning(replies)))
    assert engine.outcome == "survey_completed"
    assert sink.events.count("llm_interpretation") == len(lines)


def test_prompt_mentions_q5_scale() -> None:
    msgs = build_messages("แปด", InterpretContext(awaiting="score:q5", last_question=None, recent_turns=[]))
    assert "0 ถึง 10" in msgs[1]["content"]


def test_reflection_guardrails() -> None:
    from kpi_voicebot.llm_interpreter import safe_reflection

    text = "ก็โอเคนะ แต่รอสายนานมาก"
    assert safe_reflection("รอสายนาน", text) == "รอสายนาน"
    assert safe_reflection("เรื่องรอสายนาน", text) == "รอสายนาน"
    assert safe_reflection("เราจะแก้ไขให้เร็วขึ้น", text) is None  # promise
    assert safe_reflection("รอ 30 นาที", text) is None  # number
    assert safe_reflection("พนักงานพูดไม่สุภาพ", text) is None  # not the customer's words
    assert safe_reflection("ขออภัยที่รอนาน", text) is None


def test_model_may_abstain_and_never_turns_nonsense_into_yes() -> None:
    merged = merge(
        read_signals("กล้วยทอดอร่อย"), {**blank(affirm=True), "intents": ["affirm", "unclear"]}, "confirm:delivery"
    )
    assert not merged.affirm and merged.unclear


def test_meta_question_is_not_a_question() -> None:
    merged = merge(read_signals("อยากสอบถามเพิ่มเติมครับ"), blank(question=True, has_question=True), "questions")
    assert merged.has_question and not merged.question


def test_particles_are_tidied() -> None:
    from kpi_voicebot.engine import tidy_particles
    from kpi_voicebot.models import Segment

    out = tidy_particles(
        [Segment(text="ค่ะ"), Segment(text="วงเงิน 300,000 บาทค่ะ", facts=["death_benefit"]), Segment(text="ถูกต้องไหมค่ะ")]
    )
    assert [s.text for s in out] == ["ค่ะ", "วงเงิน 300,000 บาท", "ถูกต้องไหมคะ"]
    kept = tidy_particles([Segment(text="ขอบคุณที่บอกค่ะ"), Segment(text="ให้กี่คะแนนดีคะ")])
    assert kept[0].text == "ขอบคุณที่บอกค่ะ"


async def test_clear_short_replies_skip_the_model() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    interpreter = LLMInterpreter(LLMClient(settings(), transport=httpx.MockTransport(handler)))
    review = InterpretContext(awaiting="confirm:medical", last_question=None, recent_turns=[])
    for reply in ("ครับ", "อ่าห้ะ", "ใช่ครับ", "ถูกต้องครับ"):
        assert (await interpreter.interpret(reply, review)).affirm or read_signals(reply).backchannel
    assert not calls
    await interpreter.interpret("ครับ คิดว่านะ", review)  # hedged: the model must read it
    await interpreter.interpret("1", InterpretContext(awaiting="score:q1", last_question=None, recent_turns=[]))
    assert len(calls) == 2
