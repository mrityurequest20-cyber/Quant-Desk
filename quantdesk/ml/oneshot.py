"""The one-shot out-of-sample evaluation of the locked HAR model: `python -m quantdesk ml oneshot` (docs/prereg/har_oneshot_v1.json, amended by
docs/ml/HAR_ONESHOT_AMENDMENT_1.md). It implements what those two documents state and nothing else.

Every setting comes from the spec; the command takes three paths. The order is the spec's:

  refusals (no look spent) -> preflight (counts, dates and masks only) -> tables -> the control on the spent period (no window row) ->
  THE MARKER (the look is spent here) -> the window is scored -> one atomic write of the result.

Nothing computed from the window is printed or written before the final write: "any number displayed or written spends the look" (looks.crash).
A crash after the marker leaves the marker and no result; the registered crash rule governs what may follow, not this code.

The dataset: the registered route needs `external_verified`. Amendment 1 adds one more: the dataset's verification record must be, byte for byte,
the one P0.6 version 2 wrote (its sha256 is pinned), with its single failed reason, and the dataset digest recomputed from the data on disk must be the
pinned one. On that route the result says `external_unverified` throughout and carries the amendment's mandatory sentence, and never `external_verified`.
There is no flag that accepts any other dataset.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from ..autolearn import volstudy as V
from ..autolearn.prereg import nw_t, spec_hash
from . import build as B
from . import intake as I
from . import splits as S
from . import verify as VF

REPO = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO / "docs" / "prereg" / "har_oneshot_v1.json"
AMENDMENT_PATH = REPO / "docs" / "ml" / "HAR_ONESHOT_AMENDMENT_1.md"
CRITERIA_V2_PATH = REPO / "docs" / "ml" / "P0_6_criteria_v2.md"
ARTIFACT_PATH = REPO / "quantdesk" / "intraday" / "vol_har_v1.json"        # what the desk loads (harvol.DEFAULT_PATH; a test holds them equal, because this package never imports the live engine)
LOCK_RESULT_PATH = REPO / "docs" / "prereg" / "results" / "vol_forecast_v1-f2d4d047ee19.json"
RESULTS_DIR = REPO / "docs" / "prereg" / "results"

SYMBOLS = ("NIFTY", "BANKNIFTY")
SPEC_FILE_SHA256 = "4b06e3b45dee0b5b58d81c53eb6ca6fb9394995c1903c39a797480def6498700"       # the merged spec file's bytes (the hash the amendment quotes)
SPEC_HASH = "f767705e84300419b89ed9d997b465c79b0851410816b4ab4e0b7c4d70cb490e"              # autolearn.prereg.spec_hash: the spec's canonical hash (names the result)
ARTIFACT_SHA256 = "de59c4ab9496e9ae2bc828741686949bf5608a2c4af548ce064afa25b3bef56a"        # quantdesk/intraday/vol_har_v1.json (volshadow.COEF_PIN)
AMENDMENT_SHA256 = "5a20ea8daf64660de8bc48c220aa61d4caf980034c0f9e27feb6cb59ccaba157"       # docs/ml/HAR_ONESHOT_AMENDMENT_1.md as merged
RECORD_SHA256 = "f6288b06893d100605cdcb859e1e29e297aafff40c4efda4eaddcda25d646957"          # the P0.6 version 2 verification.json (amendment 1)
CRITERIA_V2_SHA256 = "508534f5657190f3ca57ee1cd8dd76cbc81aedabcced056a421f9ad7a019b51b"     # docs/ml/P0_6_criteria_v2.md
RECORD_REASON = "BANKNIFTY C: month 2020-03 has 79% agreeing, at least 80% needed"
LOCK_RESULT_FILE = "vol_forecast_v1-f2d4d047ee19.json"

PROFILE_END = "2018-12-31"                      # frozen_model.profile_end: the artifact's dev_end
REFIT_PROFILE_END = "2023-02-28"                # frozen_model.refit_secondary
CONTROL_START, CONTROL_END = "2019-01-01", "2023-02-28"
WINDOW_START, WINDOW_END = "2023-03-01", "2026-05-14"
CONTROL_TOLERANCE = 0.015                       # control.tolerance: stated in the spec before the control was seen
NW_LAGS, ALPHA, GAP_SESSIONS = 5, 0.05, 5
EXPECTED = {"hard_rejects": ["2023-11-12", "2024-11-01", "2025-10-21", "2024-03-02", "2024-05-18", "2026-05-15"],
            "review_queue": ["2024-01-20", "2025-02-01", "2026-02-01"],
            "kept_mondays": ["2025-02-03", "2026-02-02"]}                  # sessions_and_gaps.expected_exclusions_by_date
CELLS = [(s, h) for s in SYMBOLS for h in V.HORIZONS]


class Refused(RuntimeError):
    """The run did not start (or stopped before the marker): no look is spent."""


class ControlFailed(Refused):
    """The control on the spent period failed: the evaluation is not run and no look is spent (control.if_it_fails)."""


@dataclass(frozen=True)
class Pins:
    """What the command pins. The command line never passes one; a test does, to run the same code on a synthetic dataset."""
    spec_file_sha256: str = SPEC_FILE_SHA256
    spec_hash: str = SPEC_HASH
    artifact_sha256: str = ARTIFACT_SHA256
    amendment_sha256: str = AMENDMENT_SHA256
    dataset_digest: str = VF.DATASET_DIGEST
    record_sha256: str = RECORD_SHA256
    criteria_v2_sha256: str = CRITERIA_V2_SHA256
    reason: str = RECORD_REASON
    check: str = VF.CHECK
    control_tolerance: float = CONTROL_TOLERANCE


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_of(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


# ---- refusals ---------------------------------------------------------------------------------------------------------------------
def mandatory_sentence(amendment: Path) -> str:
    """The amendment's mandatory outcome sentence, verbatim (the file is pinned by hash, so this is the text that was reviewed)."""
    text = Path(amendment).read_text()
    m = re.search(r'^## What the result must say[^\n]*\n\n"(The dataset was .*?registration\.)"\s*$', text, re.S | re.M)
    if not m:
        raise Refused(f"{Path(amendment).name}: the mandatory sentence was not found")
    return m.group(1)


