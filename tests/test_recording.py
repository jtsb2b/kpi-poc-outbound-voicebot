"""Call recording to Tencent COS, without COS or LiveKit: the requests they would receive."""

import datetime as dt
import hashlib
from typing import Any

import httpx
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
            "calling_start_hour": 0,
            "calling_end_hour": 24,
            "livekit_url": "wss://example.invalid",
            "livekit_api_key": SecretStr("k"),
            "livekit_api_secret": SecretStr("s"),
            "livekit_sip_outbound_trunk_id": "ST_test",
            "sip_caller_number": "2211",
            "soniox_api_key": SecretStr("so"),
            "jaitts_api_key": SecretStr("t"),
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
    await recording.delete(s, recording.object_key(s, "call-1"), transport=httpx.MockTransport(cos))
    request = seen[0]
    assert request.method == "DELETE"
    assert (
        str(request.url)
        == "https://kpi-recordings-1250000000.cos.ap-bangkok.myqcloud.com/kpi-voicebot/recordings/call-1.ogg"
    )
    assert request.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDtest/")
    assert (
        "/ap-bangkok/s3/aws4_request, SignedHeaders=host;x-amz-content-sha256;x-amz-date,"
        in (request.headers["Authorization"])
    )


async def test_the_call_room_is_recorded_as_audio_into_the_bucket() -> None:
    sent: list[Any] = []

    class Egress:
        async def start_room_composite_egress(self, request: Any) -> Any:
            sent.append(request)
            return type("Info", (), {"egress_id": "EG_1"})()

    lk = type("LK", (), {"egress": Egress()})()
    s = cos_settings()
    rec = await recording.start(lk, s, "kpi-call-1", "kpi-voicebot/recordings/call-1.ogg")  # type: ignore[arg-type]
    request = sent[0]
    output = request.file_outputs[0]
    assert rec == recording.Recording("EG_1", "kpi-voicebot/recordings/call-1.ogg")
    assert (request.room_name, request.audio_only, output.filepath) == (
        "kpi-call-1",
        True,
        "kpi-voicebot/recordings/call-1.ogg",
    )
    assert (output.s3.bucket, output.s3.region, output.s3.endpoint) == (
        "kpi-recordings-1250000000",
        "ap-bangkok",
        "https://cos.ap-bangkok.myqcloud.com",
    )


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
    assert (await store.get_call(kept))["recording"] == {
        "key": f"kpi-voicebot/recordings/{kept}.ogg",
        "status": "stored",
    }

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
    assert deleted == [f"kpi-voicebot/recordings/{objected}.ogg"]
    assert (await store.get_call(objected))["recording"] == {"key": None, "status": "discarded"}
