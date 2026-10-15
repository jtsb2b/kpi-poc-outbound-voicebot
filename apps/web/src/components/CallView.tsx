import { useEffect, useState } from "react";
import type { Api, Call } from "../api";
import {
  CAMPAIGN_LABEL,
  LIFECYCLE_LABEL,
  OUTCOME_LABEL,
  elapsed,
  initials,
  label,
  outcomeTone,
  scriptProgress,
} from "../format";
import { AlertIcon, CheckIcon, DownloadIcon, ListIcon, PhoneIcon, PhoneOffIcon } from "../icons";
import { ResultView } from "./ResultView";
import { Transcript } from "./Transcript";

const TONE_ICON = { good: CheckIcon, warn: PhoneIcon, bad: AlertIcon, neutral: PhoneOffIcon };

interface Props {
  api: Api;
  call: Call;
  onNewCall: () => void;
  onOpenDetail: (id: string) => void;
}

/** The live call, shown like a phone call: who, how long, where in the script, and what was said. */
export function CallView({ api, call, onNewCall, onOpenDetail }: Props) {
  const [, tick] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!call.active) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [call.active]);

  const ended = call.lifecycle === "ended";
  const talking = call.lifecycle === "in_conversation";
  const tone = outcomeTone(call.outcome);
  const ToneIcon = TONE_ICON[tone];
  const steps = scriptProgress(call);
  const taskCount = call.result?.tasks.length ?? 0;
  const timer = call.answered_at ? elapsed(call.answered_at, call.ended_at) : "0:00";

  return (
    <div className="call-screen">
      <section className="call-head" aria-label="สถานะการโทร">
        <div className="call-who">
          <span className="avatar" aria-hidden="true">
            {initials(call.target_name)}
          </span>
          <div className="call-id">
            <div className="call-name">{call.target_name}</div>
            <div className="call-meta num">
              {call.phone.display} · {CAMPAIGN_LABEL[call.campaign]}
              {call.mode === "simulation" ? " · จำลอง" : ""}
            </div>
          </div>
          <div className="call-status" aria-live="polite">
            <span className="call-timer" aria-label={`เวลาสนทนา ${timer}`}>
              {timer}
            </span>
            <span className="call-state">
              <span className={`live-dot ${talking ? "" : "idle"}`} aria-hidden="true" />
              {ended ? "วางสายแล้ว" : label(LIFECYCLE_LABEL, call.lifecycle)}
            </span>
          </div>
          {!ended && (
            <div className="hangup-dock">
              <button
                className="btn btn-danger"
                disabled={call.cancel_requested}
                onClick={() => api.cancel(call.call_id).catch((e: Error) => setError(e.message))}
              >
                <PhoneOffIcon size={16} />
                {call.cancel_requested ? "กำลังวางสาย…" : "วางสาย"}
              </button>
            </div>
          )}
        </div>
        <ol className="progress" aria-label="ความคืบหน้าตามบทสนทนา">
          {steps.map((s) => (
            <li key={s.label} className={s.state} aria-current={s.state === "current" ? "step" : undefined}>
              <span className="bar" />
              <span className="label">
                {s.label}
                {s.detail ? ` ${s.detail}` : ""}
              </span>
            </li>
          ))}
        </ol>
      </section>

      {ended && call.outcome ? (
        <section className={`outcome ${tone}`} aria-live="polite">
          <span className="outcome-icon">
            <ToneIcon size={22} />
          </span>
          <div className="outcome-text">
            <span className="outcome-title">{label(OUTCOME_LABEL, call.outcome)}</span>
            <span className="outcome-sub">
              {taskCount > 0 ? `มีงานติดตาม ${taskCount} รายการ` : "ไม่มีงานติดตาม"}
              {call.transcript_discarded ? " · ไม่เก็บบทสนทนาตามที่ลูกค้าขอ" : ""}
            </span>
          </div>
          <div className="outcome-actions">
            <button
              className="btn btn-plain"
              onClick={() =>
                api
                  .download(`/api/v1/exports/calls.xlsx?call_id=${call.call_id}`, "kpi_call.xlsx")
                  .catch((e: Error) => setError(e.message))
              }
            >
              <DownloadIcon size={16} />
              Excel
            </button>
            <button className="btn btn-tinted" onClick={() => onOpenDetail(call.call_id)}>
              <ListIcon size={16} />
              ดูรายละเอียด
            </button>
            <button className="btn btn-primary" onClick={onNewCall}>
              <PhoneIcon size={16} />
              โทรครั้งใหม่
            </button>
          </div>
        </section>
      ) : null}

      {error && (
        <div className="alert err" role="alert">
          <AlertIcon size={18} />
          {error}
        </div>
      )}
      {call.warnings?.map((w) => (
        <div key={w} className="alert warn">
          <AlertIcon size={18} />
          {w}
        </div>
      ))}

      <div className="call-body">
        <section className="panel" aria-labelledby="conv-title">
          <h2 className="panel-title" id="conv-title">
            บทสนทนา
            <span className="aside">{call.mode === "simulation" ? "สายจำลอง · เก็บเฉพาะข้อความ" : "บันทึกเสียงและข้อความ"}</span>
          </h2>
          {call.transcript_discarded ? (
            <div className="alert info">ลูกค้าไม่ยินยอมให้บันทึก ระบบจึงไม่เก็บบทสนทนาและเสียงของสายนี้</div>
          ) : (
            <Transcript turns={call.transcript ?? []} follow waiting={talking} />
          )}
        </section>
        <section className="panel" aria-labelledby="cap-title">
          <h2 className="panel-title" id="cap-title">
            ข้อมูลที่ได้
          </h2>
          <ResultView call={call} />
        </section>
      </div>
    </div>
  );
}
