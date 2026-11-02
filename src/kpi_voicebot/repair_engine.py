"""Claims follow-up (KPI script of 29 Oct 2026): a partner garage asked about each car it repairs, or a
customer the garage could not reach asked when they can bring the car in.

The LLM-led agent (`agent.py`) holds these conversations. This engine gives it the call's facts, the
approved lines and the result rows (one per car), and keeps a plain scripted flow for `INTERPRETER=rules`:
each car's question in turn, the answer recorded by keywords.
"""

import re

from kpi_voicebot.campaigns import Campaign
from kpi_voicebot.engine import BaseEngine, EngineState, Interpreter
from kpi_voicebot.models import (
    ConversationResult,
    Directive,
    GarageCase,
    Outcome,
    RepairCase,
    Segment,
    Vehicle,
    VehicleResult,
)
from kpi_voicebot.thai_parse import Signals

# What a garage's answer says about the car just asked; the agent's model reads answers too, these are
# the safety net for the plain ones ("เสร็จแล้วครับ") and the scripted flow's whole reading.
_UNREACHABLE = re.compile(r"ติดต่อ(ลูกค้า)?ไม่ได้|โทรไม่ติด|ไม่รับสาย|ติดต่อไม่ติด|ยังไม่ได้(โทร|ติดต่อ|นัด)")
_BOOKED = re.compile(r"นัด(แล้ว|ไว้|เรียบร้อย|เข้า)|ได้(คุย|ติดต่อ|โทร)(แล้ว|ไป)|โทร(นัด)?แล้ว|ติดต่อแล้ว")
_AWAITING = re.compile(r"ยังไม่(ได้)?(เอา|นำ)?(รถ)?(มา)?(เข้า|จอด|ส่ง)|ยังไม่จอด|รอนัด|รอลูกค้า|ลูกค้ายังไม่")
_IN_REPAIR = re.compile(r"กำลังซ่อม|ระหว่าง(การ)?ซ่อม|ยังซ่อม|ยังไม่เสร็จ|ซ่อมไม่เสร็จ|ซ่อมอยู่|รออะไหล่|ทำสี|เคาะ")
_REPAIRED = re.compile(r"เสร็จแล้ว|เสร็จเรียบร้อย|ซ่อมเสร็จ|ลูกค้ารับรถ(ไป)?แล้ว|ส่งมอบแล้ว")
_NOT_HERE = re.compile(r"ไม่มีรถ|ไม่ได้ซ่อมที่|ไม่รู้จัก|ไม่เคยเข้า|ไม่ใช่รถ(ของ)?(ที่)?อู่")
# A date or a time of day in an answer ("วันที่ 10", "พรุ่งนี้", "ศุกร์หน้า", "ต้นเดือนธันวา").
WHEN = re.compile(
    r"\d|วันที่|พรุ่งนี้|มะรืน|วันนี้|อาทิตย์|สัปดาห์|จันทร์|อังคาร|พุธ|พฤหัส|ศุกร์|เสาร์|เดือน|ต้นเดือน|"
    r"กลางเดือน|ปลายเดือน|สิ้นเดือน|มกรา|กุมภา|มีนา|เมษา|พฤษภา|มิถุนา|กรกฎา|สิงหา|กันยา|ตุลา|พฤศจิกา|ธันวา"
)
# A day, not just a month: "วันที่ 10", "ศุกร์หน้า", "พรุ่งนี้" (an appointment), against "ธันวาคม" (not yet).
DAY = re.compile(r"\d|วันที่|พรุ่งนี้|มะรืน|วันนี้|อาทิตย์|สัปดาห์|จันทร์|อังคาร|พุธ|พฤหัส|ศุกร์|เสาร์")
UNSURE = re.compile(r"ไม่ทราบ|ไม่แน่ใจ|ยังไม่รู้|(ยัง)?(บอก|ตอบ)ไม่ได้|ต้อง(ขอ)?(เช็ค|ตรวจสอบ|ดู)|ไม่ได้ดู|ยังไม่มีกำหนด")


def car_status(text: str, current: str) -> str | None:
    """The status a garage's answer gives the car just asked, or None when it says none."""
    if _NOT_HERE.search(text):
        return "not_at_garage"
    if _UNREACHABLE.search(text):
        return "customer_unreachable"
    if _BOOKED.search(text) and (current == "awaiting_customer" or _AWAITING.search(text)):
        return "booked"  # "ยังไม่เอารถมาจอด แต่อู่โทรนัดแล้ว วันที่ 5" is booked, not still waiting
    if _AWAITING.search(text):
        return "awaiting_customer"
    if _IN_REPAIR.search(text):
        return "in_repair"
    if _REPAIRED.search(text):
        return "repaired"
    return None


