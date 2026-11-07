"""How often the two live sources agree, one number a day (`quantdesk data agreement`, agreement.yml).

The relay (deploy/cloudflare/live.js `tally`) counts, in every Kotak cycle of the session, the instruments for which Kite AND Kotak hold a fresh price and how many of those differ by more
than a spread explains (the same rule as the app's "differ" flag). Until now that was a live flag with no memory. This turns the relay's per-day counts, read from `/live/health`, into one small
file per day: counts and percentages only, no price and no instrument name. Market data only; it reads our own relay with the read-only key and places nothing.

Output, per day: <out>/<day>/agreement.json."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
KEYS = ("cycles", "both", "disagree", "opt_both", "opt_disagree", "worst_cycle_pct")
MIN_CYCLES = 100                      # a full session is about 4,500 five-second cycles; fewer than this is a partial day
NOTE = ("share of fresh Kite+Kotak pairs within a spread of each other (equities, futures and indices 0.5%, options 3%), counted by the relay every cycle of the session; "
        "counts only, no price, no name; data collection only, nothing here trades")


def _ist(ms) -> str | None:
    try:
        return dt.datetime.fromtimestamp(float(ms) / 1000, IST).strftime("%H:%M:%S") if float(ms) > 0 else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def day_manifest(d: dict) -> dict | None:
    """One relay day -> a published record, or None when the day is not usable."""
    try:
        day = dt.date.fromisoformat(str(d["day"]))
        n = {k: float(d.get(k) or 0) for k in KEYS}
    except (KeyError, ValueError, TypeError):
        return None
    if n["cycles"] < 1 or any(v < 0 or v != v for v in n.values()):
        return None
    both, opt = n["both"], n["opt_both"]
    return {"day": str(day), "source": "relay tally", "cycles": int(n["cycles"]), "pairs": int(both), "disagree": int(n["disagree"]),
            "agree_pct": round(100 * (1 - n["disagree"] / both), 2) if both else None,
            "opt_pairs": int(opt), "opt_disagree": int(n["opt_disagree"]), "opt_agree_pct": round(100 * (1 - n["opt_disagree"] / opt), 2) if opt else None,
            "worst_cycle_pct": round(n["worst_cycle_pct"], 2), "first": _ist(d.get("first_at")), "last": _ist(d.get("last_at")),
            "partial": n["cycles"] < MIN_CYCLES, "note": NOTE}


def build(health: dict, out_root: Path) -> list[dict]:
    """Every usable day in a `/live/health` answer (today's, and the finished days the relay keeps) -> <out>/<day>/agreement.json."""
    ag = (health or {}).get("agreement") or {}
    days = [ag.get("today")] + list((ag.get("days") or {}).values())
    made = {}
    for d in days:
        m = day_manifest(d) if isinstance(d, dict) else None
        if m:
            made[m["day"]] = m
    out = []
    for day, m in sorted(made.items()):
        f = Path(out_root) / day / "agreement.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(m, indent=2), encoding="utf-8")
        out.append(m)
    return out
