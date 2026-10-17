"""Overnight carry of the desk's own positions (docs/prereg/overnight_carry_v1.json): long options, debit spreads and the
iron fly could be held ONE night instead of squared off at 15:15, sized on their FULL max loss. PHASE 1 (this build) is
SHADOW ONLY: nothing is carried and the square-off is untouched. Every position still open at the square-off writes a
record of what it WOULD have carried, and the next morning's 09:20 real quotes mark it against its actual exit; the report
(`report`, `render`) shows the running paired difference. `apply` is not implemented: it runs as shadow, with a warning.

The prior registered with the spec is that carrying LOSES (L4, overnight theta): a stop cannot fire overnight and a gap can
take the whole premium. So the sizing here is not the intraday sizer's. The intraday sizer uses the stop distance; this
uses the worst payoff of the position at expiry, plus the fees already paid and the fees of closing it.

Read it in this order: `limits` (never looser than the desk or the ceilings) -> `legs_of`, `uncovered`, `loss_per_lot`
(defined risk and its full max loss) -> `plan` (every refusal, then the lots that fit) -> `Ledger` (shadow records, exits,
09:20 marks) -> `gate` (the evidence rule) -> `effective` (the mode in force for one setup).

This module places no order and imports no broker; the engine only calls `plan` and `Ledger` to write its records.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from ..core.types import Instrument
from .risk import IntradayRisk
from .sleeves import PREREG, REAL_SOURCES, intrinsic

SPEC_PATH = PREREG / "overnight_carry_v1.json"
RESULTS = PREREG / "results"
SETUPS = ("orb", "vwap_trend", "trend_break", "va_reversion", "range_sell")
MODES = ("off", "shadow", "apply")
SHADOW_SESSIONS_REQUIRED = 5
HIST_MIN_N, HIST_T = 100, 2.33
FWD_MIN_N, FWD_MAX_N, FWD_T, FWD_Z, UNMARKED_MAX = 30, 60, 1.645, -1.645, 0.30
MARK_FROM, MARK_TO = dt.time(9, 20), dt.time(9, 30)
CEIL = {"risk_per_trade": 0.025, "max_open": 2, "daily_loss": 0.05, "outlay": 0.5, "dd_halt": 0.10, "max_trades": 4}


def load_spec(path: Path = SPEC_PATH) -> dict:
    raw = Path(path).read_bytes()
    spec = json.loads(raw)
    spec["_hash"] = hashlib.sha256(raw).hexdigest()[:12]
    return spec


def settings(cfg) -> dict:
    """`intraday.overnight_carry.mode`: off | shadow | apply; anything else is shadow (as the earn-in gate)."""
    mode = str((cfg.get("intraday.overnight_carry", {}) or {}).get("mode", "shadow")).lower()
    return {"mode": mode if mode in MODES else "shadow"}


def limits(cfg) -> dict:
    """The smaller of the desk's configured value and the spec's ceiling, for every limit the carry is held to."""
    r = IntradayRisk(cfg)

    def cap(v, c):
        return c if v is None else min(v, c)
    dd = cfg.get("intraday.risk.cross_day_drawdown_halt", 0) or 0
    return {"risk_per_trade": cap(r.risk_per_trade, CEIL["risk_per_trade"]), "max_open": int(cap(r.max_open, CEIL["max_open"])),
            "daily_loss": cap(r.daily_loss, CEIL["daily_loss"]), "max_margin": min(cap(r.max_margin, CEIL["outlay"]), cap(r.max_exposure, CEIL["outlay"])),
            "dd_halt": cap(dd or None, CEIL["dd_halt"]), "credit_margin": float(r.credit_margin or 0.0),
            "short_from": cfg.get("intraday.short_legs_from_equity", 300000)}


# ---- the position: defined risk and its full max loss ---------------------------------------------------------------------
def legs_of(t) -> list[dict]:
    """The position per lot: [{inst, symbol, right, strike, expiry, qty, entry}] from a Trade. `qty` is the signed number of
    contracts PER LOT of the position (a lot's worth of units: ratio x lot size), so rupees are qty x points."""
    units = max(int(t.units), 1)
    out = []
    for l in t.legs:
        if l.exit_price is not None:
            continue
        per, rem = divmod(abs(int(l.qty)), units)
        if rem:
            raise ValueError(f"{l.instrument.symbol}: quantity {l.qty} is not a whole number per lot of {units}")
        out.append({"inst": l.instrument, "symbol": l.instrument.symbol, "right": l.instrument.right, "strike": float(l.instrument.strike),
                    "expiry": l.instrument.expiry, "qty": per if l.qty > 0 else -per, "entry": float(l.entry_price)})
    return out


def uncovered(legs: list[dict]) -> list[str]:
    """Defined risk: for each right and expiry the long quantity is at least the short quantity. Anything else has a short
    leg nothing covers (it could lose without bound) and is never a carry."""
    bad = []
    for key in sorted({(l["right"], l["expiry"]) for l in legs}, key=str):
        side = [l for l in legs if (l["right"], l["expiry"]) == key]
        if sum(l["qty"] for l in side if l["qty"] > 0) < -sum(l["qty"] for l in side if l["qty"] < 0):
            bad.append(f"{key[0]} {key[1]}: short quantity not covered by a long of the same right and expiry")
    return bad


def worst_payoff(legs: list[dict]) -> float:
    """The position's worst payoff at expiry per lot, in rupees (<= 0 when anything can be lost): the sum of
    qty x (intrinsic - entry) at every strike, at zero and far above. Piecewise linear, so these are the extremes."""
    strikes = sorted({l["strike"] for l in legs})
    grid = [0.0, *strikes, max(strikes) * 10.0]
    return min(0.0, min(sum(l["qty"] * (intrinsic(l["right"], l["strike"], s) - l["entry"]) for l in legs) for s in grid))


def loss_for(legs: list[dict], lots: int, paid_fees: float, costs, extra_close_lots: int = 0) -> dict:
    """The FULL max loss in rupees of carrying `lots`: the worst expiry payoff x lots, plus every fee already paid,
    plus the fees of closing each carried leg at its entry price, plus (when the position holds more lots than are carried)
    the fees of closing the excess lots the same way."""
    gross = -worst_payoff(legs) * lots
    exit_fees = sum(costs.fees(l["inst"], -l["qty"] * lots, l["entry"])[0] for l in legs)
    trim_fees = sum(costs.fees(l["inst"], -l["qty"] * extra_close_lots, l["entry"])[0] for l in legs) if extra_close_lots else 0.0
    return {"gross": gross, "paid_fees": paid_fees, "exit_fees": exit_fees, "trim_fees": trim_fees,
            "max_loss": gross + paid_fees + exit_fees + trim_fees}


# ---- the plan --------------------------------------------------------------------------------------------------------------
def plan(cfg, cal, t, day: dt.date, facts: dict, costs, lim: dict | None = None) -> dict:
    """What the position at the square-off may do: {lots, lots_fit, reasons (why not all), binding, ...numbers}. `facts`
    (from the engine): equity (cash + open positions at cost), day_start_equity, peak, reserved_loss and reserved_margin
    (of carries already registered), carries (their count), halts (a list of reasons the engine is halted). Pure."""
    lim = lim or limits(cfg)
    lots = int(t.units)
    out = {"setup": t.strategy, "underlying": t.symbol, "day": str(day), "lots": lots, "lots_fit": 0, "reasons": [], "binding": []}
    why = out["reasons"]
    try:
        legs = legs_of(t)
    except ValueError as exc:
        why.append(str(exc))
        return out
    if not legs:
        why.append("no open leg")
        return out
    out["legs"] = [{k: (str(v) if k == "expiry" else v) for k, v in l.items() if k != "inst"} for l in legs]
    if t.strategy not in SETUPS:
        why.append(f"{t.strategy} is not a setup this spec covers")
    why += uncovered(legs)
    if cfg.get("account.mode") != "paper":
        why.append(f"account.mode is {cfg.get('account.mode')!r}, not paper")
    why += list(facts.get("halts") or [])
    nxt = cal.next_trading_day(day)
    out["next_day"] = str(nxt)
    for d in (day, nxt):
        if gap := cfg.holiday_gap(d):
            why.append(f"the exchange calendar cannot be trusted for {d}: {gap}")
    if (nxt - day).days != 1:
        why.append(f"{(nxt - day).days} calendar days to the next session: a weekend or a holiday sits between")
    near = min(l["expiry"] for l in legs)
    out["expiry"] = str(near)
    if near <= nxt:
        why.append(f"expires {near}, on or before the next session {nxt}: never carried into an expiry")
    eq = float(facts.get("equity") or 0.0)
    out["equity"] = eq
    if not math.isfinite(eq) or eq <= 0:
        why.append("equity unknown")
        return out
    if any(l["qty"] < 0 for l in legs):
        sf = lim["short_from"]
        if sf is None:
            why.append("selling is off (intraday.short_legs_from_equity is null)")
        elif eq < float(sf):
            why.append(f"equity ₹{eq:,.0f} is below ₹{float(sf):,.0f}, the desk's floor for sold legs")
    start, peak = facts.get("day_start_equity"), facts.get("peak")
    if start and eq / float(start) - 1 <= -lim["daily_loss"]:
        why.append(f"the day is at its loss limit ({eq / float(start) - 1:.2%})")
    if peak and eq / float(peak) - 1 <= -lim["dd_halt"]:
        why.append(f"equity is {eq / float(peak) - 1:.1%} from its peak (halt at {lim['dd_halt']:.0%})")
    if facts.get("carries", 0) + 1 > lim["max_open"]:
        why.append(f"{lim['max_open']} positions would already be open overnight")
    if why:
        return out
    debit = sum(l["qty"] * l["entry"] for l in legs)                  # net premium paid per lot (negative: a credit)
    margin_room = lim["max_margin"] * eq - float(facts.get("reserved_margin") or 0.0)
    room = (eq - float(start) * (1 - lim["daily_loss"]) - float(facts.get("reserved_loss") or 0.0)) if start else 0.0
    out["caps"] = {"risk": lim["risk_per_trade"] * eq, "daily_room": room, "margin_room": margin_room, "debit_per_lot": debit}
    out["per_lot"] = {"worst_pts": worst_payoff(legs), "gross_loss": -worst_payoff(legs), "stop_distance_risk": float(t.initial_risk) / lots}
    for n in range(lots, 0, -1):
        e = loss_for(legs, n, float(t.fees), costs, extra_close_lots=lots - n)
        margin = debit * n if debit > 0 else max(e["max_loss"], lim["credit_margin"] * n)
        fits = {"risk": e["max_loss"] <= lim["risk_per_trade"] * eq, "daily_room": e["max_loss"] <= room, "margin": margin <= margin_room}
        if all(fits.values()):
            out.update(lots_fit=n, max_loss=e["max_loss"], margin=margin, economics=e)
            return out
        if n == 1:
            out["binding"] = [k for k, ok in fits.items() if not ok]
    why.append("not one lot fits the full max loss: " + ", ".join(out["binding"]))
    return out


# ---- the ledger ----------------------------------------------------------------------------------------------------------------
class Ledger:
    """runtime/intraday/overnight_carry_v1.jsonl: candidate (at the square-off), exit (the actual close), mark (09:20), unmarked."""

    def __init__(self, path: Path, spec: dict | None = None):
        self.path, self.spec = Path(path), spec or load_spec()

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]

    def append(self, ev: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ev = {"spec": self.spec["_hash"], "recorded_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(timespec="seconds"), **ev}
        with self.path.open("a") as f:
            f.write(json.dumps(ev, default=str) + "\n")
        return ev

    def sessions(self) -> int:
        return len({e["day"] for e in self.events() if e.get("event") == "candidate"})

    def pairs(self, setup: str | None = None) -> list[dict]:
        """Candidates with an actual exit and a 09:20 mark: [{id, setup, d (rupees per lot), carry, close}]."""
        evs = self.events()
        exits = {e["id"]: e for e in evs if e.get("event") == "exit"}
        marks = {e["id"]: e for e in evs if e.get("event") == "mark"}
        out = []
        for c in evs:
            if c.get("event") != "candidate" or (setup and c["setup"] != setup) or c["id"] not in exits or c["id"] not in marks:
                continue
            carry, close, lots = float(marks[c["id"]]["carry_pnl"]), float(exits[c["id"]]["pnl"]), max(int(c["lots"]), 1)
            out.append({"id": c["id"], "setup": c["setup"], "day": c["day"], "carry": carry, "close": close, "d": (carry - close) / lots})
        return out

    def unmarked(self, setup: str) -> int:
        return sum(1 for e in self.events() if e.get("event") == "unmarked" and e.get("setup") == setup)

    def open_records(self, next_day: dt.date) -> list[dict]:
        """Candidates due to be marked on `next_day` that are neither marked nor given up."""
        evs = self.events()
        done = {e["id"] for e in evs if e.get("event") in ("mark", "unmarked")}
        return [c for c in evs if c.get("event") == "candidate" and c.get("next_day") == str(next_day) and c["id"] not in done]

    def stale(self, day: dt.date) -> list[dict]:
        """Candidates whose marking day has passed without a mark: given up (never filled in)."""
        evs = self.events()
        done = {e["id"] for e in evs if e.get("event") in ("mark", "unmarked")}
        return [c for c in evs if c.get("event") == "candidate" and c.get("next_day") and c["next_day"] < str(day) and c["id"] not in done]


def mark_pnl(rec: dict, chain: pd.DataFrame, costs, ticks: float = 1.0) -> float | None:
    """The candidate's P&L had it been closed at `chain`'s real quotes: longs sold at the bid, shorts bought at the ask, each
    one paper-broker tick worse, the fees of the closing orders, the entry fees already paid. None if any leg is unpriced."""
    lots = int(rec["lots"])
    total, fees = 0.0, 0.0
    for l in rec["legs"]:
        side = l["right"].lower()
        try:
            px = float(chain.at[float(l["strike"]), f"{side}_bid" if l["qty"] > 0 else f"{side}_ask"])
        except KeyError:
            return None
        if not (math.isfinite(px) and px > 0):
            return None
        px = max(px - ticks * costs.tick, costs.tick) if l["qty"] > 0 else px + ticks * costs.tick
        q = l["qty"] * lots                                    # contracts: the record's legs hold the units of one lot
        inst = Instrument.option(rec["underlying"], dt.date.fromisoformat(l["expiry"]), l["strike"], l["right"], int(rec["lot"]))
        total += q * (px - float(l["entry"]))
        fees += costs.fees(inst, -q, px)[0]
    return total - float(rec["entry_fees"]) - fees


def usable_chain(chain, now: pd.Timestamp) -> bool:
    """A real-quote chain refreshed inside the 09:20-09:30 marking window (never a model)."""
    if str(chain.attrs.get("source")) not in REAL_SOURCES or not MARK_FROM <= now.time() <= MARK_TO:
        return False
    ts = pd.Timestamp(chain.attrs.get("ts"))
    ts = ts.tz_localize(now.tz) if ts.tzinfo is None else ts.tz_convert(now.tz)
    return MARK_FROM <= ts.time() <= MARK_TO


# ---- the evidence gate -------------------------------------------------------------------------------------------------------------
def _hist_passes(r: dict) -> bool:
    try:
        return bool(r) and all(k in r for k in ("n", "mean", "t", "mean_older", "mean_newest")) and r["n"] >= HIST_MIN_N \
            and r["mean"] > 0 and r["t"] >= HIST_T and r["mean_older"] > 0 and r["mean_newest"] > 0
    except TypeError:                                              # a null in the file is not a pass
        return False


def history(spec: dict, setup: str, folder: Path | None = None) -> tuple[str, dict | None]:
    """('passed'|'failed'|'absent', the row): read from the committed result file of THIS spec, recomputing the rule from its
    numbers rather than trusting its flag. A missing file, another spec's hash or an absent setup is 'absent'."""
    p = Path(folder or RESULTS) / f"{spec['name']}-{spec['_hash']}.json"
    if not p.exists():
        return "absent", None
    try:
        res = json.loads(p.read_text())
    except ValueError:
        return "absent", None
    if res.get("spec") != spec["_hash"]:
        return "absent", None
    row = (res.get("setups") or {}).get(setup)
    if not row:
        return "absent", None
    return ("passed" if _hist_passes(row) else "failed"), row


def forward(ledger: Ledger, setup: str, hist: dict | None) -> dict:
    d = [p["d"] for p in ledger.pairs(setup)]
    n, un = len(d), ledger.unmarked(setup)
    out = {"n": n, "unmarked": un, "mean": float("nan"), "t": float("nan"), "z": float("nan"), "status": "collecting"}
    if n >= 1:
        m = sum(d) / n
        out["mean"] = m
        if n >= 2:
            sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
            out.update(sd=sd, t=m / (sd / math.sqrt(n)) if sd > 0 else (math.inf if m > 0 else -math.inf))
            if hist and hist.get("sd"):
                out["z"] = (m - float(hist["mean"])) / (float(hist["sd"]) / math.sqrt(n))
    total = n + un
    if n >= FWD_MIN_N:
        ok = (out["mean"] > 0 and out["t"] >= FWD_T and (not hist or not hist.get("sd") or out["z"] >= FWD_Z)
              and (un / total if total else 0) <= UNMARKED_MAX)
        out["status"] = "passed" if ok else ("failed" if out["mean"] <= 0 or n >= FWD_MAX_N or un / total > UNMARKED_MAX else "collecting")
    return out


def gate(spec: dict, ledger: Ledger, setup: str, folder: Path | None = None) -> dict:
    """The setup's carry gate: history passed AND forward passed AND at least 5 shadow sessions on record."""
    h, row = history(spec, setup, folder)
    f = forward(ledger, setup, row)
    s = ledger.sessions()
    return {"setup": setup, "history": h, "forward": f["status"], "forward_stats": f, "sessions": s,
            "met": h == "passed" and f["status"] == "passed" and s >= SHADOW_SESSIONS_REQUIRED}


def effective(configured: str, spec: dict, ledger: Ledger, setup: str, folder: Path | None = None) -> tuple[str, str]:
    """(the mode in force for `setup`, why it is not the configured one). PHASE 1: `apply` is not implemented, so it is
    shadow whatever the gate says; the gate's state is part of the reason, so the record shows how far each setup is."""
    if configured != "apply":
        return configured, ""
    g = gate(spec, ledger, setup, folder)
    return "shadow", (f"apply is not implemented in this build (phase 1: shadow only); {setup}'s gate: history {g['history']}, "
                      f"forward {g['forward']}, {g['sessions']} of {SHADOW_SESSIONS_REQUIRED} shadow sessions")


# ---- the report ------------------------------------------------------------------------------------------------------------------
def report(spec: dict, ledger: Ledger, folder: Path | None = None) -> dict:
    """Per setup: candidates recorded, how many would have carried (lots that fit), the top reasons for the rest, the
    marked pairs with the running paired difference (carry - close, rupees per lot), unmarked, and the gate's state."""
    evs = ledger.events()
    cands = [e for e in evs if e.get("event") == "candidate"]
    rows = []
    for setup in SETUPS:
        mine = [c for c in cands if c.get("setup") == setup]
        why: dict[str, int] = {}
        for c in mine:
            for r in c.get("reasons") or []:
                key = "".join(ch for ch in r if not ch.isdigit())[:70]
                why[key] = why.get(key, 0) + 1
        g = gate(spec, ledger, setup, folder)
        rows.append({"setup": setup, "candidates": len(mine), "would_carry": sum(1 for c in mine if (c.get("lots_fit") or 0) >= 1),
                     "refusals": sorted(why.items(), key=lambda kv: -kv[1])[:3], "gate": g, **{k: g["forward_stats"][k] for k in ("n", "mean", "t", "unmarked")}})
    return {"spec": spec["name"], "spec_hash": spec["_hash"], "sessions": ledger.sessions(), "rows": rows, "records": len(cands)}


def render(rep: dict) -> str:
    def rs(x):
        return "–" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"₹{x:+,.0f}"
    out = [f"## Overnight carry (shadow) · {rep['spec']} · spec {rep['spec_hash']}", "",
           f"Phase 1: nothing is carried; every position open at the 15:15 square-off records what it would have carried "
           f"(full-max-loss sizing, one night) and is marked at the next session's 09:20 real quotes against its actual exit. "
           f"{rep['records']} records over {rep['sessions']} session(s). The desk's own evidence (L4, overnight theta) leans against carrying.", "",
           "| setup | records | would carry | marked | mean carry - close / lot | t | unmarked | history | forward |",
           "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for r in rep["rows"]:
        t = r["t"]
        out.append(f"| {r['setup']} | {r['candidates']} | {r['would_carry']} | {r['n']} | {rs(r['mean'])} | "
                   f"{'–' if t is None or not math.isfinite(t) else f'{t:.2f}'} | {r['unmarked']} | {r['gate']['history']} | {r['gate']['forward']} |")
    top = [f"{r['setup']}: {k.strip()} (x{v})" for r in rep["rows"] for k, v in r["refusals"][:1]]
    if top:
        out += ["", "**Why not (most common):** " + "; ".join(top)]
    out += ["", "Rules: docs/prereg/overnight_carry_v1.json. A paired difference above zero would mean carrying beat squaring off after costs."]
    return "\n".join(out)
