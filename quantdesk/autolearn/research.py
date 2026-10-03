"""Cost-aware, multi-horizon, plan-level research, with evidence kept in separate tracks.

Only two recorded sessions of real option chains exist. A chain modelled from bhavcopy IV is good for plumbing tests
and sensitivity analysis, but it is not evidence that an option strategy has an edge. So the study runs three tracks
and never combines them:

  real        `real_point_in_time` outcomes from the desk's recorded books (plans.py). The only qualifying track: the
              only one that can support a claim of positive expectancy, a DTE-policy change, a promotion, or
              paper-gate progress. Until it has `min_real_sessions` sessions it is descriptive only, and nothing is
              fitted on it.
  scenario    `modelled` outcomes (pricer on bhavcopy IV / India VIX). SCENARIO ANALYSIS ONLY: never registered,
              never promoted, never combined with real results, no locked test spent on it.
  eod         `real_eod_approximation` outcomes (bhavcopy open → close, pessimistic stop by the daily low). Real
              prices, but not point in time: a descriptive DTE and cost study, nothing more.

The protocol (pre-declared here and in config `autolearn.plan_research`):

1. Decision points: every completed 5-minute bar from 09:20 to 14:45.
2. Labels, per decision × DTE bucket (0, 1, 2, 3–5, 6+ trading days) × side × horizon (30m / 60m / 120m / close):
   the plan's outcome under the live engine's own strike, veto, entry and exit rules (plans.py). Each horizon is its
   own label and its own model.
3. One simple baseline (policy.py): a calibrated logistic P(net > 0) → expected net R → abstain below τ. Another
   candidate is added only when it improves out-of-sample plan-level net results after costs.
4. Development, per track: a day-grouped expanding walk-forward (5 folds after 15 sessions) with purge and an
   embargo of the horizon.
   - The development folds alone choose the horizon, bucket, threshold and features.
   - Every configuration tried is appended to `trials.jsonl`, with the frozen hash of its configuration.
   - Out-of-sample decisions are evaluated by the engine-constrained replay: the engine's IntradayRisk gate and sizing
     on the paper account. One position at a time where `max_open` is 1, trades per day, cooldown after losses, the
     daily loss limit, the premium-outlay cap, cash, and the entry window. A position blocks new entries until it
     exits. Decisions blocked by an open position are not counted as trades or abstentions.
5. Selection (real track only), pre-declared: the configuration with the highest 5% lower bound on expectancy R among
   those with at least `min_trades` replayed trades. Its frozen hash is recorded.
6. The locked final period (real track only): the newest `final_test_days` real sessions, set aside when the real
   track first has enough sessions. It is opened exactly once, for the selected configuration (refitted on the
   development sessions before it), and the opening is logged. Newer sessions are then held back until the next
   lock forms.
7. Approval: development gates + the locked test → a challenger in the plan registry, whose card states its
   evidence is real_point_in_time. The champion, the only thing allowed to steer directional entries, comes only
   from a forward record of real point-in-time sessions after the lock that passes the forward gates.

Nothing here changes a production setting (`intraday.expiry_min_days`, time stops, the horizon).
"""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.calendar import TradingCalendar
from ..core.types import Instrument
from ..execution.costs import CostModel as FeeModel
from ..intraday.chains import IntradayPricer
from ..intraday.risk import IntradayRisk
from ..risk.metrics import deflated_sharpe
from . import plans as P
from .evaluate import block_bootstrap
from .features import FEATURES, build_samples, validate_bars
from .policy import CANDIDATES, NEVER, PLAN_FEATURES, POLICY_VERSION, PlanPolicy
from .registry import PromotionRefused, Registry, code_fingerprint
from .store import ChainLog, read_json, sha, write_json
from .validation import WalkForwardConfig, folds, layout_hash, split

IST = "Asia/Kolkata"
TRACKS = {"real": P.QUALIFYING, "scenario": "modelled", "eod": "real_eod_approximation"}
DEFAULTS = {
    "final_test_days": 8,
    "folds": 5,
    "min_train_days": 15,
    "min_real_sessions": 28,                  # 15 training + 5 folds + 8 locked: below it the real track only describes
    "candidates": list(CANDIDATES),
    "horizons": list(P.HORIZONS),
    "buckets": [b for b, _, _ in P.DTE_BUCKETS],
    "bootstrap": {"samples": 1000, "block_days": 3, "seed": 7},
    "dev_gates": {"min_trades": 30, "min_trade_days": 10, "min_ci_lo_R": 0.0, "min_profit_factor": 1.10,
                  "min_dsr": 0.95, "min_positive_folds": 0.6},
    "lock_gates": {"min_trades": 8, "min_expectancy_R": 0.0, "min_net": 0.0},
    "forward_gates": {"min_sessions": 10, "min_trades": 15, "min_expectancy_R": 0.0, "min_profit_factor": 1.10},
}


def settings(cfg) -> dict:
    a = (cfg.get("autolearn.plan_research", {}) or {}) if cfg is not None else {}
    out = {**DEFAULTS, **{k: v for k, v in a.items() if k in DEFAULTS}}
    for k in ("bootstrap", "dev_gates", "lock_gates", "forward_gates"):
        out[k] = {**DEFAULTS[k], **(a.get(k) or {})}
    return out


def config_hash(track: str, horizon: str, bucket: str, name: str, rules: P.PlanRules, cost_v: str) -> str:
    """The frozen identity of one configuration: everything that decides its trades."""
    return sha({"track": track, "horizon": horizon, "bucket": bucket, "candidate": name, "spec": CANDIDATES[name],
                "features": PLAN_FEATURES, "rules": rules.to_dict(), "cost": cost_v, "policy": POLICY_VERSION,
                "code": code_fingerprint()})[:16]


def one_class(df: pd.DataFrame, evidence: str) -> pd.DataFrame:
    """Refuse to fit or evaluate on a frame that mixes evidence classes."""
    got = set(df["quote_source"].unique()) if len(df) else set()
    if got - {evidence}:
        raise ValueError(f"evidence classes must never be combined: {sorted(got)} in a {evidence} evaluation")
    return df


