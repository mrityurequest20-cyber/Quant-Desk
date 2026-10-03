"""The live desk's side of the learning loop.

At every completed 5-minute bar of each symbol, before anything about the next 30 minutes is knowable, the desk
writes one decision record to the ledger with the features it saw and the prediction of every registered model:
the champion (whose signal the desk uses), the challengers and the rollback target (shadows: recorded, never traded).
That is the paper evidence a challenger needs before it can be promoted.

Fail-closed: a champion on record whose artifact doesn't verify, or whose features don't match this code, sets
`fault`, and the engine takes no new entries. A drift alarm (drift.json, written by the cycle) makes the champion
abstain. With no champion yet, the desk runs exactly as before (the session-trained DirectionModel and the EV gate).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..intraday.quant import features_5m, to_5m
from .cycle import root_of
from .evaluate import CostModel
from .features import BAR, FEATURE_VERSION, FEATURES, HORIZON_BARS, fingerprint
from .ledger import LeakageError, Ledger
from .models import ArtifactError
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

    @property
    def active(self) -> bool:
        """A verified champion is steering (its signal gates entries)."""
        return self.champion_id is not None and self.fault is None and self.champion_id in self.models

    def on_bar(self, u: str, now: pd.Timestamp, bars: pd.DataFrame, day, prev_close: float, prev_sig: float) -> dict | None:
        """Record the decision for the last completed 5-minute bar of `u` (once per bar). Returns the champion's
        decision for that bar: {model_id, p, signal, abstained, tau, decision_id, reason}."""
        if not self.models:
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
                "errors": self.errors[-5:]}
