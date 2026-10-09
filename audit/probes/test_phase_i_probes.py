"""Phase I forensic probes: journal and auditability (read-only: journal copies opened mode=ro, temp dirs, synthetic data).

    QD_JOURNAL=<close snapshot>/intraday QD_JOURNAL_PREV=<12:20 snapshot>/intraday QD_CHAINS=<chains-2026 parquet dir> \
      python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes/test_phase_i_probes.py

Each passing probe CONFIRMS the Phase I finding or control it names (audit/QUANTDESK_PHASE_I_AUDITABILITY.md).
Probes that need a journal copy or the chain archive skip when the variable is unset.
"""
import inspect
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("QD_REPO", str(HERE.parents[1])))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))


def _dir(var):
    p = os.environ.get(var)
    if not p or not Path(p).exists():
        pytest.skip(f"{var} not set")
    return Path(p)


def _ro(db: Path):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


@pytest.fixture(scope="module")
def world():
    import phase_h_det_tests as H
    return H, *H.world()


# ---- I-01: the recorded India VIX is 0 on every Kotak session, and the analyst reads it as a −100 % crash ------------
def test_recorded_india_vix_is_zero_on_every_kotak_session():
    data = _dir("QD_JOURNAL") / "data"
    zero_share = {d.name: (pd.read_csv(d / "INDIAVIX_1m.csv")["close"] <= 0).mean()
                  for d in sorted(data.iterdir()) if (d / "INDIAVIX_1m.csv").exists()}
    assert zero_share["2026-09-29"] == 0                                                   # Yahoo era: real values
    kotak = {d: s for d, s in zero_share.items() if d >= "2026-10-05"}
    assert len(kotak) >= 4 and all(s > 0.99 for s in kotak.values())                      # ≥ 372 of 373 bars = 0


def test_every_production_read_carries_a_fabricated_vix_vote():
    with _ro(_dir("QD_JOURNAL") / "journal.db") as c:
        ev = [json.loads(e) for (e,) in c.execute("SELECT evidence FROM thoughts")]
    vix = [x for e in ev for x in e if x["factor"] == "vix"]
    fake = [x for x in vix if x["observation"].startswith("India VIX 0.00 (-100.0% today)") and x["direction"] == 1.0]
    assert len(ev) >= 743 and len(fake) >= len(ev) - 1                                     # 742 / 743: max-bullish vote


def test_thought_scores_recompute_exactly_and_the_vix_vote_flips_bias_labels():
    out = json.loads(_run("phase_i_thought_recompute.py", _dir("QD_JOURNAL") / "journal.db"))
    assert out["score_recomputed_exactly"] == out["thoughts"] == out["bias_recomputed_exactly"]   # control V-I1
    assert out["bias_label_flips_without_vix"] >= 20                                        # 23 of 743 in production


# ---- I-02: the news record of "when the desk saw it" is overwritten by every new job ---------------------------------
def test_news_first_seen_and_llm_reads_are_overwritten_between_snapshots():
    out = json.loads(_run("phase_i_news_mutation.py", _dir("QD_JOURNAL_PREV") / "journal.db",
                          _dir("QD_JOURNAL") / "journal.db"))
    c = out["counts"]
    assert out["changed_rows"] >= 274 and c["seen_at later"] == out["changed_rows"] and c["seen_at earlier"] == 0
    assert c["llm readers lost"] >= 1 and c["ts later"] + c["ts earlier"] >= 1


def test_news_dedup_lives_in_memory_and_news_add_replaces_rows():
    from quantdesk.intraday import engine, news
    from quantdesk.journal import journal
    assert "INSERT OR REPLACE INTO news" in inspect.getsource(journal.Journal.news_add)
    assert "journal.news(" not in inspect.getsource(engine) and "self.items.get(it.id)" in inspect.getsource(news.NewsDesk.refresh)


# ---- I-03: no code / config / model provenance on any record -----------------------------------------------------------
def test_journal_records_no_code_config_or_model_provenance():
    from quantdesk.journal.journal import SCHEMA
    assert not re.search(r"\b(commit|sha|git|config|version|model_id)\b", SCHEMA, re.I)
    with _ro(_dir("QD_JOURNAL") / "journal.db") as c:
        blob = " ".join(str(v) for t in ("events", "decisions", "state") for r in c.execute(f"SELECT * FROM {t}") for v in r)
    assert "c96909f" not in blob and "FEATURE_VERSION" not in blob


# ---- I-05: records are mutable and nothing detects an edit ------------------------------------------------------------
def test_silent_edits_pass_every_integrity_check():
    src = _dir("QD_JOURNAL") / "journal.db"
    tmp = Path(tempfile.mkdtemp(prefix="i-tamper-")) / "journal.db"
    shutil.copy(src, tmp)
    with sqlite3.connect(tmp) as c:
        c.execute("UPDATE decisions SET detail='entered: approved by the plan model' WHERE id=(SELECT max(id) FROM decisions)")
        c.execute("DELETE FROM events WHERE id=(SELECT max(id) FROM events)")
        c.execute("UPDATE thoughts SET bias='bearish', score=-0.9 WHERE id=(SELECT max(id) FROM thoughts)")
        c.commit()
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    from quantdesk.journal.journal import Journal
    j = Journal(tmp)
    assert j.integrity() == "ok"
    j.close()


