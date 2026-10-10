"""Cost simulation, metrics, confidence intervals and the pass/fail gates.

A signal is traded as one unit of the index future (the cleanest proxy for the direction a model calls; the desk
expresses it with options, whose extra decay the research's buyer's-edge table measures separately): entered
`delay_bars` after the decision, held 30 minutes, one position per symbol at a time (signals while a position is open
are skipped, as the desk's one-position-per-symbol rule does). Costs per round trip, in bps of notional, from the
config: brokerage per order, STT on the sell, exchange and SEBI fees, stamp duty on the buy, GST on brokerage + fees,
the half-spread crossed both ways, slippage both ways. Everything is reported in bps per trade and ₹ per lot.

Confidence intervals: a circular block bootstrap over sessions (blocks of consecutive days keep intraday and
day-to-day dependence), seeded, so the same inputs give the same interval.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .features import session_bucket


@dataclass
class CostModel:
    brokerage_per_order: float = 20.0      # ₹, flat
    stt_sell_bps: float = 5.0              # futures: 0.05% on the sell side (costs.segments.futures.stt_sell)
    exchange_bps: float = 0.173            # NSE futures transaction charge, each side
    sebi_per_crore: float = 10.0           # each side
    stamp_buy_bps: float = 0.2             # 0.002% on the buy
    gst: float = 0.18                      # on brokerage + exchange + SEBI
    half_spread_bps: float = 0.5           # crossed on entry and exit
    slippage_bps: float = 1.0              # per side, on top of the spread
    delay_bars: int = 0                    # 5-minute bars between the decision and the entry
    max_trades_per_symbol_day: int = 6     # the simulator takes at most this many per symbol per session
    lot: dict | None = None                # {symbol: lot size}

    @classmethod
    def from_cfg(cls, cfg) -> "CostModel":
        """STT, exchange fees and stamp duty come from the desk's own table (costs.segments.futures, fractions of
        turnover), so the learner and the desk charge the same statute; autolearn.costs may raise them, never lower them
        below the statute (a config edit can't quietly make registration easier)."""
        c = (cfg.get("autolearn.costs", {}) or {}) if cfg is not None else {}
        fut = (cfg.get("costs.segments.futures", {}) or {}) if cfg is not None else {}
        desk = {k: round(float(fut[s]) * 1e4, 6) for k, s in (("stt_sell_bps", "stt_sell"), ("exchange_bps", "exchange"),
                                                              ("stamp_buy_bps", "stamp_buy")) if s in fut}
        c = {**desk, **c}
        c.update({k: max(float(c[k]), v) for k, v in desk.items()})          # the statute is a floor
        lots = {}
        if cfg is not None:
            for s in (cfg.get("autolearn.symbols") or ["NIFTY", "BANKNIFTY"]):
                lots[s] = int(cfg.instrument_spec(s).get("lot_size", 1))
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in c.items() if k in known}, lot=lots or None)

    def round_trip_bps(self, price: float, symbol: str | None = None) -> float:
        lot = (self.lot or {}).get(symbol, 1) if symbol else 1
        notional = max(price * lot, 1.0)
        brokerage = 2 * self.brokerage_per_order / notional * 1e4
        fees = 2 * self.exchange_bps + 2 * self.sebi_per_crore / 1e7 * 1e4
        tax = self.stt_sell_bps + self.stamp_buy_bps
        gst = self.gst * (brokerage + fees)
        return float(brokerage + fees + tax + gst + 2 * self.half_spread_bps + 2 * self.slippage_bps)

    def to_dict(self) -> dict:
        return asdict(self)


