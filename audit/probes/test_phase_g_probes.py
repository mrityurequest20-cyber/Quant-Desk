"""Phase G forensic probes (read-only: synthetic inputs, a copy of the journal; no model is called).

    QD_JOURNAL=/tmp/qd_journal/intraday python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes

Each passing probe CONFIRMS the finding or control it names (audit/QUANTDESK_FINDINGS_REGISTER.md).
"""
import inspect
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

REPO = Path(os.environ.get("QD_REPO", str(Path(__file__).resolve().parents[2])))
JOURNAL = Path(os.environ.get("QD_JOURNAL", "/nonexistent"))
sys.path.insert(0, str(REPO))
IST = "Asia/Kolkata"


def _cfg():
    from quantdesk.config import Config, DEFAULT_CONFIG
    return Config.load(DEFAULT_CONFIG)


# ---- G-03: malformed LLM output becomes a confident read --------------------------------------------------------
def test_prose_fallback_turns_an_index_name_into_a_max_bullish_read():
    from quantdesk.intraday.llm import _parse_reads
    r = _parse_reads("h1: The NIFTY 50 may slip on crude. BANKNIFTY flat.", {"h1"})
    assert r["h1"]["NIFTY"] == 1.0                                 # "NIFTY 50 may slip" → +1.0 (max bullish)
    r = _parse_reads("h1 — NIFTY at 22,500 support holds; Bank Nifty 54,800. Mildly bearish.", {"h1"})
    assert r["h1"]["NIFTY"] == 1.0 and r["h1"]["BANKNIFTY"] == 1.0   # index levels read as signals
    assert r["h1"]["confidence"] == 0.5                            # a confidence the model never gave


def test_out_of_range_llm_json_is_clipped_and_accepted_not_rejected():
    from quantdesk.intraday.llm import _parse_reads
    bad = '{"reads":[{"id":"h1","nifty":7,"banknifty":-3,"confidence":2,"event":"made_up","why":"x"}]}'
    r = _parse_reads(bad, {"h1"})["h1"]
    assert (r["NIFTY"], r["BANKNIFTY"], r["confidence"], r["event"]) == (1.0, -1.0, 1.0, "general")


# ---- V-35 / V-36: advisory-only and arrival-time gating hold -----------------------------------------------------
def test_advisory_reader_and_unarrived_reads_never_move_the_tone():
    from quantdesk.intraday.news import NewsDesk
    nd = NewsDesk(_cfg(), fetch=lambda *a, **k: None, sources=[])
    now = pd.Timestamp("2026-10-08 10:00", tz=IST)
    x = SimpleNamespace(sentiment=0.0, nlp={"llm": {"readers": {
        "ollama": {"NIFTY": 1.0, "confidence": 1.0, "at": "2026-10-08 09:59:00+05:30"},      # advisory only
        "gemini": {"NIFTY": -1.0, "confidence": 1.0, "at": "2026-10-08 10:05:00+05:30"}}}})  # arrives later
    assert nd.item_tone(x, "NIFTY", now) == 0.0                   # neither counts at 10:00
    later = pd.Timestamp("2026-10-08 10:06", tz=IST)
    assert nd.item_tone(x, "NIFTY", later) == pytest.approx(-0.5)   # gemini, once arrived, votes with the rules


def test_llm_outputs_have_no_path_to_orders_sizing_or_risk():
    for mod in ("playbook", "risk", "quant", "sim", "sleeves"):
        src = (REPO / f"quantdesk/intraday/{mod}.py").read_text()
        assert "llm" not in src.lower() and "reflect" not in src
    eng = (REPO / "quantdesk/intraday/engine.py").read_text()
    assert eng.count('memory.d["lessons"]') == 1 and 'self.memory.d["lessons"].append' in eng   # written, never read


# ---- G-04: no model or prompt provenance on a read -----------------------------------------------------------------
def test_reads_carry_no_model_id_or_prompt_version():
    from quantdesk.intraday import llm
    r = llm._parse_reads('{"reads":[{"id":"h1","nifty":0.2,"banknifty":0.1,"confidence":0.6,"event":"policy","why":"x"}]}', {"h1"})
    assert set(r["h1"]) == {"NIFTY", "BANKNIFTY", "confidence", "event", "why"}   # + "at" when queued; no model
    src = inspect.getsource(llm)
    assert "hashlib" not in src and "prompt_version" not in src
    assert len(llm.GeminiReader.FALLBACK) >= 6                     # reads stay "gemini" across up to 7 models
    assert 'fallbacks="default"' in src                            # Claude: server-side fallback model, unrecorded


# ---- G-05 / G-06: production record of the readers ---------------------------------------------------------------
def _db():
    import sqlite3
    p = JOURNAL / "journal.db"
    if not p.exists():
        pytest.skip("journal snapshot not available")
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def test_llm_failures_are_logged_at_info_inside_the_cost_line():
    with _db() as c:
        ev = pd.read_sql("SELECT level, message FROM events WHERE category = 'llm'", c)
    probs = ev[ev.message.str.contains("problems:")]
    assert len(probs) >= 2 and set(probs.level) == {"INFO"}       # timeouts never reach WARN/ERROR (self-review blind)


def test_claude_never_ran_in_production_so_no_reflection():
    with _db() as c:
        ev = pd.read_sql("SELECT message FROM events WHERE category = 'llm'", c)
    assert not ev.message.str.contains("claude").any()
    m = json.loads((JOURNAL / "memory.json").read_text())
    assert m.get("lessons", []) == []
    assert set(m["tables"]["news_reader"]) == {"rules", "gemini", "ollama"}


def test_gemini_is_up_weighted_on_an_untested_record():
    m = json.loads((JOURNAL / "memory.json").read_text()) if (JOURNAL / "memory.json").exists() else pytest.skip("no snapshot")
    g = m["tables"]["news_reader"]["gemini"]
    shrunk = (g["hits"] + 10) / (g["n"] + 20)
    assert 1.1 < min(1.5, max(0.5, 2 * shrunk)) < 1.2             # ≈ ×1.16 trust, no CI, no placebo (cf. D-01)


# ---- G-01: the autonomous engineer's limits are prose, not controls ------------------------------------------------
def test_risk_limit_tests_read_the_config_so_loosening_it_passes():
    src = (REPO / "tests/test_intraday.py").read_text()
    assert 'cfg.get("intraday.risk.daily_loss_limit")' in src      # relative to config, not a pinned ceiling
    assert not re.search(r"daily_loss_limit\"?\)?\s*(<=|==)\s*0\.\d", src)


def test_spec_immutability_test_covers_only_specs_with_results():
    from quantdesk.research import memory as M
    reg = {r["name"]: r for r in M.registry()}
    unguarded = sorted(n for n, r in reg.items() if not r["results"])
    assert {"expiry_seller_v1", "expiry_seller_v3", "expiry_eve_entry_v1"} <= set(unguarded)


def test_autonomy_doc_grants_unreviewed_merge_authority():
    doc = (REPO / "docs/AUTONOMY.md").read_text()
    assert "The owner is not in the loop" in doc and "merge the branch into main" in doc
    assert "needs a **CLEAR** from the `risk-compliance` agent" in doc       # the reviewer is another agent
    assert not any((REPO / p).exists() for p in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"))
