"""C-02: archive, verify, then prune the journal (quantdesk/journal/retention.py), and the push-size guard."""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from quantdesk.journal import retention as R
from quantdesk.journal.journal import Journal

ROOT = Path(__file__).resolve().parent.parent
AS_OF = dt.date(2026, 10, 16)
PROTECTED_TABLES = ("trades", "fills", "decisions", "events", "equity", "checks", "state")


def _day(n: int) -> str:
    return (AS_OF - dt.timedelta(days=n)).isoformat()


def make_runtime(tmp_path: Path, days: int = 60, studies: int = 6) -> Path:
    """A synthetic runtime: `days` days of thoughts and news, every protected table filled, `studies` plan studies."""
    rt = tmp_path / "rt"
    j = Journal(rt / "intraday" / "journal.db")
    for n in range(days):
        d = _day(n)
        for k in range(3):
            j.db.execute("INSERT INTO thoughts (ts, symbol, bias, score, narrative, evidence) VALUES (?,?,?,?,?,?)",
                         (f"{d} 10:{k:02d}:04.123456+05:30", "NIFTY", "up", 0.5 + k, f"thought {d} {k} " + "x" * 200, "[]"))
            j.db.execute("INSERT INTO news (id, ts, seen_at, source, sources, title, summary, sentiment, about, nlp) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (f"n{d}-{k}", f"{d} 0{k}:10:00+05:30", f"{d} 09:00:00+05:30", "rss", "[]", f"headline {d} {k}",
                          "s" * 120, 0.1 * k, "{}", "{}"))
        j.db.execute("INSERT INTO decisions (ts, strategy, symbol, action, detail) VALUES (?,?,?,?,?)",
                     (f"{d} 11:00:00+05:30", "s", "NIFTY", "enter", "why"))
        j.db.execute("INSERT INTO equity (ts, equity, cash) VALUES (?,?,?)", (f"{d} 15:30:00+05:30", 20000 + n, 100.0))
        j.db.execute("INSERT INTO events (ts, level, category, message, data) VALUES (?,?,?,?,?)",
                     (f"{d} 09:15:00+05:30", "INFO", "x", "m", "{}"))
        j.db.execute("INSERT INTO fills (ts, trade_id, symbol, qty, price, fees, breakdown) VALUES (?,?,?,?,?,?,?)",
                     (f"{d} 11:01:00+05:30", f"t{n}", "NIFTY", 75, 100.0, 1.0, "{}"))
        j.db.execute("INSERT INTO checks (ts, routine, name, status, detail) VALUES (?,?,?,?,?)",
                     (f"{d} 08:00:00+05:30", "pre", "c", "OK", ""))
        j.db.execute("INSERT INTO trades (id, strategy, symbol, opened_at, status, pnl) VALUES (?,?,?,?,?,?)",
                     (f"t{n}", "s", "NIFTY", f"{d} 11:01:00+05:30", "closed", 10.0 - n))
    j.db.execute("INSERT INTO state (key, value) VALUES ('intraday_account', '{}')")
    j.commit()
    j.close()
    sdir = rt / "intraday" / "autolearn" / "plan" / "studies"
    for i in range(studies):                                   # oldest first: 2026-09-1x-aaaaaN ... newest last
        sid = f"2026-09-{10 + i:02d}-{i:06x}"
        d = sdir / sid
        d.mkdir(parents=True)
        (d / "report.json").write_text(json.dumps({"study": sid, "at": f"2026-09-{10 + i:02d} 20:00:00+05:30"}))
        (d / "report.md").write_text(f"# {sid}\n")
        (d / "scenario_outcomes.parquet").write_bytes(os.urandom(5000) + bytes([i]))
    plan = rt / "intraday" / "autolearn" / "plan"
    (plan / "latest.json").write_text(json.dumps({"study": f"2026-09-{10 + studies - 1:02d}-{studies - 1:06x}"}))
    (plan / "registry").mkdir()
    (plan / "registry" / "state.json").write_text(json.dumps({"champion": None, "challengers": [], "rollback_target": None}))
    (plan / "trials.jsonl").write_text("")
    return rt


