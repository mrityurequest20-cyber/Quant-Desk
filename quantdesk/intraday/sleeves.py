"""Expiry sellers: forward paper sleeves that sell index premium near the close of the session before an expiry and hold
it to settlement. The rules are pre-registered in docs/prereg/expiry_seller_v1.json; this module only carries them out.

Why this test: across 7.7 years of real NSE option prices (research/warehouse_research.py) the one effect that survived
costs was selling 20-delta premium one session before expiry. That history priced every leg at the bhavcopy close with
a modelled cost. It cannot say whether the real bid/ask at that minute is as kind. These sleeves measure exactly that,
trade by trade, on the chain tape's real quotes. They also retire a sleeve as soon as its forward results break from
its history.

- Sleeves:
  - A = iron_condor_20_10 (defined risk);
  - B = short_strangle_20d (naked);
  - on NIFTY (weekly) and BANKNIFTY (monthly), 1 lot each.
- Entry: the tape snapshot nearest 15:20 IST on the session before expiry, real quotes only. Sells fill at bid − 0.05,
  buys at ask + 0.05, statutory fees per leg.
- Exit: cash settlement at the expiry-day index close: the mean of the recorded 15:00–15:29 one-minute closes, which is
  how NSE builds it, else Yahoo's daily close. The source is recorded with every settlement.
- Paper only. Nothing here can place an order, and nothing is promoted automatically: eligibility is reported for the
  account owner to act on.

Each spec (docs/prereg/expiry_seller_v*.json) names its sleeves, legs, underlyings and history. A new pre-registered
sleeve is a new spec file, not new code. One ledger per spec: runtime/intraday/sleeves/<spec name>.jsonl, append-only
(open / settle / skip events), saved with the journal.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.calendar import TradingCalendar
from ..core.types import Instrument
from ..execution.costs import CostModel
from ..research.warehouse_research import NAKED, STRATEGIES, STT_EXERCISE, leg_cost
from .chains import IntradayPricer, load_chain
from .feeds import IST, normalise_bars
from .playbook import StrikePicker

PREREG = Path(__file__).resolve().parents[2] / "docs" / "prereg"
SPEC_PATH = PREREG / "expiry_seller_v1.json"
REAL_SOURCES = {"kotak", "nse"}                # exchange quotes; a modelled chain is refused
ENTRY, WINDOW = 1520, (1510, 1525)             # HHMM: the snapshot nearest 15:20 inside 15:10–15:25
TICK = 0.05
DELTA_TOL = 0.08                               # as in the history (warehouse_research.build_trades)
SETTLE_FROM, MIN_SETTLE_BARS = dt.time(15, 0), 20
MIN_COST, MIN_CONSISTENCY, MIN_ELIGIBLE = 6, 8, 10
Z90, Z95 = 1.2816, 1.645
NAKED_MARGIN = 0.12                            # rough SPAN + exposure for one side of a naked index strangle
B_AFTER_A_DAYS = 91


def load_spec(path: Path = SPEC_PATH) -> dict:
    raw = Path(path).read_bytes()
    spec = json.loads(raw)
    spec["_hash"] = hashlib.sha256(raw).hexdigest()[:12]
    return spec


def specs(folder: Path = PREREG) -> list[dict]:
    """Every registered expiry-seller spec, oldest version first."""
    return [load_spec(p) for p in sorted(Path(folder).glob("expiry_seller_v*.json"),
                                         key=lambda p: int(re.sub(r"\D", "", p.stem.rsplit("_v", 1)[1]) or 0))]


def sleeve_table(spec: dict) -> dict:
    """{sleeve: strategy, legs [(qty, right, delta)], underlyings, naked} from a spec (legs default to the history's)."""
    out = {}
    for k, v in spec["sleeves"].items():
        legs = ([(int(q), r, float(d)) for q, r, d in v["legs"]] if isinstance(v.get("legs"), list)   # v1 describes them
                else STRATEGIES[v["strategy"]][0])
        out[k] = {"strategy": v["strategy"], "legs": legs, "underlyings": list(v.get("underlyings") or spec["underlyings"]),
                  "naked": bool(v.get("naked", v["strategy"] in NAKED))}
    return out


def _mins(hhmm: int) -> int:
    return hhmm // 100 * 60 + hhmm % 100


def entry_snapshot(day_dir: Path, underlying: str, expiry: dt.date) -> Path | None:
    """The tape's snapshot of this expiry nearest 15:20 within 15:10–15:25 (ties: the earlier one)."""
    best = None
    for p in (Path(day_dir) / "chains").glob(f"{underlying}_{expiry}_*.csv"):
        try:
            hhmm = int(p.stem.rsplit("_", 1)[1])
        except ValueError:
            continue
        if WINDOW[0] <= hhmm <= WINDOW[1]:
            key = (abs(_mins(hhmm) - _mins(ENTRY)), hhmm)
            if best is None or key < best[0]:
                best = (key, p)
    return best[1] if best else None


def pick_legs(chain: pd.DataFrame, legs, now, picker: StrikePicker) -> tuple[list[dict] | None, str]:
    """The history's strike rule on a real snapshot: out of the money, |delta| nearest the target and within 0.08 of it,
    a two-sided quote on every leg, no wing on a short strike. Returns (legs, "") or (None, why not)."""
    S = float(chain.attrs["spot"])
    rows = {r: picker.rows(chain, r, now) for r in ("CE", "PE")}
    out = []
    for qty, right, target in legs:
        r = rows[right].dropna(subset=["delta"])
        r = r[(r["strike"] > S) if right == "CE" else (r["strike"] < S)]
        if r.empty:
            return None, f"no out-of-the-money {right} strike priced"
        j = int(np.argmin(np.abs(r["delta"].abs().to_numpy() - abs(target))))
        row = r.iloc[j]
        if abs(abs(float(row["delta"])) - abs(target)) > DELTA_TOL:
            return None, f"no {right} within {DELTA_TOL} of delta {target:+.2f} (nearest {float(row['delta']):+.3f})"
        bid, ask, mid = float(row["bid"]), float(row["ask"]), float(row["mid"])
        if not (math.isfinite(bid) and math.isfinite(ask) and bid > 0 and ask >= bid):
            return None, f"{right} {float(row['strike']):.0f}: no two-sided quote"
        sell = qty < 0
        out.append({"qty": int(qty), "right": right, "strike": float(row["strike"]), "target": float(target),
                    "delta": round(float(row["delta"]), 4), "iv": round(float(row["iv"]), 2),
                    "bid": bid, "ask": ask, "mid": mid,
                    "fill": round(max(bid - TICK, 0.0) if sell else ask + TICK, 2),
                    "model_fill": round(float(mid - leg_cost(mid) if sell else mid + leg_cost(mid)), 4)})
    if len({(x["right"], x["strike"]) for x in out}) < len(out):
        return None, "a wing landed on a short strike"
    return out, ""


def settlement_price(data_dir: Path, underlying: str, day: dt.date) -> tuple[float | None, str]:
    """NSE's index close is built from the last 30 minutes: the mean of the recorded 15:00–15:29 one-minute closes."""
    p = Path(data_dir) / str(day) / f"{underlying}_1m.csv"
    if not p.exists():
        return None, "no recorded bars"
    b = normalise_bars(pd.read_csv(p, index_col=0, parse_dates=True))
    last = b[b.index.time >= SETTLE_FROM]
    if len(last) < MIN_SETTLE_BARS:
        return None, f"only {len(last)} of 30 closing-half-hour bars recorded"
    return float(last["close"].mean()), f"mean of {len(last)} recorded 15:00–15:29 closes"


def intrinsic(right: str, strike: float, s_t: float) -> float:
    return max(s_t - strike, 0.0) if right == "CE" else max(strike - s_t, 0.0)


def _stats(x: list[float]) -> tuple[float, float]:
    a = np.asarray(x, dtype=float)
    return (float(a.mean()) if len(a) else float("nan"), float(a.std(ddof=1)) if len(a) > 1 else float("nan"))


def assess(trades: list[dict], hist: dict, naked: bool) -> dict:
    """The spec's rules on one sleeve and underlying's settled trades (oldest first)."""
    n = len(trades)
    pnl = [t["pnl_rs"] for t in trades]
    gap = [t["cost_gap_rs"] for t in trades]
    mean, _ = _stats(pnl)
    gmean, gsd = _stats(gap)
    out = {"n": n, "sum": float(sum(pnl)), "mean": mean, "win": float(np.mean([p > 0 for p in pnl])) if n else float("nan"),
           "worst": float(min(pnl)) if n else float("nan"), "gap_mean": gmean, "gap_lcb90": float("nan"),
           "cost": f"collecting ({n}/{MIN_COST})", "consistency": f"collecting ({n}/{MIN_CONSISTENCY})", "z": float("nan"),
           "tail": "ok", "retired": None, "bugs": [], "eligible": False}
    if n >= MIN_COST:
        lcb = gmean - Z90 * (gsd if math.isfinite(gsd) else 0.0) / math.sqrt(n)
        out["gap_lcb90"] = lcb
        if hist["mean"] + lcb > 0:
            out["cost"] = "passed"
        else:
            out["cost"] = "failed"
            out["retired"] = (f"real quotes cost more than the edge: history ₹{hist['mean']:,.0f}/lot, cost gap 90% low "
                              f"₹{lcb:,.0f}")
    if n >= MIN_CONSISTENCY:
        z = (mean - hist["mean"]) / (hist["sd"] / math.sqrt(n))
        out["z"] = z
        if z < -Z95:
            out["consistency"] = "rejected"
            out["retired"] = out["retired"] or f"forward mean ₹{mean:,.0f} breaks from the history's ₹{hist['mean']:,.0f} (z {z:.2f})"
        else:
            out["consistency"] = "consistent"
    if naked and n and min(pnl) < -1.5 * abs(hist["worst"]):
        out["tail"] = "breached"
        out["retired"] = out["retired"] or f"a loss of ₹{min(pnl):,.0f} beyond 1.5× the history's worst"
    for t in trades:
        if t.get("max_loss_rs") is not None and t["pnl_rs"] + t.get("stt_rs", 0.0) < -t["max_loss_rs"] - 1:   # STT on exercise is extra
            out["bugs"].append(f"{t['id']}: lost ₹{-t['pnl_rs']:,.0f}, beyond its max loss ₹{t['max_loss_rs']:,.0f}")
    out["eligible"] = (not naked and n >= MIN_ELIGIBLE and out["cost"] == "passed"
                       and out["consistency"] == "consistent" and not out["retired"] and not out["bugs"])
    return out


class ExpirySeller:
    def __init__(self, cfg, root: Path, data_dir: Path, close_fn=None, spec: dict | None = None, say=print):
        self.cfg, self.root, self.data = cfg, Path(root), Path(data_dir)
        self.spec = spec or load_spec()
        self.ledger = self.root / f"{self.spec['name']}.jsonl"
        self.sleeves = sleeve_table(self.spec)
        self.hist = self.spec["history"]["per_lot_rupees"]
        self.cal = TradingCalendar(cfg.holidays())
        self.costs = CostModel(cfg)
        self.picker = StrikePicker(IntradayPricer(cfg.get("backtest.risk_free", 0.065), cfg.get("backtest.dividend_yield", 0.012)))
        self.underlyings = list(self.spec["underlyings"])
        self.close_fn, self.say = close_fn, say

    # ---- the ledger ----------------------------------------------------------------------------------------------
    def events(self) -> list[dict]:
        if not self.ledger.exists():
            return []
        return [json.loads(x) for x in self.ledger.read_text().splitlines() if x.strip()]

    def _append(self, ev: dict) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        ev = {"spec": self.spec["_hash"], "recorded_at": pd.Timestamp.now(tz=IST).isoformat(timespec="seconds"), **ev}
        with self.ledger.open("a") as f:
            f.write(json.dumps(ev, default=str) + "\n")
        return ev

    def trades(self) -> list[dict]:
        """Every opened trade, merged with its settlement if it has one (oldest first)."""
        evs = self.events()
        settled = {e["id"]: e for e in evs if e["event"] == "settle"}
        return [{**e, **({k: v for k, v in settled[e["id"]].items() if k not in ("event", "recorded_at")}
                         if e["id"] in settled else {}), "settled": e["id"] in settled}
                for e in evs if e["event"] == "open"]

    def assessment(self, sleeve: str, underlying: str) -> dict:
        done = [t for t in self.trades() if t["settled"] and t["sleeve"] == sleeve and t["underlying"] == underlying]
        return assess(done, self.hist[f"{sleeve}_{underlying}"], self.sleeves[sleeve]["naked"])

    def trading(self, underlying: str) -> list[str]:
        return [s for s, v in self.sleeves.items() if underlying in v["underlyings"]]

    def eligible_since(self, underlying: str) -> str | None:
        """The settlement date on which this spec's first defined-risk sleeve became eligible on this underlying (a
        naked sleeve waits 3 months behind it)."""
        hedged = [s for s in self.trading(underlying) if not self.sleeves[s]["naked"]]
        if not hedged:
            return None
        s = hedged[0]
        done = [t for t in self.trades() if t["settled"] and t["sleeve"] == s and t["underlying"] == underlying]
        for k in range(MIN_ELIGIBLE, len(done) + 1):
            if assess(done[:k], self.hist[f"{s}_{underlying}"], False)["eligible"]:
                return done[k - 1]["expiry"]
        return None

    # ---- a day ---------------------------------------------------------------------------------------------------
    def run(self, day: dt.date, now: pd.Timestamp | None = None) -> list[str]:
        """Settle what has expired, then open what this session's snapshot allows. Safe to re-run: nothing opens,
        settles or skips twice. Before 15:26 on `day` nothing opens; before 15:31 nothing expiring today settles."""
        now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=IST)
        now = now.tz_localize(IST) if now.tzinfo is None else now.tz_convert(IST)
        notes = self.settle(day, now)
        if self.cal.is_trading_day(day):
            notes += self.open(day, now)
        return notes

    def settle(self, day: dt.date, now: pd.Timestamp) -> list[str]:
        notes = []
        for t in self.trades():
            exp = dt.date.fromisoformat(t["expiry"])
            if t["settled"] or exp > day:
                continue
            if exp == now.date() and now.time() < dt.time(15, 31):
                continue
            s_t, src = settlement_price(self.data, t["underlying"], exp)
            if s_t is None and self.close_fn is not None and (exp < now.date() or now.time() >= dt.time(15, 45)):
                why = src
                try:
                    s_t = self.close_fn(t["underlying"], exp)
                    src = f"Yahoo daily close ({why})"
                except Exception as exc:
                    src = f"{why}; Yahoo: {exc!s:.80}"
            if s_t is None or not math.isfinite(s_t):
                notes.append(f"UNSETTLED {t['id']}: {src}")
                continue
            lot = int(t["lot"])
            pts, stt = 0.0, 0.0
            payoff = []
            for leg in t["legs"]:
                intr = intrinsic(leg["right"], leg["strike"], s_t)
                pts += -leg["qty"] * leg["fill"] + leg["qty"] * intr
                if leg["qty"] > 0 and intr > 0:
                    stt += STT_EXERCISE * intr * leg["qty"] * lot
                payoff.append(round(intr, 2))
            pnl = pts * lot - t["entry_fees_rs"] - stt
            self._append({"event": "settle", "id": t["id"], "settle": round(s_t, 2), "settle_source": src,
                          "intrinsic": payoff, "stt_rs": round(stt, 2), "pnl_pts": round(pts, 2), "pnl_rs": round(pnl, 2)})
            notes.append(f"settled {t['id']} at {s_t:,.2f} ({src}): ₹{pnl:+,.0f}/lot")
        return notes

    def due(self, underlying: str, day: dt.date) -> dt.date | None:
        """The expiry this session is the eve of, if any: by the holiday calendar or a recorded chain for it."""
        nxt = self.cal.next_trading_day(day)
        spec = self.cfg.instrument_spec(underlying)
        exps = self.cal.expiries(day, 40, int(spec.get("expiry_weekday", 1)), bool(spec.get("weekly_expiry", True)))
        if nxt in exps or any((self.data / str(day) / "chains").glob(f"{underlying}_{nxt}_*.csv")):
            return nxt
        return None

    def missed(self, day: dt.date) -> list[str]:
        """Eves in the last 10 days (on or after registration) the sleeves never ran on: on the record, not dropped."""
        floor = dt.date.fromisoformat(self.spec["registered"])
        seen = {(e["sleeve"], e["underlying"], e["expiry"]) for e in self.events() if e["event"] in ("open", "skip")}
        notes = []
        for k in range(10, 0, -1):
            past = day - dt.timedelta(days=k)
            if past < floor or not self.cal.is_trading_day(past):
                continue
            for u in self.underlyings:
                exp = self.due(u, past)
                for s in self.trading(u) if exp else ():
                    if (s, u, str(exp)) not in seen:
                        reason = f"the sleeves did not run on the eve ({past})"
                        self._append({"event": "skip", "sleeve": s, "strategy": self.sleeves[s]["strategy"], "underlying": u,
                                      "expiry": str(exp), "day": str(past), "reason": reason})
                        notes.append(f"skip {s}-{u}-{exp}: {reason}")
        return notes

    def open(self, day: dt.date, now: pd.Timestamp) -> list[str]:
        notes = self.missed(day)
        if now.date() == day and now.time() < dt.time(15, 26):
            return notes
        seen = {(e["sleeve"], e["underlying"], e["expiry"]) for e in self.events() if e["event"] in ("open", "skip")}
        for u in self.underlyings:
            exp = self.due(u, day)
            if exp is None:
                continue
            todo = [s for s in self.trading(u) if (s, u, str(exp)) not in seen]
            if not todo:
                continue
            lot = int(self.spec["underlyings"][u]["lot"])
            snap = entry_snapshot(self.data / str(day), u, exp)
            chain = load_chain(snap) if snap else None
            for s in todo:
                base = {"sleeve": s, "strategy": self.sleeves[s]["strategy"], "underlying": u, "expiry": str(exp),
                        "day": str(day)}
                a = self.assessment(s, u)
                if a["retired"]:
                    reason = f"retired under the spec: {a['retired']}"
                elif chain is None:
                    reason = f"no real-quote snapshot of the {exp} chain between 15:10 and 15:25"
                elif str(chain.attrs.get("source")) not in REAL_SOURCES:
                    reason = f"modelled chain ({chain.attrs.get('source')}) refused: real quotes only"
                else:
                    reason = ""
                if reason:
                    self._append({"event": "skip", **base, "reason": reason})
                    notes.append(f"skip {s}-{u}-{exp}: {reason}")
                    continue
                ts = pd.Timestamp(chain.attrs["ts"])
                legs, why = pick_legs(chain, self.sleeves[s]["legs"], ts, self.picker)
                if legs is None:
                    self._append({"event": "skip", **base, "snapshot": snap.name, "reason": why})
                    notes.append(f"skip {s}-{u}-{exp}: {why}")
                    continue
                notes.append(self._open(base, legs, chain, snap, lot))
        return notes

    def _open(self, base: dict, legs: list[dict], chain, snap: Path, lot: int) -> str:
        u, exp = base["underlying"], dt.date.fromisoformat(base["expiry"])
        fees = 0.0
        for leg in legs:
            inst = Instrument.option(u, exp, leg["strike"], leg["right"], lot)
            leg["fees_rs"] = round(self.costs.fees(inst, leg["qty"] * lot, leg["fill"])[0], 2)
            fees += leg["fees_rs"]
        credit = sum(-x["qty"] * x["fill"] for x in legs)
        model = sum(-x["qty"] * x["model_fill"] for x in legs)
        spot = float(chain.attrs["spot"])
        if not self.sleeves[base["sleeve"]]["naked"]:
            width = max(max(x["strike"] for x in legs if x["right"] == r) - min(x["strike"] for x in legs if x["right"] == r)
                        for r in ("CE", "PE"))
            max_loss = round(max(width - credit, 0.0) * lot + fees, 2)
            margin = max_loss
        else:
            max_loss, margin = None, round(NAKED_MARGIN * spot * lot, 0)
        ev = self._append({"event": "open", "id": f"{base['sleeve']}-{u}-{exp}", **base, "ts": str(chain.attrs["ts"]),
                           "snapshot": snap.name, "source": str(chain.attrs.get("source")), "spot": spot, "lot": lot,
                           "legs": legs, "credit_pts": round(credit, 2), "model_credit_pts": round(model, 2),
                           "cost_gap_rs": round((credit - model) * lot, 2), "entry_fees_rs": round(fees, 2),
                           "max_loss_rs": max_loss, "margin_est_rs": margin})
        k = ", ".join(f"{'S' if x['qty'] < 0 else 'B'} {x['strike']:.0f}{x['right']} @{x['fill']:.2f}" for x in legs)
        return (f"opened {ev['id']} at {pd.Timestamp(ev['ts']):%H:%M} (spot {spot:,.2f}): {k}; credit ₹{credit * lot:,.0f}/lot, "
                f"cost gap vs history's convention ₹{ev['cost_gap_rs']:+,.0f}")

    # ---- the report ----------------------------------------------------------------------------------------------
    def report(self) -> dict:
        rows = []
        for u in self.underlyings:
            since = self.eligible_since(u)
            for s in self.trading(u):
                a = self.assessment(s, u)
                h = self.hist[f"{s}_{u}"]
                if self.sleeves[s]["naked"] and since and not a["retired"]:
                    waited = (pd.Timestamp.now(tz=IST).date() - dt.date.fromisoformat(since)).days
                    ok = (a["n"] >= MIN_ELIGIBLE and a["cost"] == "passed" and a["consistency"] == "consistent"
                          and a["tail"] == "ok" and waited >= B_AFTER_A_DAYS)
                    a["eligible"] = ok
                status = ("retired: " + a["retired"]) if a["retired"] else (
                    "eligible for the paper account (owner decides)" if a["eligible"] else "collecting")
                rows.append({"sleeve": s, "strategy": self.sleeves[s]["strategy"], "underlying": u, "history": h, **a,
                             "status": status, "naked": self.sleeves[s]["naked"]})
        trades = self.trades()
        evs = self.events()
        return {"spec": self.spec["name"], "spec_hash": self.spec["_hash"], "rows": rows,
                "open": [t for t in trades if not t["settled"]],
                "recent": [t for t in trades if t["settled"]][-8:],
                "skips": [e for e in evs if e["event"] == "skip"][-8:]}


