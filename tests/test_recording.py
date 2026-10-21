"""Call recording to Tencent COS, without COS or LiveKit: the requests they would receive."""

import datetime as dt
import hashlib
from typing import Any

import httpx
import numpy as np
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from kpi_voicebot import recording
from kpi_voicebot.config import Settings
from kpi_voicebot.models import DialResult
from kpi_voicebot.store import Store
from kpi_voicebot.telephony import CallEnd
from kpi_voicebot.worker import Worker

from .conftest import TOKEN
from .test_telephony import FakePhone, fake, queue_live_call


@pytest.fixture
def settings() -> Settings:
    """Live calls on, everything configured, recording to a test bucket."""
    return cos_settings().model_copy(
        update={
            "sim_turn_delay_ms": 0,
            "live_calls_enabled": True,
            "calling_start": "00:00",
            "calling_end": "24:00",
            "calling_days": list(range(7)),
            "livekit_url": "wss://example.invalid",
            "livekit_api_key": SecretStr("k"),
            "livekit_api_secret": SecretStr("s"),
            "livekit_sip_outbound_trunk_id": "ST_test",
            "sip_caller_number": "2211",
            "soniox_api_key": SecretStr("so"),
            "jaitts_api_key": SecretStr("t"),
            "google_api_key": SecretStr("g"),
        }
    )


def cos_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        operator_token=SecretStr(TOKEN),
        cos_secret_id=SecretStr("AKIDtest"),
        cos_secret_key=SecretStr("secret-test"),
        cos_region="ap-bangkok",
        cos_bucket="kpi-recordings-1250000000",
    )


def test_requests_are_signed_like_aws_signature_v4() -> None:
    # AWS SigV4 test suite, "get-vanilla".
    auth = recording.sign_v4(
        "GET",
        httpx.URL("https://example.amazonaws.com/"),
        {"Host": "example.amazonaws.com", "X-Amz-Date": "20150830T123600Z"},
        hashlib.sha256(b"").hexdigest(),
        access_key="AKIDEXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        service="service",
        now=dt.datetime(2015, 8, 30, 12, 36, 0),
    )
    assert auth == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
        "SignedHeaders=host;x-amz-date, "
        "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    )