def table_hashes(rt: Path) -> dict:
    db = sqlite3.connect(f"file:{rt / 'intraday' / 'journal.db'}?mode=ro", uri=True)
    try:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        out = {}
        for n in names:
            if n == "state":                                         # keyed by key, not id
                out[n] = hashlib.sha256(repr(db.execute("SELECT * FROM state ORDER BY key").fetchall()).encode()).hexdigest()
            elif n == "equity":                                      # keyed by ts
                out[n] = hashlib.sha256(repr(db.execute("SELECT * FROM equity ORDER BY ts").fetchall()).encode()).hexdigest()
            elif n in ("trades",):
                out[n] = hashlib.sha256(repr(db.execute("SELECT * FROM trades ORDER BY id").fetchall()).encode()).hexdigest()
            else:
                out[n] = R.table_digest(db, n)
        return out
    finally:
        db.close()


def study_files(rt: Path) -> dict:
    sdir = rt / "intraday" / "autolearn" / "plan" / "studies"
    return {p.relative_to(sdir).as_posix(): R.sha256_file(p) for p in sorted(sdir.rglob("*")) if p.is_file()}


def counts(rt: Path) -> dict:
    db = sqlite3.connect(f"file:{rt / 'intraday' / 'journal.db'}?mode=ro", uri=True)
    try:
        return R._counts(db)
    finally:
        db.close()


def run(rt, out, **kw):
    kw.setdefault("as_of", AS_OF)
    kw.setdefault("say", lambda *_: None)
    return R.archive(rt, out, **{"keep_days": 30, "keep_studies": 3, **kw})


# ---- the round trip ---------------------------------------------------------------------------------------------------
def test_archive_verify_prune_round_trip(tmp_path):
    rt, out = make_runtime(tmp_path), tmp_path / "out"
    before, studies_before = table_hashes(rt), study_files(rt)
    n_before = counts(rt)
    man = run(rt, out)

    cutoff = AS_OF - dt.timedelta(days=30)
    assert man["cutoff"] == cutoff.isoformat() and man["verified"] and man["pruned"]
    # 60 days x 3 rows; days 0..30 kept (dated >= cutoff), days 31..59 archived
    assert man["tables"]["thoughts"]["rows"] == 29 * 3 and man["tables"]["news"]["rows"] == 29 * 3
    n_after = counts(rt)
    assert n_after["thoughts"] == n_before["thoughts"] - 87 and n_after["news"] == n_before["news"] - 87
    assert man["row_counts_before"] == n_before and man["row_counts_after"] == n_after

    # the archive file: named by date range, hash recorded, matches the manifest and holds the same rows
    arc = out / man["files"]["rows"]["name"]
    assert arc.name == f"journal-archive-{_day(59)}_{_day(31)}.db.gz"
    assert R.sha256_file(arc) == man["files"]["rows"]["sha256"]
    with gzip.open(arc, "rb") as z:
        assert z.read(16) == b"SQLite format 3\x00"
    assert json.loads((out / f"archive-manifest-{AS_OF}.json").read_text())["verified"]

    # nothing in the protected tables moved, and no remaining thought/news row is older than the cutoff
    after = table_hashes(rt)
    for t in PROTECTED_TABLES:
        assert after[t] == before[t], t
    db = sqlite3.connect(rt / "intraday" / "journal.db")
    assert db.execute("SELECT MIN(substr(ts,1,10)) FROM thoughts").fetchone()[0] == cutoff.isoformat()
    assert db.execute("SELECT MIN(substr(ts,1,10)) FROM news").fetchone()[0] == cutoff.isoformat()
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.close()

    # studies: the oldest 3 of 6 are archived, the newest 3 stay; per-file hashes recorded in the manifest
    left = study_files(rt)
    assert {k.split("/")[0] for k in left} == {s for s in {k.split("/")[0] for k in studies_before}
                                              if s >= "2026-09-13"}
    assert sorted(man["studies"]["removed"]) == sorted({k.split("/")[0] for k in studies_before} - {k.split("/")[0] for k in left})
    for sid, files in man["studies"]["files"].items():
        for rel, meta in files.items():
            assert meta["sha256"] == studies_before[f"{sid}/{rel}"]
    assert R.sha256_file(out / man["files"]["studies"]["name"]) == man["files"]["studies"]["sha256"]
    assert man["size_after"]["journal_db"] < man["size_before"]["journal_db"]

    # restore puts every row and study back, byte for byte, into a fresh journal
    fresh = tmp_path / "fresh"
    shutil_copy_tree(rt, fresh)
    R.restore(out / f"archive-manifest-{AS_OF}.json", fresh, say=lambda *_: None)
    again = table_hashes(fresh)
    assert again["thoughts"] == before["thoughts"] and again["news"] == before["news"]
    for t in PROTECTED_TABLES:
        assert again[t] == before[t]
    assert study_files(fresh) == studies_before
    assert not R.history_archived(fresh / "intraday" / "journal.db")


