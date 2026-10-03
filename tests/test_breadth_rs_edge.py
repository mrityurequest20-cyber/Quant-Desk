"""Index breadth (breadth.py), BANKNIFTY vs NIFTY relative strength (relstrength.py), FII index-options positioning
(brain.load_flows) and the buyer's edge over the bhavcopy (warehouse_research.buyer_edge)."""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from quantdesk.intraday import breadth as B
from quantdesk.intraday import relstrength as RS
from quantdesk.intraday.learning import Memory

IST = "Asia/Kolkata"


def ts(x):
    return pd.Timestamp(x, tz=IST)


# ---- breadth ---------------------------------------------------------------------------------------------------------
def test_members_tokens_and_quotes():
    csv = b"Company Name,Industry,Symbol,Series,ISIN Code\nReliance,Oil,RELIANCE,EQ,INE002A01018\nM&M,Auto,M&M,EQ,INE101A01026\n"
    assert B.parse_index_list(csv) == ["RELIANCE", "M&M"]
    big = "Company Name,Industry,Symbol,Series,ISIN Code\n" + "\n".join(f"C{i},X,S{i},EQ,I{i}" for i in range(50))
    got, src = B.index_members("NIFTY", lambda path: big.encode())
    assert len(got) == 50 and src == "NSE ind_nifty50list.csv"
    got, src = B.index_members("NIFTY", lambda path: (_ for _ in ()).throw(RuntimeError("blocked")))
    assert got == list(B.NIFTY50) and src.startswith("built-in")
    fo = pd.DataFrame({"pSymbol": [59097, 48987, 1, 2], "pInstType": ["FUTSTK", "FUTSTK", "FUTIDX", "OPTSTK"],
                       "pSymbolName": ["RELIANCE", "RELIANCE", "NIFTY", "M&M"], "pAssetCode": [2885, 2885, 26000, 2031]})
    cm = pd.DataFrame({"pSymbol": [2031, 11], "pTrdSymbol": ["M&M-EQ", "M&M-BE"]})
    assert B.cash_tokens(fo, ["RELIANCE", "M&M"]) == {"RELIANCE": "2885"}            # options rows don't count
    assert B.cash_tokens(fo, ["RELIANCE", "M&M"], cm) == {"RELIANCE": "2885", "M&M": "2031"}
    # Kotak's field names (runner, 2 Oct 2026): per_change in %, change in points, avg_cost the day's average price
    assert B.quote_row({"ltp": "1210", "per_change": "1.25", "avg_cost": "1200.5"}) == {"ltp": 1210.0, "chg": 0.0125, "vwap": 1200.5}
    r = B.quote_row({"ltp": "110", "change": "10", "avg_cost": "0"})
    assert r["chg"] == pytest.approx(0.1) and r["vwap"] != r["vwap"]
    assert B.quote_row({"ltp": "0"}) is None and B.quote_row({"ltp": "5"}) is None


class FakeKotak:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def quotes(self, instruments, kind="all"):
        self.asked.append(list(instruments))
        return [{"exchange": "nse_cm", "exchange_token": t, **self.rows[t]} for _, t in instruments if t in self.rows]


def snap(adv: int, above: int, n: int = 50, chg: float = 0.004):
    """n stocks: the first `adv` up `chg`, the rest down; the first `above` above their VWAP."""
    return {f"S{i}": {"ltp": 100.0, "chg": chg if i < adv else -chg, "vwap": 99.0 if i < above else 101.0} for i in range(n)}


