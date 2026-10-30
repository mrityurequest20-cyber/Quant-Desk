"""The dataset builder (P0.3 of docs/ML_PHASE0.md): point-in-time tables for M1 (the size of the next move), built by the study's own code.

One row is a (symbol, day, decision minute, horizon): the features known at the decision, and the labels over the next 30m / 60m /
120m / to the close, which never reach past the session. The code is `autolearn/volstudy` (`grid`, `profile`, `rows`), called, not
copied, so the table the harness trains on is the table the locked HAR result was computed from.

**The seasonal profile is a fit.** `F_B` and `x_today` divide by the minute-of-day variance profile, and a profile fitted on the whole
sample would leak the test period into every feature. The builder therefore takes `profile_end`, fits the profile on sessions up to
and including that day only (as `volstudy.fit_har` does for a training window), records it in the table's identity, and marks every
row with `in_profile`. Score only rows with `in_profile == False`; a study that needs the profile refitted per fold rebuilds the
table per fold, which is cheap. A model's own frozen profile can be supplied instead (`profile={symbol: values}`): nothing is fitted on the grid then,
`profile_end` is the last session that profile was fitted on (it still marks `in_profile`), and the profile's sha256 enters the recipe, hence the identity.

**Identity.** The table's folder is `ml-build-1-<12 hex>`, the hash of the input dataset's digest **and its status and tier**, the recipe
(symbols, profile_end, every constant and the source of the functions that make the rows) and the builder version. The same inputs give
the same identity anywhere; a table built from an unverified dataset cannot be relabelled verified by editing its manifest, because the
status is part of the name the manifest must hash to (a rebuild after verification is a new table). That makes a casual edit of the manifest,
its digest or the status alone detectable; it is tamper-evident, not tamper-proof: someone with write access to the table folder who also renames
the folder, rewrites the file's metadata and recomputes both hashes can still relabel a table, unless the caller passes `dataset=` to `load_table`, which
re-derives the status from the dataset's own verification record (`intake.effective_status`). The status and the restriction
(`not_for`) are also written into the parquet file's own metadata, so a copy of the file still says what it is. The *values* are floats from numpy reductions that can change in the last bit with memory alignment, so a
hash of values is not an identity: the stored file is pinned by the sha256 of its bytes (it detects any change to what was
written), and a rebuild is compared with `tables_close` at a stated tolerance (default 1e-9; measured 0 on this machine).

**What the table does not hide.** Three things in it depend on the future by construction, and a consumer must know them: (1) rows with
`in_profile` True have a seasonal profile fitted on days after them (`load_table` withholds them by default); (2) `miss_frac` is the share
of the *label* window's minutes that were missing, so it is future information (it is a filter, never a feature); (3) whether a row exists at
all depends on that same mask (`volstudy.rows` drops windows more than 20% missing). Sessions are also lost silently by the study's own rules (the
first five sessions of a series, and five after any break longer than four days); the manifest counts them.

**Reserved window.** Rows from `RESERVED_FROM` (1 Mar 2023) onward are the stretch kept for the one-shot, pre-registered out-of-sample evaluation of the
locked HAR model (ML_PHASE0.md). `load_table` withholds them unless a spec is named; that is a guard against accident, not against intent.

Offline and read-only: the ml modules' own imports do not reach the engine, the journal, risk or execution (the command line process, which
builds every subcommand's parser, imports the whole desk; nothing in it is run).
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
from ..data.external_aeron import ALLOWED_USES, FORBIDDEN_NOTE, ForbiddenUse, ImmutableViolation
from .intake import VERIFIED

REPO = Path(__file__).resolve().parents[2]
BUILDER_VERSION = "ml-build-1"
TABLE = "m1_move_size"
MIN_PROFILE_DAYS = 250                                       # a minute-of-day profile from fewer sessions is mostly noise
FEATURE_LOOKBACK_SESSIONS = V.PRIOR_DAYS                     # x_prev5 and the A / B priors read this many earlier sessions of the grid
RESERVED_FROM = "2023-03-01"                                 # the one-shot evaluation window starts here (ML_PHASE0.md, T1b)
IST = "Asia/Kolkata"
COLUMNS = ["symbol", "day", "session", "year", "m", "horizon", "minutes", "rv", "ret", "miss_frac", "F_A", "F_B",
           "x_prev", "x_prev5", "x_today", "x_gap", "lF_B", "tier", "in_profile"]
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


def profile_sha256(profile: dict) -> str:
    """The identity of a supplied seasonal profile ({symbol: the N_MIN values}): it goes into the recipe, so a table built with one is a different table."""
    return hashlib.sha256(json.dumps({s: [float(x) for x in profile[s]] for s in sorted(profile)}, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def recipe(symbols, profile_end, profile: dict | None = None) -> dict:
    rec = {"table": TABLE, "symbols": sorted(symbols), "profile_end": str(profile_end), "columns": COLUMNS,
           "constants": {"N_MIN": V.N_MIN, "DECISIONS": V.DECISIONS, "HORIZONS": V.HORIZONS, "LAM": V.LAM,
                         "PRIOR_DAYS": V.PRIOR_DAYS, "FLOOR": V.FLOOR, "MIN_PROFILE_DAYS": MIN_PROFILE_DAYS},
           "code_sha256": _code_digest()}
    if profile is not None:                                              # absent otherwise: every table built before this argument keeps its name
        rec["profile_sha256"] = profile_sha256(profile)
    return rec


def refuse_tracked_tree(path: Path, what: str) -> None:
    """Tables derived from third-party data must not be written where they could be committed: refuse any folder inside a git working tree
    (this repository, another clone, a worktree) unless it is under that tree's gitignored `runtime/` folder."""
    p = Path(path).resolve()
    for anc in (p, *p.parents):
        if (anc / ".git").exists():
            if (anc / "runtime") in (p, *p.parents):
                return
            raise ForbiddenUse(f"{what} {path} is inside a git working tree ({anc}) outside its runtime/ folder: a table derived from third-party "
                               "data must not be written where it could be committed")


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(input_digest: str, rec: dict, status: str, tier) -> str:
    """The table's name: what it was built from (the dataset, and the status and tier it had), how, and by which builder."""
    return hashlib.sha256(_canon({"builder": BUILDER_VERSION, "input": {"digest": input_digest, "status": status, "tier": tier},
                                  "recipe": rec}).encode()).hexdigest()[:12]