def shutil_copy_tree(src: Path, dst: Path) -> None:
    import shutil
    shutil.copytree(src, dst)


def test_second_run_is_a_no_op(tmp_path):
    rt, out = make_runtime(tmp_path), tmp_path / "out"
    run(rt, out)
    snap = (R.sha256_file(rt / "intraday" / "journal.db"), study_files(rt), sorted(p.name for p in out.iterdir()))
    ledger = (rt / "intraday" / R.LEDGER).read_text()
    man = run(rt, out)
    assert man["note"] == "nothing to archive" and not man["pruned"]
    assert (R.sha256_file(rt / "intraday" / "journal.db"), study_files(rt), sorted(p.name for p in out.iterdir())) == snap
    assert (rt / "intraday" / R.LEDGER).read_text() == ledger


def test_dry_run_changes_nothing_and_projects_the_size(tmp_path):
    rt, out = make_runtime(tmp_path), tmp_path / "out"
    snap = (R.sha256_file(rt / "intraday" / "journal.db"), study_files(rt))
    lines: list[str] = []
    dry = run(rt, out, dry_run=True, say=lines.append)
    assert (R.sha256_file(rt / "intraday" / "journal.db"), study_files(rt)) == snap
    assert not out.exists() and not (rt / "intraday" / R.LEDGER).exists()
    assert dry["tables"]["thoughts"]["rows"] == 87 and dry["dry_run"]
    assert any("nothing was changed" in x for x in lines) and any("MB ->" in x for x in lines)
    real = run(rt, out)
    # the projection was measured on a copy: it is what the real run produced
    assert dry["projected_size_after"]["journal_db"] == real["size_after"]["journal_db"]
    assert dry["projected_size_after"]["studies"] == real["size_after"]["studies"]


# ---- a bad archive stops everything --------------------------------------------------------------------------------------
def test_a_corrupted_row_archive_aborts_before_any_deletion(tmp_path, monkeypatch):
    rt, out = make_runtime(tmp_path), tmp_path / "out"
    snap = (table_hashes(rt), study_files(rt))
    orig = R._write_row_archive

    def lossy(src, tmp_db, where, meta):
        orig(src, tmp_db, where, meta)
        c = sqlite3.connect(tmp_db)
        c.execute("DELETE FROM thoughts WHERE id = (SELECT MIN(id) FROM thoughts)")   # one row never made it
        c.commit()
        c.close()
    monkeypatch.setattr(R, "_write_row_archive", lossy)
    with pytest.raises(R.RetentionError, match="does not match"):
        run(rt, out)
    assert (table_hashes(rt), study_files(rt)) == snap
    assert not (rt / "intraday" / R.LEDGER).exists()
    assert not list(out.glob("archive-manifest-*"))                   # no manifest vouches for a bad archive


def test_a_changed_cell_is_caught_by_the_content_hash(tmp_path, monkeypatch):
    rt, out = make_runtime(tmp_path), tmp_path / "out"
    snap = table_hashes(rt)
    orig = R._write_row_archive

    def tampered(src, tmp_db, where, meta):
        orig(src, tmp_db, where, meta)
        c = sqlite3.connect(tmp_db)
        c.execute("UPDATE news SET title = 'x' WHERE id = (SELECT MIN(id) FROM news)")   # same count, different content
        c.commit()
        c.close()
    monkeypatch.setattr(R, "_write_row_archive", tampered)
    with pytest.raises(R.RetentionError, match="news does not match"):
        run(rt, out)
    assert table_hashes(rt) == snap


def test_a_garbled_gzip_aborts(tmp_path, monkeypatch):
    rt, out = make_runtime(tmp_path), tmp_path / "out"
    snap = (table_hashes(rt), study_files(rt))
    orig = R._gzip_file

    def garble(src, dst):
        orig(src, dst)
        b = bytearray(dst.read_bytes())
        b[len(b) // 2] ^= 0xFF
        dst.write_bytes(bytes(b))
    monkeypatch.setattr(R, "_gzip_file", garble)
    with pytest.raises(R.RetentionError):
        run(rt, out)
    assert (table_hashes(rt), study_files(rt)) == snap


def test_a_corrupted_study_archive_aborts_and_keeps_the_studies(tmp_path, monkeypatch):
    rt, out = make_runtime(tmp_path), tmp_path / "out"
    snap = (table_hashes(rt), study_files(rt))
    orig = R._write_study_archive

    def garble(studies, dst):
        orig(studies, dst)
        b = bytearray(dst.read_bytes())
        b[len(b) // 2] ^= 0xFF
        dst.write_bytes(bytes(b))
    monkeypatch.setattr(R, "_write_study_archive", garble)
    with pytest.raises(R.RetentionError):
        run(rt, out)
    assert (table_hashes(rt), study_files(rt)) == snap                # rows were not deleted either


def test_a_study_that_changes_after_archiving_is_not_deleted(tmp_path, monkeypatch):
    rt, out = make_runtime(tmp_path), tmp_path / "out"
    orig = R.verify_study_archive

    def then_touch(tgz, studies):
        orig(tgz, studies)
        (studies[0].path / "report.md").write_text("edited after the archive was taken")
    monkeypatch.setattr(R, "verify_study_archive", then_touch)
    man = run(rt, out)
    assert len(man["studies"]["skipped_changed_since_archive"]) == 1
    assert (rt / "intraday/autolearn/plan/studies" / man["studies"]["skipped_changed_since_archive"][0]).exists()


# ---- what is never touched --------------------------------------------------------------------------------------------------
def test_protected_studies_survive_even_keep_zero(tmp_path):
    rt, out = make_runtime(tmp_path, studies=6), tmp_path / "out"
    plan = rt / "intraday" / "autolearn" / "plan"
    ids = sorted(p.name for p in (plan / "studies").iterdir())
    champ_study, locked_study, refd_card = ids[0], ids[1], ids[2]
    (plan / "registry" / "state.json").write_text(json.dumps({"champion": "m1", "challengers": ["m2"], "rollback_target": None}))
    (plan / "registry" / "models" / "m1").mkdir(parents=True)
    (plan / "registry" / "models" / "m1" / "card.json").write_text(json.dumps({"config_hash": "abc123"}))
    (plan / "registry" / "models" / "m2").mkdir(parents=True)
    (plan / "registry" / "models" / "m2" / "card.json").write_text(json.dumps({"note": f"trained on {refd_card}"}))
    (plan / "trials.jsonl").write_text(json.dumps({"study": champ_study, "config_hash": "abc123"}) + "\n" +
                                       json.dumps({"study": ids[5], "config_hash": "zzz"}) + "\n")
    (plan / "lock.json").write_text(json.dumps({"generations": [], "from_study": locked_study}))
    (plan / "studies" / "2026-08-01-abcdef").mkdir()                   # no report.json: unfinished, not ours to take
    (plan / "studies" / "2026-08-01-abcdef" / "partial.parquet").write_bytes(b"x")
    man = run(rt, out, keep_studies=0)
    assert sorted(man["studies"]["removed"]) == sorted(ids[3:5])      # ids[5] is latest.json's; ids[0..2] are referenced
    left = {p.name for p in (plan / "studies").iterdir()}
    assert {champ_study, locked_study, refd_card, ids[5], "2026-08-01-abcdef"} <= left
    assert man["studies"]["protected"][champ_study].startswith("study that produced m1")
    assert "lock.json" in man["studies"]["protected"][locked_study]
    assert refd_card in left


def test_unresolvable_champion_means_no_studies_are_pruned(tmp_path):
    rt, out = make_runtime(tmp_path, studies=6), tmp_path / "out"
    plan = rt / "intraday" / "autolearn" / "plan"
    (plan / "registry" / "state.json").write_text(json.dumps({"champion": "m1", "challengers": [], "rollback_target": None}))
    (plan / "registry" / "models" / "m1").mkdir(parents=True)
    (plan / "registry" / "models" / "m1" / "card.json").write_text(json.dumps({"config_hash": "nope"}))
    before = study_files(rt)
    man = run(rt, out)
    assert study_files(rt) == before and man["warnings"]
    assert man["tables"]["thoughts"]["rows"] == 87                    # the rows are still archived


def test_malformed_or_missing_timestamps_are_never_selected(tmp_path):
    rt, out = make_runtime(tmp_path), tmp_path / "out"
    j = Journal(rt / "intraday" / "journal.db")
    j.db.execute("INSERT INTO thoughts (ts, symbol) VALUES (NULL, 'X')")
    j.db.execute("INSERT INTO thoughts (ts, symbol) VALUES ('Tue, 13 Oct', 'X')")
    j.db.execute("INSERT INTO news (id, ts) VALUES ('odd1', NULL)")
    j.db.execute("INSERT INTO news (id, ts) VALUES ('odd2', 'garbage')")
    j.commit()
    j.close()
    man = run(rt, out)
    db = sqlite3.connect(rt / "intraday" / "journal.db")
    assert db.execute("SELECT COUNT(*) FROM thoughts WHERE symbol='X'").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM news WHERE id LIKE 'odd%'").fetchone()[0] == 2
    assert man["tables"]["thoughts"]["rows"] == 87


def test_an_idle_desk_or_wrong_clock_cannot_archive_everything(tmp_path):
    rt, out = make_runtime(tmp_path, days=40), tmp_path / "out"
    man = run(rt, out, as_of=dt.date(2030, 1, 1))                     # a clock years ahead
    assert man["reference_date"] == AS_OF.isoformat()                 # counted back from the newest row instead
    assert counts(rt)["thoughts"] == 31 * 3                            # still keeps 30 days (+ the cutoff day)


# ---- readers of old rows --------------------------------------------------------------------------------------------------
def test_rebuild_refuses_until_the_history_is_restored(tmp_path):
    from quantdesk.intraday import cli
    rt = make_runtime(tmp_path)
    run(rt, tmp_path / "out")
    jp = rt / "intraday" / "journal.db"
    assert R.history_archived(jp) and len(R.archived_thought_days(jp)) == 29
    ns = argparse.Namespace(account=None, rebuild=True, allow_partial_journal=False, bootstrap=False, if_empty=False, top=3)
    from quantdesk.config import DEFAULT_CONFIG, Config
    c = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(rt)}})
    with pytest.raises(SystemExit, match="refused"):
        cli.cmd_learn(c, ns)
    R.restore(tmp_path / "out" / f"archive-manifest-{AS_OF}.json", rt, say=lambda *_: None)
    assert not R.history_archived(jp)                                  # restored: a rebuild sees the whole journal again