def test_breadth_reads_participation_thrust_and_the_narrow_move():
    members = {"NIFTY": [f"S{i}" for i in range(50)]}
    seq = iter([snap(20, 18), snap(36, 38)])
    br = B.Breadth(members, lambda now: next(seq), refresh_min=1, members_source={"NIFTY": "test"})
    assert br.refresh(ts("2026-10-05 10:00")) and not br.refresh(ts("2026-10-05 10:00:30"))   # at most once a minute
    br.refresh(ts("2026-10-05 10:30"))
    st = br.state("NIFTY", 0.003, ts("2026-10-05 10:31"))
    assert st["n"] == 50 and st["adv"] == pytest.approx(0.72) and st["above_vwap"] == pytest.approx(0.76)
    assert st["vwap_chg30"] == pytest.approx(0.76 - 0.36) and st["adv_chg30"] == pytest.approx(0.72 - 0.40)
    assert st["ew_chg"] == pytest.approx(0.004 * (36 - 14) / 50) and st["ew_gap"] == pytest.approx(st["ew_chg"] - 0.003)
    d, obs = B.breadth_signal(st)
    assert d == pytest.approx(((0.76 - 0.5) + (0.72 - 0.5)) * 1.5) and "36 of 50" in obs and "38 above their VWAP" in obs
    assert B.divergence_signal(st) is None                                     # a broad rally isn't narrow
    assert br.state("NIFTY", 0.003, ts("2026-10-05 10:45")) is None             # a read 15 minutes old isn't used
    # a narrow rally: the index up 0.4% with 15 of 50 stocks up → leans against it
    br2 = B.Breadth(members, lambda now: snap(15, 20, chg=0.002))
    br2.refresh(ts("2026-10-05 11:00"))
    d, obs = B.divergence_signal(br2.state("NIFTY", 0.004, ts("2026-10-05 11:00")))
    assert d < -0.3 and "narrow rally" in obs and "carried by" in obs
    # too few quotes: no read at all
    br3 = B.Breadth(members, lambda now: dict(list(snap(30, 30).items())[:20]))
    br3.refresh(ts("2026-10-05 11:00"))
    assert br3.state("NIFTY", 0.0, ts("2026-10-05 11:00")) is None
    # a failing source is reported, not raised
    br4 = B.Breadth(members, lambda now: (_ for _ in ()).throw(RuntimeError("429")))
    assert br4.refresh(ts("2026-10-05 11:00")) is False and br4.health.startswith("fail")


def test_kotak_source_maps_tokens_back_to_symbols():
    k = FakeKotak({"2885": {"ltp": "1210", "per_change": "1.0", "avg_cost": "1205"},
                   "1333": {"ltp": "1600", "per_change": "-0.5", "avg_cost": "1610"}})
    src = B.KotakBreadthSource(k, {"RELIANCE": "2885", "HDFCBANK": "1333", "TCS": "11536"})
    got = src(ts("2026-10-05 10:00"))
    assert set(got) == {"RELIANCE", "HDFCBANK"} and got["HDFCBANK"]["chg"] == pytest.approx(-0.005)
    assert ("nse_cm", "11536") in k.asked[0]


def test_breadth_goes_to_the_analyst_on_probation(cfg):
    from quantdesk.intraday.analyst import PROBATION, Analyst
    from quantdesk.intraday.features import session_state
    idx = pd.date_range("2026-10-05 09:15", "2026-10-05 11:00", freq="1min", tz=IST)
    c = 25600 + np.arange(len(idx)) * 0.5
    s = session_state(pd.DataFrame({"open": c, "high": c + 2, "low": c - 2, "close": c, "volume": 0.0}, index=idx),
                      idx[-1] + pd.Timedelta(minutes=1))
    b = {"n": 50, "members": 50, "adv": 0.3, "dec": 0.7, "above_vwap": 0.28, "ew_chg": -0.002, "median_chg": -0.002,
         "index": "NIFTY 50", "index_chg": 0.004, "ew_gap": -0.006, "up": [("HDFCBANK", 0.02)], "down": []}
    a = Analyst(cfg)
    v = a.assess("NIFTY", s, None, breadth=b)
    ev = {e.factor: e for e in v.evidence}
    assert ev["breadth"].direction < 0 and ev["breadth"].weight == 0 and ev["breadth"].category == "breadth"
    assert ev["breadth_div"].direction < 0 and ev["breadth_div"].weight == 0
    assert "Breadth: 15 of 50 NIFTY 50 stocks up, 14 above their VWAP" in v.narrative
    a.graduated = {"breadth"}
    ev = {e.factor: e for e in a.assess("NIFTY", s, None, breadth=b).evidence}
    assert ev["breadth"].weight == pytest.approx(PROBATION["breadth"]) and ev["breadth_div"].weight == 0


