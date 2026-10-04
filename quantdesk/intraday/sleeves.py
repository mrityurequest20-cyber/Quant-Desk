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
- Exit: cash settlement at the expiry-day index close: the mean of the recorded 15:00–15:29 one-minute closes, else
  Yahoo's daily close. The source is recorded with every settlement.
- Settlement check (diagnostic, not a rule): the registered mean misses NSE's official close by about 10 bps (the L1
  evidence audit), while the history settles on the official close. So each settled trade also gets an `official`
  event: the official close (NSE's published file, else the 15:29 one-minute close, which matched it on every day the
  audit checked, else Yahoo's close), the P&L at it, and the gap. The registered settlement stays the result.
- Paper only. Nothing here can place an order or promote itself: it reports eligibility by the spec's rules, and a
  registered allocator spec (BACKLOG 9) is what moves an eligible sleeve into the paper account.

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
WIDE_SPREAD = 0.25                             # a leg whose bid-ask is over 25% of its mid is flagged 'wide'
LATE_SNAPSHOT_MIN = 5                          # a snapshot more than 5 minutes from 15:20 is flagged 'late'


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
        K = float(row["strike"])
        col = f"{right.lower()}_{'bidq' if sell else 'askq'}"           # the side this order would hit
        touch = float(chain.at[K, col]) if col in chain.columns and K in chain.index else float("nan")
        spread = (ask - bid) / mid if mid > 0 else float("nan")
        flags = (["wide"] if spread > WIDE_SPREAD else []) + (["locked"] if ask == bid else [])
        out.append({"qty": int(qty), "right": right, "strike": K, "target": float(target),
                    "delta": round(float(row["delta"]), 4), "iv": round(float(row["iv"]), 2),
                    "bid": bid, "ask": ask, "mid": mid,
                    "fill": round(max(bid - TICK, 0.0) if sell else ask + TICK, 2),
                    "model_fill": round(float(mid - leg_cost(mid) if sell else mid + leg_cost(mid)), 4),
                    "spread_pct": round(spread, 4) if math.isfinite(spread) else None,
                    "touch_qty": touch if math.isfinite(touch) else None, "flags": flags})
    if len({(x["right"], x["strike"]) for x in out}) < len(out):
        return None, "a wing landed on a short strike"
    return out, ""


def settlement_price(data_dir: Path, underlying: str, day: dt.date) -> tuple[float | None, str]:
    """The exchange's index close is built from the last 30 minutes: the mean of the recorded 15:00–15:29 one-minute
    closes, or, for an index the engine doesn't record bars for, of the index spot the chain tape logged each minute."""
    p = Path(data_dir) / str(day) / f"{underlying}_1m.csv"
    why = "no recorded bars"
    if p.exists():
        b = normalise_bars(pd.read_csv(p, index_col=0, parse_dates=True))
        last = b[b.index.time >= SETTLE_FROM]
        if len(last) >= MIN_SETTLE_BARS:
            return float(last["close"].mean()), f"mean of {len(last)} recorded 15:00–15:29 closes"
        why = f"only {len(last)} of 30 closing-half-hour bars recorded"
    t = Path(data_dir) / str(day) / "tape.csv"
    if t.exists():
        lg = pd.read_csv(t)
        lg = lg[(lg["underlying"] == underlying) & (lg["ok"].astype(str).str.lower() == "true")]
        ts = pd.to_datetime(lg["ts"].astype(str).str[:16], errors="coerce")
        lg = lg.assign(minute=ts)[(ts.dt.time >= SETTLE_FROM) & (ts.dt.time < dt.time(15, 30))]
        spot = pd.to_numeric(lg["spot"], errors="coerce").groupby(lg["minute"]).median().dropna()
        spot = spot[spot > 0]
        if len(spot) >= MIN_SETTLE_BARS:
            return float(spot.mean()), f"mean of {len(spot)} tape index spots 15:00–15:29"
        why += f"; tape has {len(spot)} closing-half-hour spots"
    return None, why


def official_close(data_dir: Path, underlying: str, day: dt.date) -> tuple[float | None, str]:
    """The 15:29 one-minute close: the last bar of the session, which equalled NSE's official close on every recorded
    day the L1 evidence audit checked."""
    p = Path(data_dir) / str(day) / f"{underlying}_1m.csv"
    if p.exists():
        b = normalise_bars(pd.read_csv(p, index_col=0, parse_dates=True))
        last = b[b.index.time == dt.time(15, 29)]
        if len(last):
            return float(last["close"].iloc[-1]), "the 15:29 one-minute close"
    return None, "no 15:29 bar recorded"


def payoff(t: dict, s_t: float) -> dict:
    """A trade held to cash settlement at index level `s_t`: points, STT on exercised long legs, P&L after the entry
    fees, and each leg's intrinsic value."""
    lot = int(t["lot"])
    pts, stt, intr_ = 0.0, 0.0, []
    for leg in t["legs"]:
        intr = intrinsic(leg["right"], leg["strike"], s_t)
        pts += -leg["qty"] * leg["fill"] + leg["qty"] * intr
        if leg["qty"] > 0 and intr > 0:
            stt += STT_EXERCISE * intr * leg["qty"] * lot
        intr_.append(round(intr, 2))
    return {"pnl_pts": pts, "stt_rs": stt, "pnl_rs": pts * lot - t["entry_fees_rs"] - stt, "intrinsic": intr_}


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
    def __init__(self, cfg, root: Path, data_dir: Path, close_fn=None, spec: dict | None = None, say=print,
                 official_fn=None):
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
        self.official_fn = official_fn            # (underlying, day) -> NSE's published close, or None

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
        official = {e["id"]: e for e in evs if e["event"] == "official"}

        def extra(src: dict, i: str) -> dict:
            return {k: v for k, v in src[i].items() if k not in ("event", "recorded_at", "spec")} if i in src else {}
        return [{**e, **extra(settled, e["id"]), **extra(official, e["id"]), "settled": e["id"] in settled}
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
        notes += self.check_settlement(day, now)
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
            r = payoff(t, s_t)
            self._append({"event": "settle", "id": t["id"], "settle": round(s_t, 2), "settle_source": src,
                          "intrinsic": r["intrinsic"], "stt_rs": round(r["stt_rs"], 2), "pnl_pts": round(r["pnl_pts"], 2),
                          "pnl_rs": round(r["pnl_rs"], 2)})
            notes.append(f"settled {t['id']} at {s_t:,.2f} ({src}): ₹{r['pnl_rs']:+,.0f}/lot")
        return notes

    def official(self, underlying: str, day: dt.date) -> tuple[float | None, str]:
        """The official close for the settlement check: NSE's published file, else the 15:29 one-minute close, else
        Yahoo's daily close."""
        why = []

        def call(name: str, fn) -> float | None:
            if fn is None:
                return None
            try:
                v = fn(underlying, day)
            except Exception as exc:
                why.append(f"{name}: {exc!s:.60}")
                return None
            if v is None or not math.isfinite(v) or v <= 0:
                why.append(f"{name}: none")
                return None
            return float(v)

        if (v := call("NSE's official close", self.official_fn)) is not None:
            return v, "NSE's official close"
        v, src = official_close(self.data, underlying, day)
        if v is not None:
            return v, src
        why.append(src)
        if (v := call("Yahoo daily close", self.close_fn)) is not None:
            return v, "Yahoo daily close"
        return None, "; ".join(why)

    def check_settlement(self, day: dt.date, now: pd.Timestamp) -> list[str]:
        """Diagnostic: each settled trade's P&L at the official close too, appended once as an `official` event. Runs
        from 15:45 on expiry day (the published sources lag the close); the registered settlement is never changed."""
        notes = []
        for t in self.trades():
            if not t["settled"] or "official" in t:
                continue
            exp = dt.date.fromisoformat(t["expiry"])
            if exp > day or (exp == now.date() and now.time() < dt.time(15, 45)):
                continue
            v, src = self.official(t["underlying"], exp)
            if v is None:
                continue
            r = payoff(t, v)
            ev = self._append({"event": "official", "id": t["id"], "official": round(v, 2), "official_source": src,
                               "pnl_rs_official": round(r["pnl_rs"], 2),
                               "settle_gap_bps": round((float(t["settle"]) / v - 1) * 1e4, 2),
                               "pnl_gap_rs": round(float(t["pnl_rs"]) - r["pnl_rs"], 2)})
            notes.append(f"settlement check {t['id']}: official {v:,.2f} ({src}), registered {float(t['settle']):,.2f} "
                         f"({ev['settle_gap_bps']:+.1f} bps); P&L at official ₹{r['pnl_rs']:+,.0f} vs ₹{float(t['pnl_rs']):+,.0f}")
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
        try:
            off = abs(_mins(int(snap.stem.rsplit("_", 1)[1])) - _mins(ENTRY))
        except ValueError:
            off = None
        for leg in legs:
            if leg.get("touch_qty") is not None and leg["touch_qty"] < abs(leg["qty"]) * lot:
                leg.setdefault("flags", []).append("thin")              # less size at the touch than this order
        quality = sorted({f for x in legs for f in x.get("flags", [])}
                         | ({"late"} if off is not None and off > LATE_SNAPSHOT_MIN else set()))
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
                           "max_loss_rs": max_loss, "margin_est_rs": margin, "snapshot_off_min": off,
                           "quote_flags": quality})
        k = ", ".join(f"{'S' if x['qty'] < 0 else 'B'} {x['strike']:.0f}{x['right']} @{x['fill']:.2f}" for x in legs)
        return (f"opened {ev['id']} at {pd.Timestamp(ev['ts']):%H:%M} (spot {spot:,.2f}): {k}; credit ₹{credit * lot:,.0f}/lot, "
                f"cost gap vs history's convention ₹{ev['cost_gap_rs']:+,.0f}")

    # ---- the report ----------------------------------------------------------------------------------------------
    def report(self) -> dict:
        rows, evs = [], self.events()
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
                    "eligible for the paper account (the registered allocator applies it)" if a["eligible"] else "collecting")
                rows.append({"sleeve": s, "strategy": self.sleeves[s]["strategy"], "underlying": u, "history": h, **a,
                             "status": status, "naked": self.sleeves[s]["naked"], **skip_rate(evs, s, u)})
        trades = self.trades()
        return {"spec": self.spec["name"], "spec_hash": self.spec["_hash"], "rows": rows,
                "fills": fill_quality(evs), "settlement": settlement_check(trades),
                "open": [t for t in trades if not t["settled"]],
                "recent": [t for t in trades if t["settled"]][-8:],
                "skips": [e for e in evs if e["event"] == "skip"][-8:]}



