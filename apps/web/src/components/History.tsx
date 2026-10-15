import { useEffect, useState } from "react";
import type { Api, Call } from "../api";
import { CAMPAIGN_LABEL, LIFECYCLE_LABEL, OUTCOME_LABEL, formatTime, label, outcomeTone } from "../format";
import { AlertIcon, ChevronRightIcon, ClockIcon, DownloadIcon, PhoneIcon } from "../icons";

interface Props {
  api: Api;
  refreshKey: number;
  onOpen: (id: string) => void;
  onGoCall: () => void;
}

function Status({ call }: { call: Call }) {
  if (call.outcome) return <span className={`pill ${outcomeTone(call.outcome)}`}>{label(OUTCOME_LABEL, call.outcome)}</span>;
  return <span className="pill neutral">{label(LIFECYCLE_LABEL, call.lifecycle)}</span>;
}

export function History({ api, refreshKey, onOpen, onGoCall }: Props) {
  const [calls, setCalls] = useState<Call[] | null>(null);
  const [campaign, setCampaign] = useState("");
  const [outcome, setOutcome] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    const load = () =>
      api.calls(campaign || undefined, outcome || undefined).then(
        (c) => {
          if (!stop) {
            setCalls(c);
            setError(null);
          }
        },
        (e: Error) => !stop && setError(e.message),
      );
    load();
    const id = setInterval(load, 5000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [api, campaign, outcome, refreshKey]);

  function exportFiltered() {
    const q = new URLSearchParams();
    if (campaign) q.set("campaign", campaign);
    if (outcome) q.set("outcome", outcome);
    api.download(`/api/v1/exports/calls.xlsx?${q}`, "kpi_calls.xlsx").catch((e: Error) => setError(e.message));
  }

  return (
    <>
      <div className="page-head page-head-row">
        <div>
          <h1>ประวัติการโทร</h1>
          <p>ผลของทุกสาย กดที่รายการเพื่อดูรายละเอียด</p>
        </div>
        <button className="btn btn-tinted" onClick={exportFiltered} disabled={!calls?.length}>
          <DownloadIcon size={16} />
          ดาวน์โหลด Excel{calls?.length ? ` (${calls.length})` : ""}
        </button>
      </div>

      <div className="toolbar">
        <div className="segmented" role="group" aria-label="กรองแคมเปญ">
          {[["", "ทั้งหมด"], ...Object.entries(CAMPAIGN_LABEL)].map(([k, v]) => (
            <button key={k} type="button" aria-pressed={campaign === k} onClick={() => setCampaign(k)}>
              {v}
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="filter-outcome">
          กรองผลลัพธ์
        </label>
        <select id="filter-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="">ทุกผลลัพธ์</option>
          {Object.entries(OUTCOME_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="alert err spaced" role="alert">
          <AlertIcon size={18} />
          {error}
        </div>
      )}

      {calls === null ? (
        <div className="skeleton" style={{ height: "14rem" }} aria-busy="true" />
      ) : calls.length === 0 ? (
        <div className="group">
          <div className="empty">
            <ClockIcon size={32} />
            <strong>{campaign || outcome ? "ไม่พบสายที่ตรงกับตัวกรอง" : "ยังไม่มีการโทร"}</strong>
            <span>{campaign || outcome ? "ลองเปลี่ยนตัวกรองด้านบน" : "สายที่โทรออกจะแสดงที่นี่พร้อมผลลัพธ์"}</span>
            {!campaign && !outcome && (
              <button className="btn btn-primary" onClick={onGoCall}>
                <PhoneIcon size={16} />
                เริ่มโทรสายแรก
              </button>
            )}
          </div>
        </div>
      ) : (
        <>
          <div className="group history-table">
            <table className="table">
              <thead>
                <tr>
                  <th>ผู้รับสาย</th>
                  <th>แคมเปญ</th>
                  <th>เวลา</th>
                  <th>ผลลัพธ์</th>
                  <th>งานติดตาม</th>
                  <th>
                    <span className="sr-only">เปิด</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {calls.map((c) => (
                  <tr key={c.call_id} onClick={() => onOpen(c.call_id)}>
                    <td>
                      <button
                        className="history-row who"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpen(c.call_id);
                        }}
                      >
                        {c.target_name}
                      </button>
                      <div className="muted num">{c.phone.display}</div>
                    </td>
                    <td>
                      {CAMPAIGN_LABEL[c.campaign]}
                      {c.mode === "simulation" && <div className="muted">จำลอง</div>}
                    </td>
                    <td className="muted num">{formatTime(c.created_at)}</td>
                    <td>
                      <Status call={c} />
                    </td>
                    <td className="num">{c.result?.tasks.length || "—"}</td>
                    <td className="chev-cell">
                      <ChevronRightIcon size={18} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="group history-list">
            {calls.map((c) => (
              <button key={c.call_id} className="row history-row" onClick={() => onOpen(c.call_id)}>
                <span className="choice-text grow">
                  <span className="choice-title">{c.target_name}</span>
                  <span className="choice-sub">{CAMPAIGN_LABEL[c.campaign]}</span>
                  <span className="choice-sub num nowrap">
                    {formatTime(c.created_at)}
                  </span>
                </span>
                <Status call={c} />
                <span className="row-trailing">
                  <ChevronRightIcon size={18} />
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </>
  );
}