# ---- relative strength -----------------------------------------------------------------------------------------------
def pair_bars(days, rng, persist: float, block: int = 30):
    """NIFTY and BANKNIFTY 1-minute bars whose ratio drifts in `block`-minute blocks, each block's drift carrying
    `persist` of the last one's (block 1, persist 0: no persistence at all)."""
    out = {"NIFTY": [], "BANKNIFTY": []}
    n0, b0 = 25000.0, 55000.0
    for d in days:
        idx = pd.date_range(f"{d} 09:15", f"{d} 15:29", freq="1min", tz=IST)
        rn = rng.normal(0, 4e-4, len(idx))
        drift, rr = 0.0, np.zeros(len(idx))
        for i in range(len(idx)):
            if i % block == 0:
                drift = persist * drift + rng.normal(0, 1.2e-4)
            rr[i] = drift + rng.normal(0, 1e-4)
        n = n0 * np.exp(np.cumsum(rn))
        b = b0 * np.exp(np.cumsum(1.2 * rn + rr))
        n0, b0 = float(n[-1]), float(b[-1])
        for k, x in (("NIFTY", n), ("BANKNIFTY", b)):
            out[k].append(pd.DataFrame({"open": x, "high": x, "low": x, "close": x, "volume": 0.0}, index=idx))
    return {k: pd.concat(v) for k, v in out.items()}


def test_relative_strength_read_and_its_persistence_record():
    days = [d.date() for d in pd.bdate_range("2026-09-01", periods=12)]
    bars = pair_bars(days, np.random.default_rng(5), persist=0.9)
    now = ts(f"{days[-1]} 12:00")
    rs = RS.rel_strength(bars["BANKNIFTY"], bars["NIFTY"], days[-1], now)
    b, n = bars["BANKNIFTY"]["close"], bars["NIFTY"]["close"]
    prev = b.index.date < days[-1]
    want = np.log(b[:now].iloc[-1] / n[:now].iloc[-1]) - np.log(b[prev].iloc[-1] / n[prev].iloc[-1])
    assert rs["rs_day"] == pytest.approx(want) and rs["leader"] == ("BANKNIFTY" if want > 0 else "NIFTY")
    assert rs["beta"] == pytest.approx(1.2, abs=0.15) and "z30" in rs and RS.describe(rs).startswith("BANKNIFTY vs NIFTY")
    m = Memory()
    added = RS.grade(m, bars)
    assert added > 12 * 50 and RS.grade(m, bars) == 0                         # each whole session graded once
    rec = RS.record(m)
    assert rec["ic"] > 0.2 and rec["t"] > 2 and RS.earned(rec) and rec["days"] == 12
    lead = "BANKNIFTY" if rs["z30"] > 0 else "NIFTY"
    lag = "NIFTY" if lead == "BANKNIFTY" else "BANKNIFTY"
    strong = {**rs, "z30": 1.5 * np.sign(rs["z30"]) or 1.5}
    assert RS.preference(lead, 1, strong, rec)[0] == RS.LIFT                   # long the leader
    assert RS.preference(lag, 1, strong, rec)[0] == RS.CUT                     # long the laggard
    assert RS.preference(lead, -1, strong, rec)[0] == RS.CUT                   # short the leader
    assert RS.preference(lead, 1, {**strong, "z30": 0.4}, rec) is None         # nothing unusual: no say
    # a ratio with no persistence doesn't earn the preference
    m2 = Memory()
    RS.grade(m2, pair_bars(days, np.random.default_rng(6), persist=0.0, block=1))
    assert not RS.earned(RS.record(m2)) and RS.preference(lead, 1, strong, RS.record(m2)) is None