def test_restating_a_trade_rewrites_fills_in_place():
    from quantdesk.intraday import account
    src = inspect.getsource(account.restate_trade)
    assert "UPDATE fills SET price=?" in src and "bp.write_text(" in src                    # no new fill row; non-atomic
    assert '"WARN", "restatement"' in src                                                   # the event records both versions


# ---- I-06: what the files show after an interrupted entry / exit (production journal setting) -------------------------
def test_production_opens_the_journal_with_autocommit_every_write():
    from quantdesk.intraday import cli
    assert "Journal(p[\"journal\"], autocommit_every=1)" in inspect.getsource(cli)


def test_interrupted_entry_leaves_an_orphan_fill_that_reconcile_never_reads(world):
    H, bars, days = world
    import phase_i_evidence as E
    r = E.entry_crash(bars, days[-1])
    a, e = r["after_crash"], r["end"]
    assert a["orphan_fill_count"] == 1 and a["positions_match"] and a["cash_match"]          # reconstructable from fills
    from quantdesk.intraday.engine import IntradayEngine
    src = inspect.getsource(IntradayEngine._reconcile)
    assert e["critical_events"] and "FROM fills" not in src and "journal.df" not in src and ".fills" not in src


def test_interrupted_exit_shows_a_double_exit_in_fills(world):
    H, bars, days = world
    import phase_i_evidence as E
    r = E.exit_crash(bars, days[-1])
    tc = next(iter(r["end"]["trade_checks"].values()))
    assert tc["status"] == "closed" and not tc["consistent"]                                 # "closed" but fills net −65
    assert min(tc["fills_net"].values()) == -65 and r["end"]["positions_match"]


def test_reconcile_event_is_stamped_at_the_session_open_before_the_crash_it_reports(world):
    H, bars, days = world
    import phase_i_evidence as E
    E.entry_crash(bars, days[-1])
    tmp = sorted(Path(tempfile.gettempdir()).glob("i-8a-*"), key=lambda p: p.stat().st_mtime)[-1]
    with _ro(tmp / "j.db") as c:
        ev_ts = c.execute("SELECT ts FROM events WHERE level='CRITICAL'").fetchone()[0]
        fill_ts = c.execute("SELECT ts FROM fills").fetchone()[0]
    assert ev_ts.endswith("09:15:00+05:30") and pd.Timestamp(ev_ts) < pd.Timestamp(fill_ts)


def test_an_executed_entry_writes_no_decision_row():
    from quantdesk.intraday.engine import IntradayEngine
    calls = re.findall(r"journal\.decision\([^)]*?\"(\w+)\"", inspect.getsource(IntradayEngine))
    assert calls and set(calls) == {"rejected"}


# ---- I-07: decisions don't identify the inputs they used ----------------------------------------------------------------
def test_decision_text_reports_a_p_up_the_ev_did_not_use():
    with _ro(_dir("QD_JOURNAL") / "journal.db") as c:
        rows = c.execute("SELECT detail, context FROM decisions WHERE context LIKE '%\"ev\"%'").fetchall()
    diff = sum(abs(float(re.search(r"P\(up\) ([\d.]+)", d).group(1)) - json.loads(x)["ev"]["p_up"]) > 0.005 for d, x in rows)
    assert len(rows) >= 51 and diff >= 30                                                   # 33 of 51


def test_only_a_minority_of_decisions_match_an_archived_snapshot():
    out = json.loads(_run("phase_i_snapshot_ident.py", _dir("QD_JOURNAL") / "journal.db", _dir("QD_CHAINS")))
    assert out["outcome"].get("matches only the latest snapshot", 0) <= 25 and out["decisions"] >= 73


def test_rejected_plans_can_be_valued_afterwards_from_persisted_evidence():
    out = json.loads(_run("phase_i_counterfactual.py", _dir("QD_JOURNAL") / "journal.db", _dir("QD_CHAINS")))
    assert out["valued"] >= 72                                                              # control V-I4


# ---- I-09: model_state with the production VIX ----------------------------------------------------------------------------
def test_zero_vix_prices_the_model_chain_at_zero_volatility():
    out = json.loads(_run("phase_i_vix_zero_model_chain.py"))
    z, n = out["vix_zero"], out["vix_normal"]
    assert z["model_state_iv"] == 0.0 and z["atm_ce_ltp"] < 0.3 * n["atm_ce_ltp"] and z["vix_state"]["chg"] == -1.0


def test_zero_prior_day_vix_makes_every_step_raise(world):
    H, bars, days = world
    b = {k: v.copy() for k, v in bars.items()}
    for col in ("open", "high", "low", "close"):
        b["INDIAVIX"][col] = 0.0
    eng = H.make(Path(tempfile.mkdtemp(prefix="i-vix0-")), b, days[-1])
    eng.start_session(days[-1])
    eng.feed.advance()
    with pytest.raises(ZeroDivisionError):
        eng.step()


# ---- I-10: market data persisted for every session? ---------------------------------------------------------------------
def test_no_recorded_market_data_for_2026_10_01():
    data = _dir("QD_JOURNAL") / "data"
    assert not (data / "2026-10-01").exists()
    assert len(pd.read_csv(data / "2026-09-30" / "NIFTY_1m.csv")) < 20                       # 09-30: 10 bars


def _run(script, *args):
    import subprocess
    r = subprocess.run([sys.executable, str(HERE / script), *map(str, args)], capture_output=True, text=True, cwd=REPO,
                       timeout=1500)
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout
