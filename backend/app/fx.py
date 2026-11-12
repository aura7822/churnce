"""Indicative FX to Kenyan shillings. Every money value the finance API returns is KES.

Rates are static and indicative (no market-data feed is connected). Override or extend them with the FX_RATES_JSON environment
variable, for example FX_RATES_JSON='{"USD": 129.4, "UGX": 0.035}'. Unknown currencies are treated at 1:1 and flagged by `known()`."""
from __future__ import annotations

import json
import os

BASE = "KES"
DEFAULT_RATES: dict[str, float] = {
    "KES": 1.0, "USD": 129.0, "EUR": 140.0, "GBP": 165.0, "UGX": 0.035, "TZS": 0.05, "RWF": 0.09, "ZAR": 7.1, "NGN": 0.085, "GHS": 8.5,
    "AED": 35.1, "INR": 1.55, "CNY": 17.8, "JPY": 0.86, "CAD": 94.0, "AUD": 84.0, "ETB": 1.05, "EGP": 2.6,
}


def rates() -> dict[str, float]:
    out = dict(DEFAULT_RATES)
    raw = os.environ.get("FX_RATES_JSON", "").strip()
    if raw:
        try:
            out.update({k.upper(): float(v) for k, v in json.loads(raw).items() if float(v) > 0})
        except (ValueError, TypeError):
            pass
    out["KES"] = 1.0
    return out


def rate(cur: str) -> float:
    return rates().get((cur or BASE).upper(), 1.0)


def known(cur: str) -> bool:
    return (cur or BASE).upper() in rates()


def to_kes_minor(amount_minor: int, cur: str) -> int:
    return int(round(amount_minor * rate(cur)))
