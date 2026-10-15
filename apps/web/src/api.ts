export type CampaignId = "pa_confirmation" | "accident_survey";

export interface Profile {
  profile_id: string;
  label: string;
  case: Record<string, unknown>;
}

export interface Scenario {
  id: string;
  label: string;
  customer: string[];
  profile: string;
}

export interface Campaign {
  id: CampaignId;
  title: string;
  version: string;
  persona_name: string;
  pending_approval: string[];
  profiles: Profile[];
  scenarios: Scenario[];
}

export interface PolicyField {
  field: string;
  label: string;
  expected_value: string;
  status: string;
  delivery: string;
  customer_statement?: string | null;
}

export interface SurveyAnswer {
  question: string;
  label: string;
  scale_min: number;
  scale_max: number;
  value: number | null;
  status: string;
  raw_utterance?: string | null;
  feedback_raw?: string | null;
  changed_from: number[];
}

export interface Task {
  type: string;
  reason: string;
  detail_raw?: string | null;
  field?: string | null;
}

export interface CallResult {
  identity_result: string;
  notice_delivered: boolean;
  callback: { requested: boolean; preferred_time_text?: string | null };
  policy_fields: PolicyField[];
  free_look_delivery?: string | null;
  survey_answers: SurveyAnswer[];
  final_comment_raw?: string | null;
  final_comment_tags: string[];
  tasks: Task[];
  end_reason?: string | null;
}

export interface TranscriptTurn {
  seq: number;
  speaker: "bot" | "customer";
  at: string;
  text: string;
  generated_text?: string | null;
  interrupted?: boolean | null;
}

export interface CallEvent {
  at: string;
  type: string;
  data: Record<string, unknown>;
}

export interface Call {
  call_id: string;
  campaign: CampaignId;
  mode: string;
  scenario_id?: string;
  target_name: string;
  phone: { entered: string; e164: string | null; display: string; kind: string; sip_destination: string | null };
  source: { type: string; profile_id?: string; label?: string; row_number?: number; record_id?: string; filename?: string };
  data_label: string;
  lifecycle: string;
  dial_result: string | null;
  outcome: string | null;
  end_reason?: string | null;
  created_at: string;
  answered_at?: string;
  ended_at?: string;
  active: boolean;
  cancel_requested: boolean;
  warnings?: string[];
  transcript_discarded?: boolean;
  result?: CallResult;
  case?: Record<string, unknown>;
  transcript?: TranscriptTurn[];
  events?: CallEvent[];
}

export interface ImportRow {
  row_number: number;
  record_id: string;
  record: Record<string, unknown> | null;
  file_info: { customer_name?: string; phone?: string };
  errors: string[];
  warnings: string[];
}

export interface ImportResult {
  import_id: string;
  campaign: CampaignId;
  filename: string;
  rows: ImportRow[];
  valid_count: number;
}

export interface PhoneCheck {
  valid: boolean;
  dialable?: boolean;
  kind?: string;
  e164?: string | null;
  display?: string;
  sip_destination?: string | null;
  message?: string | null;
}

export interface SystemStatus {
  live_calls_enabled: boolean;
  telephony_ready: boolean;
  caller_id: string | null;
  interpreter: "rules" | "llm";
  within_calling_hours: boolean;
  calling_hours: string;
  retention_days: number;
  active_call_id: string | null;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "kpi-operator-token";

export function loadToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function saveToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // Private mode: the token simply is not remembered.
  }
}

function detailMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string }).msg ?? "").join(", ");
  }
  return `เกิดข้อผิดพลาด (${status})`;
}

export class Api {
  constructor(
    private readonly token: string,
    private readonly onUnauthorized: () => void,
  ) {}

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.token}`);
    const res = await fetch(path, { ...init, headers });
    if (res.status === 401) {
      this.onUnauthorized();
      throw new ApiError(401, "กรุณาเข้าสู่ระบบอีกครั้ง");
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, detailMessage(body, res.status));
    }
    return res;
  }

  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    return (await (await this.request(path, init)).json()) as T;
  }

  status = () => this.json<SystemStatus>("/api/v1/system/status");
  campaigns = () => this.json<Campaign[]>("/api/v1/campaigns");
  calls = (campaign?: string, outcome?: string) => {
    const q = new URLSearchParams();
    if (campaign) q.set("campaign", campaign);
    if (outcome) q.set("outcome", outcome);
    return this.json<Call[]>(`/api/v1/calls?${q}`);
  };
  call = (id: string) => this.json<Call>(`/api/v1/calls/${id}`);
  cancel = (id: string) => this.json<Call>(`/api/v1/calls/${id}/cancel`, { method: "POST" });
  remove = (id: string) => this.request(`/api/v1/calls/${id}`, { method: "DELETE" });
  checkPhone = (phone: string) =>
    this.json<PhoneCheck>("/api/v1/phone/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone }),
    });
  createCall = (body: unknown, idempotencyKey: string) =>
    this.json<Call>("/api/v1/calls", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    });
  upload = (campaign: CampaignId, file: File) => {
    const form = new FormData();
    form.set("campaign", campaign);
    form.set("file", file);
    return this.json<ImportResult>("/api/v1/imports", { method: "POST", body: form });
  };

  async download(path: string, fallbackName: string): Promise<void> {
    const res = await this.request(path);
    const blob = await res.blob();
    const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = match?.[1] ?? fallbackName;
    a.click();
    URL.revokeObjectURL(url);
  }
}

/** One idempotency key per distinct request body, reused when the same body is retried. */
export class IdempotencyKeys {
  private body = "";
  private key = "";

  keyFor(body: unknown): string {
    const serialized = JSON.stringify(body);
    if (serialized !== this.body || !this.key) {
      this.body = serialized;
      this.key = crypto.randomUUID();
    }
    return this.key;
  }

  reset(): void {
    this.body = "";
    this.key = "";
  }
}
