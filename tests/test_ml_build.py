"""P0.3: the dataset builder (quantdesk/ml/build.py). The properties that matter:

- it is the study's own code, so its table equals `volstudy.fit_har`'s frame bit for bit;
- no feature uses anything after its decision time (the perturbation canary, run against the real builder);
- the seasonal profile is a fit, so it is fitted on the window up to `profile_end` and every row says whether it is inside it;
- a table that breaks an invariant, or whose files or manifest changed, is refused.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.autolearn import volstudy as V
from quantdesk.data.external_aeron import ForbiddenUse, ImmutableViolation
from quantdesk.ml import build as B
from quantdesk.ml import pit

REPO = Path(B.__file__).resolve().parents[2]
IST = "Asia/Kolkata"
N_DAYS = 320
PROFILE_END = dt.date(2018, 12, 31)


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
    return B.build_tables(grids_of(grid), PROFILE_END)


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
        B.build_tables(grids_of(grid), dt.date(2018, 6, 1))
    B.build_tables(grids_of(grid), "2018-12-31")                                 # an ISO string is accepted too


def test_rows_after_the_window_do_not_depend_on_what_came_after_them(grid):
    """The point-in-time canary, against the real builder. Everything after a decision is replaced with different data and the table
    rebuilt: the decision's features must not move, its labels must."""
    later = [d for d in grid["days"] if d > PROFILE_END][5:60:11]
    keys = [("SYN", str(d), m) for d in later for m in (15, 90, 180, 345)]

    def build(g):
        return B.build_tables(grids_of(g), PROFILE_END)

    def perturb(g, key, rng):
        return pit.perturb_minute_grid(g, (dt.date.fromisoformat(key[1]), key[2]), rng)

    rep = pit.assert_point_in_time(build, grid, keys, perturb, B.KEY, B.FEATURES, B.LABELS)
    assert rep.checked == len(keys) and all(v > 0 for v in rep.label_moved.values())
    assert max(rep.max_rel_diff.values()) <= 1e-9


def test_rows_inside_the_window_do_move_with_the_profile(grid):
    """The reason `in_profile` exists: a row inside the window reads a profile fitted on days after it, so its seasonal features
    legitimately move when later days in the window change. The canary says so, which is why such rows are never scored."""
    d = [x for x in grid["days"] if x <= PROFILE_END][20]
    rep = pit.check_point_in_time(lambda g: B.build_tables(grids_of(g), PROFILE_END), grid, [("SYN", str(d), 90)],
                                  lambda g, k, rng: pit.perturb_minute_grid(g, (dt.date.fromisoformat(k[1]), k[2]), rng),
                                  B.KEY, B.FEATURES, B.LABELS)
    assert {x["feature"] for x in rep.leaks} >= {"F_B", "x_today", "lF_B"}
    assert not {x["feature"] for x in rep.leaks} & {"F_A", "x_prev", "x_prev5", "x_gap"}        # the profile-free features stay clean


def test_the_canary_catches_a_leak_injected_into_the_builder(grid):
    """A builder whose x_prev is the label itself must fail the canary: the injected leak of P0.4's exit test, on this table."""
    def leaky(g):
        t = B.build_tables(grids_of(g), PROFILE_END)
        return t.assign(x_prev=np.log(np.maximum(t["rv"], V.FLOOR)))

    d = [x for x in grid["days"] if x > PROFILE_END][30]
    with pytest.raises(pit.PointInTimeError, match="leaks"):
        pit.assert_point_in_time(leaky, grid, [("SYN", str(d), 90)],
                                 lambda g, k, rng: pit.perturb_minute_grid(g, (dt.date.fromisoformat(k[1]), k[2]), rng),
                                 B.KEY, B.FEATURES, B.LABELS)


def test_two_builds_are_identical(grid, table):
    again = B.build_tables(grids_of(grid), PROFILE_END)
    assert B.tables_close(table, again, rtol=0, atol=0) == []                    # same machine, same inputs: exactly equal
    assert table.equals(again)