def skip_rate(events: list[dict], sleeve: str, underlying: str) -> dict:
    """Eves this sleeve was due on and didn't trade: a high rate means the forward record covers fewer eves than the
    history, and not at random (a skip is usually a missing or thin quote)."""
    n = {"open": 0, "skip": 0}
    for e in events:
        if e.get("event") in n and e.get("sleeve") == sleeve and e.get("underlying") == underlying:
            n[e["event"]] += 1
    due = n["open"] + n["skip"]
    return {"eves_due": due, "skipped": n["skip"], "skip_rate": round(n["skip"] / due, 4) if due else None}


def settlement_check(trades: list[dict]) -> dict:
    """Per underlying: how far the registered settlement (15:00–15:29 mean) sat from the official close, and what it did
    to P&L. The history settles on the official close, so this gap is a forward-vs-history difference that is not
    the market's."""
    out: dict[str, dict] = {}
    for t in trades:
        if "official" not in t:
            continue
        o = out.setdefault(t["underlying"], {"days": {}, "pnl_gap": 0.0, "trades": 0, "sources": {}})
        o["days"][t["expiry"]] = float(t["settle_gap_bps"])
        o["pnl_gap"] += float(t["pnl_gap_rs"])
        o["trades"] += 1
        o["sources"][t["official_source"]] = o["sources"].get(t["official_source"], 0) + 1
    res = {}
    for u, o in sorted(out.items()):
        g = np.array(list(o["days"].values()))
        res[u] = {"days": len(g), "trades": o["trades"], "mean_gap_bps": round(float(g.mean()), 2),
                  "mean_abs_gap_bps": round(float(np.abs(g).mean()), 2), "max_abs_gap_bps": round(float(np.abs(g).max()), 2),
                  "pnl_gap_rs": round(o["pnl_gap"], 2), "sources": o["sources"]}
    return res


