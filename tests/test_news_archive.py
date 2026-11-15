"""The headline archive (quantdesk/newslink/archive.py, docs/NEWS_ENGINE.md L0): every headline the news job reads is kept, a day's file only grows, and a failed
read of the release never overwrites a day."""
from __future__ import annotations

import gzip
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
import yaml

from quantdesk.newslink import archive as AR


def row(i, ts="2026-11-15T05:00:00Z", title=None):
    return {"id": f"{i:012x}", "ts": ts, "title": title or f"Headline {i}", "source": "X", "link": f"https://x.test/{i}", "impact": "low"}


class FakeStore:
    """A release in memory: assets by name. `missing` = the release does not exist yet; `broken_download` = listed but the download returns nothing."""

    def __init__(self, files=None, missing=False, broken_download=False, broken_list=False):
        self.files, self.missing, self.broken_download, self.broken_list = dict(files or {}), missing, broken_download, broken_list
        self.pushed, self.created = [], False

    def assets(self, strict=False):
        if self.broken_list or self.missing:
            if strict:
                raise subprocess.CalledProcessError(1, "gh release view")
            return []
        return list(self.files)

    def ensure(self):
        if self.broken_list:
            return
        self.missing, self.created = False, True

    def pull(self, dest, names):
        got = []
        for n in names:
            if n in self.files and not self.broken_download:
                (Path(dest) / n).write_bytes(self.files[n])
                got.append(n)
        return got

    def push(self, src, names, clobber=True):
        for n in names:
            self.files[n] = (Path(src) / n).read_bytes()
            self.pushed.append(n)


def stores():
    made = {}
    return made, (lambda tag: made.setdefault(tag, FakeStore(missing=True)))


def test_rows_go_to_the_day_in_india_and_the_month_release():
    assert AR.day_of("2026-11-15T20:00:00Z").isoformat() == "2026-11-16"          # 01:30 IST next day
    assert AR.day_of("2026-11-15T18:29:00Z").isoformat() == "2026-11-15"
    d = AR.day_of("2026-11-30T19:00:00Z")
    assert AR.tag_for(d) == "news-archive-2026-12" and AR.asset_for(d) == "news_2026-12-01.jsonl.gz"


def test_a_day_only_grows_the_first_sighting_wins_and_the_order_is_fixed():
    a = AR.merge([], [row(2, "2026-11-15T06:00:00Z"), row(1)], "2026-11-15T06:10:00Z")
    assert [r["id"] for r in a] == [f"{1:012x}", f"{2:012x}"] and all(r["first_seen"] == "2026-11-15T06:10:00Z" for r in a)
    b = AR.merge(a, [{**row(1), "title": "changed"}, row(3, "2026-11-15T07:00:00Z")], "2026-11-15T07:10:00Z")
    assert len(b) == 3 and b[0]["title"] == "Headline 1" and b[0]["first_seen"] == "2026-11-15T06:10:00Z"
    assert AR.dumps(b) == AR.dumps(AR.merge(a, [row(3, "2026-11-15T07:00:00Z")], "2026-11-15T07:10:00Z"))  # deterministic bytes (gzip mtime 0)
    assert AR.loads(AR.dumps(b)) == b


def test_rows_that_are_not_digest_rows_are_dropped():
    assert AR.clean(row(1)) is not None
    for bad in (None, "x", {**row(1), "id": "NOT-HEX"}, {**row(1), "ts": "yesterday"}, {**row(1), "title": ""}, {**row(1), "title": "x" * 401}):
        assert AR.clean(bad) is None
    assert "summary" not in AR.clean({**row(1), "summary": "article text"})        # only the archived fields


def test_the_first_run_creates_the_release_and_later_runs_merge(tmp_path):
    made, store_for = stores()
    done = AR.archive([row(1), row(2)], "2026-11-15T05:10:00Z", store_for, tmp_path / "w")
    st = made["news-archive-2026-11"]
    assert st.created and done == {"2026-11-15": (0, 2)} and st.pushed == ["news_2026-11-15.jsonl.gz"]
    done = AR.archive([row(2), row(3)], "2026-11-15T05:20:00Z", store_for, tmp_path / "w2")
    assert done == {"2026-11-15": (2, 3)} and len(AR.loads(st.files["news_2026-11-15.jsonl.gz"])) == 3
    done = AR.archive([row(1), row(3)], "2026-11-15T05:30:00Z", store_for, tmp_path / "w3")
    assert done == {"2026-11-15": (3, 3)} and st.pushed.count("news_2026-11-15.jsonl.gz") == 2       # nothing new: no upload


def test_a_listed_file_that_cannot_be_downloaded_is_never_overwritten(tmp_path):
    big = AR.dumps(AR.merge([], [row(i) for i in range(1, 300)], "2026-11-15T04:00:00Z"))
    st = FakeStore({"news_2026-11-15.jsonl.gz": big}, broken_download=True)
    with pytest.raises(RuntimeError, match="not overwriting"):
        AR.archive([row(999)], "2026-11-15T05:10:00Z", lambda tag: st, tmp_path / "w")
    assert st.files["news_2026-11-15.jsonl.gz"] == big and st.pushed == []


def test_a_release_that_cannot_be_listed_stops_the_archive_without_writing(tmp_path):
    st = FakeStore({"news_2026-11-15.jsonl.gz": b"x"}, broken_list=True)
    with pytest.raises(subprocess.CalledProcessError):
        AR.archive([row(1)], "2026-11-15T05:10:00Z", lambda tag: st, tmp_path / "w")
    assert st.pushed == []


