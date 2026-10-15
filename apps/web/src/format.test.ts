import { describe, expect, it } from "vitest";
import { IdempotencyKeys } from "./api";
import { caseSummary, elapsed, outcomeTone, stepIndex } from "./format";

describe("format helpers", () => {
  it("maps terminal and transitional lifecycles onto the stepper", () => {
    expect(stepIndex("queued")).toBe(0);
    expect(stepIndex("ending")).toBe(4);
    expect(stepIndex("ended")).toBe(5);
  });

  it("colours outcomes", () => {
    expect(outcomeTone("survey_completed")).toBe("good");
    expect(outcomeTone("callback_requested")).toBe("warn");
    expect(outcomeTone("wrong_person")).toBe("bad");
    expect(outcomeTone(null)).toBe("neutral");
  });

  it("formats elapsed time", () => {
    expect(elapsed("2026-10-07T00:00:00Z", "2026-10-07T00:01:05Z")).toBe("1:05");
  });

  it("summarises surveyor attendance including unknown", () => {
    expect(caseSummary({ surveyor_attended: null })).toEqual([["พนักงานสำรวจภัย", "ไม่ทราบ"]]);
  });
});

describe("IdempotencyKeys", () => {
  it("reuses a key for the same body and rotates it when the body changes", () => {
    const keys = new IdempotencyKeys();
    const a = keys.keyFor({ phone: "0812345678" });
    expect(keys.keyFor({ phone: "0812345678" })).toBe(a);
    expect(keys.keyFor({ phone: "0899999999" })).not.toBe(a);
  });
});

import type { Call } from "./api";
import { initials, scriptProgress } from "./format";

function survey(partial: Partial<Call>): Call {
  return {
    call_id: "c1",
    campaign: "accident_survey",
    mode: "simulation",
    target_name: "สมชาย ใจดี",
    phone: { entered: "0812345678", e164: "+66812345678", display: "081 234 5678", kind: "thai", sip_destination: "0812345678" },
    source: { type: "profile" },
    data_label: "MOCK",
    lifecycle: "in_conversation",
    dial_result: "answered",
    outcome: null,
    created_at: "2026-10-07T00:00:00Z",
    active: true,
    cancel_requested: false,
    ...partial,
  };
}

describe("scriptProgress", () => {
  it("marks the first unfinished step as current during a call", () => {
    const steps = scriptProgress(
      survey({
        result: {
          identity_result: "confirmed",
          notice_delivered: true,
          callback: { requested: false },
          policy_fields: [],
          survey_answers: [
            { question: "q1", label: "", scale_min: 1, scale_max: 5, value: 4, status: "answered", changed_from: [] },
            { question: "q2", label: "", scale_min: 1, scale_max: 5, value: null, status: "unanswered", changed_from: [] },
          ],
          final_comment_tags: [],
          tasks: [],
        },
      }),
    );
    expect(steps.map((s) => s.state)).toEqual(["done", "done", "done", "current", "todo", "todo"]);
  });

  it("marks where an unsuccessful call stopped", () => {
    const steps = scriptProgress(survey({ lifecycle: "ended", active: false, outcome: "wrong_person" }));
    expect(steps[0].state).toBe("failed");
  });

  it("builds Thai initials from consonants", () => {
    expect(initials("สมชาย ใจดี")).toBe("สจ");
    expect(initials("เอกชัย")).toBe("อ");
  });
});
