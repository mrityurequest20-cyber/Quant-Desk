"""The paper-learning cycle: ingest → dataset → train → validate → register → paper → promote.

Every stage records its input key and outputs in `cycles/<YYYY-MM-DD>.json`; rerunning skips a stage already done on
the same inputs (idempotent), and a crashed or failed run picks up at the first stage that isn't done (resumable).
One cycle at a time (`cycle.lock`; a lock older than three hours is taken over, on the record). A failure anywhere
leaves the registry untouched: retraining only adds challengers, and only `promote` can change the champion, and only
when every gate passes. Retention keeps the files bounded (datasets, run folders, cycle records, rejected models,
ledger months, the 5-minute bar store).

    a ingest    validate and store the bars (recorded sessions + Yahoo 5-minute history), resolve the outcomes of
                pending ledger predictions, and append newly closed paper trades from the journal (validated, once)
    b dataset   samples (features + 30-minute labels) from the validated bars, the locked final test, a fingerprint
    c train     every candidate (and the champion's own spec) through identical day-grouped purged walk-forward folds,
                then a final fit on all unlocked sessions
    d validate  costs, metrics, block-bootstrap intervals, gates; the locked final test for those that pass
    e register  passing candidates become challengers (never champions)
    f paper     each registered model's live shadow record from the ledger, the champion's paper trades, drift
    g promote   a challenger that passes walk-forward, the locked test, the paper gates and the risk limits replaces
                the champion (which becomes the rollback target); otherwise the reasons are recorded
"""
from __future__ import annotations

import json
import os
import shutil
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from ..intraday.quant import to_5m
from . import drift as D
from .evaluate import CostModel, evaluate, gates, paired_edge, simulate, trading
from .features import FEATURE_VERSION, FEATURES, LABEL_VERSION, build_samples, fingerprint, validate_bars
from .ledger import Ledger
from .models import SPECS, Pipeline
from .registry import PromotionRefused, Registry, code_fingerprint
from .store import ChainLog, read_json, sha, write_json
from .validation import LockBox, WalkForwardConfig, folds, layout_hash, split

IST = "Asia/Kolkata"
STAGES = ("ingest", "dataset", "train", "validate", "register", "paper", "promote")
LOCK_STALE = pd.Timedelta(hours=3)
PROMOTION = {"min_shadow_sessions": 10, "min_shadow_signals": 60, "min_shadow_expectancy_bps": 0.0,
             "min_p_beats_champion": 0.60, "max_shadow_drawdown_bps": 1500.0, "max_challenger_days": 45,
             "max_risk_violations": 0}


def root_of(cfg) -> Path:
    return Path(cfg.runtime_dir) / str(cfg.get("autolearn.dir", "intraday/autolearn"))


class CycleBusy(RuntimeError):
    pass


