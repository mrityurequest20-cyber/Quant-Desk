"""Wider collection (data/collect_wide.py, collect-wide.yml): BSE routing, stock chains, release shards, health, and that
the new workflow stays read-only, fail-safe, pinned and clear of the live desk."""
import datetime as dt
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.data import collect_wide as W
from quantdesk.data import kotak_backfill as B
from quantdesk.intraday.feeds import IST

ROOT = Path(__file__).resolve().parents[1]
DAY = dt.date(2026, 10, 19)


def test_release_tags_are_quarterly_and_yearly():
    assert W.release_tag("option-minutes", dt.date(2026, 10, 19)) == "option-minutes-2026Q4"
    assert W.release_tag("chains", dt.date(2027, 1, 4), "quarter") == "chains-2027Q1"
    assert W.release_tag("chains", dt.date(2026, 10, 19), "year") == "chains-2026"


def test_shipped_config_lists_five_indices_and_twenty_stocks():
    cfg = Config.load(DEFAULT_CONFIG)
    S = W.settings(cfg)
    assert S["indices"] == ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"]
    assert len(S["stocks"]) == 20 and len(set(S["stocks"])) == 20 and S["shard"] == "quarter"
    assert S["min_gap_sec"] >= 0.06 and set(S["indices"]) <= set(cfg.get("instruments"))


class BseKotak:
    """Records which segment each call used; the NSE-only fake in test_kotak_backfill has no `exchange` argument."""
    def __init__(self):
        self.seen, self.calls = [], {}

    def expiries(self, u, exchange="nse_fo"):
        self.seen.append(("expiries", exchange))
        return [dt.date(2026, 10, 22)]

    def option_chain(self, u, exp, count, exchange="nse_fo"):
        self.seen.append(("chain", exchange))
        legs = lambda r: [{"inst": {"strkPrc": "82000", "neoSymbol": f"{exchange}|{r}1"}}]   # noqa: E731
        return {"data": {"call": legs("C"), "put": legs("P")}}

    def _get(self, path, params):
        raise AssertionError("BSE futures must not be asked for (KotakFutures reads nse_fo only)")

    def candles(self, token, interval, start, end, raw=False):
        self.seen.append(("candles", token.split("|")[0]))
        idx = pd.DatetimeIndex([pd.Timestamp("2026-10-19 09:15", tz=IST)])
        return pd.DataFrame({"open": [1.0], "high": [2.0], "low": [1.0], "close": [1.5], "volume": [3.0]}, index=idx)


def test_sensex_goes_to_bse_fo_and_bse_cm_and_skips_futures(tmp_path):
    k = BseKotak()
    man = B.backfill(k, tmp_path, ["SENSEX"], days=3, n_expiries=1, strikes=20, today=DAY, say=lambda *a: None)
    assert {s for _, s in k.seen} == {"bse_fo", "bse_cm"}          # never nse_fo / nse_cm for SENSEX
    assert ("candles", "bse_cm") in k.seen and man["underlyings"]["SENSEX"]["bars"] == 2
    assert "futures_bars" not in man["underlyings"]["SENSEX"]


def _chain(spot_attr):
    from quantdesk.intraday.chains import COLUMNS, DEPTH
    df = pd.DataFrame(np.nan, index=pd.Index([100.0, 110.0, 120.0], name="strike"), columns=COLUMNS + DEPTH)
    df["ce_ltp"], df["pe_ltp"] = [12.0, 5.5, 2.0], [1.0, 5.0, 11.5]
    df.attrs.update({"spot": spot_attr})
    return df


def test_stock_spot_comes_from_put_call_parity():
    assert W.parity_spot(_chain(float("nan"))) == 110.5
    assert np.isnan(W.parity_spot(_chain(1.0).assign(pe_ltp=np.nan)))


def test_health_marks_each_source_and_never_calls_unreadable_missing():
    man = {"underlyings": {
        "NIFTY": {"bars": 500, "last": "2026-10-19 15:29:00+05:30", "served": 40, "asked": 41},
        "SENSEX": {"bars": 0, "errors": {"index: HTTP 400": 1}},
        "FINNIFTY": {"bars": 90, "last": "2026-10-16 15:29:00+05:30"}}}
    rows = {r["source"]: r for r in W.health(DAY, man, [f"{DAY}_wide-eod-9_chains.parquet"],
                                             [f"{DAY}_afternoon-7_chains.parquet"],
                                             ["NIFTY", "SENSEX", "FINNIFTY", "BANKNIFTY"], 20)}
    assert rows["minutes:NIFTY"]["status"] == "OK"
    assert rows["minutes:SENSEX"]["status"] == "MISSING" and "HTTP 400" in rows["minutes:SENSEX"]["detail"]
    assert rows["minutes:FINNIFTY"]["status"] == "MISSING" and "not today" in rows["minutes:FINNIFTY"]["detail"]
    assert rows["minutes:BANKNIFTY"]["status"] == "MISSING"
    assert rows["stock_chains"]["status"] == rows["desk_tape"]["status"] == "OK"
    unknown = {r["status"] for r in W.health(DAY, None, None, None, ["NIFTY"], 20)}
    assert unknown == {"UNKNOWN"}
    lines = W.render(DAY, W.health(DAY, man, [], [], ["NIFTY"], 20))
    assert all(l.startswith("HEALTH 2026-10-19 ") for l in lines) and any("MISSING" in l for l in lines)


