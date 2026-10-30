"""The one-shot out-of-sample evaluation of the locked HAR model: `python -m quantdesk ml oneshot` (docs/prereg/har_oneshot_v1.json, amended by
docs/ml/HAR_ONESHOT_AMENDMENT_1.md). It implements what those two documents state and nothing else.

Every setting comes from the spec; the command takes three paths. The order is the spec's:

  refusals (no look spent) -> preflight (counts, dates and masks only) -> tables -> the control on the spent period (no window row) ->
  THE MARKER (the look is spent here) -> the window is scored -> one atomic write of the result.

The table (features, labels and the A_desk and B_seasonal forecasts of every row, window rows included, because the loader returns both periods in one table) is
built and held before the control, as the spec's order has it. No C_har forecast, no loss and no statistic of a window row exists before the marker, and nothing
about the window is printed or written before the final write: "any number displayed or written spends the look" (looks.crash). The marker is also written beside
the dataset, where the next run looks for it. A crash after the marker leaves the marker and a crash log and no result; the registered crash rule governs what
may follow (a person moves the marker, after the log is committed and the fix reviewed), not this code.

The dataset: amendment 1's route only. The dataset's verification record must be, byte for byte, the one P0.6 version 2 wrote (its sha256 is pinned), with
its single failed reason, and the dataset digest recomputed from the data on disk must be the pinned one. The result says `external_unverified` throughout,
carries the amendment's mandatory sentence in its header and in every sentence that states the outcome, and never says `external_verified`. A dataset that has
become `external_verified` is refused here: that is a different situation, and the amendment (a later P0.6 version needs its own amendment) says it needs a new
reviewed change. There is no flag that accepts any other dataset.
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
    try:
        return sha256_bytes(Path(path).read_bytes())
    except OSError as exc:
        raise Refused(f"{Path(path).name} cannot be read ({exc.__class__.__name__}): no look is spent") from exc


# ---- refusals ---------------------------------------------------------------------------------------------------------------------
def mandatory_sentence(amendment: Path) -> str:
    """The amendment's mandatory outcome sentence, verbatim (the file is pinned by hash, so this is the text that was reviewed)."""
    text = Path(amendment).read_text()
    m = re.search(r'^## What the result must say[^\n]*\n\n"(The dataset was .*?registration\.)"\s*$', text, re.S | re.M)
    if not m:
        raise Refused(f"{Path(amendment).name}: the mandatory sentence was not found")
    return m.group(1)


def dataset_route(ds: Path, man: dict, pins: Pins) -> tuple[str, dict]:
    """('amendment_1', the record) when the dataset's record is exactly the pinned P0.6 v2 record; anything else is refused, a dataset that has become
    `external_verified` included (that needs its own reviewed change). The dataset digest is recomputed from the manifest here and from the partitions by
    `intake.load` (expected_digest)."""
    if I.dataset_digest(man) != man.get("digest") or man.get("digest") != pins.dataset_digest:
        raise Refused(f"{Path(ds).name}: its digest is not the pinned {pins.dataset_digest[:12]} (recomputed from the manifest)")
    if I.effective_status(ds, man, list(SYMBOLS)) == I.VERIFIED:
        raise Refused(f"{Path(ds).name} is {I.VERIFIED}: this command runs on the pinned P0.6 version 2 record (amendment 1) only; a verified dataset needs a new "
                      "amendment and a reviewed change")
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
    spec_bytes = Path(spec_path).read_bytes() if Path(spec_path).is_file() else b""
    fsha, h = sha256_bytes(spec_bytes), spec_hash(spec_path)
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
    try:
        spec = json.loads(spec_bytes)                          # parsed from the bytes that were hashed above, not read a second time
    except ValueError as exc:
        raise Refused(f"{Path(spec_path).name} cannot be parsed: no look is spent") from exc
    name = spec["name"]
    for suffix in (".json", ".md"):
        if (Path(results_dir) / f"{name}-{h[:12]}{suffix}").exists():
            raise Refused(f"a result for this spec already exists in {results_dir}: the look is spent (looks.rule)")
    spent = Path(ds) / f"{name}-{h[:12]}.marker.json"
    if spent.exists() or spent.is_symlink():
        raise Refused(f"{spent} exists: the marker of an earlier run, so the look is spent (looks.rule). After a crash with no number written, a person moves it "
                      "only under the registered crash rule")
    commits = {"amendment_commit": _git_commit_of(amendment), "criteria_v2_commit": _git_commit_of(criteria)}
    if not all(commits.values()):
        raise Refused(f"the commit of the amendment or of the criteria file cannot be determined ({commits}): the run records both")
    man_path = Path(ds) / "manifest.json"
    try:
        man = json.loads(man_path.read_text())
    except (OSError, ValueError) as exc:
        raise Refused(f"{ds}: no readable manifest") from exc
    route, rec = dataset_route(Path(ds), man, pins)
    return {"spec_sha256": h, "spec_file_sha256": fsha, "route": route, "record": rec, "manifest": man, "name": name, "spec": spec, "dataset_marker": spent, **commits}


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
            "expected_present_but_absent": [d for d in EXPECTED["kept_mondays"] if dt.date.fromisoformat(d) not in dset],
            "vs_expected": {"weekdays_without_a_row": {"expected": 51, "found": len([d for d in weekdays if d not in dset]), "weekdays_in_window": len(weekdays)},
                            "sessions_with_missing_minutes": {"expected": 6, "found": len([i for i in win_idx if miss[i].any()]),
                                                              "expected_largest": "7 on 2023-06-14, 6 on 2024-04-23",
                                                              "found_largest": sorted(((int(miss[i].sum()), str(days[i])) for i in win_idx if miss[i].any()), reverse=True)[:2]}}}
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
def control_slice(t: pd.DataFrame) -> pd.DataFrame:
    """The spent period, both ends inclusive: 2019-01-01 to 2023-02-28."""
    return t[(t["day"] >= CONTROL_START) & (t["day"] <= CONTROL_END)].reset_index(drop=True)


