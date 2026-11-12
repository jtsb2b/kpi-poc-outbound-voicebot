"""The dashboard KPI asked for at the 4 Nov 2026 demo: talk time, call-backs and why, how many were
reached, the accumulated satisfaction score and what each garage said about each car."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from httpx import AsyncClient

from kpi_voicebot.config import Settings
from kpi_voicebot.dashboard import summarize
from kpi_voicebot.store import Store
from kpi_voicebot.worker import Worker
from tests.test_api import create

TZ = "Asia/Bangkok"


def call(n: int, campaign: str, outcome: str, *, at: datetime, talk: int | None = 120, **extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "_id": f"c{n}",
        "campaign": campaign,
        "lifecycle": "ended",
        "mode": "live",
        "target_name": f"ลูกค้า {n}",
        "phone": {"display": "081 234 5678"},
        "dial_result": "answered" if talk is not None else "no_answer",
        "outcome": outcome,
        "created_at": at,
        "result": extra.pop("result", {}),
        **extra,
    }
    if talk is not None:
        doc["answered_at"] = at + timedelta(seconds=10)
        doc["ended_at"] = doc["answered_at"] + timedelta(seconds=talk)
    return doc


def answers(*values: int) -> list[dict[str, Any]]:
    return [
        {"question": f"q{i}", "label": f"ข้อ {i}", "scale_min": 1, "scale_max": 5, "value": v, "status": "answered"}
        for i, v in enumerate(values, 1)
    ]


# 10 Nov, 09:00 Bangkok, and the next day.
MON = datetime(2026, 11, 10, 2, 0, tzinfo=UTC)
TUE = MON + timedelta(days=1)


def test_reach_success_and_talk_time_leave_operator_cancels_out() -> None:
    docs = [
        call(1, "pa_confirmation", "policy_confirmed", at=MON, talk=200),
        call(2, "pa_confirmation", "policy_partial", at=MON, talk=100),
        call(3, "pa_confirmation", "not_reached", at=MON, talk=None),
        call(4, "pa_confirmation", "hung_up_early", at=TUE, talk=5),
        call(5, "pa_confirmation", "canceled", at=TUE, talk=30),
    ]
    out = summarize(docs, start=MON.date(), end=TUE.date(), timezone=TZ)
    t = out["totals"]
    assert (t["calls"], t["reached"], t["completed"], t["canceled"]) == (4, 2, 1, 1)
    assert (t["contact_rate"], t["success_rate"]) == (50.0, 25.0)
    assert (t["talk_seconds"], t["average_talk_seconds"]) == (300, 150)
    pa = next(c for c in out["campaigns"] if c["campaign"] == "pa_confirmation")
    assert pa["staff_minutes"] == [3, 4] and pa["calls"] == 4
    assert out["daily"] == [
        {"date": "2026-11-10", "completed": 1, "reached_not_completed": 1, "not_reached": 1},
        {"date": "2026-11-11", "completed": 0, "reached_not_completed": 0, "not_reached": 1},
    ]


def test_calls_are_counted_on_the_thai_day() -> None:
    late = datetime(2026, 11, 10, 18, 30, tzinfo=UTC)  # 01:30 on 11 Nov in Bangkok
    out = summarize(
        [call(1, "pa_confirmation", "policy_confirmed", at=late)],
        start=date(2026, 11, 11),
        end=date(2026, 11, 11),
        timezone=TZ,
    )
    assert out["totals"]["calls"] == 1


def test_the_satisfaction_score_accumulates_day_by_day() -> None:
    docs = [
        call(1, "accident_survey", "survey_completed", at=MON, result={"survey_answers": answers(5, 4)}),
        call(2, "accident_survey", "survey_partial", at=TUE, result={"survey_answers": answers(1, 2)}),
    ]
    sat = summarize(docs, start=MON.date(), end=TUE.date() + timedelta(1), timezone=TZ)["satisfaction"]
    assert (sat["responses"], sat["surveys"], sat["average"], sat["csat"]) == (4, 2, 3.0, 50.0)
    assert [(d["day_average"], d["cumulative_average"]) for d in sat["trend"]] == [(4.5, 4.5), (1.5, 3.0), (None, 3.0)]
    q1 = sat["questions"][0]
    assert q1["average"] == 3.0 and q1["distribution"][0] == {"value": 1, "count": 1}


def test_a_0_to_10_question_is_kept_out_of_the_1_to_5_score() -> None:
    zero_ten = {"question": "q5", "label": "0-10", "scale_min": 0, "scale_max": 10, "value": 9, "status": "answered"}
    docs = [call(1, "accident_survey", "survey_completed", at=MON, result={"survey_answers": [*answers(2), zero_ten]})]
    sat = summarize(docs, start=MON.date(), end=MON.date(), timezone=TZ)["satisfaction"]
    assert sat["average"] == 2.0 and sat["questions"][1]["average"] == 9.0


def test_call_backs_say_why() -> None:
    docs = [
        call(
            1,
            "pa_confirmation",
            "callback_requested",
            at=MON,
            result={
                "callback": {"requested": True, "preferred_time_text": "พรุ่งนี้เช้า", "preferred_date": "วันพุธ"},
                "tasks": [
                    {"type": "callback", "reason": "ลูกค้าขอให้ติดต่อกลับ"},
                    {"type": "complaint", "reason": "ร้องเรียน"},
                ],
            },
        ),
        call(2, "pa_confirmation", "not_reached", at=TUE, talk=None),
        call(3, "pa_confirmation", "policy_confirmed", at=TUE),
        call(4, "pa_confirmation", "canceled", at=TUE, result={"tasks": [{"type": "callback", "reason": "x"}]}),
    ]
    rows = summarize(docs, start=MON.date(), end=TUE.date(), timezone=TZ)["follow_ups"]
    assert [r["call_id"] for r in rows] == ["c2", "c1"]  # newest first; nothing for the confirmed or canceled call
    assert rows[0]["reasons"] == [{"type": "not_reached", "text": "ติดต่อไม่ได้"}]
    assert [r["text"] for r in rows[1]["reasons"]] == ["ลูกค้าขอให้ติดต่อกลับ", "ร้องเรียน"]
    assert rows[1]["callback_date"] == "วันพุธ"


def test_each_car_shows_what_the_latest_calls_said() -> None:
    case = {"garage_name": "ช.ทวีการช่าง", "vehicles": [{"plate": "1กข 1234", "car": "Yaris", "claim_no": "CL-1"}]}
    first = {"plate": "1กข 1234", "status": "in_repair", "completion_text": "พรุ่งนี้", "completion_date": "วันพุธ"}
    docs = [
        call(1, "garage_followup", "followup_completed", at=MON, case=case, result={"vehicles": [first]}),
        call(
            2,
            "garage_followup",
            "followup_completed",
            at=TUE,
            case=case,
            result={"vehicles": [{"plate": "1กข 1234", "status": "repaired"}]},
        ),
    ]
    out = summarize(docs, start=MON.date(), end=TUE.date(), timezone=TZ)
    assert out["vehicles"] == [
        {
            "plate": "1กข 1234",
            "car": "Yaris",
            "claim_no": "CL-1",
            "garage_name": "ช.ทวีการช่าง",
            "status": "repaired",
            "campaign": "garage_followup",
            "call_id": "c2",
            "at": TUE.isoformat(),
            "overdue": False,
        }
    ]
    # Before the second call, the expected completion date was what the garage had said.
    out = summarize(docs[:1], start=MON.date(), end=MON.date(), timezone=TZ)
    assert out["vehicles"][0]["completion_date"] == "วันพุธ"


async def test_the_dashboard_endpoint(client: AsyncClient, store: Store, settings: Settings) -> None:
    await create(client)
    assert await Worker(store, settings, "w1").process_once()
    live_only = (await client.get("/api/v1/dashboard")).json()
    assert live_only["totals"]["calls"] == 0  # the simulated call is left out unless asked for
    out = (await client.get("/api/v1/dashboard", params={"days": 1, "include_simulations": True})).json()
    assert out["totals"]["calls"] == 1 and out["start"] == out["end"]
    assert out["satisfaction"]["questions"][0]["question"] == "q1"
    assert (await client.get("/api/v1/dashboard", params={"days": 0})).status_code == 422


def test_calls_from_before_dates_were_worked_out_get_them_from_the_day_of_the_call() -> None:
    wed = datetime(2026, 11, 11, 8, 0, tzinfo=UTC)  # Wednesday 11 Nov, 15:00 Bangkok
    docs = [
        call(
            1,
            "accident_survey",
            "callback_requested",
            at=wed,
            result={"callback": {"requested": True, "preferred_time_text": "พรุ่งนี้เช้า"}},
        ),
        call(
            2,
            "garage_followup",
            "followup_completed",
            at=wed,
            case={"garage_name": "ก", "vehicles": [{"plate": "1กข 1234"}]},
            result={"vehicles": [{"plate": "1กข 1234", "status": "in_repair", "completion_text": "จันทร์หน้า"}]},
        ),
    ]
    out = summarize(docs, start=wed.date(), end=date(2026, 11, 12), timezone=TZ)
    assert out["follow_ups"][0]["callback_date"] == "วันพฤหัสบดีที่ 12 พฤศจิกายน 2569 ช่วงเช้า"
    car = out["vehicles"][0]
    assert car["completion_date"] == "วันจันทร์ที่ 16 พฤศจิกายน 2569" and car["overdue"] is False
    later = summarize(docs, start=wed.date(), end=date(2026, 11, 17), timezone=TZ)["vehicles"][0]
    assert later["overdue"] is True  # still "in repair" the day after the garage said it would be done
