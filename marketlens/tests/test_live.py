"""The live engine (web/livecore.js) must compute exactly what the end-of-day engine (engine/vol.py) computes on the
same chain: forward, ATM IV, straddle, priced move and 25-delta skew. Runs the JS in node on chains the Python engine
reads, so live and end-of-day numbers can never drift apart."""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketlens.engine import vol as V

WEB = Path(__file__).resolve().parents[1] / "web"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run_js(script: str) -> dict:
    code = f"const L = require({json.dumps(str(WEB / 'livecore.js'))});\n{script}"
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def quotes_from_chain(df: pd.DataFrame, symbol: str) -> dict:
    """End-of-day rows as the live relay would show them at the 15:30 close: close as ltp, contracts traded as vol."""
    q = {}
    for r in df.itertuples():
        if not (np.isfinite(r.close) and r.close > 0):              # the relay never carries a quote without a price
            continue
        e = pd.Timestamp(r.expiry)
        if r.kind == "FUT":
            q[f"{symbol}-FUT"] = {"ltp": r.close, "oi": r.oi, "vol": r.contracts, "age_s": 1, "s": "fut"}
            continue
        k = ("%f" % r.strike).rstrip("0").rstrip(".")
        name = f"{symbol}{e.day:02d}{MON[e.month - 1]}{e.year % 100:02d}{k}{r.kind}"
        q[name] = {"ltp": r.close, "oi": r.oi, "vol": r.contracts, "age_s": 1, "s": "opt"}
    return q


def compare(df: pd.DataFrame, day: pd.Timestamp, symbol: str = "X"):
    t, _ = V.expiry_table(df)
    t = t[t["date"] == day]
    now_ms = int(pd.Timestamp(f"{day.date()} 15:30", tz="Asia/Kolkata").timestamp() * 1000)
    q = quotes_from_chain(df[df["date"] == day], symbol)
    js = run_js(f"const r = L.readUnderlying({json.dumps(q)}, {json.dumps(symbol)}, {{nowMs: {now_ms}, maxAge: 120}});"
                "console.log(JSON.stringify(r.expiries.map(e => ({e: e.expiry, ok: e.ok, F: e.F, atm: e.atm_iv, st: e.straddle,"
                " mv: e.move, rr: e.rr25 ?? null, why: e.why ?? null}))));")
    return t, {x["e"]: x for x in js}


def _chain(day, spot, vols, smile=-0.1):
    rows = []
    for exp, sig in vols.items():
        T = (exp - day).days / 365
        F = spot * np.exp(0.05 * T)
        for K in np.arange(round(spot * 0.8), round(spot * 1.2) + 1, round(spot * 0.01)):
            s = sig + smile * np.log(K / F)
            for kind, call in (("CE", True), ("PE", False)):
                px = round(float(V._b76(F, K, T, s, np.array(call))), 2)
                rows.append(dict(date=day, symbol="X", kind=kind, expiry=exp, strike=float(K), open=px, high=px, low=px,
                                 close=px, settle=px, underlying=spot, oi=1000.0, chg_oi=0.0, contracts=50.0, lot=50.0))
        rows.append(dict(date=day, symbol="X", kind="FUT", expiry=exp, strike=np.nan, open=F, high=F, low=F, close=F,
                         settle=F, underlying=spot, oi=5000.0, chg_oi=0.0, contracts=100.0, lot=50.0))
    return pd.DataFrame(rows)


def test_live_engine_matches_end_of_day_engine():
    day = pd.Timestamp("2026-11-26")
    df = _chain(day, 1000.0, {pd.Timestamp("2026-12-03"): 0.18, pd.Timestamp("2026-12-29"): 0.16})
    t, js = compare(df, day)
    assert len(t) == 2
    for r in t.itertuples():
        j = js[str(r.expiry.date())]
        assert j["ok"], j["why"]
        assert j["F"] == pytest.approx(r.F, rel=1e-9)
        assert j["st"] == pytest.approx(r.straddle, rel=1e-9)
        assert j["mv"] == pytest.approx(r.implied_move, rel=1e-9)
        assert j["atm"] == pytest.approx(r.atm_iv, abs=2e-6)          # erf approximation vs scipy: < 1e-5 vol
        assert j["rr"] == pytest.approx(r.rr25, abs=5e-6)


def test_live_engine_refuses_what_end_of_day_refuses():
    day = pd.Timestamp("2026-11-26")
    df = _chain(day, 1000.0, {pd.Timestamp("2026-12-29"): 0.2})
    df.loc[df["kind"] != "FUT", "contracts"] = 0.0                   # nothing traded today
    t, js = compare(df, day)
    assert t.empty and not js["2026-12-29"]["ok"]