# ---- the rolling one-shot holdout (real track) ------------------------------------------------------------------------
class PlanLock:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "lock.json"
        self.log = ChainLog(self.root / "lock_access.jsonl")

    def state(self) -> dict:
        return read_json(self.path) or {"generations": []}

    def current(self, days: list[str], n: int, need: int, now) -> dict:
        """{lock: [days] | None, dev: [days], reserved: [days], generation, note}. Creates a lock when one is due."""
        st = self.state()
        gens = st["generations"]
        days = sorted(days)
        if not gens:
            if n <= 0 or len(days) < need:
                return {"lock": None, "dev": days, "reserved": [], "generation": None,
                        "note": f"no lock yet: {len(days)} real sessions, {need} needed"}
            g = {"generation": 1, "days": days[-n:], "created_at": str(now), "opened": None}
            gens.append(g)
            write_json(self.path, st)
            self.log.append({"event": "created", "generation": 1, "days": g["days"], "at": str(now)})
        last = gens[-1]
        if not last.get("opened"):
            lock = last["days"]
            return {"lock": lock, "dev": [d for d in days if d not in set(lock)], "reserved": [],
                    "generation": last["generation"], "note": f"lock {last['generation']} unopened: {lock[0]} → {lock[-1]}"}
        after = [d for d in days if d > last["days"][-1]]
        if len(after) >= n:
            g = {"generation": last["generation"] + 1, "days": after, "created_at": str(now), "opened": None}
            gens.append(g)
            write_json(self.path, st)
            self.log.append({"event": "created", "generation": g["generation"], "days": after, "at": str(now)})
            return {"lock": after, "dev": [d for d in days if d <= last["days"][-1]], "reserved": [],
                    "generation": g["generation"], "note": f"lock {g['generation']}: the sessions after lock {last['generation']}"}
        return {"lock": None, "dev": [d for d in days if d <= last["days"][-1]], "reserved": after, "generation": None,
                "note": f"lock {last['generation']} was opened {last['opened']['at']}; the next forms after "
                        f"{n - len(after)} more real sessions (held back from development until then)"}

    def open(self, generation: int, config: str, cfg_hash: str, result: dict, now) -> None:
        st = self.state()
        for g in st["generations"]:
            if g["generation"] == generation:
                if g.get("opened"):
                    raise RuntimeError(f"lock {generation} was already opened for {g['opened']['config']}")
                g["opened"] = {"at": str(now), "config": config, "config_hash": cfg_hash, "result": result}
        write_json(self.path, st)
        self.log.append({"event": "opened", "generation": generation, "config": config, "config_hash": cfg_hash,
                         "at": str(now), "result": result})

    def opens(self) -> int:
        return sum(1 for r in self.log.read() if r.get("event") == "opened")


# ---- the engine-constrained replay ----------------------------------------------------------------------------------
class _PlanShim:
    """What IntradayRisk.size reads from a TradePlan, for a single long option."""

    def __init__(self, entry_px: float, lot: int, premium_stop: float, conviction: float):
        self.net_premium, self.premium_stop, self.conviction = entry_px * lot, premium_stop, conviction
        self.is_credit = False

    def planned_risk_per_lot(self) -> float:
        return self.net_premium * self.premium_stop

    def max_loss_per_lot(self) -> float:
        return self.net_premium


class _Open:
    def __init__(self, symbol, entry_cost, exit_ts, pnl):
        self.symbol, self.entry_cost, self.exit_ts, self.pnl = symbol, entry_cost, exit_ts, pnl


def replay(best: pd.DataFrame, cfg, rules: P.PlanRules, fees: FeeModel) -> tuple[pd.DataFrame, dict]:
    """Play a policy's decisions (one row per decision point: `trade`, and the chosen plan's 1-lot outcome) through the
    engine's IntradayRisk on the paper account, in time order across symbols. Returns (trades, counts). Equity for the
    gate is realised P&L with open positions at cost (the live engine marks them; a small difference)."""
    risk = IntradayRisk(cfg)
    capital = float(cfg.get("intraday.capital", 20000))
    equity = cash = capital
    opens: list[_Open] = []
    trades, counts = [], {"decision_points": 0, "free": 0, "abstained": 0, "blocked": {}, "unaffordable": 0}
    day = None
    for r in best.sort_values(["ts", "symbol"], kind="stable").itertuples(index=False):
        ts = pd.Timestamp(r.ts)
        for o in [o for o in opens if o.exit_ts <= ts]:
            opens.remove(o)
            equity += o.pnl
            cash += o.entry_cost + o.pnl
            risk.on_close(o.pnl, o.exit_ts)
        if r.day != day:
            for o in opens:                                      # square-off: nothing is held overnight
                equity += o.pnl
                cash += o.entry_cost + o.pnl
            opens, day = [], r.day
            risk.reset(day, equity)
        counts["decision_points"] += 1
        why = risk.gate(ts, equity, opens, r.symbol)
        if why:
            k = why[0].split(":")[0][:40]
            counts["blocked"][k] = counts["blocked"].get(k, 0) + 1
            continue
        counts["free"] += 1
        if not r.trade:
            counts["abstained"] += 1
            continue
        lots, _ = risk.size(_PlanShim(r.entry_px, int(r.lot), rules.premium_stop, rules.conviction), equity, cash)
        if lots < 1:
            counts["unaffordable"] += 1
            continue
        qty = lots * int(r.lot)
        inst = Instrument.option(r.symbol, pd.Timestamp(r.expiry).date(), float(r.plan_strike),
                                 "CE" if r.direction > 0 else "PE", int(r.lot))
        f = fees.fees(inst, qty, r.entry_px)[0] + fees.fees(inst, -qty, r.exit_px)[0]
        pnl = (r.exit_px - r.entry_px) * qty - f
        entry_cost = r.entry_px * qty
        risk_amt = rules.premium_stop * entry_cost
        opens.append(_Open(r.symbol, entry_cost, pd.Timestamp(r.exit_ts), pnl))
        cash -= entry_cost
        risk.trades_today += 1
        trades.append({"ts": ts, "day": r.day, "symbol": r.symbol, "direction": r.direction, "bucket": r.bucket,
                       "horizon": r.horizon, "lots": lots, "qty": qty, "entry_px": r.entry_px, "exit_px": r.exit_px,
                       "exit_ts": pd.Timestamp(r.exit_ts), "exit_reason": r.exit_reason, "premium": entry_cost, "fees": f,
                       "gross": (r.exit_px - r.entry_px) * qty, "net": pnl, "net_R": pnl / risk_amt if risk_amt > 0 else np.nan,
                       "score": getattr(r, "score", np.nan), "p_win": getattr(r, "p_win", np.nan),
                       "quote_source": r.quote_source, "hold_min": r.hold_min, "fold": getattr(r, "fold", None)})
    return pd.DataFrame(trades), counts


def _pf(net: np.ndarray) -> float | None:
    g, l_ = net[net > 0].sum(), -net[net < 0].sum()
    return float(g / l_) if l_ > 0 else (None if g == 0 else float("inf"))