def dataset_route(ds: Path, man: dict, pins: Pins) -> tuple[str, dict | None]:
    """('verified', None) on the registered route; ('amendment_1', the record) when the dataset's record is exactly the pinned P0.6 v2 record.
    Anything else is refused. The dataset digest is recomputed from the manifest and then from the partitions by `intake.load` (expected_digest)."""
    if I.dataset_digest(man) != man.get("digest") or man.get("digest") != pins.dataset_digest:
        raise Refused(f"{Path(ds).name}: its digest is not the pinned {pins.dataset_digest[:12]} (recomputed from the manifest)")
    if I.effective_status(ds, man, list(SYMBOLS)) == I.VERIFIED:
        return "verified", None
    vp = Path(ds) / "verification.json"
    try:
        raw = vp.read_bytes()
    except OSError as exc:
        raise Refused(f"{Path(ds).name} is not external_verified and has no verification.json ({exc.__class__.__name__})") from exc
    if sha256_bytes(raw) != pins.record_sha256:
        raise Refused(f"{vp}: not the P0.6 version 2 record that amendment 1 names (sha256 {sha256_bytes(raw)[:12]}, pinned {pins.record_sha256[:12]}): "
                      "a record that was edited, or another one, is refused")
    try:
        rec = json.loads(raw)
    except ValueError as exc:
        raise Refused(f"{vp} is not JSON") from exc
    want = {"check": pins.check, "digest": pins.dataset_digest, "criteria_sha256": pins.criteria_v2_sha256, "passed": False, "symbols_verified": [],
            "reasons": [pins.reason], "post_hoc": True, "supersedes": VF.SUPERSEDES}
    for k, v in want.items():
        if not isinstance(rec, dict) or rec.get(k) != v:
            raise Refused(f"{vp}: field {k!r} is not what amendment 1 pins")
    try:
        ok = all(rec["symbols"][s][c]["passed"] is True for s in SYMBOLS for c in ("A", "B")) and rec["D"]["passed"] is True
    except (KeyError, TypeError):
        ok = False
    if not ok:
        raise Refused(f"{vp}: checks A and B for both symbols and D must be recorded as passed (amendment 1)")
    if man.get("status") != I.UNVERIFIED:
        raise Refused(f"{Path(ds).name}: the manifest says {man.get('status')!r}; this route is for a dataset that stays {I.UNVERIFIED}")
    return "amendment_1", rec