def test_stale_quotes_are_not_live():
    q = {"X": {"ltp": 100, "age_s": 500, "chg": 1.0}, "X-FUT": {"ltp": 100.5, "oi": 10, "age_s": 5}}
    r = run_js(f"console.log(JSON.stringify(L.readUnderlying({json.dumps(q)}, 'X', {{nowMs: Date.now(), maxAge: 120}})));")
    assert r["spot"] is None and r["fut"]["ltp"] == 100.5


def test_futures_today_same_contract_rules():
    last = {"fut": 1000.0, "near_oi": 2000.0, "fut_expiry": "2026-12-29"}
    r = run_js(f"console.log(JSON.stringify(L.futuresToday({{spot: 995, fut: {{ltp: 1010, oi: 2200}}}}, {json.dumps(last)}, '2026-11-27')));")
    assert r["label"] == "Long build-up" and r["dp"] == pytest.approx(0.01) and r["doi"] == pytest.approx(0.1)
    assert r["basis"] == pytest.approx(15.0)
    old = dict(last, fut_expiry="2026-11-26")                          # the closing contract has expired: no read
    r = run_js(f"console.log(JSON.stringify(L.futuresToday({{spot: 995, fut: {{ltp: 1010, oi: 2200}}}}, {json.dumps(old)}, '2026-11-27')));")
    assert "expired" in r["why"]


def test_oi_vs_close_on_common_strikes():
    prof = {"strikes": [100, 110], "call_oi": [10, 20], "put_oi": [30, 5]}
    exp = {"by": {"100": {"CE": {"oi": 12, "ltp": 5}, "PE": {"oi": 25, "ltp": 1}}, "110": {"CE": {"oi": 30, "ltp": 1}, "PE": {"oi": 5, "ltp": 9}}}}
    r = run_js(f"console.log(JSON.stringify(L.oiVsClose({json.dumps(exp)}, {json.dumps(prof)})));")
    assert r["call_add"] == 12 and r["put_add"] == -5
    assert r["pcr_close"] == pytest.approx(35 / 30) and r["pcr_live"] == pytest.approx(30 / 42)


def test_contract_expiring_today_is_not_read_live():
    day = pd.Timestamp("2026-11-26")
    df = _chain(day, 1000.0, {day: 0.5, pd.Timestamp("2026-12-29"): 0.16})
    _, js = compare(df, day)
    assert "2026-11-26" not in js and js["2026-12-29"]["ok"]


def test_constant_maturity_matches_end_of_day():
    """Live 30-day IV is vol.py's constant_maturity on the same expiries (integer days, as at the close)."""
    day = pd.Timestamp("2026-11-26")
    cases = [[(3, 0.30), (10, 0.25), (33, 0.20), (61, 0.22)], [(33, 0.24), (59, 0.23)], [(20, 0.2), (45, 0.3)]]
    for c in cases:
        t = pd.DataFrame({"date": day, "expiry": [day + pd.Timedelta(days=d) for d, _ in c], "days": [d for d, _ in c],
                          "atm_iv": [v for _, v in c]})
        py = V.constant_maturity(t, 30).iloc[0]
        exps = [{"ok": True, "days": d, "atm_iv": v} for d, v in c]
        js = run_js(f"console.log(JSON.stringify(L.constantMaturity({json.dumps(exps)})));")
        assert js["iv"] == pytest.approx(py, rel=1e-12)
    # only weeklies live (NIFTY's feed): no 30-day reading rather than a weekly stretched to 30 days
    js = run_js("console.log(JSON.stringify(L.constantMaturity([{ok:true,days:4,atm_iv:.14},{ok:true,days:11,atm_iv:.15}])));")
    assert js["iv"] is None and "30 days" in js["why"]


def test_read_set_matches_end_of_day():
    """Live and end-of-day read the same expiries: the nearest six plus the current, near and far month."""
    day = pd.Timestamp("2026-11-26")
    weeks = [pd.Timestamp(x) for x in ["2026-12-01", "2026-12-08", "2026-12-15", "2026-12-22", "2026-12-29", "2027-01-05",
                                       "2027-01-12", "2027-01-25", "2027-02-23", "2027-03-30", "2027-06-29"]]
    for exps in (weeks, weeks[4:], [weeks[4], weeks[7]], weeks[:3]):
        py = V.read_set(pd.DataFrame({"date": day, "expiry": exps}))
        py = {str(r.expiry.date()): r.series for r in py.itertuples()}
        js = run_js(f"console.log(JSON.stringify(L.readSet({json.dumps([str(e.date()) for e in exps])})));")
        assert js == py
    py = {str(r.expiry.date()): r.series for r in V.read_set(pd.DataFrame({"date": day, "expiry": weeks})).itertuples()}
    assert py["2026-12-29"] == "current month" and py["2027-01-25"] == "near month" and py["2027-02-23"] == "far month"
    assert "2027-01-05" in py and "2027-01-12" not in py and "2027-03-30" not in py   # 7th weekly out; 4th month out


