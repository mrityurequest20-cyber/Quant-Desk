"""Phase A forensic probes (read-only: temp dirs only, no repo state touched).

Run from the repo root (they are outside tests/, so CI never collects them):

    git fetch origin journal && mkdir -p /tmp/qd_journal && git archive FETCH_HEAD | tar -x -C /tmp/qd_journal
    QD_JOURNAL=/tmp/qd_journal/intraday python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes

Without QD_JOURNAL the probes that need the journal snapshot skip. Each probe documents an observed behaviour; a
passing probe CONFIRMS the finding it names (finding IDs: audit/QUANTDESK_FINDINGS_REGISTER.md).
"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(os.environ.get("QD_REPO", str(Path(__file__).resolve().parents[2])))
JOURNAL = Path(os.environ.get("QD_JOURNAL", "/nonexistent"))
sys.path.insert(0, str(REPO))

IST = "Asia/Kolkata"


def _session(day="2026-10-08", drop=("12:20", "12:21"), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq="1min", tz=IST)
    c = 22500 * np.exp(np.cumsum(rng.normal(0, 4e-4, len(idx))))
    df = pd.DataFrame({"open": c, "high": c * 1.0002, "low": c * 0.9998, "close": c, "volume": 1000.0}, index=idx)
    keep = ~pd.Index([t.strftime("%H:%M") for t in idx]).isin(drop)
    return df[keep]


# ---- F-A05: row-count 5m bucketing after a missing minute -------------------------------------------------------
def test_rowcount_bucketing_makes_partial_last_bar():
    from quantdesk.intraday.quant import to_5m
    today = _session()
    now = pd.Timestamp("2026-10-08 12:30:30", tz=IST)          # 12:29 bar has completed
    seen = today[today.index + pd.Timedelta(minutes=1) <= now]
    n5 = len(seen) // 5                                         # engine.py:1050 / live.py:100
    live_five = to_5m(seen.iloc[:n5 * 5])
    clock_five = to_5m(seen)                                    # what the training path builds (by clock)
    last_live = live_five.index[-1]
    minutes_in_last = int(((seen.index >= last_live) & (seen.index < last_live + pd.Timedelta(minutes=5))
                           & np.isin(np.arange(len(seen)), np.arange(n5 * 5))).sum())
    # the live path's last 5m bar (12:25) holds only 2 of its 5 minutes, yet is treated as complete
    assert str(last_live.time()) == "12:25:00"
    assert minutes_in_last == 2
    assert live_five["close"].iloc[-1] != clock_five["close"].iloc[-1]


def test_rowcount_bucketing_on_real_recorded_session():
    """Every recorded session in the journal snapshot misses 12:20-12:21 (handover); the live path then mis-buckets."""
    from quantdesk.intraday.quant import to_5m, features_5m
    p = JOURNAL / "data" / "2026-10-08" / "NIFTY_1m.csv"
    if not p.exists():
        pytest.skip("journal snapshot not available")
    from quantdesk.intraday.feeds import normalise_bars
    bars = normalise_bars(pd.read_csv(p, index_col=0, parse_dates=True))
    mism = 0
    checks = 0
    for hhmm in ("12:30", "13:00", "14:00", "15:00"):
        now = pd.Timestamp(f"2026-10-08 {hhmm}:05", tz=IST)
        seen = bars[bars.index + pd.Timedelta(minutes=1) <= now]
        n5 = len(seen) // 5
        live = features_5m(to_5m(seen.iloc[:n5 * 5])).iloc[-1]
        clock5 = to_5m(seen)
        clock5 = clock5[clock5.index + pd.Timedelta(minutes=5) <= now]
        clock = features_5m(clock5).iloc[-1]
        checks += 1
        mism += int(not np.allclose(live[["r5", "vwap_z", "rsi"]].to_numpy(float), clock[["r5", "vwap_z", "rsi"]].to_numpy(float)))
    assert mism == checks, f"{mism}/{checks} afternoon decisions differ between live and training feature paths"


# ---- F-A03: LiveLearner writes nothing when no model is registered -------------------------------------------------
def test_livelearner_records_nothing_without_registered_model():
    from quantdesk.config import Config, DEFAULT_CONFIG
    from quantdesk.autolearn.live import LiveLearner
    cfg = Config.load(DEFAULT_CONFIG)
    with tempfile.TemporaryDirectory() as d:
        ll = LiveLearner(cfg, root=Path(d))
        ll.start(pd.Timestamp("2026-10-08").date())
        bars = _session(drop=())
        now = pd.Timestamp("2026-10-08 11:00:30", tz=IST)
        out = ll.on_bar("NIFTY", now, bars[bars.index + pd.Timedelta(minutes=1) <= now], pd.Timestamp("2026-10-08").date(),
                        22400.0, 8e-4)
        assert out is None
        assert not (Path(d) / "ledger").exists() or not any((Path(d) / "ledger").glob("predictions-*"))


# ---- F-A06: LockBox.verify ignores a change in row count --------------------------------------------------------------
def test_lockbox_verify_silent_when_rowcount_changes():
    from quantdesk.autolearn.validation import LockBox
    days = [f"2026-09-{d:02d}" for d in range(1, 25)]
    s = pd.DataFrame({"day": np.repeat(days, 10), "symbol": "NIFTY",
                      "ts": pd.date_range("2026-09-01", periods=240, freq="h", tz=IST), "y": np.tile([0.0, 1.0], 120)})
    with tempfile.TemporaryDirectory() as d:
        lb = LockBox(Path(d))
        lock = lb.ensure(s, 8)
        assert lb.verify(s) == []
        flipped = s.copy()
        locked = flipped["day"].isin(lock["days"])
        flipped.loc[locked, "y"] = 1 - flipped.loc[locked, "y"]          # every locked label changed
        assert lb.verify(flipped) != []                                 # detected when the row count is unchanged
        dropped_one = flipped.drop(flipped.index[locked][0])            # ... but drop one row as well
        assert lb.verify(dropped_one) == []                             # every label changed, verify says nothing


# ---- F-A07: build_samples back-fills σ into the first bars of each session -------------------------------------------
def test_build_samples_sig5_uses_later_bars():
    from quantdesk.autolearn.features import build_samples
    from quantdesk.intraday.quant import to_5m
    b5 = to_5m(_session(drop=()))
    a = build_samples(b5, "NIFTY")
    b5_mod = b5.copy()
    b5_mod.iloc[3, b5_mod.columns.get_loc("close")] *= 1.01             # change only the 4th bar
    b = build_samples(b5_mod, "NIFTY")
    assert a["sig5"].iloc[0] != b["sig5"].iloc[0]                       # row 0 depends on bar 3: not causal
    # ... while the model features of row 0 are unchanged (they are causal)
    from quantdesk.intraday.quant import FEATURES
    assert np.allclose(a[FEATURES].iloc[0].to_numpy(float), b[FEATURES].iloc[0].to_numpy(float))


# ---- F-A04: Kotak → Yahoo per-minute substitution leaves no per-bar provenance ------------------------------------------
def test_kotak_failure_silently_serves_yahoo_bars():
    from quantdesk.config import Config, DEFAULT_CONFIG
    from quantdesk.intraday import kotak as K
    from quantdesk.intraday.feeds import YahooIntradayFeed
    cfg = Config.load(DEFAULT_CONFIG)

    class Dead:
        def candles(self, *a, **k):
            raise K.KotakError("HTTP 503")

    feed = K.KotakIntradayFeed(cfg, Dead())
    yb = _session(drop=()).iloc[:30]
    feed.now = lambda: pd.Timestamp("2026-10-08 09:46:00", tz=IST)
    orig = YahooIntradayFeed.poll
    YahooIntradayFeed.poll = lambda self, s, since: yb
    try:
        feed._with_futures = lambda s, df, a, b: df
        got = feed.poll("NIFTY", None)
    finally:
        YahooIntradayFeed.poll = orig
    assert len(got) == 30
    assert list(got.columns) == ["open", "high", "low", "close", "volume"]   # no source column on the bars
    assert "source" not in got.attrs
    assert feed.served["yahoo"] == 1 and feed.last_error.startswith("HTTP 503")


# ---- F-A08: news graded from publish time, not from when the desk saw it -----------------------------------------------
def test_grade_news_uses_publish_time_not_seen_time():
    from quantdesk.intraday.learning import Memory, grade_news
    idx = pd.date_range("2026-10-08 09:15", "2026-10-08 15:29", freq="1min", tz=IST)
    c = np.full(len(idx), 22500.0)
    c[(idx >= pd.Timestamp("2026-10-08 10:00", tz=IST)) & (idx < pd.Timestamp("2026-10-08 10:30", tz=IST))] = \
        np.linspace(22500, 22700, 30)                                  # the move happens 10:00-10:30
    c[idx >= pd.Timestamp("2026-10-08 10:30", tz=IST)] = 22700.0          # flat after
    bars = {"NIFTY": pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 0.0}, index=idx)}
    news = pd.DataFrame([{"id": "n1", "ts": "2026-10-08 10:00:00+05:30", "seen_at": "2026-10-08 11:15:00+05:30",
                          "source": "X", "sentiment": 0.8, "about": json.dumps({"NIFTY": 4}), "nlp": json.dumps({})}])
    with tempfile.TemporaryDirectory() as d:
        mem = Memory(Path(d) / "m.json")
        n = grade_news(mem, news, bars)
        assert n == 1
        t = mem.d["tables"]["news_reader"]["rules"]
        # graded a HIT on the 10:00-10:30 move although the desk saw the story at 11:15, when nothing moved after
        assert t["n"] == 1.0 and t["hits"] == 1.0          # a full hit, from a window the desk never traded


# ---- F-A10: the journal snapshot: what the persisted state actually holds -----------------------------------------------
def test_persisted_state_facts():
    db = JOURNAL / "journal.db"
    if not db.exists():
        pytest.skip("journal snapshot not available")
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        trades = c.execute("select count(*) from trades").fetchone()[0]
    reg = json.loads((JOURNAL / "autolearn" / "registry" / "state.json").read_text())
    assert trades == 0
    assert reg["champion"] is None and reg["challengers"] == []
    assert not (JOURNAL / "autolearn" / "ledger").exists()