def refuse_unless_ready(ds: Path, spec_path: Path, out: Path, pins: Pins, amendment: Path, criteria: Path, artifact: Path, results_dir: Path,
                        commit: dict | None) -> dict:
    """Every refusal check of command.behaviour, before anything is loaded. Returns what the header records."""
    fsha, h = sha256_of(spec_path), spec_hash(spec_path)
    if fsha != pins.spec_file_sha256 or h != pins.spec_hash:
        raise Refused(f"{Path(spec_path).name} is not the merged spec (file {fsha[:12]}, canonical {h[:12]}; pinned {pins.spec_file_sha256[:12]}, {pins.spec_hash[:12]})")
    if sha256_of(artifact) != pins.artifact_sha256:
        raise Refused(f"{Path(artifact).name} does not hash to the pinned artifact {pins.artifact_sha256[:12]}")
    if sha256_of(amendment) != pins.amendment_sha256:
        raise Refused(f"{Path(amendment).name} does not hash to the merged amendment {pins.amendment_sha256[:12]}")
    if sha256_of(criteria) != pins.criteria_v2_sha256:
        raise Refused(f"{Path(criteria).name} does not hash to the pinned criteria {pins.criteria_v2_sha256[:12]}")
    if commit is None or commit.get("dirty") is not False or not commit.get("commit"):
        raise Refused(f"the code tree is not a clean checkout ({commit}): the run records the commit it ran")
    p = Path(out).resolve()
    for anc in (p, *p.parents):
        if (anc / ".git").exists():
            raise Refused(f"--out {out} is inside a git working tree ({anc}): the result carries third-party-derived numbers and must be written outside")
    if p.exists() and (not p.is_dir() or any(p.iterdir())):
        raise Refused(f"--out {out} must be an empty folder")
    name = json.loads(Path(spec_path).read_text())["name"]
    for suffix in (".json", ".md"):
        if (Path(results_dir) / f"{name}-{h[:12]}{suffix}").exists():
            raise Refused(f"a result for this spec already exists in {results_dir}: the look is spent (looks.rule)")
    man_path = Path(ds) / "manifest.json"
    try:
        man = json.loads(man_path.read_text())
    except (OSError, ValueError) as exc:
        raise Refused(f"{ds}: no readable manifest") from exc
    route, rec = dataset_route(Path(ds), man, pins)
    return {"spec_sha256": h, "spec_file_sha256": fsha, "route": route, "record": rec, "manifest": man, "name": name}


# ---- preflight: counts, dates and masks only --------------------------------------------------------------------------------------
def gap_ordinals(grids: dict) -> dict[str, list[int]]:
    """{symbol: ordinals (in that symbol's grid) of the sessions with no bar at the open}: from the missing mask alone."""
    return {s: [int(i) for i in np.flatnonzero(np.asarray(grids[s][2])[:, 0])] for s in sorted(grids)}


def preflight(grids: dict) -> dict:
    """Counts, dates and masks. No price, return, variance or loss."""
    ws, we = pd.Timestamp(WINDOW_START), pd.Timestamp(WINDOW_END)
    weekdays = [d.date() for d in pd.bdate_range(ws, we)]
    out = {"leading_gap_sessions": {}, "symbols": {}}
    for s in sorted(grids):
        days, _, miss, _ = grids[s]
        dset = {pd.Timestamp(d).date() for d in days}
        in_win = [d for d in days if ws.date() <= pd.Timestamp(d).date() <= we.date()]
        miss = np.asarray(miss)
        win_idx = [i for i, d in enumerate(days) if ws.date() <= pd.Timestamp(d).date() <= we.date()]
        out["leading_gap_sessions"][s] = [str(days[i]) for i in np.flatnonzero(miss[:, 0])]
        by_year = {}
        for d in in_win:
            by_year[str(pd.Timestamp(d).year)] = by_year.get(str(pd.Timestamp(d).year), 0) + 1
        out["symbols"][s] = {
            "sessions_total": len(days), "first": str(days[0]), "last": str(days[-1]), "sessions_in_window": len(in_win), "window_sessions_by_year": by_year,
            "weekdays_without_a_row": [str(d) for d in weekdays if d not in dset],
            "sessions_with_missing_minutes": [{"day": str(days[i]), "missing": int(miss[i].sum())} for i in win_idx if miss[i].any()],
            "expected_absent_but_present": [d for d in EXPECTED["hard_rejects"] + EXPECTED["review_queue"] if dt.date.fromisoformat(d) in dset],
            "expected_present_but_absent": [d for d in EXPECTED["kept_mondays"] if dt.date.fromisoformat(d) not in dset]}
    return out


def drop_leading_gap(table: pd.DataFrame, gaps: dict[str, list[int]]) -> pd.DataFrame:
    """Post-filter on the `session` ordinal: every row of a leading-gap session and of the next GAP_SESSIONS sessions of that symbol's grid is dropped."""
    if not any(gaps.values()):
        return table
    drop = np.zeros(len(table), dtype=bool)
    sym, ses = table["symbol"].to_numpy(), table["session"].to_numpy()
    for s, ords in gaps.items():
        for g in ords:
            drop |= (sym == s) & (ses >= g) & (ses <= g + GAP_SESSIONS)
    return table[~drop].reset_index(drop=True)


