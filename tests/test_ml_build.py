"""P0.3: the dataset builder (quantdesk/ml/build.py). The properties that matter:

- it is the study's own code, so its table equals `volstudy.fit_har`'s frame bit for bit;
- no feature uses anything after its decision time (the perturbation canary, run against the real builder);
- the seasonal profile is a fit, so it is fitted on the window up to `profile_end` and every row says whether it is inside it;
- a table that breaks an invariant, or whose files or manifest changed, is refused.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.autolearn import volstudy as V
from quantdesk.data.external_aeron import ALLOWED_USES, ForbiddenUse, ImmutableViolation
from quantdesk.ml import build as B
from quantdesk.ml import pit

REPO = Path(B.__file__).resolve().parents[2]
IST = "Asia/Kolkata"
N_DAYS = 320
PROFILE_END = dt.date(2018, 12, 31)
TIER = "T1b"
LOAD = lambda f, **k: B.load_table(f, allow_unverified=True, scoring_only=False, **k)         # the integrity checks without the gates


def synth_grid(n_days=N_DAYS, seed=0, start="2018-01-01"):
    """{days, r, missing, opens} like volstudy.grid, with a U-shaped intraday variance and volatility that clusters."""
    rng = np.random.default_rng(seed)
    days = pd.Index([d.date() for d in pd.bdate_range(start, periods=n_days)])
    u = 1.0 + 2.0 * (np.abs(np.arange(V.N_MIN) - 187) / 187) ** 2
    level = np.exp(0.5 * np.cumsum(rng.normal(0, 0.15, n_days)))
    r = rng.standard_normal((n_days, V.N_MIN)) * 2e-4 * np.sqrt(u)[None, :] * level[:, None]
    opens = 10000.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n_days)))
    return {"days": days, "r": r, "missing": np.zeros((n_days, V.N_MIN), dtype=bool), "opens": opens}


def grids_of(g, sym="SYN"):
    return {sym: (g["days"], g["r"], g["missing"], g["opens"])}


@pytest.fixture(scope="module")
def grid():
    return synth_grid()


@pytest.fixture(scope="module")
def table(grid):
    return B.build_tables(grids_of(grid), PROFILE_END, TIER)


# ---- the table ------------------------------------------------------------------------------------------------------
def test_the_table_has_the_declared_columns_and_passes_its_invariants(table):
    assert list(table.columns) == B.COLUMNS
    B.check_table(table)
    assert set(table["horizon"]) == set(V.HORIZONS) and set(table["m"]) <= set(V.DECISIONS)
    assert (table["m"] + table["minutes"] <= V.N_MIN).all()                      # no label reaches past the session
    assert table["in_profile"].dtype == bool


def test_it_is_volstudys_frame_bit_for_bit(grid, table):
    """The builder calls the study's code. `fit_har` with the same training days must give the same frame."""
    days, r, miss, opens = grid["days"], grid["r"], grid["missing"], grid["opens"]
    train = np.array([d <= PROFILE_END for d in days])
    s, _, ref = V.fit_har("SYN", days, r, miss, opens, train)
    ref = ref.assign(day=ref["day"].astype(str)).set_index(B.KEY)
    mine = table.set_index(B.KEY)
    assert len(ref) == len(mine) and set(ref.index) == set(mine.index)
    for c in B.FEATURES + B.LABELS + ["miss_frac", "minutes", "year"]:
        np.testing.assert_array_equal(mine.loc[ref.index, c].to_numpy(), ref[c].to_numpy(), err_msg=c)
    np.testing.assert_array_equal(V.profile((r ** 2)[train]), s)


def test_in_profile_marks_exactly_the_window_the_profile_was_fitted_on(table):
    days = pd.to_datetime(table["day"])
    assert (table["in_profile"] == (days <= pd.Timestamp(PROFILE_END))).all()
    assert table["in_profile"].any() and (~table["in_profile"]).any()


def test_a_profile_from_too_few_sessions_is_refused(grid):
    with pytest.raises(ValueError, match="seasonal profile needs"):
        B.build_tables(grids_of(grid), dt.date(2018, 6, 1), TIER)
    B.build_tables(grids_of(grid), "2018-12-31", TIER)                                 # an ISO string is accepted too


def test_rows_after_the_window_do_not_depend_on_what_came_after_them(grid):
    """The point-in-time canary, against the real builder. Everything after a decision is replaced with different data and the table
    rebuilt: the decision's features must not move, its labels must."""
    later = [d for d in grid["days"] if d > PROFILE_END][5:60:11]
    keys = [("SYN", str(d), m) for d in later for m in (15, 90, 180, 345)]

    def build(g):
        return B.build_tables(grids_of(g), PROFILE_END, TIER)

    def perturb(g, key, rng):
        return pit.perturb_minute_grid(g, (dt.date.fromisoformat(key[1]), key[2]), rng)

    rep = pit.assert_point_in_time(build, grid, keys, perturb, B.KEY, B.FEATURES, B.LABELS)
    assert rep.checked == len(keys) and all(v > 0 for v in rep.label_moved.values())
    assert max(rep.max_rel_diff.values()) <= 1e-9


def test_rows_inside_the_window_do_move_with_the_profile(grid):
    """The reason `in_profile` exists: a row inside the window reads a profile fitted on days after it, so its seasonal features
    legitimately move when later days in the window change. The canary says so, which is why such rows are never scored."""
    d = [x for x in grid["days"] if x <= PROFILE_END][20]
    rep = pit.check_point_in_time(lambda g: B.build_tables(grids_of(g), PROFILE_END, TIER), grid, [("SYN", str(d), 90)],
                                  lambda g, k, rng: pit.perturb_minute_grid(g, (dt.date.fromisoformat(k[1]), k[2]), rng),
                                  B.KEY, B.FEATURES, B.LABELS)
    assert {x["feature"] for x in rep.leaks} >= {"F_B", "x_today", "lF_B"}
    assert not {x["feature"] for x in rep.leaks} & {"F_A", "x_prev", "x_prev5", "x_gap"}        # the profile-free features stay clean


