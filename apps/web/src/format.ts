import type { Call } from "./api";

export const CAMPAIGN_LABEL: Record<string, string> = {
  pa_confirmation: "ยืนยันกรมธรรม์ PA",
  accident_survey: "สำรวจความพึงพอใจ",
};

export const LIFECYCLE_STEPS = ["queued", "dispatching", "dialing", "ringing", "in_conversation", "ended"] as const;

export const LIFECYCLE_LABEL: Record<string, string> = {
  queued: "รอคิว",
  dispatching: "เตรียมโทร",
  dialing: "กำลังโทร",
  ringing: "เสียงเรียกเข้า",
  in_conversation: "กำลังสนทนา",
  ending: "กำลังจบสาย",
  ended: "จบแล้ว",
  reconciling: "ตรวจสอบสถานะ",
};

export const OUTCOME_LABEL: Record<string, string> = {
  policy_confirmed: "ยืนยันข้อมูลครบ",
  confirmed_with_discrepancy: "ยืนยันแล้ว มีข้อมูลไม่ตรง",
  policy_partial: "ทวนข้อมูลไม่ครบ",
  survey_completed: "ทำแบบสอบถามครบ",
  survey_partial: "แบบสอบถามไม่ครบ",
  callback_requested: "ขอให้ติดต่อกลับ",
  wrong_person: "ผิดคน",
  verification_failed: "ยืนยันตัวตนไม่สำเร็จ",
  refused: "ปฏิเสธการสนทนา",
  do_not_call: "ไม่ประสงค์ให้โทร",
  notice_objection: "ไม่ยินยอมให้บันทึก",
  no_response: "ไม่ตอบสนอง",
  hung_up_early: "วางสายก่อนเริ่ม",
  not_reached: "ติดต่อไม่ได้",
  canceled: "ยกเลิก",
  technical_failure: "ขัดข้องทางเทคนิค",
};

export type Tone = "good" | "warn" | "bad" | "neutral";

export function outcomeTone(outcome: string | null): Tone {
  if (!outcome) return "neutral";
  if (["policy_confirmed", "survey_completed"].includes(outcome)) return "good";
  if (["technical_failure", "verification_failed", "wrong_person", "do_not_call", "notice_objection"].includes(outcome))
    return "bad";
  if (outcome === "canceled") return "neutral";
  return "warn";
}

export const FIELD_STATUS_LABEL: Record<string, string> = {
  confirmed: "ยืนยัน",
  disputed: "ไม่ตรง",
  not_reviewed: "ยังไม่ได้ทวน",
  unclear: "ไม่ชัดเจน",
};

export const ANSWER_STATUS_LABEL: Record<string, string> = {
  answered: "ตอบแล้ว",
  not_applicable: "ไม่เกี่ยวข้อง (N/A)",
  skipped: "ขอข้าม",
  unanswered: "ไม่ได้คำตอบ",
  not_asked: "ยังไม่ได้ถาม",
};

export const DELIVERY_LABEL: Record<string, string> = {
  full: "พูดครบ",
  resumed_after_interruption: "พูดครบ (มีพูดแทรก)",
  not_delivered: "ยังไม่ได้พูด",
};

export const TASK_LABEL: Record<string, string> = {
  callback: "ติดต่อกลับ",
  policy_discrepancy: "ข้อมูลกรมธรรม์ไม่ตรง",
  question_follow_up: "คำถามรอคำตอบ",
  complaint: "ร้องเรียน",
  claim_dispute: "โต้แย้งเรื่องเคลม",
  safety: "ความปลอดภัย/ผู้บาดเจ็บ",
  urgent: "เร่งด่วน",
  unclear_answer: "คำตอบไม่ชัดเจน",
};

export const IDENTITY_LABEL: Record<string, string> = {
  not_reached: "ยังไม่ถึงขั้นยืนยัน",
  confirmed: "ยืนยันแล้ว",
  wrong_person: "ผิดคน",
  unclear: "ไม่ชัดเจน",
  failed: "ไม่สำเร็จ",
};

export function label(map: Record<string, string>, key: string | null | undefined): string {
  if (!key) return "—";
  return map[key] ?? key;
}