def render(rep: dict) -> str:
    def rs(x, sign=True):
        return "–" if x is None or (isinstance(x, float) and not math.isfinite(x)) else (f"₹{x:+,.0f}" if sign else f"₹{x:,.0f}")
    kinds = {}
    for r in rep["rows"]:
        kinds.setdefault(r["sleeve"], f"{r['sleeve']} = {r['strategy']} ({'naked' if r['naked'] else 'defined risk'})")
    out = [f"## Expiry sellers (paper) · {rep['spec']} · spec {rep['spec_hash']}", "",
           "Sold at ~15:20 the session before expiry on real quotes, held to settlement. " + ", ".join(kinds.values())
           + ". 1 lot each; ₹ per lot.", "",
           "| sleeve | trades | P&L | mean (history) | win | worst (history) | cost gap mean / 90% low | cost | consistency | status |",
           "|---|---:|---:|---:|---:|---:|---:|---|---|---|"]
    for r in rep["rows"]:
        h = r["history"]
        win = f"{r['win']:.0%}" if r["n"] else "–"
        out.append(f"| {r['sleeve']} {r['underlying']} | {r['n']} | {rs(r['sum']) if r['n'] else '–'} | {rs(r['mean'])} ({rs(h['mean'])}) | "
                   f"{win} ({h['win']:.0%}) | "
                   f"{rs(r['worst'])} ({rs(h['worst'])}) | {rs(r['gap_mean'])} / {rs(r['gap_lcb90'])} | {r['cost']} | "
                   f"{r['consistency']} | {r['status']} |")
    bugs = [b for r in rep["rows"] for b in r["bugs"]]
    if bugs:
        out += ["", "**Bugs (a defined-risk trade lost more than its max loss):** " + "; ".join(bugs)]
    if rep["open"]:
        out += ["", "**Open:** " + "; ".join(
            f"{t['id']} credit ₹{t['credit_pts'] * t['lot']:,.0f}" + (f", max loss ₹{t['max_loss_rs']:,.0f}" if t["max_loss_rs"] else "")
            + f", margin ~₹{t['margin_est_rs']:,.0f}" for t in rep["open"])]
    if rep["recent"]:
        out += ["", "**Settled (latest):** " + "; ".join(f"{t['id']} {rs(t['pnl_rs'])} at {t['settle']:,.2f}" for t in rep["recent"])]
    if rep["skips"]:
        out += ["", "**Skipped (latest):** " + "; ".join(f"{e['sleeve']}-{e['underlying']}-{e['expiry']}: {e['reason']}"
                                                          for e in rep["skips"])]
    out += ["", "Forward results alone can't prove profit (A NIFTY: 26 trades give an expected t of ~0.27). What they show "
            "quickly is whether real quotes cost what the 2019–26 history assumed (the cost gap) and whether results break "
            "from that history. Rules: docs/prereg/expiry_seller_v1.json."]
    return "\n".join(out)