# ---- scoring ----------------------------------------------------------------------------------------------------------------------
def with_frozen_forecast(table: pd.DataFrame, artifact: dict) -> pd.DataFrame:
    """The table with F_C, the frozen C_har's forecast: the artifact's per-horizon fit applied to each symbol's rows. Nothing is fitted here."""
    out = table.copy()
    out["F_C"] = np.nan
    for s in SYMBOLS:
        i = (out["symbol"] == s).to_numpy()
        if i.any():
            out.loc[i, "F_C"] = V.predict_c(out.loc[i], artifact["symbols"][s]["fit"])
    return out


def daily(g: pd.DataFrame, col: str) -> pd.Series:
    """Daily QLIKE of forecast column `col` (volstudy.qlike averaged per day over the day's rows)."""
    return pd.Series(V.qlike(g["rv"].to_numpy(float), g[col].to_numpy(float))).groupby(g["day"].to_numpy()).mean()


def dm(a: pd.Series, b: pd.Series, lags: int = NW_LAGS) -> dict:
    """Diebold-Mariano on d_t = loss(a) - loss(b) over the sessions both have; one-sided p = 1 - Phi(t) ('b is better')."""
    d = (a - b).dropna()
    t = nw_t(d.to_numpy(float), lags) if len(d) else float("nan")
    return {"days": int(len(d)), "dm_t": t, "p_one": float(norm.sf(t)) if t == t else float("nan"),
            "gain_pct": float(100 * d.mean() / a.loc[d.index].mean()) if len(d) and a.loc[d.index].mean() else float("nan")}


def holm(p: dict) -> dict:
    """Holm-Bonferroni adjusted p over all of `p` (m = len(p)); a NaN is ranked last, has no adjusted p and so does not pass."""
    m = len(p)
    adj = {k: float("nan") for k in p}
    run = 0.0
    for i, (v, k) in enumerate(sorted((v, k) for k, v in p.items() if v == v)):
        run = max(run, (m - i) * v)
        adj[k] = min(1.0, run)
    return adj


def verdict(cells: dict) -> str:
    """pass_fail: PASS = all 8 pass (Holm-adjusted p < 0.05) and C_har's mean is below A_desk's in each; KILL = four or more cells do not pass, or any
    cell has C_har at or above A_desk; MIXED = anything else."""
    not_passing = sum(not c["passes"] for c in cells.values())
    worse = any(c["mean_C"] >= c["mean_A"] for c in cells.values() if c["mean_C"] == c["mean_C"] and c["mean_A"] == c["mean_A"])
    if not_passing >= 4 or worse:
        return "KILL"
    return "PASS" if not_passing == 0 else "MIXED"


def control(ctrl: pd.DataFrame, locked: dict, tol: float = CONTROL_TOLERANCE) -> dict:
    """control.what / tolerance: in each of the 8 cells, A_desk's and C_har's mean daily QLIKE within `tol` of the committed lock scores, the gain
    (A - C) within `tol` of the locked gain, and C_har below A_desk. `ctrl` has no window row (the caller restricted it)."""
    cells, fails = {}, []
    for s, h in CELLS:
        g = ctrl[(ctrl["symbol"] == s) & (ctrl["horizon"] == h)]
        a, c = float(daily(g, "F_A").mean()), float(daily(g, "F_C").mean())
        sc = locked["lock"]["tests"][f"{s} {h}"]["scores"]
        la, lc = float(sc["A_desk"]["qlike"]), float(sc["C_har"]["qlike"])
        ok = (abs(a - la) <= tol and abs(c - lc) <= tol and abs((a - c) - (la - lc)) <= tol and c < a)
        cells[f"{s} {h}"] = {"A": a, "C": c, "locked_A": la, "locked_C": lc, "ok": bool(ok)}
        if not ok:
            fails.append(f"{s} {h}")
    return {"tolerance": tol, "cells": cells, "failed": fails, "ok": not fails}


def primary(win: pd.DataFrame) -> dict:
    """The 8 cells of the family: C_har against A_desk, Holm over the 8 one-sided p-values, and the verdict."""
    cells = {}
    for s, h in CELLS:
        g = win[(win["symbol"] == s) & (win["horizon"] == h)]
        a, c = daily(g, "F_A"), daily(g, "F_C")
        r = dm(a, c)
        cells[f"{s} {h}"] = {**r, "mean_A": float(a.mean()) if len(a) else float("nan"), "mean_C": float(c.mean()) if len(c) else float("nan"),
                             "mean_B": float(daily(g, "F_B").mean()) if len(g) else float("nan")}
    adj = holm({k: v["p_one"] for k, v in cells.items()})
    for k, v in cells.items():
        v["p_holm"] = adj[k]
        v["passes"] = bool(adj[k] == adj[k] and adj[k] < ALPHA)
    return {"cells": cells, "verdict": verdict(cells)}


