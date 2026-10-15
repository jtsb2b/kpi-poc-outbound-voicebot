"""Operator API (Swagger at /docs). All /api routes need the operator bearer token."""

import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from kpi_voicebot.campaigns import load_campaign, load_profiles
from kpi_voicebot.config import Settings, get_settings
from kpi_voicebot.excel_io import ImportError_, export_calls, parse_workbook, template_workbook
from kpi_voicebot.models import ACTIVE_LIFECYCLE, CampaignId, Lifecycle
from kpi_voicebot.phone import InvalidPhone, parse_destination
from kpi_voicebot.service import CallRequest, RequestRejected, build_call_document, within_calling_hours
from kpi_voicebot.simulator import load_scenarios
from kpi_voicebot.store import ActiveCallExists, Conflict, Store, as_utc, fingerprint

log = logging.getLogger("kpi.api")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
_PRIVATE_FIELDS = {"idempotency_key", "fingerprint", "active_lock", "worker_id", "lease_until", "script", "expires_at"}


def _json(value: Any) -> Any:
    if isinstance(value, datetime):
        return as_utc(value).isoformat()
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json(v) for v in value]
    return value


def public_call(doc: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    out = {k: v for k, v in doc.items() if k not in _PRIVATE_FIELDS and k != "_id"}
    out["call_id"] = doc["_id"]
    out["active"] = doc.get("lifecycle") in {s.value for s in ACTIVE_LIFECYCLE} | {Lifecycle.QUEUED.value}
    if not detail:
        out.pop("case", None)
    return _json(out)  # type: ignore[no-any-return]


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client: AsyncMongoClient[dict[str, Any]] | None = None
        if store is None:
            client = AsyncMongoClient(
                settings.mongo_uri.get_secret_value(), tz_aware=True, serverSelectionTimeoutMS=3000
            )
            app.state.store = Store(client[settings.mongo_db], settings.retention_days)
        else:
            app.state.store = store
        try:
            await app.state.store.ensure_indexes()
        except PyMongoError:
            log.warning("MongoDB unavailable at startup; /ready will report 503 until it is reachable")
        yield
        if client is not None:
            await client.close()

    app = FastAPI(title="KPI Outbound Voicebot POC", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    bearer = HTTPBearer(auto_error=False)

    def get_store(request: Request) -> Store:
        return request.app.state.store  # type: ignore[no-any-return]

    def require_operator(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
        expected = settings.operator_token.get_secret_value()
        if creds is None or not hmac.compare_digest(creds.credentials.encode(), expected.encode()):
            raise HTTPException(401, "ต้องเข้าสู่ระบบ", headers={"WWW-Authenticate": "Bearer"})

    StoreDep = Annotated[Store, Depends(get_store)]
    auth = [Depends(require_operator)]

    @app.exception_handler(RequestRejected)
    async def _rejected(_: Request, exc: RequestRejected) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["system"])
    async def ready(store: StoreDep) -> JSONResponse:
        try:
            await store.ping()
        except PyMongoError:
            return JSONResponse({"status": "unavailable", "mongo": False}, status_code=503)
        return JSONResponse({"status": "ready", "mongo": True})

    @app.get("/api/v1/system/status", tags=["system"], dependencies=auth)
    async def system_status(store: StoreDep) -> dict[str, Any]:
        active = await store.active_call()
        return {
            "live_calls_enabled": settings.live_calls_enabled,
            "telephony_ready": settings.live_calls_enabled and not settings.livekit_missing(),
            "caller_id": settings.public_caller_id,
            "interpreter": settings.interpreter,
            "within_calling_hours": within_calling_hours(settings),
            "calling_hours": f"{settings.calling_start_hour:02d}:00-{settings.calling_end_hour:02d}:00",
            "timezone": settings.timezone,
            "retention_days": settings.retention_days,
            "active_call_id": active["_id"] if active else None,
        }

    @app.get("/api/v1/campaigns", tags=["campaigns"], dependencies=auth)
    async def campaigns() -> list[dict[str, Any]]:
        out = []
        for cid in CampaignId:
            c = load_campaign(cid)
            out.append(
                {
                    "id": cid.value,
                    "title": c.title,
                    "version": c.version,
                    "snapshot": c.snapshot_id,
                    "persona_name": c.persona_name,
                    "pending_approval": c.pending_approval(),
                    "profiles": [
                        {"profile_id": p.profile_id, "label": p.label, "case": p.case}
                        for p in load_profiles()
                        if p.campaign == cid
                    ],
                    "scenarios": [
                        {"id": s.id, "label": s.label, "customer": s.customer, "profile": s.profile}
                        for s in load_scenarios()
                        if s.campaign == cid
                    ],
                }
            )
        return _json(out)  # type: ignore[no-any-return]

    @app.post("/api/v1/phone/validate", tags=["calls"], dependencies=auth)
    async def validate_phone(body: dict[str, str]) -> dict[str, Any]:
        try:
            d = parse_destination(body.get("phone", ""), allow_extensions=settings.allow_internal_extensions)
        except InvalidPhone as exc:
            return {"valid": False, "message": str(exc)}
        return {
            "valid": True,
            "dialable": d.dialable,
            "kind": d.kind,
            "e164": d.e164,
            "display": d.display,
            "sip_destination": d.sip_destination,
            "message": d.reason,
        }

    @app.post("/api/v1/calls", tags=["calls"], dependencies=auth, status_code=201)
    async def create_call(
        request: CallRequest,
        store: StoreDep,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    ) -> JSONResponse:
        doc = await build_call_document(request, settings, store)
        try:
            call, created = await store.create_call(doc, idempotency_key, fingerprint(request.model_dump(mode="json")))
        except Conflict:
            raise HTTPException(409, "คำขอนี้ถูกส่งไปแล้วด้วยข้อมูลที่ต่างกัน กรุณาลองใหม่") from None
        except ActiveCallExists:
            raise HTTPException(409, "มีสายที่กำลังดำเนินการอยู่ กรุณารอให้จบหรือยกเลิกก่อน") from None
        if created:
            await store.add_event(call["_id"], "queued", {"mode": call["mode"]})
        return JSONResponse(public_call(call, detail=True), status_code=201 if created else 200)

    @app.get("/api/v1/calls", tags=["calls"], dependencies=auth)
    async def list_calls(
        store: StoreDep,
        campaign: CampaignId | None = None,
        outcome: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> list[dict[str, Any]]:
        docs = await store.list_calls(campaign=campaign.value if campaign else None, outcome=outcome, limit=limit)
        return [public_call(d) for d in docs]

    @app.get("/api/v1/calls/{call_id}", tags=["calls"], dependencies=auth)
    async def get_call(call_id: str, store: StoreDep) -> dict[str, Any]:
        doc = await store.get_call(call_id)
        if doc is None:
            raise HTTPException(404, "ไม่พบสาย")
        out = public_call(doc, detail=True)
        out["transcript"] = _json(
            [
                {k: v for k, v in t.items() if k not in {"_id", "call_id", "expires_at"}}
                for t in await store.transcript(call_id)
            ]
        )
        out["events"] = _json(
            [
                {k: v for k, v in e.items() if k not in {"_id", "call_id", "expires_at"}}
                for e in await store.call_events(call_id)
            ]
        )
        return out

    @app.post("/api/v1/calls/{call_id}/cancel", tags=["calls"], dependencies=auth)
    async def cancel_call(call_id: str, store: StoreDep) -> dict[str, Any]:
        doc = await store.request_cancel(call_id)
        if doc is None:
            raise HTTPException(404, "ไม่พบสาย")
        return public_call(doc)

    @app.delete("/api/v1/calls/{call_id}", tags=["calls"], dependencies=auth, status_code=204)
    async def delete_call(call_id: str, store: StoreDep) -> Response:
        if not await store.delete_call(call_id):
            raise HTTPException(409, "ลบได้เฉพาะสายที่จบแล้ว")
        return Response(status_code=204)

    @app.post("/api/v1/imports", tags=["excel"], dependencies=auth)
    async def upload_import(
        store: StoreDep,
        campaign: Annotated[CampaignId, Form()],
        file: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "ไฟล์ใหญ่เกิน 2 MB")
        try:
            rows = parse_workbook(campaign, content)
        except ImportError_ as exc:
            raise HTTPException(422, str(exc)) from None
        doc = await store.save_import(
            {
                "campaign": campaign.value,
                "filename": file.filename,
                "rows": rows,
                "valid_count": sum(1 for r in rows if r["record"] is not None),
            }
        )
        payload = {
            "import_id": doc["_id"],
            "campaign": campaign.value,
            "filename": file.filename,
            "rows": rows,
            "valid_count": doc["valid_count"],
        }
        return payload

    @app.get("/api/v1/templates/{campaign}.xlsx", tags=["excel"], dependencies=auth)
    async def template(campaign: CampaignId) -> Response:
        return _xlsx(template_workbook(campaign), f"kpi_{campaign.value}_template.xlsx")

    @app.get("/api/v1/exports/calls.xlsx", tags=["excel"], dependencies=auth)
    async def export(
        store: StoreDep,
        call_id: Annotated[list[str] | None, Query()] = None,
        campaign: CampaignId | None = None,
        outcome: str | None = None,
    ) -> Response:
        docs = await store.list_calls(
            campaign=campaign.value if campaign else None, outcome=outcome, call_ids=call_id, limit=500
        )
        transcripts = await store.transcripts([d["_id"] for d in docs])
        name = f"kpi_call_{call_id[0][:8]}.xlsx" if call_id and len(call_id) == 1 else "kpi_calls.xlsx"
        return _xlsx(export_calls(docs, transcripts, settings.timezone), name)

    return app


def _xlsx(content: bytes, filename: str) -> Response:
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.api_host, port=settings.api_port)
