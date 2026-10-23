"""The live HAR volatility forecast (vol_forecast_v1's C_har), in shadow only: it reproduces the study, it looks only at the
past, the desk's trading is identical with the shadow on or off, one record per index per session goes in the journal at
the opening read, missing inputs are a WARN not an exception, and the grading arithmetic is right."""
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.autolearn import volstudy as V
from quantdesk.intraday import harvol, volshadow
from quantdesk.intraday.quant import MIN_PER_YEAR, VolForecaster

IST = "Asia/Kolkata"
DEV_END = dt.date(2018, 12, 31)


# ---- fixtures -----------------------------------------------------------------------------------------------------
def study_grid(seed=3, per_year=45, profile=None, clustered=True):
    """A study-shaped grid (days, r, missing, opens) over 2012-2019: `per_year` consecutive sessions a year."""
    rng = np.random.default_rng(seed)
    prof = profile if profile is not None else 1 + 1.2 * np.exp(-np.arange(375) / 25) + 0.6 * np.exp(-(374 - np.arange(375)) / 40)
    prof = prof / prof.mean()
    days, rs, opens = [], [], []
    px, vol = 20000.0, 0.0
    for y in range(2012, 2020):
        for d in pd.bdate_range(f"{y}-02-01", periods=per_year):
            vol = 0.8 * vol + 0.4 * rng.standard_normal() if clustered else 0.0
            r = rng.standard_normal(375) * 6e-4 * np.exp(0.5 * vol) * np.sqrt(prof)
            o = px * np.exp(rng.normal(0, 3e-3))
            px = o * np.exp(r.sum())
            days.append(d.date()); rs.append(r); opens.append(o)
    r = np.array(rs)
    return pd.Index(days), r, np.zeros(r.shape, bool), np.array(opens)


