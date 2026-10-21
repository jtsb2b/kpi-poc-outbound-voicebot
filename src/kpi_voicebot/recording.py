"""Call recording to Tencent COS (approved by the PM on 8 Oct 2026), made by the worker itself.

The bot already has both sides of the call: the customer's audio arrives on their track and the bot's
own voice goes out through `RoomOut`. `CallRecorder` lays both on one timeline (the bot's speech where it
was actually played, cut where the customer interrupted it), and at hang-up mixes them, encodes Opus in
OGG with PyAV and uploads the file with one signed S3 PUT (AWS Signature Version 4, which COS accepts),
so no S3 SDK is needed. A customer who declines the recording gets nothing uploaded; the transcript is
kept (PM, 19 Oct 2026).

LiveKit egress did this until 20 Oct 2026, when the LiveKit Cloud project ran out of egress minutes and
the call went unrecorded ("egress minutes exceeded"); recording in the worker costs nothing per minute.
"""

import datetime as dt
import hashlib
import hmac
import io
import logging
import re
import time
from collections.abc import Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
import numpy as np

from kpi_voicebot.config import Settings

log = logging.getLogger("kpi.recording")

RATE = 16_000  # the recording's sample rate: the customer's audio arrives at it; speech needs no more
OPUS_BITRATE = 24_000  # about 180 KB a minute


class CallRecorder:
    """Both sides of one call on a shared timeline, mixed and encoded when the call ends."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self.clock = clock or time.monotonic
        self.started = self.clock()
        self.discarded = False
        self._customer = bytearray()  # continuous, from `_customer_at`
        self._customer_at: float | None = None
        self._bot: list[tuple[float, np.ndarray]] = []  # (when it plays, samples at RATE)

    def customer(self, pcm: bytes) -> None:
        """The customer's audio, 16 kHz mono, as it arrives (a continuous stream)."""
        if self.discarded:
            return
        if self._customer_at is None:
            self._customer_at = self.clock() - len(pcm) / 2 / RATE
        self._customer += pcm

    def bot(self, pcm: bytes, rate: int, plays_at: float) -> None:
        """The bot's voice as handed to the line, with the time it will be heard."""
        if self.discarded or len(pcm) < 2:
            return
        samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
        if rate != RATE:
            n = max(1, round(len(samples) * RATE / rate))
            samples = np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples).astype(np.int16)
        self._bot.append((plays_at, samples))

    def cut_bot(self, at: float) -> None:
        """The customer cut in and the rest of the turn was never played: drop it from the recording."""
        kept = []
        for start, samples in self._bot:
            if start >= at:
                continue
            heard = int((at - start) * RATE)
            kept.append((start, samples[:heard]))
        self._bot = kept

    def discard(self) -> None:
        """The customer declined the recording: keep nothing."""
        self.discarded = True
        self._customer.clear()
        self._bot.clear()

    @property
    def seconds(self) -> float:
        return len(self.mix()) / RATE

    def mix(self) -> np.ndarray:
        def offset(t: float) -> int:
            return max(0, int((t - self.started) * RATE))

        customer = np.frombuffer(bytes(self._customer), dtype=np.int16)
        tracks = [(offset(self._customer_at), customer)] if self._customer_at is not None and len(customer) else []
        tracks += [(offset(t), s) for t, s in self._bot]
        length = max((o + len(s) for o, s in tracks), default=0)
        mixed = np.zeros(length, dtype=np.int32)
        for o, samples in tracks:
            mixed[o : o + len(samples)] += samples
        return np.clip(mixed, -32768, 32767).astype(np.int16)

    def encode(self) -> bytes:
        """Opus in OGG, the format the recordings have always had."""
        import av  # PyAV ships with livekit-agents and bundles libopus

        samples = self.mix()
        out = io.BytesIO()
        with av.open(out, "w", format="ogg") as container:
            stream = container.add_stream("libopus", rate=RATE, layout="mono")
            stream.bit_rate = OPUS_BITRATE
            frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = RATE
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        return out.getvalue()


def object_key(
    settings: Settings, call_id: str, customer_name: str = "", campaign: str = "", now: dt.datetime | None = None
) -> str:
    """One folder per day, one file per call, findable by the customer's name:
    `kpi-voicebot/recordings/19-10-2026/สมชาย_ใจดี_pa_confirmation_141530_dfd63211.ogg`
    (the Bangkok date and time the call was placed; the call id keeps two calls apart)."""
    local = (now or dt.datetime.now(dt.UTC)).astimezone(ZoneInfo(settings.timezone))
    parts = [_safe(customer_name), _safe(campaign), local.strftime("%H%M%S"), _safe(call_id)[:8]]
    name = "_".join(p for p in parts if p)
    return f"{settings.cos_prefix.rstrip('/')}/{local.strftime('%d-%m-%Y')}/{name}.ogg"


def _safe(text: str) -> str:
    """Letters (Thai included) and digits only, words joined by "_": no "/" can make a folder."""
    # Thai vowel and tone marks are not \w to Python: the Thai block is listed so "ใจดี" keeps its ี.
    return "_".join(re.findall(r"(?:[^\W_]|[\u0e00-\u0e7f])+", text))


async def upload(settings: Settings, key: str, data: bytes, transport: httpx.AsyncBaseTransport | None = None) -> None:
    """Put the recording in the bucket (one signed S3 PUT)."""
    assert settings.cos_secret_id and settings.cos_secret_key and settings.cos_bucket and settings.cos_region
    host = f"{settings.cos_bucket}.cos.{settings.cos_region}.myqcloud.com"
    url = httpx.URL(f"https://{host}/{quote(key, safe='/')}")
    now = dt.datetime.now(dt.UTC)
    digest = hashlib.sha256(data).hexdigest()
    headers = {
        "host": host,
        "content-type": "audio/ogg",
        "x-amz-content-sha256": digest,
        "x-amz-date": now.strftime("%Y%m%dT%H%M%SZ"),
    }
    headers["Authorization"] = sign_v4(
        "PUT",
        url,
        headers,
        digest,
        access_key=settings.cos_secret_id.get_secret_value(),
        secret_key=settings.cos_secret_key.get_secret_value(),
        region=settings.cos_region,
        service="s3",
        now=now,
    )
    async with httpx.AsyncClient(timeout=30, transport=transport) as client:
        res = await client.put(url, headers=headers, content=data)
    if res.status_code != 200:
        raise RuntimeError(f"COS refused the recording (HTTP {res.status_code})")


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