def test_the_canary_catches_a_leak_injected_into_the_builder(grid):
    """A builder whose x_prev is the label itself must fail the canary: the injected leak of P0.4's exit test, on this table."""
    def leaky(g):
        t = B.build_tables(grids_of(g), PROFILE_END, TIER)
        return t.assign(x_prev=np.log(np.maximum(t["rv"], V.FLOOR)))

    d = [x for x in grid["days"] if x > PROFILE_END][30]
    with pytest.raises(pit.PointInTimeError, match="leaks"):
        pit.assert_point_in_time(leaky, grid, [("SYN", str(d), 90)],
                                 lambda g, k, rng: pit.perturb_minute_grid(g, (dt.date.fromisoformat(k[1]), k[2]), rng),
                                 B.KEY, B.FEATURES, B.LABELS)


def test_two_builds_are_identical(grid, table):
    again = B.build_tables(grids_of(grid), PROFILE_END, TIER)
    assert B.tables_close(table, again, rtol=0) == []                    # same machine, same inputs: exactly equal
    assert table.equals(again)


def test_symbols_are_independent_and_sorted(grid):
    other = synth_grid(seed=1)
    both = B.build_tables({"ZZZ": grids_of(other)["SYN"], "AAA": grids_of(grid)["SYN"]}, PROFILE_END, TIER)
    assert list(both["symbol"].unique()) == ["AAA", "ZZZ"]
    solo = B.build_tables({"AAA": grids_of(grid)["SYN"]}, PROFILE_END, TIER)
    assert B.tables_close(both[both["symbol"] == "AAA"].reset_index(drop=True), solo) == []


# ---- the invariants -------------------------------------------------------------------------------------------------
def put(t, col, value, row=0):
    t.loc[t.index[row], col] = value


def past_the_close(t):
    i = t.index[(t["horizon"] == "close").to_numpy().argmax()]                    # a real row, moved to the last decision with a 120-minute window
    t.loc[i, ["m", "horizon", "minutes"]] = [345, "120m", 120]


BROKEN = {                                                                        # name: (how to break a good table, the check that must fire)
    "extra column": (lambda t: t.insert(0, "x", 1), "columns are"),
    "no rows": (lambda t: t.drop(t.index, inplace=True), "no rows"),
    "duplicate row": (lambda t: t.loc.__setitem__(t.index[1], t.iloc[0]), "more than one row"),
    "decision off the grid": (lambda t: put(t, "m", 16), "decision grid"),
    "unknown horizon": (lambda t: put(t, "horizon", "45m"), "declared horizons"),
    "window length": (lambda t: put(t, "minutes", int(t["minutes"].iloc[0]) + 1), "not its horizon"),
    "label past the close": (past_the_close, "past the session"),
    "NaN feature": (lambda t: put(t, "x_prev", np.nan), "x_prev holds a NaN"),
    "infinite label": (lambda t: put(t, "rv", np.inf), "rv holds a NaN or an infinity"),
    "negative variance": (lambda t: put(t, "rv", -1e-6), "negative realised variance"),
    "non-positive forecast": (lambda t: put(t, "F_A", 0.0), "non-positive forecast"),
    "too many missing minutes": (lambda t: put(t, "miss_frac", 0.5), "20% of its minutes"),
    "just over 20% missing": (lambda t: put(t, "miss_frac", 0.2 + 1e-6), "20% of its minutes"),
    "negative missing share": (lambda t: put(t, "miss_frac", -0.01), "20% of its minutes"),
    "NaN log forecast": (lambda t: put(t, "lF_B", np.nan), "lF_B holds a NaN"),
    "NaN return": (lambda t: put(t, "ret", np.nan), "ret holds a NaN"),
    "zero B forecast": (lambda t: put(t, "F_B", 0.0), "non-positive forecast"),
    "blank tier": (lambda t: put(t, "tier", "  "), "without a tier"),
    "missing tier": (lambda t: put(t, "tier", None), "without a tier"),
    "in_profile not boolean": (lambda t: t.__setitem__("in_profile", t["in_profile"].astype(int)), "boolean"),
    "out of order": (lambda t: t.__setitem__("day", t["day"].iloc[::-1].to_numpy()), "order"),
}


@pytest.mark.parametrize("name", sorted(BROKEN))
def test_check_table_refuses(table, name):
    """Each corruption must trip its own check: asserting the message keeps a case from passing because another invariant fired."""
    fn, why = BROKEN[name]
    broken = table.copy()
    fn(broken)
    with pytest.raises(B.TableError, match=why):
        B.check_table(broken)


def test_the_label_past_the_close_case_trips_only_that_check(table):
    """Guard on the mutation above: it must fail for the stated reason, not because a different invariant happened to fire first."""
    t = table[(table["m"] == 345)].iloc[:1].copy()
    t["horizon"], t["minutes"] = "120m", 120
    with pytest.raises(B.TableError, match="past the session"):
        B.check_table(t)


def test_tables_close_semantics(table):
    other = table.copy()
    assert B.tables_close(table, other) == []
    other.loc[3, "rv"] = table.loc[3, "rv"] * (1 + 1e-10)
    assert B.tables_close(table, other) == []                                    # inside the tolerance
    other.loc[3, "rv"] = table.loc[3, "rv"] * (1 + 1e-6)
    assert "rv" in B.tables_close(table, other)[0]                               # outside it
    other = table.copy()
    other.loc[3, "rv"] = np.nan
    assert "rv" in B.tables_close(table, other)[0]                               # a NaN matches only a NaN
    both = table.copy()
    both.loc[3, "rv"] = np.nan
    assert B.tables_close(both, other) == []
    assert "rows" in B.tables_close(table, table.iloc[:-1])[0]
    assert "columns" in B.tables_close(table, table.drop(columns="rv"))[0]
    flipped = table.copy()
    flipped.loc[3, "in_profile"] = not table.loc[3, "in_profile"]
    assert "in_profile" in B.tables_close(table, flipped)[0]                     # booleans and strings must be equal
    renamed = table.copy()
    renamed.loc[3, "horizon"] = "xx"
    assert "horizon" in B.tables_close(table, renamed)[0]


