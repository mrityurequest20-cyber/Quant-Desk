"""`python -m quantdesk ml oneshot` (quantdesk/ml/oneshot.py): the pins match the documents they come from, every refusal happens before the look is spent,
the control restricts itself to the spent period, the window gets no forecast before the marker, and the statistics are the spec's. The end-to-end run is on
a small synthetic dataset with its own pins: the command line never passes any."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.autolearn import volstudy as V
from quantdesk.ml import build as B
from quantdesk.ml import intake as I
from quantdesk.ml import oneshot as OS
from quantdesk.ml import splits as S
from quantdesk.ml import verify as VF

REPO = Path(OS.__file__).resolve().parents[2]
SPEC = REPO / "docs" / "prereg" / "har_oneshot_v1.json"
AMEND = REPO / "docs" / "ml" / "HAR_ONESHOT_AMENDMENT_1.md"
IST = "Asia/Kolkata"
CLEAN = {"commit": "c0ffee0", "dirty": False}


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---- the pins are what the documents say -----------------------------------------------------------------------------------------
def test_the_pins_are_the_hashes_of_the_files_they_name():
    assert OS.SPEC_FILE_SHA256 == sha(SPEC)
    from quantdesk.autolearn.prereg import spec_hash
    assert OS.SPEC_HASH == spec_hash(SPEC)
    assert OS.ARTIFACT_SHA256 == sha(REPO / "quantdesk" / "intraday" / "vol_har_v1.json")
    from quantdesk.intraday import harvol, volshadow
    assert OS.ARTIFACT_SHA256 == volshadow.COEF_PIN and OS.ARTIFACT_PATH == harvol.DEFAULT_PATH
    assert OS.AMENDMENT_SHA256 == sha(AMEND)
    assert OS.CRITERIA_V2_SHA256 == sha(REPO / "docs" / "ml" / "P0_6_criteria_v2.md") == I.VERIFICATION_CRITERIA["p06-v2"]
    assert (REPO / "docs" / "prereg" / "results" / OS.LOCK_RESULT_FILE).is_file() and OS.LOCK_RESULT_PATH.name == OS.LOCK_RESULT_FILE


def test_the_pins_agree_with_the_amendment_and_the_spec_text():
    text, spec = AMEND.read_text(), SPEC.read_text()
    for pinned in (OS.RECORD_SHA256, OS.CRITERIA_V2_SHA256, VF.DATASET_DIGEST, OS.RECORD_REASON, OS.PROFILE_END):
        assert pinned in text or pinned in spec, pinned
    assert OS.RECORD_SHA256 in text and OS.RECORD_REASON in text and VF.DATASET_DIGEST in text
    assert "0.015" in spec and OS.CONTROL_TOLERANCE == 0.015                                  # control.tolerance
    assert OS.WINDOW_START in spec and OS.WINDOW_END in spec and OS.CONTROL_START in spec and OS.CONTROL_END in spec
    assert OS.WINDOW_START == B.RESERVED_FROM and OS.PROFILE_END == "2018-12-31" and OS.REFIT_PROFILE_END == "2023-02-28"
    for lst in OS.EXPECTED.values():
        for d in lst:
            assert d in spec, d
    assert OS.NW_LAGS == 5 and OS.ALPHA == 0.05 and OS.GAP_SESSIONS == 5


def test_the_mandatory_sentence_is_taken_verbatim_from_the_pinned_amendment():
    s = OS.mandatory_sentence(AMEND)
    assert s.startswith("The dataset was `external_unverified` when this was run") and s.endswith("This evaluation was run under amendment 1 to its registration.")
    assert "forecasts and scores realised variance built from squared 1-minute log returns (QLIKE loss)" in s and "not two independent confirmations" in s
    assert s in AMEND.read_text()


def test_a_file_without_the_sentence_is_refused(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("## What the result must say\n\nnothing here\n")
    with pytest.raises(OS.Refused, match="mandatory sentence"):
        OS.mandatory_sentence(f)


# ---- the statistics --------------------------------------------------------------------------------------------------------------
def test_holm_is_the_step_down_adjustment_and_a_nan_is_ranked_last_and_never_passes():
    adj = OS.holm({"a": 0.001, "b": 0.01, "c": 0.04, "d": float("nan")})
    assert adj["a"] == pytest.approx(0.004) and adj["b"] == pytest.approx(0.03) and adj["c"] == pytest.approx(0.08) and adj["d"] != adj["d"]
    mono = OS.holm({"a": 0.02, "b": 0.005})                                                 # sorted: 0.005 x2, then max(0.01, 0.02 x1)
    assert mono["b"] == pytest.approx(0.01) and mono["a"] == pytest.approx(0.02)
    assert OS.holm({"a": 0.9, "b": 0.8})["a"] == 1.0                                         # capped at 1
    eight = OS.holm({f"c{i}": 0.003 for i in range(8)})
    assert all(v == pytest.approx(0.024) for v in eight.values())                            # m = 8 for every cell, NaN or not


def cell(passes, c, a):
    return {"passes": passes, "mean_C": c, "mean_A": a}


def test_the_verdict_follows_pass_fail_exactly():
    ok = {f"c{i}": cell(True, 0.1, 0.2) for i in range(8)}
    assert OS.verdict(ok) == "PASS"
    assert OS.verdict({**ok, "c0": cell(False, 0.1, 0.2)}) == "MIXED"
    assert OS.verdict({**ok, "c0": cell(False, 0.1, 0.2), "c1": cell(False, 0.1, 0.2), "c2": cell(False, 0.1, 0.2)}) == "MIXED"
    four = {**ok, **{f"c{i}": cell(False, 0.1, 0.2) for i in range(4)}}
    assert OS.verdict(four) == "KILL"                                                         # four or more cells do not pass
    assert OS.verdict({**ok, "c3": cell(True, 0.2, 0.2)}) == "KILL"                           # the hair trigger: one cell at or above A, whatever the others show
    assert OS.verdict({**ok, "c3": cell(False, 0.3, 0.2)}) == "KILL"
    nan = {**ok, "c0": cell(False, float("nan"), float("nan"))}
    assert OS.verdict(nan) == "MIXED"                                                         # an undersized cell does not pass but is not 'worse'


def daily_frame(rows):
    return pd.DataFrame(rows)


def test_dm_is_a_better_than_b_one_sided():
    idx = pd.Index([f"2023-03-{d:02d}" for d in range(1, 29)])
    rng = np.random.default_rng(1)
    b = pd.Series(0.20 + rng.normal(0, 0.01, len(idx)), index=idx)
    a = b + 0.05 + rng.normal(0, 0.01, len(idx))                  # a is worse than b
    r = OS.dm(a, b)
    assert r["dm_t"] > 5 and r["p_one"] < 0.001 and r["gain_pct"] > 0 and r["days"] == len(idx)
    flip = OS.dm(b, a)
    assert flip["dm_t"] < -5 and flip["p_one"] > 0.999 and flip["gain_pct"] < 0
    short = OS.dm(a.iloc[:5], b.iloc[:5])                                                      # fewer than 10 sessions: no t, no p
    assert short["dm_t"] != short["dm_t"] and short["p_one"] != short["p_one"]


def frame_cells(win_days, f_a=2.0, f_b=2.0, f_c=1.0, drop=None):
    """One row per (symbol, horizon, day): rv 1; the forecasts are constants, so each cell's daily QLIKE is known."""
    rows = []
    for s, h in OS.CELLS:
        for i, d in enumerate(win_days):
            if drop and drop(s, h, d):
                continue
            rows.append({"symbol": s, "horizon": h, "day": d, "year": int(d[:4]), "m": 15, "rv": 1.0, "ret": 0.0, "F_A": f_a, "F_B": f_b, "F_C": f_c})
    return pd.DataFrame(rows)