class Cycle:
    def __init__(self, cfg, now: pd.Timestamp | None = None, loader=None, journal_path: Path | None = None, say=print,
                 root: Path | None = None):
        self.cfg = cfg
        self.root = Path(root) if root else root_of(cfg)
        self.now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=IST)
        self.say = say or (lambda *a: None)
        self.loader = loader
        self.journal_path = journal_path if journal_path is not None else Path(cfg.runtime_dir) / "intraday" / "journal.db"
        a = cfg.get("autolearn", {}) or {}
        self.symbols = list(a.get("symbols") or ["NIFTY", "BANKNIFTY"])
        self.cost = CostModel.from_cfg(cfg)
        self.wf = WalkForwardConfig.from_cfg(cfg)
        self.boot = a.get("bootstrap") or {}
        self.gates_cfg = a.get("gates") or {}
        self.promo = {**PROMOTION, **(a.get("promotion") or {})}
        self.ret = {"datasets": 3, "runs": 4, "cycles": 30, "rejected_models": 20, "ledger_days": 400, "bar_days": 250,
                    **(a.get("retention") or {})}
        self.lock_days = int(a.get("final_test_days", 8))
        self.candidates = list(a.get("candidates") or SPECS)
        self.min_coverage = float((a.get("abstain") or {}).get("min_coverage", 0.10))
        self.reg, self.ledger, self.lockbox = Registry(self.root), Ledger(self.root), LockBox(self.root)
        self.cycle_id = f"{self.now.date()}"
        self.state_path = self.root / "cycles" / f"{self.cycle_id}.json"
        self.run_dir = self.root / "runs" / self.cycle_id
        self.audit = ChainLog(self.root / "cycles" / "audit.jsonl")

    # ---- orchestration -------------------------------------------------------------------------------------------
    def run(self, stages=None, force: bool = False) -> dict:
        want = [s for s in STAGES if not stages or s in stages]
        self._lock()
        try:
            st = read_json(self.state_path) or {"cycle_id": self.cycle_id, "stages": {}, "started": str(self.now)}
            for name in want:
                rec = st["stages"].get(name) or {}
                key = self._key(name, st)
                if not force and rec.get("status") == "done" and rec.get("key") == key:
                    self.say(f"  {name}: done already (same inputs), skipped")
                    continue
                st["stages"][name] = {"status": "running", "key": key, "started": str(pd.Timestamp.now(tz=IST))}
                write_json(self.state_path, st)
                try:
                    out = getattr(self, f"_{name}")(st)
                except Exception as exc:                          # recorded, the cycle stops, the registry is untouched
                    st["stages"][name] = {"status": "failed", "key": key, "error": f"{type(exc).__name__}: {exc!s:.300}",
                                          "where": traceback.format_exc(limit=3)[-600:], "finished": str(pd.Timestamp.now(tz=IST))}
                    write_json(self.state_path, st)
                    self.audit.append({"event": "stage_failed", "cycle": self.cycle_id, "stage": name,
                                       "error": st["stages"][name]["error"]})
                    self.say(f"  {name}: FAILED {st['stages'][name]['error']}")
                    st["status"] = "failed"
                    return st
                st["stages"][name] = {"status": "done", "key": key, "output": out, "finished": str(pd.Timestamp.now(tz=IST))}
                write_json(self.state_path, st)
                self.say(f"  {name}: {self._brief(name, out)}")
            st["status"] = "done" if all((st["stages"].get(s) or {}).get("status") == "done" for s in STAGES) else "partial"
            st["finished"] = str(pd.Timestamp.now(tz=IST))
            write_json(self.state_path, st)
            if st["status"] == "done":
                self.audit.append({"event": "cycle_done", "cycle": self.cycle_id, "champion": self.reg.state().get("champion")})
                self._retention()
            return st
        finally:
            self._unlock()

    def _lock(self):
        p = self.root / "cycle.lock"
        p.parent.mkdir(parents=True, exist_ok=True)
        cur = read_json(p)
        if cur:
            age = self.now - pd.Timestamp(cur.get("at"))
            if age < LOCK_STALE and cur.get("pid") != os.getpid():
                raise CycleBusy(f"another learning cycle holds the lock (pid {cur.get('pid')}, since {cur.get('at')})")
            if cur.get("pid") != os.getpid():
                self.audit.append({"event": "stale_lock_taken", "held_by": cur, "at": str(self.now)})
        write_json(p, {"pid": os.getpid(), "at": str(self.now), "cycle": self.cycle_id})

    def _unlock(self):
        try:
            (self.root / "cycle.lock").unlink()
        except FileNotFoundError:
            pass

    def _key(self, name: str, st: dict) -> str:
        """What a stage's result depends on: a change re-runs it."""
        prev = {s: (st["stages"].get(s) or {}).get("output") for s in STAGES}
        if name == "ingest":
            return sha({"now": str(self.now.floor("min")), "symbols": self.symbols})[:16]
        if name == "dataset":
            return sha({"bars": (prev["ingest"] or {}).get("fingerprints"), "f": FEATURE_VERSION, "l": LABEL_VERSION,
                        "delay": self.cost.delay_bars})[:16]
        if name in ("train", "validate", "register"):
            return sha({"data": (prev["dataset"] or {}).get("fingerprint"), "wf": self.wf.to_dict(), "cands": self.candidates,
                        "code": code_fingerprint(), "cost": self.cost.to_dict(), "gates": self.gates_cfg, "boot": self.boot,
                        "champion": self.reg.state().get("champion"), "stage": name})[:16]
        reg = self.reg.state().get("last_event") or {}
        return sha({"ledger": len(self.ledger.decisions()), "outcomes": len(self.ledger.outcomes()), "reg": reg.get("hash"),
                    "promo": self.promo, "stage": name, "now": str(self.now.date())})[:16]

    @staticmethod
    def _brief(name, out) -> str:
        if not isinstance(out, dict):
            return str(out)
        keys = {"ingest": ("bars", "outcomes_resolved", "paper_trades_new"), "dataset": ("rows", "days", "fingerprint", "quality_ok"),
                "train": ("trained", "failed"), "validate": ("passed", "failed"), "register": ("registered",),
                "paper": ("evaluated", "drift"), "promote": ("decision",)}.get(name, ())
        return ", ".join(f"{k} {out.get(k)}" for k in keys if k in out)

    # ---- a. ingest -----------------------------------------------------------------------------------------------
    def _ingest(self, st) -> dict:
        bars, quality = self.gather()
        store = self.root / "bars5"
        fps = {}
        for sym, b in bars.items():
            fps[sym] = fingerprint(b)
            write_parquet(b, store / f"{sym}.parquet")
        resolved = self.ledger.resolve(bars, self.now, cost_bps=self.cost.round_trip_bps, delay_bars=self.cost.delay_bars)
        new_trades, rejected = self._ingest_paper_trades()
        return {"bars": {s: int(len(b)) for s, b in bars.items()}, "fingerprints": fps, "quality": quality,
                "outcomes_resolved": resolved, "paper_trades_new": new_trades, "paper_trades_rejected": rejected,
                "last_bar": {s: str(b.index[-1]) if len(b) else None for s, b in bars.items()}}

    def gather(self) -> tuple[dict, dict]:
        """Validated 5-minute bars per symbol: the persisted store, Yahoo's history, the desk's recorded sessions (in
        that order of preference for a session, best last), one source per session, never mixed within a day."""
        hol = set(self.cfg.holidays())
        store = self.root / "bars5"
        out, quality = {}, {}
        for sym in self.symbols:
            sources = []
            old = read_parquet(store / f"{sym}.parquet")
            if old is not None and len(old):
                sources.append(("store", old))
            if self.loader is not None:
                for name, frame, is_1m in self.loader(sym):
                    if frame is None or frame.empty:
                        continue
                    clean, rep = validate_bars(frame, hol, freq_min=1 if is_1m else 5)
                    quality.setdefault(sym, {})[name] = {k: rep[k] for k in ("rows_in", "rows_out", "issues", "ok")}
                    sources.append((name, to_5m(clean) if is_1m else clean))
            by_day: dict = {}
            for name, frame in sources:                              # later sources win a whole session
                for day, part in frame.groupby(frame.index.date):
                    if len(part) >= 60 or day not in by_day:         # a near-complete session, or nothing better
                        by_day[day] = part
            if not by_day:
                out[sym] = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
                continue
            merged = pd.concat([by_day[d] for d in sorted(by_day)])
            keep = sorted(by_day)[-int(self.ret["bar_days"]):]
            lock = set(self.lockbox.days())
            keep = sorted(set(keep) | {d for d in by_day if str(d) in lock})   # the locked sessions are never dropped
            merged = merged[pd.Index(merged.index.date).isin(keep)]
            clean, rep = validate_bars(merged, hol, freq_min=5)
            q = {k: rep[k] for k in ("rows_in", "rows_out", "issues", "ok", "jump_days", "conflicting_duplicates")}
            # usable: bars left after cleaning, and no timestamp with two different prices (quarantined jump sessions are
            # already excluded, gaps are reported)
            q["usable"] = bool(rep["rows_out"] > 0 and not rep["conflicting_duplicates"])
            quality.setdefault(sym, {})["merged"] = q
            out[sym] = clean
        return out, quality

    def _ingest_paper_trades(self) -> tuple[int, int]:
        """Closed paper trades from the journal → paper_trades.jsonl (append-only, each trade once), attributed to the
        champion that was active when the trade opened."""
        if not Path(self.journal_path).exists():
            return 0, 0
        import sqlite3
        with sqlite3.connect(f"file:{self.journal_path}?mode=ro", uri=True) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("journal failed its integrity check: restore it before learning from it")
            rows = db.execute("SELECT id, strategy, symbol, opened_at, closed_at, pnl, fees, r_multiple, meta FROM trades "
                              "WHERE status='closed' ORDER BY closed_at").fetchall()
        log = ChainLog(self.root / "paper_trades.jsonl")
        seen = {r["trade_id"] for r in log.read()}
        champs = self._champion_timeline()
        new = bad = 0
        for tid, strat, sym, op, cl, pnl, fees, r, meta in rows:
            if tid in seen:
                continue
            try:
                o, c, p = pd.Timestamp(op), pd.Timestamp(cl), float(pnl)
                if not (np.isfinite(p) and c >= o):
                    raise ValueError("bad times or P&L")
            except (TypeError, ValueError):
                bad += 1
                continue
            m = json.loads(meta or "{}") if isinstance(meta, str) else {}
            al = m.get("autolearn") or {}
            model = al.get("model_id") or next((mid for t0, mid in reversed(champs) if t0 <= o), None)
            log.append({"trade_id": tid, "strategy": strat, "symbol": sym, "opened_at": str(o), "closed_at": str(c),
                        "pnl": p, "fees": float(fees or 0), "r_multiple": float(r) if r is not None else None,
                        "model_id": model, "decision_id": al.get("decision_id")})
            new += 1
        return new, bad

    def _champion_timeline(self) -> list[tuple[pd.Timestamp, str]]:
        out = []
        for e in self.reg.events.read():
            if e.get("event") == "promoted":
                out.append((pd.Timestamp(e["at"]), e["model_id"]))
            elif e.get("event") == "rolled_back":
                out.append((pd.Timestamp(e["at"]), e.get("to")))
        return out

    # ---- b. dataset ----------------------------------------------------------------------------------------------
    def _dataset(self, st) -> dict:
        ing = (st["stages"].get("ingest") or {}).get("output") or {}
        parts = []
        for sym in self.symbols:
            b = read_parquet(self.root / "bars5" / f"{sym}.parquet")
            if b is not None and len(b):
                parts.append(build_samples(b, sym, self.cost.delay_bars))
        if not parts:
            raise RuntimeError("no validated bars to build a dataset from")
        s = pd.concat(parts, ignore_index=True).sort_values(["ts", "symbol"], kind="stable").reset_index(drop=True)
        if not np.isfinite(s[FEATURES].to_numpy(float)).all():
            raise RuntimeError("non-finite features in the dataset")
        lock = self.lockbox.ensure(s, self.lock_days, self.now)
        changed = self.lockbox.verify(s)
        if changed:
            raise RuntimeError("; ".join(changed))
        fp = sha({"bars": ing.get("fingerprints"), "f": FEATURE_VERSION, "l": LABEL_VERSION, "d": self.cost.delay_bars})[:16]
        quality = ing.get("quality") or {}
        quality_ok = bool(quality) and all((q.get("merged") or {}).get("usable", False) for q in quality.values())
        write_parquet(s, self.root / "datasets" / f"{fp}.parquet")
        meta = {"fingerprint": fp, "rows": int(len(s)), "labelled": int(s["y"].notna().sum()), "days": int(s["day"].nunique()),
                "first_day": s["day"].min(), "last_day": s["day"].max(), "symbols": sorted(s["symbol"].unique()),
                "feature_version": FEATURE_VERSION, "label_version": LABEL_VERSION, "quality_ok": bool(quality_ok),
                "lockbox_days": (lock or {}).get("days", []), "created": str(self.now)}
        write_json(self.root / "datasets" / f"{fp}.json", meta)
        return meta

    def _samples(self, st) -> pd.DataFrame:
        fp = ((st["stages"].get("dataset") or {}).get("output") or {}).get("fingerprint")
        s = read_parquet(self.root / "datasets" / f"{fp}.parquet") if fp else None
        if s is None:
            raise RuntimeError("the dataset stage's output is missing: rerun from `dataset`")
        return s

    # ---- c. train ------------------------------------------------------------------------------------------------
    def _specs(self) -> dict:
        specs = {n: SPECS[n] for n in self.candidates if n in SPECS}
        mid = self.reg.state().get("champion")
        card = self.reg.card(mid) if mid else None
        if card:                                                  # the champion's own recipe, refitted on the same folds
            specs["champion"] = card["params"]
        return specs

    def _train(self, st) -> dict:
        s = self._samples(st)
        lock = self.lockbox.days()
        fl = folds(s, self.wf, lock)
        if not fl:
            raise RuntimeError(f"not enough sessions for {self.wf.folds} folds after {self.wf.min_train_days} training days "
                               f"({s['day'].nunique()} sessions, {len(lock)} locked)")
        shutil.rmtree(self.run_dir, ignore_errors=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        lay = layout_hash(fl, self.wf, ((st["stages"].get("dataset") or {}).get("output") or {}).get("fingerprint", ""))
        trained, failed, fold_info = [], {}, []
        cb = self.cost.round_trip_bps(float(s["entry_px"].dropna().median() or 1), self.symbols[0])
        specs = self._specs()
        first = next(iter(specs))
        for name, spec in specs.items():
            try:
                oos = []
                for f in fl:
                    tr, te, info = split(s, f, self.wf, lock)
                    pipe = Pipeline(name, spec).fit(
                        tr, cb, embargo=pd.Timedelta(minutes=self.wf.embargo_min), min_coverage=self.min_coverage)
                    te = te.dropna(subset=["y"]).copy()
                    te["p"] = pipe.predict(te)
                    te["signal"] = pipe.signal(te["p"].to_numpy())
                    te["fold"] = f["fold"]
                    oos.append(te)
                    if name == first:
                        fold_info.append({"fold": f["fold"], "test_days": [f["test_days"][0], f["test_days"][-1]], **info})
                o = pd.concat(oos, ignore_index=True)
                write_parquet(o, self.run_dir / f"oos_{name}.parquet")
                unlocked = s[~s["day"].isin(lock)]
                if lock:                                          # nothing whose label reaches into the locked sessions
                    lstart = s.loc[s["day"].isin(lock), "ts"].min()
                    unlocked = unlocked[~((pd.to_datetime(unlocked["label_end"]) > lstart - pd.Timedelta(minutes=5))
                                          & (unlocked["ts"] < lstart))]
                final = Pipeline(name, spec).fit(unlocked, cb, embargo=pd.Timedelta(minutes=self.wf.embargo_min),
                                                 min_coverage=self.min_coverage)
                write_json(self.run_dir / f"artifact_{name}.json", final.artifact())
                write_json(self.run_dir / f"fit_{name}.json", {"fit": final.fit_info, "train_days": [unlocked["day"].min(), unlocked["day"].max()],
                                                               "train_rows": int(unlocked["y"].notna().sum())})
                trained.append(name)
            except Exception as exc:                              # one failed candidate never stops the others
                failed[name] = f"{type(exc).__name__}: {exc!s:.200}"
        if not trained:
            raise RuntimeError(f"every candidate failed to train: {failed}")
        return {"trained": trained, "failed": failed, "folds": fold_info, "layout_hash": lay, "cost_bps_typical": round(cb, 3)}

    # ---- d. validate ---------------------------------------------------------------------------------------------
    def _validate(self, st) -> dict:
        s = self._samples(st)
        ds = (st["stages"].get("dataset") or {}).get("output") or {}
        tr_out = (st["stages"].get("train") or {}).get("output") or {}
        res, passed, failed = {}, [], []
        oos_all = {n: read_parquet(self.run_dir / f"oos_{n}.parquet") for n in tr_out.get("trained", [])}
        champ_oos = oos_all.get("champion")
        champ_tr = simulate(champ_oos, champ_oos["p"].to_numpy(), champ_oos["signal"].to_numpy(), self.cost) if champ_oos is not None else None
        for name, o in oos_all.items():
            if o is None:
                raise RuntimeError(f"out-of-sample predictions for {name} are missing: rerun from `train`")
            m = evaluate(o, self.cost, self.boot)
            vs = None
            if champ_tr is not None and name != "champion":
                mine = simulate(o, o["p"].to_numpy(), o["signal"].to_numpy(), self.cost)
                vs = paired_edge(mine, champ_tr, sorted(o["day"].unique()), self.boot)
            ok, reasons, checks = gates(m, ds.get("quality_ok", False), self.gates_cfg, vs)
            res[name] = {"metrics": m, "vs_champion": vs, "passed": ok, "reasons": reasons, "checks": checks}
            if name != "champion":
                (passed if ok else failed).append(name)
        for name in passed:                                       # the locked final test, only for those that passed
            res[name]["lockbox"] = self._lockbox_check(s, name, st)
            if not res[name]["lockbox"]["passed"]:
                passed.remove(name)
                failed.append(name)
                res[name]["passed"] = False
                res[name]["reasons"].append("failed the locked final test")
        write_json(self.run_dir / "validation.json", res)
        return {"passed": passed, "failed": failed,
                "summary": {n: {"expectancy_bps": r["metrics"]["trading"]["expectancy_bps"], "trades": r["metrics"]["trading"]["trades"],
                                "auc": r["metrics"]["classification"]["auc"], "brier_skill": r["metrics"]["classification"]["brier_skill"],
                                "ece": r["metrics"]["classification"]["ece"], "p_positive": r["metrics"]["ci"]["expectancy_bps"]["p_positive"],
                                "reasons": r["reasons"]} for n, r in res.items()}}

    def _lockbox_check(self, s: pd.DataFrame, name: str, st) -> dict:
        lock = self.lockbox.get()
        if not lock:
            return {"passed": False, "reason": "no locked final test yet (needs 3× its length in sessions)"}
        days = set(lock["days"])
        test = s[s["day"].isin(days)].dropna(subset=["y"])
        if test.empty:
            return {"passed": False, "reason": "the locked sessions are not in the dataset"}
        start = test["ts"].min() - pd.Timedelta(minutes=5)
        before = s[(s["day"] < min(days)) & ~((pd.to_datetime(s["label_end"]) > start - pd.Timedelta(minutes=self.wf.embargo_min)))]
        spec = self._specs()[name]
        cb = self.cost.round_trip_bps(float(s["entry_px"].dropna().median() or 1), self.symbols[0])
        try:
            pipe = Pipeline(name, spec).fit(before, cb, embargo=pd.Timedelta(minutes=self.wf.embargo_min), min_coverage=self.min_coverage)
        except ValueError as exc:
            return {"passed": False, "reason": f"could not fit on the sessions before the lock: {exc}"}
        test = test.copy()
        test["p"] = pipe.predict(test)
        test["signal"] = pipe.signal(test["p"].to_numpy())
        tr = simulate(test, test["p"].to_numpy(), test["signal"].to_numpy(), self.cost)
        t = trading(tr, test["day"].nunique())
        g = {**{"lockbox_min_trades": 5, "lockbox_min_expectancy_bps": 0.0}, **(self.gates_cfg or {})}
        ok = bool(t["trades"] >= g["lockbox_min_trades"] and t["expectancy_bps"] == t["expectancy_bps"]
                  and t["expectancy_bps"] > g["lockbox_min_expectancy_bps"])
        peeks = self.lockbox.record_access(name, "final test of a candidate that passed walk-forward",
                                           {"trades": t["trades"], "expectancy_bps": t["expectancy_bps"]})
        return {"passed": ok, "trades": t["trades"], "expectancy_bps": t["expectancy_bps"], "net_bps_total": t["net_bps_total"],
                "days": sorted(days), "peeks": peeks,
                "reason": None if ok else f"{t['trades']} trades at {t['expectancy_bps']:+.2f} bps on the locked sessions"}

    # ---- e. register ---------------------------------------------------------------------------------------------
    def _register(self, st) -> dict:
        val = read_json(self.run_dir / "validation.json") or {}
        v_out = (st["stages"].get("validate") or {}).get("output") or {}
        ds = (st["stages"].get("dataset") or {}).get("output") or {}
        tr = (st["stages"].get("train") or {}).get("output") or {}
        s = self._samples(st)
        out = {"registered": [], "already": []}
        for name in v_out.get("passed", []):
            art = read_json(self.run_dir / f"artifact_{name}.json")
            fit = read_json(self.run_dir / f"fit_{name}.json") or {}
            pipe = Pipeline.from_artifact(art)
            o = read_parquet(self.run_dir / f"oos_{name}.parquet")
            train = s[s["day"].between(*fit.get("train_days", [s["day"].min(), s["day"].max()]))].dropna(subset=["y"])
            card = {"code_fingerprint": code_fingerprint(), "feature_version": FEATURE_VERSION, "label_version": LABEL_VERSION,
                    "data_fingerprint": ds.get("fingerprint"),
                    "training_window": {"first_day": fit.get("train_days", [None])[0], "last_day": fit.get("train_days", [None, None])[1],
                                        "rows": fit.get("train_rows"), "fit": fit.get("fit")},
                    "validation": {"layout_hash": tr.get("layout_hash"), "walk_forward": self.wf.to_dict(), "folds": tr.get("folds"),
                                   "metrics": val[name]["metrics"], "vs_champion": val[name].get("vs_champion"),
                                   "checks": val[name]["checks"], "passed": True, "cycle": self.cycle_id},
                    "lockbox": val[name].get("lockbox"), "costs": self.cost.to_dict(),
                    "drift_reference": D.references(train, o["p"].to_numpy(float)), "registered_at": str(self.now)}
            mid, new = self.reg.register(pipe, card)
            out["registered" if new else "already"].append(mid)
        return out

    # ---- f. paper ------------------------------------------------------------------------------------------------
    def _paper(self, st) -> dict:
        reg = self.reg.state()
        ids = [m for m in [reg.get("champion"), reg.get("rollback_target"), *reg.get("challengers", [])] if m]
        frame = self.ledger.frame(source="live")
        out = {"evaluated": [], "results": {}, "drift": None}
        for mid in ids:
            card = self.reg.card(mid) or {}
            since = _ts(card.get("registered_at")) or pd.Timestamp("1970-01-01", tz=IST)
            f = frame[(frame["model_id"] == mid) & (frame["ts"] >= since)] if len(frame) else frame
            r = shadow_result(f, self.cost)
            r["since"] = str(since)
            out["results"][mid] = r
            self.reg.update_card(mid, paper={**(card.get("paper") or {}), "shadow": r, "as_of": str(self.now)})
            out["evaluated"].append(mid)
        champ = reg.get("champion")
        if champ:
            card = self.reg.card(champ) or {}
            recent_days = sorted(frame["day"].unique())[-int((self.cfg.get("autolearn.drift", {}) or {}).get("window_days", 5)):] \
                if len(frame) else []
            recent = frame[(frame["model_id"] == champ) & frame["day"].isin(recent_days)] if len(frame) else frame
            dr = D.report(card, recent, self.cfg.get("autolearn.drift", {}) or {})
            out["drift"] = dr["state"]
            out["drift_report"] = dr
            write_json(self.root / "drift.json", {**dr, "model_id": champ, "as_of": str(self.now)})
            out["champion_paper_trades"] = self._champion_trades(champ)
        return out

    def _champion_trades(self, mid: str) -> dict:
        from ..research.protocol import evaluate_paper_candidate
        rows = [r for r in ChainLog(self.root / "paper_trades.jsonl").read() if r.get("model_id") == mid]
        if not rows:
            return {"closed_trades": 0}
        t = pd.DataFrame(rows).assign(status="closed")
        cap = float(self.cfg.get("intraday.capital", 20000) or 20000)
        return evaluate_paper_candidate(t, int(pd.to_datetime(t["closed_at"]).dt.date.nunique()), self._risk_violations(), cap)

    def _risk_violations(self) -> int:
        """Risk-limit breaches on the journal's record (ERROR events filed under risk)."""
        if not Path(self.journal_path).exists():
            return 0
        import sqlite3
        with sqlite3.connect(f"file:{self.journal_path}?mode=ro", uri=True) as db:
            return int(db.execute("SELECT COUNT(*) FROM events WHERE category='risk' AND level IN ('ERROR','CRITICAL')").fetchone()[0])

    # ---- g. promote ----------------------------------------------------------------------------------------------
    def _promote(self, st) -> dict:
        paper = (st["stages"].get("paper") or {}).get("output") or {}
        reg = self.reg.state()
        champ = reg.get("champion")
        champ_res = (paper.get("results") or {}).get(champ) if champ else None
        frame = self.ledger.frame(source="live")
        qualified, decisions = [], {}
        for mid in reg.get("challengers", []):
            card = self.reg.card(mid) or {}
            r = (paper.get("results") or {}).get(mid) or {}
            checks = {"walk_forward_validation": bool((card.get("validation") or {}).get("passed")),
                      "locked_final_test": bool((card.get("lockbox") or {}).get("passed")),
                      "paper_sessions": r.get("sessions", 0) >= self.promo["min_shadow_sessions"],
                      "paper_signals": r.get("trades", 0) >= self.promo["min_shadow_signals"],
                      "paper_net_expectancy": (r.get("expectancy_bps") or float("-inf")) > self.promo["min_shadow_expectancy_bps"],
                      "paper_drawdown": (r.get("max_drawdown_bps") if r.get("max_drawdown_bps") is not None else float("-inf"))
                      >= -self.promo["max_shadow_drawdown_bps"],
                      "risk_limits": self._risk_violations() <= self.promo["max_risk_violations"]}
            try:
                self.reg.load(mid)
                checks["artifact_verifies"] = True
            except Exception:
                checks["artifact_verifies"] = False
            if champ and champ_res:
                mine = frame[frame["model_id"] == mid]
                theirs = frame[frame["model_id"] == champ]
                common = sorted(set(mine["day"]) & set(theirs["day"]))
                pe = paired_edge(shadow_trades(mine[mine["day"].isin(common)], self.cost),
                                 shadow_trades(theirs[theirs["day"].isin(common)], self.cost), common, self.boot) if common else {}
                checks["paper_beats_champion"] = bool(pe.get("p_positive") is not None and pe["p_positive"] >= self.promo["min_p_beats_champion"])
            decisions[mid] = checks
            if all(checks.values()):
                qualified.append((r.get("expectancy_bps") or 0.0, mid))
        out = {"decision": "no change", "checks": decisions, "champion": champ}
        if qualified:
            best = max(qualified)[1]
            reason = (f"passed walk-forward, the locked final test, every paper gate and the risk limits; "
                      f"shadow expectancy {max(qualified)[0]:+.2f} bps after costs")
            try:
                self.reg.promote(best, reason, decisions[best])
                out.update({"decision": f"promoted {best}", "previous": champ})
            except PromotionRefused as exc:
                out.update({"decision": f"promotion refused: {exc}"})
        for mid, checks in decisions.items():
            if out["decision"] == f"promoted {mid}":
                continue
            card = self.reg.card(mid) or {}
            age = (self.now - pd.Timestamp(card.get("registered_at") or self.now)).days if card.get("registered_at") else 0
            failed = [k for k, v in checks.items() if not v]
            if age > self.promo["max_challenger_days"] or not checks.get("artifact_verifies", True):
                self.reg.reject(mid, f"not promoted within {self.promo['max_challenger_days']} days" if checks.get("artifact_verifies", True)
                                else "artifact failed verification", {"failed": failed})
            elif failed:
                self.reg.note(mid, "deferred", failed=failed, cycle=self.cycle_id)
        return out

    # ---- retention -----------------------------------------------------------------------------------------------
    def _retention(self) -> dict:
        gone = {}
        for folder, n, pat in (("datasets", self.ret["datasets"], "*.parquet"), ("runs", self.ret["runs"], "*"),
                               ("cycles", self.ret["cycles"], "*.json")):
            d = self.root / folder
            files = sorted(d.glob(pat), key=lambda p: p.stat().st_mtime) if d.exists() else []
            old = files[:-n] if n and len(files) > n else []
            for p in old:
                if p.name == "audit.jsonl":
                    continue
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                    j = p.with_suffix(".json")
                    if folder == "datasets" and j.exists():
                        j.unlink()
            gone[folder] = len(old)
        slim = 0                                                  # older runs keep their JSON records, not the bulky parquet
        for d in sorted((self.root / "runs").glob("*")) if (self.root / "runs").exists() else []:
            if d.is_dir() and d.name != self.cycle_id:
                for f in d.glob("*.parquet"):
                    f.unlink()
                    slim += 1
        gone["run_parquet"] = slim
        gone["models"] = len(self.reg.prune(int(self.ret["rejected_models"])))
        gone["ledger_months"] = len(self.ledger.prune(self.now.date(), int(self.ret["ledger_days"])))
        self.ledger.close_months(self.now.date())
        return gone


# ---- shadow (paper) results from the ledger ----------------------------------------------------------------------------
def shadow_trades(f: pd.DataFrame, cost: CostModel) -> pd.DataFrame:
    """A model's resolved live predictions → the non-overlapping trades it would have taken (the same simulator)."""
    if f is None or f.empty:
        return simulate(pd.DataFrame(columns=["fwd_ret", "entry_px", "ts", "label_end", "symbol", "day", "minute", "sig5", "day_ret"]),
                        np.array([]), np.array([]), cost)
    r = f[f["resolved"]].copy()
    r["fwd_ret"] = r["fwd_ret"].astype(float)
    return simulate(r, r["p"].to_numpy(float), r["signal"].to_numpy(int), cost)


def shadow_result(f: pd.DataFrame, cost: CostModel) -> dict:
    tr = shadow_trades(f, cost)
    days = sorted(f["day"].unique()) if f is not None and len(f) else []
    t = trading(tr, len(days))
    return {"sessions": len(days), "predictions": int(len(f)) if f is not None else 0,
            "resolved": int(f["resolved"].sum()) if f is not None and len(f) else 0, **t}


def _ts(x) -> pd.Timestamp | None:
    if not x:
        return None
    t = pd.Timestamp(x)
    return t.tz_localize(IST) if t.tzinfo is None else t.tz_convert(IST)


# ---- data sources ------------------------------------------------------------------------------------------------------
def default_loader(cfg, offline: bool = False, say=print):
    """loader(symbol) → [(name, bars, is_1m)]: Yahoo's 5-minute history (unless offline), then the desk's recorded
    1-minute sessions (runtime/intraday/data/<day>/<SYMBOL>_1m.csv), which win a session they cover."""
    from ..intraday.feeds import normalise_bars
    data = Path(cfg.runtime_dir) / "intraday" / "data"
    days = int(cfg.get("autolearn.history_days", 55))

    def load(sym):
        out = []
        if not offline:
            try:
                from ..intraday.feeds import YahooIntradayFeed
                out.append(("yahoo", YahooIntradayFeed(cfg).history_bars(sym, days), False))
            except Exception as exc:                                 # offline runs still learn from what's recorded
                say(f"  yahoo {sym}: unavailable ({exc!s:.100})")
        rec = []
        for p in sorted(data.glob(f"*/{sym}_1m.csv")) if data.exists() else []:
            try:
                rec.append(normalise_bars(pd.read_csv(p, index_col=0, parse_dates=True)))
            except (OSError, ValueError) as exc:
                say(f"  recorded {p.parent.name} {sym}: unreadable ({exc!s:.80})")
        if rec:
            out.append(("recorded", pd.concat(rec), True))
        return out
    return load


# ---- parquet helpers ---------------------------------------------------------------------------------------------------
def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, compression="zstd")
    os.replace(tmp, path)


def read_parquet(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError, FileNotFoundError):
        return None