def test_symbols_are_independent_and_sorted(grid):
    other = synth_grid(seed=1)
    both = B.build_tables({"ZZZ": grids_of(other)["SYN"], "AAA": grids_of(grid)["SYN"]}, PROFILE_END)
    assert list(both["symbol"].unique()) == ["AAA", "ZZZ"]
    solo = B.build_tables({"AAA": grids_of(grid)["SYN"]}, PROFILE_END)
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
    base = B.identity("a" * 64, B.recipe(["NIFTY", "BANKNIFTY"], "2022-12-31"))
    assert base == B.identity("a" * 64, B.recipe(["BANKNIFTY", "NIFTY"], "2022-12-31"))        # symbol order is not identity
    assert base != B.identity("b" * 64, B.recipe(["NIFTY", "BANKNIFTY"], "2022-12-31"))        # another dataset
    assert base != B.identity("a" * 64, B.recipe(["NIFTY", "BANKNIFTY"], "2022-12-30"))        # another profile window
    assert base != B.identity("a" * 64, B.recipe(["NIFTY"], "2022-12-31"))                     # another symbol set
    monkeypatch.setattr(V, "N_MIN", V.N_MIN + 1)
    assert base != B.identity("a" * 64, B.recipe(["NIFTY", "BANKNIFTY"], "2022-12-31"))        # another constant


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
    assert folder.parent.name == "m1" and folder.name == man["name"] == f"{B.BUILDER_VERSION}-{B.identity('d' * 64, man['recipe'])}"
    assert man["input"] == {"dataset": "stub", "digest": "d" * 64, "status": "external_unverified", "tier": "T1b", "source": "stub://",
                            "not_for": "options", "excluded_review": ["SYN 2018-03-01"], "admitted_reviewed": []}
    assert man["rows"] == {"SYN": len(table)} and man["scoring_rows"] == int((~table["in_profile"]).sum())
    assert man["recipe"]["profile_end"] == str(PROFILE_END) and man["tolerance"]["rtol"] == 1e-9
    assert man["digest"] == B.manifest_digest(man) and man["table_sha256"] == B.sha256_file(folder / "table.parquet")


def test_the_stored_table_is_the_table(built, table):
    folder, _, _ = built
    back = B.load_table(folder)
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
    assert len(B.load_table(ok)) > 0

    nomanifest = copy_of(built, tmp_path / "a")
    (nomanifest / "manifest.json").unlink()
    with pytest.raises(ImmutableViolation, match="no manifest"):
        B.load_table(nomanifest)

    edited = copy_of(built, tmp_path / "b")
    m = json.loads((edited / "manifest.json").read_text())
    m["input"]["status"] = "external_verified"
    (edited / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ImmutableViolation, match="altered"):
        B.load_table(edited)

    redigested = copy_of(built, tmp_path / "c")                                  # edit the manifest and recompute its digest
    m = json.loads((redigested / "manifest.json").read_text())
    m["input"]["digest"] = "e" * 64
    m["digest"] = B.manifest_digest(m)
    (redigested / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ImmutableViolation, match="folder name"):                 # the identity no longer matches the folder
        B.load_table(redigested)

    renamed = copy_of(built, tmp_path / "d")
    moved = renamed.with_name("ml-build-1-000000000000")
    renamed.rename(moved)
    with pytest.raises(ImmutableViolation, match="folder name"):
        B.load_table(moved)

    flipped = copy_of(built, tmp_path / "e")
    t = pd.read_parquet(flipped / "table.parquet")
    t.loc[5, "rv"] *= 2
    t.to_parquet(flipped / "table.parquet", index=False)
    with pytest.raises(ImmutableViolation, match="table was altered"):
        B.load_table(flipped)

    gone = copy_of(built, tmp_path / "f")
    (gone / "table.parquet").unlink()
    with pytest.raises(ImmutableViolation, match="missing"):
        B.load_table(gone)


def test_load_refuses_a_stored_table_that_breaks_an_invariant(built, tmp_path):
    """A table whose bytes match the manifest but whose rows are wrong (written by a buggy builder) is still refused."""
    bad = copy_of(built, tmp_path)
    t = pd.read_parquet(bad / "table.parquet")
    t.loc[0, "F_A"] = -1.0
    t.to_parquet(bad / "table.parquet", index=False)
    m = json.loads((bad / "manifest.json").read_text())
    m["table_sha256"] = B.sha256_file(bad / "table.parquet")
    m["digest"] = B.manifest_digest(m)
    (bad / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(B.TableError, match="non-positive"):
        B.load_table(bad)


# ---- the boundary ---------------------------------------------------------------------------------------------------
# The builder calls the locked study's code. That reaches, through autolearn.prereg -> evaluate -> features, the desk's pure-computation
# modules below (and options pricing). They hold a data-feed and a broker adapter whose network clients and secrets are used only
# inside methods, never at import. Anything else from the live packages, or any network client, fails this test.
READ_ONLY_TRANSITIVE = {"quantdesk.intraday", "quantdesk.intraday.quant", "quantdesk.intraday.chains", "quantdesk.intraday.feeds",
                        "quantdesk.intraday.orderflow"}
LIVE = {"intraday", "engine", "execution", "journal", "risk", "learnbot", "web", "ops", "strategies", "backtest"}


@pytest.mark.parametrize("module", ["build", "splits", "pit", "reproduce"])
def test_importing_an_ml_module_loads_no_order_journal_risk_or_network_code(module):
    out = subprocess.run([sys.executable, "-c", f"import sys, quantdesk.ml.{module}; print('\\n'.join(sorted(sys.modules)))"],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    loaded = [m for m in out if m.startswith("quantdesk.") and m.split(".")[1] in LIVE and m not in READ_ONLY_TRANSITIVE]
    assert not loaded, loaded
    assert not {"requests", "yfinance", "anthropic", "kiteconnect"} & set(out)


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
        main(["ml", "reproduce", "--dataset", str(tmp_path), "--out", str(REPO / "docs" / "prereg" / "results" / "x")])
