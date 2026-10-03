"""Plan-level outcomes: what the desk's actual option trade would have made, not whether the index went up.

For a decision point (a completed 5-minute bar), a side (+1 long call, −1 long put) and an expiry in a days-to-expiry
bucket, this builds the plan the live engine would build and plays it out under the live engine's own rules:

  strike   the engine's StrikePicker.by_delta at `long_delta` (0.45: the setups' buyer leg; buyer-only mode)
  veto     no entry when the ATM call's quoted spread exceeds `intraday.risk.max_spread_pct` (the analyst's veto), or
           when the chosen strike has no two-sided quote (the engine's live-book check)
  entry    the ask plus `adverse_ticks` (IntradayBroker)
  exits    the engine's `_manage` order, evaluated at every bar close on mid marks:
             premium stop (gross ≤ −stop × premium) → premium target (gross ≥ target × premium) →
             breakeven (open P&L once beyond half the target, gross back to ≤ 0) →
             time exit (held ≥ the horizon's minutes and gross < 10% of premium) → square-off at 15:15
           The horizon is the plan's `time_stop_min` (30 / 60 / 120; "close" = none, held to the square-off). As in the
           engine, a winner past its time stop is held, so a horizon is not a fixed holding period.
  OHLC     A bar's adverse extreme (low for a call, high for a put) that reaches the stop counts as a stop, even if
           the close reached the target: stop first, always. A target counts only at an observed close. Intrabar
           ordering is never inferred.
  fills    at the next available bid, minus `adverse_ticks`. A stop touched inside a bar fills at the worse of the
           next available bid and the stop level: a gap through the stop costs the gap.
  fees     the desk's cost model per order (brokerage, STT on the sell, exchange, SEBI, GST, stamp)

Every outcome carries `quote_source`, its evidence class:

  real_point_in_time      Every price came from the desk's own recorded book (Kotak / NSE / Kite snapshots, never
                          the model-chain fallback):
                          - the entry was quoted at most `pit_max_age_min` before the decision;
                          - every mark used for an exit decision was calibrated on a real snapshot at most
                            `chain_stale_min` old;
                          - the exit filled at a real bid at most `pit_max_age_min` after the trigger.
  real_eod_approximation  Real bhavcopy prices, but end of day: entry at the contract's open, exit at its close,
                          stop by its daily low. The spread is modelled. Close horizon only.
  modelled                Anything else: a chain priced by the pricer from bhavcopy IV or India VIX, or a real
                          entry whose marks or exit had to be modelled. A plan that mixes real and modelled prices is
                          `modelled`.

Only `real_point_in_time` may support a claim, a DTE change, a promotion or paper-gate progress (research.py enforces
it). Modelled outcomes are scenario analysis only.

Causality:
- a snapshot prices only moments at or after its timestamp;
- bhavcopy IV and the listed expiries come only from sessions before the decision's day;
- VIX comes only from bars completed by the decision;
- spread estimates come only from snapshots on earlier sessions.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import inspect
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from ..core.types import Instrument
from ..intraday.chains import COLUMNS, IST, IntradayPricer, time_to_expiry
from ..intraday.playbook import StrikePicker
from ..options.pricing import bs_price, greeks, implied_vol_vec
from .store import sha

HORIZONS = {"30m": 30, "60m": 60, "120m": 120, "close": None}
DTE_BUCKETS = (("0", 0, 0), ("1", 1, 1), ("2", 2, 2), ("3-5", 3, 5), ("6+", 6, 10_000))
EVIDENCE = ("real_point_in_time", "real_eod_approximation", "modelled")
QUALIFYING = "real_point_in_time"
SCENARIO = "scenario analysis only"
BAR5 = pd.Timedelta(minutes=5)
REAL_BOOKS = ("kotak", "nse", "kite", "recorded")               # chain sources with a real bid / ask
MNY_BANDS = (0.005, 0.015, 0.03, 0.08)                          # |K/S − 1| bands for spread estimates


def dte_bucket(n: int) -> str:
    """Bucket of a trading-day DTE. The engine's `expiry_min_days` counts calendar days; for the "skip 0-DTE" rule
    (≥ 1) the two agree, since an expiry is always a trading day."""
    return next(lab for lab, lo, hi in DTE_BUCKETS if lo <= n <= hi)


def horizon_minutes(h: str) -> int:
    """The longest a horizon's plan can live (close: a whole session), for embargoes."""
    m = HORIZONS[h]
    return 375 if m is None else int(m)