DAYS = [f"2023-{m:02d}-{d:02d}" for m in (3, 4) for d in range(1, 29)]


def test_the_pooled_test_uses_only_dates_where_all_eight_cells_have_a_loss_and_reports_the_drop():
    full = OS.pooled_c_vs_b(frame_cells(DAYS, f_b=3.0, f_c=1.0))
    assert full["dates"] == len(DAYS) and full["dates_dropped"] == 0
    part = OS.pooled_c_vs_b(frame_cells(DAYS, f_b=3.0, f_c=1.0, drop=lambda s, h, d: s == "BANKNIFTY" and h == "60m" and d in DAYS[:3]))
    assert part["dates"] == len(DAYS) - 3 and part["dates_dropped"] == 3
    q = lambda f: 1 / f - np.log(1 / f) - 1
    assert OS.daily(frame_cells(DAYS[:2], f_a=2.0), "F_A").to_numpy() == pytest.approx([q(2.0)] * 2)
    assert OS.pooled_c_vs_b(frame_cells(DAYS[:5]))["says"].startswith("B_seasonal")             # fewer than 10 dates: NaN, so the cheaper alternative is named
    rng = np.random.default_rng(5)
    noisy = frame_cells(DAYS, f_b=3.0, f_c=1.0)
    noisy["F_C"] = noisy["F_C"] * (1 + 0.1 * rng.standard_normal(len(noisy)))                    # B clearly worse than C, with a variance
    yes = OS.pooled_c_vs_b(noisy)
    assert yes["significant"] and "adds beyond" in yes["says"] and yes["p_one"] < 0.05
    no = OS.pooled_c_vs_b(noisy.assign(F_B=lambda d: d["F_C"]))                                  # B identical to C: nothing to add
    assert not no["significant"] and no["says"].startswith("B_seasonal")


def test_the_primary_test_has_eight_cells_holm_and_a_verdict():
    rng = np.random.default_rng(3)
    win = frame_cells(DAYS)
    win["F_C"] = win["F_C"] * (1 + 0.05 * rng.standard_normal(len(win)))                       # so the daily differences have a variance
    r = OS.primary(win)
    assert list(r["cells"]) == [f"{s} {h}" for s, h in OS.CELLS] and len(r["cells"]) == 8
    assert all(c["passes"] for c in r["cells"].values()) and r["verdict"] == "PASS"
    assert all(c["p_holm"] >= c["p_one"] for c in r["cells"].values())
    worse = OS.primary(win.assign(F_C=lambda d: d["F_A"] * 3))                                   # C worse than A everywhere
    assert worse["verdict"] == "KILL" and not any(c["passes"] for c in worse["cells"].values())


def test_autocorrelation_of_a_known_series():
    x = np.tile([1.0, -1.0], 20)
    ac = OS.autocorr(x, lags=[1, 2])
    assert ac["1"] == pytest.approx(-0.975) and ac["2"] == pytest.approx(0.95)


# ---- the control -----------------------------------------------------------------------------------------------------------------
def locked_like(a_q, c_q):
    return {"lock": {"tests": {f"{s} {h}": {"scores": {"A_desk": {"qlike": a_q}, "C_har": {"qlike": c_q}}} for s, h in OS.CELLS}}}


Q2 = 1 / 2.0 - np.log(1 / 2.0) - 1                              # QLIKE with rv 1, forecast 2


def test_the_control_passes_within_tolerance_and_names_every_cell_that_fails():
    ctrl = frame_cells(DAYS, f_a=2.0, f_c=1.0)                    # A: Q2, C: 0
    ok = OS.control(ctrl, locked_like(Q2 + 0.01, 0.01))
    assert ok["ok"] and not ok["failed"] and len(ok["cells"]) == 8
    bad = OS.control(ctrl, locked_like(Q2, 0.2))                  # the locked C is 0.2 away
    assert not bad["ok"] and len(bad["failed"]) == 8
    gain = OS.control(ctrl, locked_like(Q2 + 0.014, -0.014 + 0.0))     # each level is within the tolerance but the gain is 0.028 away
    assert not gain["ok"]
    worse = OS.control(frame_cells(DAYS, f_a=1.0, f_c=2.0), locked_like(0.0, Q2))                # C not below A in the control
    assert not worse["ok"]


# ---- sessions and gaps --------------------------------------------------------------------------------------------------------------
def tiny_grid(n=12, lead_gap_at=None, start="2023-03-01"):
    days = pd.Index([d.date() for d in pd.bdate_range(start, periods=n)])
    miss = np.zeros((n, V.N_MIN), dtype=bool)
    for i in lead_gap_at or []:
        miss[i, 0] = True
    return days, np.zeros((n, V.N_MIN)), miss, np.full(n, 100.0)


def test_leading_gap_sessions_are_found_from_the_mask_alone():
    g = {"NIFTY": tiny_grid(lead_gap_at=[3]), "BANKNIFTY": tiny_grid()}
    assert OS.gap_ordinals(g) == {"BANKNIFTY": [], "NIFTY": [3]}
    pre = OS.preflight(g)
    assert pre["leading_gap_sessions"]["NIFTY"] == [str(g["NIFTY"][0][3])] and pre["leading_gap_sessions"]["BANKNIFTY"] == []


def test_the_gap_session_and_the_next_five_of_that_symbol_are_dropped_and_nothing_else():
    t = pd.DataFrame({"symbol": ["NIFTY"] * 14 + ["BANKNIFTY"] * 14, "session": list(range(14)) * 2})
    out = OS.drop_leading_gap(t, {"NIFTY": [3], "BANKNIFTY": []})
    assert sorted(out.loc[out["symbol"] == "NIFTY", "session"]) == [0, 1, 2, 9, 10, 11, 12, 13]       # 3..8 gone
    assert (out["symbol"] == "BANKNIFTY").sum() == 14
    assert OS.drop_leading_gap(t, {"NIFTY": [], "BANKNIFTY": []}) is t                              # nothing found: nothing changes


