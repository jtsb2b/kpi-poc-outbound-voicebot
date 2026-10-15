"""MongoDB persistence: calls, transcript turns, events and Excel imports.

One call at a time is enforced by the database, not by a check-then-insert: every
queued or active call carries `active_lock = "global"` under a unique sparse index, so
a second concurrent call cannot be inserted. The lock is removed when the call ends.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from kpi_voicebot.models import ACTIVE_LIFECYCLE, DialResult, Lifecycle, Outcome

ACTIVE_LOCK = "global"


class Conflict(Exception):
    """Idempotency key reused with a different request body."""


class ActiveCallExists(Exception):
    """Another call is queued or in progress."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def fingerprint(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class Store:
    def __init__(self, db: Any, retention_days: int = 30) -> None:
        self.db = db
        self.calls = db["calls"]
        self.turns = db["transcript_turns"]
        self.events = db["call_events"]
        self.imports = db["imports"]
        self.retention = timedelta(days=retention_days)

    async def ensure_indexes(self) -> None:
        await self.calls.create_index("idempotency_key", unique=True, sparse=True)
        await self.calls.create_index("active_lock", unique=True, sparse=True)
        await self.calls.create_index([("lifecycle", ASCENDING), ("created_at", ASCENDING)])
        await self.calls.create_index([("created_at", DESCENDING)])
        for coll in (self.calls, self.turns, self.events, self.imports):
            await coll.create_index("expires_at", expireAfterSeconds=0)
        await self.turns.create_index([("call_id", ASCENDING), ("seq", ASCENDING)])
        await self.events.create_index([("call_id", ASCENDING), ("at", ASCENDING)])

    async def ping(self) -> bool:
        await self.db.command("ping")
        return True

    # ---- calls ----

    async def create_call(
        self, doc: dict[str, Any], idempotency_key: str, body_fingerprint: str
    ) -> tuple[dict[str, Any], bool]:
        existing = await self.calls.find_one({"idempotency_key": idempotency_key})
        if existing is not None:
            if existing["fingerprint"] != body_fingerprint:
                raise Conflict
            return existing, False
        now = utcnow()
        doc = {
            **doc,
            "_id": uuid.uuid4().hex,
            "idempotency_key": idempotency_key,
            "fingerprint": body_fingerprint,
            "lifecycle": Lifecycle.QUEUED.value,
            "active_lock": ACTIVE_LOCK,
            "cancel_requested": False,
            "dial_attempted": False,
            "dial_result": None,
            "outcome": None,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + self.retention,
        }
        try:
            await self.calls.insert_one(doc)
        except DuplicateKeyError:
            existing = await self.calls.find_one({"idempotency_key": idempotency_key})
            if existing is not None:
                if existing["fingerprint"] != body_fingerprint:
                    raise Conflict from None
                return existing, False
            raise ActiveCallExists from None
        return doc, True

    async def get_call(self, call_id: str) -> dict[str, Any] | None:
        doc: dict[str, Any] | None = await self.calls.find_one({"_id": call_id})
        return doc

    async def active_call(self) -> dict[str, Any] | None:
        doc: dict[str, Any] | None = await self.calls.find_one({"active_lock": ACTIVE_LOCK})
        return doc

    async def list_calls(
        self,
        *,
        campaign: str | None = None,
        outcome: str | None = None,
        call_ids: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if campaign:
            query["campaign"] = campaign
        if outcome:
            query["outcome"] = outcome
        if call_ids is not None:
            query["_id"] = {"$in": call_ids}
        cursor = self.calls.find(query).sort("created_at", DESCENDING).limit(limit)
        docs: list[dict[str, Any]] = await cursor.to_list(length=limit)
        return docs

    async def claim_next(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        queued = await self.calls.find_one({"lifecycle": Lifecycle.QUEUED.value}, sort=[("created_at", ASCENDING)])
        if queued is None:
            return None
        now = utcnow()
        doc: dict[str, Any] | None = await self.calls.find_one_and_update(
            {"_id": queued["_id"], "lifecycle": Lifecycle.QUEUED.value, "cancel_requested": False},
            {
                "$set": {
                    "lifecycle": Lifecycle.DISPATCHING.value,
                    "worker_id": worker_id,
                    "lease_until": now + timedelta(seconds=lease_seconds),
                    "dispatched_at": now,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return doc

    async def heartbeat(self, call_id: str, worker_id: str, lease_seconds: int) -> bool:
        res = await self.calls.update_one(
            {"_id": call_id, "worker_id": worker_id, "active_lock": ACTIVE_LOCK},
            {"$set": {"lease_until": utcnow() + timedelta(seconds=lease_seconds)}},
        )
        return bool(res.matched_count)

    async def mark_dial_attempted(self, call_id: str, worker_id: str) -> bool:
        """One-way flag: a call is originated at most once, whatever happens afterwards."""
        res = await self.calls.update_one(
            {"_id": call_id, "worker_id": worker_id, "dial_attempted": False, "cancel_requested": False},
            {"$set": {"dial_attempted": True, "lifecycle": Lifecycle.DIALING.value, "updated_at": utcnow()}},
        )
        return bool(res.matched_count)

    async def set_lifecycle(self, call_id: str, lifecycle: Lifecycle, **fields: Any) -> None:
        now = utcnow()
        update: dict[str, Any] = {"lifecycle": lifecycle.value, "updated_at": now, **fields}
        if lifecycle is Lifecycle.IN_CONVERSATION:
            update["answered_at"] = now
        await self.calls.update_one({"_id": call_id, "active_lock": ACTIVE_LOCK}, {"$set": update})

    async def set_recording(self, call_id: str, recording: dict[str, Any]) -> None:
        await self.calls.update_one({"_id": call_id}, {"$set": {"recording": recording, "updated_at": utcnow()}})

    async def save_progress(self, call_id: str, result: dict[str, Any]) -> None:
        await self.calls.update_one({"_id": call_id}, {"$set": {"result": result, "updated_at": utcnow()}})

    async def finish(
        self,
        call_id: str,
        *,
        outcome: Outcome,
        dial_result: DialResult | None,
        result: dict[str, Any] | None,
        end_reason: str | None,
    ) -> None:
        now = utcnow()
        update: dict[str, Any] = {
            "lifecycle": Lifecycle.ENDED.value,
            "outcome": outcome.value,
            "dial_result": dial_result.value if dial_result else None,
            "end_reason": end_reason,
            "ended_at": now,
            "updated_at": now,
        }
        if result is not None:
            update["result"] = result
        await self.calls.update_one(
            {"_id": call_id}, {"$set": update, "$unset": {"active_lock": "", "lease_until": "", "worker_id": ""}}
        )

    async def request_cancel(self, call_id: str) -> dict[str, Any] | None:
        queued = await self.calls.find_one_and_update(
            {"_id": call_id, "lifecycle": Lifecycle.QUEUED.value},
            {"$set": {"cancel_requested": True}},
        )
        if queued is not None:
            await self.finish(
                call_id,
                outcome=Outcome.CANCELED,
                dial_result=DialResult.CANCELED,
                result=None,
                end_reason="operator_canceled",
            )
            await self.add_event(call_id, "canceled", {"while": "queued"})
        else:
            await self.calls.update_one(
                {"_id": call_id, "active_lock": ACTIVE_LOCK}, {"$set": {"cancel_requested": True}}
            )
        return await self.get_call(call_id)

    async def is_cancel_requested(self, call_id: str) -> bool:
        doc = await self.calls.find_one({"_id": call_id}, {"cancel_requested": 1})
        return bool(doc and doc.get("cancel_requested"))

    async def reconcile_expired(self) -> list[str]:
        """Active calls whose worker lease expired are ended, never re-queued or re-dialled."""
        now = utcnow()
        stale = await self.calls.find(
            {"active_lock": ACTIVE_LOCK, "lifecycle": {"$in": [s.value for s in ACTIVE_LIFECYCLE]}}
        ).to_list(length=50)
        ended = []
        for doc in stale:
            lease = doc.get("lease_until")
            if lease is not None and as_utc(lease) > now:
                continue
            answered = doc.get("answered_at") is not None
            await self.finish(
                doc["_id"],
                outcome=Outcome.TECHNICAL_FAILURE,
                dial_result=DialResult.ANSWERED if answered else DialResult.TECHNICAL_FAILURE,
                result=None,
                end_reason="worker_lease_expired",
            )
            await self.add_event(doc["_id"], "reconciled", {"previous_lifecycle": doc["lifecycle"]})
            ended.append(doc["_id"])
        return ended

    async def delete_call(self, call_id: str) -> bool:
        res = await self.calls.delete_one({"_id": call_id, "active_lock": {"$exists": False}})
        if not res.deleted_count:
            return False
        await self.turns.delete_many({"call_id": call_id})
        await self.events.delete_many({"call_id": call_id})
        return True

    # ---- transcript and events ----

    async def add_turn(self, call_id: str, turn: dict[str, Any]) -> None:
        await self.turns.insert_one({**turn, "call_id": call_id, "expires_at": utcnow() + self.retention})

    async def transcript(self, call_id: str) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = (
            await self.turns.find({"call_id": call_id}).sort("seq", ASCENDING).to_list(length=1000)
        )
        return docs

    async def transcripts(self, call_ids: list[str]) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = (
            await self.turns.find({"call_id": {"$in": call_ids}})
            .sort([("call_id", ASCENDING), ("seq", ASCENDING)])
            .to_list(length=20000)
        )
        return docs

    async def discard_transcript(self, call_id: str) -> None:
        await self.turns.delete_many({"call_id": call_id})
        await self.calls.update_one({"_id": call_id}, {"$set": {"transcript_discarded": True}})

    async def add_event(self, call_id: str, kind: str, data: dict[str, Any] | None = None) -> None:
        now = utcnow()
        await self.events.insert_one(
            {"call_id": call_id, "at": now, "type": kind, "data": data or {}, "expires_at": now + self.retention}
        )

    async def call_events(self, call_id: str) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = (
            await self.events.find({"call_id": call_id}).sort("at", ASCENDING).to_list(length=1000)
        )
        return docs

    # ---- imports ----

    async def save_import(self, doc: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        doc = {**doc, "_id": uuid.uuid4().hex, "uploaded_at": now, "expires_at": now + self.retention}
        await self.imports.insert_one(doc)
        return doc

    async def get_import(self, import_id: str) -> dict[str, Any] | None:
        doc: dict[str, Any] | None = await self.imports.find_one({"_id": import_id})
        return doc
