import type { Call } from "../api";
import { ANSWER_STATUS_LABEL, DELIVERY_LABEL, FIELD_STATUS_LABEL, IDENTITY_LABEL, TASK_LABEL, label } from "../format";

const FIELD_TONE: Record<string, string> = { confirmed: "good", disputed: "bad", unclear: "warn", not_reviewed: "neutral" };
const DELIVERY_TONE: Record<string, string> = { full: "good", resumed_after_interruption: "good", not_delivered: "neutral" };
const ANSWER_TONE: Record<string, string> = {
  answered: "good",
  not_applicable: "neutral",
  skipped: "warn",
  unanswered: "neutral",
  not_asked: "neutral",
};

/** What the call has captured so far, as a quiet key–value list. */
export function ResultView({ call, detailed = false }: { call: Call; detailed?: boolean }) {
  const r = call.result;
  if (!r) return <p className="empty">ยังไม่มีข้อมูล</p>;
  return (
    <div>
      <div className="kv">
        <div className="kv-row">
          <span className="kv-label">ยืนยันตัวตน</span>
          <span className="kv-value">
            <span className={`pill ${r.identity_result === "confirmed" ? "good" : r.identity_result === "not_reached" ? "neutral" : "bad"}`}>
              {label(IDENTITY_LABEL, r.identity_result)}
            </span>
          </span>
        </div>
        <div className="kv-row">
          <span className="kv-label">แจ้งการบันทึกเสียง</span>
          <span className="kv-value">
            <span className={`pill ${r.notice_delivered ? "good" : "neutral"}`}>{r.notice_delivered ? "แจ้งแล้ว" : "ยังไม่ได้แจ้ง"}</span>
            {r.recording_consent === true && <span className="pill good">ยินยอมบันทึกเสียง</span>}
            {r.recording_consent === false && <span className="pill warn">ไม่ยินยอม · บันทึกเฉพาะข้อความ</span>}
          </span>
        </div>
        {r.callback.requested && (
          <div className="kv-row">
            <span className="kv-label">ขอให้ติดต่อกลับ</span>
            <span className="kv-value">{r.callback.preferred_time_text || "ไม่ได้ระบุเวลา"}</span>
          </div>
        )}
        {r.free_look_delivery && (
          <div className="kv-row">
            <span className="kv-label">แจ้งสิทธิยกเลิกกรมธรรม์</span>
            <span className="kv-value">
              <span className={`pill ${DELIVERY_TONE[r.free_look_delivery] ?? "neutral"}`}>
                {label(DELIVERY_LABEL, r.free_look_delivery)}
              </span>
            </span>
          </div>
        )}
      </div>

      {r.policy_fields.length > 0 && (
        <>
          <h3 className="subhead">ข้อมูลกรมธรรม์</h3>
          <div className="kv">
            {r.policy_fields.map((f) => (
              <div className="kv-row" key={f.field}>
                <span className="kv-label">
                  {f.label}
                  {detailed && <small>{f.expected_value}</small>}
                  {f.customer_statement && <p className="quote">“{f.customer_statement}”</p>}
                </span>
                <span className="kv-value">
                  <span className={`pill ${FIELD_TONE[f.status] ?? "neutral"}`}>{label(FIELD_STATUS_LABEL, f.status)}</span>
                  {f.delivery === "resumed_after_interruption" && <small className="choice-sub">ถูกพูดแทรก แล้วพูดต่อ</small>}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {r.survey_answers.length > 0 && (
        <>
          <h3 className="subhead">คะแนน</h3>
          <div className="kv">
            {r.survey_answers.map((a) => (
              <div className="kv-row" key={a.question}>
                <span className="kv-label">
                  <strong>{a.question.toUpperCase()}</strong> {a.label}
                  {a.changed_from.length > 0 && <small>เปลี่ยนจาก {a.changed_from.join(" → ")}</small>}
                  {a.feedback_raw && <p className="quote">“{a.feedback_raw}”</p>}
                </span>
                <span className="kv-value">
                  {a.value !== null ? (
                    <span className="score">
                      {a.value}
                      <small>/{a.scale_max}</small>
                    </span>
                  ) : (
                    <span className={`pill ${ANSWER_TONE[a.status] ?? "neutral"}`}>{label(ANSWER_STATUS_LABEL, a.status)}</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {r.final_comment_raw && (
        <>
          <h3 className="subhead">ความคิดเห็นเพิ่มเติม (ตามคำพูดลูกค้า)</h3>
          <p className="quote">{r.final_comment_raw}</p>
        </>
      )}

      {r.tasks.length > 0 && (
        <>
          <h3 className="subhead">งานติดตาม · บันทึกไว้ ไม่มีการดำเนินการอัตโนมัติ</h3>
          <ul className="tasks">
            {r.tasks.map((t, i) => (
              <li key={i}>
                <span>
                  <span className="pill warn">{label(TASK_LABEL, t.type)}</span> {t.reason}
                </span>
                {detailed && t.detail_raw && <span className="quote">“{t.detail_raw}”</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