def window_slice(t: pd.DataFrame) -> pd.DataFrame:
    """The reserved window, both ends inclusive: 2023-03-01 to 2026-05-14."""
    return t[(t["day"] >= WINDOW_START) & (t["day"] <= WINDOW_END)].reset_index(drop=True)


def with_frozen_forecast(table: pd.DataFrame, artifact: dict) -> pd.DataFrame:
    """The table with F_C, the frozen C_har's forecast: the artifact's per-horizon fit applied to each symbol's rows. Nothing is fitted here."""
    out = table.copy()
    out["F_C"] = np.nan
    for s in SYMBOLS:
        i = (out["symbol"] == s).to_numpy()
        if i.any():
            out.loc[i, "F_C"] = V.predict_c(out.loc[i], artifact["symbols"][s]["fit"])
    return out


_CANDIDATE = {"F_A": "A_desk", "F_B": "B_seasonal", "F_C": "C_har"}


def daily(g: pd.DataFrame, col: str) -> pd.Series:
    """Daily QLIKE of forecast column `col`: `volstudy.daily_loss` for the three candidates, the same computation for the refit's forecast."""
    if col in _CANDIDATE:
        return V.daily_loss(g, _CANDIDATE[col])
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
                "daily_gain_autocorr_lags_1_to_5": autocorr((a - c).dropna().to_numpy(float)),
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