def test_paper_gate_still_counts_archived_sessions(tmp_path, capsys):
    from quantdesk.config import DEFAULT_CONFIG, Config
    from quantdesk.intraday import cli
    rt = make_runtime(tmp_path)
    c = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(rt)}})
    ns = argparse.Namespace(strategy="s", since=_day(59), account=None)
    cli.cmd_paper_gate(c, ns)
    full = json.loads(capsys.readouterr().out)["observed_sessions"]
    run(rt, tmp_path / "out")
    cli.cmd_paper_gate(c, ns)
    assert json.loads(capsys.readouterr().out)["observed_sessions"] == full == 60
    ns.since = _day(10)                                                # a window inside what is kept is unchanged
    cli.cmd_paper_gate(c, ns)
    assert json.loads(capsys.readouterr().out)["observed_sessions"] == 11


def test_cli_dry_run_and_floor(tmp_path, capsys):
    from quantdesk import cli as top
    rt = make_runtime(tmp_path)
    top.main(["intraday", "archive", "--root", str(rt), "--out", str(tmp_path / "o"), "--dry-run", "--as-of", AS_OF.isoformat()])
    assert "nothing was changed" in capsys.readouterr().out and not (tmp_path / "o").exists()
    with pytest.raises(SystemExit, match="at least"):
        top.main(["intraday", "archive", "--root", str(rt), "--out", str(tmp_path / "o"), "--keep-days", "3"])


