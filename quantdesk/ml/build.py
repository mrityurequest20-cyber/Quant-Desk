"""The dataset builder (P0.3 of docs/ML_PHASE0.md): point-in-time tables for M1 (the size of the next move), built by the study's own code.

One row is a (symbol, day, decision minute, horizon): the features known at the decision, and the labels over the next 30m / 60m /
120m / to the close, which never reach past the session. The code is `autolearn/volstudy` (`grid`, `profile`, `rows`), called, not
copied, so the table the harness trains on is the table the locked HAR result was computed from.

**The seasonal profile is a fit.** `F_B` and `x_today` divide by the minute-of-day variance profile, and a profile fitted on the whole
sample would leak the test period into every feature. The builder therefore takes `profile_end`, fits the profile on sessions up to
and including that day only (as `volstudy.fit_har` does for a training window), records it in the table's identity, and marks every
row with `in_profile`. Score only rows with `in_profile == False`; a study that needs the profile refitted per fold rebuilds the
table per fold, which is cheap.

**Identity.** The table's folder is `ml-build-1-<12 hex>`, the hash of the input dataset's digest, the recipe (symbols, profile_end,
every constant and the source of the functions that make the rows) and the builder version. The same inputs give the same
identity anywhere. The *values* are floats from numpy reductions that can change in the last bit with memory alignment, so a
hash of values is not an identity: the stored file is pinned by the sha256 of its bytes (it detects any change to what was
written), and a rebuild is compared with `tables_close` at a stated tolerance (default 1e-9; measured 0 on this machine).

Offline and read-only: nothing here imports the engine, the journal, risk or execution.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ..autolearn import volstudy as V
from ..data.external_aeron import ImmutableViolation

BUILDER_VERSION = "ml-build-1"
TABLE = "m1_move_size"
MIN_PROFILE_DAYS = 250                                       # a minute-of-day profile from fewer sessions is mostly noise
COLUMNS = ["symbol", "day", "year", "m", "horizon", "minutes", "rv", "ret", "miss_frac", "F_A", "F_B",
           "x_prev", "x_prev5", "x_today", "x_gap", "lF_B", "in_profile"]
FEATURES = ["F_A", "F_B", "x_prev", "x_prev5", "x_today", "x_gap", "lF_B"]
LABELS = ["rv", "ret"]
KEY = ["symbol", "day", "m", "horizon"]
_HORIZON_ORDER = {h: i for i, h in enumerate(V.HORIZONS)}


class TableError(ValueError):
    """A table breaks one of its own invariants (a label past the session, a duplicate row, a non-finite number, a wrong column)."""


def _code_digest() -> str:
    """The source of every function whose output is in the table: changing one makes a different recipe, hence a different table."""
    src = "\n".join(inspect.getsource(f) for f in (V.grid, V.profile, V._ewma_upto, V.forecasts, V.rows))
    return hashlib.sha256(src.encode()).hexdigest()


def recipe(symbols, profile_end) -> dict:
    return {"table": TABLE, "symbols": sorted(symbols), "profile_end": str(profile_end), "columns": COLUMNS,
            "constants": {"N_MIN": V.N_MIN, "DECISIONS": V.DECISIONS, "HORIZONS": V.HORIZONS, "LAM": V.LAM,
                          "PRIOR_DAYS": V.PRIOR_DAYS, "FLOOR": V.FLOOR, "MIN_PROFILE_DAYS": MIN_PROFILE_DAYS},
            "code_sha256": _code_digest()}


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(input_digest: str, rec: dict) -> str:
    return hashlib.sha256(_canon({"builder": BUILDER_VERSION, "input": input_digest, "recipe": rec}).encode()).hexdigest()[:12]


def manifest_digest(man: dict) -> str:
    return hashlib.sha256(_canon({k: v for k, v in man.items() if k != "digest"}).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_table(d: pd.DataFrame) -> None:
    """The invariants every table must satisfy, whoever built it. Raises TableError on the first that fails."""
    if list(d.columns) != COLUMNS:
        raise TableError(f"columns are {list(d.columns)}, expected {COLUMNS}")
    if d.empty:
        raise TableError("the table has no rows")
    if d.duplicated(KEY).any():
        raise TableError(f"more than one row for the same {KEY}")
    if not d["m"].isin(V.DECISIONS).all():
        raise TableError("a decision minute outside the declared decision grid")
    if not d["horizon"].isin(list(V.HORIZONS)).all():
        raise TableError("a horizon outside the declared horizons")
    fixed = d["horizon"].map(lambda h: V.HORIZONS[h])
    want = np.where(fixed.isna(), V.N_MIN - d["m"], fixed)
    if (d["minutes"].to_numpy() != want).any():
        raise TableError("a label window whose length is not its horizon's")
    if ((d["m"] + d["minutes"]) > V.N_MIN).any():
        raise TableError("a label reaches past the session close")
    for c in ("rv", "ret", "miss_frac", "F_A", "F_B", "x_prev", "x_prev5", "x_today", "x_gap", "lF_B"):
        if not np.isfinite(d[c].to_numpy(float)).all():
            raise TableError(f"{c} holds a NaN or an infinity")
    if (d["rv"] < 0).any() or (d["F_A"] <= 0).any() or (d["F_B"] <= 0).any():
        raise TableError("a negative realised variance or a non-positive forecast")
    if ((d["miss_frac"] < 0) | (d["miss_frac"] > 0.2 + 1e-12)).any():
        raise TableError("a label window with more than 20% of its minutes missing was kept")
    if d["in_profile"].dtype != bool:
        raise TableError("in_profile must be boolean")
    order = list(zip(d["symbol"], d["day"], d["m"], d["horizon"].map(_HORIZON_ORDER)))
    if order != sorted(order):
        raise TableError("rows are not in (symbol, day, decision, horizon) order")


def build_tables(grids: dict, profile_end) -> pd.DataFrame:
    """{symbol: (days, r, missing, opens)} (the output of `volstudy.grid`) -> the M1 table. The minute-of-day profile is fitted on the
    sessions up to and including `profile_end` only. Pure: no I/O, no clock, no randomness."""
    import datetime as dt
    pe = profile_end if isinstance(profile_end, dt.date) else dt.date.fromisoformat(str(profile_end))
    parts = []
    for sym in sorted(grids):
        days, r, miss, opens = grids[sym]
        train = np.array([d <= pe for d in days])
        if int(train.sum()) < MIN_PROFILE_DAYS:
            raise ValueError(f"{sym}: only {int(train.sum())} sessions up to {pe}; a seasonal profile needs {MIN_PROFILE_DAYS}")
        s = V.profile((r ** 2)[train])
        d = V.rows(sym, days, r, miss, opens, s)
        d["lF_B"] = np.log(np.maximum(d["F_B"], V.FLOOR))
        d["in_profile"] = (pd.Index(d["day"]) <= pe)
        d["day"] = pd.Index(d["day"]).map(str)
        parts.append(d)
    out = pd.concat(parts, ignore_index=True)[COLUMNS]
    out["in_profile"] = out["in_profile"].astype(bool)
    out["_h"] = out["horizon"].map(_HORIZON_ORDER)
    out = out.sort_values(["symbol", "day", "m", "_h"], kind="stable").drop(columns="_h").reset_index(drop=True)
    check_table(out)
    return out


def tables_close(a: pd.DataFrame, b: pd.DataFrame, rtol: float = 1e-9, atol: float = 1e-12) -> list[str]:
    """Differences between two tables beyond the tolerance (an empty list means they match). Keys, integers, strings and booleans must be
    equal; floats within `atol + rtol * max(|a|, |b|)`; a NaN matches only a NaN."""
    if list(a.columns) != list(b.columns):
        return [f"columns differ: {list(a.columns)} vs {list(b.columns)}"]
    if len(a) != len(b):
        return [f"{len(a)} rows vs {len(b)}"]
    out = []
    for c in a.columns:
        x, y = a[c].to_numpy(), b[c].to_numpy()
        if x.dtype.kind == "f" or y.dtype.kind == "f":
            x, y = x.astype(float), y.astype(float)
            nan_x, nan_y = np.isnan(x), np.isnan(y)
            bad = nan_x ^ nan_y
            both = ~nan_x & ~nan_y
            with np.errstate(invalid="ignore"):
                bad |= both & ~(np.abs(x - y) <= atol + rtol * np.maximum(np.abs(x), np.abs(y)))
            bad &= ~(np.isinf(x) & (x == y))
        else:
            bad = x != y
        if bad.any():
            i = int(np.flatnonzero(bad)[0])
            out.append(f"{c}: {int(bad.sum())} rows differ, first at row {i}: {x[i]!r} vs {y[i]!r}")
    return out


def build(dataset: Path, symbols, profile_end, out_root: Path, loader=None, allow_unverified: bool = False,
          expected_digest: str | None = None, say=print) -> Path:
    """Load the dataset (through its importer's loader, which refuses what it must), build the table and write it once under
    `out_root / m1 / <identity>`. An existing folder with the same identity is verified, never rewritten."""
    from . import intake
    loader = loader or intake.load
    bars = loader(Path(dataset), list(symbols), use="regime_research", allow_unverified=allow_unverified, expected_digest=expected_digest)
    attrs = dict(bars.attrs)
    grids = {sym: V.grid(bars[bars["symbol"] == sym]) for sym in symbols}
    table = build_tables(grids, profile_end)
    rec = recipe(symbols, profile_end)
    ident = identity(attrs["digest"], rec)
    folder = Path(out_root) / "m1" / f"{BUILDER_VERSION}-{ident}"
    if folder.exists():
        old = load_table(folder)
        diff = tables_close(old, table)
        if diff:
            raise ImmutableViolation(f"{folder.name} exists and a rebuild from the same inputs differs from it: {diff[:3]}")
        say(f"{folder.name}: already built, verified against a rebuild")
        return folder
    folder.mkdir(parents=True)
    path = folder / "table.parquet"
    table.to_parquet(path, index=False)
    man = {"builder": BUILDER_VERSION, "table": TABLE, "name": folder.name, "recipe": rec,
           "input": {"dataset": attrs.get("dataset"), "digest": attrs["digest"], "status": attrs.get("status"),
                     "tier": attrs.get("tier"), "source": attrs.get("source"), "not_for": attrs.get("not_for"),
                     "excluded_review": attrs.get("excluded_review", []), "admitted_reviewed": attrs.get("admitted_reviewed", [])},
           "rows": {s: int((table["symbol"] == s).sum()) for s in sorted(symbols)},
           "days": {s: [table.loc[table["symbol"] == s, "day"].min(), table.loc[table["symbol"] == s, "day"].max()] for s in sorted(symbols)},
           "scoring_rows": int((~table["in_profile"]).sum()),
           "table_sha256": sha256_file(path),
           "tolerance": {"rtol": 1e-9, "atol": 1e-12, "why": "numpy reductions can differ in the last bit; compare, do not hash, float values"}}
    man["digest"] = manifest_digest(man)
    (folder / "manifest.json").write_text(json.dumps(man, indent=1))
    say(f"{folder.name}: {len(table):,} rows ({man['scoring_rows']:,} outside the profile window), input {attrs['digest'][:16]} ({attrs.get('status')})")
    return folder


def load_table(folder: Path) -> pd.DataFrame:
    """Read a built table back, refusing one that is not what its manifest says: no manifest, a manifest altered after it was
    written, a folder renamed, a file whose bytes changed, or a table that breaks an invariant."""
    folder = Path(folder)
    mp = folder / "manifest.json"
    if not mp.is_file():
        raise ImmutableViolation(f"{folder}: no manifest, so no provenance: refused")
    man = json.loads(mp.read_text())
    if manifest_digest(man) != man.get("digest"):
        raise ImmutableViolation(f"{folder.name}: the manifest does not hash to its own digest: it was altered")
    if folder.name != man["name"] or folder.name != f"{man['builder']}-{identity(man['input']['digest'], man['recipe'])}":
        raise ImmutableViolation(f"{folder.name}: the folder name does not match what the manifest says this table is")
    path = folder / "table.parquet"
    if not path.is_file() or sha256_file(path) != man["table_sha256"]:
        raise ImmutableViolation(f"{folder.name}: table.parquet is missing or no longer hashes to the manifest: the table was altered")
    d = pd.read_parquet(path)
    check_table(d)
    d.attrs.update({"table": man["name"], "input_digest": man["input"]["digest"], "input_status": man["input"]["status"],
                    "profile_end": man["recipe"]["profile_end"], "not_for": man["input"].get("not_for")})
    return d