def slice_accounting(grids: dict, before: pd.DataFrame, after: pd.DataFrame, lo: str, hi: str, man: dict | None = None) -> dict:
    """What the rules left out of [lo, hi], per symbol, decided from the calendar, the missing-minute mask and row counts alone (never a return, a variance or
    a loss): the sessions of the grid, the sessions that kept rows, every session with no row and the rule that removed it, and the rows removed by each rule.
    `before` is the table before the leading-gap filter and `after` the table after it. The importer's own exclusions (sessions of the manifest that were
    rejected or left for review) are listed from the manifest."""
    per_session = sum(1 for m in V.DECISIONS for h, mins in V.HORIZONS.items() if (V.N_MIN if mins is None else m + mins) <= V.N_MIN)
    gaps = gap_ordinals(grids)
    out = {"rows_possible_per_session": per_session, "symbols": {}}
    for s in SYMBOLS:
        days, _, _, _ = grids[s]
        dd = pd.to_datetime(pd.Series(list(days))).diff().dt.days.to_numpy()
        valid_prior = pd.Series((dd <= 4).astype(float)).rolling(V.PRIOR_DAYS).min().fillna(0).to_numpy() > 0       # volstudy.rows: 5 prior consecutive sessions
        gap_drop = {o for g in gaps[s] for o in range(g, g + GAP_SESSIONS + 1)}
        idx = [i for i, d in enumerate(days) if lo <= str(d) <= hi]
        b = before[(before["symbol"] == s) & (before["day"] >= lo) & (before["day"] <= hi)]
        a = after[(after["symbol"] == s) & (after["day"] >= lo) & (after["day"] <= hi)]
        n_b, n_a = b.groupby("day").size().to_dict(), a.groupby("day").size().to_dict()
        none, lookback, miss_rule, gap_rows = [], 0, 0, 0
        for i in idx:
            d = str(days[i])
            if not valid_prior[i]:
                lookback += per_session
            else:
                miss_rule += per_session - n_b.get(d, 0)
            gap_rows += n_b.get(d, 0) - n_a.get(d, 0)
            if d not in n_a:
                why = ("feature lookback (the first 5 sessions, or 5 consecutive sessions needed after a break over 4 days)" if not valid_prior[i]
                       else "leading-gap filter" if i in gap_drop else "every label window over 20% missing")
                none.append({"day": d, "why": why})
        kept_by_year = {}
        for d in n_a:
            kept_by_year[d[:4]] = kept_by_year.get(d[:4], 0) + 1
        rows_possible = per_session * len(idx)
        out["symbols"][s] = {"sessions_in_grid": len(idx), "sessions_with_rows": len(n_a), "sessions_with_rows_by_year": dict(sorted(kept_by_year.items())),
                             "sessions_without_rows": none, "rows_possible": rows_possible,
                             "rows_removed": {"feature_lookback_rule": lookback, "label_window_over_20pct_missing": miss_rule, "leading_gap_filter": gap_rows},
                             "rows_kept": int(len(a)), "reconciles": bool(rows_possible - lookback - miss_rule - gap_rows == len(a))}
    if man is not None:
        out["importer_exclusions"] = [{k: v for k, v in x.items() if k in ("symbol", "day", "status", "why", "reason", "reasons", "rule")}
                                      for x in man.get("sessions", []) if x.get("symbol") in SYMBOLS and x.get("status") in ("rejected", "review") and lo <= str(x.get("day")) <= hi]
    return out


def _f(x, spec: str = ".4f") -> str:
    """A number for the report; a missing or NaN one reads 'n/a' instead of breaking the render after numbers exist."""
    try:
        return "n/a" if x is None or x != x else format(x, spec)
    except (TypeError, ValueError):
        return "n/a"


def _write_pair(out: Path, stem: str, text_json: str, text_md: str) -> None:
    """Both result files, each whole under a private name and linked into place only if absent. Both texts exist before the first link."""
    tmps = []
    try:
        for suffix, text in ((".json", text_json), (".md", text_md)):
            tmp = Path(f"{out / (stem + suffix)}.{os.getpid()}.tmp")
            tmp.write_text(text)
            tmps.append((tmp, out / (stem + suffix)))
        linked = []
        try:
            for tmp, final in tmps:
                os.link(tmp, final)
                linked.append(final)
        except BaseException:
            for final in linked:                                       # never leave one of the two files behind: the crash message says nothing was written
                final.unlink(missing_ok=True)
            raise
    finally:
        for tmp, _ in tmps:
            tmp.unlink(missing_ok=True)


class CrashAfterMarker(RuntimeError):
    """The run failed after the marker was written: the look is spent. The crash log is beside the marker."""


