"""PII and secret detection / redaction applied before anything is stored or embedded."""

from __future__ import annotations

import re
from collections import Counter

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
PHONE_CANDIDATE = re.compile(r"(?<![\w.])\+?\d[\d\s\-().]{7,}\d(?![\w])")
JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}\b")
BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}")
API_KEY = re.compile(r"\b(?:sk|pk|api|key|tok|secret)[-_][A-Za-z0-9_\-]{16,}\b", re.I)
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
# Labelled government identifiers (national ID / passport) and Kenyan KRA PINs (A123456789B).
GOV_ID = re.compile(
    r"(?i)\b(?:national\s*id|nat\.?\s*id|id\s*(?:no|number|num)|passport(?:\s*(?:no|number|num))?)\b\s*[:#.]?\s*[A-Z0-9]{6,12}\b"
    r"|\bID\s*[:#]?\s*\d{7,9}\b"
)
KRA_PIN = re.compile(r"\b[AP]\d{9}[A-Z]\b")
CREDENTIAL_PAIR = re.compile(r"(?i)\b(password|passwd|pwd|passcode|secret|token|api[_-]?key)\b\s*[:=]\s*\S+")

PLACEHOLDER = {
    "credential": "[credential]",
    "token": "[token]",
    "email": "[email]",
    "ssn": "[id-number]",
    "gov_id": "[id-number]",
    "iban": "[bank-account]",
    "card": "[card]",
    "phone": "[phone]",
}


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _iban_valid(raw: str) -> bool:
    """ISO 13616 mod-97 check, so ordinary alphanumeric codes are not mistaken for IBANs."""
    rearranged = raw[4:] + raw[:4]
    try:
        return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1
    except ValueError:
        return False


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return (clean_text, {category: count}). Order matters: secrets, then identifiers."""
    if not text:
        return text, {}
    found: Counter[str] = Counter()

    def sub(pattern: re.Pattern[str], kind: str, s: str) -> str:
        def repl(m: re.Match[str]) -> str:
            found[kind] += 1
            return PLACEHOLDER[kind]

        return pattern.sub(repl, s)

    out = text
    out = sub(CREDENTIAL_PAIR, "credential", out)
    out = sub(JWT, "token", out)
    out = sub(BEARER, "token", out)
    out = sub(API_KEY, "token", out)
    out = sub(EMAIL, "email", out)
    out = sub(SSN, "ssn", out)
    out = sub(GOV_ID, "gov_id", out)
    out = sub(KRA_PIN, "gov_id", out)

    def iban_repl(m: re.Match[str]) -> str:
        if _iban_valid(m.group(0)):
            found["iban"] += 1
            return PLACEHOLDER["iban"]
        return m.group(0)

    out = IBAN.sub(iban_repl, out)

    def card_repl(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found["card"] += 1
            return PLACEHOLDER["card"]
        return m.group(0)

    out = CARD_CANDIDATE.sub(card_repl, out)

    def phone_repl(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 9 <= len(digits) <= 15:
            found["phone"] += 1
            return PLACEHOLDER["phone"]
        return m.group(0)

    out = PHONE_CANDIDATE.sub(phone_repl, out)
    return out, dict(found)


def scan(text: str) -> dict[str, int]:
    """Detect sensitive content without rewriting. Used as the final gate before indexing."""
    _, found = redact(text)
    return found


INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|prompts?|rules)"),
    re.compile(r"(?i)disregard\s+(all\s+)?(the\s+)?(previous|prior|above|system)"),
    re.compile(r"(?i)\byou\s+are\s+now\b"),
    re.compile(r"(?i)\bsystem\s*prompt\b"),
    re.compile(r"(?i)\b(reveal|print|show)\s+(your|the)\s+(instructions|prompt|secrets?|api\s*keys?)"),
    re.compile(r"(?i)\b(send|email)\s+(a\s+)?(discount|coupon|promo)\b.*\b(all|every)\b"),
    re.compile(r"(?i)\boverride\s+(the\s+)?(policy|policies|safety|guardrails?)\b"),
]


def injection_suspected(text: str) -> bool:
    """Heuristic detector for instructions smuggled into retrieved or customer-supplied text."""
    return any(p.search(text) for p in INJECTION_PATTERNS)
