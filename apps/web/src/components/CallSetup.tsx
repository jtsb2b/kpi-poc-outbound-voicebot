import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  IdempotencyKeys,
  type Api,
  type Call,
  type Campaign,
  type CampaignId,
  type EngineId,
  type ImportResult,
  type PhoneCheck,
  type SystemStatus,
} from "../api";
import { ENGINE_LABEL, caseSummary } from "../format";
import { AlertIcon, CalendarIcon, CheckIcon, ChevronDownIcon, DownloadIcon, FileIcon, PhoneIcon, ShieldCheckIcon, StarIcon, UploadIcon, WrenchIcon } from "../icons";

type SourceKind = "profile" | "import";

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
  garage_followup: {
    title: "ติดตามอู่วางบิล",
    sub: "สอบถามสถานะซ่อมรถทีละคัน และขอให้ตั้งเบิกเคลม",
    Icon: WrenchIcon,
  },
  repair_appointment: {
    title: "นัดเข้าซ่อมกับลูกค้า",
    sub: "ลูกค้าที่อู่ติดต่อไม่ได้ ถามวันที่สะดวกนำรถเข้าซ่อม",
    Icon: CalendarIcon,
  },
};

const ENGINE_NOTE: Record<EngineId, string> = {
  pipeline: "Soniox → Gemini 3.5 Flash-Lite → Gemini TTS (Achernar) · ระบบที่ใช้อยู่",
  agni: "Agni Premium (เสียง Iris) · speech-to-speech · ผลสรุปอ่านจากบทสนทนาหลังวางสาย",
  gemini_live: "Gemini 3.8 Live (เสียง Sulafat = Iris) · speech-to-speech · ผลสรุปอ่านจากบทสนทนาหลังวางสาย",
};

/** +6621004148 → 02-100-4148 */
function callerDisplay(e164: string): string {
  const national = e164.startsWith("+66") ? `0${e164.slice(3)}` : e164;
  return national.length === 9 && national.startsWith("02")
    ? `${national.slice(0, 2)}-${national.slice(2, 5)}-${national.slice(5)}`
    : national;
}

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
  const [engine, setEngine] = useState<EngineId>("pipeline");

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

  const record =
    sourceKind === "profile"
      ? campaign?.profiles.find((p) => p.profile_id === profileId)?.case
      : (imported?.rows.find((r) => r.row_number === rowNumber)?.record ??
        undefined);

  const phoneOk = Boolean(phoneCheck?.valid && phoneCheck.dialable);
  // Only real calls are placed from here (the simulation mode was removed from the page, 21 Oct 2026).
  const live = Boolean(status?.telephony_ready);
  const offHours = status ? !status.within_calling_hours : false;
  const missing = !live
    ? "ยังไม่เปิดใช้การโทรจริง (ตั้งค่าระบบโทรศัพท์ใน .env)"
    : !name.trim()
    ? "กรอกชื่อผู้รับสาย"
    : !phoneOk
      ? "กรอกเบอร์โทรให้ถูกต้อง"
      : !record
        ? "เลือกข้อมูลประกอบการโทร"
        : offHours
          ? `อยู่นอกเวลาโทร (${status?.calling_hours})`
          : null;
  const lab = status?.role === "lab" ? status.engines : null;
  const engineReady = !lab || Boolean(lab.find((e) => e.id === engine)?.ready);
  const canCall = Boolean(campaign && !missing && engineReady && !busy && !submitting);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canCall) return;
    setSubmitting(true);
    setError(null);
    const payload = {
      campaign: campaignId,
      target_name: name.trim(),
      phone: phone.trim(),
      mode: "live",
      ...(lab ? { engine } : {}),
      source:
        sourceKind === "profile"
          ? { type: "profile", profile_id: profileId }
          : {
              type: "import",
              import_id: imported?.import_id,
              row_number: rowNumber,
            },
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
          <p className="section-note">
            โทรออกจริงผ่านระบบโทรศัพท์
            {status?.caller_id
              ? ` · ลูกค้าจะเห็นเบอร์ ${callerDisplay(status.caller_id)}`
              : ""}{" "}
            · โทรครั้งเดียว ไม่โทรซ้ำอัตโนมัติ
          </p>
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

      {lab && (
        <section className="section" aria-labelledby="s-engine">
          <div className="section-head">
            <h2 className="section-title" id="s-engine">
              เครื่องยนต์สนทนา
            </h2>
            <div className="segmented" role="group" aria-labelledby="s-engine">
              {lab.map((e) => (
                <button
                  key={e.id}
                  type="button"
                  aria-pressed={engine === e.id}
                  disabled={!e.ready}
                  title={e.ready ? undefined : "ยังตั้งค่าไม่ครบใน .env"}
                  onClick={() => setEngine(e.id)}
                >
                  {ENGINE_LABEL[e.id]}
                </button>
              ))}
            </div>
          </div>
          <p className="section-note">{ENGINE_NOTE[engine]}</p>
        </section>
      )}

      <section className="section" aria-labelledby="s-who">
        <h2 className="section-title" id="s-who">
          ผู้รับสาย
        </h2>
        <div className="group">
          <label className="row field" htmlFor="name">
            <span className="row-label">{campaignId === "garage_followup" ? "ชื่อผู้ติดต่อที่อู่" : "ชื่อ-นามสกุล"}</span>
            <input
              id="name"
              className="row-input"
              type="text"
              autoComplete="off"
              placeholder={campaignId === "garage_followup" ? "เช่น ช่างเอก (ใช้บันทึกเท่านั้น)" : "เช่น สมชาย ใจดี"}
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
                    <dd style={{ whiteSpace: "pre-line" }}>{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </details>
        )}
      </section>

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
            : (missing ?? "ระบบจะโทรออกจริงไปยังเบอร์นี้")}
        </span>
      </div>
    </form>
  );
}
