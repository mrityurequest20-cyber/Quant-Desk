"""The immutable learning dataset: every prediction is written before its outcome can be known, and the outcome is
written later as a separate record. Neither is ever edited.

One `decision` record per symbol per completed 5-minute bar (`predictions-YYYY-MM.jsonl`):
  decision_id, ts (the decision time), symbol, timeframe "5m", horizon_min, session {bucket, minute}, features,
  feature_version, label_version, data_fingerprint (of the bars the features were computed from), costs_assumed
  (round-trip bps), recorded_at, source (live / replay / backfill), and `models`: every model that predicted at that
  bar, each {model_id, role (champion / challenger / baseline), p_raw, p, confidence, signal, abstained, tau,
  decision_id}.
One `outcome` record per decision (`outcomes-YYYY-MM.jsonl`): decision_id, entry/exit prices and times, fwd_ret, y,
resolved_at, label_end, and for each model its simulated net bps.

Leakage guards: a decision whose recorded_at is at or after its label_end is refused (unless source="backfill", which
never counts as paper evidence); an outcome is only computed from bars strictly after the decision time and only once
the label window has closed; a second record for the same decision_id is refused. Both files are hash-chained
(store.ChainLog). Retention drops whole closed months only, with a tombstone in the manifest.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from .features import BAR, FEATURE_VERSION, FEATURES, HORIZON_BARS, LABEL_VERSION, session_bucket
from .store import ChainLog, sha

IST = "Asia/Kolkata"
REQUIRED = ("ts", "symbol", "features", "models", "data_fingerprint", "costs_assumed", "label_end")


class LeakageError(ValueError):
    pass


def decision_id(symbol: str, ts, source: str) -> str:
    return sha(f"{symbol}|{pd.Timestamp(ts).isoformat()}|{source}")[:20]


class Ledger:
    def __init__(self, root: Path):
        self.root = Path(root) / "ledger"
        self.manifest = ChainLog(self.root / "manifest.jsonl")
        self._seen: dict[str, set] = {}

    def _month(self, kind: str, ts) -> Path:
        t = pd.Timestamp(ts)
        return self.root / f"{kind}-{t:%Y-%m}.jsonl"

    def _files(self, kind: str) -> list[Path]:
        return sorted(self.root.glob(f"{kind}-*.jsonl*")) if self.root.exists() else []

    def _ids(self, kind: str, path: Path) -> set:
        key = f"{kind}:{path.name}"
        if key not in self._seen:
            ids = set()
            for p in (path, path.with_suffix(path.suffix + ".gz")):
                if p.exists():
                    ids |= {r["decision_id"] for r in ChainLog(p).read()}
            self._seen[key] = ids
        return self._seen[key]

    # ---- writing --------------------------------------------------------------------------------------------------
    def record_decision(self, rec: dict, now: pd.Timestamp | None = None) -> str | None:
        """Append a decision; returns its decision_id, or None if that decision is already on the ledger."""
        missing = [k for k in REQUIRED if k not in rec]
        if missing:
            raise ValueError(f"decision record lacks {missing}")
        ts, end = pd.Timestamp(rec["ts"]), pd.Timestamp(rec["label_end"])
        source = rec.get("source", "live")
        recorded = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=IST)
        if source != "backfill" and recorded >= end:
            raise LeakageError(f"{rec['symbol']} {ts}: prediction recorded at {recorded}, after its outcome was knowable ({end})")
        if recorded < ts - pd.Timedelta(minutes=1):
            raise LeakageError(f"{rec['symbol']} {ts}: recorded at {recorded}, before its own decision time")
        feats = rec["features"]
        if sorted(feats) != sorted(FEATURES) or not all(np.isfinite(float(v)) for v in feats.values()):
            raise ValueError("decision features must be the full, finite feature vector")
        did = rec.get("decision_id") or decision_id(rec["symbol"], ts, source)
        path = self._month("predictions", ts)
        if did in self._ids("predictions", path):
            return None
        body = {"decision_id": did, "ts": ts.isoformat(), "symbol": rec["symbol"], "timeframe": "5m",
                "horizon_min": HORIZON_BARS * 5, "label_end": end.isoformat(),
                "session": {"bucket": str(session_bucket([rec.get("minute", 0)])[0]), "minute": float(rec.get("minute", 0))},
                "features": {k: float(feats[k]) for k in FEATURES}, "feature_version": rec.get("feature_version", FEATURE_VERSION),
                "label_version": LABEL_VERSION, "data_fingerprint": rec["data_fingerprint"],
                "costs_assumed": float(rec["costs_assumed"]), "recorded_at": recorded.isoformat(), "source": source,
                "models": [{**m, "decision_id": sha(f"{did}|{m['model_id']}")[:20]} for m in rec["models"]],
                "paper_trade_id": rec.get("paper_trade_id")}
        ChainLog(path).append(body)
        self._ids("predictions", path).add(did)
        return did

    def record_outcome(self, did: str, ts, out: dict, now: pd.Timestamp | None = None) -> bool:
        path = self._month("outcomes", ts)
        if did in self._ids("outcomes", path):
            return False
        resolved = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=IST)
        if resolved < pd.Timestamp(out["label_end"]):
            raise LeakageError(f"outcome for {did} resolved at {resolved}, before its label window closed")
        ChainLog(path).append({"decision_id": did, "ts": pd.Timestamp(ts).isoformat(), **out, "resolved_at": resolved.isoformat()})
        self._ids("outcomes", path).add(did)
        return True

    # ---- reading --------------------------------------------------------------------------------------------------
    def decisions(self, since=None) -> list[dict]:
        out = []
        for p in self._files("predictions"):
            if p.name.endswith((".corrupt", ".tmp")):
                continue
            out += ChainLog(p).read()
        if since is not None:
            s = pd.Timestamp(since)
            out = [r for r in out if pd.Timestamp(r["ts"]) >= s]
        return out

    def outcomes(self) -> dict[str, dict]:
        out = {}
        for p in self._files("outcomes"):
            if p.name.endswith((".corrupt", ".tmp")):
                continue
            for r in ChainLog(p).read():
                out[r["decision_id"]] = r
        return out

    def frame(self, model_id: str | None = None, role: str | None = None, source: str | None = "live") -> pd.DataFrame:
        """One row per (decision, model) with its outcome when resolved."""
        outs = self.outcomes()
        rows = []
        for r in self.decisions():
            if source and r.get("source") != source:
                continue
            o = outs.get(r["decision_id"]) or {}
            for m in r["models"]:
                if (model_id and m["model_id"] != model_id) or (role and m.get("role") != role):
                    continue
                rows.append({"decision_id": r["decision_id"], "ts": pd.Timestamp(r["ts"]), "symbol": r["symbol"],
                             "day": str(pd.Timestamp(r["ts"]).date()), "minute": r["session"]["minute"], "model_id": m["model_id"],
                             "role": m.get("role"), "p": m["p"], "signal": m["signal"], "abstained": m["abstained"],
                             "fwd_ret": o.get("fwd_ret"), "y": o.get("y"), "entry_px": o.get("entry_px"),
                             "net_bps": (o.get("net_bps") or {}).get(m["model_id"]),
                             "label_end": pd.Timestamp(r["label_end"]), "resolved": bool(o),
                             "sig5": o.get("sig5"), "day_ret": o.get("day_ret"),
                             **{f"f_{k}": v for k, v in r["features"].items()}})
        return pd.DataFrame(rows)

    def pending(self, until: pd.Timestamp) -> list[dict]:
        """Decisions whose label window has closed by `until` and that have no outcome yet."""
        outs = self.outcomes()
        return [r for r in self.decisions(since=None) if r["decision_id"] not in outs and pd.Timestamp(r["label_end"]) <= until]

    # ---- resolving ------------------------------------------------------------------------------------------------
    def resolve(self, bars5: dict[str, pd.DataFrame], now: pd.Timestamp, cost_bps=None, delay_bars: int = 0) -> int:
        """Write outcomes for every pending decision whose exit bar exists, from bars strictly after the decision."""
        n = 0
        for r in self.pending(now):
            b = bars5.get(r["symbol"])
            if b is None or b.empty:
                continue
            ts = pd.Timestamp(r["ts"])
            day = b[b.index.date == ts.date()]
            after = day[day.index >= ts]                          # bars that start at/after the decision: unknown at ts
            before = day[day.index + BAR <= ts]                   # bars complete by the decision
            if before.empty or len(after) < HORIZON_BARS + delay_bars:
                continue                                           # the session's bars aren't all there (yet): try later
            c0 = float(before["close"].iloc[-1])
            entry_px = c0 if delay_bars == 0 else float(after["close"].iloc[delay_bars - 1])
            exit_px = float(after["close"].iloc[HORIZON_BARS + delay_bars - 1])
            label_px = float(after["close"].iloc[HORIZON_BARS - 1])  # the existing label: close 30 minutes after ts
            fwd = float(np.log(exit_px / entry_px))
            lr = np.log(before["close"].astype(float)).diff().dropna()
            sig = float(lr.tail(12).std()) if len(lr) >= 4 else float("nan")
            sig_ = sig if sig == sig and sig > 0 else 8e-4
            out = {"entry_px": entry_px, "exit_px": exit_px, "exit_bar": str(after.index[HORIZON_BARS + delay_bars - 1]),
                   "fwd_ret": fwd, "y": float(label_px > c0), "label_end": r["label_end"],
                   "sig5": sig if sig == sig else None,
                   "day_ret": float(np.log(c0 / float(day["open"].iloc[0])) / (sig_ * np.sqrt(max(len(before), 1)))),
                   "net_bps": {m["model_id"]: (float(m["signal"]) * fwd * 1e4 - (cost_bps(entry_px, r["symbol"]) if cost_bps else
                                                                                    r["costs_assumed"])) if m["signal"] else 0.0
                               for m in r["models"]}}
            if self.record_outcome(r["decision_id"], ts, out, now):
                n += 1
        return n

    # ---- integrity and retention ----------------------------------------------------------------------------------
    def verify(self) -> list[str]:
        bad = []
        for p in self._files("predictions") + self._files("outcomes") + [self.manifest.path]:
            if p.name.endswith((".corrupt", ".tmp")) or not p.exists():
                continue
            bad += ChainLog(p).verify()
        return bad

    def recover(self) -> int:
        n = 0
        for p in self._files("predictions") + self._files("outcomes"):
            if p.suffix == ".jsonl":
                n += ChainLog(p).recover()
        self._seen = {}
        return n

    def close_months(self, today: dt.date) -> list[str]:
        """Compress finished months (chains still verify)."""
        done = []
        cur = f"{today:%Y-%m}"
        for p in self._files("predictions") + self._files("outcomes"):
            if p.suffix == ".jsonl" and p.stem.split("-", 1)[1] < cur:
                ChainLog(p).close()
                done.append(p.name)
        self._seen = {}
        return done

    def prune(self, today: dt.date, keep_days: int) -> list[str]:
        """Delete whole months entirely older than `keep_days`, recording each in the manifest."""
        cutoff = pd.Timestamp(today) - pd.Timedelta(days=keep_days)
        gone = []
        for p in self._files("predictions") + self._files("outcomes"):
            month = p.name.split("-", 1)[1][:7]
            end = pd.Period(month).end_time
            if end < cutoff:
                self.manifest.append({"event": "pruned", "file": p.name, "at": str(today), "keep_days": keep_days})
                p.unlink()
                gone.append(p.name)
        self._seen = {}
        return gone