def _ist(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_localize(IST) if t.tzinfo is None else t.tz_convert(IST)


@dataclass
class PlanRules:
    long_delta: float = 0.45
    premium_stop: float = 0.30
    premium_target: float = 0.60
    breakeven_frac: float = 0.5                 # engine: mfe > ½ × target × premium and gross ≤ 0 → out at breakeven
    progress_frac: float = 0.1                  # engine: the time stop exits only when gross < 10% of premium
    adverse_ticks: int = 1
    tick: float = 0.05
    half_spread_pct: float = 0.012
    min_half_spread: float = 0.10
    entry_from: str = "09:20"
    entry_until: str = "14:45"
    square_off: str = "15:15"
    max_spread_pct: float = 0.06
    chain_stale_min: float = 12.0
    pit_max_age_min: float = 2.0
    conviction: float = 0.5                     # the sizing scale input for model-driven plans (IntradayRisk.size)

    @classmethod
    def from_cfg(cls, cfg) -> "PlanRules":
        if cfg is None:
            return cls()
        p = cfg.get("autolearn.plans", {}) or {}
        r = cfg.get("intraday.risk", {}) or {}
        s = cfg.get("slippage", {}) or {}
        base = cls(adverse_ticks=int(cfg.get("intraday.adverse_ticks", 1)),
                   half_spread_pct=float(s.get("option_half_spread_pct", 0.012)),
                   min_half_spread=float(s.get("option_min_half_spread", 0.10)), tick=float(s.get("option_tick", 0.05)),
                   entry_from=str(r.get("no_entry_before", "09:20")), entry_until=str(r.get("no_entry_after", "14:45")),
                   square_off=str(r.get("square_off", "15:15")), max_spread_pct=float(r.get("max_spread_pct", 0.06)),
                   chain_stale_min=float(cfg.get("intraday.chain_stale_min", 12)))
        return cls(**{**asdict(base), **{k: v for k, v in p.items() if k in cls.__dataclass_fields__}})

    @staticmethod
    def t(s: str) -> dt.time:
        h, m = s.split(":")
        return dt.time(int(h), int(m))

    def to_dict(self) -> dict:
        return asdict(self)


# ---- measured spreads (causal) --------------------------------------------------------------------------------------
def _band(mny: float) -> int:
    return int(np.searchsorted(MNY_BANDS, abs(mny), side="left"))


class SpreadTable:
    """Half-spread as a fraction of mid, by (symbol, DTE bucket, moneyness band), measured from real recorded books.
    A modelled quote on day d uses the median of the observations from sessions before d when there are at least
    `min_obs` of them, and the config's flat % otherwise."""

    def __init__(self, min_obs: int = 30):
        self.min_obs = int(min_obs)
        self.obs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._cache: dict = {}

    @classmethod
    def measure(cls, recorded: pd.DataFrame | None, calendar, min_obs: int = 30) -> "SpreadTable":
        t = cls(min_obs)
        if recorded is None or recorded.empty:
            return t
        r = recorded[recorded["source"].astype(str).str.lower().isin(REAL_BOOKS)]
        if r.empty:
            return t
        acc: dict = {}
        days = pd.to_datetime(r["ts"]).dt.date.to_numpy()
        exps = pd.to_datetime(r["expiry"]).dt.date.to_numpy()
        mny = (r["strike"].to_numpy(float) / r["spot"].to_numpy(float)) - 1
        und = r["underlying"].astype(str).to_numpy()
        for side in ("ce", "pe"):
            b, a = r[f"{side}_bid"].to_numpy(float), r[f"{side}_ask"].to_numpy(float)
            m = (a + b) / 2
            for i in np.flatnonzero((b > 0) & (a >= b) & np.isfinite(b) & np.isfinite(a) & (m > 1.0)):
                n = calendar.trading_days_between(days[i], exps[i]) if calendar is not None else (exps[i] - days[i]).days
                acc.setdefault(f"{und[i]}|{dte_bucket(n)}|{_band(mny[i])}", []).append((days[i].toordinal(), (a[i] - b[i]) / 2 / m[i]))
        for k, v in acc.items():
            v = np.array(v)
            t.obs[k] = (v[:, 0].astype(int), v[:, 1])
        return t

    def pct(self, symbol: str, bucket: str, mny: float, default: float, day: dt.date | None) -> tuple[float, str]:
        key = f"{symbol}|{bucket}|{_band(mny)}"
        if (key, day) not in self._cache:
            o, val = self.obs.get(key), None
            if o is not None:
                m = o[0] < day.toordinal() if day is not None else np.ones(len(o[0]), bool)
                if m.sum() >= self.min_obs:
                    val = float(np.median(o[1][m]))
            self._cache[(key, day)] = val
        v = self._cache[(key, day)]
        return (v, "measured") if v is not None else (default, "config")

    @property
    def cells(self) -> dict:
        return {k: {"pct": float(np.median(v)), "n": int(len(v)), "sessions": int(len(set(d)))} for k, (d, v) in self.obs.items()}

    def version(self) -> str:
        return sha({"cells": self.cells, "min_obs": self.min_obs})[:10]


def cost_model_version(cfg, spreads: SpreadTable | None = None, rules: PlanRules | None = None) -> str:
    """Changes whenever the fee configuration, the fee code, the spread estimates or the fill rules change."""
    from ..execution import costs as C
    body = {"costs": (cfg.get("costs", {}) or {}) if cfg is not None else {},
            "slippage": (cfg.get("slippage", {}) or {}) if cfg is not None else {},
            "fee_code": hashlib.sha256(inspect.getsource(C.CostModel).encode()).hexdigest()[:12],
            "spreads": spreads.version() if spreads else None, "rules": rules.to_dict() if rules else None}
    return "c3-" + sha(body)[:10]


# ---- implied vol from the bhavcopy -----------------------------------------------------------------------------------
def iv_table(bhav: pd.DataFrame | None, symbol: str, pricer: IntradayPricer | None = None) -> pd.DataFrame:
    """(date, expiry) → ATM IV (decimal) and the index close, at that session's close, from the call and put settled at
    the strike nearest the index close (both must have traded). A decision on day d uses only rows dated before d."""
    cols = ["date", "expiry", "atm_iv", "spot"]
    if bhav is None or bhav.empty:
        return pd.DataFrame(columns=cols)
    pr = pricer or IntradayPricer()
    b = bhav[(bhav["symbol"] == symbol) & bhav["kind"].isin(["CE", "PE"]) & (bhav["close"] > 0) & (bhav["contracts"] > 0)]
    if b.empty:
        return pd.DataFrame(columns=cols)
    b = b.assign(date=pd.to_datetime(b["date"]).dt.date, expiry=pd.to_datetime(b["expiry"]).dt.date)
    rows = []
    for (day, exp), g in b.groupby(["date", "expiry"]):
        S = g["underlying"].dropna()
        if S.empty or exp < day:
            continue
        S = float(S.iloc[0])
        both = g.pivot_table(index="strike", columns="kind", values="close", aggfunc="last").dropna()
        if both.empty or not {"CE", "PE"} <= set(both.columns):
            continue
        K = float(both.index[np.argmin(np.abs(both.index.to_numpy(dtype=float) - S))])
        T = time_to_expiry(pd.Timestamp(dt.datetime.combine(day, dt.time(15, 30)), tz=IST), exp)
        if T <= 0:
            continue
        ivs = [implied_vol_vec([both.loc[K, side]], S, [K], T, pr.r, pr.q, side)[0] for side in ("CE", "PE")]
        ivs = [v for v in ivs if v == v and 0.02 < v < 2]
        if ivs:
            rows.append((day, exp, float(np.mean(ivs)), S))
    return pd.DataFrame(rows, columns=cols)


# ---- the real book ---------------------------------------------------------------------------------------------------
class RealBook:
    """The desk's recorded snapshots for one underlying (real books only), by expiry."""

    def __init__(self, recorded: pd.DataFrame | None, symbol: str):
        self.snaps: dict = {}
        self._days: dict = {}
        if recorded is None or recorded.empty:
            return
        rec = recorded[(recorded["underlying"] == symbol) & recorded["source"].astype(str).str.lower().isin(REAL_BOOKS)]
        tmp: dict = {}
        for (exp, t), g in rec.groupby([pd.to_datetime(rec["expiry"]).dt.date, pd.to_datetime(rec["ts"])]):
            ch = g.set_index(g["strike"].astype(float)).sort_index()
            ch = ch[[c for c in COLUMNS if c in ch.columns]].astype(float)
            ch.attrs.update({"spot": float(g["spot"].iloc[0]), "expiry": exp, "ts": _ist(t), "source": "recorded"})
            tmp.setdefault(exp, []).append((_ist(t), ch))
        self._days: dict = {}
        for exp, lst in tmp.items():
            lst.sort(key=lambda x: x[0])
            self.snaps[exp] = (np.array([t.value for t, _ in lst], dtype=np.int64), [g for _, g in lst])
            for t, _ in lst:
                self._days.setdefault(t.date(), set()).add(exp)

    def days(self) -> set:
        return set(self._days) if self.snaps else set()

    def expiries(self, day: dt.date) -> list[dt.date]:
        return sorted(self._days.get(day, ())) if self.snaps else []

    def at(self, expiry, t: pd.Timestamp, max_age_min: float):
        """The newest snapshot at or before t, if it is at most `max_age_min` old."""
        s = self.snaps.get(expiry)
        if s is None:
            return None
        v = pd.Timestamp(t).value
        i = int(np.searchsorted(s[0], v, side="right")) - 1
        if i < 0 or v - s[0][i] > max_age_min * 60e9:
            return None
        return s[1][i]

    def after(self, expiry, t: pd.Timestamp, max_wait_min: float):
        """The first snapshot at or after t, if it comes within `max_wait_min`."""
        s = self.snaps.get(expiry)
        if s is None:
            return None
        v = pd.Timestamp(t).value
        i = int(np.searchsorted(s[0], v, side="left"))
        if i >= len(s[0]) or s[0][i] - v > max_wait_min * 60e9:
            return None
        return s[1][i]


# ---- the modelled book -----------------------------------------------------------------------------------------------
class ModelBook:
    """A chain priced by the desk's pricer at the index level then. Scenario analysis only."""

    def __init__(self, symbol: str, spec: dict, rules: PlanRules, iv_tab: pd.DataFrame | None = None,
                 vix5: pd.Series | None = None, calendar=None, pricer: IntradayPricer | None = None,
                 spreads: SpreadTable | None = None):
        self.symbol, self.rules, self.cal = symbol, rules, calendar
        self.step = float(spec.get("strike_step", 50))
        self.iv_beta = float(spec.get("iv_beta", 1.0))
        self.weekly, self.weekday = bool(spec.get("weekly_expiry", True)), int(spec.get("expiry_weekday", 1))
        self.pricer = pricer or IntradayPricer()
        self.spreads = spreads or SpreadTable()
        iv = iv_tab if iv_tab is not None and len(iv_tab) else pd.DataFrame(columns=["date", "expiry", "atm_iv"])
        self._iv = {(d, e): float(v) for d, e, v in iv[["date", "expiry", "atm_iv"]].itertuples(index=False)}
        self._iv_dates = sorted({d for d, _ in self._iv})
        self.vix = None
        if vix5 is not None and len(vix5):
            v = vix5.dropna().copy()
            v.index = pd.DatetimeIndex([_ist(t) for t in v.index]) + BAR5      # by bar end: known from then on
            self.vix = v.sort_index()

    def expiries(self, day: dt.date) -> list[dt.date]:
        """Contracts listed on `day`: the previous session's bhavcopy expiries still live, else the calendar's."""
        i = int(np.searchsorted(self._iv_dates, day, side="left")) - 1
        if i >= 0:
            ex = sorted({e for (d, e) in self._iv if d == self._iv_dates[i] and e >= day})
            if ex:
                return ex
        return list(self.cal.expiries(day, 70, self.weekday, self.weekly)) if self.cal is not None else []

    def atm_iv(self, ts: pd.Timestamp, expiry: dt.date) -> tuple[float | None, str]:
        i = int(np.searchsorted(self._iv_dates, ts.date(), side="left"))
        for d in reversed(self._iv_dates[max(0, i - 3):i]):
            v = self._iv.get((d, expiry))
            if v:
                return v, "bhavcopy"
        if self.vix is not None:
            k = int(np.searchsorted(self.vix.index, ts, side="right")) - 1
            if k >= 0 and self.vix.iloc[k] > 0 and ts - self.vix.index[k] <= pd.Timedelta(days=4):
                return float(self.vix.iloc[k]) / 100 * self.iv_beta, "vix"
        return None, "none"

    def half(self, mid, bucket: str, mny, day):
        mid = np.asarray(mid, dtype=float)
        mny = np.broadcast_to(np.asarray(mny, dtype=float), mid.shape)
        pct = np.array([self.spreads.pct(self.symbol, bucket, float(x), self.rules.half_spread_pct, day)[0]
                        for x in mny.ravel()]).reshape(mid.shape)
        return np.maximum(self.rules.min_half_spread, pct * mid)

    def chain(self, ts: pd.Timestamp, S: float, expiry: dt.date, bucket: str) -> pd.DataFrame | None:
        atm, src = self.atm_iv(ts, expiry)
        if not atm:
            return None
        T = time_to_expiry(ts, expiry)
        if T <= 0:
            return None
        r, q, tick = self.pricer.r, self.pricer.q, self.rules.tick
        K = round(S / self.step) * self.step + self.step * np.arange(-12, 13)
        K = K[K > 0]
        F = S * np.exp((r - q) * T)
        iv = np.atleast_1d(np.asarray(self.pricer.skew.iv(atm, K, F, max(T, 1 / 365 / 24)), dtype=float))
        cols = {}
        for side in ("ce", "pe"):
            m = np.atleast_1d(np.asarray(bs_price(S, K, max(T, 1e-9), r, q, iv, side.upper()), dtype=float))
            h = self.half(m, bucket, K / S - 1, ts.date())
            cols.update({f"{side}_ltp": np.round(m / tick) * tick, f"{side}_bid": np.maximum(tick, np.round((m - h) / tick) * tick),
                         f"{side}_ask": np.round((m + h) / tick) * tick, f"{side}_iv": iv * 100,
                         f"{side}_oi": np.nan, f"{side}_doi": np.nan, f"{side}_vol": np.nan})
        ch = pd.DataFrame(cols, index=K.astype(float))[COLUMNS]
        ch.index.name = "strike"
        ch.attrs.update({"spot": S, "expiry": expiry, "ts": ts, "source": "model", "iv_source": src, "atm_iv": atm})
        return ch


# ---- the plan ---------------------------------------------------------------------------------------------------------
def atm_spread_pct(chain: pd.DataFrame) -> float | None:
    """The analyst's veto input: the ATM call's (ask − bid) / mid (chain_analytics)."""
    S = float(chain.attrs["spot"])
    ks = chain.index.to_numpy(float)
    row = chain.loc[float(ks[np.argmin(np.abs(ks - S))])]
    b, a = row.get("ce_bid"), row.get("ce_ask")
    if pd.notna(b) and pd.notna(a) and a >= b > 0:
        return float((a - b) / ((a + b) / 2))
    return None


def build_plan(picker: StrikePicker, chain: pd.DataFrame, direction: int, ts: pd.Timestamp, rules: PlanRules
               ) -> tuple[dict | None, str | None]:
    """(plan, None) or (None, why not): the engine's strike, entry and entry vetoes."""
    sp = atm_spread_pct(chain)
    if sp is not None and sp > rules.max_spread_pct:
        return None, "spread_veto"
    right = "CE" if direction > 0 else "PE"
    q = picker.by_delta(chain, right, rules.long_delta, ts)
    if q is None:
        return None, "no_strike"
    bid, ask = q.get("bid"), q.get("ask")
    if not (pd.notna(bid) and pd.notna(ask) and ask >= bid > 0):
        return None, "no_two_sided_quote"
    return {"right": right, "strike": float(q["strike"]), "bid": float(bid), "ask": float(ask), "mid": float(q["mid"]),
            "iv": float(q["iv"]) / 100, "delta": float(q["delta"]), "spread_pct": float((ask - bid) / q["mid"]),
            "entry_px": float(ask) + rules.adverse_ticks * rules.tick}, None


def exit_index(entry_px: float, qty: int, fee_in: float, mid_close: np.ndarray, mid_adv: np.ndarray,
               times: pd.DatetimeIndex, ts: pd.Timestamp, rules: PlanRules, time_stop_min, require_hit: bool = False):
    """The engine's `_manage` order at each bar close, with the bar's adverse extreme counting for the stop.
    Returns (bar index, reason, whether the stop was touched only inside the bar); None with `require_hit` when no rule
    fires within the bars given."""
    if not len(times):
        return None
    prem = entry_px * qty
    gross = (mid_close - entry_px) * qty
    g_adv = (mid_adv - entry_px) * qty
    mfe = np.maximum.accumulate(gross - fee_in)                   # Trade.update_excursions: open P&L after fees
    held = np.asarray((times - ts) / pd.Timedelta(minutes=1), dtype=float)
    so = rules.t(rules.square_off)
    stop_close = gross <= -prem * rules.premium_stop
    stop_any = stop_close | (g_adv <= -prem * rules.premium_stop)
    tgt = gross >= prem * rules.premium_target
    be = (mfe > rules.breakeven_frac * prem * rules.premium_target) & (gross <= 0)
    tim = (held >= time_stop_min) & (gross < rules.progress_frac * prem) if time_stop_min is not None else np.zeros(len(times), bool)
    sq = np.array([t.time() >= so for t in times])
    hit = np.flatnonzero(stop_any | tgt | be | tim | sq)
    if not len(hit):
        return None if require_hit else (len(times) - 1, "square_off", False)
    k = int(hit[0])
    if stop_any[k]:
        return k, "premium_stop", not bool(stop_close[k])
    if tgt[k]:
        return k, "premium_target", False
    if be[k]:
        return k, "breakeven_stop", False
    if tim[k]:
        return k, "time_exit", False
    return k, "square_off", False


class Simulator:
    """Plays plans out on one underlying's path, under the engine's rules. `real`: RealBook or None; `model`: ModelBook
    or None."""

    def __init__(self, symbol: str, lot: int, rules: PlanRules, fees, pricer: IntradayPricer,
                 real: RealBook | None = None, model: ModelBook | None = None):
        self.symbol, self.lot, self.rules, self.fees, self.pricer = symbol, int(lot), rules, fees, pricer
        self.real, self.model = real, model
        self.picker = StrikePicker(pricer)

    def _real_marks(self, plan, expiry, times, S_close, S_adv):
        """The engine's QuoteMarker on real snapshots: each bar re-priced at the IV the newest snapshot (within the stale
        limit) implies for the strike, with that snapshot's half-spread. `fresh` is False from the first bar without one."""
        K, right, side = plan["strike"], plan["right"], plan["right"].lower()
        n = len(times)
        mid_c, mid_a, half, fresh = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, bool)
        cache: dict = {}
        for i, t in enumerate(times):
            snap = self.real.at(expiry, t, self.rules.chain_stale_min)
            if snap is None or K not in snap.index:
                break                                             # the first stale bar ends real marking
            key = id(snap)
            if key not in cache:
                b, a = float(snap.at[K, f"{side}_bid"]), float(snap.at[K, f"{side}_ask"])
                iv = float("nan")
                if a >= b > 0:
                    T0 = time_to_expiry(snap.attrs["ts"], expiry)
                    iv = implied_vol_vec([(a + b) / 2], snap.attrs["spot"], [K], T0, self.pricer.r, self.pricer.q, right)[0]
                cache[key] = (iv, (a - b) / 2)
            iv, h = cache[key]
            if not (iv == iv and iv > 0):
                break
            T = max(time_to_expiry(t, expiry), 1e-9)
            mid_c[i] = float(bs_price(S_close[i], K, T, self.pricer.r, self.pricer.q, iv, right))
            mid_a[i] = float(bs_price(S_adv[i], K, T, self.pricer.r, self.pricer.q, iv, right))
            half[i], fresh[i] = h, True
        return mid_c, mid_a, half, fresh

    def _sticky_marks(self, plan, expiry, times, S_close, S_adv):
        """The engine's marker with no fresh real quote: the entry's own IV and half-spread (modelled)."""
        K, right = plan["strike"], plan["right"]
        T = np.array([max(time_to_expiry(t, expiry), 1e-9) for t in times])
        mid_c = np.atleast_1d(np.asarray(bs_price(S_close, K, T, self.pricer.r, self.pricer.q, plan["iv"], right), dtype=float))
        mid_a = np.atleast_1d(np.asarray(bs_price(S_adv, K, T, self.pricer.r, self.pricer.q, plan["iv"], right), dtype=float))
        return mid_c, mid_a, np.full(len(times), (plan["ask"] - plan["bid"]) / 2)

    def _model_marks(self, plan, expiry, times, S_close, S_adv, bucket):
        K, right = plan["strike"], plan["right"]
        T = np.array([max(time_to_expiry(t, expiry), 1e-9) for t in times])
        mid_c = np.atleast_1d(np.asarray(bs_price(S_close, K, T, self.pricer.r, self.pricer.q, plan["iv"], right), dtype=float))
        mid_a = np.atleast_1d(np.asarray(bs_price(S_adv, K, T, self.pricer.r, self.pricer.q, plan["iv"], right), dtype=float))
        half = self.model.half(mid_c, bucket, K / S_close - 1, times[0].date())
        return mid_c, mid_a, half

    def play(self, plan: dict, ts: pd.Timestamp, expiry: dt.date, path: pd.DataFrame, bucket: str, real_entry: bool,
             horizons=HORIZONS) -> dict[str, dict]:
        """Every horizon's outcome for one plan entered at `ts`. `path`: close / high / low by bar end, same session."""
        rules, tick, adv = self.rules, self.rules.tick, self.rules.adverse_ticks * self.rules.tick
        so = pd.Timestamp(dt.datetime.combine(ts.date(), rules.t(rules.square_off)), tz=IST)
        p = path[(path.index > ts) & (path.index <= so)]
        if p.empty:
            return {}
        times = p.index
        S_c = p["close"].to_numpy(float)
        S_a = (p["low"] if plan["right"] == "CE" else p["high"]).to_numpy(float)
        qty, entry = self.lot, plan["entry_px"]
        inst = Instrument.option(self.symbol, expiry, plan["strike"], plan["right"], self.lot)
        fee_in = self.fees.fees(inst, qty, entry)[0]
        j = 0                                                     # bars marked off fresh real quotes, from the entry
        if real_entry and self.real is not None:
            rc, ra, rh, fresh = self._real_marks(plan, expiry, times, S_c, S_a)
            j = len(times) if fresh.all() else int(np.argmin(fresh))
        if self.model is not None:
            mc, ma, mh = self._model_marks(plan, expiry, times, S_c, S_a, bucket)
        else:
            mc, ma, mh = self._sticky_marks(plan, expiry, times, S_c, S_a)
        out = {}
        for name, mins in horizons.items():
            # real only if an exit rule fired while every mark so far came from a fresh real quote
            res = exit_index(entry, qty, fee_in, rc[:j], ra[:j], times[:j], ts, rules, mins, require_hit=True) if j else None
            if res is not None:
                (k, why, intrabar), real = res, True
                mid_c, mid_a, half = rc, ra, rh
            else:
                (k, why, intrabar), real = exit_index(entry, qty, fee_in, mc, ma, times, ts, rules, mins), False
                mid_c, mid_a, half = mc, ma, mh
            ev, nxt = ("real_point_in_time" if real else "modelled"), None
            if real:
                snap = self.real.after(expiry, times[k], rules.pit_max_age_min)
                if snap is not None and plan["strike"] in snap.index:
                    b = float(snap.at[plan["strike"], f"{plan['right'].lower()}_bid"])
                    nxt = b if b > 0 else None
                if nxt is None:
                    ev = "modelled"                               # no real bid to exit at in time: not real evidence
            bid = nxt if nxt is not None else float(max(tick, mid_c[k] - half[k]))
            if intrabar:                                          # stopped inside the bar: never better than the stop
                bid = min(bid, entry * (1 - rules.premium_stop) - float(half[k]))
            x = float(max(tick, np.round((bid - adv) / tick) * tick))
            fee_out = self.fees.fees(inst, -qty, x)[0]
            gross = (x - entry) * qty
            net = gross - fee_in - fee_out
            risk = rules.premium_stop * entry * qty
            lo = (np.minimum(mid_c[: k + 1], mid_a[: k + 1]) - entry) * qty
            hi = (mid_c[: k + 1] - entry) * qty
            out[name] = {"quote_source": ev, "exit_ts": times[k], "exit_px": x, "exit_reason": why, "intrabar_stop": bool(intrabar),
                         "hold_min": float((times[k] - ts) / pd.Timedelta(minutes=1)), "gross": gross,
                         "fees": fee_in + fee_out, "spread_cost": (entry - plan["mid"]) * qty + max(0.0, float(mid_c[k]) - x) * qty,
                         "net": net, "net_R": net / risk if risk > 0 else float("nan"),
                         "mae": float(min(0.0, lo.min())), "mfe": float(max(0.0, hi.max()))}
        return out


