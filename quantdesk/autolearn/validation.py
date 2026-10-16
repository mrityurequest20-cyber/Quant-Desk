"""Day-grouped walk-forward validation with purging and an embargo, and the locked final test.

Walk-forward: the sessions (minus the locked final test) are ordered; after `min_train_days`, the rest are cut into
`folds` contiguous test blocks. Fold k trains on every session before its block (expanding window) and tests on the
block. Two guards make it leak-proof even if a fold ever starts mid-session or labels ever cross a session:
  purge    drop every training row whose label is still open at the test block's start (label_end > test start);
  embargo  also drop training rows decided within `embargo_min` (≥ the 30-minute horizon) before the test start.
Each fold's training data then goes through the Pipeline's own fit / calibration split (also purged). The fold layout is
a pure function of the config and the day list, and is recorded with a hash, so a run is reproducible.

The locked final test: the newest `final_test_days` sessions at the moment it is first created are written to
`lockbox.json` and never move. Selection never sees them: walk-forward excludes them (with the embargo around them).
`lockbox_check` refits a candidate's spec on sessions strictly before the lock and scores it once on the locked
sessions; every look is appended to `lockbox_access.jsonl`, so how many times it has been looked at is on the record
(the more looks, the less "final" it is; the report says so).
"""
from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .store import ChainLog, read_json, sha, write_json


@dataclass
class WalkForwardConfig:
    folds: int = 5
    min_train_days: int = 15
    embargo_min: int = 30
    horizon_min: int = 30

    @classmethod
    def from_cfg(cls, cfg) -> "WalkForwardConfig":
        w = (cfg.get("autolearn.walk_forward", {}) or {}) if cfg is not None else {}
        hz = int(cfg.get("autolearn.horizon_min", 30)) if cfg is not None else 30
        c = cls(**{k: v for k, v in w.items() if k in cls.__dataclass_fields__})
        c.horizon_min = hz
        c.embargo_min = max(int(c.embargo_min), hz)                 # never shorter than the prediction horizon
        return c

    def to_dict(self) -> dict:
        return asdict(self)


def folds(samples: pd.DataFrame, cfg: WalkForwardConfig, exclude_days: set | None = None) -> list[dict]:
    """[{fold, train_days, test_days, test_start, test_end}] over the samples' sessions (minus `exclude_days`)."""
    days = sorted(set(samples["day"]) - set(exclude_days or ()))
    rest = days[cfg.min_train_days:]
    if cfg.folds < 1 or len(rest) < cfg.folds:
        return []
    blocks = np.array_split(np.array(rest, dtype=object), cfg.folds)
    out = []
    for k, b in enumerate(blocks):
        b = list(b)
        test = samples[samples["day"].isin(b)]
        out.append({"fold": k, "train_days": [d for d in days if d < b[0]], "test_days": b,
                    "test_start": test["ts"].min() - pd.Timedelta(minutes=5), "test_end": test["ts"].max()})
    return out


def split(samples: pd.DataFrame, fold: dict, cfg: WalkForwardConfig, exclude_days: set | None = None
          ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(train, test, info) for one fold, with the purge and embargo applied to the training side."""
    tr = samples[samples["day"].isin(fold["train_days"])]
    te = samples[samples["day"].isin(fold["test_days"])]
    start = fold["test_start"]
    label_end = pd.to_datetime(tr["label_end"])
    purge = label_end.notna() & (label_end > start)
    emb = (tr["ts"] > start - pd.Timedelta(minutes=cfg.embargo_min)) & (tr["ts"] <= fold["test_end"])
    ex = set(exclude_days or ())
    if ex:                                                       # nothing may lean on the locked sessions either
        lock_start = samples.loc[samples["day"].isin(ex), "ts"].min()
        if lock_start == lock_start:
            near = (label_end > lock_start - pd.Timedelta(minutes=5)) & (tr["ts"] < lock_start)
            purge = purge | near.fillna(False)
    keep = ~(purge | emb)
    info = {"train_rows": int(keep.sum()), "test_rows": int(len(te)), "purged": int(purge.sum()), "embargoed": int((emb & ~purge).sum())}
    return tr[keep], te, info


def layout_hash(fold_list: list[dict], cfg: WalkForwardConfig, data_fp: str) -> str:
    body = {"cfg": cfg.to_dict(), "data": data_fp,
            "folds": [{"train": [f["train_days"][0], f["train_days"][-1], len(f["train_days"])] if f["train_days"] else [],
                       "test": f["test_days"]} for f in fold_list]}
    return sha(body)[:16]


# ---- the locked final test ---------------------------------------------------------------------------------------------
class LockBox:
    def __init__(self, root):
        from pathlib import Path
        self.root = Path(root)
        self.path = self.root / "lockbox.json"
        self.log = ChainLog(self.root / "lockbox_access.jsonl")

    def get(self) -> dict | None:
        return read_json(self.path)

    def ensure(self, samples: pd.DataFrame, n_days: int, now: pd.Timestamp | None = None) -> dict | None:
        """The lock, creating it from the newest `n_days` sessions the first time there are enough sessions (at least
        3× the lock), and never changing it afterwards."""
        lock = self.get()
        if lock:
            return lock
        days = sorted(set(samples["day"]))
        if n_days <= 0 or len(days) < 3 * n_days:
            return None
        locked = days[-n_days:]
        part = samples[samples["day"].isin(locked)]
        lock = {"days": locked, "created_at": str(now or pd.Timestamp.now(tz="Asia/Kolkata")),
                "rows": int(len(part)), "fingerprint": hashlib.sha256(
                    pd.util.hash_pandas_object(part[["symbol", "ts", "y"]].astype(str), index=False).to_numpy().tobytes()).hexdigest()[:16],
                "note": "created once from the newest sessions; never moved; never used for selection"}
        write_json(self.path, lock)
        self.log.append({"event": "created", "at": lock["created_at"], "days": locked})
        return lock

    def days(self) -> set:
        lock = self.get()
        return set(lock["days"]) if lock else set()

    def verify(self, samples: pd.DataFrame) -> list[str]:
        """The locked sessions still hash the same (labels unchanged); problems as strings."""
        lock = self.get()
        if not lock:
            return []
        part = samples[samples["day"].isin(lock["days"])]
        if part.empty:
            return []                                              # aged out of the dataset: nothing to compare
        fp = hashlib.sha256(pd.util.hash_pandas_object(part[["symbol", "ts", "y"]].astype(str), index=False)
                            .to_numpy().tobytes()).hexdigest()[:16]
        if fp == lock["fingerprint"] and len(part) == lock["rows"]:
            return []
        return [f"locked final test changed: {len(part)} rows (locked {lock['rows']}), fingerprint {fp} != "
                f"{lock['fingerprint']}"]                         # A-07: a changed row count is a change too

    def record_access(self, model_id: str, purpose: str, result: dict | None = None) -> int:
        self.log.append({"event": "access", "model": model_id, "purpose": purpose, "at": str(dt.datetime.now()),
                         "result": result or {}})
        return self.peeks()

    def peeks(self) -> int:
        return sum(1 for r in self.log.read() if r.get("event") == "access")
