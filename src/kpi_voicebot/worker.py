"""Call worker: claims one queued call at a time and runs it.

Simulated calls run through the text simulator; live calls dial out over LiveKit SIP
(`telephony.py`). Both share the lifecycle and the single origination guard
(`mark_dial_attempted`): a call is dialled at most once and never redialled automatically.
"""

import asyncio
import contextlib
import logging
import signal
import socket
import uuid
from typing import Any

from pymongo import AsyncMongoClient

from kpi_voicebot.agent import make_dialogue
from kpi_voicebot.config import Settings, get_settings
from kpi_voicebot.dialogue import AsyncInterpreter
from kpi_voicebot.models import CallMode, CampaignId, DialResult, Directive, Lifecycle, Outcome
from kpi_voicebot.recording import delete as delete_recording
from kpi_voicebot.recording import object_key
from kpi_voicebot.responder import Responder
from kpi_voicebot.simulator import Canceled, build_engine, run_script
from kpi_voicebot.store import Store, utcnow

log = logging.getLogger("kpi.worker")


def scrub_customer_text(result: dict[str, Any]) -> dict[str, Any]:
    """The customer objected to text capture: keep statuses and scores, drop their words."""
    for f in result.get("policy_fields", []):
        f["customer_statement"] = None
    for a in result.get("survey_answers", []):
        a["raw_utterance"] = None
        a["feedback_raw"] = None
    for t in result.get("tasks", []):
        t["detail_raw"] = None
    result["final_comment_raw"] = None
    if result.get("callback"):
        result["callback"]["preferred_time_text"] = None
    return result


class StoreSink:
    def __init__(self, store: Store, call_id: str, engine_result: Any) -> None:
        self.store = store
        self.call_id = call_id
        self.result = engine_result
        self.seq = 0

    async def bot(self, directive: Directive, spoken_segments: int, complete: bool) -> None:
        self.seq += 1
        spoken = " ".join(s.text for s in directive.segments[:spoken_segments])
        await self.store.add_turn(
            self.call_id,
            {
                "seq": self.seq,
                "speaker": "bot",
                "at": utcnow(),
                "text": spoken,
                "generated_text": directive.text,
                "spoken_complete": complete,
                "interrupted": not complete,
                "directive_key": directive.key,
            },
        )
        await self.store.save_progress(self.call_id, self.result.model_dump(mode="json"))

    async def customer(self, text: str) -> None:
        self.seq += 1
        await self.store.add_turn(self.call_id, {"seq": self.seq, "speaker": "customer", "at": utcnow(), "text": text})

    async def event(self, kind: str, data: dict[str, Any] | None = None) -> None:
        await self.store.add_event(self.call_id, kind, data)