def code_state() -> dict:
    """{commit, dirty}: HEAD, and whether anything under quantdesk/, docs/, tests/ or config/ differs from it (the code, its tests, the specs and the pins it reads)."""
    try:
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "quantdesk", "docs", "tests", "config"], capture_output=True, text=True, timeout=20,
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
    h = info["spec_sha256"]
    try:
        art, locked = json.loads(artifact.read_text()), json.loads(lock_result.read_text())
    except (OSError, ValueError) as exc:
        raise Refused(f"the artifact or the lock result cannot be read ({exc.__class__.__name__}): no look is spent") from exc
    lock_sha = sha256_of(lock_result)
    sentence = mandatory_sentence(amendment)
    out.mkdir(parents=True, exist_ok=True)
    say(f"oneshot: route {info['route']}; spec {h[:12]}; dataset {info['manifest']['digest'][:12]}")

    # -- load and preflight (masks only) ------------------------------------------------------------------------------------------------
    bars = (loader or I.load)(ds, list(SYMBOLS), use="regime_research", allow_unverified=True, expected_digest=pins.dataset_digest)
    attrs = dict(bars.attrs)
    grids = {s: V.grid(bars[bars["symbol"] == s]) for s in SYMBOLS}
    pre = preflight(grids)
    gaps = gap_ordinals(grids)
    say("oneshot: preflight " + ("found leading-gap sessions; they and the next 5 are dropped from scoring" if any(gaps.values()) else "found no leading-gap session"))

    # -- tables (the window rows are read only through load_table(reserved_spec=<this spec>)) --------------------------------------------
    profile = {s: art["symbols"][s]["profile"] for s in SYMBOLS}
    root = out / "tables"
    kw = dict(loader=loader, allow_unverified=True, expected_digest=pins.dataset_digest, say=lambda *_: None)
    gap_ok = any(gaps.values())
    f1 = B.build(ds, list(SYMBOLS), PROFILE_END, root, profile=profile, allow_leading_gap=gap_ok, **kw)
    f2 = B.build(ds, list(SYMBOLS), REFIT_PROFILE_END, root, allow_leading_gap=gap_ok, **kw)
    lt = dict(allow_unverified=True, reserved_spec=spec_path, dataset=None if loader else ds)
    raw_all = B.load_table(f1, scoring_only=True, **lt)
    refit_all = B.load_table(f2, scoring_only=False, **lt)
    raw = drop_leading_gap(raw_all, gaps)

    # -- the control: restricted to the spent period before it scores anything; no window row gets a C_har forecast, let alone a score -----
    ctrl = with_frozen_forecast(control_slice(raw), art)
    ctl = control(ctrl, locked, pins.control_tolerance)
    if not ctl["ok"]:
        bad = "; ".join(f"{k}: A {_f(ctl['cells'][k]['A'])} (locked {_f(ctl['cells'][k]['locked_A'])}), C {_f(ctl['cells'][k]['C'])} (locked {_f(ctl['cells'][k]['locked_C'])})"
                        for k in ctl["failed"])
        raise ControlFailed(f"the control failed in {ctl['failed']} ({bad}; spent-period numbers): the evaluation is not run and no look is spent")
    say("oneshot: control passed")

    # -- THE MARKER: the look is spent here. Beside the dataset first (where the next run looks), then in the output folder ----------------
    opened = pd.Timestamp.now(tz=I.IST).isoformat()
    header = {"spec": info["name"], "spec_sha256": h, "spec_file_sha256": info["spec_file_sha256"], "route": info["route"], "code_commit": commit["commit"],
              "dataset": attrs.get("dataset"), "dataset_digest": attrs.get("digest"), "dataset_status": attrs.get("status"), "dataset_tier": attrs.get("tier"),
              "artifact_sha256": pins.artifact_sha256, "tables": {"primary": f1.name, "refit": f2.name},
              "amendment_sha256": pins.amendment_sha256, "amendment_commit": info["amendment_commit"],
              "criteria_v2_sha256": pins.criteria_v2_sha256, "criteria_v2_commit": info["criteria_v2_commit"],
              "record_sha256": pins.record_sha256, "lock_result_sha256": lock_sha, "opened": opened}
    stem = f"{info['name']}-{h[:12]}"
    try:
        _write_once(info["dataset_marker"], json.dumps(header, indent=1))
    except OSError as exc:
        raise Refused(f"the marker cannot be written beside the dataset ({exc.__class__.__name__}): no look is spent") from exc
    say("oneshot: the marker is written beside the dataset; the look is spent")

    # -- the window ---------------------------------------------------------------------------------------------------------------------
    try:
        _write_once(out / f"{stem}.marker.json", json.dumps(header, indent=1))             # the copy beside the result; the dataset's marker already stands
        win = with_frozen_forecast(window_slice(raw), art)
        prim = primary(win)
        pooled = pooled_c_vs_b(win)
        refit_f, refit_fits = refit_forecast(refit_all, win, gaps)
        refit_profile = {s: B.fit_profile(grids[s], REFIT_PROFILE_END).tolist() for s in SYMBOLS}
        sec = secondary(win, refit_f)
        gap_dates = {s: [str(grids[s][0][o]) for o in gaps[s]] for s in SYMBOLS if gaps[s]}
        result = {"caveat": sentence, "outcome_statement": f"{prim['verdict']}. {sentence}", "evidence": "external_unverified", **header,
                  "not_for": info["spec"]["not_for"], "use_if_passed": info["spec"]["use_if_passed"], "control": ctl, "preflight": pre,
                  "leading_gap_sessions_dropped": gap_dates,
                  "primary": prim, "pooled_c_vs_b": pooled, "secondary": sec,
                  "refit": {"fits": refit_fits, "profile": refit_profile, "profile_end": REFIT_PROFILE_END},
                  "frozen": {"profile": profile, "fit": {s: art["symbols"][s]["fit"] for s in SYMBOLS}},
                  "accounting": {"window": slice_accounting(grids, raw_all, raw, WINDOW_START, WINDOW_END, info["manifest"]),
                                 "control_period": slice_accounting(grids, raw_all, raw, CONTROL_START, CONTROL_END, info["manifest"])},
                  "rows_by_symbol_year": {f"{s} {y}": int(n) for (s, y), n in win.groupby(["symbol", "year"]).size().items()},
                  "verdict": prim["verdict"]}
        _write_pair(out, stem, json.dumps(result, indent=1, default=str), render(result))
    except Exception as exc:
        import traceback
        log = out / f"{stem}.crash.txt"
        try:
            log.write_text(traceback.format_exc())
        except OSError:
            pass
        raise CrashAfterMarker(f"crashed after the marker (the look is spent; no result file was written, only the markers and this log): {exc.__class__.__name__}; the detail is in the log, which may hold values and is not printed. "
                               f"The crash log is {log}. The registered crash rule governs what may follow.") from exc
    return result


