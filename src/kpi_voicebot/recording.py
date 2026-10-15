"""Call recording: LiveKit egress records the call room (bot and customer mixed) as Opus audio and
uploads it to Tencent COS through COS's S3-compatible API (approved by the PM on 8 Oct 2026).

Recording starts when the customer answers; the opening tells them the call is recorded. If the
customer objects to the recording, the call's file is deleted, as its transcript is. Deleting is one
signed S3 request (AWS Signature Version 4, which COS accepts), so no S3 SDK is needed.
"""

import datetime as dt
import hashlib
import hmac
import logging
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from livekit import api

from kpi_voicebot.config import Settings

log = logging.getLogger("kpi.recording")


@dataclass(frozen=True)
class Recording:
    egress_id: str
    key: str  # object key in the COS bucket


def object_key(settings: Settings, call_id: str) -> str:
    return f"{settings.cos_prefix.rstrip('/')}/{call_id}.ogg"


def cos_endpoint(settings: Settings) -> str:
    return f"https://cos.{settings.cos_region}.myqcloud.com"


async def start(lk: api.LiveKitAPI, settings: Settings, room_name: str, key: str) -> Recording:
    assert settings.cos_secret_id and settings.cos_secret_key and settings.cos_bucket and settings.cos_region
    upload = api.S3Upload(
        access_key=settings.cos_secret_id.get_secret_value(),
        secret=settings.cos_secret_key.get_secret_value(),
        region=settings.cos_region,
        endpoint=cos_endpoint(settings),
        bucket=settings.cos_bucket,
    )
    output = api.EncodedFileOutput(file_type=api.EncodedFileType.OGG, filepath=key, s3=upload)
    info = await lk.egress.start_room_composite_egress(
        api.RoomCompositeEgressRequest(room_name=room_name, audio_only=True, file_outputs=[output])
    )
    return Recording(info.egress_id, key)


async def stop(lk: api.LiveKitAPI, recording: Recording) -> None:
    """Finish the file now (it is uploaded when the egress ends); a room that already closed ended it."""
    try:
        await lk.egress.stop_egress(api.StopEgressRequest(egress_id=recording.egress_id))
    except api.TwirpError as exc:
        log.info("egress %s already ended (%s)", recording.egress_id, exc.code)


def sign_v4(
    method: str,
    url: httpx.URL,
    headers: dict[str, str],
    payload_sha256: str,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    now: dt.datetime,
) -> str:
    """The Authorization header for a request (AWS Signature Version 4) over exactly `headers`."""
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    lowered = {name.lower(): value.strip() for name, value in headers.items()}
    canonical_headers = "".join(f"{name}:{lowered[name]}\n" for name in sorted(lowered))
    signed = ";".join(sorted(lowered))
    query = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(url.params.multi_items()))
    request = "\n".join(
        [method, quote(url.path or "/", safe="/-_.~"), query, canonical_headers, signed, payload_sha256]
    )
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(request.encode()).hexdigest()])
    key = f"AWS4{secret_key}".encode()
    for part in (day, region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={signature}"


async def delete(settings: Settings, key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
    """Delete a recording from the bucket (the customer objected to being recorded)."""
    assert settings.cos_secret_id and settings.cos_secret_key and settings.cos_bucket and settings.cos_region
    host = f"{settings.cos_bucket}.cos.{settings.cos_region}.myqcloud.com"
    url = httpx.URL(f"https://{host}/{quote(key, safe='/')}")
    now = dt.datetime.now(dt.UTC)
    empty = hashlib.sha256(b"").hexdigest()
    headers = {"host": host, "x-amz-content-sha256": empty, "x-amz-date": now.strftime("%Y%m%dT%H%M%SZ")}
    headers["Authorization"] = sign_v4(
        "DELETE",
        url,
        headers,
        empty,
        access_key=settings.cos_secret_id.get_secret_value(),
        secret_key=settings.cos_secret_key.get_secret_value(),
        region=settings.cos_region,
        service="s3",
        now=now,
    )
    async with httpx.AsyncClient(timeout=10, transport=transport) as client:
        res = await client.delete(url, headers=headers)
    if res.status_code not in (200, 204, 404):
        raise RuntimeError(f"COS refused to delete the recording (HTTP {res.status_code})")