def metrics(trades: pd.DataFrame, counts: dict, days: list[str], boot: dict) -> dict:
    n = len(trades)
    free = counts.get("free", 0)
    base = {"trades": n, "sessions": len(days), "decision_points": counts.get("decision_points", 0), "free_points": free,
            "abstention": round(counts.get("abstained", 0) / free, 4) if free else None,
            "unaffordable": counts.get("unaffordable", 0), "blocked": counts.get("blocked", {})}
    if n == 0:
        return {**base, "trade_days": 0, "net_total": 0.0, "expectancy": None, "expectancy_R": None, "p_win": None,
                "profit_factor": None, "ci_R": {"lo": None, "hi": None, "p_positive": None}}
    t = trades.sort_values("ts", kind="stable")
    net, R = t["net"].to_numpy(float), t["net_R"].to_numpy(float)
    cum = np.cumsum(net)
    k = max(1, int(math.ceil(0.05 * n)))
    kw = {"samples": int(boot.get("samples", 1000)), "block": int(boot.get("block_days", 3)), "seed": int(boot.get("seed", 7))}
    m = {**base, "trade_days": int(t["day"].nunique()), "net_total": float(net.sum()), "gross_total": float(t["gross"].sum()),
         "fees_total": float(t["fees"].sum()), "premium_mean": float(t["premium"].mean()),
         "expectancy": float(net.mean()), "expectancy_R": float(R.mean()), "median_R": float(np.median(R)),
         "p_win": float((net > 0).mean()), "profit_factor": _pf(net),
         "max_drawdown": float((cum - np.maximum.accumulate(np.r_[0.0, cum])[1:]).min()),
         "cvar5": float(np.sort(net)[:k].mean()), "hold_min_mean": float(t["hold_min"].mean()),
         "sharpe_per_trade": float(R.mean() / R.std()) if n > 1 and R.std() > 0 else None,
         "exit_reasons": {str(a): int(b) for a, b in t["exit_reason"].value_counts().items()},
         "by_side": {("call" if s > 0 else "put"): {"trades": int(len(g)), "expectancy_R": float(g["net_R"].mean())}
                     for s, g in t.groupby("direction")}}
    m["ci_R"] = block_bootstrap(t, sorted(days), lambda x: x["net_R"].mean(), **kw)
    return m


def calibration(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float | None:
    ok = np.isfinite(p)
    p, y = p[ok], y[ok]
    if len(p) < 30:
        return None
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    idx = np.clip(np.searchsorted(edges[1:-1], p, side="right"), 0, bins - 1)
    return float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).sum() for b in range(bins) if (idx == b).any()) / len(p))


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 30:
        return None
    return float(np.corrcoef(pd.Series(a[ok]).rank().to_numpy(), pd.Series(b[ok]).rank().to_numpy())[0, 1])


