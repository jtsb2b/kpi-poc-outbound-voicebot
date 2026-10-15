import { useEffect, useRef, useState } from "react";
import type { Api, Call } from "../api";
import {
  CAMPAIGN_LABEL,
  LIFECYCLE_LABEL,
  OUTCOME_LABEL,
  formatClock,
  formatDate,
  formatTime,
  label,
  outcomeTone,
} from "../format";
import { AlertIcon, ChevronDownIcon, CloseIcon, DownloadIcon, TrashIcon } from "../icons";
import { ResultView } from "./ResultView";
import { Transcript } from "./Transcript";

interface Props {
  api: Api;
  callId: string;
  onClose: () => void;
  onDeleted: () => void;
}

export function CallSheet({ api, callId, onClose, onDeleted }: Props) {
  const [call, setCall] = useState<Call | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    api.call(callId).then(setCall, (e: Error) => setError(e.message));
  }, [api, callId]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      previous?.focus();
    };
  }, [onClose]);

  async function remove() {
    if (!window.confirm("ลบสายนี้และบทสนทนาทั้งหมดอย่างถาวร?")) return;
    try {
      await api.remove(callId);
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <aside className="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <h2 id="sheet-title">{call?.target_name ?? "รายละเอียดการโทร"}</h2>
          {call?.outcome && <span className={`pill ${outcomeTone(call.outcome)}`}>{label(OUTCOME_LABEL, call.outcome)}</span>}
          <button ref={closeButton} className="icon-btn" onClick={onClose} aria-label="ปิด">
            <CloseIcon size={20} />
          </button>
        </div>
        <div className="sheet-body">
          {error && (
            <div className="alert err" role="alert">
              <AlertIcon size={18} />
              {error}
            </div>
          )}
          {!call && !error && <div className="skeleton" style={{ height: "16rem" }} aria-busy="true" />}
          {call && (
            <>
              <dl className="group info-grid">
                <div className="info-cell">
                  <dt>แคมเปญ</dt>
                  <dd>{CAMPAIGN_LABEL[call.campaign]}</dd>
                </div>
                <div className="info-cell">
                  <dt>สถานะ</dt>
                  <dd>{label(LIFECYCLE_LABEL, call.lifecycle)}</dd>
                </div>
                <div className="info-cell">
                  <dt>เบอร์โทร</dt>
                  <dd className="num">{call.phone.display}</dd>
                </div>
                <div className="info-cell">
                  <dt>เบอร์ที่โทรออก (SIP)</dt>
                  <dd className="num">{call.phone.sip_destination}</dd>
                </div>
                <div className="info-cell wide">
                  <dt>ข้อมูลที่ใช้</dt>
                  <dd>
                    <span className="pill mock">{call.data_label}</span>{" "}
                    {call.source.type === "import"
                      ? `${call.source.filename ?? "Excel"} แถว ${call.source.row_number}`
                      : call.source.label}
                  </dd>
                </div>
                <div className="info-cell wide">
                  <dt>วันที่</dt>
                  <dd>{formatDate(call.created_at)}</dd>
                </div>
                <div className="info-cell wide info-times">
                  {(
                    [
                      ["เริ่ม", call.created_at],
                      ["รับสาย", call.answered_at],
                      ["จบ", call.ended_at],
                    ] as const
                  ).map(([k, v]) => (
                    <div key={k}>
                      <dt>{k}</dt>
                      <dd className="num">{v ? formatClock(v) : "—"}</dd>
                    </div>
                  ))}
                </div>
              </dl>

              <section className="panel">
                <h3 className="panel-title">ผลการโทร</h3>
                <ResultView call={call} detailed />
              </section>

              <section className="panel">
                <h3 className="panel-title">
                  บทสนทนา
                  <span className="aside">{call.mode === "simulation" ? "สายจำลอง · เก็บเฉพาะข้อความ" : "บันทึกเสียงและข้อความ"}</span>
                </h3>
                {call.transcript_discarded ? (
                  <div className="alert info">ลูกค้าไม่ยินยอมให้บันทึก ระบบจึงไม่เก็บบทสนทนาและเสียงของสายนี้</div>
                ) : (
                  <Transcript turns={call.transcript ?? []} />
                )}
              </section>

              <details className="group disclosure">
                <summary className="row">
                  <span className="choice-title">เหตุการณ์ของระบบ</span>
                  <span className="row-trailing">
                    <ChevronDownIcon size={18} className="chev" />
                  </span>
                </summary>
                <div className="disclosure-body">
                  <dl className="facts">
                    {call.events?.map((e, i) => (
                      <div key={i} style={{ display: "contents" }}>
                        <dt className="num">{formatTime(e.at)}</dt>
                        <dd>{e.type}</dd>
                      </div>
                    ))}
                  </dl>
                  {call.end_reason && <p className="section-note">เหตุผลที่จบสาย: {call.end_reason}</p>}
                </div>
              </details>

              <div className="sheet-actions">
                {!call.active ? (
                  <button className="btn btn-danger" onClick={remove}>
                    <TrashIcon size={16} />
                    ลบสายนี้
                  </button>
                ) : (
                  <span />
                )}
                <button
                  className="btn btn-primary"
                  onClick={() =>
                    api
                      .download(`/api/v1/exports/calls.xlsx?call_id=${call.call_id}`, "kpi_call.xlsx")
                      .catch((e: Error) => setError(e.message))
                  }
                >
                  <DownloadIcon size={16} />
                  ดาวน์โหลด Excel
                </button>
              </div>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