# ---- identity -------------------------------------------------------------------------------------------------------
def test_identity_depends_on_everything_that_makes_the_table(monkeypatch):
    rec = lambda syms=("NIFTY", "BANKNIFTY"), pe="2022-12-31": B.recipe(list(syms), pe)
    base = B.identity("a" * 64, rec(), "external_unverified", "T1b")
    assert base == B.identity("a" * 64, rec(("BANKNIFTY", "NIFTY")), "external_unverified", "T1b")        # symbol order is not identity
    assert base != B.identity("b" * 64, rec(), "external_unverified", "T1b")                           # another dataset
    assert base != B.identity("a" * 64, rec(pe="2022-12-30"), "external_unverified", "T1b")            # another profile window
    assert base != B.identity("a" * 64, rec(("NIFTY",)), "external_unverified", "T1b")                 # another symbol set
    assert base != B.identity("a" * 64, rec(), "external_verified", "T1b")                             # verified is a different table
    assert base != B.identity("a" * 64, rec(), "external_unverified", "T1")                            # another tier
    monkeypatch.setattr(V, "N_MIN", V.N_MIN + 1)
    assert base != B.identity("a" * 64, rec(), "external_unverified", "T1b")                           # another constant


def test_changing_the_code_that_makes_the_rows_changes_the_recipe(monkeypatch):
    before = B.recipe(["X"], "2022-12-31")["code_sha256"]
    real = V.rows

    def rows(*a, **k):                                                            # a different function body
        return real(*a, **k)

    monkeypatch.setattr(V, "rows", rows)
    assert B.recipe(["X"], "2022-12-31")["code_sha256"] != before


# ---- build / load round trip ----------------------------------------------------------------------------------------
def bars_from(g, sym):
    """1-minute bars (ts, open, close) that `volstudy.grid` turns back into the grid g."""
    n, m = g["r"].shape
    close = g["opens"][:, None] * np.exp(np.cumsum(g["r"], axis=1))
    ts = [pd.Timestamp(f"{d} 09:15", tz=IST) + pd.Timedelta(minutes=int(k)) for d in g["days"] for k in range(m)]
    open_ = np.c_[g["opens"], close[:, :-1]]
    return pd.DataFrame({"symbol": sym, "ts": ts, "open": open_.ravel(), "close": close.ravel()})


class StubLoader:
    def __init__(self, grid, sym="SYN", digest="d" * 64, status="external_unverified"):
        self.bars, self.digest, self.status, self.calls = bars_from(grid, sym), digest, status, []

    def __call__(self, ds, symbols, use, allow_unverified=False, expected_digest=None):
        self.calls.append({"ds": ds, "symbols": symbols, "use": use, "allow_unverified": allow_unverified, "expected_digest": expected_digest})
        out = self.bars.copy()
        out.attrs.update({"dataset": "stub", "digest": self.digest, "status": self.status, "tier": "T1b", "source": "stub://",
                          "not_for": "options", "excluded_review": ["SYN 2018-03-01"], "admitted_reviewed": []})
        return out


@pytest.fixture(scope="module")
def built(grid, tmp_path_factory):
    out = tmp_path_factory.mktemp("tables")
    loader = StubLoader(grid)
    return B.build(Path("ds"), ["SYN"], PROFILE_END, out, loader=loader, allow_unverified=True, expected_digest="d" * 64, say=lambda *_: None), loader, out


def test_build_asks_the_loader_for_exactly_the_declared_use_and_passes_its_guards_on(built):
    _, loader, _ = built
    assert loader.calls == [{"ds": Path("ds"), "symbols": ["SYN"], "use": "regime_research", "allow_unverified": True, "expected_digest": "d" * 64}]


def test_the_loader_s_refusal_stops_the_build(grid, tmp_path):
    def refuse(*a, **k):
        raise ForbiddenUse("dataset is external_unverified")

    with pytest.raises(ForbiddenUse):
        B.build(Path("ds"), ["SYN"], PROFILE_END, tmp_path, loader=refuse)
    assert not list(tmp_path.iterdir())                                          # nothing was written


def test_build_writes_a_manifest_that_names_its_inputs(built, grid, table):
    folder, _, _ = built
    man = json.loads((folder / "manifest.json").read_text())
    assert folder.parent.name == "m1" and folder.name == man["name"] == f"{B.BUILDER_VERSION}-{B.identity('d' * 64, man['recipe'], 'external_unverified', 'T1b')}"
    assert man["input"] == {"dataset": "stub", "digest": "d" * 64, "status": "external_unverified", "tier": "T1b", "source": "stub://",
                            "not_for": "options", "excluded_review": ["SYN 2018-03-01"], "admitted_reviewed": []}
    assert man["rows"] == {"SYN": len(table)} and man["scoring_rows"] == int((~table["in_profile"]).sum())
    assert man["recipe"]["profile_end"] == str(PROFILE_END) and man["tolerance"]["rtol"] == 1e-9
    assert man["digest"] == B.manifest_digest(man) and man["table_sha256"] == B.sha256_file(folder / "table.parquet")


def test_the_stored_table_is_the_table(built, table):
    folder, _, _ = built
    back = B.load_table(folder, allow_unverified=True, scoring_only=False)
    assert B.tables_close(back, table, rtol=1e-9) == []                          # via bars and back: equal within the tolerance
    assert back.attrs["input_status"] == "external_unverified" and back.attrs["profile_end"] == str(PROFILE_END)
    assert "options" in back.attrs["not_for"]


def test_building_again_verifies_and_does_not_rewrite(built, grid, capsys):
    folder, loader, out = built
    before = (folder / "table.parquet").stat().st_mtime_ns
    again = B.build(Path("ds"), ["SYN"], PROFILE_END, out, loader=StubLoader(grid), allow_unverified=True, expected_digest="d" * 64)
    assert again == folder and "already built, verified" in capsys.readouterr().out
    assert (folder / "table.parquet").stat().st_mtime_ns == before