# ---- FII index options positioning -----------------------------------------------------------------------------------
def participant_rows(n=200):
    days = pd.bdate_range("2025-12-01", periods=n)
    rows = []
    for i, d in enumerate(days):
        for who, k in (("FII", 1.0), ("Client", -1.0)):
            rows.append({"date": d.date(), "participant": who, "fut_idx_long": 100000.0 + 100 * i, "fut_idx_short": 150000.0,
                         "opt_idx_call_long": 500000.0 + k * 1000 * i, "opt_idx_call_short": 400000.0,
                         "opt_idx_put_long": 450000.0, "opt_idx_put_short": 420000.0})
    return pd.DataFrame(rows)


def test_fii_option_positioning_and_flows(tmp_path):
    from quantdesk.data.warehouse import Warehouse
    from quantdesk.intraday.brain import Brain, BrainState, load_flows, option_positioning
    po = participant_rows()
    po["date"] = pd.to_datetime(po["date"])
    o = option_positioning(po)
    # FII: calls net 100k + 1000·i, puts net 30k → net 70k + 1000·199 at the end; rising every day: top of its year
    assert o["fii_opt_net"] == pytest.approx(70000 + 199000) and o["fii_opt_d1"] == pytest.approx(1000)
    assert o["fii_opt_d5"] == pytest.approx(5000) and o["fii_opt_pctile"] > 0.99 and o["client_opt_pctile"] < 0.01
    wh = Warehouse(tmp_path / "wh")
    wh.upsert("participant_oi", participant_rows())
    rdir = tmp_path / "research"
    rdir.mkdir()
    (rdir / "vrp_positioning.json").write_text(json.dumps({"positioning": [
        {"id": "P4", "symbol": "NIFTY", "verdict": "NO EDGE", "t": 0.71, "n": 1100},
        {"id": "P1", "symbol": "NIFTY", "verdict": "NO EDGE", "t": 1.0, "n": 1100}]}))
    f = load_flows(tmp_path / "wh", dt.date(2026, 9, 30), rdir)
    assert f["fii_opt_net"] == pytest.approx(269000) and f["fii_opt_research"] == {"NIFTY": "NO EDGE (t +0.7, n 1100)"}
    st = BrainState("t", "mixed", 0.0, 0.0, 1.0, flows=f)
    text = Brain(None, None)._narrate("NIFTY", st)
    assert "FII index options net +269k contracts calls − puts (+1k on the day, percentile" in text


# ---- the buyer's edge over the bhavcopy ------------------------------------------------------------------------------
def bhav_days(n=60, S0=25000.0, seed=3, daily_move=0.006, straddle_frac=0.008):
    """A synthetic NIFTY with weekly Tuesday expiries and ATM straddles priced at `straddle_frac` of spot per
    remaining session (√), legs split evenly, opens = previous close moves."""
    rng = np.random.default_rng(seed)
    days = [d.date() for d in pd.bdate_range("2026-03-02", periods=n)]
    exps = sorted({d + dt.timedelta(days=(1 - d.weekday()) % 7) for d in days})
    S, rows, spot, opens = S0, [], {}, {}
    for d in days:
        o = S * np.exp(rng.normal(0, daily_move / 3))
        c = o * np.exp(rng.normal(0, daily_move))
        spot[d], opens[d] = c, o
        e = next(x for x in exps if x >= d)
        left = max(sum(1 for x in days if d < x <= e), 0) + 1
        for K in np.arange(round(c / 50) * 50 - 200, round(c / 50) * 50 + 250, 50):
            for kind in ("CE", "PE"):
                def px(Sx, lft):
                    intr = max(Sx - K, 0) if kind == "CE" else max(K - Sx, 0)
                    return intr + straddle_frac * Sx * np.sqrt(lft) / 2 * np.exp(-((Sx - K) / (0.01 * Sx)) ** 2)
                rows.append({"date": d, "symbol": "NIFTY", "kind": kind, "expiry": e, "strike": float(K),
                             "open": px(o, left + 0.3), "close": px(c, left), "underlying": c, "contracts": 1000.0})
        S = c
    return pd.DataFrame(rows), pd.Series(spot), pd.Series(opens)