async def test_an_objected_recording_is_deleted_from_the_bucket() -> None:
    seen: list[httpx.Request] = []

    def cos(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    s = cos_settings()
    await recording.delete(s, "kpi-voicebot/recordings/19-10-2026/สมชาย_ใจดี_1.ogg", transport=httpx.MockTransport(cos))
    request = seen[0]
    assert request.method == "DELETE"
    assert request.url.host == "kpi-recordings-1250000000.cos.ap-bangkok.myqcloud.com"
    assert request.url.path == "/kpi-voicebot/recordings/19-10-2026/สมชาย_ใจดี_1.ogg"  # sent percent-encoded
    assert request.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDtest/")
    assert (
        "/ap-bangkok/s3/aws4_request, SignedHeaders=host;x-amz-content-sha256;x-amz-date,"
        in (request.headers["Authorization"])
    )


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def tone(seconds: float, value: int = 1000, rate: int = 16_000) -> bytes:
    return (np.full(int(seconds * rate), value, dtype=np.int16)).tobytes()


def test_both_sides_are_laid_on_one_timeline_and_mixed() -> None:
    clock = Clock()
    rec = recording.CallRecorder(clock)
    rec.bot(tone(1.0, 1000, 24_000), 24_000, plays_at=100.0)  # the greeting, 0-1 s
    clock.now = 101.5
    rec.customer(tone(0.5, 2000))  # "ครับ", heard 1.0-1.5 s
    mixed = rec.mix()
    assert len(mixed) == int(1.5 * 16_000)
    assert mixed[8_000] == 1000 and mixed[20_000] == 2000 and mixed[-1] == 2000


def test_bot_speech_cut_by_the_customer_is_not_in_the_recording() -> None:
    clock = Clock()
    rec = recording.CallRecorder(clock)
    rec.bot(tone(4.0), 16_000, plays_at=100.0)
    rec.cut_bot(101.0)  # the customer talked over it after a second
    assert len(rec.mix()) == 16_000


def test_a_declined_recording_keeps_nothing() -> None:
    rec = recording.CallRecorder(Clock())
    rec.customer(tone(1.0))
    rec.discard()
    rec.customer(tone(1.0))
    rec.bot(tone(1.0), 16_000, plays_at=100.0)
    assert rec.discarded and len(rec.mix()) == 0


def test_the_recording_is_opus_in_ogg_of_the_right_length() -> None:
    import io

    import av

    clock = Clock()
    rec = recording.CallRecorder(clock)
    rec.bot(tone(2.0), 16_000, plays_at=100.0)
    data = rec.encode()
    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.audio[0]
        assert stream.codec_context.name == "opus"
        seconds = sum(f.samples / f.sample_rate for f in container.decode(stream))
    assert data[:4] == b"OggS" and abs(seconds - 2.0) < 0.1


async def test_the_recording_is_uploaded_with_a_signed_put() -> None:
    seen: list[httpx.Request] = []

    def cos(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    s = cos_settings()
    key = "kpi-voicebot/recordings/20-10-2026/สมชาย_ใจดี_pa_confirmation_101500_abcd1234.ogg"
    await recording.upload(s, key, b"OggS...", transport=httpx.MockTransport(cos))
    request = seen[0]
    assert request.method == "PUT" and request.url.path == "/" + key and request.content == b"OggS..."
    assert request.headers["content-type"] == "audio/ogg"
    assert request.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDtest/")
    assert request.headers["x-amz-content-sha256"] == hashlib.sha256(b"OggS...").hexdigest()


async def test_a_refused_upload_is_an_error_not_silence() -> None:
    s = cos_settings()
    with pytest.raises(RuntimeError, match="HTTP 403"):
        await recording.upload(s, "k.ogg", b"x", transport=httpx.MockTransport(lambda r: httpx.Response(403)))


def answered_with(outcome_text: str) -> Any:
    async def call(phone: FakePhone) -> CallEnd:
        await phone.kw["on_answered"]()
        engine = phone.engine
        engine.start()
        if outcome_text == "objection":
            from kpi_voicebot.models import Outcome

            engine.state.finished, engine.state.outcome = True, Outcome.NOTICE_OBJECTION
        else:
            engine.handle_hangup()
        return CallEnd(DialResult.ANSWERED, True, "customer_hung_up", recording_key=phone.kw["recording_key"])

    return call


async def test_recording_is_kept_normally_and_deleted_when_the_customer_objects(
    client: AsyncClient, store: Store, settings: Settings
) -> None:
    deleted: list[str] = []

    async def delete(_: Settings, key: str) -> None:
        deleted.append(key)

    worker = Worker(store, settings, "w1")
    worker.delete_recording = delete
    kept = await queue_live_call(client)
    worker.phone_factory = fake(answered_with("hangup"))
    await worker.process_once()
    stored = (await store.get_call(kept))["recording"]
    assert stored["status"] == "stored"
    folder, name = stored["key"].removeprefix("kpi-voicebot/recordings/").split("/")
    assert dt.datetime.strptime(folder, "%d-%m-%Y")  # one folder per day
    assert name.startswith("สมชาย_ใจดี_accident_survey_") and name.endswith(f"_{kept[:8]}.ogg")

    r = await client.post(
        "/api/v1/calls",
        json={
            "campaign": "accident_survey",
            "target_name": "สมชาย ใจดี",
            "phone": "081-234-5678",
            "mode": "live",
            "source": {"type": "profile", "profile_id": "survey-surveyor"},
        },
        headers={"Idempotency-Key": "live-0002"},
    )
    objected = r.json()["call_id"]
    worker.phone_factory = fake(answered_with("objection"))
    await worker.process_once()
    assert len(deleted) == 1 and deleted[0].endswith(f"_{objected[:8]}.ogg")
    assert (await store.get_call(objected))["recording"] == {"key": None, "status": "discarded"}


def test_recordings_are_filed_by_day_under_the_customers_name() -> None:
    s = cos_settings()
    at = dt.datetime(2026, 10, 19, 17, 30, 5, tzinfo=dt.UTC)  # 00:30 on 20 Oct in Bangkok
    key = recording.object_key(s, "dfd6321189fe4c8c", "สมชาย ใจดี", "pa_confirmation", at)
    assert key == "kpi-voicebot/recordings/20-10-2026/สมชาย_ใจดี_pa_confirmation_003005_dfd63211.ogg"
    assert recording.object_key(s, "c1", "a/b ../x", "", at).count("/") == 3  # a name never makes a folder


async def test_a_failed_or_declined_recording_is_said_on_the_call(
    client: AsyncClient, store: Store, settings: Settings
) -> None:
    def ended(**flags: bool) -> Any:
        async def call(phone: FakePhone) -> CallEnd:
            await phone.kw["on_answered"]()
            phone.engine.start()
            phone.engine.handle_hangup()
            return CallEnd(DialResult.ANSWERED, True, "customer_hung_up", **flags)

        return call

    worker = Worker(store, settings, "w1")
    failed = await queue_live_call(client)
    worker.phone_factory = fake(ended(recording_failed=True))
    await worker.process_once()
    assert (await store.get_call(failed))["recording"] == {"key": None, "status": "failed"}

    r = await client.post(
        "/api/v1/calls",
        json={
            "campaign": "accident_survey",
            "target_name": "สมชาย ใจดี",
            "phone": "081-234-5678",
            "mode": "live",
            "source": {"type": "profile", "profile_id": "survey-surveyor"},
        },
        headers={"Idempotency-Key": "live-0003"},
    )
    declined = r.json()["call_id"]
    worker.phone_factory = fake(ended(recording_declined=True))
    await worker.process_once()
    assert (await store.get_call(declined))["recording"] == {"key": None, "status": "declined"}


async def test_the_call_uploads_its_recording_at_hang_up_or_says_it_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    from kpi_voicebot.telephony import PhoneCall

    uploaded: list[str] = []

    async def ok(_: Settings, key: str, data: bytes) -> None:
        uploaded.append(key)

    async def refused(_: Settings, key: str, data: bytes) -> None:
        raise RuntimeError("COS refused the recording (HTTP 403)")

    def call(declined: bool = False) -> Any:
        phone = object.__new__(PhoneCall)
        phone.settings, phone.recording_key, phone.console = cos_settings(), "k/20-10-2026/a.ogg", False
        phone.sink, phone._end, phone.room_name = None, CallEnd(DialResult.ANSWERED, True), "kpi-test"
        phone.recorder = recording.CallRecorder(Clock())
        phone.recorder.customer(tone(1.0))
        if declined:
            phone.recorder.discard()
        return phone

    monkeypatch.setattr(recording, "upload", ok)
    phone = call()
    await phone._save_recording()
    assert phone._end.recording_key == "k/20-10-2026/a.ogg" and uploaded == ["k/20-10-2026/a.ogg"]

    phone = call(declined=True)
    await phone._save_recording()
    assert phone._end.recording_key is None and len(uploaded) == 1  # nothing kept, nothing uploaded

    monkeypatch.setattr(recording, "upload", refused)
    phone = call()
    await phone._save_recording()
    assert phone._end.recording_failed and phone._end.recording_key is None
