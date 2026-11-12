import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { Api, Dashboard as Data, DashboardVehicle } from "../api";
import {
  CAMPAIGN_LABEL,
  OUTCOME_LABEL,
  REPAIR_STATUS_LABEL,
  formatTime,
  hoursMinutes,
  label,
  minutesSeconds,
  outcomeTone,
  percent,
  reasonLabel,
  repairTone,
} from "../format";
import { AlertIcon, ChartIcon, ChevronRightIcon } from "../icons";
import { BarList, LineOverDays, Legend, StackedColumns, dayLabel, type Series } from "./Charts";

/** The voicebot at a glance, for KPI (demo feedback of 4 Nov 2026): how many calls, how many reached,
 * time on the phone, who needs a call back and why, the satisfaction score and every car's status. */

const PERIODS: [number | null, string][] = [
  [1, "วันนี้"],
  [7, "7 วัน"],
  [30, "30 วัน"],
  [null, "ทั้งหมด"],
];

const DAILY: Series[] = [
  { key: "completed", label: "สำเร็จตามวัตถุประสงค์", color: "var(--series-1)" },
  { key: "reached_not_completed", label: "ติดต่อได้ ยังไม่ครบ", color: "var(--series-2)" },
  { key: "not_reached", label: "ติดต่อไม่ได้", color: "var(--series-3)" },
];

interface Props {
  api: Api;
  refreshKey: number;
  onOpen: (id: string) => void;
}

function Tile({ title, value, unit, sub }: { title: string; value: string; unit?: string; sub?: string }) {
  return (
    <div className="group stat">
      <span className="stat-title">{title}</span>
      <span className="stat-value">
        {value}
        {unit && <span className="stat-unit">{unit}</span>}
      </span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  );
}

function Card({ title, note, children, wide }: { title: string; note?: string; children: ReactNode; wide?: boolean }) {
  return (
    <section className={`group card${wide ? " card-wide" : ""}`}>
      <header className="card-head">
        <h2>{title}</h2>
        {note && <p>{note}</p>}
      </header>
      {children}
    </section>
  );
}

function carDates(v: DashboardVehicle): string[] {
  const pick = (date?: string | null, text?: string | null) => date || text;
  return [
    ["คาดว่าซ่อมเสร็จ", pick(v.completion_date, v.completion_text)],
    ["นัดเข้าซ่อม", pick(v.appointment_date, v.appointment_text)],
    ["รับรถ", pick(v.pickup_date, v.pickup_text)],
  ]
    .filter(([, value]) => value)
    .map(([name, value]) => `${name}: ${value}`);
}

function claimLine(v: DashboardVehicle): string | null {
  if (v.campaign !== "garage_followup") return null;
  if (v.status === "repaired") return "แจ้งอู่ตั้งเบิกเคลมแล้ว";
  if (v.status === "not_at_garage") return "ให้เจ้าหน้าที่ตรวจสอบเคลม";
  return null;
}