def fill_quality(events: list[dict]) -> dict:
    """Did the paper fills measure reality? Per underlying, over every leg the sleeves opened:
    - real cost: how far each fill sat from the quote's mid (the spread crossed plus a tick);
    - model cost: what the history assumed for the same leg (warehouse_research.leg_cost);
    - real ÷ model: above 1, the history's results were too kind;
    - the median bid-ask as a share of mid;
    - the share of legs flagged (wide, locked, thin, late snapshot) and the size at the touch, where the book showed it.
    Skips are counted by reason: the data the sleeves refused."""
    out: dict[str, dict] = {}
    for e in events:
        if e.get("event") == "open":
            o = out.setdefault(e["underlying"], {"trades": 0, "legs": 0, "real": 0.0, "model": 0.0, "spreads": [],
                                                 "flagged": 0, "flags": {}, "skips": {}})
            o["trades"] += 1
            for x in e.get("legs", []):
                o["legs"] += 1
                o["real"] += abs(float(x["fill"]) - float(x["mid"]))
                o["model"] += abs(float(x["model_fill"]) - float(x["mid"]))
                if x.get("spread_pct") is not None:
                    o["spreads"].append(float(x["spread_pct"]))
                fl = x.get("flags") or []
                o["flagged"] += bool(fl)
                for f in fl:
                    o["flags"][f] = o["flags"].get(f, 0) + 1
            for f in e.get("quote_flags") or []:
                if f == "late":
                    o["flags"]["late"] = o["flags"].get("late", 0) + 1
        elif e.get("event") == "skip":
            o = out.setdefault(e["underlying"], {"trades": 0, "legs": 0, "real": 0.0, "model": 0.0, "spreads": [],
                                                 "flagged": 0, "flags": {}, "skips": {}})
            why = re.sub(r"[-+]?\d[\d.,]*", "#", str(e.get("reason", "")))[:60]
            o["skips"][why] = o["skips"].get(why, 0) + 1
    return {u: {"trades": o["trades"], "legs": o["legs"],
                "real_cost_pts": round(o["real"] / o["legs"], 3) if o["legs"] else None,
                "model_cost_pts": round(o["model"] / o["legs"], 3) if o["legs"] else None,
                "real_vs_model": round(o["real"] / o["model"], 2) if o["model"] > 0 else None,
                "median_spread_pct": round(float(np.median(o["spreads"])), 4) if o["spreads"] else None,
                "flagged_legs": o["flagged"], "flags": o["flags"], "skips": o["skips"]}
            for u, o in sorted(out.items())}

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
    due = [r for r in rep["rows"] if r.get("eves_due")]
    if due:
        out += ["", "**Skip rate (eves due, not traded):** " + "; ".join(
            f"{r['sleeve']} {r['underlying']} {r['skipped']}/{r['eves_due']} ({r['skip_rate']:.0%})" for r in due)]
    st = rep.get("settlement") or {}
    if st:
        out += ["", "**Settlement check (registered 15:00–15:29 mean vs the official close; diagnostic):** " + "; ".join(
            f"{u}: {c['days']} expiries, mean |gap| {c['mean_abs_gap_bps']:.1f} bps (max {c['max_abs_gap_bps']:.1f}), "
            f"P&L at the registered rule minus at the official close {rs(c['pnl_gap_rs'])} over {c['trades']} trades"
            for u, c in st.items())]
    fills = {u: f for u, f in (rep.get("fills") or {}).items() if f["legs"]}
    if fills:
        out += ["", "**Fill quality (real quotes vs the history's cost model):** " + "; ".join(
            f"{u}: {f['legs']} legs, real {f['real_cost_pts']:.2f} vs model {f['model_cost_pts']:.2f} pts a leg "
            f"(×{f['real_vs_model']}), median spread {f['median_spread_pct']:.0%} of mid"
            + (f", flagged {f['flagged_legs']} ({', '.join(f'{k} {v}' for k, v in f['flags'].items())})" if f["flags"] else "")
            for u, f in fills.items())]
    out += ["", "Forward results alone can't prove profit (A NIFTY: 26 trades give an expected t of ~0.27). What they show "
            "quickly is whether real quotes cost what the 2019–26 history assumed (the cost gap) and whether results break "
            "from that history. Rules: docs/prereg/expiry_seller_v1.json."]
    return "\n".join(out)