def simulate(df: pd.DataFrame, p: np.ndarray, signal: np.ndarray, cost: CostModel, overlap: bool = False) -> pd.DataFrame:
    """Rows of `df` (samples with fwd_ret, entry_px, ts, label_end, symbol) → the trades taken: one per non-abstaining
    signal, skipping signals while that symbol's previous trade is still open (unless `overlap`)."""
    d = df.assign(p=p, signal=signal)
    d = d[(d["signal"] != 0) & d["fwd_ret"].notna()].sort_values(["symbol", "ts"], kind="stable")
    rows = []
    for sym, g in d.groupby("symbol", sort=True):
        free_at, count = None, {}
        for r in g.itertuples(index=False):
            if not overlap and free_at is not None and r.ts < free_at:
                continue
            if count.get(r.day, 0) >= cost.max_trades_per_symbol_day:
                continue
            count[r.day] = count.get(r.day, 0) + 1
            c = cost.round_trip_bps(float(r.entry_px), sym)
            gross = float(r.signal) * float(r.fwd_ret) * 1e4
            lot = (cost.lot or {}).get(sym, 1)
            rows.append({"symbol": sym, "ts": r.ts, "day": r.day, "signal": int(r.signal), "p": float(r.p),
                         "gross_bps": gross, "cost_bps": c, "net_bps": gross - c,
                         "net_inr_lot": (gross - c) / 1e4 * float(r.entry_px) * lot, "minute": r.minute,
                         "sig5": r.sig5, "day_ret": r.day_ret})
            free_at = r.label_end
    cols = ["symbol", "ts", "day", "signal", "p", "gross_bps", "cost_bps", "net_bps", "net_inr_lot", "minute", "sig5", "day_ret"]
    return pd.DataFrame(rows, columns=cols)


# ---- metrics ---------------------------------------------------------------------------------------------------------
def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error over equal-width probability bins."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    if not len(p):
        return float("nan")
    idx = np.minimum((p * bins).astype(int), bins - 1)
    err = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            err += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(err)


def ece_noise(p: np.ndarray, bins: int = 10) -> float:
    """The ECE a perfectly calibrated model shows from sampling noise alone with these predictions:
    Σ (n_b/N) · √(2/π) · √(p̄_b(1 − p̄_b)/n_b). Calibration is judged on the excess over this floor."""
    p = np.asarray(p, float)
    if not len(p):
        return float("nan")
    idx = np.minimum((p * bins).astype(int), bins - 1)
    out = 0.0
    for b in range(bins):
        m = idx == b
        n = int(m.sum())
        if n:
            pb = float(p[m].mean())
            out += n / len(p) * math.sqrt(2 / math.pi) * math.sqrt(max(pb * (1 - pb), 1e-9) / n)
    return float(out)


def auc(y, p) -> float:
    y = np.asarray(y, bool)
    n1, n0 = y.sum(), (~y).sum()
    if not n1 or not n0:
        return float("nan")
    r = pd.Series(np.asarray(p, float)).rank().to_numpy()
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def classification(y: np.ndarray, p: np.ndarray, signal: np.ndarray) -> dict:
    ok = np.isfinite(y)
    y, p, s = y[ok], p[ok], signal[ok]
    base = float(np.clip(y.mean(), 1e-3, 1 - 1e-3)) if len(y) else 0.5
    brier = float(np.mean((p - y) ** 2)) if len(y) else float("nan")
    brier_ref = float(np.mean((base - y) ** 2)) if len(y) else float("nan")
    up, dn = s > 0, s < 0
    out = {"rows": int(len(y)), "base_rate": base, "auc": auc(y, p), "brier": brier,
           "brier_skill": float(1 - brier / brier_ref) if brier_ref > 0 else float("nan"), "ece": ece(y, p),
           "ece_noise": ece_noise(p), "ece_excess": ece(y, p) - ece_noise(p) if len(y) else float("nan"),
           "coverage": float((s != 0).mean()) if len(s) else 0.0, "abstention_rate": float((s == 0).mean()) if len(s) else 1.0,
           "accuracy_traded": float(((s > 0) == (y > 0))[s != 0].mean()) if (s != 0).any() else float("nan"),
           "precision_up": float(y[up].mean()) if up.any() else float("nan"),
           "recall_up": float((up & (y > 0)).sum() / max((y > 0).sum(), 1)),
           "precision_down": float(1 - y[dn].mean()) if dn.any() else float("nan"),
           "recall_down": float((dn & (y < 1)).sum() / max((y < 1).sum(), 1))}
    return out


