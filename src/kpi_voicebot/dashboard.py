"""The dashboard: what the voicebot has done across every campaign (KPI demo feedback, 4 Nov 2026).

KPI asked for, per use case: time spent on calls in total and per case, which cases need a call back
and why, how many people were reached, the satisfaction score accumulated over time, and what each
garage said about each car (repaired and claim to be filed, or when it goes in for repair).

Everything is worked out here from stored calls, so the page and any later report read one set of
numbers. Days are Thai calendar days.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from kpi_voicebot.store import as_utc
from kpi_voicebot.when import resolve, worked_out

# KPI's own staff time per case, from the 4 Nov meeting (minutes, low-high): the bar the bot is held to.
STAFF_MINUTES: dict[str, tuple[int, int]] = {
    "pa_confirmation": (3, 4),
    "accident_survey": (4, 4),
    "garage_followup": (1, 2),
    "repair_appointment": (2, 3),
}
CAMPAIGNS = tuple(STAFF_MINUTES)

COMPLETED = frozenset({"policy_confirmed", "confirmed_with_discrepancy", "survey_completed", "followup_completed"})
# Reached but the call never got going: counted as not successful, like a call nobody picked up.
NOT_REACHED = frozenset({"not_reached", "no_response", "hung_up_early"})
CANCELED = "canceled"  # stopped by an operator: left out of every rate

# Why a call needs a call back when the conversation itself left no task.
_OUTCOME_REASON = {
    "not_reached": "ติดต่อไม่ได้",
    "no_response": "ไม่มีเสียงตอบรับ",
    "hung_up_early": "วางสายก่อนเริ่มสนทนา",
    "technical_failure": "ระบบขัดข้องระหว่างโทร",
    "policy_partial": "วางสายก่อนทวนข้อมูลครบ",
    "survey_partial": "วางสายก่อนตอบแบบสอบถามครบ",
    "followup_partial": "ได้ข้อมูลไม่ครบทุกคัน",
    "refused": "ปฏิเสธการสนทนา",
    "verification_failed": "ยืนยันตัวตนไม่สำเร็จ",
}


def _talk_seconds(doc: dict[str, Any]) -> float | None:
    answered, ended = doc.get("answered_at"), doc.get("ended_at")
    if not answered or not ended:
        return None
    return max(0.0, (as_utc(ended) - as_utc(answered)).total_seconds())


def _reached(doc: dict[str, Any]) -> bool:
    return doc.get("dial_result") == "answered" and doc.get("outcome") not in NOT_REACHED


def _day(value: datetime, tz: ZoneInfo) -> date:
    return as_utc(value).astimezone(tz).date()


def _iso(value: datetime | None) -> str | None:
    return as_utc(value).isoformat() if value else None


def _date_of(stored: str | None, text: str | None, day: date) -> str | None:
    """The worked-out day: stored with the call, or worked out now from the day of the call (calls made
    before the bot worked dates out, 12 Nov 2026)."""
    return stored or worked_out(text, day)


def _latest_day(text: str | None, day: date) -> str | None:
    """The last day the words can mean ("ปลายเดือน": the 30th), as an ISO date, to tell when it has passed."""
    named = resolve(text or "", day)
    if not named:
        return None
    when = named[-1]
    return max(d for d in (when.start, when.end, when.also) if d is not None).isoformat()


def _follow_up(doc: dict[str, Any], day: date) -> dict[str, Any] | None:
    """The call as a row of the call-back list, or None when nothing is left to do."""
    outcome = doc.get("outcome")
    result = doc.get("result") or {}
    callback = result.get("callback") or {}
    reasons: list[dict[str, str]] = []
    if callback.get("requested"):
        reasons.append({"type": "callback", "text": "ลูกค้าขอให้ติดต่อกลับ"})
    for task in result.get("tasks") or []:
        text = str(task.get("reason") or "")
        if not any(r["text"] == text for r in reasons):
            reasons.append({"type": str(task.get("type")), "text": text})
    if not reasons and outcome in _OUTCOME_REASON:
        reasons.append(
            {"type": "not_reached" if outcome in NOT_REACHED else str(outcome), "text": _OUTCOME_REASON[outcome]}
        )
    if not reasons or outcome == CANCELED:
        return None
    return {
        "call_id": doc["_id"],
        "campaign": doc.get("campaign"),
        "target_name": doc.get("target_name"),
        "phone": (doc.get("phone") or {}).get("display"),
        "at": _iso(doc.get("created_at")),
        "outcome": outcome,
        "reasons": reasons,
        "callback_time_text": callback.get("preferred_time_text"),
        "callback_date": _date_of(callback.get("preferred_date"), callback.get("preferred_time_text"), day),
    }


def _vehicles(doc: dict[str, Any], day: date) -> list[dict[str, Any]]:
    """What the call found out about each car, joined with the car's case details."""
    case = doc.get("case") or {}
    known = {v.get("plate"): v for v in case.get("vehicles") or ([case["vehicle"]] if case.get("vehicle") else [])}
    rows = []
    for v in (doc.get("result") or {}).get("vehicles") or []:
        if v.get("status") in (None, "not_asked"):
            continue
        car = known.get(v.get("plate")) or {}
        rows.append(
            {
                "plate": v.get("plate"),
                "car": v.get("label") or car.get("car") or "",
                "customer_name": car.get("customer_name") or "",
                "claim_no": car.get("claim_no") or "",
                "garage_name": case.get("garage_name") or "",
                "status": v.get("status"),
                **{
                    key: value
                    for when in ("completion", "appointment", "pickup")
                    for key, value in (
                        (f"{when}_text", v.get(f"{when}_text")),
                        (f"{when}_date", _date_of(v.get(f"{when}_date"), v.get(f"{when}_text"), day)),
                    )
                },
                "completion_by": _latest_day(v.get("completion_text"), day),
                "statement": v.get("statement"),
                "campaign": doc.get("campaign"),
                "call_id": doc["_id"],
                "at": _iso(doc.get("created_at")),
            }
        )
    return rows