# ---- the push-size guard (shell) ------------------------------------------------------------------------------------------
def _sh(args, cwd, env=None):
    e = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
    e.update(env or {})
    return subprocess.run(["bash", *args], cwd=cwd, env=e, capture_output=True, text=True, timeout=120)


def test_push_guard_refuses_a_file_at_80mb_before_touching_git(tmp_path):
    d = tmp_path / "snap"
    (d / "intraday").mkdir(parents=True)
    with open(d / "intraday" / "journal.db", "wb") as f:
        f.truncate(80 * 1024 * 1024)                                   # sparse
    (d / "README.md").write_text("hi")
    r = _sh([str(ROOT / "deploy" / "push-dir.sh"), str(d), "journal", "msg"], cwd=tmp_path)   # cwd is no repo: git would fail
    assert r.returncode == 1
    assert "::error::" in r.stderr and "intraday/journal.db" in r.stderr and "80 MB" in r.stderr
    assert "not a git repository" not in r.stderr                       # it stopped before any git command


def test_push_guard_lets_a_file_just_under_80mb_through(tmp_path):
    d = tmp_path / "snap"
    d.mkdir()
    with open(d / "journal.db", "wb") as f:
        f.truncate(80 * 1024 * 1024 - 1)
    r = _sh([str(ROOT / "deploy" / "push-dir.sh"), str(d), "journal", "msg"], cwd=tmp_path)
    assert "::error::push-dir" not in r.stderr                         # past the guard (git then fails: not a repo)
    assert "::warning::" in r.stderr                                    # but a 60 MB+ file is flagged


def test_journal_save_stops_with_an_error_annotation_and_a_normal_save_still_pushes(tmp_path):
    bare = tmp_path / "remote.git"
    work = tmp_path / "work"
    for cmd in (["git", "init", "-q", "--bare", str(bare)], ["git", "init", "-q", str(work)],
                ["git", "-C", str(work), "remote", "add", "origin", str(bare)]):
        subprocess.run(cmd, check=True)
    rt = work / "runtime"
    (rt / "intraday").mkdir(parents=True)
    (rt / "intraday" / "journal.db").write_bytes(b"small")
    env = {"QD_RUNTIME": str(rt), "JOURNAL_BRANCH": "journal"}
    ok = _sh([str(ROOT / "deploy" / "journal.sh"), "save", "first"], cwd=work, env=env)
    assert ok.returncode == 0, ok.stderr
    tip = subprocess.run(["git", "-C", str(bare), "rev-parse", "refs/heads/journal"], capture_output=True, text=True)
    assert tip.returncode == 0
    with open(rt / "intraday" / "journal.db", "wb") as f:
        f.truncate(81 * 1024 * 1024)
    bad = _sh([str(ROOT / "deploy" / "journal.sh"), "save", "second"], cwd=work, env=env)
    assert bad.returncode == 1 and "::error::push-dir: intraday/journal.db is 81 MB" in bad.stderr
    tip2 = subprocess.run(["git", "-C", str(bare), "rev-parse", "refs/heads/journal"], capture_output=True, text=True)
    assert tip2.stdout == tip.stdout                                    # the old journal branch is untouched
