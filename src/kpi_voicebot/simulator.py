"""Text simulator: drives a campaign engine with scripted or typed customer replies.

It stands in for ASR, TTS and telephony. The same runner feeds the worker (results go
to MongoDB) and the `kpi-sim` CLI (results go to the terminal).
"""

import argparse
import asyncio
import json
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Protocol

import yaml
from pydantic import BaseModel

from kpi_voicebot.campaigns import get_profile, load_campaign, validate_case
from kpi_voicebot.dialogue import AsyncInterpreter, Dialogue
from kpi_voicebot.engine import BaseEngine
from kpi_voicebot.models import CampaignId, Directive, PACase
from kpi_voicebot.pa_engine import PAEngine
from kpi_voicebot.playback import VoicePlayer
from kpi_voicebot.responder import Responder
from kpi_voicebot.survey_engine import SurveyEngine

_INTERRUPT = re.compile(r"^\[INTERRUPT(?::(\d+))?\]\s*(.*)$")


class Scenario(BaseModel):
    id: str
    campaign: CampaignId
    profile: str
    label: str
    customer: list[str]
    expect: dict[str, Any] = {}


@cache
def load_scenarios() -> tuple[Scenario, ...]:
    raw = resources.files("kpi_voicebot.campaigns").joinpath("data", "scenarios.yaml").read_text(encoding="utf-8")
    return tuple(Scenario.model_validate(s) for s in yaml.safe_load(raw)["scenarios"])


def get_scenario(scenario_id: str) -> Scenario | None:
    return next((s for s in load_scenarios() if s.id == scenario_id), None)


def build_engine(campaign_id: CampaignId, case: dict[str, object], customer_name: str) -> BaseEngine:
    campaign = load_campaign(campaign_id)
    parsed = validate_case(campaign_id, case)
    if isinstance(parsed, PACase):
        return PAEngine(campaign, parsed, customer_name)
    return SurveyEngine(campaign, parsed, customer_name)


class Sink(Protocol):
    async def bot(self, directive: Directive, spoken_segments: int, complete: bool) -> None: ...
    async def customer(self, text: str) -> None: ...
    async def event(self, kind: str, data: dict[str, Any] | None = None) -> None: ...


class Canceled(Exception):
    pass


@dataclass
class _Line:
    kind: str  # say | silence | hangup
    text: str = ""
    interrupt_after: int | None = None


def parse_line(line: str) -> _Line:
    stripped = line.strip()
    if stripped == "[SILENCE]":
        return _Line("silence")
    if stripped == "[HANGUP]":
        return _Line("hangup")
    m = _INTERRUPT.match(stripped)
    if m:
        return _Line("say", m.group(2), int(m.group(1) or 1))
    return _Line("say", stripped)


async def run_script(
    engine: BaseEngine,
    lines: list[str],
    sink: Sink,
    *,
    delay_seconds: float = 0.0,
    is_canceled: Callable[[], Awaitable[bool]] | None = None,
    interpreter: AsyncInterpreter | None = None,
    responder: Responder | None = None,
) -> None:
    script = [parse_line(line) for line in lines if line.strip()]
    dialogue = Dialogue(engine, interpreter, responder)
    directive = dialogue.start()
    while True:
        upcoming = script[0] if script else None
        interrupt = upcoming.interrupt_after if upcoming else None
        if interrupt is not None and interrupt < len(directive.segments) and not directive.end_call:
            spoken, complete = interrupt, False
        else:
            spoken, complete = len(directive.segments), True
        engine.report_delivery(spoken, complete)
        await sink.bot(directive, spoken, complete)
        if directive.end_call:
            return
        if delay_seconds:
            await asyncio.sleep(delay_seconds)
        if is_canceled is not None and await is_canceled():
            raise Canceled
        if not script:
            await sink.event("customer_hung_up", {"reason": "script_ended"})
            engine.handle_hangup()
            return
        line = script.pop(0)
        if line.kind == "hangup":
            await sink.event("customer_hung_up")
            engine.handle_hangup()
            return
        if line.kind == "silence":
            await sink.event("customer_silence")
            directive = engine.handle_silence()
            continue
        await sink.customer(line.text)
        directive = await dialogue.reply(line.text)
        for kind, data in dialogue.events:
            await sink.event(kind, data)
        dialogue.events.clear()


# ---- CLI ----


class _PrintSink:
    def __init__(self, voice: VoicePlayer | None = None) -> None:
        self.voice = voice
        self.waited_from = time.monotonic()  # when the customer stopped talking

    async def bot(self, directive: Directive, spoken_segments: int, complete: bool) -> None:
        spoken = " ".join(s.text for s in directive.segments[:spoken_segments])
        marker = "" if complete else "  ⟂ [ถูกพูดแทรก]"
        print(f"\033[34m🤖 น้องเคพีไอ:\033[0m {spoken}{marker}")
        if self.voice is not None:
            await self.voice.play(directive, spoken_segments, self.waited_from)
            self.waited_from = time.monotonic()

    async def customer(self, text: str) -> None:
        print(f"\033[32m👤 ลูกค้า:\033[0m {text}")
        self.waited_from = time.monotonic()

    async def event(self, kind: str, data: dict[str, Any] | None = None) -> None:
        print(f"\033[90m   · {kind} {data or ''}\033[0m")


def _summary(engine: BaseEngine) -> str:
    result = engine.result.model_dump(exclude_defaults=True)
    return json.dumps({"outcome": engine.outcome, **result}, ensure_ascii=False, indent=2, default=str)


Run = Callable[[AsyncInterpreter | None, Responder | None], Awaitable[None]]