def manifest_digest(man: dict) -> str:
    return hashlib.sha256(_canon({k: v for k, v in man.items() if k != "digest"}).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


META_STATUS, META_NOT_FOR = b"quantdesk.input_status", b"quantdesk.not_for"


def _write_parquet(table: pd.DataFrame, path: Path, status: str, not_for: str) -> None:
    """Write the table with its input's status and restriction in the file's own key-value metadata."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    t = pa.Table.from_pandas(table, preserve_index=False)
    t = t.replace_schema_metadata({**(t.schema.metadata or {}), META_STATUS: str(status).encode(), META_NOT_FOR: str(not_for).encode()})
    pq.write_table(t, path)


def _read_meta(path: Path) -> dict:
    import pyarrow.parquet as pq
    md = pq.read_schema(path).metadata or {}
    return {"status": md.get(META_STATUS, b"").decode(), "not_for": md.get(META_NOT_FOR, b"").decode()}


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
    if d["session"].dtype.kind not in "iu" or (d["session"] < 0).any():
        raise TableError("session must be a non-negative integer (the day's ordinal in the feature builder's calendar)")
    if (d.groupby(["symbol", "day"])["session"].nunique() != 1).any():
        raise TableError("one day carries more than one session ordinal")
    if not d["tier"].map(lambda t: isinstance(t, str) and bool(t.strip())).all():
        raise TableError("a row without a tier: every row says which data tier it came from")
    order = list(zip(d["symbol"], d["day"], d["m"], d["horizon"].map(_HORIZON_ORDER)))
    if order != sorted(order):
        raise TableError("rows are not in (symbol, day, decision, horizon) order")
    if not d.groupby("symbol")["session"].apply(lambda x: x.is_monotonic_increasing).all():
        raise TableError("session ordinals do not increase with the day")


def _as_date(x):
    import datetime as dt
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x))


def fit_profile(grid: tuple, profile_end) -> np.ndarray:
    """The minute-of-day variance profile fitted on the sessions of `grid` (the output of `volstudy.grid`) up to and including `profile_end`: the
    builder's one fit, exposed so a reproduction can compare it."""
    days, r, _, _ = grid
    pe = _as_date(profile_end)
    train = np.array([d <= pe for d in days])
    if int(train.sum()) < MIN_PROFILE_DAYS:
        raise ValueError(f"only {int(train.sum())} sessions up to {pe}; a seasonal profile needs {MIN_PROFILE_DAYS}")
    return V.profile((r ** 2)[train])


def build_tables(grids: dict, profile_end, tier: str, allow_leading_gap: bool = False, allow_reserved_profile: bool = False,
                 profile: dict | None = None) -> pd.DataFrame:
    """{symbol: (days, r, missing, opens)} (the output of `volstudy.grid`) -> the M1 table. The minute-of-day profile is fitted on the
    sessions up to and including `profile_end` only. `tier` is the data tier every row came from (ML_PHASE0.md rule 2). A session whose first
    minute is missing is refused: `volstudy.grid` back-fills its opening bars from a later close, which would put the future into the first
    features. `allow_leading_gap=True` is for reproducing a result that was computed that way (the locked HAR study's aeron7 data has such
    sessions); the caller must then report them (`leading_gap_sessions`). A `profile_end` inside the reserved window (from `RESERVED_FROM`) is
    refused: the profile would be fitted on the stretch kept for the one-shot evaluation and every row after it would be contaminated;
    `allow_reserved_profile=True` is for that evaluation's own spec. `profile={symbol: the N_MIN values}` replaces `fit_profile` for every symbol
    (a model's own, frozen profile; nothing is fitted on the grid, so `MIN_PROFILE_DAYS` does not apply); `in_profile` still marks the sessions up to
    `profile_end`, the last session that profile was fitted on. Each row's `session` is its day's ordinal in the symbol's grid, the calendar
    the features' lookback is counted in. Pure: no I/O, no clock, no randomness."""
    if not isinstance(tier, str) or not tier.strip():
        raise ValueError("tier must name the data tier the rows came from (T1, T1b, ...)")
    pe = _as_date(profile_end)
    if str(pe) >= RESERVED_FROM and not allow_reserved_profile:
        raise ValueError(f"profile_end {pe} is inside the reserved window (from {RESERVED_FROM}): the seasonal profile would be fitted on the stretch "
                         "kept for the one-shot evaluation")
    parts = []
    for sym in sorted(grids):
        days, r, miss, opens = grids[sym]
        lead = np.flatnonzero(np.asarray(miss)[:, 0])
        if len(lead) and not allow_leading_gap:
            raise ValueError(f"{sym}: {len(lead)} sessions have no bar at the open (first {days[lead[0]]}); the grid would fill them from a later close")
        if profile is not None:
            s = _supplied_profile(profile, sym)
        else:
            try:
                s = fit_profile(grids[sym], pe)
            except ValueError as exc:
                raise ValueError(f"{sym}: {exc}") from exc
        d = V.rows(sym, days, r, miss, opens, s)
        d["lF_B"] = np.log(np.maximum(d["F_B"], V.FLOOR))
        d["in_profile"] = (pd.Index(d["day"]) <= pe)
        d["session"] = pd.Index(days).get_indexer(d["day"]).astype("int64")
        d["day"] = pd.Index(d["day"]).map(str)
        d["tier"] = tier
        parts.append(d)
    out = pd.concat(parts, ignore_index=True)[COLUMNS]
    out["in_profile"] = out["in_profile"].astype(bool)
    out["_h"] = out["horizon"].map(_HORIZON_ORDER)
    out = out.sort_values(["symbol", "day", "m", "_h"], kind="stable").drop(columns="_h").reset_index(drop=True)
    check_table(out)
    return out


def _supplied_profile(profile: dict, sym: str) -> np.ndarray:
    """A supplied profile for `sym`, or a refusal: it must be there, N_MIN finite positive numbers."""
    if sym not in profile:
        raise ValueError(f"{sym}: the supplied profile has no entry for it")
    s = np.asarray(profile[sym], dtype=float)
    if s.shape != (V.N_MIN,) or not np.isfinite(s).all() or (s <= 0).any():
        raise ValueError(f"{sym}: the supplied profile must be {V.N_MIN} finite positive numbers")
    return s


def leading_gap_sessions(grids: dict) -> dict:
    """{symbol: [sessions with no bar at the open]}: the sessions `volstudy.grid` fills from a later close."""
    return {sym: [str(g[0][i]) for i in np.flatnonzero(np.asarray(g[2])[:, 0])] for sym, g in sorted(grids.items())}


def t0_t1(table: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Each row's decision time and the time its label ends, as int64 nanoseconds UTC, for `splits`: t0 is the session open plus the decision
    minute, t1 is t0 plus the label window. The features reach `FEATURE_LOOKBACK_SESSIONS` sessions back, which a time embargo cannot express (holidays
    and dropped sessions stretch five sessions over up to 19 calendar days and more): use `cpcv_for`, or pass the `session` column to `splits.cpcv`."""
    open_ = pd.to_datetime(table["day"]).dt.tz_localize(IST) + pd.Timedelta(hours=9, minutes=15)
    t0 = open_ + pd.to_timedelta(table["m"].to_numpy(), unit="min")
    t1 = t0 + pd.to_timedelta(table["minutes"].to_numpy(), unit="min")
    ns = lambda x: pd.DatetimeIndex(x).tz_convert("UTC").as_unit("ns").asi8.astype("int64")
    return ns(t0), ns(t1)


def cpcv_for(table: pd.DataFrame, n_groups: int, n_test: int):
    """Combinatorial purged CV on one symbol of the M1 table with the purge its features need: label overlap, and every training sample whose
    feature window (this session up to its decision and the `FEATURE_LOOKBACK_SESSIONS` before it) contains a test session."""
    from . import splits as S
    if table["symbol"].nunique() != 1:
        raise ValueError("cpcv_for takes one symbol at a time: each symbol has its own calendar of sessions")
    t0, t1 = t0_t1(table)
    return S.cpcv(t0, t1, n_groups, n_test, embargo=0, session=table["session"].to_numpy(), lookback_sessions=FEATURE_LOOKBACK_SESSIONS)


def accounting(grids: dict, table: pd.DataFrame) -> dict:
    """What the study's own rules left out, per symbol: sessions in the grid, sessions with at least one row, the rows that were possible
    (every decision and horizon whose window ends inside the session) and the rows kept, and the sessions lost (listed up to 60)."""
    per_session = sum(1 for m in V.DECISIONS for h, mins in V.HORIZONS.items() if (V.N_MIN if mins is None else m + mins) <= V.N_MIN)
    out = {}
    for sym in sorted(grids):
        days = [str(d) for d in grids[sym][0]]
        have = set(table.loc[table["symbol"] == sym, "day"])
        lost = [d for d in days if d not in have]
        n = int((table["symbol"] == sym).sum())
        out[sym] = {"sessions_in_grid": len(days), "sessions_with_rows": len(days) - len(lost), "sessions_lost": len(lost), "lost_first": lost[:60],
                    "rows_possible": len(days) * per_session, "rows_kept": n, "rows_dropped": len(days) * per_session - n}
    return out


def tables_close(a: pd.DataFrame, b: pd.DataFrame, rtol: float = 1e-9) -> list[str]:
    """Differences between two tables beyond the tolerance (an empty list means they match). Keys, integers, strings and booleans must be
    equal; floats within `rtol * max(|a|, |b|, scale)`, where `scale` is the column's median magnitude (so rounding noise on a value near zero is
    measured against what the column typically holds, and a drift of 1e-7 on a column of 1e-6 values is not hidden by an absolute allowance);
    a NaN matches only a NaN, an infinity only itself."""
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
            both = ~nan_x & ~nan_y & np.isfinite(x) & np.isfinite(y)
            mag = np.abs(x[np.isfinite(x)])
            scale = float(np.median(mag)) if len(mag) else 0.0
            with np.errstate(invalid="ignore"):
                bad |= both & ~(np.abs(x - y) <= rtol * np.maximum(np.maximum(np.abs(x), np.abs(y)), scale))
            bad |= (np.isinf(x) | np.isinf(y)) & ~(x == y)
        else:
            bad = x != y
        if bad.any():
            i = int(np.flatnonzero(bad)[0])
            out.append(f"{c}: {int(bad.sum())} rows differ, first at row {i}: {x[i]!r} vs {y[i]!r}")
    return out


def build(dataset: Path, symbols, profile_end, out_root: Path, loader=None, allow_unverified: bool = False,
          expected_digest: str | None = None, say=print, profile: dict | None = None, allow_leading_gap: bool = False) -> Path:
    """Load the dataset (through its importer's loader, which refuses what it must), build the table and write it once under
    `out_root / m1 / <identity>`. An existing folder with the same identity is verified, never rewritten. `loader` is a test hook: the
    command line never passes one, and a loader of one's own is not covered by the importer's checks."""
    from . import intake
    refuse_tracked_tree(out_root, "the tables folder")
    loader = loader or intake.load
    bars = loader(Path(dataset), list(symbols), use="regime_research", allow_unverified=allow_unverified, expected_digest=expected_digest)
    attrs = dict(bars.attrs)
    tier = attrs.get("tier")
    tier = tier if isinstance(tier, str) else "+".join(map(str, tier or ["unknown"]))
    grids = {sym: V.grid(bars[bars["symbol"] == sym]) for sym in symbols}
    table = build_tables(grids, profile_end, tier, allow_leading_gap=allow_leading_gap, profile=profile)
    rec = recipe(symbols, profile_end, profile)
    ident = identity(attrs["digest"], rec, attrs.get("status"), attrs.get("tier"))
    folder = Path(out_root) / "m1" / f"{BUILDER_VERSION}-{ident}"
    if folder.exists():
        old, _ = _read_checked(folder)
        diff = tables_close(old, table)
        if diff:
            raise ImmutableViolation(f"{folder.name} exists and a rebuild from the same inputs differs from it: {diff[:3]}")
        say(f"{folder.name}: already built, verified against a rebuild")
        return folder
    folder.mkdir(parents=True)
    path = folder / "table.parquet"
    _write_parquet(table, path, attrs.get("status"), attrs.get("not_for") or FORBIDDEN_NOTE)
    man = {"builder": BUILDER_VERSION, "table": TABLE, "name": folder.name, "recipe": rec,
           "input": {"dataset": attrs.get("dataset"), "digest": attrs["digest"], "status": attrs.get("status"),
                     "tier": attrs.get("tier"), "source": attrs.get("source"), "not_for": attrs.get("not_for"),
                     "excluded_review": attrs.get("excluded_review", []), "admitted_reviewed": attrs.get("admitted_reviewed", [])},
           "rows": {s: int((table["symbol"] == s).sum()) for s in sorted(symbols)},
           "days": {s: [table.loc[table["symbol"] == s, "day"].min(), table.loc[table["symbol"] == s, "day"].max()] for s in sorted(symbols)},
           "accounting": accounting(grids, table),
           "scoring_rows": int((~table["in_profile"]).sum()),
           "reserved_from": RESERVED_FROM, "reserved_rows": int((table["day"] >= RESERVED_FROM).sum()),
           "feature_lookback_sessions": FEATURE_LOOKBACK_SESSIONS,
           "table_sha256": sha256_file(path),
           "tolerance": {"rtol": 1e-9, "scale": "the column's median magnitude",
                         "why": "numpy reductions can differ in the last bit; compare, do not hash, float values"}}
    man["digest"] = manifest_digest(man)
    (folder / "manifest.json").write_text(json.dumps(man, indent=1))
    say(f"{folder.name}: {len(table):,} rows ({man['scoring_rows']:,} outside the profile window, {man['reserved_rows']:,} in the reserved window), "
        f"input {attrs['digest'][:16]} ({attrs.get('status')})")
    return folder


def _read_checked(folder: Path) -> tuple[pd.DataFrame, dict]:
    """The table exactly as written, after every integrity check: no manifest, a manifest altered after it was written (the status and tier
    are part of the name it must hash to), a renamed folder, a file whose bytes changed, a file whose own metadata disagrees with the manifest,
    a table that breaks an invariant. No gate on use, status or window: `load_table` adds those."""
    folder = Path(folder)
    mp = folder / "manifest.json"
    if not mp.is_file():
        raise ImmutableViolation(f"{folder}: no manifest, so no provenance: refused")
    man = json.loads(mp.read_text())
    if manifest_digest(man) != man.get("digest"):
        raise ImmutableViolation(f"{folder.name}: the manifest does not hash to its own digest: it was altered")
    inp = man["input"]
    if folder.name != man["name"] or folder.name != f"{man['builder']}-{identity(inp['digest'], man['recipe'], inp.get('status'), inp.get('tier'))}":
        raise ImmutableViolation(f"{folder.name}: the folder name does not match what the manifest says this table is")
    path = folder / "table.parquet"
    if not path.is_file() or sha256_file(path) != man["table_sha256"]:
        raise ImmutableViolation(f"{folder.name}: table.parquet is missing or no longer hashes to the manifest: the table was altered")
    meta = _read_meta(path)
    if meta["status"] != str(inp.get("status")):
        raise ImmutableViolation(f"{folder.name}: the file's own metadata disagrees with the manifest about the status")
    if meta["not_for"] != str(inp.get("not_for") or FORBIDDEN_NOTE):
        raise ImmutableViolation(f"{folder.name}: the file's own metadata disagrees with the manifest about the restriction")
    d = pd.read_parquet(path)
    check_table(d)
    return d, man


def load_table(folder: Path, use: str = "regime_research", allow_unverified: bool = False, scoring_only: bool = True,
               reserved_spec: Path | None = None, dataset: Path | None = None) -> pd.DataFrame:
    """Read a built table back for a declared use. Refused: a use outside the dataset's `ALLOWED_USES`; a table built from data that is not
    `external_verified` unless the caller says it accepts that (as `intake.load` does); anything `_read_checked` refuses. By default the rows
    a study must not score are withheld: those whose seasonal profile was fitted on later days (`scoring_only`), and those in the reserved
    window from `RESERVED_FROM`, unless `reserved_spec` names the pre-registered spec that reads them (recorded in `attrs`). With `dataset=`
    the table's status is re-derived from that dataset's own manifest and verification record: a different dataset, or one whose status has changed
    since the table was built (verified since, or no longer), is refused and the table must be rebuilt."""
    if use not in ALLOWED_USES:
        raise ForbiddenUse(f"use {use!r} refused: {FORBIDDEN_NOTE}")
    d, man = _read_checked(folder)
    inp = man["input"]
    if dataset is not None:
        from .intake import effective_status
        try:
            dm = json.loads((Path(dataset) / "manifest.json").read_text())
        except (OSError, ValueError) as exc:
            raise ImmutableViolation(f"{dataset}: no readable manifest to check {man['name']} against") from exc
        if dm.get("digest") != inp["digest"]:
            raise ImmutableViolation(f"{man['name']} was not built from {Path(dataset).name} (digest {str(dm.get('digest'))[:12]} ≠ {inp['digest'][:12]})")
        now = effective_status(Path(dataset), dm, man["recipe"]["symbols"])
        if now != inp.get("status"):
            raise ImmutableViolation(f"{man['name']} says {inp.get('status')} but the dataset is {now} now: rebuild the table")
    if inp.get("status") != VERIFIED and not allow_unverified:
        raise ForbiddenUse(f"{man['name']} was built from {inp.get('status')} data: run the verification and rebuild, or pass allow_unverified=True "
                           "and label the results as unverified")
    spec_name = None
    if reserved_spec is not None:
        try:
            spec = json.loads(Path(reserved_spec).read_text())
            spec_name = str(spec["name"]).strip()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ForbiddenUse(f"reserved_spec {reserved_spec} is not a readable spec with a name: the reserved window stays withheld") from exc
        if not spec_name:
            raise ForbiddenUse("reserved_spec has an empty name: the reserved window stays withheld")
    withheld = {"in_profile": 0, "reserved": 0}
    if scoring_only:
        withheld["in_profile"] = int(d["in_profile"].sum())
        d = d[~d["in_profile"]]
    if spec_name is None:
        res = d["day"] >= RESERVED_FROM
        withheld["reserved"] = int(res.sum())
        d = d[~res]
    d = d.reset_index(drop=True)
    d.attrs.update({"table": man["name"], "input_digest": inp["digest"], "input_status": inp.get("status"), "profile_end": man["recipe"]["profile_end"],
                    "not_for": inp.get("not_for") or FORBIDDEN_NOTE, "use": use, "withheld": withheld, "reserved_spec": spec_name,
                    "scoring_only": scoring_only})
    return d
