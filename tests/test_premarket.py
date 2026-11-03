"""The pre-market brief (quantdesk/premarket): the universe has no cap, history is read the way the docstring says,
labels use only unbiased (calendar) events, the watch-list states its reasons, and the job reads public data only."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quantdesk.premarket import brief as B
from quantdesk.premarket import history as H
from quantdesk.premarket import universe as U

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = list(pd.bdate_range("2026-05-01", periods=130))
E1, E2 = 40, 105                                        # two results, a quarter apart
EXPIRY = SESSIONS[-1] + pd.Timedelta(days=25)          # one expiry, always >= 7 days away


def _chain(sym, day, spot, iv, step=20.0, lot=500, underlying=True, contracts=500):
    """A small option chain: the ATM straddle is 0.8 x spot x iv x sqrt(dte/365), split evenly; others by intrinsic."""
    dte = (EXPIRY - day).days
    strad = H.SQRT_2_PI * spot * iv * np.sqrt(dte / 365)
    atm = round(spot / step) * step
    rows = []
    for k in np.arange(atm - 10 * step, atm + 10 * step + 1, step):
        for kind in ("CE", "PE"):
            intr = max(spot - k, 0) if kind == "CE" else max(k - spot, 0)
            px = intr + strad / 2 * np.exp(-abs(k - spot) / (3 * step))
            rows.append({"date": day, "symbol": sym, "kind": kind, "expiry": EXPIRY, "strike": float(k), "open": px, "high": px,
                         "low": px, "close": round(px, 2), "last": px, "prev_close": px, "settle": px,
                         "underlying": spot if underlying else np.nan, "oi": 1000.0, "chg_oi": 0.0, "contracts": float(contracts),
                         "lot": float(lot), "src": "udiff"})
    rows.append({"date": day, "symbol": sym, "kind": "FUT", "expiry": EXPIRY, "strike": 0.0, "open": spot, "high": spot, "low": spot,
                 "close": spot * 1.002, "last": spot, "prev_close": spot, "settle": spot, "underlying": np.nan, "oi": 1.2e6,
                 "chg_oi": 2e5, "contracts": 1000.0, "lot": float(lot), "src": "udiff"})
    return rows


def _stock(sym, events=(), base_iv=0.30, jump=0.08, seed=0):
    """A stock whose results (at each index in `events`) come with an IV run-up the session before and a crush + jump."""
    rng = np.random.default_rng(seed)
    spot, rows = 1000.0, []
    for i, d in enumerate(SESSIONS):
        iv = base_iv
        if any(i == e - 1 for e in events):
            iv = base_iv * 1.6                              # the run-up into the result
        if any(i == e for e in events):
            spot *= 1 + jump                                # the reaction
            iv = base_iv * 1.05                             # the crush (from 1.6x to 1.05x)
        else:
            spot *= 1 + rng.normal(0, 0.004)
        rows += _chain(sym, d, spot, iv)
    return rows


@pytest.fixture(scope="module")
def opts():
    rows = _stock("AAA", events=(E1, E2), seed=1) + _stock("BBB", seed=2, base_iv=0.25)
    return pd.DataFrame(rows)


# ---- universe -------------------------------------------------------------------------------------------------
def test_the_universe_lists_every_underlying_with_no_cap():
    day = SESSIONS[0]
    rows = []
    for i in range(300):
        rows += _chain(f"S{i:03d}", day, 500 + i, 0.3, step=10.0, contracts=100 + i)
    idx = _chain("NIFTY", day, 23000.0, 0.12, step=50.0, lot=65)
    u = U.fo_universe(pd.DataFrame(rows), pd.DataFrame(idx))
    assert len(u) == 301 and u.iloc[0]["symbol"] == "NIFTY" and u.iloc[0]["segment"] == "index"
    assert set(u["segment"]) == {"index", "stock"}
    assert u.loc[u.symbol == "S000", "strike_step"].item() == 10.0
    assert u.loc[u.symbol == "NIFTY", "strike_step"].item() == 50.0
    assert u.iloc[1]["symbol"] == "S299"                   # stocks by option contracts traded, most first
    assert u.loc[u.symbol == "S010", "fut_oi_chg_pct"].item() == pytest.approx(2e5 / 1e6)


def test_spot_falls_back_to_the_nearest_future_when_the_bhavcopy_has_no_underlying():
    g = pd.DataFrame(_chain("OLD", SESSIONS[0], 800.0, 0.3, underlying=False))
    g["expiry"] = pd.to_datetime(g["expiry"])
    assert U.spot(g) == pytest.approx(800.0 * 1.002)


# ---- history --------------------------------------------------------------------------------------------------
def test_atm_implied_reads_the_straddle_as_a_volatility(opts):
    imp = H.atm_implied(opts)
    b = imp[imp.symbol == "BBB"]
    assert len(b) == len(SESSIONS)
    assert b["iv"].median() == pytest.approx(0.25, rel=0.03)          # the generator's IV comes back out
    a = imp[imp.symbol == "AAA"].set_index("date")
    assert a.loc[SESSIONS[E1 - 1], "iv"] > 1.5 * a.loc[SESSIONS[E1 - 10], "iv"]   # the run-up shows


def test_atm_implied_skips_expiries_closer_than_the_minimum():
    day = EXPIRY - pd.Timedelta(days=3)
    assert H.atm_implied(pd.DataFrame(_chain("ZZZ", day, 1000.0, 0.3)), min_dte=7).empty


def test_the_fingerprint_finds_results_and_not_quiet_stocks(opts):
    imp = H.atm_implied(opts)
    inf = H.inferred_results(imp)
    assert list(inf[inf.symbol == "AAA"]["react"]) == [SESSIONS[E1], SESSIONS[E2]]
    assert inf[inf.symbol == "BBB"].empty


def test_a_crush_without_a_jump_is_not_a_result(opts):
    o = opts.copy()
    imp = H.atm_implied(o)
    imp.loc[imp.symbol == "BBB", "iv"] = np.where(imp.loc[imp.symbol == "BBB", "date"] == SESSIONS[70], 0.15, 0.25)
    assert H.inferred_results(imp).query("symbol == 'BBB'").empty


def test_results_history_measures_the_window_and_the_straddle(opts):
    imp = H.atm_implied(opts)
    cal = H.results_calendar(pd.DataFrame([{"date": SESSIONS[E2], "symbol": "AAA", "company": "Aaa Industries Limited",
                                            "purpose": "Financial Results", "desc": ""}]), H.sessions_of(imp))
    hist = H.results_history(opts, imp, cal, H.inferred_results(imp))
    a = hist[hist.symbol == "AAA"].set_index("event")
    assert a.loc[SESSIONS[E2], "source"] == "calendar"                 # the calendar replaces the inferred event
    assert a.loc[SESSIONS[E1], "source"] == "inferred"
    r = a.loc[SESSIONS[E2]]
    assert r["pre"] == SESSIONS[E2 - 1] and r["post"] == SESSIONS[E2 + 1]
    assert r["move"] == pytest.approx(abs(r["spot_post"] / r["spot_pre"] - 1))
    assert r["move"] > 0.06
    assert r["iem"] > 0.02 and r["iv_base"] == pytest.approx(0.30, rel=0.05)
    assert r["straddle_ret"] < 0.5                                     # IV fell from 1.6x to ~1x: the straddle paid little
    assert len(hist) == 2


def test_event_implied_move_is_the_variance_above_normal():
    assert H.event_implied_move(0.5, 0.3, 365) == pytest.approx(0.4)
    assert H.event_implied_move(0.2, 0.3, 30) == 0.0
    assert np.isnan(H.event_implied_move(float("nan"), 0.3, 30))


def test_macro_history_reads_fomc_on_the_next_indian_session():
    days = pd.bdate_range("2025-01-01", periods=120)
    close = 20000 * np.cumprod(np.r_[1, np.full(119, 1.001)])
    ic = pd.DataFrame({"date": days, "symbol": "NIFTY", "close": close})
    jump_on = days[41]
    ic.loc[ic.date == jump_on, "close"] *= 1.05
    dates = {"kinds": {"fomc": {"reacts": "next_session", "dates": [str(days[40].date())]},
                       "rbi": {"reacts": "same_session", "dates": [str(days[40].date())]}}}
    mh = H.macro_history(ic, dates, symbols=("NIFTY",))
    assert mh["fomc"]["NIFTY"]["median_move"] > 0.04                  # the next session carries the move
    assert mh["rbi"]["NIFTY"]["median_move"] < 0.002


def test_macro_dates_file_is_well_formed():
    d = H.macro_dates()
    for kind, spec in d["kinds"].items():
        days = [dt.date.fromisoformat(x) for x in spec["dates"]]
        assert days == sorted(days) and len(set(days)) == len(days), kind
        assert spec["reacts"] in ("same_session", "next_session") and spec["evidence"]


# ---- brief ----------------------------------------------------------------------------------------------------
def _hist_rows(sym, moves, source="calendar", iem=0.03):
    return [{"symbol": sym, "source": source, "event": SESSIONS[5 + i], "pre": SESSIONS[4 + i], "post": SESSIONS[6 + i],
             "spot_pre": 100.0, "spot_post": 100 * (1 + m), "move": m, "iv_pre": 0.5, "iv_base": 0.3, "iem": iem,
             "straddle_pre": 5.0, "straddle_ret": 0.0} for i, m in enumerate(moves)]


def _inputs(opts, hist, events_day, now):
    corp = pd.DataFrame([{"date": events_day, "symbol": "AAA", "company": "Aaa Industries Limited", "purpose": "Financial Results", "desc": ""}])
    return B.Inputs(now=pd.Timestamp(now, tz=B.IST), stock_opts=opts, corp_events=corp, history=pd.DataFrame(hist),
                    holidays=())


def _opts_with_runup_at_the_end():
    return pd.DataFrame(_stock("AAA", events=(len(SESSIONS),), seed=1) + _stock("BBB", seed=2, base_iv=0.25))   # run-up on the last session


def test_label_compares_with_calendar_events_only():
    opts = _opts_with_runup_at_the_end()
    today = (SESSIONS[-1] + pd.offsets.BDay(1)).date()
    now = dt.datetime.combine(today, dt.time(8, 0))
    inferred_only = _hist_rows("AAA", [0.20, 0.25, 0.30], source="inferred")
    r = B.build(_inputs(opts, inferred_only, today, now))["results"][0]
    assert r["symbol"] == "AAA" and r["label"] == "no history"
    assert "biased toward big moves" in r["why"] and r["past_inferred"]["n"] == 3
    big = _hist_rows("AAA", [0.20, 0.25, 0.30])
    r = B.build(_inputs(opts, big, today, now))["results"][0]
    assert r["label"] == "cheap" and r["move_over_implied"] >= B.CHEAP
    small = _hist_rows("AAA", [0.001, 0.002, 0.001])
    assert B.build(_inputs(opts, small, today, now))["results"][0]["label"] == "rich"


def test_a_result_already_crushed_at_the_last_close_is_called_out(opts):
    today = (SESSIONS[E2] + pd.offsets.BDay(1)).date()
    o = opts[pd.to_datetime(opts["date"]) <= SESSIONS[E2]]
    now = dt.datetime.combine(today, dt.time(8, 0))
    b = B.build(_inputs(o, _hist_rows("AAA", [0.05] * 3), SESSIONS[E2].date(), now))
    r = b["results"][0]
    assert r["when"].startswith("reaction day") and r["label"] == "already out"


def test_the_watch_list_ranks_every_name_with_reasons():
    opts = _opts_with_runup_at_the_end()
    today = (SESSIONS[-1] + pd.offsets.BDay(1)).date()
    b = B.build(_inputs(opts, _hist_rows("AAA", [0.2, 0.25, 0.3]), today, dt.datetime.combine(today, dt.time(8, 0))))
    w = {x["symbol"]: x for x in b["watch"]}
    assert set(w) == {"AAA", "BBB"} and b["watch"][0]["symbol"] == "AAA"
    assert "results today" in w["AAA"]["why"] and any("cheap" in x for x in w["AAA"]["why"])
    assert b["universe"] == {"indices": 0, "stocks": 2}
    json.dumps(B.jsonable(b))                                          # the brief is valid JSON
    md = B.to_markdown(B.jsonable(b))
    assert "## Results" in md and "| AAA |" in md


def test_the_recording_plan_spends_kites_budget_and_never_more():
    watch = [{"symbol": f"S{i}", "segment": "stock"} for i in range(400)] + [{"symbol": "NIFTY", "segment": "index"}]
    watch = watch[-1:] + watch[:-1]
    p = B.record_plan(watch)
    assert p["used"] <= p["budget"] == 9000
    assert p["plan"][0]["symbol"] == "NIFTY" and p["plan"][0]["strikes_each_side"] == 20
    assert p["plan"][1]["strikes_each_side"] == 10 and p["names"] == 401          # 401 names fit in 9,000
    many = B.record_plan(watch + [{"symbol": f"T{i}", "segment": "stock"} for i in range(1000)])
    assert many["used"] <= many["budget"] and many["names"] < many["of"]           # beyond the budget the list stops
    small = B.record_plan(watch[:5], tokens=100)
    assert small["used"] <= 100


def test_next_session_skips_weekends_holidays_and_the_closed_market():
    fri_eve = pd.Timestamp("2026-11-06 16:00", tz=B.IST)
    assert B.next_session(fri_eve) == dt.date(2026, 11, 9)
    assert B.next_session(pd.Timestamp("2026-11-09 08:00", tz=B.IST), holidays=["2026-11-09"]) == dt.date(2026, 11, 11) - dt.timedelta(days=1)
    assert B.next_session(pd.Timestamp("2026-11-03 08:00", tz=B.IST)) == dt.date(2026, 11, 3)


def test_headlines_name_companies_but_not_ordinary_words():
    hl = [{"title": "Vodafone Idea shares jump", "ts": "t", "source": "x", "link": ""},
          {"title": "A good idea for markets", "ts": "t", "source": "x", "link": ""},
          {"title": "Infosys wins a deal", "ts": "t", "source": "x", "link": ""}]
    corp = pd.DataFrame([{"symbol": "IDEA", "company": "Vodafone Idea Limited"}, {"symbol": "INFY", "company": "Infosys Limited"}])
    m = B.match_headlines(hl, ["IDEA", "INFY"], B._company_aliases(corp))
    assert [x["title"] for x in m["IDEA"]] == ["Vodafone Idea shares jump"]
    assert [x["title"] for x in m["INFY"]] == ["Infosys wins a deal"]


def test_the_cli_writes_the_brief_offline(tmp_path, opts):
    wh = tmp_path / "wh"
    wh.mkdir()
    opts.to_parquet(wh / "fo_stock_opts_2026-10.parquet")
    pd.DataFrame([{"date": SESSIONS[-1].date(), "symbol": "AAA", "company": "Aaa Ltd", "purpose": "Financial Results", "desc": ""}]) \
        .to_parquet(wh / "corp_events_2026.parquet")
    from quantdesk.cli import main
    main(["premarket", "history", "--warehouse", str(wh), "--out", str(tmp_path / "h.parquet")])
    assert len(pd.read_parquet(tmp_path / "h.parquet")) >= 1
    main(["premarket", "brief", "--warehouse", str(wh), "--history", str(tmp_path / "h.parquet"), "--out", str(tmp_path / "out"),
          "--now", f"{SESSIONS[-1].date()}T08:00", "--offline"])
    b = json.loads((tmp_path / "out" / "brief.json").read_text())
    assert b["session"] == str(SESSIONS[-1].date()) and b["results"][0]["symbol"] == "AAA"
    assert (tmp_path / "out" / "brief.md").read_text().startswith("# Pre-market brief")


def test_a_dead_source_fails_soft():
    from quantdesk.premarket import sources as SRC
    health = {}
    assert SRC.fetch_globals(health, download=lambda t: (_ for _ in ()).throw(RuntimeError("rate limited"))) == []
    assert health["yahoo"].startswith("fail")
    rss = "<rss><channel><item><title>Infosys wins a deal</title><pubDate>Tue, 03 Nov 2026 02:00:00 +0000</pubDate></item></channel></rss>"
    now = pd.Timestamp("2026-11-03 08:00", tz=B.IST)

    def fetch(url):
        if "bad" in url:
            raise OSError("down")
        return rss
    out = SRC.fetch_headlines(health, now, fetch=fetch, sources=[{"name": "ok", "url": "u"}, {"name": "dead", "url": "bad"}])
    assert [x["title"] for x in out] == ["Infosys wins a deal"]
    assert health["rss:dead"].startswith("fail") and health["rss:ok"] == "ok 1"


# ---- what it may touch ------------------------------------------------------------------------------------------
def test_the_package_reads_public_data_only_and_places_nothing():
    src = "\n".join(p.read_text() for p in (ROOT / "quantdesk" / "premarket").glob("*.py"))
    for word in ("kite", "kotak", "place_order", "broker", "journal", "risk"):
        assert not re.search(rf"\b(import|from)\b[^\n]*\b{word}", src, re.I), word
    assert not re.search(r"KITE_(API|DATA|ACCESS)|API_SECRET|os\.environ", src)


def test_the_workflow_holds_no_secret_and_writes_only_the_premarket_branch():
    text = (ROOT / ".github" / "workflows" / "premarket.yml").read_text()
    wf = yaml.load(text, Loader=yaml.BaseLoader)
    assert wf["permissions"] == {"contents": "write"}
    assert "secrets." not in text
    job = wf["jobs"]["brief"]
    steps = job["steps"]
    assert steps[0]["with"]["persist-credentials"] == "false"
    # the token: in the env of exactly the two named steps, never the workflow's or the job's
    assert "env" not in wf and "env" not in job
    holders = [s.get("name") for s in steps if "GH_TOKEN" in (s.get("env") or {})]
    assert holders == ["Warehouse tables and the results history (rebuilt once a day)",
                       "Brief every 15 minutes to 09:15 IST (once, if started later)"]
    assert text.count("github.token") == 2
    pip_step = next(i for i, s in enumerate(steps) if "pip install" in s.get("run", ""))
    assert all("GH_TOKEN" not in json.dumps(s) for s in steps[:pip_step + 1])
    # the publish: a host-scoped, masked header, given to push-dir.sh alone, for one branch
    run = steps[-1]["run"]
    assert 'GIT_CONFIG_KEY_0="http.https://github.com/.extraheader"' in run
    assert not re.search(r"[\"' ]http\.extraheader", text)
    assert run.index('echo "::add-mask::$auth"') < run.index('GIT_CONFIG_VALUE_0="$auth"')
    assert run.count("$auth") == 2 + run.count("auth=") - 1                 # set once, masked once, used once
    pushes = re.findall(r"push-dir\.sh\s+\S+\s+(\S+)", text)
    assert pushes == ["premarket"] and "git push" not in text
    # every token step narrows PATH before any tool runs, and starts python without the token
    data = (ROOT / "deploy" / "premarket-data.sh").read_text()
    for body in (run, data):
        lines = [l.split(" # ")[0].strip() for l in body.splitlines() if l.strip() and not l.strip().startswith("#")]
        first_tool = next(i for i, l in enumerate(lines) if re.search(r"\b(gh|git|base64|push-dir\.sh)\b", l))
        narrow = next(i for i, l in enumerate(lines) if l.startswith("export PATH=/usr/bin:/bin"))
        assert narrow < first_tool
        assert all("env -u GH_TOKEN" in l for l in lines if re.search(r'"\$PY"|\bpython\b', l) and "command -v python" not in l
                   and not l.startswith("print("))


def test_the_app_has_a_today_tab_and_the_site_can_reach_the_brief():
    app = (ROOT / "quantdesk" / "web" / "static" / "app" / "app.js").read_text()
    assert '["today", "Today"]' in app and "renderToday" in app and "/api/i/premarket" in app
    html = (ROOT / "quantdesk" / "web" / "static" / "app" / "index.html").read_text()
    assert 'data-view="today"' in html and "repeat(6,1fr)" in html
    from quantdesk.web import export_site as X
    assert '"/api/i/premarket"' in X.ROUTES and "window.qdRealFetch" in X.SHIM and "window.qdRealFetch" in X.LIVE_SHIM


def test_the_site_points_at_the_premarket_branch(monkeypatch):
    from quantdesk.web.export_site import premarket_url

    class Cfg(dict):
        def get(self, k, d=None):
            return super().get(k, d)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    assert premarket_url(Cfg()) == "https://raw.githubusercontent.com/owner/repo/premarket/brief.json"
    assert premarket_url(Cfg({"premarket.url": "brief.json"})) == "brief.json"
    monkeypatch.delenv("GITHUB_REPOSITORY")
    assert premarket_url(Cfg()) is None
