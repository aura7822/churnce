import { describe, expect, it } from "vitest";
import { autoSendEligible, type Draft } from "../src/shared/outreach";

const NOW = Date.parse("2026-10-30T12:00:00Z");
const ok = { name: "communication_consent", passed: true, detail: "" };
const draft = (over: Partial<Draft> = {}): Draft => ({
  id: "com_1", status: "draft", subject: "Buttons that respond instantly", body: "Come back and see the faster checkout.", recipient: "j***@x.com",
  customer_ref: "c1", holdout: false, generated_by: "gemma", created_at: "2026-10-30T11:00:00Z", policy_result: { checks: [ok] }, ...over,
});

describe("auto-send eligibility", () => {
  it("accepts a clean draft that has waited past the delay", () => expect(autoSendEligible(draft(), 10, NOW)).toBe(true));
  it("waits for the edit window", () => expect(autoSendEligible(draft({ created_at: "2026-10-30T11:55:00Z" }), 10, NOW)).toBe(false));
  it("never sends holdout, blocked, sent or failing-policy drafts", () => {
    expect(autoSendEligible(draft({ holdout: true }), 0, NOW)).toBe(false);
    expect(autoSendEligible(draft({ status: "blocked" }), 0, NOW)).toBe(false);
    expect(autoSendEligible(draft({ status: "sent" }), 0, NOW)).toBe(false);
    expect(autoSendEligible(draft({ policy_result: { checks: [ok, { name: "not_suppressed", passed: false, detail: "suppressed" }] } }), 0, NOW)).toBe(false);
  });
  it("refuses drafts with no policy result or empty content", () => {
    expect(autoSendEligible(draft({ policy_result: undefined }), 0, NOW)).toBe(false);
    expect(autoSendEligible(draft({ body: "  " }), 0, NOW)).toBe(false);
  });
});