# ---- inputs ----------------------------------------------------------------------------------------------------------
def by_bar_end(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """OHLC indexed by when each bar was complete."""
    out = bars[["open", "high", "low", "close"]].astype(float).copy()
    out.index = pd.DatetimeIndex([P._ist(t) for t in out.index]) + pd.Timedelta(minutes=minutes)
    return out


def load_inputs(cfg, root: Path, say=print, offline: bool = True) -> dict:
    """Everything the study reads, from the runtime folder:
      - the cycle's 5-minute bar store (with INDIAVIX);
      - the desk's recorded 1-minute bars and chains (the chain archive and the recorder's day folders);
      - the warehouse bhavcopy;
      - the journal's option fills."""
    from ..data.archive import compact_day, day_dirs, load_archive
    from ..intraday.feeds import normalise_bars
    from .cycle import read_parquet, write_parquet
    rt = Path(cfg.runtime_dir)
    syms = list(cfg.get("autolearn.symbols") or ["NIFTY", "BANKNIFTY"])
    bars5 = {s: b for s in syms if (b := read_parquet(root / "bars5" / f"{s}.parquet")) is not None and len(b)}
    vix = read_parquet(root / "bars5" / "INDIAVIX.parquet")
    if (vix is None or vix.empty) and not offline:
        try:
            from ..intraday.feeds import YahooIntradayFeed
            vix = YahooIntradayFeed(cfg).history_bars("INDIAVIX", int(cfg.get("autolearn.history_days", 55)))
            write_parquet(vix, root / "bars5" / "INDIAVIX.parquet")
        except Exception as exc:                                    # VIX is only the scenario track's IV fallback
            say(f"  INDIAVIX: unavailable ({exc!s:.100})")
            vix = None
    bhav = None
    wh = rt / "warehouse"
    if wh.exists() and any(wh.glob("fo_bhav_*.parquet")):
        import pyarrow.parquet as pq
        parts = []
        for p in sorted(wh.glob("fo_bhav_*.parquet")):
            cols = [c for c in ("date", "symbol", "kind", "expiry", "strike", "open", "high", "low", "close", "underlying",
                                "contracts") if c in pq.read_schema(p).names]
            parts.append(pq.read_table(p, columns=cols, filters=[("symbol", "in", syms)]).to_pandas())
        bhav = pd.concat(parts, ignore_index=True) if parts else None
    rec, b1 = [], []
    arch = rt / "chains_archive"
    if arch.exists():
        r = load_archive(arch, "chains")
        if len(r):
            rec.append(r)
        b = load_archive(arch, "bars")
        if len(b):
            b1.append(b)
    data = rt / "intraday" / "data"
    if data.exists():
        for dd in day_dirs(data):
            try:
                c = compact_day(dd)
            except Exception as exc:                                # a damaged recording loses only itself
                say(f"  recorded {dd.name}: unreadable ({exc!s:.80})")
                continue
            if c.get("chains") is not None and len(c["chains"]):
                rec.append(c["chains"])
            if c.get("bars") is not None and len(c["bars"]):
                b1.append(c["bars"])
    recorded = pd.concat(rec, ignore_index=True).drop_duplicates(["ts", "underlying", "expiry", "strike"]) if rec else None
    bars1 = {}
    if b1:
        allb = pd.concat(b1, ignore_index=True).drop_duplicates(["symbol", "ts"])
        for s, g in allb.groupby("symbol"):
            if s in syms:
                bars1[s] = normalise_bars(g.set_index(pd.to_datetime(g["ts"]))[["open", "high", "low", "close", "volume"]])
    return {"bars5": bars5, "bars1": bars1, "vix5": None if vix is None or vix.empty else vix["close"], "bhav": bhav,
            "recorded": recorded, "fills": journal_fills(rt / "intraday" / "journal.db")}


def journal_fills(path: Path) -> pd.DataFrame | None:
    """The paper broker's option fills (price and the fees it charged) for the fee-model comparison."""
    if not Path(path).exists():
        return None
    import sqlite3
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            rows = db.execute("SELECT ts, symbol, qty, price, fees FROM fills").fetchall()
    except sqlite3.Error:
        return None
    out = []
    for ts, sym, qty, px, fee in rows:
        s = str(sym or "").upper()
        if s[-2:] not in ("CE", "PE") or not qty or not px:
            continue
        inst = Instrument.option("X", dt.date(2000, 1, 1), 1.0, s[-2:], 1)   # fees depend on segment and turnover only
        out.append({"ts": ts, "instrument": inst, "qty": int(qty), "price": float(px), "fees": float(fee or 0)})
    return pd.DataFrame(out)


# ---- the study ---------------------------------------------------------------------------------------------------------
class PlanStudy:
    def __init__(self, cfg, inputs: dict, root: Path | None = None, now: pd.Timestamp | None = None, say=print):
        from .cycle import root_of
        self.cfg = cfg
        self.root = Path(root) if root else root_of(cfg)
        self.dir = self.root / "plan"
        self.now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=IST)
        self.say = say or (lambda *a: None)
        self.inputs = inputs
        self.s = settings(cfg)
        self.cal = TradingCalendar(cfg.holidays())
        self.rules = P.PlanRules.from_cfg(cfg)
        self.fees = FeeModel(cfg)
        self.pricer = IntradayPricer(cfg.get("backtest.risk_free", 0.065), cfg.get("backtest.dividend_yield", 0.012))
        self.lock = PlanLock(self.dir)
        self.reg = Registry(self.dir)
        self.trials = ChainLog(self.dir / "trials.jsonl")
        self.spreads = P.SpreadTable.measure(inputs.get("recorded"), self.cal)
        self.cost_v = P.cost_model_version(cfg, self.spreads, self.rules)

    # ---- data ------------------------------------------------------------------------------------------------------
    def samples(self, quality: dict) -> pd.DataFrame:
        """Decision points with their features, from the 5-minute store, plus recorded 1-minute sessions the store lacks."""
        from ..intraday.quant import to_5m
        parts = []
        hol = set(self.cfg.holidays())
        for s in sorted(set(self.inputs["bars5"]) | set(self.inputs.get("bars1") or {})):
            b5 = self.inputs["bars5"].get(s)
            b1 = (self.inputs.get("bars1") or {}).get(s)
            if b1 is not None and len(b1):                        # recorded sessions the 5-minute store doesn't have
                c1, rep = validate_bars(b1, hol, freq_min=1)
                quality[f"{s} recorded 1m"] = {k: rep[k] for k in ("rows_in", "rows_out", "jump_days", "gaps", "conflicting_duplicates")}
                self.inputs["bars1"][s] = c1
                have = set(b5.index.date) if b5 is not None and len(b5) else set()
                extra = to_5m(c1[~pd.Index(c1.index.date).isin(have)]) if len(c1) else pd.DataFrame()
                if len(extra):
                    b5 = extra if b5 is None or b5.empty else pd.concat([b5, extra]).sort_index()
            if b5 is None or b5.empty:
                continue
            c5, rep = validate_bars(b5, hol, freq_min=5)
            quality[f"{s} 5m"] = {k: rep[k] for k in ("rows_in", "rows_out", "jump_days", "gaps", "conflicting_duplicates")}
            self.inputs.setdefault("_bars5_clean", {})[s] = c5
            parts.append(build_samples(c5, s, 0))
        if not parts:
            raise RuntimeError("no index bars: run `autolearn ingest` first")
        s = pd.concat(parts, ignore_index=True)
        bad = ~np.isfinite(s[FEATURES].to_numpy(float)).all(1)
        quality["decision_points_non_finite_features"] = int(bad.sum())
        s = s[~bad]
        t0, t1 = self.rules.t(self.rules.entry_from), self.rules.t(self.rules.entry_until)
        tod = pd.DatetimeIndex(s["ts"]).tz_convert(IST).time
        return s[(tod >= t0) & (tod <= t1)].reset_index(drop=True)

    def sims(self, mode: str) -> tuple[dict, dict]:
        """Simulators and paths per symbol: real (1-minute paths, recorded books) or modelled (5-minute paths)."""
        sims, paths = {}, {}
        for sym in self.inputs["bars5"]:
            spec = self.cfg.instrument_spec(sym)
            if mode == "real":
                b1 = (self.inputs.get("bars1") or {}).get(sym)
                book = P.RealBook(self.inputs.get("recorded"), sym)
                if b1 is None or b1.empty or not book.snaps:
                    continue
                paths[sym] = by_bar_end(b1, 1)
                sims[sym] = P.Simulator(sym, int(spec.get("lot_size", 1)), self.rules, self.fees, self.pricer, real=book)
            else:
                ivt = P.iv_table(self.inputs.get("bhav"), sym, self.pricer)
                mb = P.ModelBook(sym, spec, self.rules, ivt, self.inputs.get("vix5"), self.cal, self.pricer, self.spreads)
                paths[sym] = by_bar_end(self.inputs.get("_bars5_clean", {}).get(sym, self.inputs["bars5"][sym]), 5)
                sims[sym] = P.Simulator(sym, int(spec.get("lot_size", 1)), self.rules, self.fees, self.pricer, model=mb)
        return sims, paths

    def build(self, samples: pd.DataFrame, days: list[str], mode: str, skipped: dict, horizons=None, buckets=None) -> pd.DataFrame:
        sims, paths = self.sims(mode)
        dec = samples[samples["day"].isin(set(days))]
        hz = {h: P.HORIZONS[h] for h in (horizons or self.s["horizons"])}
        o = P.outcomes(dec, paths, sims, self.cal, mode, hz, buckets or self.s["buckets"], skipped=skipped)
        if o.empty:
            return o
        o["day"] = o["day"].astype(str)
        feats = samples[["ts", "symbol"] + FEATURES].copy()
        feats["ts"] = pd.DatetimeIndex(feats["ts"]).tz_convert(IST)
        o = o.merge(feats, on=["ts", "symbol"], how="left")
        o["dte"] = o["dte"].astype(float)
        return o

    # ---- development -------------------------------------------------------------------------------------------------
    def _wf(self, horizon: str) -> WalkForwardConfig:
        e = P.horizon_minutes(horizon)
        return WalkForwardConfig(folds=int(self.s["folds"]), min_train_days=int(self.s["min_train_days"]),
                                 embargo_min=e, horizon_min=e)

    def trial(self, rows: pd.DataFrame, horizon: str, bucket: str, name: str, layout: list[dict], evidence: str) -> dict:
        """One configuration through every development fold, then the engine-constrained replay of its out-of-sample
        decisions."""
        one_class(rows, evidence)
        wf = self._wf(horizon)
        emb = pd.Timedelta(minutes=wf.embargo_min)
        oos, fold_rec, all_days = [], [], []
        for f in layout:
            tr, te, info = split(rows, f, wf)
            all_days += list(f["test_days"])
            try:
                pol = PlanPolicy(name, CANDIDATES[name], horizon, bucket).fit(tr, emb)
            except ValueError as exc:
                fold_rec.append({"fold": f["fold"], "status": "not fitted", "why": str(exc)[:120], **info})
                continue
            te = te.dropna(subset=PLAN_FEATURES + ["net_R"])
            if te.empty:
                fold_rec.append({"fold": f["fold"], "status": "no test rows", **info})
                continue
            best = pol.decide(te)
            best["fold"] = f["fold"]
            fold_rec.append({"fold": f["fold"], "status": "ok", "tau": None if pol.tau == NEVER else pol.tau, **info})
            oos.append(best)
        days = sorted(set(all_days))
        if not oos:
            return {"status": "insufficient data", "folds": fold_rec, "sessions": len(days)}
        best = pd.concat(oos, ignore_index=True)
        trades, counts = replay(best, self.cfg, self.rules, self.fees)
        m = metrics(trades, counts, days, self.s["bootstrap"])
        fitted = [f for f in fold_rec if f["status"] == "ok"]
        if len(trades):
            by_fold = trades.groupby("fold")["net"].sum()
            m["positive_folds"] = round(sum(1 for f in fitted if by_fold.get(f["fold"], 0.0) > 0) / len(fitted), 3)
        else:
            m["positive_folds"] = 0.0
        m["folds_fitted"] = len(fitted)
        m["ev_rank_ic"] = _spearman(best["score"].to_numpy(float), best["net_R"].to_numpy(float))
        m["ece_p_win"] = calibration(best["p_win"].to_numpy(float), (best["net"] > 0).to_numpy(float))
        return {"status": "ok", "metrics": m, "folds": fold_rec, "_R": trades["net_R"].to_numpy(float) if len(trades) else np.array([])}

    def dev_gates(self, m: dict, dsr) -> dict:
        g = self.s["dev_gates"]
        ci = (m.get("ci_R") or {}).get("lo")
        return {"trades": m.get("trades", 0) >= g["min_trades"], "trade_days": m.get("trade_days", 0) >= g["min_trade_days"],
                "ci_lo_R": ci is not None and ci > g["min_ci_lo_R"],
                "profit_factor": (m.get("profit_factor") or 0) >= g["min_profit_factor"],
                "deflated_sharpe": dsr is not None and dsr == dsr and dsr >= g["min_dsr"],
                "positive_folds": (m.get("positive_folds") or 0) >= g["min_positive_folds"]}

    def develop(self, o: pd.DataFrame, track: str, study_id: str) -> tuple[list[dict], str | None]:
        """Every configuration of one track through the development folds. All are logged."""
        evidence = TRACKS[track]
        one_class(o, evidence)
        points = o.drop_duplicates(["ts", "symbol"])[["ts", "day", "symbol", "label_end"]]
        layout = folds(points, self._wf("30m"))
        if not layout:
            return [], None
        lay = layout_hash(layout, self._wf("30m"), sha({"days": sorted(points["day"].unique()), "cost": self.cost_v})[:16])
        trials, Rs = [], {}
        for h in self.s["horizons"]:
            for b in self.s["buckets"]:
                rows = o[(o["horizon"] == h) & (o["bucket"] == b)].dropna(subset=PLAN_FEATURES)
                for name in self.s["candidates"]:
                    cid = f"{h}|{b}|{name}"
                    r = self.trial(rows, h, b, name, layout, evidence) if len(rows) else {"status": "no plans", "folds": []}
                    Rs[cid] = r.pop("_R", np.array([]))
                    trials.append({"track": track, "evidence": evidence, "config": cid, "horizon": h, "bucket": b,
                                   "candidate": name, "config_hash": config_hash(track, h, b, name, self.rules, self.cost_v), **r})
        srs = [float(R.mean() / R.std()) for R in Rs.values() if len(R) > 2 and R.std() > 0]
        n_tr, sr_sd = len(srs), (float(np.std(srs, ddof=1)) if len(srs) > 1 else 0.0)
        for t in trials:
            R = Rs.get(t["config"], np.array([]))
            dsr = float(deflated_sharpe(pd.Series(R), max(n_tr, 1), sr_sd)) if len(R) >= 10 else None
            if t["status"] == "ok":
                t["metrics"]["dsr"] = dsr
                t["gates"] = self.dev_gates(t["metrics"], dsr)
                t["passed"] = all(t["gates"].values()) and track == "real"     # nothing modelled ever passes
            else:
                t["gates"], t["passed"] = {}, False
            self.trials.append({"study": study_id, "at": str(self.now), "track": track, "evidence": evidence,
                                "config": t["config"], "config_hash": t["config_hash"], "status": t["status"],
                                "passed": t["passed"], "metrics": _brief(t.get("metrics")), "gates": t["gates"],
                                "layout": lay, "cost_model": self.cost_v, "policy_version": POLICY_VERSION})
        return trials, lay

    # ---- descriptive DTE × horizon -------------------------------------------------------------------------------------
    def describe(self, o: pd.DataFrame) -> list[dict]:
        """Unconditional: buy every call (or every put), per bucket and horizon. All plans as a distribution, and the
        engine-constrained replay of buying at every decision point."""
        out = []
        boot = self.s["bootstrap"]
        for (b, h, d), g in o.groupby(["bucket", "horizon", "direction"]):
            prem = g["premium"].to_numpy(float)
            tr, counts = replay(g.assign(trade=True, score=0.0, p_win=np.nan), self.cfg, self.rules, self.fees)
            k = max(1, int(math.ceil(0.05 * len(g))))
            out.append({"bucket": b, "horizon": h, "side": "call" if d > 0 else "put", "plans": int(len(g)),
                        "sessions": int(g["day"].nunique()), "mean_net_R": float(g["net_R"].mean()), "mean_net": float(g["net"].mean()),
                        "p_win": float((g["net"] > 0).mean()), "mean_gross": float(g["gross"].mean()), "mean_fees": float(g["fees"].mean()),
                        "mean_spread": float(g["spread_cost"].mean()), "mean_premium": float(prem.mean()),
                        "cost_share_of_premium": float(((g["fees"] + g["spread_cost"]) / prem).mean()),
                        "cvar5": float(np.sort(g["net"].to_numpy(float))[:k].mean()), "mae_mean": float(g["mae"].mean()),
                        "mfe_mean": float(g["mfe"].mean()), "intrabar_stops": int(g["intrabar_stop"].sum()),
                        "exit_reasons": {str(x): int(v) for x, v in g["exit_reason"].value_counts().items()},
                        "replay": {"trades": int(len(tr)), "unaffordable": counts["unaffordable"],
                                   "expectancy_R": float(tr["net_R"].mean()) if len(tr) else None,
                                   "net_total": float(tr["net"].sum()) if len(tr) else 0.0,
                                   "ci_R": block_bootstrap(tr, sorted(g["day"].unique()), lambda x: x["net_R"].mean(),
                                                           samples=int(boot["samples"]), block=int(boot["block_days"]),
                                                           seed=int(boot["seed"])) if len(tr) else None}})
        return out

    def describe_eod(self, e: pd.DataFrame) -> list[dict]:
        out = []
        boot = self.s["bootstrap"]
        for (sym, b, d), g in e.groupby(["symbol", "bucket", "direction"]):
            ci = block_bootstrap(g, sorted(g["day"].unique()), lambda x: x["net_R"].mean(), samples=int(boot["samples"]),
                                 block=int(boot["block_days"]), seed=int(boot["seed"]))
            out.append({"symbol": sym, "bucket": b, "side": "call" if d > 0 else "put", "plans": int(len(g)),
                        "sessions": int(g["day"].nunique()), "first_day": g["day"].min(), "last_day": g["day"].max(),
                        "mean_net_R": float(g["net_R"].mean()), "p_win": float(g["win"].mean()),
                        "mean_premium": float(g["premium"].mean()), "mean_fees": float(g["fees"].mean()),
                        "mean_spread": float(g["spread_cost"].mean()),
                        "cost_share_of_premium": float(((g["fees"] + g["spread_cost"]) / g["premium"]).mean()),
                        "stops": int((g["exit_reason"] == "premium_stop").sum()), "ci_R": ci})
        return out

    # ---- the run -----------------------------------------------------------------------------------------------------
    def run(self) -> dict:
        quality: dict = {}
        s = self.samples(quality)
        days = sorted(s["day"].unique())
        real_days = sorted({str(d) for sym in self.inputs["bars5"] for d in P.RealBook(self.inputs.get("recorded"), sym).days()}
                           & set(days))
        study_id = f"{self.now.date()}-{sha({'days': days, 'real': real_days, 'cfg': self.s, 'cost': self.cost_v})[:6]}"
        out_dir = self.dir / "studies" / study_id
        from .cycle import write_parquet

        # ---- real track: the only evidence that can qualify -----------------------------------------------------------
        sk_real: dict = {}
        o_real_all = self.build(s, real_days, "real", sk_real) if real_days else pd.DataFrame(columns=P.OUTCOME_COLUMNS)
        hybrid = o_real_all[o_real_all["quote_source"] != P.QUALIFYING] if len(o_real_all) else o_real_all
        if len(hybrid):
            sk_real["real_entry_but_modelled_marks_or_exit"] = int(len(hybrid))
        o_real = o_real_all[o_real_all["quote_source"] == P.QUALIFYING] if len(o_real_all) else o_real_all
        pit_days = sorted(o_real["day"].unique()) if len(o_real) else []
        lk = self.lock.current(pit_days, int(self.s["final_test_days"]), int(self.s["min_real_sessions"]), self.now)
        real = {"evidence": P.QUALIFYING, "sessions_with_recorded_chains": real_days, "pit_sessions": pit_days,
                "plan_outcomes": int(len(o_real)), "lock": lk, "exclusions": sk_real}
        if len(o_real):                                  # descriptive only on development sessions (never the lock)
            real["describe"] = self.describe(o_real[o_real["day"].isin(set(lk["dev"]))])
        if len(pit_days) < int(self.s["min_real_sessions"]):
            real["status"] = (f"insufficient real point-in-time data: {len(pit_days)} session(s) with complete real plans; the "
                              f"protocol needs {self.s['min_real_sessions']} ({self.s['min_train_days']} training + "
                              f"{self.s['folds']} folds + {self.s['final_test_days']} locked). Descriptive only; nothing fitted.")
            real["trials"], real["selected"], real["lockbox"], real["approved"] = [], None, {"opened": False, "why": real["status"]}, False
        else:
            o_dev = o_real[o_real["day"].isin(set(lk["dev"]))]
            trials, lay = self.develop(o_dev, "real", study_id)
            g = self.s["dev_gates"]
            elig = [t for t in trials if t["status"] == "ok" and t["metrics"]["trades"] >= g["min_trades"]
                    and (t["metrics"].get("ci_R") or {}).get("lo") is not None]
            sel = max(elig, key=lambda t: (t["metrics"]["ci_R"]["lo"], t["metrics"]["expectancy_R"])) if elig else None
            lockres = self._lockbox(s, o_real, sel, lk) if sel else {"opened": False, "why": f"no configuration had {g['min_trades']} trades"}
            approved = bool(sel and sel["passed"] and lockres.get("passed"))
            real.update({"status": "protocol run", "layout": lay, "trials": trials, "selected": sel["config"] if sel else None,
                         "selected_hash": sel["config_hash"] if sel else None, "selected_passed_dev": bool(sel and sel["passed"]),
                         "lockbox": lockres, "approved": approved,
                         "registered": self._register(o_real, sel, lk) if approved else None})
        real["forward"] = self.forward(o_real, pit_days)
        if len(o_real):                                  # on disk: the locked sessions only once they have been opened
            shown = set(lk["dev"]) | (set(lk["lock"] or []) if (real.get("lockbox") or {}).get("opened") else set())
            write_parquet(o_real[o_real["day"].isin(shown)], out_dir / "real_outcomes.parquet")

        # ---- scenario track: modelled chains, scenario analysis only -------------------------------------------------
        sk_scen: dict = {}
        held = set(lk["lock"] or []) | set(lk.get("reserved") or [])
        scen_days = [d for d in days if d not in held]
        o_scen = self.build(s, scen_days, "modelled", sk_scen)
        scen = {"evidence": "modelled", "label": P.SCENARIO, "sessions": len(scen_days),
                "period": [scen_days[0], scen_days[-1]] if scen_days else None, "plan_outcomes": int(len(o_scen)),
                "exclusions": sk_scen, "excluded_sessions_held_for_real_lock": sorted(held)}
        if len(o_scen):
            write_parquet(o_scen, out_dir / "scenario_outcomes.parquet")
            scen["iv_sources"] = {k: int(v) for k, v in o_scen.drop_duplicates(["ts", "symbol", "bucket", "direction"])["iv_source"].value_counts().items()}
            scen["describe"] = self.describe(o_scen)
            trials, lay = self.develop(o_scen, "scenario", study_id)
            scen.update({"layout": lay, "trials": trials})
            ok = [t for t in trials if t["status"] == "ok" and t["metrics"]["trades"] >= self.s["dev_gates"]["min_trades"]
                  and (t["metrics"].get("ci_R") or {}).get("lo") is not None]
            best = max(ok, key=lambda t: (t["metrics"]["ci_R"]["lo"], t["metrics"]["expectancy_R"])) if ok else None
            scen["best_by_the_selection_rule"] = best["config"] if best else None

        # ---- EOD approximation: real bhavcopy prices, not point in time ------------------------------------------------
        sk_eod: dict = {}
        eod_parts = [P.eod_outcomes(self.inputs.get("bhav"), sym, self.cfg.instrument_spec(sym), self.rules, self.fees, self.cal,
                                    self.pricer, sk_eod) for sym in self.inputs["bars5"]]
        o_eod = pd.concat([e for e in eod_parts if len(e)], ignore_index=True) if any(len(e) for e in eod_parts) else pd.DataFrame(columns=P.EOD_COLUMNS)
        eod = {"evidence": "real_eod_approximation", "label": "real prices, end of day: not point in time, cannot qualify",
               "plan_outcomes": int(len(o_eod)), "sessions": int(o_eod["day"].nunique()) if len(o_eod) else 0,
               "period": [o_eod["day"].min(), o_eod["day"].max()] if len(o_eod) else None, "exclusions": sk_eod,
               "describe": self.describe_eod(o_eod) if len(o_eod) else []}

        rep = {"study": study_id, "at": str(self.now),
               "data": {"first_day": days[0], "last_day": days[-1], "index_sessions": len(days),
                        "symbols": sorted(self.inputs["bars5"]), "bar_quality": quality,
                        "recorded_snapshots": int(self.inputs["recorded"]["ts"].nunique()) if self.inputs.get("recorded") is not None else 0,
                        "bhavcopy_rows": int(len(self.inputs["bhav"])) if self.inputs.get("bhav") is not None else 0},
               "costs": {"version": self.cost_v, "rules": self.rules.to_dict(), "spread_cells": self.spreads.cells,
                         "fills": P.fills_report(self.inputs.get("fills"), self.fees)},
               "protocol": {"settings": self.s, "policy_version": POLICY_VERSION, "code": code_fingerprint(),
                            "selection": f"highest 5% lower bound of expectancy R among configurations with ≥ "
                                         f"{self.s['dev_gates']['min_trades']} replayed trades (pre-declared; real track only)",
                            "lock_opens_total": self.lock.opens()},
               "real": real, "scenario": scen, "eod": eod,
               "production_change": self._recommend(real)}
        rep["replay_hash"] = sha({"real": [_brief(t.get("metrics")) for t in real.get("trials") or []],
                                  "scenario": [_brief(t.get("metrics")) for t in scen.get("trials") or []],
                                  "eod": eod["describe"], "sel": real.get("selected")})[:16]
        write_json(out_dir / "report.json", _jsonable(rep))
        (out_dir / "report.md").write_text(render(rep))
        write_json(self.dir / "latest.json", _jsonable({
            "study": study_id, "path": str(out_dir / "report.json"), "at": str(self.now),
            "real": {"status": real.get("status"), "pit_sessions": len(pit_days), "plan_outcomes": real["plan_outcomes"],
                     "approved": real.get("approved", False), "selected": real.get("selected"), "lock": lk["note"]},
            "scenario": {"label": P.SCENARIO, "sessions": scen["sessions"], "plan_outcomes": scen["plan_outcomes"],
                         "best_by_the_selection_rule": scen.get("best_by_the_selection_rule")},
            "eod": {"sessions": eod["sessions"], "plan_outcomes": eod["plan_outcomes"]},
            "champion": self.reg.state().get("champion")}))
        return rep

    def _lockbox(self, s, o_real, sel, lk) -> dict:
        if not lk["lock"]:
            return {"opened": False, "why": lk["note"]}
        h, b, name = sel["horizon"], sel["bucket"], sel["candidate"]
        if config_hash("real", h, b, name, self.rules, self.cost_v) != sel["config_hash"]:
            return {"opened": False, "why": "the configuration changed between selection and the locked test"}
        lock = lk["lock"]
        pre = o_real[(o_real["day"] < lock[0]) & (o_real["horizon"] == h) & (o_real["bucket"] == b)].dropna(subset=PLAN_FEATURES)
        try:
            pol = PlanPolicy(name, CANDIDATES[name], h, b).fit(one_class(pre, P.QUALIFYING),
                                                              pd.Timedelta(minutes=self._wf(h).embargo_min))
        except ValueError as exc:
            return {"opened": False, "why": f"refit before the lock failed: {exc}"}
        ol = o_real[o_real["day"].isin(set(lock)) & (o_real["horizon"] == h) & (o_real["bucket"] == b)].dropna(subset=PLAN_FEATURES)
        best = pol.decide(one_class(ol, P.QUALIFYING)) if len(ol) else pd.DataFrame()
        tr, counts = replay(best, self.cfg, self.rules, self.fees) if len(best) else (pd.DataFrame(), {})
        m = metrics(tr, counts, lock, self.s["bootstrap"])
        g = self.s["lock_gates"]
        checks = {"trades": m["trades"] >= g["min_trades"],
                  "expectancy_R": m.get("expectancy_R") is not None and m["expectancy_R"] > g["min_expectancy_R"],
                  "net": m["net_total"] > g["min_net"]}
        res = {"opened": True, "config": sel["config"], "config_hash": sel["config_hash"], "generation": lk["generation"],
               "sessions": lock, "refit_on": [pre["day"].min(), pre["day"].max()], "tau": None if pol.tau == NEVER else pol.tau,
               "plan_outcomes": int(len(ol)), "metrics": m, "checks": checks, "passed": all(checks.values())}
        self.lock.open(lk["generation"], sel["config"], sel["config_hash"], {"passed": res["passed"], **_brief(m)}, self.now)
        return res

    def _register(self, o_real, sel, lk) -> dict:
        """Refit on every development session and the lock (real evidence only), then register a plan challenger."""
        h, b, name = sel["horizon"], sel["bucket"], sel["candidate"]
        use = sorted(set(lk["dev"]) | set(lk["lock"] or []))
        rows = o_real[o_real["day"].isin(set(use)) & (o_real["horizon"] == h) & (o_real["bucket"] == b)].dropna(subset=PLAN_FEATURES)
        pol = PlanPolicy(name, CANDIDATES[name], h, b).fit(one_class(rows, P.QUALIFYING), pd.Timedelta(minutes=self._wf(h).embargo_min))
        card = {"code_fingerprint": code_fingerprint(), "feature_version": "plan:" + POLICY_VERSION, "label_version": self.cost_v,
                "data_fingerprint": sha({"days": use})[:16], "evidence": P.QUALIFYING, "config_hash": sel["config_hash"],
                "training_window": {"first_day": use[0], "last_day": use[-1], "sessions": len(use)},
                "validation": {"dev": _brief(sel["metrics"]), "gates": sel["gates"], "passed": True},
                "horizon": h, "bucket": b, "family": "plan"}
        mid, new = self.reg.register(pol, card)
        return {"model_id": mid, "new": new}

    def forward(self, o_real: pd.DataFrame, pit_days: list[str]) -> dict:
        """Each plan challenger's record on real point-in-time sessions after its training window. Promotes one only when
        every forward gate passes and its card says real_point_in_time."""
        out = {}
        for mid in self.reg.state().get("challengers") or []:
            card = self.reg.card(mid) or {}
            if card.get("evidence") != P.QUALIFYING:
                self.reg.reject(mid, "plan challenger without real point-in-time evidence")
                out[mid] = {"rejected": "no real point-in-time evidence"}
                continue
            try:
                pol = self.reg.load(mid)
            except Exception as exc:
                out[mid] = {"error": str(exc)[:160]}
                continue
            after = [d for d in pit_days if d > (card.get("training_window") or {}).get("last_day", "9999")]
            rows = o_real[o_real["day"].isin(set(after)) & (o_real["horizon"] == pol.horizon) & (o_real["bucket"] == pol.bucket)] \
                .dropna(subset=PLAN_FEATURES) if after and len(o_real) else pd.DataFrame()
            best = pol.decide(one_class(rows, P.QUALIFYING)) if len(rows) else pd.DataFrame()
            tr, counts = replay(best, self.cfg, self.rules, self.fees) if len(best) else (pd.DataFrame(), {})
            m = metrics(tr, counts, after, self.s["bootstrap"])
            g = self.s["forward_gates"]
            checks = {"evidence_real_point_in_time": True, "sessions": len(after) >= g["min_sessions"],
                      "trades": m["trades"] >= g["min_trades"],
                      "expectancy_R": m.get("expectancy_R") is not None and m["expectancy_R"] > g["min_expectancy_R"],
                      "profit_factor": (m.get("profit_factor") or 0) >= g["min_profit_factor"]}
            self.reg.update_card(mid, paper={"forward": _brief(m), "checks": checks, "at": str(self.now)})
            out[mid] = {"sessions": len(after), "metrics": _brief(m), "checks": checks}
            if all(checks.values()):
                try:
                    self.reg.promote(mid, "real point-in-time forward record passed every gate", checks)
                    out[mid]["promoted"] = True
                except PromotionRefused as exc:
                    out[mid]["promoted"], out[mid]["refused"] = False, str(exc)[:160]
        return out

    def _recommend(self, real: dict) -> dict:
        cur = int(self.cfg.get("intraday.expiry_min_days", 1))
        if not real.get("approved"):
            return {"change": None, "expiry_min_days": cur,
                    "why": "no configuration has passed on real point-in-time evidence (development gates and the locked "
                           "test): no basis for a DTE or horizon change. Modelled and EOD results cannot supply one."}
        return {"change": None, "expiry_min_days": cur, "candidate": real["selected"],
                "why": f"{real['selected']} passed development and the locked test on real point-in-time data and is a "
                       "registered challenger; a production change waits for its forward record (promotion)"}