class RepairEngine(BaseEngine):
    def __init__(
        self,
        campaign: Campaign,
        case: GarageCase | RepairCase,
        customer_name: str,
        interpreter: Interpreter | None = None,
        state: EngineState | None = None,
        result: ConversationResult | None = None,
    ) -> None:
        self.case = case
        self.garage_call = isinstance(case, GarageCase)
        self.vehicles: list[Vehicle] = case.vehicles if isinstance(case, GarageCase) else [case.vehicle]
        variables = {
            "garage_name": case.garage_name,
            "vehicle_count": str(len(self.vehicles)),
            "plate": self.vehicles[0].plate,
        }
        if self.garage_call:
            # The garage is who we speak to: the greeting and the silence ladder name it, not a person.
            variables |= {"customer_name": f"อู่{case.garage_name}", "customer_first": f"อู่{case.garage_name}"}
        else:
            variables["customer_name"] = customer_name or self.vehicles[0].customer_name
        super().__init__(campaign, variables, interpreter, state, result)

    def _initial_result(self) -> ConversationResult:
        return ConversationResult(vehicles=[VehicleResult(plate=v.plate, label=v.car) for v in self.vehicles])

    def fact_sheet(self) -> list[str]:
        lines = [f"- ศูนย์บริการลูกค้า: {self.vars['service_phone']} หรือเว็บไซต์ www.kpi.co.th"]
        if self.garage_call:
            lines.append(f"- อู่ที่โทรหา: อู่{self.case.garage_name} (อู่คู่สัญญา)")
            lines.append(f"- จำนวนรถที่ติดตามในสายนี้: {len(self.vehicles)} คัน")
            for n, v in enumerate(self.vehicles, 1):
                owner = f"เจ้าของรถ คุณ{v.customer_name} เลขที่เคลม {v.claim_no}"
                lines.append(f"- รถคันที่ {n} (car{n}): ทะเบียน {v.plate} {v.car} {owner}")
        else:
            v = self.vehicles[0]
            lines.append(f"- ชื่อลูกค้า: คุณ{self.vars['customer_name']}")
            lines.append(f"- รถของลูกค้า: ทะเบียน {v.plate} {v.car} เลขที่เคลม {v.claim_no}")
            lines.append(f"- อู่คู่สัญญาที่ซ่อม: อู่{self.case.garage_name}")
        return lines

    def plate_line(self, key: str, index: int) -> str:
        """An approved line about one car, with that car's plate."""
        return " ".join(s.text for s in self._seg(key, plate=self.vehicles[index].plate))

    # ---- the scripted flow (INTERPRETER=rules) ----

    def _begin_body(self) -> Directive:
        self.state.body_started = True
        self.state.stage = "body"
        lead = [] if self.garage_call else self._seg("car_reason")
        return self._directive("car:0", [*lead, *self._ask(0)], expects="car")

    def _ask(self, index: int) -> list[Segment]:
        return [Segment(text=self.plate_line("car_ask", index))]

    def _body(self, signals: Signals) -> Directive:
        index = self.state.question_index
        row = self.result.vehicles[index]
        text = signals.text
        row.statement = text
        if not self.garage_call:
            row.status = "not_ready" if signals.negative and not re.search(r"\d", text) else "date_given"
            row.appointment_text = text if row.status == "date_given" else None
            self._task("garage_notify" if row.status == "date_given" else "callback", "นัดหมายเข้าซ่อม", text)
            ack = self._seg("car_date_ack" if row.status == "date_given" else "car_not_ready")
            return self._finish(ack)
        status = car_status(text, row.status)
        if status == "awaiting_customer" or (status is None and row.status == "not_asked" and not signals.affirm):
            row.status = "awaiting_customer"
            return self._directive(f"car:{index}:contacted", self._seg("car_ask_contacted"), expects="car")
        if status == "in_repair":
            row.status = "in_repair"
            return self._directive(f"car:{index}:completion", self._seg("car_ask_completion"), expects="car")
        if status == "booked":
            row.status = "booked"
            return self._directive(f"car:{index}:dates", self._seg("car_ask_dates"), expects="car")
        if status in ("customer_unreachable", "not_at_garage"):
            row.status = "not_at_garage" if status == "not_at_garage" else "customer_unreachable"
            self._task("customer_contact", f"อู่ติดต่อลูกค้าไม่ได้ ({row.plate})", text)
            ack = self._seg("car_unreachable")
        elif row.status == "in_repair":
            row.completion_text = text
            ack = self._seg("car_completion_ack")
        elif row.status == "booked":
            row.appointment_text = text
            ack = self._seg("car_dates_ack")
        else:
            row.status = "repaired"
            ack = self._seg("car_repaired")
        if index + 1 < len(self.vehicles):
            self.state.question_index = index + 1
            return self._directive(f"car:{index + 1}", [*ack, *self._ask(index + 1)], expects="car")
        return self._finish(ack)

    def _finish(self, ack: list[Segment]) -> Directive:
        self.state.outcome = self._complete_outcome()
        self.result.end_reason = "completed"
        return self._directive("closing", [*ack, *self._seg("closing")], end_call=True)

    def _complete_outcome(self) -> Outcome:
        open_rows = [r for r in self.result.vehicles if r.status == "not_asked"]
        return Outcome.FOLLOWUP_PARTIAL if open_rows else Outcome.FOLLOWUP_COMPLETED

    def _continue(self) -> Directive:
        return self._begin_body()

    def _reprompt_body(self) -> list[Segment]:
        return self._ask(self.state.question_index)

    def _partial_outcome(self) -> Outcome:
        return Outcome.FOLLOWUP_PARTIAL