def test_preflight_lists_the_weekdays_without_a_row_and_the_expected_exclusions():
    days = pd.Index([d.date() for d in pd.bdate_range("2023-02-20", "2023-03-10") if d.day != 8])        # 8 Mar 2023 has no row
    n = len(days)
    miss = np.zeros((n, V.N_MIN), dtype=bool)
    miss[8, 100] = True                                                                       # 2023-03-02, inside the window
    g = {s: (days, np.zeros((n, V.N_MIN)), miss, np.full(n, 100.0)) for s in OS.SYMBOLS}
    pre = OS.preflight(g)["symbols"]["NIFTY"]
    assert pre["weekdays_without_a_row"][0] == "2023-03-08" and "2023-03-07" not in pre["weekdays_without_a_row"]          # the grid ends on 10 Mar: later weekdays are listed too
    assert pre["sessions_with_missing_minutes"] == [{"day": "2023-03-02", "missing": 1}]
    assert pre["sessions_in_window"] == 7 and pre["window_sessions_by_year"] == {"2023": 7}
    assert pre["expected_present_but_absent"] == ["2025-02-03", "2026-02-02"] and pre["expected_absent_but_present"] == []


# ---- refusals: before anything is loaded ---------------------------------------------------------------------------------------
def make_dataset(tmp_path, status=I.UNVERIFIED, record_overrides=None, raw_edit=None, verified=False):
    ds = tmp_path / "ds"
    ds.mkdir()
    man = {"schema": 1, "importer_version": "ml-intake-2", "rules": {}, "reviewed_sha256": "r" * 8, "partitions": {}, "sessions": [],
           "source": {"name": "n", "url": "u", "files": [], "version": "v"}, "status": status, "dataset": "ds"}
    man["digest"] = I.dataset_digest(man)
    (ds / "manifest.json").write_text(json.dumps(man))
    if verified:
        rec = {"check": "p06-v2", "criteria_sha256": I.VERIFICATION_CRITERIA["p06-v2"], "digest": man["digest"], "passed": True,
               "symbols_verified": list(OS.SYMBOLS)}
    else:
        rec = {"check": "p06-v2", "digest": man["digest"], "criteria_sha256": OS.CRITERIA_V2_SHA256, "passed": False, "symbols_verified": [],
               "reasons": [OS.RECORD_REASON], "post_hoc": True, "supersedes": VF.SUPERSEDES,
               "symbols": {s: {"A": {"passed": True}, "B": {"passed": True}, "C": {"passed": s == "NIFTY"}} for s in OS.SYMBOLS}, "D": {"passed": True, "reasons": []}}
    rec.update(record_overrides or {})
    raw = json.dumps(rec).encode()
    (ds / "verification.json").write_bytes(raw)
    pins = OS.Pins(dataset_digest=man["digest"], record_sha256=hashlib.sha256(raw).hexdigest())
    if raw_edit:
        (ds / "verification.json").write_bytes(raw + raw_edit)
    return ds, man, pins


def test_the_pinned_failed_record_opens_the_amended_route(tmp_path):
    ds, man, pins = make_dataset(tmp_path)
    route, rec = OS.dataset_route(ds, man, pins)
    assert route == "amendment_1" and rec["passed"] is False


def test_a_dataset_that_has_become_verified_is_refused_here_it_needs_its_own_reviewed_change(tmp_path):
    ds, man, pins = make_dataset(tmp_path, status=I.VERIFIED, verified=True)
    with pytest.raises(OS.Refused, match="needs a new amendment"):
        OS.dataset_route(ds, man, pins)


@pytest.mark.parametrize("name,kw,match", [
    ("edited record", {"raw_edit": b" "}, "not the P0.6 version 2 record"),
    ("another reason", {"record_overrides": {"reasons": ["NIFTY C: something else"]}}, "reasons"),
    ("two reasons", {"record_overrides": {"reasons": [OS.RECORD_REASON, "x"]}}, "reasons"),
    ("another check", {"record_overrides": {"check": "p06-v1"}}, "check"),
    ("other criteria", {"record_overrides": {"criteria_sha256": "0" * 64}}, "criteria_sha256"),
    ("a symbol licensed", {"record_overrides": {"symbols_verified": ["NIFTY"]}}, "symbols_verified"),
    ("not post hoc", {"record_overrides": {"post_hoc": False}}, "post_hoc"),
    ("another dataset in the record", {"record_overrides": {"digest": "1" * 64}}, "digest"),
    ("check B failed", {"record_overrides": {"symbols": {s: {"A": {"passed": True}, "B": {"passed": s == "NIFTY"}} for s in OS.SYMBOLS}}}, "checks A and B"),
    ("check D failed", {"record_overrides": {"D": {"passed": False}}}, "checks A and B"),
])
def test_anything_but_the_exact_pinned_record_is_refused(tmp_path, name, kw, match):
    ds, man, pins = make_dataset(tmp_path, **kw)
    with pytest.raises(OS.Refused, match=match):
        OS.dataset_route(ds, man, pins)


def test_the_record_sha_is_what_decides_not_what_the_record_says_about_itself(tmp_path):
    ds, man, pins = make_dataset(tmp_path)
    forged = OS.Pins(dataset_digest=pins.dataset_digest, record_sha256="0" * 64)
    with pytest.raises(OS.Refused, match="not the P0.6 version 2 record"):
        OS.dataset_route(ds, man, forged)


def test_another_dataset_digest_or_a_manifest_that_does_not_hash_is_refused(tmp_path):
    ds, man, pins = make_dataset(tmp_path)
    with pytest.raises(OS.Refused, match="digest"):
        OS.dataset_route(ds, man, OS.Pins(dataset_digest="2" * 64, record_sha256=pins.record_sha256))
    altered = dict(man, digest="3" * 64)
    with pytest.raises(OS.Refused, match="digest"):
        OS.dataset_route(ds, altered, OS.Pins(dataset_digest="3" * 64, record_sha256=pins.record_sha256))


def test_an_unverified_dataset_with_no_record_has_no_route(tmp_path):
    ds, man, pins = make_dataset(tmp_path)
    (ds / "verification.json").unlink()
    with pytest.raises(OS.Refused, match="no verification.json"):
        OS.dataset_route(ds, man, pins)


def test_the_manifest_must_still_say_unverified_on_the_amended_route(tmp_path):
    ds, man, pins = make_dataset(tmp_path, status="external_verified")           # 'verified' in the manifest but its record failed
    with pytest.raises(OS.Refused):
        OS.dataset_route(ds, man, pins)


@pytest.fixture()
def ready(tmp_path):
    ds, man, pins = make_dataset(tmp_path)
    art = tmp_path / "vol_har.json"
    art.write_text("{}")
    pins = OS.Pins(artifact_sha256=sha(art), dataset_digest=pins.dataset_digest, record_sha256=pins.record_sha256)
    out, results = tmp_path / "out", tmp_path / "results"
    results.mkdir()
    kw = dict(ds=ds, spec_path=SPEC, out=out, pins=pins, amendment=AMEND, criteria=REPO / "docs" / "ml" / "P0_6_criteria_v2.md", artifact=art,
              results_dir=results, commit=CLEAN)
    return kw


def test_everything_in_order_returns_the_route_and_the_header_facts(ready):
    info = OS.refuse_unless_ready(**ready)
    assert info["route"] == "amendment_1" and info["spec_sha256"] == OS.SPEC_HASH and info["spec_file_sha256"] == OS.SPEC_FILE_SHA256 and info["name"] == "har_oneshot_v1"


