"""One call's turn loop: understand the reply, let the engine decide, say it naturally.

Shared by the simulator and the worker. While the bot is speaking, the most likely next
turn (the customer simply acknowledging with "ครับ") is prepared in advance, both its
wording and, in voice mode, its audio, so the common path has no model wait at all.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from kpi_voicebot.engine import BaseEngine, InterpretContext
from kpi_voicebot.models import Directive
from kpi_voicebot.responder import Responder
from kpi_voicebot.thai_parse import Signals, normalize, read_signals, strip_particles

LIKELY_REPLY = "ครับ"
# Where the usual answer is not "ครับ": "anything else?" is mostly answered "no".
LIKELY_BY_AWAITING = {"questions": "ไม่มีครับ"}


def likely_reply(awaiting: str | None) -> str:
    return LIKELY_BY_AWAITING.get(awaiting or "", LIKELY_REPLY)


class AsyncInterpreter(Protocol):
    last_metrics: dict[str, Any]

    async def interpret(self, text: str, context: InterpretContext) -> Signals: ...


def plain_acknowledgement(text: str) -> bool:
    signals = read_signals(text)
    bare = strip_particles(normalize(text)).replace(" ", "")
    return signals.backchannel or (signals.affirm and len(bare) <= 4)


def _same_no(text: str, likely: str) -> bool:
    """ "ไม่มีนะครับ" / "ไม่มีแล้วครับ" when "ไม่มีครับ" was expected."""
    a, b = read_signals(text), read_signals(likely)
    return (a.no_comment or (a.negative and not a.question)) and (b.no_comment or b.negative)


@dataclass
class Prepared:
    draft_key: str
    draft_text: str
    directive: Directive


@dataclass
class Dialogue:
    engine: BaseEngine
    interpreter: AsyncInterpreter | None = None
    responder: Responder | None = None
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _prepared: asyncio.Task[Prepared | None] | None = None
    _prepared_for: str = LIKELY_REPLY

    def start(self) -> Directive:
        return self.engine.start()

    async def reply(self, text: str) -> Directive:
        signals = None
        if self.interpreter is not None:
            signals = await self.interpreter.interpret(text, self.engine.context())
            kind = "llm_fallback_rules" if "fallback" in self.interpreter.last_metrics else "llm_interpretation"
            self.events.append((kind, dict(self.interpreter.last_metrics)))
        # A plain "ครับ" almost always leads to the prepared turn: worth waiting for it. Any other
        # reply uses it only if it is already done and turns out to lead to the same turn.
        task = self._prepared
        expected = plain_acknowledgement(text) or (
            self._prepared_for != LIKELY_REPLY and _same_no(text, self._prepared_for)
        )
        prepared = await self._take_prepared() if expected or (task and task.done()) else None
        self._drop_prepared()
        draft = self.engine.handle(text, signals)
        if self.responder is None:
            return draft
        if prepared and prepared.draft_key == draft.key and prepared.draft_text == draft.text:
            self.engine.adopt(prepared.directive)
            self.events.append(("reply_prepared", {}))
            return prepared.directive
        result = await self.responder.respond(self.engine, draft, text)
        if result.generated:
            self.engine.adopt(result.directive)
            if result.answered_from_facts:
                self.engine.withdraw_follow_up(text)
        self.events.append(
            ("llm_reply" if result.generated else "scripted_reply", {"reason": result.reason, **(result.metrics or {})})
        )
        return result.directive

    def prepare_next(self) -> None:
        """Start wording the turn that most likely follows (a plain "ครับ", or "ไม่มีครับ" to "anything
        else?"), while the current turn is spoken."""
        self._drop_prepared()
        engine = self.engine
        if self.responder is None or engine.state.finished or engine.state.awaiting is None:
            return
        self._prepared_for = likely_reply(engine.state.awaiting)
        self._prepared = asyncio.ensure_future(self._prepare(engine.fork()))

    async def _prepare(self, fork: BaseEngine) -> Prepared | None:
        assert self.responder is not None
        said = likely_reply(fork.state.awaiting)
        draft = fork.handle(said, read_signals(said))
        result = await self.responder.respond(fork, draft, said)
        return Prepared(draft.key, draft.text, result.directive) if result.generated else None

    async def _take_prepared(self) -> Prepared | None:
        task, self._prepared = self._prepared, None
        if task is None:
            return None
        try:
            return await task
        except Exception:  # a failed preparation just means wording the turn now
            return None

    def _drop_prepared(self) -> None:
        if self._prepared is not None:
            self._prepared.cancel()
            self._prepared = None

    @property
    def prepared(self) -> asyncio.Task[Prepared | None] | None:
        return self._prepared