def test_a_rebuild_that_differs_from_the_stored_table_is_refused(built, grid):
    folder, _, out = built
    other = StubLoader(synth_grid(seed=99))                                       # same digest claimed, different data
    with pytest.raises(ImmutableViolation, match="differs"):
        B.build(Path("ds"), ["SYN"], PROFILE_END, out, loader=other, allow_unverified=True)


def copy_of(built, tmp_path):
    folder = built[0]
    dst = tmp_path / "m1" / folder.name
    dst.mkdir(parents=True)
    for f in folder.iterdir():
        (dst / f.name).write_bytes(f.read_bytes())
    return dst


def test_load_refuses_every_kind_of_tampering(built, tmp_path):
    ok = copy_of(built, tmp_path / "ok")
    assert len(LOAD(ok)) > 0

    nomanifest = copy_of(built, tmp_path / "a")
    (nomanifest / "manifest.json").unlink()
    with pytest.raises(ImmutableViolation, match="no manifest"):
        LOAD(nomanifest)

    edited = copy_of(built, tmp_path / "b")
    m = json.loads((edited / "manifest.json").read_text())
    m["input"]["status"] = "external_verified"
    (edited / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ImmutableViolation, match="altered"):
        LOAD(edited)

    redigested = copy_of(built, tmp_path / "c")                                  # edit the manifest and recompute its digest
    m = json.loads((redigested / "manifest.json").read_text())
    m["input"]["digest"] = "e" * 64
    m["digest"] = B.manifest_digest(m)
    (redigested / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ImmutableViolation, match="folder name"):                 # the identity no longer matches the folder
        LOAD(redigested)

    renamed = copy_of(built, tmp_path / "d")
    moved = renamed.with_name("ml-build-1-000000000000")
    renamed.rename(moved)
    with pytest.raises(ImmutableViolation, match="folder name"):
        LOAD(moved)

    flipped = copy_of(built, tmp_path / "e")
    t = pd.read_parquet(flipped / "table.parquet")
    t.loc[5, "rv"] *= 2
    t.to_parquet(flipped / "table.parquet", index=False)
    with pytest.raises(ImmutableViolation, match="table was altered"):
        LOAD(flipped)

    gone = copy_of(built, tmp_path / "f")
    (gone / "table.parquet").unlink()
    with pytest.raises(ImmutableViolation, match="missing"):
        LOAD(gone)