def test_an_edited_spec_artifact_amendment_or_criteria_is_refused(ready, tmp_path):
    edited = tmp_path / "spec.json"
    edited.write_text(SPEC.read_text() + " ")
    with pytest.raises(OS.Refused, match="not the merged spec"):
        OS.refuse_unless_ready(**{**ready, "spec_path": edited})
    other = tmp_path / "other.json"
    other.write_text("{ }")
    with pytest.raises(OS.Refused, match="pinned artifact"):
        OS.refuse_unless_ready(**{**ready, "artifact": other})
    with pytest.raises(OS.Refused, match="merged amendment"):
        OS.refuse_unless_ready(**{**ready, "amendment": other})
    with pytest.raises(OS.Refused, match="pinned criteria"):
        OS.refuse_unless_ready(**{**ready, "criteria": other})


@pytest.mark.parametrize("commit", [{"commit": "abc", "dirty": True}, {"commit": None, "dirty": None}, {"commit": "abc", "dirty": None}, {"commit": "", "dirty": False}])
def test_an_unclean_or_unknown_code_tree_is_refused(ready, commit):
    with pytest.raises(OS.Refused, match="clean checkout"):
        OS.refuse_unless_ready(**{**ready, "commit": commit})


def test_the_output_folder_must_be_empty_and_outside_every_git_tree(ready, tmp_path):
    with pytest.raises(OS.Refused, match="git working tree"):
        OS.refuse_unless_ready(**{**ready, "out": REPO / "runtime" / "oneshot_test_never_created"})
    full = tmp_path / "full"
    full.mkdir()
    (full / "x").write_text("x")
    with pytest.raises(OS.Refused, match="empty folder"):
        OS.refuse_unless_ready(**{**ready, "out": full})


def test_a_result_already_committed_for_this_spec_means_the_look_is_spent(ready):
    (ready["results_dir"] / f"har_oneshot_v1-{OS.SPEC_HASH[:12]}.json").write_text("{}")
    with pytest.raises(OS.Refused, match="look is spent"):
        OS.refuse_unless_ready(**ready)


# ---- the command line --------------------------------------------------------------------------------------------------------------
def parse(*argv):
    from quantdesk.cli import build_parser
    return build_parser().parse_args(["ml", "oneshot", *argv])


@pytest.mark.parametrize("extra", [["--allow-unverified"], ["--profile-end", "2020-01-01"], ["--symbols", "NIFTY"], ["--rtol", "1e-3"], ["--through", "study"],
                                   ["--flip"], ["--readout", "final"], ["--source", "x"], ["--aeron", "x"]])
def test_the_command_takes_three_paths_and_nothing_else(extra, tmp_path):
    from quantdesk.cli import _ml_oneshot
    a = parse("--dataset", str(tmp_path), "--spec", str(SPEC), "--out", str(tmp_path / "o"), *extra)
    with pytest.raises(SystemExit, match="takes --dataset, --spec and --out only"):
        _ml_oneshot(a)


def test_the_command_needs_its_three_paths_and_not_the_default_spec(tmp_path):
    from quantdesk.cli import _ml_oneshot
    for argv in ([], ["--dataset", str(tmp_path)], ["--dataset", str(tmp_path), "--out", str(tmp_path / "o")]):          # the last has the default (locked) spec
        with pytest.raises(SystemExit, match="are required"):
            _ml_oneshot(parse(*argv))


def test_a_refusal_through_the_command_says_no_look_was_spent(tmp_path):
    from quantdesk.cli import _ml_oneshot
    a = parse("--dataset", str(tmp_path), "--spec", str(SPEC), "--out", str(tmp_path / "o"))
    with pytest.raises(SystemExit, match="refused, no look spent"):
        _ml_oneshot(a)


def test_the_cli_offers_no_unverified_flag_to_the_oneshot_action():
    from quantdesk.cli import _ONESHOT_DEFAULTS
    assert "allow_unverified" in _ONESHOT_DEFAULTS and _ONESHOT_DEFAULTS["allow_unverified"] is False


# ---- the table builder takes a supplied profile ---------------------------------------------------------------------------------------
def synth_grid(n_days, seed, start):
    rng = np.random.default_rng(seed)
    days = pd.Index([d.date() for d in pd.bdate_range(start, periods=n_days)])
    u = 1.0 + 2.0 * (np.abs(np.arange(V.N_MIN) - 187) / 187) ** 2
    level = np.exp(0.5 * np.cumsum(rng.normal(0, 0.15, n_days)))
    r = rng.standard_normal((n_days, V.N_MIN)) * 2e-4 * np.sqrt(u)[None, :] * level[:, None]
    return {"days": days, "r": r, "missing": np.zeros((n_days, V.N_MIN), dtype=bool), "opens": 10000.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n_days)))}


def bars_from(g, sym):
    n, m = g["r"].shape
    close = g["opens"][:, None] * np.exp(np.cumsum(g["r"], axis=1))
    start = np.array([pd.Timestamp(f"{d} 09:15", tz=IST).value for d in g["days"]], dtype="int64")[:, None]
    ts = pd.DatetimeIndex((start + np.arange(m, dtype="int64")[None, :] * 60_000_000_000).ravel(), tz="UTC").tz_convert(IST)
    open_ = np.c_[g["opens"], close[:, :-1]]
    return pd.DataFrame({"symbol": sym, "ts": ts, "open": open_.ravel(), "close": close.ravel()})


def test_a_supplied_profile_replaces_the_fit_and_enters_the_identity():
    g = synth_grid(40, 0, "2018-06-01")                                   # 40 sessions: far fewer than MIN_PROFILE_DAYS
    grids = {"SYN": (g["days"], g["r"], g["missing"], g["opens"])}
    prof = {"SYN": list(np.linspace(0.5, 1.5, V.N_MIN))}
    with pytest.raises(ValueError, match="needs"):
        B.build_tables(grids, "2018-12-31", "T1b")                        # no profile: the fit refuses
    t = B.build_tables(grids, "2018-12-31", "T1b", profile=prof)
    assert len(t) and t["in_profile"].all()                                # every session is up to profile_end
    base = B.recipe(["SYN"], "2018-12-31")
    assert "profile_sha256" not in base                                    # tables built before this argument keep their names
    withp = B.recipe(["SYN"], "2018-12-31", prof)
    assert withp["profile_sha256"] == B.profile_sha256(prof) and withp != base
    other = {"SYN": list(np.linspace(0.6, 1.4, V.N_MIN))}
    assert B.profile_sha256(other) != B.profile_sha256(prof)


@pytest.mark.parametrize("bad", [[1.0] * 10, [0.0] * V.N_MIN, [float("nan")] * V.N_MIN])
def test_a_supplied_profile_must_be_n_min_finite_positive_numbers(bad):
    g = synth_grid(30, 0, "2018-06-01")
    with pytest.raises(ValueError, match="supplied profile"):
        B.build_tables({"SYN": (g["days"], g["r"], g["missing"], g["opens"])}, "2018-12-31", "T1b", profile={"SYN": bad})
    with pytest.raises(ValueError, match="supplied profile"):
        B.build_tables({"SYN": (g["days"], g["r"], g["missing"], g["opens"])}, "2018-12-31", "T1b", profile={"OTHER": [1.0] * V.N_MIN})


def test_the_supplied_profile_is_what_b_seasonal_uses():
    g = synth_grid(40, 1, "2018-06-01")
    grids = {"SYN": (g["days"], g["r"], g["missing"], g["opens"])}
    flat = {"SYN": [1.0] * V.N_MIN}
    t = B.build_tables(grids, "2018-12-31", "T1b", profile=flat)
    ref = V.rows("SYN", g["days"], g["r"], g["missing"], g["opens"], np.ones(V.N_MIN))
    ref = ref.assign(day=ref["day"].map(str)).sort_values(["day", "m", "horizon"]).reset_index(drop=True)
    got = t.sort_values(["day", "m", "horizon"]).reset_index(drop=True)
    assert np.allclose(got["F_B"].to_numpy(), ref["F_B"].to_numpy()) and len(got) == len(ref)


# ---- the run, end to end on a synthetic dataset ---------------------------------------------------------------------------------------
class Loader:
    def __init__(self, grids, digest, drop_open=None):
        bars = pd.concat([bars_from(g, s) for s, g in grids.items()], ignore_index=True)
        for sym, days in (drop_open or {}).items():                              # a leading-gap session: its 09:15 bar is missing
            opens = {pd.Timestamp(f"{d} 09:15", tz=IST) for d in days}
            bars = bars[~((bars["symbol"] == sym) & bars["ts"].isin(opens))]
        self.bars, self.digest, self.calls = bars.reset_index(drop=True), digest, []

    def __call__(self, ds, symbols, use, allow_unverified=False, expected_digest=None):
        self.calls.append({"allow_unverified": allow_unverified, "expected_digest": expected_digest, "use": use})
        out = self.bars[self.bars["symbol"].isin(symbols)].copy()
        out.attrs.update({"dataset": "synthetic", "digest": self.digest, "status": I.UNVERIFIED, "tier": "T1b", "source": "stub://", "not_for": "no options",
                          "excluded_review": [], "admitted_reviewed": []})
        return out


def fresh_ds(synth, name):
    """A copy of the synthetic dataset folder: the run writes its marker beside the dataset, so each run gets its own."""
    import shutil
    dst = synth["tmp"] / name
    shutil.copytree(synth["ds"], dst)
    return dst


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("oneshot")
    grids = {s: synth_grid(380, seed, "2022-01-03") for seed, s in enumerate(OS.SYMBOLS)}
    art = {"schema": 1, "model": "C_har", "symbols": {}}
    for s, g in grids.items():
        p = V.profile(g["r"] ** 2)
        art["symbols"][s] = {"profile": p.tolist(), "fit": {h: {"beta": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0], "smear": 1.0} for h in V.HORIZONS},
                             "sessions": 100, "trained_through": "2018-12-31"}
    art_path = tmp / "vol_har_v1.json"
    art_path.write_text(json.dumps(art))
    ds, man, pins = make_dataset(tmp)
    lock = tmp / "lock.json"
    lock.write_text(json.dumps(locked_like(0.0, 0.0)))
    pins = OS.Pins(artifact_sha256=sha(art_path), dataset_digest=pins.dataset_digest, record_sha256=pins.record_sha256, control_tolerance=1e9)
    results = tmp / "results"
    results.mkdir()
    return {"tmp": tmp, "grids": grids, "ds": ds, "pins": pins, "art": art_path, "lock": lock, "results": results,
            "loader": Loader(grids, pins.dataset_digest)}


def run_kw(synth, out, dsname, **over):
    kw = dict(dataset=fresh_ds(synth, dsname), spec_path=SPEC, out=out, say=lambda *_: None, pins=synth["pins"], loader=synth["loader"], amendment=AMEND,
              criteria=REPO / "docs" / "ml" / "P0_6_criteria_v2.md", artifact=synth["art"], lock_result=synth["lock"], results_dir=synth["results"], commit=CLEAN)
    kw.update(over)
    return kw


OK_CONTROL = lambda ctrl, locked, tol=0: {"tolerance": tol, "cells": {}, "failed": [], "ok": True}      # the control is tested above; synthetic data cannot match the lock


@pytest.fixture(scope="module")
def ran(synth):
    out = synth["tmp"] / "ran"
    seen = []
    orig = OS.with_frozen_forecast

    def watch(table, art):
        marker = out / f"har_oneshot_v1-{OS.SPEC_HASH[:12]}.marker.json"
        seen.append({"min": table["day"].min(), "max": table["day"].max(), "marker": marker.exists()})
        return orig(table, art)
    kw = run_kw(synth, out, "ds_ran")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(OS, "with_frozen_forecast", watch)
        mp.setattr(OS, "control", OK_CONTROL)
        res = OS.run(**kw)
    return {"out": out, "res": res, "seen": seen, "ds": kw["dataset"]}


def stem():
    return f"har_oneshot_v1-{OS.SPEC_HASH[:12]}"


def test_the_run_writes_a_marker_a_result_and_a_report_and_nothing_into_the_repo(ran, synth):
    out = ran["out"]
    for suffix in (".marker.json", ".json", ".md"):
        assert (out / f"{stem()}{suffix}").is_file()
    assert (ran["ds"] / f"{stem()}.marker.json").is_file()                                      # the marker beside the dataset, where the next run looks
    assert json.loads((ran["ds"] / f"{stem()}.marker.json").read_text()) == json.loads((out / f"{stem()}.marker.json").read_text())
    res = ran["res"]
    assert res["verdict"] in ("PASS", "MIXED", "KILL") and len(res["primary"]["cells"]) == 8


def test_the_window_gets_no_forecast_before_the_marker_and_the_control_none_after_its_period(ran):
    ctrl_call, win_call = ran["seen"]
    assert ctrl_call["max"] <= OS.CONTROL_END and not ctrl_call["marker"]                  # the control's rows end on the last spent day; no marker yet
    assert win_call["min"] >= OS.WINDOW_START and win_call["marker"]                         # the window's rows are first touched after the marker is on disk


def test_the_report_carries_the_registered_not_for_and_use_if_passed_above_the_numbers(ran):
    out = ran["out"]
    md, js = (out / f"{stem()}.md").read_text(), json.loads((out / f"{stem()}.json").read_text())
    spec = json.loads(SPEC.read_text())
    assert js["not_for"] == spec["not_for"] and js["use_if_passed"] == spec["use_if_passed"]
    assert spec["not_for"] in md and spec["use_if_passed"] in md
    assert md.index(spec["not_for"]) < md.index("| cell |") and md.index(spec["use_if_passed"]) < md.index("| cell |")


def test_the_label_is_unverified_everywhere_and_the_sentence_heads_the_report_and_closes_it(ran):
    out, res = ran["out"], ran["res"]
    md, js = (out / f"{stem()}.md").read_text(), (out / f"{stem()}.json").read_text()
    sentence = OS.mandatory_sentence(AMEND)
    assert res["evidence"] == "external_unverified" and res["caveat"] == sentence
    assert "external_verified" not in md and "external_verified" not in js
    assert md.startswith(f"> {sentence}") and md.rstrip().endswith(f"> {sentence}") and md.index(sentence) < md.index("| cell |")
    assert res["outcome_statement"] == f"{res['verdict']}. {sentence}" and res["record_sha256"] in md
    keys = list(json.loads(js))
    assert keys.index("caveat") < keys.index("verdict") and keys.index("outcome_statement") < keys.index("primary")       # the sentence precedes any outcome in the JSON too


def test_the_header_records_every_pin_and_both_commits(ran, synth):
    res = ran["res"]
    assert res["spec_sha256"] == OS.SPEC_HASH and res["spec_file_sha256"] == OS.SPEC_FILE_SHA256 and res["code_commit"] == "c0ffee0" and res["route"] == "amendment_1"
    assert res["artifact_sha256"] == synth["pins"].artifact_sha256 and res["amendment_sha256"] == OS.AMENDMENT_SHA256
    assert res["criteria_v2_sha256"] == OS.CRITERIA_V2_SHA256 and res["record_sha256"] == synth["pins"].record_sha256
    assert res["amendment_commit"] and res["criteria_v2_commit"] and res["lock_result_sha256"] == sha(synth["lock"])
    assert res["dataset_digest"] == synth["pins"].dataset_digest and res["dataset_status"] == I.UNVERIFIED
    assert set(res["tables"]) == {"primary", "refit"} and res["tables"]["primary"] != res["tables"]["refit"]


def test_the_loader_is_always_asked_for_the_pinned_digest(synth, ran):
    calls = synth["loader"].calls
    assert calls and all(c["expected_digest"] == synth["pins"].dataset_digest and c["allow_unverified"] is True and c["use"] == "regime_research" for c in calls)


def test_the_primary_table_is_built_on_the_frozen_profile_and_the_refit_table_on_its_own(ran, synth):
    root = ran["out"] / "tables" / "m1"
    mans = {p.name: json.loads((p / "manifest.json").read_text()) for p in root.iterdir()}
    prim = mans[ran["res"]["tables"]["primary"]]["recipe"]
    refit = mans[ran["res"]["tables"]["refit"]]["recipe"]
    assert prim["profile_end"] == OS.PROFILE_END and "profile_sha256" in prim
    assert refit["profile_end"] == OS.REFIT_PROFILE_END and "profile_sha256" not in refit


def test_the_secondary_tables_the_refit_coefficients_and_its_profile_are_in_the_result(ran):
    res = ran["res"]
    sec = res["secondary"]
    assert set(sec["cells"]) == set(res["primary"]["cells"]) and all("refit" in c for c in sec["cells"].values())
    assert all(set(c["C_vs_A_lags"]) == {"10", "20"} and "daily_gain_autocorr_lags_1_to_5" in c for c in sec["cells"].values())
    assert res["pooled_c_vs_b"]["dates"] > 10 and set(sec["by_year"]["NIFTY 30m"]) == {"2023"}
    assert res["refit"]["profile_end"] == OS.REFIT_PROFILE_END and set(res["refit"]["fits"]) == set(OS.SYMBOLS)
    assert all(len(res["refit"]["profile"][s]) == V.N_MIN and min(res["refit"]["profile"][s]) > 0 for s in OS.SYMBOLS)
    assert res["leading_gap_sessions_dropped"] == {}
    assert sum(res["rows_by_symbol_year"].values()) > 0 and all(k.endswith(" 2023") for k in res["rows_by_symbol_year"])


def test_frozen_coefficients_are_copied_unchanged_into_the_result(ran, synth):
    art = json.loads(synth["art"].read_text())
    for s in OS.SYMBOLS:
        assert ran["res"]["frozen"]["fit"][s] == art["symbols"][s]["fit"] and ran["res"]["frozen"]["profile"][s] == art["symbols"][s]["profile"]


def test_the_accounting_is_by_slice_and_by_rule_and_does_not_count_the_profile_window_as_lost(ran):
    acc = ran["res"]["accounting"]
    for part in ("window", "control_period"):
        for s in OS.SYMBOLS:
            a = acc[part]["symbols"][s]
            assert a["reconciles"] and a["rows_kept"] > 0 and set(a["rows_removed"]) == {"feature_lookback_rule", "label_window_over_20pct_missing", "leading_gap_filter"}
            assert a["rows_possible"] == acc[part]["rows_possible_per_session"] * a["sessions_in_grid"]
            assert all(x["day"] >= (OS.WINDOW_START if part == "window" else OS.CONTROL_START) for x in a["sessions_without_rows"])
    w = acc["window"]["symbols"]["NIFTY"]
    assert w["sessions_with_rows"] == w["sessions_in_grid"] and w["sessions_without_rows"] == [] and set(w["sessions_with_rows_by_year"]) == {"2023"}
    c = acc["control_period"]["symbols"]["NIFTY"]
    assert c["sessions_in_grid"] > 200 and c["sessions_without_rows"][0]["why"].startswith("feature lookback")                   # the first 5 sessions of the series, said as such


def test_a_second_run_into_the_same_folder_is_refused(ran, synth):
    with pytest.raises(OS.Refused, match="empty folder"):
        OS.run(**run_kw(synth, ran["out"], "ds_again", dataset=ran["ds"]))


def test_the_marker_beside_the_dataset_refuses_a_second_run_into_a_new_folder(ran, synth):
    with pytest.raises(OS.Refused, match="the look is spent"):
        OS.run(**run_kw(synth, synth["tmp"] / "another_folder", "ds_unused", dataset=ran["ds"]))
    assert not (synth["tmp"] / "another_folder").exists() or not any((synth["tmp"] / "another_folder").iterdir())


def test_a_failed_control_stops_before_any_marker_and_spends_no_look(synth):
    out = synth["tmp"] / "ctrl_fail"
    kw = run_kw(synth, out, "ds_ctrl", pins=OS.Pins(artifact_sha256=synth["pins"].artifact_sha256, dataset_digest=synth["pins"].dataset_digest,
                                                    record_sha256=synth["pins"].record_sha256, control_tolerance=0.0))
    with pytest.raises(OS.ControlFailed, match="no look is spent") as e:
        OS.run(**kw)
    assert "locked" in str(e.value) and "spent-period numbers" in str(e.value)                      # the cause can be looked for
    assert not list(out.glob("*.marker.json")) and not list(out.glob("har_oneshot_v1-*.json")) and not list(out.glob("*.md"))
    assert not list(kw["dataset"].glob("*.marker.json"))


