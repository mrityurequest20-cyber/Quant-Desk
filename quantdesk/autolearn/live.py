"""The live desk's side of the learning loop.

At every completed 5-minute bar of each symbol, before anything about the next 30 minutes is knowable, the desk
writes one decision record to the ledger with the features it saw and the prediction of every registered model:
the champion (whose signal the desk uses), the challengers and the rollback target (shadows: recorded, never traded).
That is the paper evidence a challenger needs before it can be promoted.

Fail-closed: a champion on record whose artifact doesn't verify, or whose features don't match this code, sets
`fault`, and the engine takes no new entries. A drift alarm (drift.json, written by the cycle) makes the champion
abstain.

Directional entries (`plan_gate`): with `autolearn.require_approved_model` (the default), a directional option trade
needs the plan registry's champion (research.py), which is promoted only on real point-in-time evidence. That model
must cover the trade's DTE bucket and must give it an expected net R at or above its threshold, and above zero. The
trade then runs on the model's horizon as its time stop. Without such a champion no directional trade is taken. The
analyst's tilt, the narrative, LLM reads and the session-trained DirectionModel remain advisory: shown and
journalled, never the reason for a trade.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from ..intraday.quant import features_5m, to_5m
from .cycle import root_of
from .evaluate import CostModel
from .features import BAR, FEATURE_VERSION, FEATURES, HORIZON_BARS, fingerprint
from .ledger import LeakageError, Ledger
from .models import ArtifactError
from .plans import HORIZONS, QUALIFYING, PlanRules, dte_bucket
from .registry import Registry
from .store import read_json

IST = "Asia/Kolkata"


class LiveLearner:
    def __init__(self, cfg, root=None, source: str = "live"):
        self.cfg = cfg
        self.root = root or root_of(cfg)
        self.reg, self.ledger = Registry(self.root), Ledger(self.root)
        self.cost = CostModel.from_cfg(cfg)
        self.source = source
        self.gate_entries = bool(cfg.get("autolearn.gate_entries", True))
        self.models: dict[str, tuple[str, object]] = {}           # model_id → (role, pipeline)
        self.champion_id: str | None = None
        self.fault: str | None = None
        self.drift: dict = {}
        self.last: dict[str, dict] = {}                            # symbol → the champion's latest decision
        self.done: dict[str, pd.Timestamp] = {}
        self.errors: list[str] = []
        self.require_model = bool(cfg.get("autolearn.require_approved_model", True))
        self.plan_reg = Registry(self.root / "plan")
        self.plan: tuple[str, object] | None = None                # (model_id, PlanPolicy): the approved plan champion
        self.plan_rules = PlanRules.from_cfg(cfg)
        self.feats: dict[str, tuple[pd.Timestamp, dict]] = {}      # symbol → (decision time, features) of the last bar
        self.cal = None

    def start(self, day) -> None:
        """Load and verify every model the desk will predict with today."""
        self.models, self.fault, self.last, self.done = {}, None, {}, {}
        st = self.reg.state()
        mid, pipe, fault = self.reg.champion()
        self.champion_id = mid
        if fault:
            self.fault = fault
        elif pipe is not None:
            self.models[mid] = ("champion", pipe)
        for role, ids in (("rollback", [st.get("rollback_target")]), ("challenger", st.get("challengers") or [])):
            for m in ids:
                if not m or m in self.models:
                    continue
                try:
                    self.models[m] = (role, self.reg.load(m))
                except (ArtifactError, OSError, ValueError, KeyError) as exc:   # a bad shadow only loses its shadow
                    self.errors.append(f"{m}: {exc!s:.120}")
        d = read_json(self.root / "drift.json") or {}
        self.drift = d if d.get("model_id") == mid else {}
        self.plan, self.feats = None, {}
        pid, pol, pfault = self.plan_reg.champion()
        if pfault:
            self.fault = self.fault or pfault
        elif pid:
            card = self.plan_reg.card(pid) or {}
            if card.get("evidence") != QUALIFYING:                # fail closed: only real point-in-time evidence approves
                self.fault = self.fault or f"plan champion {pid} has no real point-in-time evidence on its card"
            else:
                self.plan = (pid, pol)
        if self.cal is None:
            from ..core.calendar import TradingCalendar
            self.cal = TradingCalendar(self.cfg.holidays())

    @property
    def active(self) -> bool:
        """A verified champion is steering (its signal gates entries)."""
        return self.champion_id is not None and self.fault is None and self.champion_id in self.models

    def on_bar(self, u: str, now: pd.Timestamp, bars: pd.DataFrame, day, prev_close: float, prev_sig: float) -> dict | None:
        """Record the decision for the last completed 5-minute bar of `u` (once per bar). Returns the champion's
        decision for that bar: {model_id, p, signal, abstained, tau, decision_id, reason}."""
        if not self.models and self.plan is None:
            return None
        today = bars[bars.index.date == day]
        n5 = len(today) // 5
        if n5 < 1:
            return None
        five = to_5m(today.iloc[:n5 * 5])
        ts = five.index[-1] + BAR                                  # the decision time: the last 5-minute bar's end
        if self.done.get(u) == ts:
            return self.last.get(u)
        if now < ts:                                               # never decide on a bar that hasn't finished
            return self.last.get(u)
        f = features_5m(five, prev_close, prev_sig)
        row = f.iloc[[-1]]
        if not np.isfinite(row[FEATURES].to_numpy(float)).all():
            return None
        self.feats[u] = (ts, {k: float(row[k].iloc[0]) for k in FEATURES})
        if not self.models:
            return None
        preds, champ = [], None
        for mid, (role, pipe) in self.models.items():
            try:
                p_raw = float(pipe.predict_raw(row)[0])
                p = float(pipe.predict(row)[0])
            except (ValueError, FloatingPointError) as exc:
                self.errors.append(f"{mid}: {exc!s:.80}")
                continue
            sig = int(pipe.signal(np.array([p]))[0])
            why = None
            if role == "champion" and self.drift.get("state") == "alarm":
                sig, why = 0, "drift alarm: " + "; ".join(self.drift.get("reasons") or [])
            elif sig == 0:
                why = f"|p − ½| {abs(p - 0.5):.3f} < τ {pipe.tau:.3f}"
            preds.append({"model_id": mid, "role": role, "p_raw": p_raw, "p": p, "confidence": abs(p - 0.5) * 2,
                          "signal": sig, "abstained": sig == 0, "tau": pipe.tau, "reason": why})
            if role == "champion":
                champ = preds[-1]
        if not preds:
            return None
        minute = (five.index[-1] - pd.Timestamp(day, tz=IST)) / pd.Timedelta(minutes=1) - 555
        rec = {"ts": ts, "symbol": u, "features": {k: float(row[k].iloc[0]) for k in FEATURES},
               "feature_version": FEATURE_VERSION, "models": preds, "data_fingerprint": fingerprint(five),
               "costs_assumed": self.cost.round_trip_bps(float(five["close"].iloc[-1]), u),
               "label_end": ts + HORIZON_BARS * BAR + self.cost.delay_bars * BAR, "minute": float(minute), "source": self.source}
        try:
            did = self.ledger.record_decision(rec, now=now)
        except LeakageError as exc:                                # too late to count: say so, don't trade on it
            self.errors.append(str(exc)[:160])
            return None
        self.done[u] = ts
        if champ is not None:
            from .store import sha
            champ = {**champ, "decision_id": sha(f"{did}|{champ['model_id']}")[:20] if did else None, "ts": str(ts)}
            self.last[u] = champ
        return champ

    def entry_filter(self, u: str, plans: list) -> tuple[list, str | None]:
        """With an active champion steering entries: only plans its non-abstaining signal agrees with."""
        if not (self.active and self.gate_entries):
            return plans, None
        d = self.last.get(u)
        if not d:
            return [], "standing aside: the champion model has no read for this bar yet"
        if d["signal"] == 0:
            return [], f"standing aside: the champion model abstains ({d.get('reason')})"
        keep = [p for p in plans if p.direction == d["signal"]]
        for p in keep:
            p.notes["autolearn"] = {"model_id": d["model_id"], "decision_id": d.get("decision_id"), "p": round(d["p"], 4),
                                    "signal": d["signal"]}
        if not keep:
            return [], f"standing aside: the champion model calls {'up' if d['signal'] > 0 else 'down'}, no setup agrees"
        return keep, None

    def plan_gate(self, u: str, plans: list, now: pd.Timestamp) -> tuple[list, str | None]:
        """Directional plans only with the approved plan champion's positive expected net R; non-directional plans pass
        through. Approved plans get the model's horizon as their time stop, its premium stop / target, and a
        `plan_model` note. Returns (plans that may trade, why the directional ones may not)."""
        if not self.require_model:
            return plans, None
        other = [p for p in plans if p.direction == 0]
        directional = [p for p in plans if p.direction != 0]
        if not directional:
            return plans, None
        if self.plan is None:
            return other, ("standing aside: no approved plan model. A directional option trade needs a model approved on "
                           "real point-in-time evidence for its horizon; the analyst's read, the narrative, LLM reads and "
                           "unvalidated models are advisory only")
        pid, pol = self.plan
        got = self.feats.get(u)
        if got is None or now - got[0] > pd.Timedelta(minutes=10):
            return other, "standing aside: the plan model has no read for this bar yet"
        feats = got[1]
        keep, why = [], []
        so = pd.Timestamp(dt.datetime.combine(now.date(), self.plan_rules.t(self.plan_rules.square_off)), tz=IST)
        for p in directional:
            if len(p.legs) != 1 or p.legs[0].ratio != 1:
                why.append(f"{p.setup}: the plan model covers single long options only ({p.structure})")
                continue
            n = self.cal.trading_days_between(now.date(), p.expiry)
            if dte_bucket(n) != pol.bucket:
                why.append(f"{p.setup}: expiry {p.expiry} is {n} trading days out; the plan model covers DTE {pol.bucket}")
                continue
            leg = p.legs[0]
            spread = 2 * (leg.price - leg.mid) / leg.mid if leg.mid > 0 else np.nan
            row = pd.DataFrame([{**feats, "plan_iv": leg.iv / 100, "plan_spread_pct": spread, "dte": float(n),
                                 "direction": p.direction}])
            try:
                ev, pw = float(pol.score(row)[0]), float(pol.p_win(row)[0])
            except (ValueError, KeyError) as exc:
                why.append(f"{p.setup}: plan model failed ({exc!s:.60})")
                continue
            floor = max(pol.tau, 0.0)
            if not (ev > 0 and ev >= floor):
                why.append(f"{p.setup}: plan model expects {ev:+.2f}R (P(net>0) {pw:.0%}), below {'∞' if floor == float('inf') else f'{floor:.2f}'}R")
                continue
            mins = HORIZONS[pol.horizon]
            p.time_stop_min = int(mins) if mins is not None else int((so - now).total_seconds() // 60) + 1
            p.premium_stop, p.premium_target = self.plan_rules.premium_stop, self.plan_rules.premium_target
            p.notes["plan_model"] = {"model_id": pid, "horizon": pol.horizon, "bucket": pol.bucket, "ev_R": round(ev, 4),
                                     "p_win": round(pw, 4), "tau": None if pol.tau == float("inf") else pol.tau,
                                     "evidence": QUALIFYING}
            keep.append(p)
        if not keep:
            return other, "standing aside: " + "; ".join(why[:3])
        return keep + other, None

    def resolve(self, bars_by_symbol: dict, now: pd.Timestamp) -> int:
        """Outcomes for today's decisions whose 30 minutes have passed (the cycle does the same; it's idempotent)."""
        b5 = {u: to_5m(b) for u, b in bars_by_symbol.items() if b is not None and len(b)}
        try:
            return self.ledger.resolve(b5, now, cost_bps=self.cost.round_trip_bps, delay_bars=self.cost.delay_bars)
        except Exception as exc:                                   # learning never costs a session
            self.errors.append(f"resolve: {exc!s:.120}")
            return 0

    def status(self) -> dict:
        st = self.reg.state()
        return {"champion": self.champion_id, "active": self.active, "fault": self.fault,
                "challengers": [m for m, (r, _) in self.models.items() if r == "challenger"],
                "rollback_target": st.get("rollback_target"), "drift": self.drift.get("state"),
                "drift_reasons": self.drift.get("reasons"), "gate_entries": self.gate_entries,
                "last": {u: {k: d.get(k) for k in ("ts", "p", "signal", "abstained", "reason")} for u, d in self.last.items()},
                "require_approved_model": self.require_model,
                "plan_champion": ({"model_id": self.plan[0], "horizon": self.plan[1].horizon, "bucket": self.plan[1].bucket}
                                  if self.plan else None),
                "plan_research": read_json(self.root / "plan" / "latest.json"),
                "errors": self.errors[-5:]}