def rehearse_control(dataset: Path, out: Path, say=print, pins: Pins | None = None, loader=None, artifact: Path | None = None,
                     lock_result: Path | None = None) -> dict:
    """The spent-period rehearsal (controls_before_the_run: "rehearse the whole command on a synthetic dataset and on the spent period"). It runs the
    command's own machinery up to and including the control, on the real dataset, and stops: no marker, no result. No window row is built, held
    or scored: `intake.load` reads (and hashes) every partition, the 2023 one included, but the bars are cut at CONTROL_END straight after the load, before any
    grid or table exists, and the table is read WITHOUT the reserved spec, so the loader itself withholds the reserved window. (Its table folder carries the
    primary table's recipe but fewer rows; it is a scratch folder and is discarded.) What it returns is about the spent period only (the same control the run will make). Written under `out`
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
    """The result as text. The mandatory sentence heads the report, before the heading, the label and every number; the outcome line carries it again."""
    L = [f"> {r['caveat']}", "", f"# {r['spec']} - one-shot evaluation ({r['evidence']})", "", f"**Outcome: {r['outcome_statement']}**", "",
         f"**Not for:** {r['not_for']}.", "", f"**If passed:** {r['use_if_passed']}", ""]
    L += [f"Evidence label: **{r['evidence']}**. Opened {r['opened']}. Spec sha256 `{r['spec_sha256']}` (autolearn.prereg.spec_hash; file `{r['spec_file_sha256']}`), "
          f"code commit `{r['code_commit']}`.",
          f"Dataset `{r['dataset']}` (digest `{r['dataset_digest']}`, status {r['dataset_status']}, tier {r['dataset_tier']}); artifact sha256 `{r['artifact_sha256']}`; "
          f"tables `{r['tables']['primary']}` and `{r['tables']['refit']}`; amendment sha256 `{r['amendment_sha256']}` (commit `{r['amendment_commit']}`); "
          f"criteria v2 sha256 `{r['criteria_v2_sha256']}` (commit `{r['criteria_v2_commit']}`); record sha256 `{r['record_sha256']}`; lock result sha256 `{r['lock_result_sha256']}`.", "",
          "| cell | days | mean A | mean B | mean C | gain % | DM t | p | Holm p | passes |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, c in r["primary"]["cells"].items():
        L.append(f"| {k} | {c['days']} | {_f(c['mean_A'])} | {_f(c['mean_B'])} | {_f(c['mean_C'])} | {_f(c['gain_pct'], '+.1f')} | {_f(c['dm_t'], '+.2f')} | "
                 f"{_f(c['p_one'], '.3g')} | {_f(c['p_holm'], '.3g')} | {'yes' if c['passes'] else 'no'} |")
    p = r["pooled_c_vs_b"]
    L += ["", f"Pooled C versus B: {p['dates']} dates ({p['dates_dropped']} dropped), t {_f(p['dm_t'], '+.2f')}, one-sided p {_f(p['p_one'], '.3g')}: {p['says']}.",
          "", f"Control (spent period): {'passed' if r['control']['ok'] else 'FAILED'} within {r['control']['tolerance']} in every cell.",
          f"Leading-gap sessions dropped from scoring (with the next 5 of that symbol): {r['leading_gap_sessions_dropped'] or 'none'}.",
          "The weekdays without a row, the sessions with missing minutes and the differences from the expected exclusions are in the JSON preflight; the exchange-holiday "
          "check is the steward's (docs/EXTERNAL_DATA.md item 13) and is not repeated by this run.",
          "", "Everything else (the secondary tables, the accounting of sessions and rows by rule, the refit's coefficients and profile, the frozen coefficients) is in the JSON "
          "file beside this one.", "", f"> {r['caveat']}", ""]
    return "\n".join(L)