def trading(trades: pd.DataFrame, n_days: int) -> dict:
    x = trades["net_bps"].to_numpy(float) if len(trades) else np.array([])
    wins, losses = x[x > 0], x[x < 0]
    curve = np.cumsum(x) if len(x) else np.array([0.0])
    dd = float((curve - np.maximum.accumulate(np.r_[0.0, curve])[1:]).min()) if len(x) else 0.0
    daily = trades.groupby("day")["net_bps"].sum() if len(trades) else pd.Series(dtype=float)
    daily = daily.reindex(sorted(set(daily.index)), fill_value=0.0)
    days_all = max(n_days, len(daily), 1)
    dv = np.r_[daily.to_numpy(float), np.zeros(max(0, days_all - len(daily)))]
    sd, down = dv.std(ddof=1) if len(dv) > 1 else float("nan"), dv[dv < 0]
    mean_day = float(dv.mean()) if len(dv) else float("nan")
    return {"trades": int(len(x)), "trades_per_day": float(len(x) / days_all), "turnover_lots_per_day": float(2 * len(x) / days_all),
            "win_rate": float((x > 0).mean()) if len(x) else float("nan"),
            "expectancy_bps": float(x.mean()) if len(x) else float("nan"),
            "gross_expectancy_bps": float(trades["gross_bps"].mean()) if len(x) else float("nan"),
            "cost_bps_avg": float(trades["cost_bps"].mean()) if len(x) else float("nan"),
            "net_bps_total": float(x.sum()), "net_inr_per_lot_total": float(trades["net_inr_lot"].sum()) if len(x) else 0.0,
            "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else (math.inf if len(wins) else float("nan")),
            "max_drawdown_bps": dd, "daily_vol_bps": float(sd), "mean_daily_bps": mean_day,
            # how many average days of profit it takes to earn back the worst drawdown (inf when there's no profit)
            "drawdown_recovery_days": float(-dd / mean_day) if mean_day == mean_day and mean_day > 0 else math.inf,
            "sharpe": float(dv.mean() / sd * math.sqrt(252)) if sd and sd > 0 else float("nan"),
            "sortino": float(dv.mean() / down.std(ddof=1) * math.sqrt(252)) if len(down) > 1 and down.std(ddof=1) > 0 else float("nan")}


def breakdown(trades: pd.DataFrame) -> dict:
    """Net bps per trade and count by session bucket, volatility regime, trend/range regime and symbol."""
    if trades.empty:
        return {}
    t = trades.copy()
    t["session"] = session_bucket(t["minute"])
    q = np.nanquantile(t["sig5"], [1 / 3, 2 / 3]) if t["sig5"].notna().sum() >= 3 else [np.inf, np.inf]
    t["vol_regime"] = np.where(t["sig5"] <= q[0], "low vol", np.where(t["sig5"] <= q[1], "mid vol", "high vol"))
    t["market_regime"] = np.where(t["day_ret"] > 1.5, "trend up", np.where(t["day_ret"] < -1.5, "trend down", "range"))
    out = {}
    for col in ("session", "vol_regime", "market_regime", "symbol"):
        g = t.groupby(col)["net_bps"]
        out[col] = {str(k): {"trades": int(v.count()), "expectancy_bps": round(float(v.mean()), 3),
                             "win_rate": round(float((v > 0).mean()), 3)} for k, v in g}
    return out


def block_bootstrap(trades: pd.DataFrame, days: list[str], stat, samples: int = 1000, block: int = 3,
                    seed: int = 7) -> dict:
    """Circular block bootstrap over sessions: resample runs of `block` consecutive days (with their trades),
    recompute `stat(trades)`; 5% / 95% bounds and the share of resamples above zero."""
    days = sorted(days)
    if len(days) < 3 or trades.empty:
        return {"lo": None, "hi": None, "p_positive": None, "samples": 0}
    by_day = {d: g for d, g in trades.groupby("day")}
    rng = np.random.default_rng(seed)
    n, vals = len(days), []
    for _ in range(samples):
        starts = rng.integers(0, n, size=math.ceil(n / block))
        pick = [days[(s + i) % n] for s in starts for i in range(block)][:n]
        parts = [by_day[d] for d in pick if d in by_day]
        v = stat(pd.concat(parts)) if parts else float("nan")
        if v == v:
            vals.append(v)
    if not vals:
        return {"lo": None, "hi": None, "p_positive": None, "samples": 0}
    a = np.array(vals)
    return {"lo": float(np.quantile(a, 0.05)), "hi": float(np.quantile(a, 0.95)), "p_positive": float((a > 0).mean()),
            "samples": int(len(a))}