def test_buyer_edge_rows_tables_and_the_desk_lookup(cfg, tmp_path):
    from quantdesk.intraday.analyst import hist_edge_note
    from quantdesk.research import warehouse_research as W
    opts, spot, opens = bhav_days()
    rows = W.buyer_edge_rows(opts, spot, opens, "NIFTY")
    assert set(rows["horizon"]) == {"intraday", "overnight"} and set(rows["weekday"]) <= set(W.WEEKDAYS)
    tue = rows[(rows["horizon"] == "intraday") & (rows["weekday"] == "Tue")]
    assert (tue["dte"] == 0).all() and (tue["bucket"] == "0 (expiry day)").all()
    assert (rows[rows["horizon"] == "overnight"]["dte"] >= 1).all()           # the contract has to exist tomorrow
    r = rows.iloc[0]                                                             # one row, by hand
    o = opts[(opts["date"] == r["date"]) & (opts["expiry"] == r["expiry"])]
    S0 = opens[r["date"]]
    K = o["strike"].iloc[int(np.abs(o["strike"] - S0).argmin())]
    leg = o[o["strike"] == K].set_index("kind")
    p0, p1 = leg.loc["CE", "open"] + leg.loc["PE", "open"], leg.loc["CE", "close"] + leg.loc["PE", "close"]
    costs = sum(float(W.leg_cost(x)) for x in (leg.loc["CE", "open"], leg.loc["PE", "open"], leg.loc["CE", "close"], leg.loc["PE", "close"]))
    assert r["horizon"] == "intraday" and r["pnl_pct"] == pytest.approx((p1 - p0 - costs) / p0)
    table = W.buyer_edge(rows, min_n=5)
    assert {t["by"] for t in table} == {"days to expiry", "weekday"}
    assert all(t["verdict"] in ("BUYERS WIN", "BUYERS LOSE", "NO EDGE") for t in table)
    md = "\n".join(W.buyer_edge_report(table, rows))
    assert "When does buying options pay?" in md and "NIFTY intraday" in md
    js = json.loads(W.buyer_edge_json({"buyer_edge": table, "span": {"NIFTY": "x"}}))
    got = W.edge_for(js, "NIFTY", dt.date(2026, 10, 6), 0)                    # a Tuesday, expiry day
    assert got["bucket"]["group"] == "0 (expiry day)" and got["weekday"]["group"] == "Tue"
    note = hist_edge_note("NIFTY", got)
    assert note.startswith("History (2026–2026): the NIFTY ATM straddle bought at the open with 0 (expiry day) days")
    # the engine picks today's rows from runtime/research/buyer_edge.json at the session start
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    from pathlib import Path
    rdir = Path(cfg.runtime_dir) / "research"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "buyer_edge.json").write_text(json.dumps(js))
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=11)
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    eng.start_session(days[-1])
    assert "NIFTY" in eng.hist_edge and eng.hist_edge["NIFTY"]["bucket"]["symbol"] == "NIFTY"


def test_the_engine_carries_breadth_and_relative_strength(cfg, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine, run_replay
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=11)
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000),
                         say=None, memory=Memory(tmp_path / "memory.json"))
    members = {"NIFTY": [f"S{i}" for i in range(50)], "BANKNIFTY": [f"S{i}" for i in range(12)]}
    eng.breadth = B.Breadth(members, lambda now: snap(30 + now.minute % 10, 28))
    run_replay(eng)
    hb = eng.journal.get_state("intraday_live")
    v = hb["views"]["NIFTY"]
    assert v["breadth"]["n"] == 50 and v["rel"]["pair"] == "BANKNIFTY/NIFTY" and "Breadth:" in v["narrative"]
    assert any(e["factor"] == "breadth" for e in v["evidence"]) and hb["learning"]["probation"]["breadth"]["voting"] is False
    assert "BANKNIFTY vs NIFTY" in v["narrative"]
    th = eng.journal.df("SELECT evidence FROM thoughts")
    assert th["evidence"].str.contains('"breadth"').any()                     # journaled, so the learning loop grades it
    assert eng.memory.d["rs"]["days"] >= 1                                     # persistence graded at the close