def test_thin_monthly_is_measured_against_monthlies():
    """A far month trading 0.1% of an expiry-week weekly but 5% of the current month is read, live and end-of-day."""
    day = pd.Timestamp("2026-11-26")
    w, m1, m2 = pd.Timestamp("2026-12-01"), pd.Timestamp("2026-12-29"), pd.Timestamp("2027-01-25")
    df = _chain(day, 1000.0, {w: 0.15, m1: 0.14, m2: 0.145})
    opt = df["kind"] != "FUT"
    df.loc[opt & (df["expiry"] == w), "contracts"] = 100000.0
    df.loc[opt & (df["expiry"] == m1), "contracts"] = 2000.0
    df.loc[opt & (df["expiry"] == m2), "contracts"] = 100.0
    t, js = compare(df, day)
    assert set(t["expiry"].dt.strftime("%Y-%m-%d")) == {"2026-12-01", "2026-12-29", "2027-01-25"}
    assert dict(zip(t["expiry"].dt.strftime("%Y-%m-%d"), t["series"])) == {"2026-12-01": "weekly", "2026-12-29": "current month", "2027-01-25": "near month"}
    assert all(js[e]["ok"] for e in ("2026-12-01", "2026-12-29", "2027-01-25"))


def test_futures_months_compare_each_contract_with_its_own_close():
    now = int(pd.Timestamp("2026-11-27 11:00", tz="Asia/Kolkata").timestamp() * 1000)
    q = {"X-FUT": {"ltp": 1010, "oi": 1100, "age_s": 3, "e": "2026-12-29"}, "X-FUT-2027-01-25": {"ltp": 1020, "oi": 220, "age_s": 3},
         "X-FUT-2027-02-23": {"ltp": 1030, "oi": 30, "age_s": 999}, "XY-FUT-2027-01-25": {"ltp": 5, "age_s": 1}}
    base = [{"expiry": "2026-12-29", "fut": 1000, "oi": 1000}, {"expiry": "2027-01-25", "fut": 1010, "oi": 200}, {"expiry": "2027-02-23", "fut": 1020, "oi": 30}]
    r = run_js(f"console.log(JSON.stringify(L.futuresMonths({json.dumps(q)}, 'X', {{nowMs: {now}, maxAge: 120}}, {json.dumps(base)}, 1000)));")
    assert [m["expiry"] for m in r] == ["2026-12-29", "2027-01-25"]                 # the far month is stale; XY is another underlying
    assert [m["series"] for m in r] == ["current month", "near month"]
    assert r[0]["dp"] == pytest.approx(0.01) and r[1]["doi"] == pytest.approx(0.1) and r[1]["spread"] == pytest.approx(10)
    assert r[0]["carry"] is not None and r[0]["basis"] == pytest.approx(10)
    q["X-FUT"]["age_s"] = 999                                                       # the near month stale: the next keeps its own name
    r = run_js(f"console.log(JSON.stringify(L.futuresMonths({json.dumps(q)}, 'X', {{nowMs: {now}, maxAge: 120}}, {json.dumps(base)}, 1000)));")
    assert [(m["expiry"], m["series"], m["spread"]) for m in r] == [("2027-01-25", "near month", None)]


def test_a_delayed_chain_is_read_with_its_age_and_a_stale_one_is_not():
    """Kotak rotates stock chains (about 6 minutes a round): a chain up to optMaxAge old is read, carrying its age."""
    day = pd.Timestamp("2026-11-26")
    df = _chain(day, 1000.0, {pd.Timestamp("2026-12-29"): 0.2})
    q = quotes_from_chain(df[df["date"] == day], "X")
    for k, v in q.items():
        if v["s"] == "opt":
            v["age_s"] = 300
    now_ms = int(pd.Timestamp("2026-11-26 15:30", tz="Asia/Kolkata").timestamp() * 1000)
    run = lambda o: run_js(f"const r = L.readUnderlying({json.dumps(q)}, 'X', {json.dumps(dict(nowMs=now_ms, maxAge=120, **o))});"
                           "console.log(JSON.stringify(r.expiries.map(e => ({ok: e.ok, age: e.age}))));")
    assert run({}) == []                                                   # prices-only age limit: no chain
    assert run({"optMaxAge": 480}) == [{"ok": True, "age": 300}]
    assert run({"optMaxAge": 240}) == []