def to_bars(grid, n_days=7):
    """The last `n_days` sessions of a grid as the desk's 1-minute bars (start-labelled, IST)."""
    days, r, _, opens = grid
    frames = []
    for i in range(len(days) - n_days, len(days)):
        c = opens[i] * np.exp(np.cumsum(r[i]))
        o = np.r_[opens[i], c[:-1]]
        idx = pd.date_range(pd.Timestamp(days[i], tz=IST) + pd.Timedelta(hours=9, minutes=15), periods=375, freq="min")
        frames.append(pd.DataFrame({"open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c, "volume": 0.0}, index=idx))
    return pd.concat(frames)


def at(day, m):
    return pd.Timestamp(day, tz=IST) + pd.Timedelta(hours=9, minutes=15 + m)


# ---- 1. the study is unchanged, and the live model is the study's ---------------------------------------------------
def test_the_shared_fit_leaves_the_studys_numbers_unchanged(tmp_path):
    """Pinned from the study code as it was before fit_har was factored out of run()."""
    spec = json.loads((V.Path(__file__).resolve().parent.parent / "docs/prereg/vol_forecast_v1.json").read_text())
    spec["symbols"] = ["FIX"]
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    rep = V.run(None, None, tmp_path / "spec.json", tmp_path / "res", open_lock=True, say=lambda *a: None, grids={"FIX": study_grid()})
    c = {h: v["dev_mean_qlike"]["C_har"] for h, v in rep["selected"].items()}
    assert c == pytest.approx({"120m": 0.021546887233, "30m": 0.046610208212, "60m": 0.029714307975, "close": 0.022343914496}, abs=1e-9)
    a = {h: v["dev_mean_qlike"]["A_desk"] for h, v in rep["selected"].items()}
    assert a == pytest.approx({"120m": 0.046304414524, "30m": 0.064322801562, "60m": 0.049961372349, "close": 0.040698203854}, abs=1e-9)
    t = rep["lock"]["tests"]["FIX 30m"]
    assert t["scores"]["C_har"]["qlike"] == pytest.approx(0.04545349704336234, rel=1e-9)
    assert t["dm_t"] == pytest.approx(3.929250795454207, rel=1e-9) and t["qlike_gain_pct"] == pytest.approx(34.3780377431439, rel=1e-9)
    assert rep["dev"]["FIX 60m"]["C_har"]["2015"]["log_bias"] == pytest.approx(-0.0705200619826326, rel=1e-9)


@pytest.mark.parametrize("m", [15, 105, 255, 345])
def test_live_har_reproduces_the_study_on_a_fixture(m):
    grid = study_grid()
    days = grid[0]
    day = days[-1]                                                     # a lock-period session (2019)
    train = np.array([d <= DEV_END for d in days])
    s, fit, d = V.fit_har("FIX", *grid, train)                         # the study's own fit and frame
    te = d[(d["day"] == day) & (d["m"] == m)].copy()
    te["F_C"] = V.predict_c(te, fit)
    assert len(te) >= 2
    entry = harvol.fit_coefs({"FIX": grid}, DEV_END)["symbols"]["FIX"]
    res, why = harvol.HarVol(entry).forecast(to_bars(grid), at(day, m))     # the live model on 1-minute bars before `now`
    assert why == "" and res["m"] == m
    assert set(res["var"]) == set(te["horizon"])
    for r in te.itertuples():
        assert res["var"][r.horizon] == pytest.approx(r.F_C, rel=1e-9)
        assert res["minutes"][r.horizon] == r.minutes


def test_coefficients_roundtrip_through_the_file(tmp_path):
    grid = study_grid()
    coefs = harvol.fit_coefs({"FIX": grid}, DEV_END, "vol_forecast_v1", "abc")
    harvol.save_coefs(tmp_path / "sub" / "c.json", coefs)
    back, why = harvol.load_coefs(tmp_path / "sub" / "c.json")
    assert why == "" and back == json.loads(json.dumps(coefs))
    day = grid[0][-1]
    a = harvol.HarVol(coefs["symbols"]["FIX"]).forecast(to_bars(grid), at(day, 105))[0]
    b = harvol.HarVol(back["symbols"]["FIX"]).forecast(to_bars(grid), at(day, 105))[0]
    assert a == b
    assert harvol.load_coefs(tmp_path / "nope.json")[0] is None
    (tmp_path / "bad.json").write_text("{not json")
    assert harvol.load_coefs(tmp_path / "bad.json")[0] is None


# ---- 2. point in time -----------------------------------------------------------------------------------------------
def test_the_fit_uses_nothing_after_its_training_window():
    grid = study_grid()
    days, r, miss, opens = grid
    r2, opens2 = r.copy(), opens.copy()
    late = np.array([d > DEV_END for d in days])
    r2[late] *= 3.0                                                    # rewrite the lock period completely
    opens2[late] *= 1.3
    a = harvol.fit_coefs({"FIX": grid}, DEV_END)["symbols"]["FIX"]
    b = harvol.fit_coefs({"FIX": (days, r2, miss, opens2)}, DEV_END)["symbols"]["FIX"]
    assert a == b
    assert a["trained_through"] == str(max(d for d in days if d <= DEV_END))


def test_a_forecast_looks_only_at_bars_completed_before_now():
    grid = study_grid()
    day = grid[0][-1]
    h = harvol.HarVol(harvol.fit_coefs({"FIX": grid}, DEV_END)["symbols"]["FIX"])
    bars = to_bars(grid)
    now = at(day, 105)
    clean = h.forecast(bars[bars.index < now], now)[0]
    assert clean == h.forecast(bars, now)[0]                           # bars from `now` on (the future) change nothing
    poisoned = bars.copy()
    poisoned.loc[poisoned.index >= now, ["open", "high", "low", "close"]] *= 1.5
    assert h.forecast(poisoned, now)[0] == clean
    assert h.forecast(bars, now - pd.Timedelta(minutes=30))[0]["var"] != clean["var"]      # and it does move with `now`


def test_a_fit_that_is_not_before_the_session_is_refused():
    grid = study_grid()
    coefs = harvol.fit_coefs({"FIX": grid}, DEV_END)
    assert harvol.HarVol.for_session(coefs, "FIX", dt.date(2019, 1, 2))[0] is not None
    through = dt.date.fromisoformat(coefs["symbols"]["FIX"]["trained_through"])
    assert harvol.HarVol.for_session(coefs, "FIX", through + dt.timedelta(days=1))[0] is not None
    h, why = harvol.HarVol.for_session(coefs, "FIX", through)           # a fit that saw the session itself is lookahead
    assert h is None and "not before the session" in why
    assert harvol.HarVol.for_session(coefs, "OTHER", dt.date(2026, 1, 5))[0] is None


def test_unusable_inputs_say_why_instead_of_guessing():
    grid = study_grid()
    day = grid[0][-1]
    h = harvol.HarVol(harvol.fit_coefs({"FIX": grid}, DEV_END)["symbols"]["FIX"])
    bars = to_bars(grid)
    assert "before" in h.forecast(bars, at(day, 10))[1]
    assert "after" in h.forecast(bars, at(day, 360))[1]
    assert "prior sessions" in h.forecast(to_bars(grid, 3), at(day, 105))[1]
    gappy = bars.drop(bars.index[(bars.index.date == grid[0][-3]) & (bars.index.hour < 12)])
    assert "incomplete" in h.forecast(gappy, at(day, 105))[1]


# ---- 3. the forecaster beats the flat per-minute estimate where the day has a shape ---------------------------------
def test_har_is_nearer_the_truth_where_the_desk_overestimates_the_morning():
    """Quiet mornings, busy afternoons: the desk's flat per-minute variance is too big early and too small late."""
    prof = np.linspace(0.4, 1.6, 375)
    grid = study_grid(profile=prof, clustered=False)
    days = grid[0]
    day = days[-1]
    h = harvol.HarVol(harvol.fit_coefs({"FIX": grid}, DEV_END)["symbols"]["FIX"])
    bars = to_bars(grid)
    p = prof / prof.mean()
    for m, lo, hi in ((30, 0.0, 0.85), (255, 1.02, 9.0)):
        now = at(day, m)
        done = bars[bars.index < now]
        rv_ann = VolForecaster().forecast(done, day, None, today_close=done["close"][done.index.date == day].to_numpy())["rv_ann"]
        a30 = (rv_ann / 100) ** 2 / MIN_PER_YEAR * 30
        res = h.forecast(bars, now)[0]
        truth = (6e-4) ** 2 * p[m:m + 30].sum()
        assert lo < res["var"]["30m"] / a30 < hi
        assert abs(math.log(res["var"]["30m"] / truth)) < abs(math.log(a30 / truth))


# ---- 4. the engine: shadow records at the opening read and changes nothing ----------------------------------------
def _run(cfg, tmp_path, name, vf=None, coefs="fit", seed=5, first="2026-08-20", hook=None):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine, run_replay
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days(first, "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=seed)
    vf = vf if isinstance(vf, str) else dict(vf or {})                 # a malformed (string) block is passed through as it is
    if coefs == "fit":                                                 # fitted on the sessions before the replayed one only
        grids = {s: V.grid(bars[s][bars[s].index.date < days[-1]]) for s in ("NIFTY", "BANKNIFTY")}
        harvol.save_coefs(tmp_path / f"{name}_har.json", harvol.fit_coefs(grids, days[-2]))
        vf["path"] = str(tmp_path / f"{name}_har.json")
    elif coefs == "missing":
        vf["path"] = str(tmp_path / "does_not_exist.json")
    cfg = cfg.with_overrides({"autolearn": {"require_approved_model": False}, "intraday": {"vol_forecast": vf}})
    j = Journal(tmp_path / f"{name}.db")
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", j, IntradayBroker(cfg, starting_cash=20000), say=None)
    if hook:
        hook(eng)
    run_replay(eng)
    return eng, j, days[-1], bars


def _books(j, eng):
    """What the desk decided, did and holds: decisions, trades, fills, equity curve, thoughts, cash."""
    return {"decisions": j.df("SELECT ts, strategy, symbol, action, units, detail, context FROM decisions ORDER BY id").to_dict("records"),
            "trades": j.trades().to_dict("records"), "fills": j.df("SELECT * FROM fills ORDER BY id").drop(columns=["id"]).to_dict("records"),
            "equity": j.df("SELECT * FROM equity ORDER BY ts").to_dict("records"),
            "thoughts": j.df("SELECT ts, symbol, bias, score, conviction, day_type, vol_view, spot, action, narrative, evidence, "
                             "vetoes, levels, chain FROM thoughts ORDER BY id").to_dict("records"),
            "cash": eng.broker.cash(), "n_closed": len(eng.closed)}


def _shadow_events(j):
    ev = j.events()
    return ev[ev["data"].str.contains("vol_shadow", na=False)] if len(ev) else ev


def test_shadow_on_or_off_the_desk_decides_and_trades_identically(cfg, tmp_path):
    """The proof that the shadow is only a record: the same session replayed with the shadow off and on (two seeds) gives
    the same decisions, trades, fills, equity curve, thoughts and cash, and the same Live-screen numbers."""
    for seed in (5, 8):
        off, j_off, day, _ = _run(cfg, tmp_path, f"off{seed}", {"mode": "off"}, seed=seed)
        on, j_on, _, _ = _run(cfg, tmp_path, f"on{seed}", {"mode": "shadow"}, seed=seed)
        b_off = _books(j_off, off)
        assert len(b_off["thoughts"]) > 100 and len(b_off["decisions"]) > 0
        assert _books(j_on, on) == b_off
        assert len(_shadow_events(j_off)) == 0 and len(_shadow_events(j_on)) == 2
        for u in ("NIFTY", "BANKNIFTY"):
            assert j_on.get_state("intraday_live")["views"][u]["quant"] == j_off.get_state("intraday_live")["views"][u]["quant"]


class _Bomb:
    def forecast(self, bars, now):
        raise RuntimeError("synthetic failure")


def test_the_shadow_changes_nothing_even_if_it_blows_up(cfg, tmp_path):
    base, j_base, _, _ = _run(cfg, tmp_path, "b", {"mode": "off"})

    def boom(eng):
        real = eng.volshadow.start_session

        def start(day, t0, us):
            real(day, t0, us)
            eng.volshadow.har = {u: _Bomb() for u in us}
        eng.volshadow.start_session = start
    eng, j, _, _ = _run(cfg, tmp_path, "x", {"mode": "shadow"}, hook=boom)
    assert _books(j, eng) == _books(j_base, base)
    w = j.events(level="WARN")
    assert w["message"].str.contains("no HAR forecast at the opening read").sum() == 2     # one per index, then it stops trying
    assert j.events(level="ERROR").empty and len(_shadow_events(j)) == 0


def test_one_record_per_index_per_session_at_the_opening_read_with_both_forecasts(cfg, tmp_path):
    eng, j, day, _ = _run(cfg, tmp_path, "sh", {"mode": "shadow"})
    sh = _shadow_events(j)
    assert len(sh) == 2 and j.events(level="ERROR").empty
    for u in ("NIFTY", "BANKNIFTY"):
        row = sh[sh["message"].str.contains(f"vol shadow {u} ")]
        assert len(row) == 1
        assert pd.Timestamp(row.iloc[0]["ts"]).strftime("%H:%M") == "09:30"          # the first decision point the study covered
        d = json.loads(row.iloc[0]["data"])["vol_shadow"]
        assert d["symbol"] == u and d["model"] == "C_har" and d["m"] == 15
        assert d["pin"]["coef"] == hashlib.sha256((tmp_path / "sh_har.json").read_bytes()).hexdigest()   # the file this run loaded
        assert d["pin"]["coef"] != volshadow.COEF_PIN                                    # a fixture fit is not the protocol's pinned file
        assert re.fullmatch(r"[0-9a-f]{64}", d["pin"]["code"])
        assert set(d["desk"]) == set(d["har"]) == {"30m", "60m", "120m", "close"} and d["minutes"]["close"] == 375 - 15
        assert all(v > 0 for v in d["desk"].values()) and all(v > 0 for v in d["har"].values())
        assert d["desk"]["60m"] == pytest.approx(2 * d["desk"]["30m"], rel=1e-4)       # the desk's: per-minute variance x minutes
    ev = j.events()
    assert ev["message"].str.contains("vol shadow: HAR").any()


def test_missing_coefficients_are_a_warn_not_an_exception(cfg, tmp_path):
    base, j_base, _, _ = _run(cfg, tmp_path, "b", {"mode": "off"})
    eng, j, _, _ = _run(cfg, tmp_path, "m", {"mode": "shadow"}, coefs="missing")
    assert _books(j, eng) == _books(j_base, base)
    w = j.events(level="WARN")
    msgs = w[w["message"].str.contains("vol shadow unavailable")]
    assert len(msgs) == 1 and "vol-har-fit" in msgs.iloc[0]["message"]
    assert len(_shadow_events(j)) == 0 and j.events(level="ERROR").empty


def test_too_little_history_at_the_opening_read_is_a_warn_once_per_index(cfg, tmp_path):
    off, j_off, _, _ = _run(cfg, tmp_path, "short_off", {"mode": "off"}, first="2026-09-22")     # fewer than 5 prior sessions
    eng, j, _, _ = _run(cfg, tmp_path, "short", {"mode": "shadow"}, first="2026-09-22")
    assert _books(j, eng) == _books(j_off, off)
    w = j.events(level="WARN")
    w = w[w["message"].str.contains("opening read")]
    assert len(w) == 2 and all("prior sessions" in m for m in w["message"])
    assert len(_shadow_events(j)) == 0 and j.events(level="ERROR").empty


def test_a_bad_mode_is_off_with_a_warn_and_apply_does_not_exist(cfg, tmp_path):
    base, j_base, _, _ = _run(cfg, tmp_path, "b", {"mode": "off"})
    for i, mode in enumerate(("apply", "har", "ON")):
        eng, j, _, _ = _run(cfg, tmp_path, f"bad{i}", {"mode": mode})
        assert _books(j, eng) == _books(j_base, base)
        assert j.events(level="WARN")["message"].str.contains("treated as off").sum() == 1
        assert len(_shadow_events(j)) == 0
    from quantdesk.intraday.volshadow import MODES
    assert MODES == ("off", "shadow")


def test_the_key_absent_means_off(tmp_path):
    class _Cfg:
        runtime_dir = str(tmp_path)

        def get(self, key, default=None):
            return default
    vs = volshadow.VolShadow(_Cfg(), journal=None)
    assert vs.mode == "off" and not vs.on and vs.bad_mode is None
    vs.step("NIFTY", at(dt.date(2026, 10, 12), 20), pd.DataFrame(), 12.0)       # off: returns before touching anything


class _VCfg:
    """A config whose only block is `intraday.vol_forecast`, whatever it holds (a dict, a string, a bare `off` read as False)."""
    runtime_dir = "unused"

    def __init__(self, vf):
        self.vf = vf

    def get(self, key, default=None):
        return self.vf if key == "intraday.vol_forecast" else default


class _Jnl:
    def __init__(self):
        self.rows = []

    def event(self, ts, level, category, message, data=None):
        self.rows.append((level, message))


def test_a_string_block_still_constructs_the_engine_with_the_shadow_off_and_a_warn(cfg, tmp_path):
    base, j_base, _, _ = _run(cfg, tmp_path, "b", {"mode": "off"})
    eng, j, _, _ = _run(cfg, tmp_path, "str", "shadow", coefs="none")         # `vol_forecast: shadow` in the YAML
    assert eng.volshadow.mode == "off" and not eng.volshadow.on
    assert _books(j, eng) == _books(j_base, base)
    assert j.events(level="WARN")["message"].str.contains("treated as off").sum() == 1
    assert len(_shadow_events(j)) == 0 and j.events(level="ERROR").empty


def test_a_string_block_never_raises_at_construction_or_session_start(tmp_path):
    jn = _Jnl()
    vs = volshadow.VolShadow(_VCfg("shadow"), journal=jn)
    assert vs.mode == "off" and not vs.on and vs.bad_mode == "shadow"
    vs.start_session(dt.date(2026, 10, 19), at(dt.date(2026, 10, 19), 0), ["NIFTY"])
    assert jn.rows == [("WARN", "intraday.vol_forecast.mode 'shadow' is not off or shadow: treated as off (there is no apply mode)")]


def test_a_non_string_path_constructs_and_starts_without_an_exception(tmp_path):
    from pathlib import Path
    jn = _Jnl()
    vs = volshadow.VolShadow(_VCfg({"mode": "shadow", "path": 123}), journal=jn)
    assert vs.path == Path("123") and vs.on and vs.bad_mode is None
    vs.start_session(dt.date(2026, 10, 19), at(dt.date(2026, 10, 19), 0), ["NIFTY"])   # no coefficients at "123": a WARN, not a raise
    assert [lvl for lvl, _ in jn.rows] == ["WARN"]


def test_mode_false_is_a_bare_off_with_no_warn(tmp_path):
    jn = _Jnl()
    vs = volshadow.VolShadow(_VCfg({"mode": False}), journal=jn)
    assert vs.mode == "off" and not vs.on and vs.bad_mode is None
    vs.start_session(dt.date(2026, 10, 19), at(dt.date(2026, 10, 19), 0), ["NIFTY"])
    assert jn.rows == []


def test_the_shipped_config_is_shadow_and_paper(cfg):
    assert cfg.get("intraday.vol_forecast.mode") == "shadow"
    assert cfg.get("account.mode") == "paper"


# ---- 5. the live comparison ------------------------------------------------------------------------------------------
def _ev_row(ts, symbol, m, minutes, desk, har):
    return {"ts": str(ts), "level": "INFO", "category": "quant", "message": "vol shadow",
            "data": json.dumps({"vol_shadow": {"symbol": symbol, "m": m, "minutes": minutes, "desk": desk, "har": har}})}


def test_compare_scores_qlike_and_move_ratio_against_the_recorded_bars():
    day = dt.date(2026, 10, 12)
    idx = pd.date_range(pd.Timestamp(day, tz=IST) + pd.Timedelta(hours=9, minutes=15), periods=375, freq="min")
    c = 20000 * np.exp(np.cumsum(np.full(375, 1e-4)))                       # +0.01% every minute: a clean known path
    bars = pd.DataFrame({"open": np.r_[20000.0, c[:-1]], "close": c}, index=idx)
    rv30, ret30 = 30 * 1e-8, 30 * 1e-4                                      # realised over the 30 minutes after minute 15
    f_desk, f_har = 2 * rv30, rv30                                          # desk twice too big, HAR right
    ev = pd.DataFrame([_ev_row(idx[15], "NIFTY", 15, {"30m": 30}, {"30m": f_desk}, {"30m": f_har}),
                       _ev_row(idx[15], "BANKNIFTY", 15, {"30m": 30}, {"30m": f_desk}, {"30m": f_har}),
                       _ev_row(idx[30], "NIFTY", 30, {"30m": 30}, {"30m": 9 * rv30}, {"30m": 9 * rv30})])   # a restart's second record
    rep = volshadow.compare(ev, {"NIFTY": bars})
    assert rep["forecasts"] == 2 and rep["scored"] == 1                     # the first of the day counts; BANKNIFTY has no bars
    cell = rep["by"]["NIFTY 30m"]
    assert cell["n"] == 1
    assert cell["har"]["qlike"] == pytest.approx(0.0, abs=1e-9)
    assert cell["desk"]["qlike"] == pytest.approx(0.5 - math.log(0.5) - 1)
    assert cell["har"]["move_ratio"] == pytest.approx(ret30 / (math.sqrt(2 / math.pi) * math.sqrt(f_har)))
    assert cell["desk"]["move_ratio"] == pytest.approx(cell["har"]["move_ratio"] / math.sqrt(2))
    assert cell["har"]["move_ratio_by_time"]["09:30-10:00"] == pytest.approx(cell["har"]["move_ratio"])
    assert cell["qlike_gain_pct"] == pytest.approx(100.0) and cell["dm_t"] is None
    assert rep["sessions"] == 1
    late = pd.DataFrame([_ev_row(idx[360], "NIFTY", 360, {"30m": 30}, {"30m": f_desk}, {"30m": f_har})])
    assert volshadow.compare(late, {"NIFTY": bars})["scored"] == 0          # its horizon runs past the close: not gradable yet
    desk_less = pd.DataFrame([_ev_row(idx[15], "NIFTY", 15, {"30m": 30}, {}, {"30m": f_har})])
    assert volshadow.compare(desk_less, {"NIFTY": bars})["scored"] == 0     # nothing to compare HAR against
    text = volshadow.render(rep)
    assert "1 sessions graded, 0 of 60 with both indices" in text and "withheld until 60 sessions" in text
    assert "NIFTY 30m" in text and "QLIKE" in text
    assert "Nothing to score" in volshadow.render(volshadow.compare(pd.DataFrame(columns=["ts", "category", "data"]), {}))


def test_compare_reads_a_real_shadow_journal(cfg, tmp_path):
    eng, j, day, bars = _run(cfg, tmp_path, "cmp")
    rep = volshadow.compare(j.events(), {"NIFTY": bars["NIFTY"], "BANKNIFTY": bars["BANKNIFTY"]})
    assert rep["forecasts"] == len(_shadow_events(j)) == 2 and rep["scored"] == 8      # 2 indices x 4 horizons
    cell = rep["by"]["NIFTY close"]
    assert cell["days"] == 1 and cell["desk"]["qlike"] > 0 and cell["har"]["qlike"] > 0
    assert "NIFTY close" in volshadow.render(rep)


def test_vol_har_fit_stores_the_specs_training_window_and_leaves_the_spec_alone(cfg, tmp_path, monkeypatch, capsys):
    import argparse
    import hashlib

    from quantdesk.autolearn import cli as acli
    from quantdesk.data import external_aeron as X
    spec_path = V.Path(__file__).resolve().parent.parent / "docs/prereg/vol_forecast_v1.json"
    before = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    grid = study_grid()
    ds = tmp_path / "ds-1"
    ds.mkdir()
    (ds / "manifest.json").write_text(json.dumps({"status": "external_verified", "source_commit": "abc", "importer_version": "aeron7-2",
                                                  "partitions": {"1m/symbol=NIFTY/year=2018.parquet": "h1", "5m/x": "h2"}}))
    monkeypatch.setattr(X, "latest", lambda root: ds)
    monkeypatch.setattr(V, "prepare", lambda d, symbols: {s: grid for s in symbols})
    to = tmp_path / "coefs.json"
    acli.cmd_vol_har_fit(cfg, argparse.Namespace(out=None, spec=str(spec_path), to=str(to), asset_sha256=None))
    coefs, why = harvol.load_coefs(to)
    assert why == "" and coefs["dev_end"] == "2018-12-31" and coefs["spec"] == "vol_forecast_v1" and coefs["dataset"] == "ds-1"
    assert set(coefs["symbols"]) == {"NIFTY", "BANKNIFTY"}
    assert coefs["symbols"]["NIFTY"]["trained_through"] <= "2018-12-31"
    assert coefs["symbols"]["NIFTY"] == harvol.fit_coefs({"NIFTY": grid}, DEV_END)["symbols"]["NIFTY"]
    pv = coefs["provenance"]
    assert pv["spec"] == "vol_forecast_v1" and pv["spec_sha256"] == coefs["spec_sha256"] and pv["training_window"]["end"] == "2018-12-31"
    assert pv["inputs"]["source_commit"] == "abc" and pv["inputs"]["partitions_1m"] == {"1m/symbol=NIFTY/year=2018.parquet": "h1"}
    assert len(pv["inputs"]["manifest_sha256"]) == 64 and pv["created_at"] and pv["fit_command"].startswith("python -m quantdesk")
    assert hashlib.sha256(spec_path.read_bytes()).hexdigest() == before          # the locked spec is only read
    monkeypatch.setattr(X, "latest", lambda root: None)
    with pytest.raises(SystemExit):
        acli.cmd_vol_har_fit(cfg, argparse.Namespace(out=None, spec=str(spec_path), to=str(to), asset_sha256=None))


def test_the_committed_coefficients_are_the_locked_specs_fit_and_usable():
    """quantdesk/intraday/vol_har_v1.json: fitted by `autolearn vol-har-fit` on the verified external minutes. Reproduced
    against the locked test's own C_har QLIKE on the real lock-period data when it was committed (max difference 0.0);
    here: its provenance matches the spec and window, the numbers are finite and the right shape, and the desk can use it."""
    root = V.Path(__file__).resolve().parent.parent
    c, why = harvol.load_coefs(harvol.DEFAULT_PATH)
    assert why == "" and harvol.DEFAULT_PATH == root / "quantdesk/intraday/vol_har_v1.json"
    from quantdesk.autolearn.prereg import spec_hash
    spec_path = root / "docs/prereg/vol_forecast_v1.json"
    spec = json.loads(spec_path.read_text())
    locked = json.loads(next((root / "docs/prereg/results").glob("vol_forecast_v1-*.json")).read_text())
    pv = c["provenance"]
    assert c["spec"] == pv["spec"] == spec["name"] and c["spec_sha256"] == pv["spec_sha256"] == spec_hash(spec_path) == locked["spec_sha256"]
    assert c["dev_end"] == pv["training_window"]["end"] == spec["dev"]["end"] == "2018-12-31"
    assert pv["inputs"]["status"] == "external_verified" and pv["inputs"]["source_commit"] and len(pv["inputs"]["manifest_sha256"]) == 64
    assert pv["inputs"]["importer_version"] == "aeron7-2" and any(k.startswith("1m/symbol=NIFTY") for k in pv["inputs"]["partitions_1m"])
    assert pv["code_commit"] and pv["fit_command"].startswith("python -m quantdesk autolearn vol-har-fit") and pv["created_at"]
    assert set(c["symbols"]) == set(spec["symbols"])
    for sym, e in c["symbols"].items():
        assert e["sessions"] == locked["sessions"][sym]["dev"]                       # the same training sessions the study used
        assert dt.date.fromisoformat(e["trained_through"]) <= DEV_END
        prof = np.asarray(e["profile"], float)
        assert prof.shape == (V.N_MIN,) and np.isfinite(prof).all() and (prof > 0).all() and prof.mean() == pytest.approx(1.0)
        assert set(e["fit"]) == set(V.HORIZONS)
        for h, p in e["fit"].items():
            assert len(p["beta"]) == 1 + len(V.C_X) and np.isfinite(p["beta"]).all() and np.isfinite(p["smear"]) and p["smear"] > 0
        assert harvol.HarVol.for_session(c, sym, dt.date(2026, 10, 19))[0] is not None
    h = harvol.HarVol(c["symbols"]["NIFTY"])                                          # and it forecasts on desk-shaped bars
    grid = study_grid()
    res, why = h.forecast(to_bars(grid), at(grid[0][-1], 15))
    assert why == "" and all(np.isfinite(v) and v > 0 for v in res["var"].values())
    from quantdesk.intraday.volshadow import VolShadow

    class _Cfg:
        runtime_dir = "unused"

        def get(self, key, default=None):
            return {"intraday.vol_forecast": {"mode": "shadow"}}.get(key, default)
    assert VolShadow(_Cfg(), journal=None).path == harvol.DEFAULT_PATH               # the desk reads it by default


def test_the_vol_shadow_command_reports_from_the_journal_and_the_recorded_bars(cfg, capsys):
    import argparse

    from quantdesk.intraday import cli
    from quantdesk.intraday.recorder import SessionRecorder
    from quantdesk.journal.journal import Journal
    day = dt.date(2026, 10, 12)
    idx = pd.date_range(pd.Timestamp(day, tz=IST) + pd.Timedelta(hours=9, minutes=15), periods=375, freq="min")
    c = 20000 * np.exp(np.cumsum(np.full(375, 1e-4)))
    o = np.r_[20000.0, c[:-1]]
    bars = pd.DataFrame({"open": o, "high": c, "low": o, "close": c, "volume": 0.0}, index=idx)
    p = cli.paths(cfg, "live")
    SessionRecorder(p["data"]).record_bars("NIFTY", bars)
    j = Journal(p["journal"])
    j.event(idx[15], "INFO", "quant", "vol shadow NIFTY 09:30",
            {"vol_shadow": {"symbol": "NIFTY", "m": 15, "minutes": {"30m": 30}, "desk": {"30m": 6e-7}, "har": {"30m": 3e-7}}})
    j.commit()
    cli.cmd_vol_shadow(cfg, argparse.Namespace(account=None, since=None))
    out = capsys.readouterr().out
    assert "NIFTY 30m" in out and "of 60 with both indices" in out


def test_the_report_says_why_sessions_have_no_record(cfg):
    """Research review of #87: skipped index-sessions must be visible, by reason, not only buried in the journal."""
    def warn(msg):
        return {"ts": "2026-10-26 10:01:00", "level": "WARN", "category": "quant", "message": msg, "data": None}
    ev = pd.DataFrame([warn("NIFTY vol shadow: no HAR forecast at the opening read (too few prior sessions); nothing is recorded for today"),
                       warn("BANKNIFTY vol shadow: no HAR forecast at the opening read (a gap); nothing is recorded for today"),
                       warn("NIFTY vol shadow: the desk has no realised-vol estimate at the opening read; HAR is recorded alone"),
                       warn("NIFTY vol shadow failed (no decision is affected): ValueError()"),
                       {"ts": "2026-10-26 10:02:00", "level": "INFO", "category": "quant", "message": "vol shadow NIFTY 09:30: ok", "data": None},
                       {"ts": "2026-10-26 10:03:00", "level": "WARN", "category": "risk", "message": "vol shadow in a risk event", "data": None}])
    got = volshadow.skips(ev)
    assert got == {"no HAR forecast by 10:00 (too little history or a gap)": 2,
                   "the desk had no estimate (HAR recorded, not graded)": 1, "error while recording": 1}
    assert volshadow.skips(pd.DataFrame(columns=["ts", "category", "message"])) == {}
    text = volshadow.render({"forecasts": 0, "scored": 0, "by": {}, "skips": got, "sessions": 0})
    assert "2 x no HAR forecast by 10:00" in text and "of 60 with both indices" in text
    assert "none" in volshadow.render({"forecasts": 0, "scored": 0, "by": {}, "skips": {}})


def test_every_skip_the_shadow_can_emit_is_counted_by_reason():
    """Delta review of #87: a late start, a failed start_session and a bad mode setting must be visible in the report; a
    coefficient error whose text contains 'failed' is still 'coefficients missing', not 'error while recording'."""
    def warn(msg):
        return {"ts": "2026-10-26 10:05:00", "level": "WARN", "category": "quant", "message": msg, "data": None}
    ev = pd.DataFrame([warn("NIFTY vol shadow: the engine first reached the opening read at 10:07, after 10:00 (a late start); nothing is recorded for today"),
                       warn("vol shadow could not start: ValueError('x')"),
                       warn("intraday.vol_forecast.mode 'x' is not off or shadow: treated as off (there is no apply mode)"),
                       warn("vol shadow unavailable (HAR could not load (failed to read)): nothing is recorded today")])
    assert volshadow.skips(ev) == {"late start (the engine first reached the read after 10:00)": 1, "could not start": 1,
                                   "bad vol_forecast config (treated as off)": 1, "coefficients missing or unusable": 1}


def test_a_runner_that_first_reaches_an_index_after_10_leaves_a_warn(cfg, tmp_path):
    """The protocol says a late start is visible; it is only true if the shadow journals it."""
    from quantdesk.journal.journal import Journal
    j = Journal(tmp_path / "late.db")
    vs = volshadow.VolShadow(cfg.with_overrides({"intraday": {"vol_forecast": {"mode": "shadow"}}}), j)
    vs.har = {"NIFTY": object()}                                           # the index is loaded, but the engine arrives late
    vs.day = dt.date(2026, 10, 26)
    vs.step("NIFTY", pd.Timestamp("2026-10-26 10:07", tz=IST), pd.DataFrame(), 15.0)
    msgs = list(j.events()["message"])
    assert any("after 10:00 (a late start)" in m for m in msgs)
    n = len(msgs)
    vs.step("NIFTY", pd.Timestamp("2026-10-26 10:08", tz=IST), pd.DataFrame(), 15.0)
    assert len(j.events()) == n                                            # once, not every minute


def test_a_failed_start_session_is_on_the_record_and_never_stops_the_session(cfg, tmp_path):
    def boom(eng):
        eng.volshadow.start_session = lambda *a, **k: (_ for _ in ()).throw(ValueError("no coefficients today"))
    eng, j, day, bars = _run(cfg, tmp_path, "boom", hook=boom)
    assert any("vol shadow could not start" in m for m in j.events()["message"])
    assert len(j.trades()) >= 0 and eng.health.get("safe_mode") is None      # the session ran


GOOD_PIN = f"{volshadow.COEF_PIN}:{'c' * 64}"           # the pinned coefficient file and one code pin


def _day_rows(day, symbol, base_diff, horizons=volshadow.HORIZONS, pin=GOOD_PIN):
    return [{"symbol": symbol, "day": day, "m": 15, "horizon": h, "rv": 1.0, "ret": 0.0, "F_desk": 1.0 + base_diff,
             "F_har": 1.0, "pin": pin} for h in horizons]


def _sessions(n, start=dt.date(2026, 10, 1), pin=GOOD_PIN, diff=0.5, indices=("NIFTY", "BANKNIFTY")):
    days = [start + dt.timedelta(days=i) for i in range(n)]
    rows = []
    for k, d in enumerate(days):
        for u in indices:
            rows += _day_rows(d, u, diff + 0.1 * (k % 3), pin=pin)
    return days, rows


def test_the_pooled_statistic_counts_only_sessions_with_both_indices_and_is_withheld_until_60():
    days = [dt.date(2026, 10, 1) + dt.timedelta(days=i) for i in range(70)]
    rows = []
    for k, d in enumerate(days):
        rows += _day_rows(d, "NIFTY", 0.5 + 0.1 * (k % 3))                           # HAR better every session
        if k % 2 == 0:
            rows += _day_rows(d, "BANKNIFTY", 0.4)                                    # BANKNIFTY on every other session only
    out = volshadow._pooled(pd.DataFrame(rows))
    assert out["sessions_both"] == 35 and out["pooled"]["sessions"] == 35
    assert out["pooled"]["mean_diff"] > 0 and out["pooled"]["nw_t"] > 3 and out["pooled"]["p_one_sided"] < 0.01
    rep = {"forecasts": 70, "scored": 280, "sessions": 70, "by": {}, "skips": {}, **out}
    assert "withheld until 60 sessions" in volshadow.render(rep) and "PASS" not in volshadow.render(rep)
    rows += [r for d in days[1::2] for r in _day_rows(d, "BANKNIFTY", 0.4)]          # now both indices on all 70 sessions
    out = volshadow._pooled(pd.DataFrame(rows))
    assert out["sessions_both"] == 70 and out["pooled"]["sessions"] == volshadow.TARGET_SESSIONS   # the first 60 only
    due = volshadow.render({"forecasts": 140, "scored": 560, "sessions": 70, "by": {}, "skips": {}, **out})
    assert "the single read is due" in due and "**PASS**" not in due                # computing is not reading: read_once reads
    worse = pd.DataFrame([{**r, "F_desk": 1.0, "F_har": 1.5} for r in rows])             # HAR worse: cannot pass
    assert volshadow._pooled(worse)["pooled"]["mean_diff"] < 0


def test_only_the_first_60_sessions_enter_the_statistic():
    """research-reviewer HIGH-1: a rerun on day 61, 62 ... was optional stopping; session 61 can no longer move the number."""
    _, rows = _sessions(60)
    base = volshadow._pooled(pd.DataFrame(rows))["pooled"]
    _, more = _sessions(65)
    later = volshadow._pooled(pd.DataFrame(more))
    assert later["sessions_both"] == 65 and later["pooled"]["sessions"] == 60
    assert later["pooled"]["mean_diff"] == base["mean_diff"] and later["pooled"]["nw_t"] == base["nw_t"]
    bad = pd.DataFrame(more)
    bad.loc[bad["day"] == bad["day"].max(), "F_desk"] = 1.0                           # a terrible 65th session
    assert volshadow._pooled(bad)["pooled"]["mean_diff"] == base["mean_diff"]


def test_a_pin_change_restarts_the_count_and_unpinned_or_wrongly_pinned_sessions_never_count():
    """research-reviewer HIGH-2: a refit or a change to harvol.py / quant.py must not mix regimes in the 60."""
    other = f"{volshadow.COEF_PIN}:{'d' * 64}"
    _, a = _sessions(30, pin=GOOD_PIN)
    _, b = _sessions(10, start=dt.date(2026, 11, 20), pin=other)                     # the code pin changed on 20 Nov
    out = volshadow._pooled(pd.DataFrame(a + b))
    assert out["sessions_both"] == 10 and out["sessions_excluded"] == 30             # the count restarted; the old ones are shown
    _, c = _sessions(10, start=dt.date(2027, 1, 5), pin=None)
    assert volshadow._pooled(pd.DataFrame(a + c))["sessions_both"] == 0              # no pin recorded: never counts
    refit = f"{'e' * 64}:{'c' * 64}"                                                  # a different coefficient file
    _, r = _sessions(30, pin=refit)
    assert volshadow._pooled(pd.DataFrame(r))["sessions_both"] == 0
    _, mixed = _sessions(5, pin=GOOD_PIN)
    mixed = [{**row, "pin": other} if row["symbol"] == "BANKNIFTY" else row for row in mixed]
    assert volshadow._pooled(pd.DataFrame(mixed))["sessions_both"] == 0              # the two indices disagree on the pin


def test_a_session_needs_all_four_horizons_for_both_indices():
    """research-reviewer MEDIUM-3: a report run at 11:00 counted 30m and 60m only."""
    _, rows = _sessions(12)
    short = [r for r in rows if not (r["symbol"] == "BANKNIFTY" and r["horizon"] == "close" and r["day"].day % 2 == 0)]
    out = volshadow._pooled(pd.DataFrame(short))
    assert out["sessions_both"] == 6                                                  # 12 days, the 6 even ones lack a BANKNIFTY close
    assert volshadow._pooled(pd.DataFrame([r for r in rows if r["horizon"] != "120m"]))["sessions_both"] == 0


def _noisy_rows(n, seed=7):
    """Sessions with realistic scatter: the desk a little biased and noisy, HAR noisy, so t is moderate (not 45)."""
    rng = np.random.default_rng(seed)
    days = [dt.date(2026, 10, 1) + dt.timedelta(days=i) for i in range(n)]
    rows = []
    for d in days:
        for u in volshadow.INDICES:
            f_desk, f_har = 1.08 + 0.1 * rng.standard_normal(), 1.0 + 0.1 * rng.standard_normal()
            rows += [{"symbol": u, "day": d, "m": 15, "horizon": h, "rv": 1.0, "ret": 0.0, "F_desk": f_desk, "F_har": f_har,
                      "pin": GOOD_PIN} for h in volshadow.HORIZONS]
    return rows


def test_the_p_value_is_students_t_not_the_liberal_normal_tail():
    from scipy.stats import norm
    from scipy.stats import t as student
    pl = volshadow._pooled(pd.DataFrame(_noisy_rows(60)))["pooled"]
    assert 1.0 < pl["nw_t"] < 3 and 0.02 < pl["p_one_sided"] < 0.15                    # a moderate positive t, where the tails differ
    assert pl["p_one_sided"] == pytest.approx(float(student.sf(pl["nw_t"], df=59)), rel=1e-9)
    assert pl["p_one_sided"] > float(norm.sf(pl["nw_t"])) > 0                           # more conservative than the normal tail


class _Memory:
    """The journal state the one read is kept in."""
    def __init__(self):
        self.s, self.commits = {}, 0

    def get_state(self, k, default=None):
        return self.s.get(k, default)

    def set_state(self, k, v):
        self.s[k] = v

    def commit(self):
        self.commits += 1


def _rep(n, diff=0.5, worse=False):
    _, rows = _sessions(n, diff=diff)
    if worse:                                                    # HAR is the one that is wrong (QLIKE is smallest at F = rv = 1)
        rows = [{**r, "F_desk": 1.0, "F_har": 1.5} for r in rows]
    out = volshadow._pooled(pd.DataFrame(rows))
    return {"forecasts": 2 * n, "scored": 8 * n, "sessions": n, "by": {}, "skips": {}, **out}


def test_the_primary_read_is_taken_once_stored_and_never_recomputed():
    j = _Memory()
    early = volshadow.read_once(j, _rep(59), dt.date(2026, 12, 20))
    assert "stored" not in early and j.s == {}                                       # before 60: no read, nothing kept
    first = volshadow.read_once(j, _rep(60), dt.date(2026, 12, 21))
    rec = first["stored"]
    assert first["first_read"] and rec["verdict"] == "PASS" and rec["sessions"] == 60 and rec["coef_pin"] == volshadow.COEF_PIN
    assert j.s[volshadow.STATE_KEY] == rec and j.commits == 1
    again = volshadow.read_once(j, _rep(75, worse=True), dt.date(2027, 2, 1))       # more sessions, and now they look terrible
    assert again["stored"] == rec and "first_read" not in again and j.commits == 1   # the stored record, not a recomputation
    text = volshadow.render(again)
    assert "READ ONCE on 2026-12-21" in text and "**PASS**" in text and "does not recompute it" in text


def test_a_failing_read_is_stored_as_not_confirmed():
    j = _Memory()
    rec = volshadow.read_once(j, _rep(60, worse=True), dt.date(2026, 12, 21))["stored"]
    assert rec["verdict"] == "NOT CONFIRMED" and rec["mean_diff"] < 0
    assert "**NOT CONFIRMED**" in volshadow.render({**_rep(60), "stored": rec})


def test_the_backstop_stores_not_confirmed_underpowered_after_31_march():
    j = _Memory()
    assert "stored" not in volshadow.read_once(j, _rep(40), dt.date(2027, 3, 31))     # the backstop day itself is not past it
    rec = volshadow.read_once(j, _rep(40), dt.date(2027, 4, 1))["stored"]
    assert rec["verdict"] == "NOT CONFIRMED (underpowered)" and rec["sessions"] == 40
    assert "**NOT CONFIRMED (underpowered)**" in volshadow.render({**_rep(40), "stored": rec})
    assert volshadow.read_once(j, _rep(60), dt.date(2027, 5, 1))["stored"] == rec     # and it is final


def test_the_pins_are_the_sha256_of_the_files_the_protocol_names(tmp_path):
    import hashlib
    f = tmp_path / "c.json"
    f.write_bytes(b"coefficients")
    got = volshadow.pins(f)
    assert got["coef"] == hashlib.sha256(b"coefficients").hexdigest()
    here = Path(volshadow.__file__).parent
    assert got["code"] == hashlib.sha256((here / "harvol.py").read_bytes() + (here / "quant.py").read_bytes()).hexdigest()
    assert volshadow.pins(tmp_path / "missing.json")["coef"] is None                 # unreadable: recorded as None, never counted
    assert hashlib.sha256((here / "vol_har_v1.json").read_bytes()).hexdigest() == volshadow.COEF_PIN


def test_the_command_takes_the_single_read_once_on_the_live_journal(cfg, capsys, monkeypatch):
    import argparse

    from quantdesk.intraday import cli
    from quantdesk.journal.journal import Journal
    p = cli.paths(cfg, "live")
    base = {"forecasts": 120, "scored": 480, "sessions": 60, "by": {}, "skips": {}}
    calls = []

    def fake_compare(events, bars):
        calls.append(1)
        return {**base, **volshadow._pooled(pd.DataFrame(_sessions(60 if len(calls) < 3 else 80)[1]))}
    monkeypatch.setattr(volshadow, "compare", fake_compare)
    cli.cmd_vol_shadow(cfg, argparse.Namespace(account=None, since=None))
    first = capsys.readouterr().out
    assert "READ ONCE" in first and "**PASS**" in first
    assert Journal(p["journal"]).get_state(volshadow.STATE_KEY)["verdict"] == "PASS"
    cli.cmd_vol_shadow(cfg, argparse.Namespace(account=None, since="2020-01-01"))        # a second look, with --since, on worse data
    second = capsys.readouterr().out
    assert "**PASS**" in second and "does not recompute it" in second                    # still the stored record
    cli.cmd_vol_shadow(cfg, argparse.Namespace(account="replay", since=None))
    assert "applies to the live journal only" in capsys.readouterr().out
    assert Journal(cli.paths(cfg, "replay")["journal"]).get_state(volshadow.STATE_KEY) is None