def pooled_c_vs_b(win: pd.DataFrame) -> dict:
    """pooled_cb_test: e_t = the mean over the 8 cells of (daily QLIKE of B_seasonal minus that of the frozen C_har) on the dates where all 8 cells have a
    daily loss; one Newey-West t (5 lags), one-sided p, level 0.05, no correction."""
    parts_b, parts_c = {}, {}
    for s, h in CELLS:
        g = win[(win["symbol"] == s) & (win["horizon"] == h)]
        parts_b[f"{s} {h}"], parts_c[f"{s} {h}"] = daily(g, "F_B"), daily(g, "F_C")
    d = pd.DataFrame({k: parts_b[k] - parts_c[k] for k in parts_b})
    all_dates = len(d)
    e = d.dropna(how="any").mean(axis=1)
    t = nw_t(e.to_numpy(float), NW_LAGS) if len(e) else float("nan")
    p = float(norm.sf(t)) if t == t else float("nan")
    return {"dates": int(len(e)), "dates_dropped": int(all_dates - len(e)), "dm_t": t, "p_one": p, "significant": bool(p == p and p < ALPHA),
            "says": ("the HAR layer adds beyond the seasonal profile on this window" if p == p and p < ALPHA else
                     "B_seasonal, which needs no fit, is the cheaper alternative; the HAR layer is not said to add")}


def autocorr(x: np.ndarray, lags=range(1, NW_LAGS + 1)) -> dict:
    x = np.asarray(x, float)
    x = x - x.mean() if len(x) else x
    den = float(x @ x)
    return {str(k): (float(x[k:] @ x[:-k]) / den if den > 0 and len(x) > k else float("nan")) for k in lags}


def secondary(win: pd.DataFrame, refit_f: pd.Series | None) -> dict:
    """secondary_descriptive: reported, never decisive. `refit_f` is the refit's forecast aligned to `win`'s rows (or None)."""
    out = {"cells": {}, "by_year": {}, "time_of_day": {}}
    for s, h in CELLS:
        k = f"{s} {h}"
        g = win[(win["symbol"] == s) & (win["horizon"] == h)]
        a, b, c = daily(g, "F_A"), daily(g, "F_B"), daily(g, "F_C")
        cell = {"C_vs_B": dm(b, c), "B_vs_A": dm(a, b),
                "C_vs_A_lags": {str(L): dm(a, c, L) for L in (10, 20)},
                "daily_gain_autocorr": autocorr((a - c).dropna().to_numpy(float)),
                "qlike": {"A_desk": float(a.mean()) if len(a) else None, "B_seasonal": float(b.mean()) if len(b) else None,
                          "C_har": float(c.mean()) if len(c) else None}}
        if refit_f is not None:
            gg = g.assign(F_R=refit_f.loc[g.index].to_numpy(float))
            r = daily(gg, "F_R")
            cell["refit"] = {"qlike": float(r.mean()) if len(r) else None, "vs_A": dm(a, r), "vs_B": dm(b, r), "vs_frozen_C": dm(c, r)}
        out["cells"][k] = cell
        years = {}
        for y, gy in g.groupby("year"):
            ay, by_, cy = daily(gy, "F_A"), daily(gy, "F_B"), daily(gy, "F_C")
            years[str(y)] = {"A_desk": float(ay.mean()), "B_seasonal": float(by_.mean()), "C_har": float(cy.mean()), "days": int(len(ay)),
                             "gain_pct": float(100 * (ay - cy).mean() / ay.mean()) if ay.mean() else float("nan")}
        out["by_year"][k] = years
        out["time_of_day"][k] = V.score(g) if len(g) else {}
    return out


def refit_forecast(refit_tbl: pd.DataFrame, win_keys: pd.DataFrame, gaps: dict) -> tuple[pd.Series, dict]:
    """The refit secondary: the C_har structure refitted once per symbol on the refit table's in_profile rows (every session up to 2023-02-28), frozen,
    and applied to the window rows. Returns (its forecast aligned to `win_keys`' index, what it fitted). The leakage assertion is `splits.check_test_mask`."""
    t = drop_leading_gap(refit_tbl, gaps).reset_index(drop=True)
    in_prof = t["in_profile"].to_numpy(bool)
    is_win = (t["day"] >= WINDOW_START).to_numpy()
    if (in_prof & is_win).any():
        raise S.LeakError("a window row is marked in_profile in the refit table")
    folds = [S.Fold(train=np.flatnonzero(in_prof), test=np.flatnonzero(~in_prof & is_win), label="refit: train in_profile, score the window")]
    S.check_test_mask(folds, ~in_prof & is_win)
    if np.intersect1d(folds[0].train, folds[0].test).size:
        raise S.LeakError("a scored row is in the refit's training set")
    fits, f = {}, pd.Series(np.nan, index=win_keys.index)
    scored = t.iloc[folds[0].test]
    key = ["symbol", "day", "m", "horizon"]
    for s in SYMBOLS:
        train = t.iloc[folds[0].train]
        fit = V.fit_c(train[train["symbol"] == s])
        fits[s] = fit
        sc = scored[scored["symbol"] == s].copy()
        sc["F_R"] = V.predict_c(sc, fit)
        m = win_keys[win_keys["symbol"] == s][key].merge(sc[key + ["F_R"]], on=key, how="left")
        f.loc[win_keys.index[(win_keys["symbol"] == s).to_numpy()]] = m["F_R"].to_numpy()
    return f, fits