def evaluate(oos: pd.DataFrame, cost: CostModel, boot: dict | None = None) -> dict:
    """Everything about one candidate's out-of-sample predictions (oos: samples + p + signal columns)."""
    boot = boot or {}
    days = sorted(oos["day"].unique()) if len(oos) else []
    tr = simulate(oos, oos["p"].to_numpy(float), oos["signal"].to_numpy(int), cost)
    m = {"classification": classification(oos["y"].to_numpy(float), oos["p"].to_numpy(float), oos["signal"].to_numpy(int)),
         "trading": trading(tr, len(days)), "by": breakdown(tr), "days": len(days),
         "first_day": days[0] if days else None, "last_day": days[-1] if days else None}
    kw = {"samples": int(boot.get("samples", 1000)), "block": int(boot.get("block_days", 3)), "seed": int(boot.get("seed", 7))}
    m["ci"] = {"expectancy_bps": block_bootstrap(tr, days, lambda t: t["net_bps"].mean(), **kw),
               "net_bps_per_day": block_bootstrap(tr, days, lambda t: t["net_bps"].sum() / max(len(days), 1), **kw),
               "win_rate": block_bootstrap(tr, days, lambda t: (t["net_bps"] > 0).mean() - 0.5, **kw)}
    if m["ci"]["win_rate"]["lo"] is not None:                       # stored relative to ½ for p_positive; shift back
        for k in ("lo", "hi"):
            m["ci"]["win_rate"][k] += 0.5
    return m


def paired_edge(a: pd.DataFrame, b: pd.DataFrame, days: list[str], boot: dict | None = None) -> dict:
    """Challenger (a) vs champion (b) on the same sessions: daily net bps difference, bootstrapped."""
    boot = boot or {}
    da = a.groupby("day")["net_bps"].sum() if len(a) else pd.Series(dtype=float)
    db = b.groupby("day")["net_bps"].sum() if len(b) else pd.Series(dtype=float)
    diff = pd.DataFrame({"day": days, "net_bps": [float(da.get(d, 0.0)) - float(db.get(d, 0.0)) for d in days]})
    r = block_bootstrap(diff, days, lambda t: t["net_bps"].mean(), samples=int(boot.get("samples", 1000)),
                        block=int(boot.get("block_days", 3)), seed=int(boot.get("seed", 7)))
    return {"mean_daily_diff_bps": float(diff["net_bps"].mean()) if len(diff) else float("nan"), **r}


# ---- gates -----------------------------------------------------------------------------------------------------------
DEFAULT_GATES = {"min_days": 20, "min_rows": 600, "min_trades": 40, "max_ece": 0.03, "min_brier_skill": 0.0,
                 "min_expectancy_bps": 0.0, "min_p_positive": 0.80, "min_profit_factor": 1.05,
                 "max_drawdown_bps": 1500.0, "max_drawdown_days": 20.0, "max_trades_per_day": 12.0,
                 "min_p_beats_champion": 0.70}


def gates(m: dict, quality_ok: bool, g: dict | None = None, vs_champion: dict | None = None) -> tuple[bool, list[str], dict]:
    """Fail-closed pass/fail with every reason. A missing number fails its check."""
    g = {**DEFAULT_GATES, **(g or {})}
    c, t = m.get("classification") or {}, m.get("trading") or {}
    ci = ((m.get("ci") or {}).get("expectancy_bps")) or {}

    def ge(x, lo):
        return x is not None and x == x and x >= lo

    def le(x, hi):
        return x is not None and x == x and x <= hi
    checks = {
        "data_quality": bool(quality_ok),
        "sample_days": ge(m.get("days"), g["min_days"]),
        "sample_rows": ge(c.get("rows"), g["min_rows"]),
        "sample_trades": ge(t.get("trades"), g["min_trades"]),
        "calibration_ece": le(c.get("ece_excess", c.get("ece")), g["max_ece"]),   # beyond what sampling noise explains
        "calibration_brier_skill": ge(c.get("brier_skill"), g["min_brier_skill"]) and c["brier_skill"] > g["min_brier_skill"] - 1e-12,
        "cost_net_expectancy": ge(t.get("expectancy_bps"), g["min_expectancy_bps"]) and t["expectancy_bps"] > g["min_expectancy_bps"],
        "cost_ci_p_positive": ge(ci.get("p_positive"), g["min_p_positive"]),
        "cost_profit_factor": ge(t.get("profit_factor"), g["min_profit_factor"]),
        "risk_drawdown": ge(t.get("max_drawdown_bps"), -g["max_drawdown_bps"]) and le(t.get("drawdown_recovery_days"), g["max_drawdown_days"]),
        "risk_trade_frequency": le(t.get("trades_per_day"), g["max_trades_per_day"]),
    }
    if vs_champion is not None:
        checks["beats_champion"] = ge(vs_champion.get("p_positive"), g["min_p_beats_champion"])
    reasons = [f"failed {k}" for k, v in checks.items() if not v]
    return all(checks.values()), reasons, checks