async def _with_llm(use_llm: bool, run: Run) -> None:
    """With --llm, the self-hosted LLM both reads the customer's replies and words the bot's turns."""
    if not use_llm:
        await run(None, None)
        return
    from kpi_voicebot.config import get_settings
    from kpi_voicebot.llm import LLMClient
    from kpi_voicebot.llm_interpreter import LLMInterpreter

    client = LLMClient(get_settings())
    try:
        await run(LLMInterpreter(client), Responder(client))
    finally:
        await client.aclose()


async def _chat(engine: BaseEngine, dialogue: Dialogue, voice: VoicePlayer | None = None) -> None:
    if voice is None:
        await _chat_loop(engine, dialogue, _PrintSink())
        return
    await voice.prepare()
    try:
        await _chat_loop(engine, dialogue, _PrintSink(voice))
    finally:
        await voice.close()


async def _chat_loop(engine: BaseEngine, dialogue: Dialogue, sink: _PrintSink) -> None:
    directive = dialogue.start()
    while True:
        dialogue.prepare_next()  # word the likely next turn while this one is spoken
        if sink.voice is not None and dialogue.prepared is not None:
            sink.voice.prefetch(dialogue.prepared)
        await sink.bot(directive, len(directive.segments), True)
        if directive.end_call:
            engine.report_delivery(len(directive.segments), True)
            return
        raw = (await asyncio.to_thread(input, "> ")).strip()
        sink.waited_from = time.monotonic()
        spoken, complete = len(directive.segments), True
        if raw.startswith("/interrupt"):
            parts = raw.split(maxsplit=2)
            spoken, complete = min(int(parts[1]), len(directive.segments) - 1), False
            raw = parts[2] if len(parts) > 2 else "ค่ะ"
            print(f"   · bot was cut off after {spoken} segment(s)")
        engine.report_delivery(spoken, complete)
        if raw in {"/hangup", "/quit"}:
            engine.handle_hangup()
            return
        if raw == "/silence":
            directive = engine.handle_silence()
            continue
        directive = await dialogue.reply(raw)
        for kind, data in dialogue.events:
            print(f"\033[90m   · {kind} {data}\033[0m")
        dialogue.events.clear()


def main() -> None:
    parser = argparse.ArgumentParser(prog="kpi-sim", description="KPI voicebot text simulator")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list scenarios and mock profiles")
    run = sub.add_parser("run", help="run a scripted scenario")
    run.add_argument("scenario")
    run.add_argument("--name", default="สมชาย ใจดี")
    run.add_argument("--llm", action="store_true", help="interpret replies with the self-hosted LLM")
    run.add_argument("--voice", action="store_true", help="speak bot turns aloud (JAI TTS)")
    chat = sub.add_parser("chat", help="type the customer's replies yourself")
    chat.add_argument("profile")
    chat.add_argument("--name", default="สมชาย ใจดี")
    chat.add_argument("--llm", action="store_true", help="interpret replies with the self-hosted LLM")
    chat.add_argument("--voice", action="store_true", help="speak bot turns aloud (JAI TTS)")
    chat.add_argument(
        "--mic", action="store_true", help="answer by speaking into the microphone (JaiASR); implies --voice"
    )
    chat.add_argument(
        "--headphones", action="store_true", help="with --mic: let the customer cut in while the bot talks"
    )
    chat.add_argument(
        "--aec", action="store_true", help="with --mic on speakers: echo cancellation, so the customer can cut in"
    )
    args = parser.parse_args()

    if args.command == "list":
        from kpi_voicebot.campaigns import load_profiles

        print("Profiles:")
        for p in load_profiles():
            print(f"  {p.profile_id:20} {p.campaign:16} {p.label}")
        print("Scenarios:")
        for s in load_scenarios():
            print(f"  {s.id:28} {s.label}")
        return

    if args.command == "run":
        scenario = get_scenario(args.scenario)
        if scenario is None:
            sys.exit(f"unknown scenario {args.scenario}")
        profile = get_profile(scenario.profile)
        assert profile is not None
        engine = build_engine(scenario.campaign, profile.case, args.name)
        script = scenario.customer
        voice = VoicePlayer() if args.voice else None

        async def scripted(i: AsyncInterpreter | None, responder: Responder | None) -> None:
            if voice is not None:
                await voice.prepare()
            try:
                await run_script(engine, script, _PrintSink(voice), interpreter=i, responder=responder)
            finally:
                if voice is not None:
                    await voice.close()

        asyncio.run(_with_llm(args.llm, scripted))
    else:
        profile = get_profile(args.profile)
        if profile is None:
            sys.exit(f"unknown profile {args.profile}")
        print("คำสั่ง: /silence  /hangup  /interrupt <n> ข้อความ")
        engine = build_engine(profile.campaign, profile.case, args.name)
        try:
            if args.mic:
                from kpi_voicebot.agent import make_dialogue
                from kpi_voicebot.config import get_settings
                from kpi_voicebot.mic import MicChat

                mode = get_settings().conversation_mode

                def mic(i: AsyncInterpreter | None, r: Responder | None) -> Awaitable[None]:
                    talk, dialogue = make_dialogue(engine, i, r, mode)
                    return MicChat(talk, dialogue, args.headphones, args.aec).run()

                asyncio.run(_with_llm(args.llm, mic))
            else:
                from kpi_voicebot.agent import make_dialogue
                from kpi_voicebot.config import get_settings

                mode = get_settings().conversation_mode
                voice = VoicePlayer() if args.voice else None
                asyncio.run(_with_llm(args.llm, lambda i, r: _chat(*make_dialogue(engine, i, r, mode), voice)))
        except KeyboardInterrupt, EOFError:
            print("\n   · จบการทดสอบ (customer hung up)")
            engine.handle_hangup()
    print(_summary(engine))