# ---- report helpers --------------------------------------------------------------------------------------------------
_BRIEF = ("trades", "trade_days", "sessions", "net_total", "expectancy", "expectancy_R", "p_win", "profit_factor",
          "max_drawdown", "cvar5", "abstention", "unaffordable", "dsr", "positive_folds", "ev_rank_ic", "ece_p_win", "fees_total")


def _brief(m: dict | None) -> dict:
    if not m:
        return {}
    out = {k: m.get(k) for k in _BRIEF if k in m}
    ci = m.get("ci_R") or {}
    out["ci_R_lo"], out["ci_R_hi"], out["p_R_positive"] = ci.get("lo"), ci.get("hi"), ci.get("p_positive")
    return out


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.floating):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.ndarray):
        return _jsonable(x.tolist())
    if isinstance(x, (pd.Timestamp, dt.date)):
        return str(x)
    return x


def _fmt(x, d=3):
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:+.{d}f}"


def _desc_table(rows: list[dict]) -> list[str]:
    L = ["| bucket | horizon | side | plans | sessions | mean net R | P(net>0) | cost / premium | replay trades | unaffordable | replay exp. R | 90% CI |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        rp = r["replay"]
        ci = rp.get("ci_R") or {}
        L.append(f"| {r['bucket']} | {r['horizon']} | {r['side']} | {r['plans']} | {r['sessions']} | {_fmt(r['mean_net_R'])} | "
                 f"{r['p_win']:.2f} | {r['cost_share_of_premium']:.1%} | {rp['trades']} | {rp['unaffordable']} | "
                 f"{_fmt(rp.get('expectancy_R'))} | {_fmt(ci.get('lo'))} … {_fmt(ci.get('hi'))} |")
    return L


def _trial_table(trials: list[dict]) -> list[str]:
    L = ["| config | hash | status | trades | days | exp. R | 90% CI R | P(win) | PF | net ₹ | DSR | abstain | unaffordable | passed |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in trials:
        m = t.get("metrics") or {}
        ci = m.get("ci_R") or {}
        pf = m.get("profit_factor")
        L.append(f"| {t['config']} | {t['config_hash'][:8]} | {t['status']} | {m.get('trades', '—')} | {m.get('trade_days', '—')} | "
                 f"{_fmt(m.get('expectancy_R'))} | {_fmt(ci.get('lo'))} … {_fmt(ci.get('hi'))} | {_fmt(m.get('p_win'), 2)} | "
                 f"{_fmt(pf, 2) if pf is not None else '—'} | {m.get('net_total', 0):,.0f} | {_fmt(m.get('dsr'), 2)} | "
                 f"{_fmt(m.get('abstention'), 2)} | {m.get('unaffordable', '—')} | {'yes' if t.get('passed') else 'no'} |")
    return L


def render(rep: dict) -> str:
    d, r, sc, e = rep["data"], rep["real"], rep["scenario"], rep["eod"]
    L = [f"# Plan-level research — {rep['study']}", "",
         f"Index data: {d['first_day']} → {d['last_day']}, {d['index_sessions']} sessions ({', '.join(d['symbols'])}). "
         f"Recorded chain snapshots: {d['recorded_snapshots']}. Bhavcopy rows: {d['bhavcopy_rows']:,}. Cost model {rep['costs']['version']}.",
         f"Fee model vs paper fills: {rep['costs']['fills']}.", "",
         "## 1. Real point-in-time results (the only qualifying evidence)", "",
         f"Sessions with recorded chains: {len(r['sessions_with_recorded_chains'])} {r['sessions_with_recorded_chains']}. "
         f"Sessions with complete real plans: {len(r['pit_sessions'])}. Completed real plan outcomes: {r['plan_outcomes']:,}.",
         f"Exclusions: {r['exclusions']}.", f"Status: {r.get('status')}", f"Lock: {r['lock']['note']}.", ""]
    if r.get("describe"):
        L += ["Descriptive (development sessions; not a result: too few sessions to mean anything):", ""] + _desc_table(r["describe"]) + [""]
    if r.get("trials"):
        L += [f"Every configuration tried ({len(r['trials'])}):", ""] + _trial_table(r["trials"]) + [""]
        L.append(f"Selected (pre-declared rule): {r.get('selected') or 'none'} {('#' + r['selected_hash'][:8]) if r.get('selected_hash') else ''}")
    lb = r.get("lockbox") or {}
    if lb.get("opened"):
        m = lb["metrics"]
        L.append(f"Locked final period, opened once ({lb['sessions'][0]} → {lb['sessions'][-1]}): {m['trades']} trades, expectancy "
                 f"{_fmt(m.get('expectancy_R'))} R, net ₹{m['net_total']:,.0f} → {'PASS' if lb['passed'] else 'FAIL'}.")
    else:
        L.append(f"Locked final period: not opened ({lb.get('why')}).")
    L += [f"Approved: {'yes' if r.get('approved') else 'no'}.", "",
          "## 2. Modelled scenario results — SCENARIO ANALYSIS ONLY", "",
          "Priced by the desk's model from bhavcopy IV / India VIX. Not evidence of an edge; never combined with real "
          "results; never used for promotion, a DTE change or the paper gate.", "",
          f"Sessions: {sc['sessions']} ({sc['period'][0] if sc['period'] else '—'} → {sc['period'][1] if sc['period'] else '—'}). "
          f"Completed modelled plan outcomes: {sc['plan_outcomes']:,}. IV sources: {sc.get('iv_sources')}. Exclusions: {sc['exclusions']}.", ""]
    if sc.get("describe"):
        L += _desc_table(sc["describe"]) + [""]
    if sc.get("trials"):
        L += [f"Every configuration tried ({len(sc['trials'])}), scenario analysis only:", ""] + _trial_table(sc["trials"]) + [""]
        L.append(f"Best by the selection rule (scenario analysis only, not selected for anything): {sc.get('best_by_the_selection_rule') or 'none'}")
    L += ["", "## 3. Real end-of-day approximation (bhavcopy open → close) — not point in time, cannot qualify", "",
          f"Sessions: {e['sessions']} ({e['period'][0] if e['period'] else '—'} → {e['period'][1] if e['period'] else '—'}). "
          f"Plan outcomes: {e['plan_outcomes']:,}. Exclusions: {e['exclusions']}.", ""]
    if e["describe"]:
        L += ["| symbol | bucket | side | plans | sessions | mean net R | P(net>0) | cost / premium | stops | 90% CI R |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for x in e["describe"]:
            ci = x["ci_R"] or {}
            L.append(f"| {x['symbol']} | {x['bucket']} | {x['side']} | {x['plans']} | {x['sessions']} | {_fmt(x['mean_net_R'])} | "
                     f"{x['p_win']:.2f} | {x['cost_share_of_premium']:.1%} | {x['stops']} | {_fmt(ci.get('lo'))} … {_fmt(ci.get('hi'))} |")
    L += ["", f"## Production change: none. {rep['production_change']['why']}", "", f"Replay hash: {rep['replay_hash']}."]
    return "\n".join(L) + "\n"