def test_option_names_match_the_feed():
    r = run_js("console.log(JSON.stringify([L.optName('NIFTY','2026-12-08',25450,'PE'), L.optName('RELIANCE','2027-01-25',1402.5,'CE'), L.optName('M&M','2026-12-29',3200,'CE')]));")
    assert r == ["NIFTY08DEC2625450PE", "RELIANCE25JAN271402.5CE", "M&M29DEC263200CE"]
    # and the parser reads them back to the same expiry and strike
    q = {n: {"ltp": 10, "vol": 1, "oi": 1, "age_s": 1} for n in r}
    back = run_js(f"const c = L.chains({json.dumps(q)}, 'NIFTY', 120); console.log(JSON.stringify(Object.keys(c).map(e => [e, c[e][0].K, c[e][0].right])));")
    assert back == [["2026-12-08", 25450, "PE"]]


def test_intraday_straddle_recovers_the_vol_minute_by_minute():
    """A straddle priced at a known vol each minute reads back that vol; a stale leg leaves its minutes out."""
    K, F, sig, exp = 1000.0, 1002.0, 0.18, "2026-12-03"
    start = int(pd.Timestamp("2026-11-27 09:15", tz="Asia/Kolkata").timestamp() // 60)
    calls, puts = [], []
    for i in range(0, 60):
        m = start + i
        T = max((pd.Timestamp(f"{exp} 15:30", tz="Asia/Kolkata").timestamp() - m * 60) / 60, 1) / (365 * 1440)
        c = float(V._b76(F, K, T, sig, np.array(True)))
        p = float(V._b76(F, K, T, sig, np.array(False)))
        calls.append([m, c])
        if i < 30 or i >= 50:                                   # the put stops printing for 20 minutes
            puts.append([m, p])
    r = run_js(f"console.log(JSON.stringify(L.intraday({json.dumps(calls)}, {json.dumps(puts)}, {K}, '{exp}')));")
    assert len(r["minute"]) == 60 - 10                          # minutes 40..49: the put's last print is over 10 minutes old
    both = {m for m, _ in puts}                                 # minutes where both legs printed (30..39 carry a put up to 9 min old)
    fresh = [i for i, m in enumerate(r["minute"]) if m in both]
    assert len(fresh) == 40
    assert all(r["iv"][i] == pytest.approx(sig, abs=1e-5) for i in fresh)     # the vol it was priced at
    assert all(r["F"][i] == pytest.approx(F, abs=1e-6) for i in fresh)       # parity at the strike gives the forward back


def test_the_contract_expiring_today_is_kept_for_the_expiry_view_only():
    day = pd.Timestamp("2026-11-26")
    df = _chain(day, 1000.0, {day: 0.5, pd.Timestamp("2026-12-29"): 0.16})
    q = quotes_from_chain(df[df["date"] == day], "X")
    now_ms = int(pd.Timestamp("2026-11-26 11:00", tz="Asia/Kolkata").timestamp() * 1000)
    r = run_js(f"const r = L.readUnderlying({json.dumps(q)}, 'X', {{nowMs: {now_ms}, maxAge: 120}});"
               "console.log(JSON.stringify({exp: r.expiries.map(e => e.expiry), today: r.expiring ? r.expiring.expiry : null, n: r.expiring ? r.expiring.strikes.length : 0}));")
    assert r["exp"] == ["2026-12-29"] and r["today"] == "2026-11-26" and r["n"] > 10


def test_live_max_pain_matches_end_of_day():
    from marketlens.engine import expiry as X
    rng = np.random.default_rng(3)
    K = [float(k) for k in range(900, 1101, 10)]
    oi = pd.DataFrame({"strike": K, "oi_c": rng.integers(0, 9000, len(K)).astype(float), "oi_p": rng.integers(0, 9000, len(K)).astype(float)})
    by = {str(int(k)): {"CE": {"oi": c}, "PE": {"oi": p}} for k, c, p in zip(K, oi["oi_c"], oi["oi_p"])}
    js = run_js(f"console.log(JSON.stringify(L.maxPain({json.dumps(K)}, {json.dumps(by)})));")
    assert js == X.max_pain(oi)