def _satisfaction(docs: list[dict[str, Any]], tz: ZoneInfo, days: list[date]) -> dict[str, Any]:
    """Survey answers: each question's average and spread, and the 1-5 score accumulated day by day.

    The headline is the 1-5 questions only (CSAT: the share answering 4 or 5); a 0-10 question is shown
    on its own scale and never averaged in with them."""
    questions: dict[str, dict[str, Any]] = {}
    per_day: dict[date, list[int]] = defaultdict(list)
    for doc in sorted(docs, key=lambda d: as_utc(d["created_at"])):
        for a in (doc.get("result") or {}).get("survey_answers") or []:
            if a.get("status") != "answered" or a.get("value") is None:
                continue
            q = questions.setdefault(
                a["question"],
                {
                    "question": a["question"],
                    "label": a.get("label") or a["question"],
                    "scale_min": a.get("scale_min", 1),
                    "scale_max": a.get("scale_max", 5),
                    "values": [],
                },
            )
            q["values"].append(int(a["value"]))
            if q["scale_min"] == 1 and q["scale_max"] == 5:
                per_day[_day(doc["created_at"], tz)].append(int(a["value"]))

    out_questions = []
    for q in sorted(questions.values(), key=lambda q: q["question"]):
        values: list[int] = q.pop("values")
        spread = Counter(values)
        out_questions.append(
            {
                **q,
                "responses": len(values),
                "average": round(sum(values) / len(values), 2),
                "distribution": [
                    {"value": v, "count": spread.get(v, 0)} for v in range(q["scale_min"], q["scale_max"] + 1)
                ],
            }
        )

    trend, total, count, satisfied = [], 0, 0, 0
    for day in days:
        values = per_day.get(day, [])
        total, count = total + sum(values), count + len(values)
        satisfied += sum(1 for v in values if v >= 4)
        trend.append(
            {
                "date": day.isoformat(),
                "responses": len(values),
                "day_average": round(sum(values) / len(values), 2) if values else None,
                "cumulative_average": round(total / count, 2) if count else None,
                "cumulative_csat": round(100 * satisfied / count, 1) if count else None,
            }
        )
    return {
        "responses": count,
        "surveys": sum(
            1
            for d in docs
            if any(a.get("status") == "answered" for a in (d.get("result") or {}).get("survey_answers") or [])
        ),
        "average": round(total / count, 2) if count else None,
        "csat": round(100 * satisfied / count, 1) if count else None,
        "questions": out_questions,
        "trend": trend,
    }