def test_a_crash_after_the_marker_keeps_both_markers_saves_a_log_and_writes_no_result(synth):
    out = synth["tmp"] / "crash"
    kw = run_kw(synth, out, "ds_crash")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(OS, "control", OK_CONTROL)
        mp.setattr(OS, "primary", lambda win: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(OS.CrashAfterMarker, match="RuntimeError") as e:
            OS.run(**kw)
    assert "the look is spent" in str(e.value) and "crash log" in str(e.value)
    assert "boom" not in str(e.value)                                                          # the detail stays in the log: a message could carry a value
    assert (out / f"{stem()}.marker.json").is_file() and (kw["dataset"] / f"{stem()}.marker.json").is_file()
    assert "boom" in (out / f"{stem()}.crash.txt").read_text() and "Traceback" in (out / f"{stem()}.crash.txt").read_text()
    assert not (out / f"{stem()}.json").exists() and not (out / f"{stem()}.md").exists()
    with pytest.raises(OS.Refused, match="the look is spent"):                                   # and the next run is refused until a person moves the marker
        OS.run(**run_kw(synth, synth["tmp"] / "after_crash", "ds_unused2", dataset=kw["dataset"]))


def test_a_crash_message_does_not_claim_a_log_that_could_not_be_written(synth):
    out = synth["tmp"] / "crash_nolog"
    kw = run_kw(synth, out, "ds_nolog")
    real = Path.write_text

    def no_log(self, *a, **k):
        if self.name.endswith(".crash.txt"):
            raise OSError("read-only")
        return real(self, *a, **k)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(OS, "control", OK_CONTROL)
        mp.setattr(OS, "primary", lambda win: (_ for _ in ()).throw(RuntimeError("boom")))
        mp.setattr(Path, "write_text", no_log)
        with pytest.raises(OS.CrashAfterMarker) as e:
            OS.run(**kw)
    msg = str(e.value)
    assert "the look is spent" in msg and "could not be written" in msg and "boom" not in msg and "and this log" not in msg
    assert not (out / f"{stem()}.crash.txt").exists() and (kw["dataset"] / f"{stem()}.marker.json").is_file()


def test_the_report_labels_use_if_passed_as_the_registered_text_not_as_a_condition_on_this_outcome(ran):
    md = (ran["out"] / f"{stem()}.md").read_text()
    assert "**Registered use_if_passed (verbatim from the spec; its last sentence holds for every outcome):**" in md and "**If passed:**" not in md


def test_a_render_failure_happens_before_any_result_file_exists(synth):
    out = synth["tmp"] / "render_fail"
    kw = run_kw(synth, out, "ds_render")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(OS, "control", OK_CONTROL)
        mp.setattr(OS, "render", lambda r: (_ for _ in ()).throw(ValueError("cannot render")))
        with pytest.raises(OS.CrashAfterMarker, match="ValueError"):
            OS.run(**kw)
    assert not (out / f"{stem()}.json").exists() and not (out / f"{stem()}.md").exists() and list(out.glob("*.tmp")) == []


def test_the_report_renders_when_a_statistic_is_missing():
    assert OS._f(None) == "n/a" and OS._f(float("nan"), ".3g") == "n/a" and OS._f(1.23456, ".2f") == "1.23" and OS._f("x", ".2f") == "n/a"


def test_nothing_about_the_window_is_printed_before_the_result_is_written(synth):
    said = []
    out = synth["tmp"] / "quiet"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(OS, "control", OK_CONTROL)
        res = OS.run(**run_kw(synth, out, "ds_quiet", say=said.append))
    text = "\n".join(said).lower()
    assert said and all(w not in text for w in ("qlike", "verdict", res["verdict"].lower() + " ", "dm_t", "p_holm", "loss"))


def test_the_command_line_prints_the_outcome_with_the_sentence(monkeypatch, capsys, tmp_path):
    from quantdesk.cli import _ml_oneshot
    sentence = OS.mandatory_sentence(AMEND)
    monkeypatch.setattr(OS, "run", lambda *a, **k: {"spec": "har_oneshot_v1", "outcome_statement": f"KILL. {sentence}"})
    _ml_oneshot(parse("--dataset", str(tmp_path), "--spec", str(SPEC), "--out", str(tmp_path / "o")))
    printed = capsys.readouterr().out
    assert "KILL" in printed and sentence in printed


def test_refit_forecast_refuses_a_window_row_marked_in_profile():
    t = pd.DataFrame({"symbol": ["NIFTY"] * 4, "day": ["2023-02-27", "2023-02-28", "2023-03-01", "2023-03-02"], "m": 15, "horizon": "30m",
                      "session": [1, 2, 3, 4], "in_profile": [True, True, True, False]})
    with pytest.raises(S.LeakError, match="window row is marked in_profile"):
        OS.refit_forecast(t, t.iloc[2:], {})


def test_the_two_slices_include_both_ends_and_nothing_beyond():
    t = pd.DataFrame({"day": ["2018-12-31", "2019-01-01", "2023-02-28", "2023-03-01", "2026-05-14", "2026-05-15"]})
    assert list(OS.control_slice(t)["day"]) == ["2019-01-01", "2023-02-28"]
    assert list(OS.window_slice(t)["day"]) == ["2023-03-01", "2026-05-14"]


def test_the_commit_of_the_amendment_and_of_the_criteria_must_be_known(ready, monkeypatch):
    monkeypatch.setattr(OS, "_git_commit_of", lambda path: None)
    with pytest.raises(OS.Refused, match="commit of the amendment or of the criteria"):
        OS.refuse_unless_ready(**ready)


def test_an_unreadable_pinned_file_is_a_refusal_not_a_traceback(ready, tmp_path):
    with pytest.raises(OS.Refused, match="cannot be read"):
        OS.refuse_unless_ready(**{**ready, "criteria": tmp_path / "missing.md"})


def test_the_marker_beside_the_dataset_is_found_by_the_refusals(ready):
    (ready["ds"] / f"{stem()}.marker.json").write_text("{}")
    with pytest.raises(OS.Refused, match="the look is spent"):
        OS.refuse_unless_ready(**ready)


# ---- a leading-gap session through the whole run ----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def gap_run(synth):
    """NIFTY has a session without a 09:15 bar inside the spent period (ordinal 150) and one inside the window (ordinal 330)."""
    g = synth["grids"]["NIFTY"]["days"]
    gap_days = [str(g[150]), str(g[330])]
    loader = Loader(synth["grids"], synth["pins"].dataset_digest, drop_open={"NIFTY": gap_days})
    out = synth["tmp"] / "gap_run"
    seen = {"control_sessions": None, "train_sessions": {}}
    orig_fit = V.fit_c

    def spy_fit(train):
        seen["train_sessions"][str(train["symbol"].iloc[0])] = set(train["session"])
        return orig_fit(train)

    def spy_control(ctrl, locked, tol=0):
        seen["control_sessions"] = set(ctrl.loc[ctrl["symbol"] == "NIFTY", "session"])
        return OK_CONTROL(ctrl, locked, tol)
    kw = run_kw(synth, out, "ds_gap", loader=loader)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(OS, "control", spy_control)
        mp.setattr(V, "fit_c", spy_fit)
        res = OS.run(**kw)
    return {"res": res, "seen": seen, "days": gap_days, "loader": loader, "out": out}


def test_a_leading_gap_session_and_the_next_five_are_out_of_the_control_the_refit_training_and_the_scoring(gap_run):
    res, seen = gap_run["res"], gap_run["seen"]
    assert res["leading_gap_sessions_dropped"] == {"NIFTY": gap_run["days"]}                       # listed as dates, not ordinals
    gone = set(range(150, 156))
    assert seen["control_sessions"] and not (seen["control_sessions"] & gone)                       # the control does not score them
    assert set(seen["train_sessions"]) == {"NIFTY", "BANKNIFTY"}
    assert not (seen["train_sessions"]["NIFTY"] & gone)                                              # the refit does not train on them
    assert gone <= seen["train_sessions"]["BANKNIFTY"]                                               # and the other symbol, with no gap, keeps those sessions
    w = res["accounting"]["window"]["symbols"]["NIFTY"]
    dropped = [x for x in w["sessions_without_rows"] if x["why"] == "leading-gap filter"]
    assert len(dropped) == 6 and w["rows_removed"]["leading_gap_filter"] == 6 * res["accounting"]["window"]["rows_possible_per_session"] and w["reconciles"]
    c = res["accounting"]["control_period"]["symbols"]["NIFTY"]
    assert c["rows_removed"]["leading_gap_filter"] == 6 * res["accounting"]["control_period"]["rows_possible_per_session"] and c["reconciles"]


def test_the_tables_of_a_run_with_a_gap_were_built_with_the_gap_allowed_and_the_other_symbol_is_untouched(gap_run):
    w = gap_run["res"]["accounting"]["window"]["symbols"]["BANKNIFTY"]
    assert w["rows_removed"]["leading_gap_filter"] == 0 and w["sessions_without_rows"] == []


# ---- the spent-period rehearsal ------------------------------------------------------------------------------------------------------
def test_the_spent_period_rehearsal_never_builds_holds_or_scores_a_window_row(synth):
    out = synth["tmp"] / "rehearsal"
    res = OS.rehearse_control(synth["ds"], out, say=lambda *_: None, pins=synth["pins"], loader=synth["loader"], artifact=synth["art"], lock_result=synth["lock"])
    assert res["control"]["ok"] and res["last_day"] <= OS.CONTROL_END and res["rows"] > 0
    man = json.loads(next((out / "tables" / "m1").iterdir()).joinpath("manifest.json").read_text())
    assert all(last <= OS.CONTROL_END for first, last in man["days"].values())                                  # the stored table ends on the last spent day
    assert not list(out.rglob("*.marker.json")) and not list(out.rglob("har_oneshot_v1-*"))                       # no marker, no result: no look is spent
    assert not list(synth["ds"].glob("*.marker.json"))                                                          # and none beside the dataset
    assert all(c["allow_unverified"] is True for c in synth["loader"].calls)


def test_the_rehearsal_reports_a_failing_control_instead_of_hiding_it(synth):
    res = OS.rehearse_control(synth["ds"], synth["tmp"] / "rehearsal_bad", say=lambda *_: None, loader=synth["loader"], artifact=synth["art"],
                              lock_result=synth["lock"], pins=OS.Pins(artifact_sha256=synth["pins"].artifact_sha256, dataset_digest=synth["pins"].dataset_digest,
                                                                      record_sha256=synth["pins"].record_sha256, control_tolerance=0.0))
    assert not res["control"]["ok"] and len(res["control"]["failed"]) == 8


def test_the_rehearsal_has_the_same_refusals_as_the_run(synth, tmp_path):
    with pytest.raises(OS.Refused, match="git working tree"):
        OS.rehearse_control(synth["ds"], REPO / "runtime" / "never_created", loader=synth["loader"], pins=synth["pins"], artifact=synth["art"])
    other = tmp_path / "other.json"
    other.write_text("{ }")
    with pytest.raises(OS.Refused, match="pinned artifact"):
        OS.rehearse_control(synth["ds"], tmp_path / "o", loader=synth["loader"], pins=synth["pins"], artifact=other)
    (tmp_path / "x").mkdir()
    bad_ds, _, bad_pins = make_dataset(tmp_path / "x", raw_edit=b" ")
    with pytest.raises(OS.Refused, match="not the P0.6 version 2 record"):
        OS.rehearse_control(bad_ds, tmp_path / "o2", loader=synth["loader"], pins=OS.Pins(artifact_sha256=synth["pins"].artifact_sha256, dataset_digest=bad_pins.dataset_digest,
                                                                                         record_sha256=bad_pins.record_sha256), artifact=synth["art"])


def test_a_failed_second_link_leaves_neither_result_file(tmp_path, monkeypatch):
    real = OS.os.link
    calls = []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(src, dst)
    monkeypatch.setattr(OS.os, "link", flaky)
    with pytest.raises(OSError, match="disk full"):
        OS._write_pair(tmp_path, "r", "{}", "# md")
    assert list(tmp_path.iterdir()) == []                                                    # the first file was taken back; no temp file is left either


def test_a_failure_writing_the_out_folder_marker_is_a_crash_after_the_look_is_spent(synth):
    out = synth["tmp"] / "out_marker_fail"
    kw = run_kw(synth, out, "ds_outmarker")
    real = OS._write_once

    def only_dataset_marker(path, text):
        if Path(path).parent == out:
            raise OSError("out folder not writable")
        return real(path, text)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(OS, "control", OK_CONTROL)
        mp.setattr(OS, "_write_once", only_dataset_marker)
        with pytest.raises(OS.CrashAfterMarker, match="the look is spent"):
            OS.run(**kw)
    assert (kw["dataset"] / f"{stem()}.marker.json").is_file()                               # the look is recorded where the next run looks
    with pytest.raises(OS.Refused, match="the look is spent"):
        OS.run(**run_kw(synth, synth["tmp"] / "after_out_marker_fail", "ds_unused3", dataset=kw["dataset"]))


def test_a_session_with_no_row_that_the_lookback_rule_explains_is_labelled_so_even_inside_a_gap_range():
    days = pd.Index([d.date() for d in pd.bdate_range("2023-02-20", periods=12)])
    miss = np.zeros((12, V.N_MIN), dtype=bool)
    miss[2, 0] = True                                                                         # a gap at ordinal 2, whose range 2..7 includes sessions 2 to 4 that the lookback rule already empties
    g = {s: (days, np.zeros((12, V.N_MIN)), miss if s == "NIFTY" else np.zeros_like(miss), np.full(12, 100.0)) for s in OS.SYMBOLS}
    empty = pd.DataFrame({"symbol": pd.Series([], dtype=object), "day": pd.Series([], dtype=object), "session": pd.Series([], dtype="int64")})
    a = OS.slice_accounting(g, empty, empty, "2023-02-20", "2023-03-31")["symbols"]["NIFTY"]
    whys = {x["day"]: x["why"] for x in a["sessions_without_rows"]}
    assert whys[str(days[2])].startswith("feature lookback") and whys[str(days[3])].startswith("feature lookback")
    assert whys[str(days[6])] == "leading-gap filter" and whys[str(days[7])] == "leading-gap filter"
