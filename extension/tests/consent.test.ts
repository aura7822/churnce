import { describe, expect, it } from "vitest";
import { hostOf, monitoringAllowed, summariseCookies, type Consent } from "../src/shared/consent";

const c = (scopes: Consent["scopes"]): Consent => ({ scopes, acceptedAt: "2026-11-06T00:00:00Z", extensionVersion: "1.1.0" });

describe("consent gating", () => {
  it("needs session and usage data; cookies are optional", () => {
    expect(monitoringAllowed(c(["session", "user_data"]))).toBe(true);
    expect(monitoringAllowed(c(["session", "user_data", "cookies"]))).toBe(true);
    expect(monitoringAllowed(c(["session"]))).toBe(false);
    expect(monitoringAllowed(c(["cookies"]))).toBe(false);
    expect(monitoringAllowed(null)).toBe(false);
  });
});

describe("cookie summary", () => {
  it("returns counts and flags only, never names or values", () => {
    const s = summariseCookies([{ session: true, secure: true, httpOnly: true, name: "sid", value: "SECRET" } as never, { secure: true }, {}]);
    expect(s).toEqual({ total: 3, session_cookies: 1, secure: 2, http_only: 1, session_present: true });
    expect(JSON.stringify(s)).not.toMatch(/SECRET|sid/);
  });
  it("handles an empty jar", () => expect(summariseCookies([]).session_present).toBe(false));
});

describe("helpers", () => {
  it("derives the host", () => { expect(hostOf("https://App.Shop.com:8443")).toBe("app.shop.com"); expect(hostOf("nope")).toBeNull(); });
});

import { sanitiseTxn } from "../src/shared/consent";
describe("transaction sanitiser", () => {
  const base = { txn_type: "payment", status: "failed", amount: 64, currency: "kes", method: "card", reason: "timeout", event_id: "order_1042" };
  it("keeps a clean bank label and due date, drops unsafe ones", () => {
    const ok = sanitiseTxn({ ...base, txn_type: "invoice", status: "pending", bank: "Equity Bank", due_at: "2026-12-01" })!;
    expect(ok.bank).toBe("Equity Bank"); expect(ok.due_at).toMatch(/^2026-12-01/);
    expect(sanitiseTxn({ ...base, bank: "1234567890123456" })!.bank).toBeUndefined();
  });
  it("keeps only whitelisted fields", () => {
    const t = sanitiseTxn({ ...base, card_number: "4242424242424242", payer_email: "a@b.com", name: "Jane" })!;
    expect(Object.keys(t).sort()).toEqual(["amount", "currency", "event_id", "method", "occurred_at", "reason", "status", "txn_type"]);
    expect(t.currency).toBe("KES");
  });
  it("rejects bad amounts, types, currencies and card-shaped ids", () => {
    expect(sanitiseTxn({ ...base, amount: -1 })).toBeNull();
    expect(sanitiseTxn({ ...base, amount: "64" })).toBeNull();
    expect(sanitiseTxn({ ...base, txn_type: "transfer" })).toBeNull();
    expect(sanitiseTxn({ ...base, currency: "US" })).toBeNull();
    expect(sanitiseTxn({ ...base, event_id: "4242424242424242" })).toBeNull();
  });
  it("drops a reason on non-failed transactions and defaults unknown values", () => {
    expect(sanitiseTxn({ ...base, status: "success" })!.reason).toBeUndefined();
    expect(sanitiseTxn({ ...base, method: "crypto", reason: "weird" })).toMatchObject({ method: "other", reason: "other" });
  });
});

describe("transaction sanitiser: bank, due date and finance types", () => {
  const base = { txn_type: "invoice", status: "pending", amount: 12000, currency: "kes", event_id: "inv_2001" };
  it("accepts the new types and a clean bank label", () => {
    expect(sanitiseTxn({ ...base, bank: "Equity Bank" })).toMatchObject({ txn_type: "invoice", bank: "Equity Bank", currency: "KES" });
    for (const t of ["bill", "inventory_in", "inventory_out"]) expect(sanitiseTxn({ ...base, txn_type: t })).not.toBeNull();
  });
  it("drops an invalid or oversize bank label rather than forwarding it", () => {
    expect(sanitiseTxn({ ...base, bank: "Bad<script>" })!.bank).toBeUndefined();
    expect(sanitiseTxn({ ...base, bank: "x".repeat(41) })!.bank).toBeUndefined();
    expect(sanitiseTxn({ ...base, bank: "  " })!.bank).toBeUndefined();
  });
  it("normalises a valid due date and drops garbage", () => {
    expect(sanitiseTxn({ ...base, due_at: "2026-12-01" })!.due_at).toBe("2026-12-01T00:00:00.000Z");
    expect(sanitiseTxn({ ...base, due_at: "soon" })!.due_at).toBeUndefined();
  });
});
