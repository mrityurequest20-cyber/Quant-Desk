"""The scout's journal (intraday/scoutlog.py): tamper-evident, cumulative, and fed by the commands."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.intraday import scout as C
from quantdesk.intraday import scout_lab as L
from quantdesk.intraday import scoutlog as J

REPO = Path(C.__file__).resolve().parents[2]


def test_entries_are_chained_and_an_edited_or_removed_one_is_found(tmp_path):
    j = J.ScoutJournal(tmp_path / "j.jsonl")
    a = j.add("observation", "blind entries lose", {"text": "3R reached 20%"})
    b = j.add("hypothesis", "compression then trend", {"text": "low ATR ratio"}, refs=[a["seq"]], tags=["compression"])
    assert (a["seq"], b["seq"]) == (1, 2) and b["prev"] == a["hash"] and b["refs"] == [1] and b["payload"]["status"] == "open"
    assert j.verify() == []
    lines = (tmp_path / "j.jsonl").read_text().splitlines()
    (tmp_path / "j.jsonl").write_text(lines[0].replace("blind entries lose", "blind entries win") + "\n" + lines[1] + "\n")
    assert any("altered" in p or "chain" in p for p in j.verify())
    (tmp_path / "j.jsonl").write_text(lines[1] + "\n")                        # entry 1 removed
    assert j.verify()


def test_an_unknown_kind_or_a_dangling_reference_is_refused(tmp_path):
    j = J.ScoutJournal(tmp_path / "j.jsonl")
    with pytest.raises(ValueError, match="kind"):
        j.add("gossip", "x")
    with pytest.raises(ValueError, match="not entries"):
        j.add("note", "x", refs=[7])
    with pytest.raises(ValueError, match="status"):
        j.set_status(1, "winning", "because")


def test_a_hypothesis_keeps_its_history_and_shows_its_latest_status(tmp_path):
    j = J.ScoutJournal(tmp_path / "j.jsonl")
    h = j.add("hypothesis", "H1")
    assert j.hypotheses()[0]["status"] == "open"
    j.set_status(h["seq"], "tested", "validation slice did not hold")
    j.set_status(h["seq"], "killed", "sealed test failed")
    assert j.hypotheses()[0]["status"] == "killed" and len(j.entries("status")) == 2     # the old status is still there
    assert "killed" in j.summary()


def test_the_running_trial_count_adds_up_across_runs(tmp_path):
    j = J.ScoutJournal(tmp_path / "j.jsonl")
    j.add("run", "r1", {"rows": 1000, "trials": {"cells": 0, "rules_tried": 0, "nulls": 0}})
    j.add("run", "r2", {"rows": 500, "trials": {"cells": 140, "rules_tried": 135000, "nulls": 8}})
    j.add("run", "r3", {"rows": 200, "trials": {"cells": 140, "rules_tried": 135000, "nulls": 8}})
    t = j.trials()
    assert t == {"runs": 3, "strategy_policy_cells": 280, "rules_tried": 270000, "search_nulls": 16, "candidates": 1700, "report_looks": 0}
    s = j.summary()
    assert "270,000 mined rules" in s and "judged against ALL of it" in s and "external_unverified" in s


def synthetic_grid(tmp_path):
    from quantdesk.intraday.synthetic import simulate_sessions
    days = [d.date() for d in pd.bdate_range("2020-10-01", "2020-12-15")]
    bars, _ = simulate_sessions(days, seed=2)
    df = C.build({s: bars[s] for s in ("NIFTY", "BANKNIFTY")}, ["NIFTY", "BANKNIFTY"], "index", vix=bars["INDIAVIX"]["close"], say=lambda *_: None)
    C._write(tmp_path / "grid", df, {"stop_atr": C.STOP_ATR}, {"path": "synthetic", "use": "synthetic"})
    return tmp_path / "grid"


def test_a_grid_run_is_recorded_with_its_base_rates_and_no_trials(tmp_path):
    j = J.ScoutJournal(tmp_path / "j.jsonl")
    rec = J.record_grid(j, synthetic_grid(tmp_path))
    p = rec["payload"]
    assert rec["kind"] == "run" and p["command"] == "scout" and p["sealed_from"] == "2023-01-01" and p["trials"]["cells"] == 0
    assert set(p["base_rates"]) == {"NIFTY", "BANKNIFTY"} and set(p["base_rates"]["NIFTY"]) == {"reach_2", "reach_3", "reach_4", "reach_6"}
    assert "never evidence" in rec["not_for"] and j.verify() == []
    assert "close" not in json.dumps(p) and "ohlc" not in json.dumps(p).lower()         # aggregates and parameters only, no prices


def test_a_lab_run_is_recorded_with_its_cells_and_every_search_it_ran(tmp_path):
    rng = np.random.default_rng(1)
    recs = []
    for day in pd.bdate_range("2019-01-01", periods=800):
        for strat, mu in (("good", 0.9), ("flat", -0.05)):
            for _ in range(3):
                r = rng.normal(mu, 1.0)
                recs.append({"strategy": strat, "symbol": "X", "kind": "index", "day": day.date(), **{c: r for c in C.POLICY_COLUMNS.values()}})
    out = tmp_path / "lab"
    L._finish(out, pd.DataFrame(recs), {"first": None}, {"path": "synthetic", "use": "synthetic"}, None, False, lambda *_: None)
    (out / "mined_grid.json").write_text(json.dumps({"outcome": "r_trail", "ledger": {"trials": 100, "nulls": 2, "conditions": 50, "max_depth": 3, "min_support": 10,
                                                                                      "top_k": 5, "seed": 1, "rules_clearing_support": 40, "cap_r": 10, "cost_r": 0.05},
                                                      "best_valid_mean": 0.12, "p_vs_null": 0.33, "null_best_valid_means": [0.1, 0.2], "rules": [{"rule": "f1>0.5"}]}))
    j = J.ScoutJournal(tmp_path / "j.jsonl")
    p = J.record_lab(j, out)["payload"]
    assert p["trials"] == {"cells": 14, "rules_tried": 300, "nulls": 2}              # the real search (100) plus the two null searches (200)
    assert p["leaderboard"]["cells"] == 14 and p["leaderboard"]["clears_bar"] >= 2 and p["mined"]["grid"]["p_vs_null"] == 0.33
    assert j.trials()["strategy_policy_cells"] == 14 and j.trials()["rules_tried"] == 300


def test_the_command_line_adds_moves_on_shows_verifies_and_summarises(tmp_path):
    jp = str(tmp_path / "j.jsonl")

    def run(*args):
        return subprocess.run([sys.executable, "-m", "quantdesk", "intraday", "scout-log", *args, "--journal", jp], capture_output=True, text=True, cwd=REPO)
    r = run("add", "--kind", "hypothesis", "--title", "compression precedes the big moves", "--text", "low ATR ratio", "--tag", "compression")
    assert r.returncode == 0 and "#1" in r.stdout
    assert run("add", "--kind", "note", "--title", "owner: December is the full review", "--by", "owner", "--ref", "1").returncode == 0
    assert run("status", "--hypothesis", "1", "--set", "tested", "--why", "held on the later slice").returncode == 0
    shown = run("show").stdout
    assert "hypothesis" in shown and "owner: December" in shown and "refs [1]" in shown
    assert "tested" in run("summary").stdout and run("verify").returncode == 0
    bad = run("add", "--kind", "note", "--title", "x", "--ref", "99")
    assert bad.returncode != 0 and "refused" in bad.stderr + bad.stdout
    lines = Path(jp).read_text().splitlines()
    Path(jp).write_text(lines[0].replace("compression", "expansion") + "\n" + "\n".join(lines[1:]) + "\n")
    assert run("verify").returncode == 1


def test_the_summary_prints_the_head_hash_and_calls_the_journal_accident_evident():
    import tempfile
    d = Path(tempfile.mkdtemp())
    j = J.ScoutJournal(d / "j.jsonl")
    j.add("note", "a")
    b = j.add("note", "b")
    assert j.head() == {"seq": 2, "hash": b["hash"]}
    t = j.summary()
    assert b["hash"] in t and "accident-evident" in t and "tamper-evident" not in t and "CHAIN BROKEN" not in t


def test_a_broken_chain_is_announced_at_the_top_of_the_summary_not_hidden_behind_a_total(tmp_path):
    j = J.ScoutJournal(tmp_path / "j.jsonl")
    j.add("run", "r1", {"rows": 10, "trials": {"cells": 140, "rules_tried": 1000, "nulls": 2}})
    j.add("note", "n")
    lines = (tmp_path / "j.jsonl").read_text().splitlines()
    edited = lines[0].replace("140", "1", 1)                                                                               # someone lowers the trial count
    assert edited != lines[0]
    (tmp_path / "j.jsonl").write_text(edited + "\n" + lines[1] + "\n")
    assert j.verify() and "CHAIN BROKEN" in j.summary().splitlines()[2]


def test_a_run_entry_cannot_be_typed_in_by_hand_but_a_backfill_records_when_the_run_really_ran(tmp_path):
    jp = str(tmp_path / "j.jsonl")

    def run(*args):
        return subprocess.run([sys.executable, "-m", "quantdesk", "intraday", "scout-log", *args, "--journal", jp], capture_output=True, text=True, cwd=REPO)
    r = run("add", "--kind", "run", "--title", "fake", "--json", '{"trials": {"cells": 0}}')
    assert r.returncode != 0 and "cannot be typed in" in r.stderr + r.stdout and not Path(jp).exists()
    grid = synthetic_grid(tmp_path)
    b = run("backfill", "--what", "grid", "--out", str(grid), "--ran-at", "2026-10-30T10:00:00+00:00")
    assert b.returncode == 0 and "ran_at 2026-10-30T10:00:00" in b.stdout and "head #1" in b.stdout
    e = J.ScoutJournal(jp).entries("run")[0]["payload"]
    assert e["backfill"] is True and e["ran_at"].startswith("2026-10-30T10:00") and len(e["run_fingerprint"]) == 64


def test_a_run_entry_carries_a_fingerprint_that_changes_when_a_result_file_does(tmp_path):
    grid = synthetic_grid(tmp_path)
    before = J.run_fingerprint(grid)
    assert before == J.run_fingerprint(grid)
    (grid / "manifest.json").write_text((grid / "manifest.json").read_text().replace('"rows"', '"rows_"', 1))
    assert J.run_fingerprint(grid) != before


def test_a_read_out_is_charged_for_every_look_it_took(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "looks.json").write_text(json.dumps({"feature_bin_rows": 190, "model_readouts": 8, "total": 198}))
    j = J.ScoutJournal(tmp_path / "j.jsonl")
    rec = J.record_report(j, out)
    assert rec["kind"] == "run" and rec["payload"]["trials"]["looks"] == 198 and j.trials()["report_looks"] == 198
    assert "198 read-out looks" in j.summary()


def _args(*argv):
    from quantdesk.cli import build_parser
    return build_parser().parse_args(["intraday", *argv])


def test_scout_with_report_charges_the_read_outs_looks_to_the_journal_too(tmp_path, monkeypatch):
    jp = tmp_path / "j.jsonl"
    cfg = type("Cfg", (), {"runtime_dir": tmp_path / "rt"})()

    def fake_run(dataset, out, symbols=None, stop_atr=None, first=None, last=None, say=print):
        from quantdesk.intraday.synthetic import simulate_sessions
        days = [d.date() for d in pd.bdate_range("2020-10-01", "2021-04-30")]                 # straddles the train/valid split, so the read-out has tables to look at
        bars, _ = simulate_sessions(days, seed=5)
        df = C.build({s: bars[s] for s in ("NIFTY", "BANKNIFTY")}, ["NIFTY", "BANKNIFTY"], "index", vix=bars["INDIAVIX"]["close"], say=lambda *_: None)
        C._write(Path(out), df, {"stop_atr": C.STOP_ATR}, {"path": "synthetic", "use": "synthetic"})
    monkeypatch.setattr(C, "run_dataset", fake_run)
    a = _args("scout", "--dataset", str(tmp_path / "ds"), "--out", str(tmp_path / "run"), "--to", "2022-12-31", "--report", "--journal", str(jp))
    a.fn(cfg, a)
    j = J.ScoutJournal(jp)
    cmds = [e["payload"]["command"] for e in j.entries("run")]
    assert cmds == ["scout", "scout-report"] and j.trials()["report_looks"] > 0


def test_the_lab_counts_earlier_cells_only_from_a_verified_journal_and_says_when_it_cannot(tmp_path, monkeypatch, capsys):
    import sys as _sys
    from quantdesk.intraday import scout_lab as SL
    seen = {}
    monkeypatch.setattr(SL, "run_dataset_lab", lambda *a, **k: seen.update(prior=k.get("prior_cells")) or {})
    cfg = type("Cfg", (), {"runtime_dir": tmp_path / "rt"})()

    def lab(*extra):
        a = _args("scout-lab", "--dataset", str(tmp_path / "ds"), "--out", str(tmp_path / "o"), "--to", "2022-12-31", *extra)
        a.fn(cfg, a)
    jp = tmp_path / "j.jsonl"
    j = J.ScoutJournal(jp)
    j.add("run", "r1", {"rows": 1, "trials": {"cells": 140, "rules_tried": 0, "nulls": 0}})
    j.add("note", "n")
    monkeypatch.setattr(J, "record_lab", lambda *a, **k: {"seq": 9})
    lab("--journal", str(jp))
    assert seen["prior"] == 140                                                            # a verified journal supplies the earlier cells
    lab("--journal", "none")
    assert seen["prior"] == 0 and "THIS RUN ONLY" in capsys.readouterr().out               # and when there is none, it says so
    lines = jp.read_text().splitlines()
    jp.write_text(lines[0].replace("140", "1", 1) + "\n" + lines[1] + "\n")                # a broken chain is refused, not trusted
    with pytest.raises(SystemExit, match="chain is broken"):
        lab("--journal", str(jp))


def test_a_torn_line_is_reported_by_verify_and_summary_instead_of_raising(tmp_path):
    j = J.ScoutJournal(tmp_path / "j.jsonl")
    j.add("note", "a")
    with open(tmp_path / "j.jsonl", "a") as f:
        f.write('{"seq": 2, "kind": "no')                                                                                  # a write cut off half way
    assert any("JSON" in p for p in j.verify())
    text = j.summary()
    assert "CHAIN BROKEN" in text.splitlines()[2] and "cannot be computed" in text
    r = subprocess.run([sys.executable, "-m", "quantdesk", "intraday", "scout-log", "verify", "--journal", str(tmp_path / "j.jsonl")], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 1 and "Traceback" not in r.stderr and "JSON" in r.stdout
