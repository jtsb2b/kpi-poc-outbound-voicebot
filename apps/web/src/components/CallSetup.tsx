import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  IdempotencyKeys,
  type Api,
  type Call,
  type Campaign,
  type CampaignId,
  type ImportResult,
  type PhoneCheck,
  type SystemStatus,
} from "../api";
import { caseSummary } from "../format";
import {
  AlertIcon,
  CheckIcon,
  ChevronDownIcon,
  DownloadIcon,
  FileIcon,
  FlaskIcon,
  PhoneIcon,
  ShieldCheckIcon,
  StarIcon,
  UploadIcon,
} from "../icons";

type SourceKind = "profile" | "import";
type ScriptKind = "scenario" | "custom";
type Mode = "simulation" | "live";

export interface Draft {
  campaignId: CampaignId;
  name: string;
  phone: string;
}

interface Props {
  draft: Draft;
  onDraft: (draft: Draft) => void;
  api: Api;
  campaigns: Campaign[] | null;
  status: SystemStatus | null;
  busy: boolean;
  onShowActive: () => void;
  onCreated: (call: Call) => void;
}

const CAMPAIGN_COPY: Record<
  CampaignId,
  { title: string; sub: string; Icon: typeof ShieldCheckIcon }
> = {
  pa_confirmation: {
    title: "ยืนยันกรมธรรม์ PA",
    sub: "ทวนข้อมูลกรมธรรม์ที่ลูกค้าเพิ่งซื้อ",
    Icon: ShieldCheckIcon,
  },
  accident_survey: {
    title: "สำรวจความพึงพอใจ",
    sub: "หลังใช้บริการรับแจ้งอุบัติเหตุรถยนต์",
    Icon: StarIcon,
  },
};

/** +6621004148 → 02-100-4148 */
function callerDisplay(e164: string): string {
  const national = e164.startsWith("+66") ? `0${e164.slice(3)}` : e164;
  return national.length === 9 && national.startsWith("02")
    ? `${national.slice(0, 2)}-${national.slice(2, 5)}-${national.slice(5)}`
    : national;
}

const CUSTOM_HINT =
  "พิมพ์คำตอบของลูกค้าทีละบรรทัด\n[SILENCE] = เงียบ · [HANGUP] = วางสาย · [INTERRUPT:1] ข้อความ = พูดแทรก";