class Worker:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        worker_id: str | None = None,
        interpreter: AsyncInterpreter | None = None,
        responder: Responder | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        self.interpreter = interpreter
        self.responder = responder
        self.delay = settings.sim_turn_delay_ms / 1000
        self.phone_factory: Any = None  # tests replace the LiveKit phone with a fake
        self.delete_recording = delete_recording

    async def process_once(self) -> bool:
        await self.store.reconcile_expired()
        call = await self.store.claim_next(self.worker_id, self.settings.lease_seconds)
        if call is None:
            return False
        heartbeat = asyncio.create_task(self._heartbeat(call["_id"]))
        try:
            if call.get("mode") == CallMode.LIVE.value:
                await self._run_live(call)
            else:
                await self._run_simulation(call)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
        return True

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        """Claim and run calls until `stop` is set; a call in progress is always finished first."""
        await self.store.ensure_indexes()
        log.info("worker %s started", self.worker_id)
        stop = stop or asyncio.Event()
        while not stop.is_set():
            try:
                if not await self.process_once():
                    await asyncio.sleep(self.settings.worker_poll_seconds)
            except Exception:
                log.exception("worker loop error")
                await asyncio.sleep(2)
        log.info("worker %s stopped", self.worker_id)

    async def _heartbeat(self, call_id: str) -> None:
        while True:
            await asyncio.sleep(max(1, self.settings.lease_seconds // 3))
            await self.store.heartbeat(call_id, self.worker_id, self.settings.lease_seconds)

    async def _run_simulation(self, call: dict[str, Any]) -> None:
        call_id = call["_id"]
        store = self.store
        await store.add_event(call_id, "dispatched", {"mode": "simulation", "worker": self.worker_id})
        if not await store.mark_dial_attempted(call_id, self.worker_id):
            await store.finish(
                call_id,
                outcome=Outcome.CANCELED,
                dial_result=DialResult.CANCELED,
                result=None,
                end_reason="canceled_before_dial",
            )
            return
        await store.add_event(call_id, "dialing", {"simulated_sip_destination": call["phone"].get("sip_destination")})
        await asyncio.sleep(self.delay)
        await store.set_lifecycle(call_id, Lifecycle.RINGING)
        await store.add_event(call_id, "ringing")
        await asyncio.sleep(self.delay)
        if await store.is_cancel_requested(call_id):
            await store.finish(
                call_id,
                outcome=Outcome.CANCELED,
                dial_result=DialResult.CANCELED,
                result=None,
                end_reason="operator_canceled",
            )
            await store.add_event(call_id, "canceled", {"while": "ringing"})
            return
        await store.set_lifecycle(call_id, Lifecycle.IN_CONVERSATION, dial_result=DialResult.ANSWERED.value)
        await store.add_event(call_id, "answered")

        engine = build_engine(CampaignId(call["campaign"]), call["case"], call["target_name"])
        sink = StoreSink(store, call_id, engine.result)
        try:
            await run_script(
                engine,
                call["script"],
                sink,
                delay_seconds=self.delay,
                is_canceled=lambda: store.is_cancel_requested(call_id),
                interpreter=self.interpreter,
                responder=self.responder,
            )
        except Canceled:
            await store.finish(
                call_id,
                outcome=Outcome.CANCELED,
                dial_result=DialResult.ANSWERED,
                result=engine.result.model_dump(mode="json"),
                end_reason="operator_canceled",
            )
            await store.add_event(call_id, "canceled", {"while": "in_conversation"})
            return
        except Exception as exc:
            log.exception("simulation failed for %s", call_id)
            await store.finish(
                call_id,
                outcome=Outcome.TECHNICAL_FAILURE,
                dial_result=DialResult.ANSWERED,
                result=engine.result.model_dump(mode="json"),
                end_reason=type(exc).__name__,
            )
            await store.add_event(call_id, "technical_failure", {"error": type(exc).__name__})
            return

        await self._finish_conversation(call_id, engine)

    async def _finish_conversation(self, call_id: str, engine: Any) -> None:
        store = self.store
        await store.set_lifecycle(call_id, Lifecycle.ENDING)
        outcome = engine.outcome or Outcome.TECHNICAL_FAILURE
        result = engine.result.model_dump(mode="json")
        if outcome is Outcome.NOTICE_OBJECTION:
            result = scrub_customer_text(result)
        await store.finish(
            call_id,
            outcome=outcome,
            dial_result=DialResult.ANSWERED,
            result=result,
            end_reason=engine.result.end_reason,
        )
        if outcome is Outcome.NOTICE_OBJECTION:
            await store.discard_transcript(call_id)
            await store.add_event(call_id, "transcript_discarded", {"reason": "notice_objection"})
        await store.add_event(call_id, "ended", {"outcome": outcome.value})

    async def _run_live(self, call: dict[str, Any]) -> None:
        """A real phone call over LiveKit SIP: dialled once, whatever happens."""
        from kpi_voicebot.telephony import PhoneCall

        call_id = call["_id"]
        store = self.store
        await store.add_event(call_id, "dispatched", {"mode": "live", "worker": self.worker_id})
        missing = self.settings.livekit_missing()
        if not self.settings.live_calls_enabled or missing:
            reason = "live_calls_disabled" if not self.settings.live_calls_enabled else "telephony_not_configured"
            await store.finish(
                call_id,
                outcome=Outcome.TECHNICAL_FAILURE,
                dial_result=None,
                result=None,
                end_reason=reason,
            )
            await store.add_event(call_id, "not_dialed", {"missing": missing})
            return
        if not await store.mark_dial_attempted(call_id, self.worker_id):
            await store.finish(
                call_id,
                outcome=Outcome.CANCELED,
                dial_result=DialResult.CANCELED,
                result=None,
                end_reason="canceled_before_dial",
            )
            return
        engine = build_engine(CampaignId(call["campaign"]), call["case"], call["target_name"])
        sink = StoreSink(store, call_id, engine.result)
        destination = call["phone"]["sip_destination"]
        await store.add_event(call_id, "dialing", {"trunk": "outbound", "from": self.settings.sip_caller_number})

        async def ringing() -> None:
            await store.set_lifecycle(call_id, Lifecycle.RINGING)
            await store.add_event(call_id, "ringing")

        async def answered() -> None:
            await store.set_lifecycle(call_id, Lifecycle.IN_CONVERSATION, dial_result=DialResult.ANSWERED.value)
            await store.add_event(call_id, "answered")

        # The LLM-led agent when an LLM is configured (CONVERSATION_MODE=agent), otherwise scripted.
        talk, dialogue = make_dialogue(engine, self.interpreter, self.responder, self.settings.conversation_mode)
        make_phone = self.phone_factory or PhoneCall
        phone = make_phone(
            self.settings,
            talk,
            dialogue,
            room_name=f"{self.settings.livekit_room_prefix}{call_id}",
            sip_call_to=destination,
            recording_key=object_key(self.settings, call_id),
            sink=sink,
            is_canceled=lambda: store.is_cancel_requested(call_id),
            on_ringing=ringing,
            on_answered=answered,
        )
        answered_at_all = False
        try:
            end = await phone.run()
            answered_at_all = end.answered
        except Canceled:
            current = await store.get_call(call_id)
            was_answered = bool(current and current.get("answered_at"))
            await store.finish(
                call_id,
                outcome=Outcome.CANCELED,
                dial_result=DialResult.ANSWERED if was_answered else DialResult.CANCELED,
                result=engine.result.model_dump(mode="json") if was_answered else None,
                end_reason="operator_canceled",
            )
            await store.add_event(call_id, "canceled", {"while": "in_conversation" if was_answered else "ringing"})
            return
        except Exception as exc:
            log.exception("live call failed for %s", call_id)
            current = await store.get_call(call_id)
            was_answered = answered_at_all or bool(current and current.get("answered_at"))
            await store.finish(
                call_id,
                outcome=Outcome.TECHNICAL_FAILURE,
                dial_result=DialResult.ANSWERED if was_answered else DialResult.TECHNICAL_FAILURE,
                result=engine.result.model_dump(mode="json") if was_answered else None,
                end_reason=type(exc).__name__,
            )
            await store.add_event(call_id, "technical_failure", {"error": type(exc).__name__})
            return
        if not end.answered:
            reached = end.dial_result is not DialResult.TECHNICAL_FAILURE
            await store.finish(
                call_id,
                outcome=Outcome.NOT_REACHED if reached else Outcome.TECHNICAL_FAILURE,
                dial_result=end.dial_result,
                result=None,
                end_reason=end.end_reason,
            )
            await store.add_event(
                call_id, "dial_failed", {"dial_result": end.dial_result.value, "sip_status": end.sip_status}
            )
            return
        if end.timings:
            await store.add_event(call_id, "latency", {"reply_ready_s": [round(t, 2) for t in end.timings]})
        await self._keep_or_discard_recording(call_id, end.recording_key, talk.outcome)
        await self._finish_conversation(call_id, talk)

    async def _keep_or_discard_recording(self, call_id: str, key: str | None, outcome: Outcome | None) -> None:
        """The call's audio stays in COS, unless the customer objected to being recorded."""
        if key is None:
            return
        if outcome is not Outcome.NOTICE_OBJECTION:
            await self.store.set_recording(call_id, {"key": key, "status": "stored"})
            return
        try:
            await self.delete_recording(self.settings, key)
        except Exception as exc:  # the transcript is still discarded; the file needs a manual delete
            log.exception("could not delete the recording of %s", call_id)
            await self.store.set_recording(call_id, {"key": key, "status": "delete_failed"})
            await self.store.add_event(call_id, "recording_delete_failed", {"error": type(exc).__name__})
            return
        await self.store.set_recording(call_id, {"key": None, "status": "discarded"})
        await self.store.add_event(call_id, "recording_discarded", {"reason": "notice_objection"})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    if settings.live_calls_enabled:
        from kpi_voicebot.telephony import quiet_released_handles

        quiet_released_handles()
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.mongo_uri.get_secret_value(), tz_aware=True)
    store = Store(client[settings.mongo_db], settings.retention_days)
    interpreter: AsyncInterpreter | None = None
    responder: Responder | None = None
    if settings.interpreter == "llm":
        from kpi_voicebot.llm import LLMClient
        from kpi_voicebot.llm_interpreter import LLMInterpreter

        llm_client = LLMClient(settings)
        interpreter = LLMInterpreter(llm_client)
        responder = Responder(llm_client)
        log.info(
            "self-hosted LLM %s: reads replies and words the bot's turns (rule safety layer on)", settings.llm_model
        )
    else:
        log.info("reply interpretation: rules only, scripted wording")
    asyncio.run(_serve(Worker(store, settings, interpreter=interpreter, responder=responder)))


async def _serve(worker: Worker) -> None:
    """In a container the worker is process 1, which ignores SIGTERM by default: handle it, stop
    claiming new calls and let a call in progress finish (compose allows two minutes)."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await worker.run_forever(stop)