OUTCOME_COLUMNS = ["ts", "symbol", "day", "dte", "dte_cal", "bucket", "expiry", "direction", "horizon", "quote_source",
                   "entry_quote", "iv_source", "spot", "lot", "premium", "entry_px", "plan_strike", "plan_bid", "plan_ask",
                   "plan_mid", "plan_iv", "plan_delta", "plan_spread_pct", "exit_ts", "exit_px", "exit_reason",
                   "intrabar_stop", "hold_min", "gross", "fees", "spread_cost", "net", "net_R", "mae", "mfe", "label_end", "win"]


def outcomes(decisions: pd.DataFrame, paths: dict, sims: dict, calendar, mode: str, horizons=HORIZONS,
             buckets=None, directions=(1, -1), skipped: dict | None = None) -> pd.DataFrame:
    """Plan outcomes for decision points (rows with ts, symbol) × DTE bucket (nearest expiry in it) × side × horizon.

    mode "real": only expiries with a real snapshot at most `pit_max_age_min` old at the decision. The evidence is
                 real_point_in_time where the whole plan stayed real, and modelled where it didn't (kept, labelled).
    mode "modelled": the model book for every listed expiry (scenario analysis only).
    `paths[symbol]` is the OHLC by bar end. `skipped` collects the data-quality exclusions by reason."""
    rows = []
    skipped = skipped if skipped is not None else {}
    want = set(buckets) if buckets else None
    dte_of: dict = {}

    def skip(why):
        skipped[why] = skipped.get(why, 0) + 1

    def dte(day, exp):
        if (day, exp) not in dte_of:
            dte_of[(day, exp)] = calendar.trading_days_between(day, exp) if calendar is not None else (exp - day).days
        return dte_of[(day, exp)]

    for sym, g in decisions.groupby("symbol"):
        sim, path = sims.get(sym), paths.get(sym)
        if sim is None or path is None or path.empty or (mode == "real" and sim.real is None) or (mode != "real" and sim.model is None):
            skip("no_path_or_quotes")
            continue
        rules = sim.rules
        t0, t1 = rules.t(rules.entry_from), rules.t(rules.entry_until)
        by_day = {d: f for d, f in path.groupby(path.index.date)}
        for ts in pd.DatetimeIndex([_ist(t) for t in g["ts"]]):
            if not (t0 <= ts.time() <= t1):
                continue
            day = ts.date()
            pday = by_day.get(day)
            if pday is None:
                skip("no_path_for_session")
                continue
            seen = pday[pday.index <= ts]
            if seen.empty:
                skip("no_bar_at_decision")
                continue
            S = float(seen["close"].iloc[-1])
            exps = sim.real.expiries(day) if mode == "real" else sim.model.expiries(day)
            done = set()
            for exp in exps:
                n = dte(day, exp)
                bucket = dte_bucket(n)
                if bucket in done or (want and bucket not in want):
                    continue
                done.add(bucket)
                if mode == "real":
                    ch = sim.real.at(exp, ts, rules.pit_max_age_min)
                    if ch is None:
                        skip("no_fresh_real_snapshot")
                        continue
                    iv_src = "recorded"
                else:
                    ch = sim.model.chain(ts, S, exp, bucket)
                    if ch is None:
                        skip("no_iv_source")
                        continue
                    iv_src = ch.attrs.get("iv_source")
                for d in directions:
                    plan, why = build_plan(sim.picker, ch, d, ts, rules)
                    if plan is None:
                        skip(why)
                        continue
                    res = sim.play(plan, ts, exp, pday, bucket, real_entry=(mode == "real"), horizons=horizons)
                    if not res:
                        skip("no_path_after_entry")
                        continue
                    base = {"ts": ts, "symbol": sym, "day": str(day), "dte": n, "dte_cal": (exp - day).days, "bucket": bucket,
                            "expiry": exp, "direction": d, "entry_quote": "recorded" if mode == "real" else "model",
                            "iv_source": iv_src, "spot": S, "lot": sim.lot, "premium": plan["entry_px"] * sim.lot,
                            "entry_px": plan["entry_px"], "plan_strike": plan["strike"], "plan_bid": plan["bid"],
                            "plan_ask": plan["ask"], "plan_mid": plan["mid"], "plan_iv": plan["iv"], "plan_delta": plan["delta"],
                            "plan_spread_pct": plan["spread_pct"]}
                    for hz, o in res.items():
                        rows.append({**base, "horizon": hz, **o, "label_end": o["exit_ts"], "win": float(o["net"] > 0)})
    return pd.DataFrame(rows, columns=OUTCOME_COLUMNS) if rows else pd.DataFrame(columns=OUTCOME_COLUMNS)