# ---- the run ----------------------------------------------------------------------------------------------------------------------
def _write_once(path: Path, text: str) -> None:
    """Whole file under a private name, linked into place only if absent: a reader never sees half of it and a second write cannot replace it."""
    tmp = Path(f"{path}.{os.getpid()}.tmp")
    tmp.write_text(text)
    try:
        os.link(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def code_state() -> dict:
    """{commit, dirty}: HEAD, and whether anything under quantdesk/ or docs/ differs from it (the code, the specs and the pins it reads)."""
    try:
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "quantdesk", "docs"], capture_output=True, text=True, timeout=20,
                               check=True).stdout.strip()
        return {"commit": head or None, "dirty": bool(dirty)}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def _git_commit_of(path: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(REPO), "log", "-1", "--format=%H", "--", str(path)], capture_output=True, text=True, timeout=20).stdout.strip() or None
    except Exception:
        return None


def run(dataset: Path, spec_path: Path, out: Path, say=print, pins: Pins | None = None, loader=None, amendment: Path | None = None,
        criteria: Path | None = None, artifact: Path | None = None, lock_result: Path | None = None, results_dir: Path | None = None,
        commit: dict | None = None) -> dict:
    """The command. `pins`, `loader` and the path overrides are for tests; the command line passes none of them."""
    pins = pins or Pins()
    amendment, criteria = Path(amendment or AMENDMENT_PATH), Path(criteria or CRITERIA_V2_PATH)
    artifact, lock_result = Path(artifact or ARTIFACT_PATH), Path(lock_result or LOCK_RESULT_PATH)
    results_dir = Path(results_dir or RESULTS_DIR)
    commit = commit if commit is not None else code_state()
    ds, spec_path, out = Path(dataset), Path(spec_path), Path(out)
    info = refuse_unless_ready(ds, spec_path, out, pins, amendment, criteria, artifact, results_dir, commit)
    route, h = info["route"], info["spec_sha256"]
    art = json.loads(artifact.read_text())
    locked = json.loads(lock_result.read_text())
    sentence = mandatory_sentence(amendment) if route == "amendment_1" else None
    out.mkdir(parents=True, exist_ok=True)
    say(f"oneshot: route {route}; spec {h[:12]}; dataset {info['manifest']['digest'][:12]}")

    # -- load and preflight (masks only) ------------------------------------------------------------------------------------------------
    unverified = route == "amendment_1"
    bars = (loader or I.load)(ds, list(SYMBOLS), use="regime_research", allow_unverified=unverified, expected_digest=pins.dataset_digest)
    attrs = dict(bars.attrs)
    grids = {s: V.grid(bars[bars["symbol"] == s]) for s in SYMBOLS}
    pre = preflight(grids)
    gaps = gap_ordinals(grids)
    say("oneshot: preflight " + ("found leading-gap sessions; they and the next 5 are dropped from scoring" if any(gaps.values()) else "found no leading-gap session"))

    # -- tables (the window rows are read only through load_table(reserved_spec=<this spec>)) --------------------------------------------
    profile = {s: art["symbols"][s]["profile"] for s in SYMBOLS}
    root = out / "tables"
    kw = dict(loader=loader, allow_unverified=unverified, expected_digest=pins.dataset_digest, say=lambda *_: None)
    gap_ok = any(gaps.values())
    f1 = B.build(ds, list(SYMBOLS), PROFILE_END, root, profile=profile, allow_leading_gap=gap_ok, **kw)
    f2 = B.build(ds, list(SYMBOLS), REFIT_PROFILE_END, root, allow_leading_gap=gap_ok, **kw)
    lt = dict(allow_unverified=unverified, reserved_spec=spec_path, dataset=None if loader else ds)
    raw = drop_leading_gap(B.load_table(f1, scoring_only=True, **lt), gaps)
    refit_all = B.load_table(f2, scoring_only=False, **lt)

    # -- the control: restricted to the spent period before it scores anything; no window row gets a forecast, let alone a score -------------
    ctrl = with_frozen_forecast(raw[(raw["day"] >= CONTROL_START) & (raw["day"] <= CONTROL_END)].reset_index(drop=True), art)
    ctl = control(ctrl, locked, pins.control_tolerance)
    if not ctl["ok"]:
        raise ControlFailed(f"the control failed in {ctl['failed']}: the evaluation is not run and no look is spent")
    say("oneshot: control passed")

    # -- THE MARKER: the look is spent here ---------------------------------------------------------------------------------------------
    opened = pd.Timestamp.now(tz=I.IST).isoformat()
    header = {"spec": info["name"], "spec_sha256": h, "spec_file_sha256": info["spec_file_sha256"], "route": route, "code_commit": commit["commit"], "dataset": attrs.get("dataset"),
              "dataset_digest": attrs.get("digest"), "dataset_status": attrs.get("status"), "dataset_tier": attrs.get("tier"),
              "artifact_sha256": pins.artifact_sha256, "tables": {"primary": f1.name, "refit": f2.name},
              "amendment_sha256": pins.amendment_sha256, "amendment_commit": _git_commit_of(amendment), "criteria_v2_sha256": pins.criteria_v2_sha256,
              "record_sha256": pins.record_sha256 if route == "amendment_1" else None, "opened": opened}
    stem = f"{info['name']}-{h[:12]}"
    _write_once(out / f"{stem}.marker.json", json.dumps(header, indent=1))
    say("oneshot: the marker is written; the look is spent")

    # -- the window ---------------------------------------------------------------------------------------------------------------------
    win = with_frozen_forecast(raw[(raw["day"] >= WINDOW_START) & (raw["day"] <= WINDOW_END)].reset_index(drop=True), art)
    prim = primary(win)
    pooled = pooled_c_vs_b(win)
    refit_f, refit_fits = refit_forecast(refit_all, win, gaps)
    sec = secondary(win, refit_f)
    acct = B.accounting(grids, raw)
    result = {**header, "evidence": ("external_unverified" if route == "amendment_1" else "external_verified (underlying only)"),
              "caveat": sentence, "not_for": json.loads(spec_path.read_text())["not_for"], "control": ctl, "preflight": pre,
              "leading_gap_sessions_dropped": {s: gaps[s] for s in gaps if gaps[s]},
              "primary": prim, "pooled_c_vs_b": pooled, "secondary": sec, "refit": {"fits": refit_fits, "profile_end": REFIT_PROFILE_END},
              "frozen": {"profile": profile, "fit": {s: art["symbols"][s]["fit"] for s in SYMBOLS}},
              "accounting": acct, "rows_by_symbol_year": {f"{s} {y}": int(n) for (s, y), n in win.groupby(["symbol", "year"]).size().items()},
              "verdict": prim["verdict"]}
    _write_once(out / f"{stem}.json", json.dumps(result, indent=1, default=str))
    _write_once(out / f"{stem}.md", render(result))
    return result