def test_load_refuses_a_stored_table_that_breaks_an_invariant(built, tmp_path):
    """A table whose bytes match the manifest but whose rows are wrong (written by a buggy builder) is still refused."""
    bad = copy_of(built, tmp_path)
    t = pd.read_parquet(bad / "table.parquet")
    t.loc[0, "F_A"] = -1.0
    B._write_parquet(t, bad / "table.parquet", "external_unverified", "options")                 # written as the builder would write it
    m = json.loads((bad / "manifest.json").read_text())
    m["table_sha256"] = B.sha256_file(bad / "table.parquet")
    m["digest"] = B.manifest_digest(m)
    (bad / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(B.TableError, match="non-positive"):
        LOAD(bad)


def test_a_table_built_from_unverified_data_cannot_be_relabelled_verified(built, tmp_path):
    """The attack: change the manifest's status and recompute its (public) digest. The status is part of the name the manifest must hash to."""
    bad = copy_of(built, tmp_path)
    m = json.loads((bad / "manifest.json").read_text())
    m["input"]["status"] = "external_verified"
    m["digest"] = B.manifest_digest(m)
    (bad / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ImmutableViolation, match="folder name"):
        LOAD(bad)


def test_the_file_carries_its_own_status_and_restriction(built):
    folder, _, _ = built
    import pyarrow.parquet as pq
    md = pq.read_schema(folder / "table.parquet").metadata
    assert md[B.META_STATUS] == b"external_unverified" and md[B.META_NOT_FOR] == b"options"          # a copy of the bare file still says what it is
    assert B._read_meta(folder / "table.parquet") == {"status": "external_unverified", "not_for": "options"}


def test_a_file_whose_metadata_disagrees_with_its_manifest_is_refused(built, tmp_path):
    """Swap in a file that says 'verified' and fix up the manifest's file hash and digest: the file and the manifest still disagree."""
    bad = copy_of(built, tmp_path)
    t = pd.read_parquet(bad / "table.parquet")
    B._write_parquet(t, bad / "table.parquet", "external_verified", "nothing")
    m = json.loads((bad / "manifest.json").read_text())
    m["table_sha256"] = B.sha256_file(bad / "table.parquet")
    m["digest"] = B.manifest_digest(m)
    (bad / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ImmutableViolation, match="metadata disagrees"):
        LOAD(bad)


def test_load_refuses_a_use_the_dataset_does_not_allow(built):
    folder, _, _ = built
    for use in ("option_strategy", "paper_gate", "promotion", "profitability", ""):
        with pytest.raises(ForbiddenUse, match="refused"):
            LOAD(folder, use=use)
    for use in sorted(ALLOWED_USES):
        assert LOAD(folder, use=use).attrs["use"] == use


# ---- the guards added after review of the first head ------------------------------------------------------------------
def test_every_row_carries_its_tier_and_the_builder_requires_one(grid, table):
    assert set(table["tier"]) == {TIER}
    for bad in ("", "   ", None, 3):
        with pytest.raises(ValueError, match="tier must name"):
            B.build_tables(grids_of(grid), PROFILE_END, bad)


def test_a_session_without_a_bar_at_the_open_is_refused(grid):
    """volstudy.grid back-fills an absent opening bar from a later close; the first features of that session would read the future."""
    miss = grid["missing"].copy()
    miss[40, :20] = True
    g = {**grid, "missing": miss}
    with pytest.raises(ValueError, match="no bar at the open"):
        B.build_tables(grids_of(g), PROFILE_END, TIER)
    miss2 = grid["missing"].copy()
    miss2[40, 5:20] = True                                                        # a hole after the open is the study's business, not a refusal
    B.build_tables(grids_of({**grid, "missing": miss2}), PROFILE_END, TIER)
    assert B.leading_gap_sessions(grids_of(g)) == {"SYN": [str(grid["days"][40])]} and B.leading_gap_sessions(grids_of(grid)) == {"SYN": []}
    # reproducing a result computed that way is possible only by saying so, and the sessions can then be listed
    assert len(B.build_tables(grids_of(g), PROFILE_END, TIER, allow_leading_gap=True)) > 0


def test_the_profile_minimum_is_exactly_250_sessions(grid):
    days = list(grid["days"])
    B.build_tables(grids_of(grid), days[249], TIER)                               # 250 sessions up to and including the 250th
    with pytest.raises(ValueError, match="seasonal profile needs 250"):
        B.build_tables(grids_of(grid), days[248], TIER)                           # 249 are not enough
    assert B.MIN_PROFILE_DAYS == 250


def test_the_log_forecast_is_floored_where_the_forecast_is_tiny():
    g = synth_grid(seed=3)
    tiny = {**g, "r": g["r"] * 1e-7}                                              # forecasts far below the floor
    t = B.build_tables(grids_of(tiny), PROFILE_END, TIER)
    assert (t["F_B"] < V.FLOOR).any()
    np.testing.assert_array_equal(t["lF_B"].to_numpy(), np.log(np.maximum(t["F_B"].to_numpy(), V.FLOOR)))


def test_build_tables_checks_its_own_output(grid, monkeypatch):
    real = V.rows

    def broken(*a, **k):
        d = real(*a, **k)
        d.loc[d.index[0], "rv"] = -1.0
        return d

    monkeypatch.setattr(V, "rows", broken)
    with pytest.raises(B.TableError, match="negative realised variance"):
        B.build_tables(grids_of(grid), PROFILE_END, TIER)


def test_the_miss_frac_boundary_is_20_percent_inclusive(table):
    ok = table.copy()
    put(ok, "miss_frac", 0.2)
    B.check_table(ok)


def test_the_identity_is_12_hex_and_depends_on_the_builder_version_and_the_grid_code(monkeypatch):
    rec = B.recipe(["X"], "2022-12-31")
    ident = B.identity("a" * 64, rec, "external_unverified", "T1b")
    assert len(ident) == 12 and all(c in "0123456789abcdef" for c in ident)
    monkeypatch.setattr(B, "BUILDER_VERSION", "ml-build-2")
    assert B.identity("a" * 64, rec, "external_unverified", "T1b") != ident
    monkeypatch.undo()
    real = V.grid

    def grid(bars1):                                                              # a different function body
        return real(bars1)

    monkeypatch.setattr(V, "grid", grid)
    assert B.recipe(["X"], "2022-12-31")["code_sha256"] != rec["code_sha256"]


def test_tables_close_scales_its_tolerance_to_the_column_and_handles_infinity(table):
    a = pd.DataFrame({"v": [1e-6, 2e-6, 3e-6, 0.0, 1e-6]})
    b = a.copy()
    b.loc[0, "v"] = 1e-6 * (1 + 1e-7)                                             # 1e-7 relative: real drift, not rounding
    assert B.tables_close(a, b) and B.tables_close(a, b, rtol=1e-6) == []
    c = a.copy()
    c.loc[3, "v"] = 1e-16                                                         # noise around a true zero, against a column of 1e-6s
    assert B.tables_close(a, c) == []
    c.loc[3, "v"] = 1e-9                                                          # a thousandth of the column's size: not noise
    assert B.tables_close(a, c)
    inf = pd.DataFrame({"v": [1.0, np.inf, -np.inf]})
    assert B.tables_close(inf, inf.copy()) == []
    assert B.tables_close(inf, pd.DataFrame({"v": [1.0, np.inf, np.inf]}))        # -inf against +inf
    assert B.tables_close(inf, pd.DataFrame({"v": [1.0, 5.0, -np.inf]}))          # inf against a number


def test_sha256_reads_the_whole_file(tmp_path):
    import hashlib
    f = tmp_path / "big.bin"
    data = np.random.default_rng(0).bytes(2_500_000)                              # more than two 1 MiB chunks
    f.write_bytes(data)
    assert B.sha256_file(f) == hashlib.sha256(data).hexdigest()
    f.write_bytes(data[:1 << 20] + b"x" + data[(1 << 20) + 1:])                   # a change after the first chunk
    assert B.sha256_file(f) != hashlib.sha256(data).hexdigest()


def test_t0_t1_are_the_decision_time_and_the_end_of_the_label_in_utc_nanoseconds(table):
    t0, t1 = B.t0_t1(table)
    assert t0.dtype == np.int64 and (t1 > t0).all() and ((t1 - t0) == table["minutes"].to_numpy() * 60 * 10 ** 9).all()
    r = table.iloc[0]
    want = pd.Timestamp(f"{r['day']} 09:15", tz=IST) + pd.Timedelta(minutes=int(r["m"]))
    assert t0[0] == want.tz_convert("UTC").value
    assert (np.diff(t0[table["horizon"] == "30m"]) >= 0).all()                    # the table's order is time order within a horizon


def test_a_cpcv_on_this_tables_shape_leaks_without_the_feature_lookback_embargo(table):
    """The auditor's scenario: x_prev, x_prev5 and the priors read earlier sessions, so a sample just after a test block carries its labels."""
    from quantdesk.ml import splits as S
    t = table[table["horizon"] == "close"].reset_index(drop=True)
    t0, t1 = B.t0_t1(t)
    leaky = S.cpcv(t0, t1, 8, 2, embargo=0)
    S.check_no_overlap(leaky, t0, t1, embargo=0, windows=S.windows_of(leaky, t0, t1))                  # passes the plain verifier...
    with pytest.raises(S.LeakError):
        S.check_no_overlap(leaky, t0, t1, embargo=B.EMBARGO_NS, windows=S.windows_of(leaky, t0, t1))   # ...but not the lookback-aware one
    safe = S.cpcv(t0, t1, 8, 2, embargo=B.EMBARGO_NS)
    S.check_no_overlap(safe, t0, t1, embargo=B.EMBARGO_NS, windows=S.windows_of(safe, t0, t1))
    assert B.FEATURE_LOOKBACK_SESSIONS == V.PRIOR_DAYS == 5 and B.EMBARGO_NS >= 9 * 86_400 * 10 ** 9      # nine calendar days: five sessions over a long weekend and a holiday


def test_scoring_rows_are_the_only_ones_a_fold_may_test_on(table):
    from quantdesk.ml import splits as S
    t0, t1 = B.t0_t1(table)
    folds = S.walk_forward(t0, t1, pd.to_datetime(["2018-03-01", "2018-09-01", "2019-02-01"]))
    with pytest.raises(S.LeakError):
        S.check_test_mask(folds, ~table["in_profile"].to_numpy())                 # the first fold tests on 2018 rows, inside the profile window
    scoring = table["in_profile"].to_numpy() == False                             # noqa: E712
    late = S.walk_forward(t0, t1, pd.to_datetime(["2019-01-15", "2019-02-15"]))
    S.check_test_mask(late, scoring)


# ---- the gates on reading a table -----------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def built_verified(tmp_path_factory):
    g = synth_grid(n_days=320, seed=4, start="2022-01-03")                        # runs to late March 2023: past the reserved window's start
    out = tmp_path_factory.mktemp("verified")
    folder = B.build(Path("ds"), ["SYN"], dt.date(2022, 12, 31), out, loader=StubLoader(g, status="external_verified"), say=lambda *_: None)
    return folder


def test_a_table_from_unverified_data_is_refused_unless_the_caller_accepts_it(built):
    folder, _, _ = built
    with pytest.raises(ForbiddenUse, match="external_unverified"):
        B.load_table(folder)
    with pytest.raises(ForbiddenUse, match="external_unverified"):
        B.load_table(folder, scoring_only=False)
    assert len(B.load_table(folder, allow_unverified=True)) > 0


def test_verified_data_needs_no_acknowledgement_and_the_default_withholds_what_must_not_be_scored(built_verified):
    d = B.load_table(built_verified)
    assert d.attrs["input_status"] == "external_verified" and d.attrs["scoring_only"] is True
    assert not d["in_profile"].any() and (d["day"] < B.RESERVED_FROM).all()                              # neither the profile window nor the reserved one
    full = B.load_table(built_verified, scoring_only=False, reserved_spec=None)
    assert full.attrs["withheld"]["reserved"] > 0 and d.attrs["withheld"]["in_profile"] > 0
    allrows, _ = B._read_checked(built_verified)
    assert len(allrows) == len(d) + d.attrs["withheld"]["in_profile"] + d.attrs["withheld"]["reserved"]


def test_the_reserved_window_is_released_only_to_a_named_spec(built_verified, tmp_path):
    spec = tmp_path / "har_oos_v1.json"
    spec.write_text(json.dumps({"name": "har_oos_v1"}))
    d = B.load_table(built_verified, reserved_spec=spec)
    assert (d["day"] >= B.RESERVED_FROM).any() and d.attrs["reserved_spec"] == "har_oos_v1" and d.attrs["withheld"]["reserved"] == 0
    for bad in (tmp_path / "missing.json", None):
        if bad is not None:
            with pytest.raises(ForbiddenUse, match="stays withheld"):
                B.load_table(built_verified, reserved_spec=bad)
    junk = tmp_path / "junk.json"
    junk.write_text("not json")
    nameless = tmp_path / "nameless.json"
    nameless.write_text(json.dumps({"name": "  "}))
    for bad in (junk, nameless, tmp_path):
        with pytest.raises(ForbiddenUse, match="stays withheld|empty name"):
            B.load_table(built_verified, reserved_spec=bad)


def test_the_manifest_accounts_for_what_the_study_dropped_and_names_the_reserved_window(built, table):
    folder, _, _ = built
    man = json.loads((folder / "manifest.json").read_text())
    acc = man["accounting"]["SYN"]
    per_session = sum(1 for m in V.DECISIONS for h, mins in V.HORIZONS.items() if (V.N_MIN if mins is None else m + mins) <= V.N_MIN)
    assert per_session == 84
    assert acc["sessions_in_grid"] == N_DAYS and acc["sessions_lost"] == 5 and len(acc["lost_first"]) == 5          # the first five lose x_prev5
    assert acc["rows_possible"] == N_DAYS * 84 and acc["rows_kept"] == len(table) and acc["rows_dropped"] == acc["rows_possible"] - len(table)
    assert acc["sessions_with_rows"] == N_DAYS - 5
    assert man["reserved_from"] == B.RESERVED_FROM == "2023-03-01" and man["reserved_rows"] == 0
    assert man["feature_lookback_sessions"] == 5 and man["embargo_ns"] == B.EMBARGO_NS


def test_the_manifest_counts_the_rows_in_the_reserved_window(built_verified):
    man = json.loads((built_verified / "manifest.json").read_text())
    allrows, _ = B._read_checked(built_verified)
    want = int((allrows["day"] >= B.RESERVED_FROM).sum())
    assert want > 0 and man["reserved_rows"] == want and man["reserved_from"] == "2023-03-01"
    assert man["scoring_rows"] == int((~allrows["in_profile"]).sum())


def test_a_file_whose_status_alone_disagrees_with_its_manifest_is_refused(built, tmp_path):
    bad = copy_of(built, tmp_path)
    B._write_parquet(pd.read_parquet(bad / "table.parquet"), bad / "table.parquet", "external_verified", "options")       # the restriction still agrees
    m = json.loads((bad / "manifest.json").read_text())
    m["table_sha256"] = B.sha256_file(bad / "table.parquet")
    m["digest"] = B.manifest_digest(m)
    (bad / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ImmutableViolation, match="about the status"):
        LOAD(bad)


def test_a_file_whose_restriction_alone_disagrees_with_its_manifest_is_refused(built, tmp_path):
    bad = copy_of(built, tmp_path)
    B._write_parquet(pd.read_parquet(bad / "table.parquet"), bad / "table.parquet", "external_unverified", "nothing at all")   # the status still agrees
    m = json.loads((bad / "manifest.json").read_text())
    m["table_sha256"] = B.sha256_file(bad / "table.parquet")
    m["digest"] = B.manifest_digest(m)
    (bad / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ImmutableViolation, match="about the restriction"):
        LOAD(bad)


def test_build_does_not_accept_unverified_data_by_default(grid, tmp_path):
    class Strict(StubLoader):
        def __call__(self, ds, symbols, use, allow_unverified=False, expected_digest=None):
            if self.status != "external_verified" and not allow_unverified:
                raise ForbiddenUse(f"{self.status}: refused")
            return super().__call__(ds, symbols, use, allow_unverified, expected_digest)

    loader = Strict(grid)
    with pytest.raises(ForbiddenUse, match="refused"):
        B.build(Path("ds"), ["SYN"], PROFILE_END, tmp_path, loader=loader)
    assert loader.calls == [] and not list(tmp_path.iterdir())                    # refused before anything was loaded or written
    B.build(Path("ds"), ["SYN"], PROFILE_END, tmp_path, loader=loader, allow_unverified=True, say=lambda *_: None)
    assert [c["allow_unverified"] for c in loader.calls] == [True]


# ---- where a table may be written, and checking its status against the dataset --------------------------------------
def test_tables_are_not_written_where_they_could_be_committed(tmp_path, grid):
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    for bad in (clone, clone / "docs" / "x", clone / "tables"):
        with pytest.raises(ForbiddenUse, match="inside a git working tree"):
            B.refuse_tracked_tree(bad, "the tables folder")
        with pytest.raises(ForbiddenUse, match="inside a git working tree"):
            B.build(Path("ds"), ["SYN"], PROFILE_END, bad, loader=StubLoader(grid), allow_unverified=True, say=lambda *_: None)
    assert not (clone / "docs").exists() and not (clone / "tables").exists()                      # refused before anything was written
    B.refuse_tracked_tree(clone / "runtime" / "ml_tables", "the tables folder")                  # the gitignored runtime folder is the one place allowed
    B.refuse_tracked_tree(clone / "runtime", "the tables folder")
    B.refuse_tracked_tree(tmp_path / "outside" / "anywhere", "the tables folder")
    with pytest.raises(ForbiddenUse):
        B.refuse_tracked_tree(clone / "runtime2", "the tables folder")                           # only the folder named runtime, not a prefix of it
    with pytest.raises(ForbiddenUse):
        B.refuse_tracked_tree(B.REPO / "docs" / "ml_tables", "the tables folder")


def test_the_command_refuses_an_output_folder_inside_the_repository(tmp_path):
    from quantdesk.cli import main
    with pytest.raises(SystemExit, match="ml build: .*inside a git working tree"):
        main(["ml", "build", "--dataset", str(tmp_path), "--profile-end", "2022-12-31", "--out", str(REPO / "docs" / "ml_tables_probe")])
    assert not (REPO / "docs" / "ml_tables_probe").exists()


def make_dataset_dir(tmp_path, digest="d" * 64, status="external_verified", verification=True, name="ds"):
    d = tmp_path / name
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"digest": digest, "status": status}))
    if verification:
        (d / "verification.json").write_text(json.dumps({"digest": digest, "passed": True, "check": "yahoo daily and the aeron7 overlap"}))
    return d