# ---- the end-of-day approximation (real bhavcopy prices) ------------------------------------------------------------
EOD_COLUMNS = ["day", "symbol", "dte", "bucket", "expiry", "direction", "horizon", "quote_source", "plan_strike", "entry_px",
               "exit_px", "exit_reason", "premium", "lot", "gross", "fees", "spread_cost", "net", "net_R", "win"]


def eod_outcomes(bhav: pd.DataFrame | None, symbol: str, spec: dict, rules: PlanRules, fees, calendar,
                 pricer: IntradayPricer, skipped: dict | None = None) -> pd.DataFrame:
    """Close-horizon plans from the bhavcopy. The strike is the one nearest `long_delta` by the previous session's ATM IV
    and index close, which are known before the open. Each plan is filled as follows:
      - entry at the contract's open, plus a modelled half-spread and the adverse ticks;
      - a stop when the daily low reaches the stop level. Pessimistic: it counts even if the high reached the
        target, and it fills at the worse of the stop level and the close;
      - otherwise the exit is at the close, less the half-spread and the ticks.
    Real prices, but not point in time: never evidence for a claim."""
    skipped = skipped if skipped is not None else {}
    if bhav is None or bhav.empty or not {"high", "low", "open"} <= set(bhav.columns):
        return pd.DataFrame(columns=EOD_COLUMNS)
    ivt = iv_table(bhav, symbol, pricer)
    if ivt.empty:
        return pd.DataFrame(columns=EOD_COLUMNS)
    b = bhav[(bhav["symbol"] == symbol) & bhav["kind"].isin(["CE", "PE"])].copy()
    b["date"], b["expiry"] = pd.to_datetime(b["date"]).dt.date, pd.to_datetime(b["expiry"]).dt.date
    key = {(r.date, r.expiry, float(r.strike), r.kind): r for r in b.itertuples(index=False)}
    days = sorted(b["date"].unique())
    lot, step = int(spec.get("lot_size", 1)), float(spec.get("strike_step", 50))
    tick, adv = rules.tick, rules.adverse_ticks * rules.tick
    prev = {d: g for d, g in ivt.groupby("date")}
    rows = []
    for i, day in enumerate(days[1:], 1):
        p = prev.get(days[i - 1])
        if p is None:
            skipped["eod_no_prior_iv"] = skipped.get("eod_no_prior_iv", 0) + 1
            continue
        done = set()
        for r in p.sort_values("expiry").itertuples(index=False):
            if r.expiry < day:
                continue
            n = calendar.trading_days_between(day, r.expiry)
            bucket = dte_bucket(n)
            if bucket in done:
                continue
            done.add(bucket)
            S0 = float(r.spot)
            T = time_to_expiry(pd.Timestamp(dt.datetime.combine(day, dt.time(9, 15)), tz=IST), r.expiry)
            K = round(S0 / step) * step + step * np.arange(-12, 13)
            F = S0 * np.exp((pricer.r - pricer.q) * T)
            iv = np.atleast_1d(np.asarray(pricer.skew.iv(r.atm_iv, K, F, max(T, 1 / 365 / 24)), dtype=float))
            for d in (1, -1):
                right = "CE" if d > 0 else "PE"
                dl = np.atleast_1d(np.asarray(greeks(S0, K, max(T, 1e-6), pricer.r, pricer.q, iv, right)["delta"], dtype=float))
                Kp = float(K[int(np.argmin(np.abs(np.abs(dl) - rules.long_delta)))])
                c = key.get((day, r.expiry, Kp, right))
                if c is None or not (c.open > 0 and c.contracts > 0):
                    skipped["eod_untraded_strike"] = skipped.get("eod_untraded_strike", 0) + 1
                    continue
                h_in = max(rules.min_half_spread, rules.half_spread_pct * c.open)
                entry = float(np.round((c.open + h_in) / tick) * tick) + adv
                stop_mid = entry * (1 - rules.premium_stop)
                if c.low <= stop_mid:
                    why, xm = "premium_stop", min(stop_mid, float(c.close))
                else:
                    why, xm = "square_off", float(c.close)
                h_out = max(rules.min_half_spread, rules.half_spread_pct * xm)
                x = float(max(tick, np.round((xm - h_out - adv) / tick) * tick))
                inst = Instrument.option(symbol, r.expiry, Kp, right, lot)
                f = fees.fees(inst, lot, entry)[0] + fees.fees(inst, -lot, x)[0]
                gross = (x - entry) * lot
                net = gross - f
                risk = rules.premium_stop * entry * lot
                rows.append({"day": str(day), "symbol": symbol, "dte": n, "bucket": bucket, "expiry": r.expiry, "direction": d,
                             "horizon": "close", "quote_source": "real_eod_approximation", "plan_strike": Kp, "entry_px": entry,
                             "exit_px": x, "exit_reason": why, "premium": entry * lot, "lot": lot, "gross": gross, "fees": f,
                             "spread_cost": (h_in + h_out + 2 * adv) * lot, "net": net, "net_R": net / risk, "win": float(net > 0)})
    return pd.DataFrame(rows, columns=EOD_COLUMNS)


# ---- the cost model against the desk's paper fills ------------------------------------------------------------------
def fills_report(fills: pd.DataFrame | None, costs) -> dict:
    """The fee model against what the paper broker actually charged, per option order (model − charged)."""
    if fills is None or fills.empty:
        return {"fills": 0, "note": "no paper option fills yet: the cost model is unverified against fills"}
    err = np.array([costs.fees(r.instrument, int(r.qty), float(r.price))[0] - float(r.fees) for r in fills.itertuples(index=False)])
    return {"fills": int(len(fills)), "fee_bias": float(err.mean()), "fee_mae": float(np.abs(err).mean()),
            "fee_max_abs": float(np.abs(err).max())}