def rehearse_control(dataset: Path, out: Path, say=print, pins: Pins | None = None, loader=None, artifact: Path | None = None,
                     lock_result: Path | None = None) -> dict:
    """The spent-period rehearsal (controls_before_the_run: "rehearse the whole command on a synthetic dataset and on the spent period"). It runs the
    command's own machinery up to and including the control, on the real dataset, and stops: no marker, no result. No window row is built, read or
    scored: the bars are cut at CONTROL_END straight after the load (before any grid), and the table is read WITHOUT the reserved spec, so the loader
    itself withholds the reserved window. What it returns is about the spent period only (the same control the run will make). Written under `out`
    (outside every git tree) and discarded; it is not an evaluation and spends no look."""
    pins = pins or Pins()
    artifact, lock_result = Path(artifact or ARTIFACT_PATH), Path(lock_result or LOCK_RESULT_PATH)
    ds, out = Path(dataset), Path(out)
    p = out.resolve()
    for anc in (p, *p.parents):
        if (anc / ".git").exists():
            raise Refused(f"--out {out} is inside a git working tree ({anc})")
    if p.exists() and (not p.is_dir() or any(p.iterdir())):
        raise Refused(f"--out {out} must be an empty folder")
    if sha256_of(artifact) != pins.artifact_sha256:
        raise Refused(f"{artifact.name} does not hash to the pinned artifact")
    man = json.loads((ds / "manifest.json").read_text())
    route, _ = dataset_route(ds, man, pins)
    art, locked = json.loads(artifact.read_text()), json.loads(lock_result.read_text())
    inner = loader or I.load
    cut = pd.Timestamp(WINDOW_START, tz=I.IST)

    def spent_only(*args, **kw):
        bars = inner(*args, **kw)
        keep = pd.to_datetime(bars["ts"]).dt.tz_convert(I.IST) < cut if "ts" in bars.columns else pd.DatetimeIndex(bars.index) < cut
        res = bars[np.asarray(keep)].reset_index(drop=True)
        res.attrs.update(bars.attrs)
        return res
    out.mkdir(parents=True, exist_ok=True)
    unverified = route == "amendment_1"
    grids = {s: V.grid(spent_only(ds, list(SYMBOLS), use="regime_research", allow_unverified=unverified, expected_digest=pins.dataset_digest)
                       .pipe(lambda b, s=s: b[b["symbol"] == s])) for s in SYMBOLS}
    gaps = gap_ordinals(grids)
    profile = {s: art["symbols"][s]["profile"] for s in SYMBOLS}
    f1 = B.build(ds, list(SYMBOLS), PROFILE_END, out / "tables", loader=spent_only, allow_unverified=unverified, expected_digest=pins.dataset_digest,
                 say=lambda *_: None, profile=profile, allow_leading_gap=any(gaps.values()))
    tbl = drop_leading_gap(B.load_table(f1, scoring_only=True, allow_unverified=unverified, dataset=None if loader else ds), gaps)
    if (tbl["day"] >= WINDOW_START).any():
        raise Refused("a window row reached the rehearsal table: stopped")
    ctrl = tbl[(tbl["day"] >= CONTROL_START) & (tbl["day"] <= CONTROL_END)].reset_index(drop=True)
    ctl = control(with_frozen_forecast(ctrl, art), locked, pins.control_tolerance)
    say(f"rehearsal: control {'passed' if ctl['ok'] else 'FAILED in ' + str(ctl['failed'])} on the spent period; {len(ctrl):,} rows, last day {ctrl['day'].max()}")
    return {"control": ctl, "route": route, "leading_gap_sessions": {s: gaps[s] for s in gaps if gaps[s]}, "table": f1.name, "rows": int(len(ctrl)),
            "last_day": str(ctrl["day"].max())}