def test_stock_window_is_the_session_until_the_deadline():
    at = lambda hm: pd.Timestamp(f"2026-10-19 {hm}", tz=IST)   # noqa: E731
    assert W.in_stock_window(at("15:25"), "15:35") and not W.in_stock_window(at("15:50"), "15:35")
    assert not W.in_stock_window(at("08:00"), "15:35")


class FakeChainSrc:
    def __init__(self, bad=()):
        self.bad = set(bad)

    def expiries(self, s):
        return [dt.date(2026, 10, 27), dt.date(2026, 11, 24)]

    def chain(self, s, e, spot=None, ts=None):
        if s in self.bad:
            raise RuntimeError("empty option chain")
        ch = _chain(float("nan"))
        ch.attrs.update({"underlying": s, "expiry": e, "ts": ts, "source": "kotak", "quoted": 6})
        return ch


def test_snapshot_stocks_isolates_failures_and_writes_the_tapes_layout(tmp_path):
    now = pd.Timestamp("2026-10-19 15:25", tz=IST)
    rep = W.snapshot_stocks(FakeChainSrc(bad={"ONGC"}), ["RELIANCE", "ONGC"], tmp_path, 1, now, say=lambda m: None)
    assert rep["RELIANCE"]["ok"] and rep["RELIANCE"]["expiries"] == 1 and not rep["ONGC"]["ok"]
    assert (tmp_path / "2026-10-19" / "chains" / "RELIANCE_2026-10-27_1525.csv").exists()
    from quantdesk.data.archive import archive
    names = archive(tmp_path, "wide-eod-1", tmp_path / "pq", dt.date(2026, 10, 19), None, say=lambda m: None)
    assert names == ["2026-10-19_wide-eod-1_chains.parquet"]
    df = pd.read_parquet(tmp_path / "pq" / names[0])
    assert set(df["underlying"]) == {"RELIANCE"} and (df["spot"] == 110.5).all()


# ---- the workflow ------------------------------------------------------------------------------------------------------
WF = ROOT / ".github" / "workflows" / "collect-wide.yml"


def test_workflow_is_read_only_pinned_isolated_and_adds_no_secret():
    text = WF.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    chain = yaml.safe_load((ROOT / ".github" / "workflows" / "chain-archive.yml").read_text(encoding="utf-8"))
    live = yaml.safe_load((ROOT / ".github" / "workflows" / "live.yml").read_text(encoding="utf-8"))
    assert wf["permissions"]["contents"] == "write" == chain["permissions"]["contents"] and len(wf["permissions"]) == 1
    assert all("permissions" not in j for j in wf["jobs"].values())
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"KOTAK_CONSUMER_KEY"}
    assert "secrets.KOTAK_CONSUMER_KEY" in live["env"]["KOTAK_CONSUMER_KEY"]
    for uses in re.findall(r"uses:\s*(\S+)", text):
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", uses), uses
    assert wf["concurrency"]["group"] == "collect-wide" != live["concurrency"]["group"]
    assert wf["concurrency"]["cancel-in-progress"] is False
    for job in wf["jobs"].values():                               # a failing step never fails the run or reaches the desk
        for st in job["steps"]:
            if "collect-wide --step" in st.get("run", "") and "tee" in st["run"]:
                assert st.get("continue-on-error") is True
    assert "quantdesk intraday" not in text and "journal" not in text.replace("the journal, the", "")


def test_workflow_schedule_stocks_in_session_minutes_after_close():
    wf = yaml.safe_load(WF.read_text(encoding="utf-8"))
    crons = [s["cron"] for s in wf.get("on", wf.get(True))["schedule"]]
    ist = []
    for c in crons:
        t = (int(c.split()[1]) * 60 + int(c.split()[0]) + 330) % 1440
        ist.append(t // 60 * 100 + t % 60)
    assert ist == [1525, 1545]                                    # 09:55 and 10:15 UTC
    assert wf["jobs"]["stocks"]["if"].count(crons[0]) == 1 and wf["jobs"]["minutes"]["if"].count(crons[1]) == 1


def test_live_workflow_is_untouched_by_this_change():
    text = (ROOT / ".github" / "workflows" / "live.yml").read_text(encoding="utf-8")
    assert "collect-wide" not in text and "collect_wide" not in text