def test_the_status_can_be_re_derived_from_the_dataset_itself(built_verified, built, tmp_path):
    ds = make_dataset_dir(tmp_path)
    assert B.load_table(built_verified, dataset=ds).attrs["input_status"] == "external_verified"                    # still verified: accepted
    no_record = make_dataset_dir(tmp_path, verification=False, name="ds2")                                         # a manifest that only says so
    with pytest.raises(ImmutableViolation, match="says external_verified but the dataset is external_unverified"):
        B.load_table(built_verified, dataset=no_record)
    other = make_dataset_dir(tmp_path, digest="e" * 64, name="ds3")
    with pytest.raises(ImmutableViolation, match="was not built from"):
        B.load_table(built_verified, dataset=other)
    with pytest.raises(ImmutableViolation, match="no readable manifest"):
        B.load_table(built_verified, dataset=tmp_path / "nowhere")
    # a table built while unverified goes stale the day the dataset is verified: it must be rebuilt (and is a different table)
    folder, _, _ = built
    unverified = make_dataset_dir(tmp_path, status="external_unverified", verification=False, name="ds4")
    assert len(B.load_table(folder, allow_unverified=True, dataset=unverified)) > 0
    with pytest.raises(ImmutableViolation, match="rebuild the table"):
        B.load_table(folder, allow_unverified=True, dataset=make_dataset_dir(tmp_path, name="ds5"))