def summarize(docs: list[dict[str, Any]], *, start: date, end: date, timezone: str) -> dict[str, Any]:
    """The dashboard for the calls placed from `start` to `end` (Thai calendar days, both included)."""
    tz = ZoneInfo(timezone)
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    docs = [d for d in docs if d.get("lifecycle") == "ended" and start <= _day(d["created_at"], tz) <= end]
    counted = [d for d in docs if d.get("outcome") != CANCELED]

    def totals(group: list[dict[str, Any]]) -> dict[str, Any]:
        reached = [d for d in group if _reached(d)]
        talk = [s for d in reached if (s := _talk_seconds(d)) is not None]
        completed = sum(1 for d in group if d.get("outcome") in COMPLETED)
        return {
            "calls": len(group),
            "reached": len(reached),
            "not_reached": len(group) - len(reached),
            "completed": completed,
            "contact_rate": round(100 * len(reached) / len(group), 1) if group else None,
            "success_rate": round(100 * completed / len(group), 1) if group else None,
            "talk_seconds": round(sum(talk)),
            "average_talk_seconds": round(sum(talk) / len(talk)) if talk else None,
        }

    daily = []
    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for d in counted:
        by_day[_day(d["created_at"], tz)].append(d)
    for day in days:
        group = by_day.get(day, [])
        completed = sum(1 for d in group if d.get("outcome") in COMPLETED)
        reached = sum(1 for d in group if _reached(d))
        daily.append(
            {
                "date": day.isoformat(),
                "completed": completed,
                "reached_not_completed": reached - completed,
                "not_reached": len(group) - reached,
            }
        )

    follow_ups = [
        row
        for d in sorted(docs, key=lambda d: as_utc(d["created_at"]), reverse=True)
        if (row := _follow_up(d, _day(d["created_at"], tz)))
    ]
    latest: dict[str, dict[str, Any]] = {}
    for d in sorted(docs, key=lambda d: as_utc(d["created_at"])):
        for row in _vehicles(d, _day(d["created_at"], tz)):
            # The newest call about a car sets its status; a date said in an earlier call (the garage's
            # completion date, the customer's repair date) stays until a later call gives another.
            before = latest.get(row["plate"], {})
            if row["status"] == "repaired":  # an expected completion date no longer applies
                before = {k: v for k, v in before.items() if not k.startswith("completion_")}
            latest[row["plate"]] = {**before, **{k: v for k, v in row.items() if v not in (None, "")}}

    for row in latest.values():
        # KPI's problem (4 Nov): garages finish a car and never say so. Past its expected day and still
        # "in repair": call the garage again.
        row["overdue"] = (
            row["status"] == "in_repair" and bool(row.get("completion_by")) and row["completion_by"] < end.isoformat()
        )

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": timezone,
        "totals": {**totals(counted), "canceled": len(docs) - len(counted)},
        "campaigns": [
            {
                "campaign": c,
                **totals([d for d in counted if d.get("campaign") == c]),
                "staff_minutes": list(STAFF_MINUTES[c]),
            }
            for c in CAMPAIGNS
        ],
        "daily": daily,
        "outcomes": [
            {"outcome": o, "count": n} for o, n in Counter(d.get("outcome") for d in counted).most_common() if o
        ],
        "satisfaction": _satisfaction(counted, tz, days),
        "follow_ups": follow_ups,
        "vehicles": sorted(latest.values(), key=lambda r: r["at"] or "", reverse=True),
    }