export function CallSetup({
  draft,
  onDraft,
  api,
  campaigns,
  status,
  busy,
  onShowActive,
  onCreated,
}: Props) {
  const [campaignId, setCampaignId] = useState<CampaignId>(draft.campaignId);
  const [name, setName] = useState(draft.name);
  const [phone, setPhone] = useState(draft.phone);

  useEffect(
    () => onDraft({ campaignId, name, phone }),
    [campaignId, name, phone, onDraft],
  );
  const [phoneCheck, setPhoneCheck] = useState<PhoneCheck | null>(null);
  const [sourceKind, setSourceKind] = useState<SourceKind>("profile");
  const [profileId, setProfileId] = useState("");
  const [imported, setImported] = useState<ImportResult | null>(null);
  const [rowNumber, setRowNumber] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [scriptKind, setScriptKind] = useState<ScriptKind>("scenario");
  const [modeChoice, setModeChoice] = useState<Mode>("simulation");
  const [scenarioId, setScenarioId] = useState("");
  const [customScript, setCustomScript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const keys = useRef(new IdempotencyKeys());
  const fileInput = useRef<HTMLInputElement>(null);

  const campaign = campaigns?.find((c) => c.id === campaignId);

  useEffect(() => {
    if (!campaign) return;
    setProfileId(campaign.profiles[0]?.profile_id ?? "");
    setImported(null);
    setRowNumber(null);
  }, [campaign]);

  // The default scenario follows the chosen mock profile, so test mode can stay closed.
  useEffect(() => {
    if (!campaign) return;
    const match =
      campaign.scenarios.find((s) => s.profile === profileId) ??
      campaign.scenarios[0];
    setScenarioId(match?.id ?? "");
  }, [campaign, profileId]);

  useEffect(() => {
    const value = phone.trim();
    if (value.length < 3) {
      setPhoneCheck(null);
      return;
    }
    const id = setTimeout(
      () =>
        api.checkPhone(value).then(setPhoneCheck, () => setPhoneCheck(null)),
      300,
    );
    return () => clearTimeout(id);
  }, [api, phone]);

  const scenarios = useMemo(() => campaign?.scenarios ?? [], [campaign]);
  const scenario = scenarios.find((s) => s.id === scenarioId);
  const record =
    sourceKind === "profile"
      ? campaign?.profiles.find((p) => p.profile_id === profileId)?.case
      : (imported?.rows.find((r) => r.row_number === rowNumber)?.record ??
        undefined);

  const phoneOk = Boolean(phoneCheck?.valid && phoneCheck.dialable);
  const live = Boolean(status?.telephony_ready);
  const mode: Mode = live ? modeChoice : "simulation";
  const scriptOk =
    mode === "live" ||
    (scriptKind === "scenario"
      ? Boolean(scenarioId)
      : customScript.trim().length > 0);
  const offHours =
    mode === "live" && status ? !status.within_calling_hours : false;
  const missing = !name.trim()
    ? "กรอกชื่อผู้รับสาย"
    : !phoneOk
      ? "กรอกเบอร์โทรให้ถูกต้อง"
      : !record
        ? "เลือกข้อมูลประกอบการโทร"
        : offHours
          ? `อยู่นอกเวลาโทร (${status?.calling_hours})`
          : null;
  const canCall = Boolean(
    campaign && !missing && scriptOk && !busy && !submitting,
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canCall) return;
    setSubmitting(true);
    setError(null);
    const payload = {
      campaign: campaignId,
      target_name: name.trim(),
      phone: phone.trim(),
      mode,
      source:
        sourceKind === "profile"
          ? { type: "profile", profile_id: profileId }
          : {
              type: "import",
              import_id: imported?.import_id,
              row_number: rowNumber,
            },
      scenario_id:
        mode === "simulation" && scriptKind === "scenario" ? scenarioId : null,
      custom_script:
        mode === "simulation" && scriptKind === "custom"
          ? customScript.split("\n").filter((l) => l.trim())
          : null,
    };
    try {
      const call = await api.createCall(payload, keys.current.keyFor(payload));
      keys.current.reset();
      onCreated(call);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const result = await api.upload(campaignId, file);
      setImported(result);
      setRowNumber(result.rows.find((r) => r.record)?.row_number ?? null);
    } catch (err) {
      setError((err as Error).message);
      setImported(null);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const phoneHint = !phoneCheck
    ? { tone: "", text: "รองรับ 08x-xxx-xxxx, 66… และ +66…" }
    : !phoneCheck.valid || !phoneCheck.dialable
      ? { tone: "err", text: phoneCheck.message ?? "หมายเลขไม่ถูกต้อง" }
      : { tone: "ok", text: `จะโทรไปที่ ${phoneCheck.display}` };

  if (!campaigns) {
    return (
      <div aria-busy="true">
        <div
          className="skeleton"
          style={{ height: "3rem", width: "40%", marginBottom: "1.5rem" }}
        />
        <div
          className="skeleton"
          style={{ height: "7rem", marginBottom: "1.75rem" }}
        />
        <div className="skeleton" style={{ height: "7rem" }} />
      </div>
    );
  }

  return (
    <form onSubmit={submit} noValidate>
      <div className="page-head">
        <h1>โทรออก</h1>
        <p>เลือกแคมเปญ กรอกผู้รับสาย แล้วกดโทร น้องเคพีไอจะคุยแทนให้</p>
      </div>

      {live && (
        <div className="section">
          <div
            className="segmented block"
            role="group"
            aria-label="รูปแบบการโทร"
          >
            <button
              type="button"
              aria-pressed={mode === "simulation"}
              onClick={() => setModeChoice("simulation")}
            >
              จำลอง
            </button>
            <button
              type="button"
              aria-pressed={mode === "live"}
              onClick={() => setModeChoice("live")}
            >
              โทรจริง
            </button>
          </div>
          {mode === "live" && (
            <p className="section-note">
              โทรออกจริงผ่านระบบโทรศัพท์
              {status?.caller_id
                ? ` · ลูกค้าจะเห็นเบอร์ ${callerDisplay(status.caller_id)}`
                : ""}{" "}
              · โทรครั้งเดียว ไม่โทรซ้ำอัตโนมัติ
            </p>
          )}
        </div>
      )}

      {busy && (
        <div className="section">
          <div className="alert info">
            <PhoneIcon size={18} />
            <span>
              มีสายที่กำลังดำเนินการอยู่ รอให้จบก่อนโทรสายใหม่{" "}
              <button
                type="button"
                className="btn btn-plain"
                onClick={onShowActive}
              >
                ดูสายนี้
              </button>
            </span>
          </div>
        </div>
      )}

      <section className="section" aria-labelledby="s-campaign">
        <h2 className="section-title" id="s-campaign">
          แคมเปญ
        </h2>
        <div className="tiles" role="radiogroup" aria-labelledby="s-campaign">
          {campaigns.map((c) => {
            const copy = CAMPAIGN_COPY[c.id];
            const selected = c.id === campaignId;
            return (
              <button
                key={c.id}
                type="button"
                role="radio"
                aria-checked={selected}
                className="tile"
                onClick={() => setCampaignId(c.id)}
              >
                <span className="tile-icon">
                  <copy.Icon size={22} />
                </span>
                <span className="tile-title">{copy.title}</span>
                <span className="tile-sub">{copy.sub}</span>
                <span className="tile-check">
                  <CheckIcon size={14} strokeWidth={2.5} />
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="section" aria-labelledby="s-who">
        <h2 className="section-title" id="s-who">
          ผู้รับสาย
        </h2>
        <div className="group">
          <label className="row field" htmlFor="name">
            <span className="row-label">ชื่อ-นามสกุล</span>
            <input
              id="name"
              className="row-input"
              type="text"
              autoComplete="off"
              placeholder="เช่น สมชาย ใจดี"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="row field" htmlFor="phone">
            <span className="row-label">เบอร์โทร</span>
            <input
              id="phone"
              className="row-input num"
              type="tel"
              inputMode="tel"
              autoComplete="off"
              placeholder="081 234 5678"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              aria-invalid={phoneCheck ? !phoneOk : undefined}
              aria-describedby="phone-hint"
            />
          </label>
        </div>
        <p
          id="phone-hint"
          className={`field-hint ${phoneHint.tone}`}
          aria-live="polite"
        >
          {phoneHint.text}
        </p>
      </section>

      <section className="section" aria-labelledby="s-record">
        <div className="section-head">
          <h2 className="section-title" id="s-record">
            ข้อมูลประกอบการโทร
          </h2>
          <div className="segmented" role="group" aria-label="แหล่งข้อมูล">
            <button
              type="button"
              aria-pressed={sourceKind === "profile"}
              onClick={() => setSourceKind("profile")}
            >
              ข้อมูลตัวอย่าง
            </button>
            <button
              type="button"
              aria-pressed={sourceKind === "import"}
              onClick={() => setSourceKind("import")}
            >
              ไฟล์ Excel
            </button>
          </div>
        </div>

        {sourceKind === "profile" ? (
          <fieldset className="group fieldset">
            <legend className="sr-only">เลือกข้อมูลตัวอย่าง</legend>
            {campaign?.profiles.map((p) => (
              <label key={p.profile_id} className="row choice">
                <input
                  type="radio"
                  name="profile"
                  checked={profileId === p.profile_id}
                  onChange={() => setProfileId(p.profile_id)}
                />
                <span className="check">
                  <CheckIcon size={14} strokeWidth={2.5} />
                </span>
                <span className="choice-text">
                  <span className="choice-title">
                    {p.label.split(" · ").slice(1).join(" · ") || p.label}
                  </span>
                  <span className="choice-sub">{p.label.split(" · ")[0]}</span>
                </span>
              </label>
            ))}
          </fieldset>
        ) : (
          <div className="group">
            <div className="row">
              <span className="tile-icon small">
                <FileIcon size={18} />
              </span>
              <span className="choice-text">
                <span className="choice-title">
                  {imported ? imported.filename : "นำเข้าไฟล์ .xlsx"}
                </span>
                <span className="choice-sub">
                  {imported
                    ? `ใช้ได้ ${imported.valid_count} จาก ${imported.rows.length} แถว · เลือกครั้งละ 1 แถว`
                    : "เลือกครั้งละ 1 แถว ระบบไม่โทรทุกแถวอัตโนมัติ"}
                </span>
              </span>
              <span className="row-trailing actions">
                <button
                  type="button"
                  className="btn btn-plain"
                  onClick={() =>
                    api.download(
                      `/api/v1/templates/${campaignId}.xlsx`,
                      "template.xlsx",
                    )
                  }
                >
                  <DownloadIcon size={16} />
                  แบบฟอร์ม
                </button>
                <button
                  type="button"
                  className="btn btn-tinted"
                  onClick={() => fileInput.current?.click()}
                >
                  <UploadIcon size={16} />
                  {uploading
                    ? "กำลังอ่าน…"
                    : imported
                      ? "เปลี่ยนไฟล์"
                      : "เลือกไฟล์"}
                </button>
              </span>
              <input
                ref={fileInput}
                type="file"
                accept=".xlsx"
                className="sr-only"
                tabIndex={-1}
                aria-label="ไฟล์ Excel"
                onChange={(e) => upload(e.target.files?.[0])}
              />
            </div>
            {imported?.rows.map((r) => (
              <label
                key={r.row_number}
                className={`row choice ${r.record ? "" : "disabled"}`}
              >
                <input
                  type="radio"
                  name="row"
                  disabled={!r.record}
                  checked={rowNumber === r.row_number}
                  onChange={() => setRowNumber(r.row_number)}
                />
                <span className="check">
                  <CheckIcon size={14} strokeWidth={2.5} />
                </span>
                <span className="choice-text">
                  <span className="choice-title">
                    แถว {r.row_number} · {r.record_id || "ไม่มีรหัส"}
                    {r.file_info.customer_name
                      ? ` · ${r.file_info.customer_name}`
                      : ""}
                  </span>
                  {r.errors.length > 0 && (
                    <span className="choice-sub err">
                      {r.errors.join(" · ")}
                    </span>
                  )}
                  {r.warnings.length > 0 && (
                    <span className="choice-sub">{r.warnings.join(" · ")}</span>
                  )}
                </span>
              </label>
            ))}
          </div>
        )}

        {record && (
          <details className="group disclosure record-facts">
            <summary className="row">
              <span className="pill mock">
                {String(record.data_label ?? "MOCK")}
              </span>
              <span className="choice-sub">
                ข้อมูลสมมติสำหรับทดสอบ ไม่ใช่ข้อมูลจริง
              </span>
              <span className="row-trailing">
                <span className="disclosure-label">ดูข้อมูล</span>
                <ChevronDownIcon size={18} className="chev" />
              </span>
            </summary>
            <div className="disclosure-body">
              <dl className="facts">
                {caseSummary(record).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </details>
        )}
      </section>

      {mode === "simulation" && (
        <section className="section">
          <details className="group disclosure">
            <summary className="row">
              <span className="tile-icon small">
                <FlaskIcon size={18} />
              </span>
              <span className="choice-text">
                <span className="choice-title">โหมดทดสอบ</span>
                <span className="choice-sub">
                  {`ยังไม่โทรจริง ลูกค้าจำลองจะตอบแบบ “${scriptKind === "custom" ? "พิมพ์เอง" : (scenario?.label ?? "—")}”`}
                </span>
              </span>
              <span className="row-trailing">
                <ChevronDownIcon size={18} className="chev" />
              </span>
            </summary>
            <div className="disclosure-body">
              <div
                className="segmented block"
                role="group"
                aria-label="รูปแบบคำตอบจำลอง"
              >
                <button
                  type="button"
                  aria-pressed={scriptKind === "scenario"}
                  onClick={() => setScriptKind("scenario")}
                >
                  สถานการณ์สำเร็จรูป
                </button>
                <button
                  type="button"
                  aria-pressed={scriptKind === "custom"}
                  onClick={() => setScriptKind("custom")}
                >
                  พิมพ์คำตอบเอง
                </button>
              </div>
              {scriptKind === "scenario" ? (
                <>
                  <label className="sr-only" htmlFor="scenario">
                    สถานการณ์
                  </label>
                  <select
                    id="scenario"
                    className="control"
                    value={scenarioId}
                    onChange={(e) => setScenarioId(e.target.value)}
                  >
                    {scenarios.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                  {scenario && (
                    <p className="section-note flush">
                      ลูกค้าจะตอบ: {scenario.customer.slice(0, 4).join(" → ")}
                      {scenario.customer.length > 4 ? " → …" : ""}
                    </p>
                  )}
                </>
              ) : (
                <>
                  <label className="sr-only" htmlFor="custom">
                    คำตอบของลูกค้า
                  </label>
                  <textarea
                    id="custom"
                    className="control"
                    placeholder={CUSTOM_HINT}
                    value={customScript}
                    onChange={(e) => setCustomScript(e.target.value)}
                  />
                </>
              )}
              {campaign && campaign.pending_approval.length > 0 && (
                <p className="section-note flush">
                  มีข้อความหรือข้อมูลที่ยังรอ KPI อนุมัติ{" "}
                  {campaign.pending_approval.length} รายการ
                </p>
              )}
            </div>
          </details>
        </section>
      )}

      {error && (
        <div className="section">
          <div className="alert err" role="alert">
            <AlertIcon size={18} />
            {error}
          </div>
        </div>
      )}

      <div className="call-dock">
        <button
          className="btn btn-primary btn-lg btn-block call-cta"
          disabled={!canCall}
        >
          <PhoneIcon size={20} />
          {submitting
            ? "กำลังเริ่มสาย…"
            : `โทรหา${name.trim() ? ` ${name.trim().split(/\s+/)[0]}` : ""}`}
        </button>
        <span className="caption">
          {busy
            ? "มีสายที่กำลังดำเนินการอยู่"
            : (missing ??
              (mode === "live"
                ? "ระบบจะโทรออกจริงไปยังเบอร์นี้"
                : "โหมดจำลอง · ระบบยังไม่โทรออกจริง"))}
        </span>
      </div>
    </form>
  );
}
