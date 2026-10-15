import { useRef, useState, type FormEvent } from "react";
import { AlertIcon, ShieldCheckIcon, StarIcon } from "../icons";
import { ThemeToggle } from "../ui/ThemeToggle";

const PREVIEW_STEPS = ["ยืนยันตัวตน", "แจ้งการบันทึก", "ทวนข้อมูล", "สิทธิยกเลิก", "จบสาย"];

export function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [token, setToken] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!token.trim()) {
      setError("กรอกรหัสผู้ใช้งานก่อนเข้าสู่ระบบ");
      input.current?.focus();
      return;
    }
    setChecking(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/system/status", { headers: { Authorization: `Bearer ${token.trim()}` } });
      if (res.status === 401) {
        setError("รหัสไม่ถูกต้อง ตรวจสอบแล้วลองอีกครั้ง");
        input.current?.select();
      } else if (!res.ok) setError(`ระบบยังไม่พร้อม (${res.status}) ลองใหม่อีกครั้งในสักครู่`);
      else onLogin(token.trim());
    } catch {
      setError("เชื่อมต่อระบบไม่ได้ ตรวจสอบว่าเซิร์ฟเวอร์ทำงานอยู่");
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="auth">
      <aside className="auth-stage" aria-label="เกี่ยวกับระบบ">
        <div className="auth-brand">
          <span className="logo-plate">
            <img className="auth-logo" src="/brand/kpi-logo.svg" alt="กรุงไทยพานิชประกันภัย (KPI)" width={138} height={67} />
          </span>
          <span>Outbound Voicebot</span>
        </div>

        <div className="auth-pitch">
          <h1>
            <span className="nowrap">น้องเคพีไอ</span> <span className="nowrap">โทรหาลูกค้า</span>
            <span className="nowrap">แทนคุณ</span>
          </h1>
          <p>กรอกชื่อและเบอร์ กดโทร แล้วดูบทสนทนากับผลลัพธ์ได้ทันที</p>
        </div>

        <div className="auth-preview" aria-hidden="true">
          <div className="auth-preview-who">
            <span className="avatar">คพ</span>
            <span>
              <span className="auth-preview-name">น้องเคพีไอ</span>
              <span className="auth-preview-meta">AI ผู้ช่วย · กรุงไทยพานิชประกันภัย</span>
            </span>
            <span className="auth-preview-state">
              <span className="live-dot" />
              กำลังสนทนา
            </span>
          </div>
          <ol className="progress">
            {PREVIEW_STEPS.map((label, i) => (
              <li key={label} className={i < 2 ? "done" : i === 2 ? "current" : "todo"}>
                <span className="bar" />
                <span className="label">{label}</span>
              </li>
            ))}
          </ol>
        </div>

        <ul className="auth-campaigns">
          <li>
            <ShieldCheckIcon size={18} />
            ยืนยันกรมธรรม์ประกันอุบัติเหตุ (PA)
          </li>
          <li>
            <StarIcon size={18} />
            สำรวจความพึงพอใจศูนย์รับแจ้งอุบัติเหตุ
          </li>
        </ul>
      </aside>

      <main className="auth-panel">
        <ThemeToggle className="icon-btn auth-theme" />
        <form className="auth-form auth-form-card" onSubmit={submit} noValidate>
          <div className="auth-form-head">
            <h2>เข้าสู่ระบบ</h2>
            <p>สำหรับผู้ใช้งานที่ได้รับรหัสจาก JTS</p>
          </div>

          <div className="auth-field">
            <label htmlFor="token">รหัสผู้ใช้งาน</label>
            <div className={`auth-input ${error ? "invalid" : ""}`}>
              <input
                ref={input}
                id="token"
                type={show ? "text" : "password"}
                autoComplete="current-password"
                autoFocus
                spellCheck={false}
                placeholder="วางรหัสที่ได้รับ"
                value={token}
                onChange={(e) => {
                  setToken(e.target.value);
                  if (error) setError(null);
                }}
                aria-invalid={Boolean(error)}
                aria-describedby="token-help"
              />
              <button
                type="button"
                className="auth-reveal"
                onClick={() => setShow((s) => !s)}
                aria-pressed={show}
                aria-label={show ? "ซ่อนรหัส" : "แสดงรหัส"}
              >
                {show ? "ซ่อน" : "แสดง"}
              </button>
            </div>
            <p id="token-help" className={`auth-help ${error ? "err" : ""}`} role={error ? "alert" : undefined}>
              {error ? (
                <>
                  <AlertIcon size={16} />
                  {error}
                </>
              ) : (
                "ไม่มีรหัส? ติดต่อผู้ดูแลระบบ JTS"
              )}
            </p>
          </div>

          <button className="btn btn-primary btn-lg btn-block" disabled={checking}>
            {checking ? "กำลังตรวจสอบ…" : "เข้าสู่ระบบ"}
          </button>

          <p className="auth-foot">ระบบทดลอง (POC) · ใช้ข้อมูลตัวอย่างเท่านั้น</p>
        </form>
      </main>
    </div>
  );
}