def render(r: dict) -> str:
    """The result as text. The header carries the label and, on the amendment route, the mandatory sentence in full."""
    L = [f"# {r['spec']} - one-shot evaluation: {r['verdict']}", ""]
    if r["caveat"]:
        L += [f"> {r['caveat']}", ""]
    L += [f"Evidence label: **{r['evidence']}**. Opened {r['opened']}. Spec sha256 `{r['spec_sha256']}` (autolearn.prereg.spec_hash; file `{r['spec_file_sha256']}`), code commit `{r['code_commit']}`.",
          f"Dataset `{r['dataset']}` (digest `{r['dataset_digest']}`, status {r['dataset_status']}, tier {r['dataset_tier']}); artifact sha256 `{r['artifact_sha256']}`; "
          f"tables `{r['tables']['primary']}` and `{r['tables']['refit']}`; amendment sha256 `{r['amendment_sha256']}` (commit `{r['amendment_commit']}`); "
          f"criteria v2 sha256 `{r['criteria_v2_sha256']}`; record sha256 `{r['record_sha256']}`.", "",
          "| cell | days | mean A | mean B | mean C | gain % | DM t | p | Holm p | passes |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, c in r["primary"]["cells"].items():
        L.append(f"| {k} | {c['days']} | {c['mean_A']:.4f} | {c['mean_B']:.4f} | {c['mean_C']:.4f} | {c['gain_pct']:+.1f} | {c['dm_t']:+.2f} | "
                 f"{c['p_one']:.3g} | {c['p_holm']:.3g} | {'yes' if c['passes'] else 'no'} |")
    p = r["pooled_c_vs_b"]
    L += ["", f"Pooled C versus B: {p['dates']} dates ({p['dates_dropped']} dropped), t {p['dm_t']:+.2f}, one-sided p {p['p_one']:.3g}: {p['says']}.",
          "", f"Control (spent period): {'passed' if r['control']['ok'] else 'FAILED'} within {r['control']['tolerance']} in every cell.",
          f"Leading-gap sessions dropped from scoring: {r['leading_gap_sessions_dropped'] or 'none'}.",
          f"Weekdays without a row are listed in the JSON preflight; the exchange-holiday check is the steward's (docs/EXTERNAL_DATA.md item 13), not repeated by this run.",
          "", "Everything else (secondary tables, accounting, the frozen coefficients) is in the JSON file beside this one.", ""]
    return "\n".join(L)