def test_a_full_forgery_is_caught_when_the_caller_names_the_dataset(built, tmp_path):
    """Relabel the table verified everywhere (manifest, file, folder name, hashes): self-consistent, so only the dataset can contradict it."""
    src = copy_of(built, tmp_path / "src")
    m = json.loads((src / "manifest.json").read_text())
    m["input"]["status"] = "external_verified"
    new = f"{m['builder']}-{B.identity(m['input']['digest'], m['recipe'], 'external_verified', m['input']['tier'])}"
    m["name"] = new
    dst = tmp_path / "forged" / new
    dst.mkdir(parents=True)
    B._write_parquet(pd.read_parquet(src / "table.parquet"), dst / "table.parquet", "external_verified", m["input"]["not_for"])
    m["table_sha256"] = B.sha256_file(dst / "table.parquet")
    m["digest"] = B.manifest_digest(m)
    (dst / "manifest.json").write_text(json.dumps(m))
    assert B.load_table(dst, scoring_only=False).attrs["input_status"] == "external_verified"          # on its own, the forgery loads
    honest = make_dataset_dir(tmp_path, status="external_unverified", verification=False, name="honest")
    with pytest.raises(ImmutableViolation, match="says external_verified but the dataset is external_unverified"):
        B.load_table(dst, scoring_only=False, dataset=honest)