export function Dashboard({ api, refreshKey, onOpen }: Props) {
  const [days, setDays] = useState<number | null>(30);
  const [campaign, setCampaign] = useState("");
  const [simulations, setSimulations] = useState(false);
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    const load = () =>
      api.dashboard(days, campaign || undefined, simulations).then(
        (d) => {
          if (!stop) {
            setData(d);
            setError(null);
          }
        },
        (e: Error) => !stop && setError(e.message),
      );
    load();
    const id = setInterval(load, 30000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [api, days, campaign, simulations, refreshKey]);

  const reasons = useMemo(() => {
    const counts = new Map<string, number>();
    for (const f of data?.follow_ups ?? []) {
      for (const type of new Set(f.reasons.map((r) => r.type))) counts.set(type, (counts.get(type) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [data]);
  const followUps = (data?.follow_ups ?? []).filter((f) => !reason || f.reasons.some((r) => r.type === reason));

  const t = data?.totals;
  const sat = data?.satisfaction;
  const period = data && (data.start === data.end ? dayLabel(data.start) : `${dayLabel(data.start)} – ${dayLabel(data.end)}`);
  const maxOutcome = Math.max(1, ...(data?.outcomes ?? []).map((o) => o.count));
  const maxReason = Math.max(1, ...reasons.map(([, n]) => n));
  const overdue = (data?.vehicles ?? []).filter((v) => v.overdue).length;
  const showCars = !campaign || campaign === "garage_followup" || campaign === "repair_appointment";

  return (
    <>
      <div className="page-head">
        <h1>ภาพรวม</h1>
        <p>
          {period ? `${period} · ` : ""}
          {simulations ? "รวมสายจำลอง" : "เฉพาะสายโทรจริง"} · ไม่นับสายที่เจ้าหน้าที่ยกเลิก
        </p>
      </div>

      <div className="toolbar">
        <div className="segmented" role="group" aria-label="ช่วงเวลา">
          {PERIODS.map(([d, name]) => (
            <button key={name} type="button" aria-pressed={days === d} onClick={() => setDays(d)}>
              {name}
            </button>
          ))}
        </div>
        <div className="segmented scroll-x" role="group" aria-label="กรองแคมเปญ">
          {[["", "ทุกแคมเปญ"], ...Object.entries(CAMPAIGN_LABEL)].map(([k, v]) => (
            <button key={k} type="button" aria-pressed={campaign === k} onClick={() => setCampaign(k)}>
              {v}
            </button>
          ))}
        </div>
        <label className="toggle-check">
          <input type="checkbox" checked={simulations} onChange={(e) => setSimulations(e.target.checked)} />
          รวมสายจำลอง
        </label>
      </div>

      {error && (
        <div className="alert err spaced" role="alert">
          <AlertIcon size={18} />
          {error}
        </div>
      )}

      {!data || !t || !sat ? (
        <div className="skeleton" style={{ height: "24rem" }} aria-busy="true" />
      ) : t.calls === 0 ? (
        <div className="group">
          <div className="empty">
            <ChartIcon size={32} />
            <strong>ยังไม่มีสายในช่วงนี้</strong>
            <span>ลองเลือกช่วงเวลาที่ยาวขึ้น หรือแคมเปญอื่น</span>
          </div>
        </div>
      ) : (
        <div className="dash">
          <div className="stats">
            <Tile title="สายที่โทรออก" value={t.calls.toLocaleString("th-TH")} sub={t.canceled ? `ยกเลิก ${t.canceled} สาย (ไม่นับ)` : undefined} />
            <Tile title="ติดต่อได้" value={percent(t.contact_rate)} sub={`${t.reached} สาย · ไม่ได้ ${t.not_reached} สาย`} />
            <Tile title="สำเร็จตามวัตถุประสงค์" value={percent(t.success_rate)} sub={`${t.completed} จาก ${t.calls} สาย`} />
            <Tile title="เวลาสนทนารวม" value={(t.talk_seconds / 3600).toLocaleString("th-TH", { maximumFractionDigits: 1 })} unit="ชั่วโมง" sub={`${hoursMinutes(t.talk_seconds)} จาก ${t.reached} สาย`} />
            <Tile title="เฉลี่ยต่อเคส" value={minutesSeconds(t.average_talk_seconds)} unit="นาที" sub="นับจากรับสายถึงวางสาย" />
            <Tile
              title="ความพึงพอใจ (CSAT)"
              value={percent(sat.csat)}
              sub={sat.average != null ? `ตอบ 4–5 · เฉลี่ย ${sat.average.toFixed(2)}/5` : "ยังไม่มีคำตอบ"}
            />
          </div>

          <div className="cards">
            <Card title="สายรายวัน" note="แยกตามผลการโทร ชี้ที่แท่งเพื่อดูตัวเลข" wide>
              <Legend series={DAILY} />
              <StackedColumns rows={data.daily} series={DAILY} ariaLabel="จำนวนสายต่อวัน แยกตามผลการโทร" />
            </Card>
            <Card title="สถานะการโทร" note="ผลลัพธ์ของทุกสาย">
              <BarList
                color="var(--series-1)"
                rows={data.outcomes.map((o) => ({
                  key: o.outcome,
                  label: <span className={`tone-dot ${outcomeTone(o.outcome)}`}>{label(OUTCOME_LABEL, o.outcome)}</span>,
                  value: o.count,
                  share: o.count / maxOutcome,
                  display: o.count.toLocaleString("th-TH"),
                }))}
              />
            </Card>
          </div>

          <Card title="แยกตามแคมเปญ" note="เวลาเฉลี่ยของเจ้าหน้าที่ตามที่ KPI แจ้งในการประชุมวันที่ 4 พ.ย. 2569" wide>
            <div className="table-scroll">
              <table className="table compact">
                <thead>
                  <tr>
                    <th>แคมเปญ</th>
                    <th className="r">สาย</th>
                    <th className="r">ติดต่อได้</th>
                    <th className="r">สำเร็จ</th>
                    <th className="r">เวลาสนทนารวม</th>
                    <th className="r">เฉลี่ยต่อเคส</th>
                    <th className="r">เจ้าหน้าที่ (อ้างอิง)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.campaigns
                    .filter((c) => c.calls > 0)
                    .map((c) => (
                      <tr key={c.campaign} onClick={() => setCampaign(c.campaign)} title="ดูเฉพาะแคมเปญนี้">
                        <td className="who">{CAMPAIGN_LABEL[c.campaign]}</td>
                        <td className="r num">{c.calls}</td>
                        <td className="r num">{percent(c.contact_rate)}</td>
                        <td className="r num">{percent(c.success_rate)}</td>
                        <td className="r num">{hoursMinutes(c.talk_seconds)}</td>
                        <td className="r num">{minutesSeconds(c.average_talk_seconds)}</td>
                        <td className="r num muted">
                          {c.staff_minutes[0] === c.staff_minutes[1]
                            ? `${c.staff_minutes[0]} นาที`
                            : `${c.staff_minutes[0]}–${c.staff_minutes[1]} นาที`}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </Card>

          {sat.responses > 0 && (
            <div className="cards">
              <Card
                title="คะแนนความพึงพอใจสะสม"
                note={`ค่าเฉลี่ยสะสมของข้อที่ให้คะแนน 1–5 · ${sat.responses} คำตอบจาก ${sat.surveys} สาย`}
                wide
              >
                <LineOverDays
                  points={sat.trend.map((d) => ({ date: d.date, value: d.cumulative_average }))}
                  min={1}
                  max={5}
                  color="var(--series-1)"
                  format={(v) => v.toFixed(2)}
                  ariaLabel="คะแนนความพึงพอใจเฉลี่ยสะสมรายวัน"
                  tip={(i) => {
                    const d = sat.trend[i];
                    return (
                      <>
                        <strong>{dayLabel(d.date, true)}</strong>
                        <span className="tip-row">
                          สะสม<b className="num">{d.cumulative_average?.toFixed(2) ?? "—"}</b>
                        </span>
                        <span className="tip-row">
                          CSAT สะสม<b className="num">{percent(d.cumulative_csat)}</b>
                        </span>
                        <span className="tip-row">
                          วันนี้<b className="num">{d.responses ? `${d.day_average?.toFixed(2)} (${d.responses} คำตอบ)` : "ไม่มีคำตอบ"}</b>
                        </span>
                      </>
                    );
                  }}
                />
              </Card>
              <Card title="คะแนนรายข้อ" note="ค่าเฉลี่ย เทียบกับคะแนนเต็มของแต่ละข้อ">
                <BarList
                  stacked
                  color="var(--series-1)"
                  rows={sat.questions.map((q) => ({
                    key: q.question,
                    label: (
                      <>
                        <span className="q-id">{q.question.toUpperCase()}</span> {q.label}
                      </>
                    ),
                    value: q.average,
                    share: (q.average - q.scale_min) / (q.scale_max - q.scale_min),
                    display: `${q.average.toFixed(1)}/${q.scale_max}`,
                    title: `${q.responses} คำตอบ · ${q.distribution.map((d) => `${d.value}: ${d.count}`).join(" · ")}`,
                  }))}
                />
              </Card>
            </div>
          )}

          <Card
            title={`เคสที่ต้องติดต่อกลับ (${data.follow_ups.length})`}
            note="สายที่ลูกค้าขอให้ติดต่อกลับ ติดต่อไม่ได้ หรือมีงานให้เจ้าหน้าที่ตามต่อ กดเหตุผลเพื่อกรอง"
            wide
          >
            {data.follow_ups.length === 0 ? (
              <p className="card-empty">ไม่มีเคสค้าง</p>
            ) : (
              <div className="follow">
                <BarList
                  color="var(--series-2)"
                  selected={reason}
                  onSelect={(k) => setReason((r) => (r === k ? null : k))}
                  rows={reasons.map(([type, n]) => ({
                    key: type,
                    label: reasonLabel(type),
                    value: n,
                    share: n / maxReason,
                    display: `${n}`,
                  }))}
                />
                <div className="table-scroll">
                  <table className="table compact">
                    <thead>
                      <tr>
                        <th>ผู้รับสาย</th>
                        <th>เหตุผล</th>
                        <th>สะดวกให้ติดต่อ</th>
                        <th>
                          <span className="sr-only">เปิด</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {followUps.slice(0, 50).map((f) => (
                        <tr key={f.call_id} onClick={() => onOpen(f.call_id)}>
                          <td>
                            <button
                              className="history-row who"
                              onClick={(e) => {
                                e.stopPropagation();
                                onOpen(f.call_id);
                              }}
                            >
                              {f.target_name}
                            </button>
                            <div className="muted">
                              {CAMPAIGN_LABEL[f.campaign]} · <span className="num">{formatTime(f.at)}</span>
                            </div>
                          </td>
                          <td>
                            <ul className="reasons">
                              {f.reasons.map((r, i) => (
                                <li key={i}>
                                  <span className="pill neutral">{reasonLabel(r.type)}</span> {r.text}
                                </li>
                              ))}
                            </ul>
                          </td>
                          <td>
                            {f.callback_date || f.callback_time_text || <span className="muted">—</span>}
                            {f.callback_date && f.callback_time_text && <div className="muted">“{f.callback_time_text}”</div>}
                          </td>
                          <td className="chev-cell">
                            <ChevronRightIcon size={18} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {followUps.length > 50 && <p className="section-note">แสดง 50 เคสล่าสุดจาก {followUps.length}</p>}
              </div>
            )}
          </Card>

          {showCars && data.vehicles.length > 0 && (
            <Card
              title="สถานะรถจากการติดตามอู่และนัดเข้าซ่อม"
              note={`สถานะล่าสุดของรถแต่ละคัน วันที่คำนวณจากวันที่โทร${overdue ? ` · ${overdue} คันเลยวันที่อู่แจ้งว่าจะซ่อมเสร็จ ควรโทรถามอู่อีกครั้ง` : ""}`}
              wide
            >
              <div className="table-scroll">
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>ทะเบียน</th>
                      <th>อู่</th>
                      <th>สถานะ</th>
                      <th>วันที่</th>
                      <th>
                        <span className="sr-only">เปิด</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.vehicles.map((v) => {
                      const dates = carDates(v);
                      const claim = claimLine(v);
                      return (
                        <tr key={v.plate} onClick={() => onOpen(v.call_id)}>
                          <td>
                            <div className="who">{v.plate}</div>
                            <div className="muted">{[v.car, v.claim_no].filter(Boolean).join(" · ")}</div>
                          </td>
                          <td>
                            {v.garage_name ? `อู่${v.garage_name}` : "—"}
                            {v.customer_name && <div className="muted">คุณ{v.customer_name}</div>}
                          </td>
                          <td>
                            <span className={`pill ${repairTone(v.status)}`}>{label(REPAIR_STATUS_LABEL, v.status)}</span>
                            {v.overdue && (
                              <div>
                                <span className="pill bad">
                                  <AlertIcon size={13} />
                                  เลยวันที่อู่แจ้งว่าจะเสร็จ
                                </span>
                              </div>
                            )}
                            {claim && <div className="muted">{claim}</div>}
                          </td>
                          <td>
                            {dates.length ? dates.map((d) => <div key={d}>{d}</div>) : <span className="muted">—</span>}
                            <div className="muted num">โทรล่าสุด {formatTime(v.at)}</div>
                          </td>
                          <td className="chev-cell">
                            <ChevronRightIcon size={18} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
