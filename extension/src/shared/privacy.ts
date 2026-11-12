/** Client-side redaction. The backend redacts again; this makes sure sensitive text never leaves the browser. */
const PATTERNS: [RegExp, string][] = [
  // Government identifiers (labelled national ID / passport, KRA PIN) and IBAN-shaped strings. Over-redacting here is deliberate.
  [/\b(?:national\s*id|id\s*(?:no|number)|passport(?:\s*(?:no|number))?)\b\s*[:#.]?\s*[A-Z0-9]{6,12}\b/gi, "[id-number]"],
  [/\bID\s*[:#]?\s*\d{7,9}\b/g, "[id-number]"],
  [/\b[AP]\d{9}[A-Z]\b/g, "[id-number]"],
  [/\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b/g, "[bank-account]"],
  [/\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b/g, "[email]"],
  [/\b(?:\d[ -]?){13,19}\b/g, "[number]"],
  [/\b(?:\+?\d{1,3}[ -]?)?(?:\(?\d{2,4}\)?[ -]?){2,4}\d{2,4}\b/g, "[phone]"],
  [/\b(?:eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}|[A-Za-z0-9_-]{32,})\b/g, "[token]"],
];

export function redact(text: string): string {
  return PATTERNS.reduce((t, [re, label]) => t.replace(re, label), text);
}

/** Path only: no query string (often holds identifiers) and no fragment. */
export function safeRoute(href: string): string {
  try {
    const u = new URL(href);
    return u.pathname || "/";
  } catch {
    return "/";
  }
}

/** Input types whose contents must never be read at all. */
export const NEVER_READ = new Set(["password", "hidden", "file", "tel", "email"]);
