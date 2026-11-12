import { describe, expect, it } from "vitest";
import { formatCountdown, trialView } from "../src/shared/trial";

const now = Date.parse("2026-11-07T10:00:00Z");
describe("trial view", () => {
  it("is none before a trial starts", () => expect(trialView(undefined, undefined, now).phase).toBe("none"));
  it("counts down while active", () => {
    const v = trialView({ ends_at: "2026-11-10T10:00:00Z", used: true }, undefined, now);
    expect(v.phase).toBe("active"); expect(formatCountdown(v.msLeft)).toBe("72:00:00");
  });
  it("is ended after the deadline and when only 'used' is known", () => {
    expect(trialView({ ends_at: "2026-11-07T09:59:59Z", used: true }, undefined, now).phase).toBe("ended");
    expect(trialView({ ends_at: null, used: true }, undefined, now).phase).toBe("ended");
  });
  it("prefers the backend's premium object and recognises an organisation plan", () => {
    expect(trialView(undefined, { active: true, source: "trial", trial_ends_at: "2026-11-08T10:00:00Z", seconds_left: 86400 }, now).phase).toBe("active");
    expect(trialView({ ends_at: null, used: true }, { active: true, source: "org", trial_ends_at: null, seconds_left: 0 }, now).phase).toBe("org");
  });
  it("formats", () => expect(formatCountdown(3_661_000)).toBe("01:01:01"));
});
