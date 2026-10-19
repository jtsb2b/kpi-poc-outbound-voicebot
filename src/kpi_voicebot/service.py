"""Call request validation: phone, campaign record, mode and calling-hour gates."""

from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from kpi_voicebot.campaigns import get_profile, load_campaign, validate_case
from kpi_voicebot.config import Settings
from kpi_voicebot.models import CallMode, CampaignId
from kpi_voicebot.phone import InvalidPhone, parse_destination
from kpi_voicebot.simulator import get_scenario
from kpi_voicebot.store import Store


class ProfileSource(BaseModel):
    type: Literal["profile"] = "profile"
    profile_id: str


class ImportSource(BaseModel):
    type: Literal["import"] = "import"
    import_id: str
    row_number: int


class CallRequest(BaseModel):
    campaign: CampaignId
    target_name: Annotated[str, Field(min_length=1, max_length=120)]
    phone: Annotated[str, Field(min_length=3, max_length=32)]
    mode: CallMode = CallMode.SIMULATION
    source: Annotated[ProfileSource | ImportSource, Field(discriminator="type")]
    scenario_id: str | None = None
    custom_script: list[Annotated[str, Field(max_length=300)]] | None = Field(default=None, max_length=40)

    @field_validator("target_name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("กรุณากรอกชื่อ")
        return value


class RequestRejected(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def within_calling_hours(settings: Settings, now: datetime | None = None) -> bool:
    local = (now or datetime.now(ZoneInfo(settings.timezone))).astimezone(ZoneInfo(settings.timezone))
    clock = local.strftime("%H:%M")
    return local.weekday() in settings.calling_days and settings.calling_start <= clock < settings.calling_end


async def build_call_document(request: CallRequest, settings: Settings, store: Store) -> dict[str, Any]:
    try:
        destination = parse_destination(request.phone, allow_extensions=settings.allow_internal_extensions)
    except InvalidPhone as exc:
        raise RequestRejected(422, str(exc)) from exc
    if not destination.dialable:
        raise RequestRejected(422, destination.reason or "ไม่สามารถโทรออกไปยังหมายเลขนี้ได้")

    warnings: list[str] = []
    if isinstance(request.source, ProfileSource):
        profile = get_profile(request.source.profile_id)
        if profile is None or profile.campaign != request.campaign:
            raise RequestRejected(422, "ไม่พบข้อมูลจำลองสำหรับแคมเปญนี้")
        case = validate_case(request.campaign, profile.case).model_dump(mode="json")
        source: dict[str, Any] = {"type": "profile", "profile_id": profile.profile_id, "label": profile.label}
    else:
        imported = await store.get_import(request.source.import_id)
        if imported is None or imported["campaign"] != request.campaign:
            raise RequestRejected(422, "ไม่พบไฟล์ที่นำเข้าสำหรับแคมเปญนี้")
        row = next((r for r in imported["rows"] if r["row_number"] == request.source.row_number), None)
        if row is None or row["record"] is None:
            raise RequestRejected(422, "แถวที่เลือกไม่ถูกต้องหรือมีข้อผิดพลาด")
        case = dict(row["record"])
        info = row.get("file_info", {})
        if info.get("customer_name") and info["customer_name"] != request.target_name:
            warnings.append(f"ชื่อในไฟล์ ({info['customer_name']}) ไม่ตรงกับชื่อในฟอร์ม ระบบใช้ชื่อจากฟอร์ม")
        if info.get("phone"):
            try:
                file_dest = parse_destination(info["phone"], allow_extensions=True)
                if file_dest.e164 != destination.e164:
                    warnings.append("เบอร์ในไฟล์ไม่ตรงกับเบอร์ในฟอร์ม ระบบโทรตามเบอร์ในฟอร์ม")
            except InvalidPhone:
                warnings.append("เบอร์ในไฟล์ไม่ถูกต้อง ระบบโทรตามเบอร์ในฟอร์ม")
        source = {
            "type": "import",
            "import_id": imported["_id"],
            "row_number": row["row_number"],
            "record_id": row["record_id"],
            "filename": imported.get("filename"),
        }

    script: list[str] | None = None
    if request.mode is CallMode.LIVE:
        if not settings.live_calls_enabled:
            raise RequestRejected(409, "การโทรจริงยังไม่เปิดใช้งาน (ใช้โหมดจำลองได้)")
        if not within_calling_hours(settings):
            raise RequestRejected(409, f"อยู่นอกเวลาโทร ({settings.calling_window})")
        if destination.e164 and await store.asked_not_to_call(destination.e164):
            # OIC guideline: a customer's refusal is kept and respected for at least 6 months.
            raise RequestRejected(409, "ลูกค้าเบอร์นี้ขอไม่ให้ติดต่อกลับ (ภายใน 6 เดือน)")
        if settings.livekit_missing():
            raise RequestRejected(409, "ยังตั้งค่าระบบโทรศัพท์ไม่ครบ (LiveKit / ระบบรู้จำเสียง / ระบบเสียงพูด)")
    else:
        if request.custom_script:
            script = [line for line in request.custom_script if line.strip()]
        elif request.scenario_id:
            scenario = get_scenario(request.scenario_id)
            if scenario is None or scenario.campaign != request.campaign:
                raise RequestRejected(422, "ไม่พบสถานการณ์จำลองสำหรับแคมเปญนี้")
            script = scenario.customer
        if not script:
            raise RequestRejected(422, "โหมดจำลองต้องเลือกสถานการณ์หรือพิมพ์คำตอบของลูกค้า")

    campaign = load_campaign(request.campaign)
    return {
        "campaign": request.campaign.value,
        "campaign_version": campaign.version,
        "campaign_snapshot": campaign.snapshot_id,
        "mode": request.mode.value,
        "scenario_id": None
        if request.mode is CallMode.LIVE
        else (request.scenario_id if not request.custom_script else "custom"),
        "script": script,
        "target_name": request.target_name,
        "phone": {
            "entered": destination.entered,
            "e164": destination.e164,
            "display": destination.display,
            "kind": destination.kind,
            "sip_destination": destination.sip_destination,
        },
        "source": source,
        "case": case,
        "data_label": case.get("data_label", "MOCK"),
        "warnings": warnings,
    }
