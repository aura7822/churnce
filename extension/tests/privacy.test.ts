import { describe, expect, it } from "vitest";
import { NEVER_READ, redact, safeRoute } from "../src/shared/privacy";
import { normalizeOrigin } from "../src/shared/config";

describe("client-side privacy", () => {
  it("redacts emails, card-like numbers and long tokens", () => {
    expect(redact("mail me at jo@example.com")).toBe("mail me at [email]");
    expect(redact("card 4242 4242 4242 4242")).toContain("[number]");
    expect(redact("key abcdefghijklmnopqrstuvwxyz0123456789")).toContain("[token]");
  });
  it("redacts government identifiers and IBANs", () => {
    expect(redact("ID 12345678")).toBe("[id-number]");
    expect(redact("KRA A123456789B")).toBe("KRA [id-number]");
    expect(redact("GB82WEST12345698765432")).toBe("[bank-account]");
  });
  it("keeps ordinary search words", () => {
    expect(redact("blue running shoes")).toBe("blue running shoes");
  });
  it("drops query strings and fragments from routes", () => {
    expect(safeRoute("https://shop.test/checkout?email=a@b.c&token=xyz#pay")).toBe("/checkout");
  });
  it("never reads sensitive input types", () => {
    for (const t of ["password", "hidden", "email", "tel", "file"]) expect(NEVER_READ.has(t)).toBe(true);
  });
  it("normalises origins and rejects non-web schemes", () => {
    expect(normalizeOrigin("shop.example.com/cart")).toBe("https://shop.example.com");
    expect(normalizeOrigin("javascript:alert(1)")).toBeNull();
  });
});