export function formatTime(iso: string | undefined | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("th-TH", {
    timeZone: "Asia/Bangkok",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString("th-TH", {
    timeZone: "Asia/Bangkok",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("th-TH", {
    timeZone: "Asia/Bangkok",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function elapsed(fromIso: string | undefined, toIso?: string): string {
  if (!fromIso) return "0:00";
  const end = toIso ? new Date(toIso).getTime() : Date.now();
  const seconds = Math.max(0, Math.floor((end - new Date(fromIso).getTime()) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** Index of the lifecycle step to highlight; terminal states map to the final step. */
export function stepIndex(lifecycle: string): number {
  if (lifecycle === "ending" || lifecycle === "reconciling") return LIFECYCLE_STEPS.indexOf("in_conversation");
  const i = LIFECYCLE_STEPS.indexOf(lifecycle as (typeof LIFECYCLE_STEPS)[number]);
  return i < 0 ? 0 : i;
}

const CASE_LABEL: Record<string, string> = {
  plan_name: "แผน",
  death_benefit_thb: "วงเงินคุ้มครองหลัก",
  medical_per_accident_thb: "ค่ารักษาต่อครั้ง",
  daily_hospital_thb: "ชดเชยรายวัน",
  premium_thb: "เบี้ยประกัน",
  effective_date: "เริ่มคุ้มครอง",
  beneficiary: "ผู้รับผลประโยชน์",
  payment_channel: "ชำระผ่าน",
  delivery_channel: "จัดส่งทาง",
  delivery_target: "ปลายทาง",
  case_id: "เลขเคส",
  accident_date: "วันที่เกิดเหตุ",
  surveyor_attended: "พนักงานสำรวจภัย",
};

export function caseSummary(c: Record<string, unknown>): [string, string][] {
  return Object.entries(CASE_LABEL)
    .filter(([key]) => key in c && (c[key] != null || key === "surveyor_attended"))
    .map(([key, name]) => {
      const v = c[key];
      if (key === "surveyor_attended") return [name, v === true ? "มีไปที่เกิดเหตุ" : v === false ? "ไม่มี" : "ไม่ทราบ"];
      if (key === "premium_thb" && typeof v === "number" && c.billing_period) {
        return [name, `${v.toLocaleString("th-TH")} บาทต่อ${String(c.billing_period)}`];
      }
      if (typeof v === "number") return [name, `${v.toLocaleString("th-TH")} บาท`];
      if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return [name, formatDate(`${v}T12:00:00+07:00`)];
      return [name, String(v)];
    });
}

export type StepState = "done" | "current" | "todo" | "failed";

export interface ProgressStep {
  label: string;
  state: StepState;
  detail?: string;
}

const DONE_ANSWER = new Set(["answered", "not_applicable", "skipped"]);
const FAILED_OUTCOMES = new Set([
  "wrong_person",
  "verification_failed",
  "refused",
  "do_not_call",
  "notice_objection",
  "no_response",
  "hung_up_early",
  "not_reached",
  "canceled",
  "technical_failure",
  "callback_requested",
]);

/** Where the conversation is in the campaign script, derived from the captured result. */
export function scriptProgress(call: Call): ProgressStep[] {
  const r = call.result;
  const ended = call.lifecycle === "ended";
  const raw: { label: string; done: boolean; detail?: string }[] = [
    { label: "ยืนยันตัวตน", done: r?.identity_result === "confirmed" },
    { label: "แจ้งการบันทึก", done: Boolean(r?.notice_delivered) },
  ];
  if (call.campaign === "pa_confirmation") {
    const fields = r?.policy_fields ?? [];
    const reviewed = fields.filter((f) => f.status !== "not_reviewed").length;
    raw.push({
      label: "ทวนข้อมูล",
      done: fields.length > 0 && reviewed === fields.length,
      detail: fields.length ? `${reviewed}/${fields.length}` : undefined,
    });
    raw.push({ label: "สิทธิยกเลิก", done: Boolean(r?.free_look_delivery) });
  } else {
    for (const a of r?.survey_answers ?? []) {
      raw.push({ label: a.question.toUpperCase(), done: DONE_ANSWER.has(a.status) });
    }
    raw.push({ label: "ความคิดเห็น", done: Boolean(r?.final_comment_raw) || call.outcome === "survey_completed" });
  }
  raw.push({ label: "จบสาย", done: ended });

  const failed = ended && call.outcome ? FAILED_OUTCOMES.has(call.outcome) || call.outcome.endsWith("_partial") : false;
  let currentAssigned = false;
  return raw.map((s) => {
    if (s.done) return { label: s.label, state: "done", detail: s.detail };
    if (!currentAssigned) {
      currentAssigned = true;
      return { label: s.label, state: failed ? "failed" : ended ? "todo" : "current", detail: s.detail };
    }
    return { label: s.label, state: "todo", detail: s.detail };
  });
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return parts
    .slice(0, 2)
    .map((p) => (p.match(/[ก-ฮA-Za-z0-9]/) ?? [Array.from(p)[0]])[0])
    .join("");
}
