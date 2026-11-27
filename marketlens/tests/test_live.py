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