# ---- the boundary ---------------------------------------------------------------------------------------------------
# The builder calls the locked study's code. That reaches, through autolearn.prereg -> evaluate -> features, the desk's pure-computation
# modules below (and options pricing, and the data loaders). They hold a data-feed adapter and a broker adapter whose network clients and
# secrets are used only inside methods, never at import. The list is an allowlist: any other quantdesk module loaded by an ml module,
# after it has done its work (reproduce imports the study lazily), fails this test.
ALLOWED_QUANTDESK = {
    "quantdesk", "quantdesk.ml", "quantdesk.autolearn", "quantdesk.core", "quantdesk.data", "quantdesk.intraday", "quantdesk.options",
    "quantdesk.autolearn.evaluate", "quantdesk.autolearn.features", "quantdesk.autolearn.prereg", "quantdesk.autolearn.volstudy",
    "quantdesk.core.calendar", "quantdesk.core.types",
    "quantdesk.data.base", "quantdesk.data.csv_store", "quantdesk.data.external_aeron", "quantdesk.data.synthetic",
    "quantdesk.data.validation", "quantdesk.data.yahoo",
    "quantdesk.intraday.chains", "quantdesk.intraday.feeds", "quantdesk.intraday.orderflow", "quantdesk.intraday.quant",
    "quantdesk.options.chain", "quantdesk.options.pricing", "quantdesk.options.structures", "quantdesk.options.surface"}
NETWORK_AND_BROKER = {"requests", "yfinance", "anthropic", "kiteconnect", "urllib3", "httpx", "aiohttp"}
PROBE = (
    "import sys\n"
    "events = []\n"
    "sys.addaudithook(lambda e, a: events.append(e) if e in ('socket.connect', 'socket.getaddrinfo', 'socket.bind', 'subprocess.Popen') else None)\n"
    "import quantdesk.ml.{module} as M\n"
    "{work}\n"
    "print('EVENTS', sorted(set(events)))\n"
    "print('\\n'.join(sorted(sys.modules)))\n")
WORK = {
    "build": ("import numpy as np, pandas as pd, tempfile, pathlib\n"
              "from quantdesk.ml import intake\n"                                # build() imports it lazily; so does the probe, to see its graph
              "days = pd.Index([d.date() for d in pd.bdate_range('2018-01-01', periods=300)])\n"
              "r = np.random.default_rng(0).standard_normal((300, 375)) * 2e-4\n"
              "ts = [pd.Timestamp(f'{d} 09:15', tz='Asia/Kolkata') + pd.Timedelta(minutes=int(k)) for d in days for k in range(375)]\n"
              "c = (10000 * np.exp(np.cumsum(r, axis=1))).ravel()\n"
              "bars = pd.DataFrame({'symbol': 'S', 'ts': ts, 'open': np.r_[c[:1], c[:-1]], 'close': c})\n"
              "def loader(ds, symbols, use, allow_unverified=False, expected_digest=None):\n"
              "    b = bars.copy()\n"
              "    b.attrs.update({'dataset': 'x', 'digest': 'd' * 64, 'status': 'external_verified', 'tier': 'T1b', 'source': 's', 'not_for': 'n'})\n"
              "    return b\n"
              "out = pathlib.Path(tempfile.mkdtemp())\n"
              "f = M.build(out, ['S'], '2018-12-31', out, loader=loader, say=lambda *a: None)\n"
              "M.load_table(f)"),
    "splits": "import numpy as np\nM.walk_forward(np.arange(10), np.arange(10) + 1, [0, 5, 10])",
    "pit": "pass",
    "study": "pass",                                                         # study imports the builder, the splits and the study at import
    "reproduce": "import quantdesk.autolearn.volstudy",                     # what reproduce() imports when it runs
}


def probe(module, work):
    out = subprocess.run([sys.executable, "-c", PROBE.format(module=module, work=work)], cwd=REPO, capture_output=True, text=True, check=True,
                         env={**os.environ, "PYTHONPATH": str(REPO)}).stdout.splitlines()
    events = next(l for l in out if l.startswith("EVENTS"))
    return events, set(out) - {events}


def stray_of(mods):
    return sorted(m for m in mods if m.startswith("quantdesk") and m not in ALLOWED_QUANTDESK and not m.startswith("quantdesk.ml"))


@pytest.mark.parametrize("module", sorted(WORK))
def test_an_ml_module_after_its_work_has_loaded_only_allowlisted_quantdesk_modules_and_touched_no_network(module):
    events, mods = probe(module, WORK[module])
    assert events == "EVENTS []", events                                          # no socket was opened or resolved, no process started
    assert not stray_of(mods), stray_of(mods)
    assert not NETWORK_AND_BROKER & {m.split(".")[0] for m in mods}
    assert any(m.startswith("quantdesk.ml.") for m in mods)                       # the probe imported what it says it did


def test_the_allowlist_would_catch_a_live_module():
    """The probe is not vacuous: an order-path or risk module imported alongside shows up as stray."""
    for live in ("quantdesk.execution.broker", "quantdesk.risk"):
        events, mods = probe("splits", f"import {live}")
        assert stray_of(mods), live


# ---- the command ----------------------------------------------------------------------------------------------------
def test_the_ml_command_needs_what_each_action_needs(tmp_path):
    from quantdesk.cli import main
    for argv, msg in ((["ml", "import"], "--source is required"), (["ml", "build"], "--dataset and --profile-end"),
                      (["ml", "build", "--dataset", str(tmp_path)], "--dataset and --profile-end"),
                      (["ml", "reproduce"], "--dataset is required")):
        with pytest.raises(SystemExit, match=msg):
            main(argv)


def test_ml_build_refuses_a_folder_without_provenance(tmp_path):
    from quantdesk.cli import main
    with pytest.raises(SystemExit, match="ml build: .*no manifest"):
        main(["ml", "build", "--dataset", str(tmp_path), "--profile-end", "2022-12-31", "--out", str(tmp_path / "o")])


def test_ml_reproduce_refuses_to_write_beside_the_committed_results(tmp_path):
    from quantdesk.cli import main
    with pytest.raises(SystemExit, match="ml reproduce: .*inside"):
        main(["ml", "reproduce", "--through", "study", "--dataset", str(tmp_path), "--out", str(REPO / "docs" / "prereg" / "results" / "x")])
    with pytest.raises(SystemExit, match="applies to --through study only"):
        main(["ml", "reproduce", "--dataset", str(tmp_path), "--out", str(tmp_path / "x")])