def test_the_journal_backfill_reads_the_journal_read_only_in_the_archive_shape(tmp_path):
    db = tmp_path / "j.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE news (id, ts, seen_at, source, sources, title, link, summary, sentiment, impact, about, nlp)")
    con.execute("INSERT INTO news VALUES ('a', '2026-10-15 09:00:00+05:30', '', 'Mint', '[]', '  Rupee   falls  ', 'https://m.test/1', 'body', -0.4, 'high', '{}', ?)",
                (json.dumps({"event": "currency", "novelty": 0.8}),))
    con.commit()
    con.close()
    rows = AR.from_journal(str(db))
    assert rows == [{"id": rows[0]["id"], "ts": "2026-10-15T03:30:00Z", "title": "Rupee falls", "source": "Mint", "link": "https://m.test/1", "from": "journal",
                     "tone": -0.4, "impact": "high", "event": "currency", "novelty": 0.8}]
    assert AR.clean(rows[0]) is not None and "summary" not in rows[0]


def test_the_news_command_writes_every_row_beyond_the_digest_cap_and_never_sends_them(cfg, tmp_path, monkeypatch):
    from quantdesk.newslink import cli as C
    from quantdesk.premarket import newsdigest as ND
    many = [row(i) for i in range(1, 200)]
    digest = {"v": 1, "asof": "2026-11-15T05:10:00Z", "n": 80, "sources": {"A": "ok 200"}, "items": many[:80], "events": [], "_archive": many}
    monkeypatch.setattr(ND, "fetch_digest", lambda cfg, now=None, **k: dict(digest))

    class A:
        send = archive = backfill_journal = push = now = None
        out = str(tmp_path)
    C.cmd_news(cfg, A)
    sent = json.loads((tmp_path / "news.json").read_text())
    kept = json.loads((tmp_path / "archive.json").read_text())
    assert "_archive" not in sent and len(sent["items"]) == 80 and len(kept["items"]) == 199 and kept["asof"] == digest["asof"]


def test_the_archive_step_reads_only_our_own_file_and_refuses_another_shape(cfg, tmp_path, monkeypatch):
    from quantdesk.data import warehouse as W
    from quantdesk.newslink import cli as C
    made = {}
    monkeypatch.setattr(W, "ReleaseStore", lambda tag, **k: made.setdefault(tag, FakeStore(missing=True)))
    p = tmp_path / "archive.json"
    p.write_text(json.dumps({"v": 1, "asof": "2026-11-15T05:10:00Z", "items": [row(1), row(2)]}))

    class A:
        send = push = now = backfill_journal = None
        archive = str(p)
        out = str(tmp_path)
    C.cmd_news(cfg, A)
    assert len(AR.loads(made["news-archive-2026-11"].files["news_2026-11-15.jsonl.gz"])) == 2
    p.write_text(json.dumps({"items": "not a list"}))
    with pytest.raises(SystemExit, match="not an archive rows file"):
        C.cmd_news(cfg, A)


def test_the_digest_stays_read_only_and_only_the_archive_workflow_writes_without_the_relay_key():
    news = yaml.safe_load(Path(".github/workflows/news.yml").read_text())
    assert news["permissions"] == {"contents": "read"} and list(news["jobs"]) == ["digest"]
    up = [s for s in news["jobs"]["digest"]["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert len(up) == 1 and up[0]["with"]["path"] == "runtime/news/archive.json" and up[0]["with"]["retention-days"] == 1
    raw = Path(".github/workflows/news-archive.yml").read_text()
    wf = yaml.safe_load(raw)
    assert wf["permissions"] == {"contents": "write", "actions": "read"} and set(wf[True]) == {"workflow_run", "workflow_dispatch"}
    assert wf[True]["workflow_run"] == {"workflows": ["News digest"], "types": ["completed"]}
    cond = " ".join(wf["jobs"]["archive"]["if"].split())
    assert "conclusion == 'success'" in cond and "head_branch == 'main'" in cond                     # only a successful digest run on main
    assert "secrets." not in raw and "LIVE_" not in raw and "place_order" not in raw and "git push" not in raw
    for step in wf["jobs"]["archive"]["steps"]:
        if str(step.get("uses", "")).startswith("actions/checkout"):
            assert step["with"]["persist-credentials"] is False
        if "GH_TOKEN" in (step.get("env") or {}):
            assert "--archive" in step["run"] or "--backfill-journal" in step["run"]


def test_the_archive_module_holds_no_secret_and_places_nothing():
    src = Path(AR.__file__).read_text()
    for bad in ("os.environ", "place_order", "LIVE_INGEST_TOKEN", "requests.post", "urlopen"):
        assert bad not in src


def test_one_run_is_bounded_but_the_one_time_backfill_is_not(tmp_path):
    rows = [row(i, f"2026-10-{15 + i % 10:02d}T05:00:00Z") for i in range(1, AR.MAX_ROWS + 50)]
    made, store_for = stores()
    done = AR.archive(rows, "run", store_for, tmp_path / "a")
    assert sum(b for _a, b in done.values()) == AR.MAX_ROWS
    made, store_for = stores()
    done = AR.archive(rows, "journal-backfill", store_for, tmp_path / "b", limit=None)
    assert sum(b for _a, b in done.values()) == len(rows)
