"""The headline archive (quantdesk/newslink/archive.py, docs/NEWS_ENGINE.md L0): every headline the news job reads is kept, a day's file only grows, it is replaced
only through a confirmed superset (never deleted first), a bad artifact cannot write outside its run's window, and only this repository's dispatched digest runs
can feed it."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
import yaml

from quantdesk.newslink import archive as AR

ASOF = "2026-11-15T05:10:00Z"


def row(i, ts="2026-11-15T05:00:00Z", **k):
    return {"id": f"{i:012x}", "ts": ts, "title": f"Headline {i}", "source": "X", "link": f"https://x.test/{i}", "impact": "low", **k}


class FakeStore:
    """A release in memory, with GhRelease's interface. Failures can be injected at each step."""

    def __init__(self, files=None, missing=False, fail=None, wrong_size=False):
        self.files = dict(files or {})                       # name -> bytes
        self.ids = {n: i + 1 for i, n in enumerate(self.files)}
        self.missing, self.fail, self.wrong_size = missing, set(fail or ()), wrong_size
        self.log, self.next_id = [], 100

    def _maybe(self, step):
        if step in self.fail:
            raise subprocess.CalledProcessError(1, f"gh {step}")

    def assets(self):
        self._maybe("list")
        if self.missing:
            return None
        return {n: {"id": self.ids[n], "size": len(b) + (1 if self.wrong_size else 0)} for n, b in self.files.items()}

    def ensure(self):
        self.missing = False
        self.log.append("create")

    def download(self, name, dest):
        self._maybe("download")
        if name in self.files:
            (Path(dest) / name).write_bytes(self.files[name])

    def upload(self, path):
        self._maybe("upload")
        self.next_id += 1
        self.files[path.name], self.ids[path.name] = path.read_bytes(), self.next_id
        self.log.append(("upload", path.name))

    def delete(self, asset_id):
        self._maybe("delete")
        name = next(n for n, i in self.ids.items() if i == asset_id)
        del self.files[name], self.ids[name]
        self.log.append(("delete", name))

    def rename(self, asset_id, name):
        self._maybe("rename")
        old = next(n for n, i in self.ids.items() if i == asset_id)
        self.files[name], self.ids[name] = self.files.pop(old), self.ids.pop(old)
        self.log.append(("rename", old, name))


DAY = "news_2026-11-15.jsonl.gz"


def day_rows(store, name=DAY):
    return AR.loads(store.files[name])


def run(store, rows, tmp_path, seen=ASOF, token="t1", **k):
    return AR.archive([(rows, seen)], lambda tag: store, tmp_path / token, token, **k)


def test_rows_go_to_the_day_in_india_and_the_month_release():
    assert AR.day_of("2026-11-15T20:00:00Z").isoformat() == "2026-11-16"
    assert AR.day_of("2026-11-15T18:29:00Z").isoformat() == "2026-11-15"
    d = AR.day_of("2026-11-30T19:00:00Z")
    assert AR.tag_for(d) == "news-archive-2026-12" and AR.asset_for(d) == "news_2026-12-01.jsonl.gz"


def test_a_day_only_grows_the_first_sighting_wins_and_the_bytes_are_fixed():
    a = AR.merge([], [row(2, "2026-11-15T06:00:00Z"), row(1)], "s1")
    b = AR.merge(a, [{**row(1), "title": "changed"}, row(3, "2026-11-15T07:00:00Z")], "s2")
    assert [r["id"] for r in b] == [f"{i:012x}" for i in (1, 2, 3)] and b[0]["title"] == "Headline 1" and b[0]["first_seen"] == "s1"
    assert AR.loads(AR.dumps(b)) == b and AR.dumps(b) == AR.dumps(list(b))


def test_every_kept_field_is_checked_and_a_bad_field_is_dropped_not_the_row():
    assert AR.clean(row(1)) is not None
    for bad in (None, "x", {**row(1), "id": "NOT-HEX"}, {**row(1), "ts": "yesterday"}, {**row(1), "title": ""}, {**row(1), "title": "x" * 221}):
        assert AR.clean(bad) is None
    r = AR.clean({**row(1), "link": "http://evil.test/x", "source": "s" * 41, "tone": float("nan"), "novelty": 3, "symbols": ["ok", "<script>"],
                  "summary": "article text", "recap": "yes"})
    assert set(r) == {"id", "ts", "title", "impact"}
    r = AR.clean({**row(1), "tone": -0.4, "novelty": 0.8, "symbols": ["NIFTY", "M&M"], "recap": False, "event": "currency", "tone_from": "words"})
    assert r["symbols"] == ["NIFTY", "M&M"] and r["tone"] == -0.4 and r["recap"] is False


def test_a_runs_rows_must_lie_in_that_runs_window_but_the_backfill_is_not_windowed(tmp_path):
    st = FakeStore(missing=True)
    old, future = row(7, "2026-10-01T05:00:00Z"), row(8, "2026-11-15T07:00:00Z")
    done = run(st, [row(1), old, future], tmp_path)
    assert done == {"2026-11-15": (0, 1)} and "news_2026-10-01.jsonl.gz" not in st.files
    done = AR.archive([([old], "journal-backfill")], lambda tag: st, tmp_path / "b", "t2", limit=None, windowed=False)
    assert done == {"2026-10-01": (0, 1)}


def test_the_first_run_creates_the_release_later_runs_merge_and_nothing_new_uploads_nothing(tmp_path):
    st = FakeStore(missing=True)
    assert run(st, [row(1), row(2)], tmp_path, token="a") == {"2026-11-15": (0, 2)} and "create" in st.log
    assert run(st, [row(2), row(3)], tmp_path, token="b") == {"2026-11-15": (2, 3)} and len(day_rows(st)) == 3
    before = list(st.log)
    assert run(st, [row(1), row(3)], tmp_path, token="c") == {"2026-11-15": (3, 3)} and st.log == before
    assert set(st.files) == {DAY}                                                   # no temporaries left behind


def test_the_old_file_is_deleted_only_after_its_superset_is_confirmed_uploaded(tmp_path):
    st = FakeStore({DAY: AR.dumps(AR.merge([], [row(i) for i in range(1, 300)], "s0"))})
    run(st, [row(999)], tmp_path)
    steps = [e[0] for e in st.log if isinstance(e, tuple)]
    assert steps == ["upload", "delete", "rename"] and len(day_rows(st)) == 300


@pytest.mark.parametrize("step", ["upload", "list_after"])
def test_a_failed_or_unconfirmed_upload_leaves_the_old_file_untouched(tmp_path, step):
    big = AR.dumps(AR.merge([], [row(i) for i in range(1, 300)], "s0"))
    st = FakeStore({DAY: big}, fail={"upload"} if step == "upload" else ())
    if step == "list_after":
        orig = st.upload

        def upload_then_wrong_size(path):
            orig(path)
            st.wrong_size = True
        st.upload = upload_then_wrong_size
    with pytest.raises((subprocess.CalledProcessError, RuntimeError)):
        run(st, [row(999)], tmp_path)
    assert st.files[DAY] == big and not any(isinstance(e, tuple) and e[0] == "delete" for e in st.log)


def test_a_run_that_stops_between_delete_and_rename_is_finished_by_the_next_run(tmp_path):
    st = FakeStore({DAY: AR.dumps(AR.merge([], [row(1), row(2)], "s0"))}, fail={"rename"})
    with pytest.raises(subprocess.CalledProcessError):
        run(st, [row(3)], tmp_path, token="a")
    assert DAY not in st.files and len(AR.loads(st.files[f"{DAY}.tmp-a"])) == 3              # the data is in the temporary, not lost
    st.fail = set()
    assert run(st, [row(4)], tmp_path, token="b") == {"2026-11-15": (3, 4)}
    assert set(st.files) == {DAY} and len(day_rows(st)) == 4                              # recovered; the old temporary removed only after the confirmed file


def test_a_temporary_left_beside_the_days_file_is_merged_and_only_then_removed(tmp_path):
    # run 2 confirmed its superset temporary but stopped before deleting the old file: both are listed; story 2 is only in the temporary
    old = AR.dumps(AR.merge([], [row(1)], "s1"))
    tmp = AR.dumps(AR.merge([], [row(1), row(2)], "s2"))
    st = FakeStore({DAY: old, f"{DAY}.tmp-r2": tmp})
    assert run(st, [row(3)], tmp_path, token="r3") == {"2026-11-15": (2, 3)}
    assert [r["id"] for r in day_rows(st)] == [f"{i:012x}" for i in (1, 2, 3)] and set(st.files) == {DAY}


def test_a_leftover_is_kept_if_any_of_its_rows_is_missing_from_the_confirmed_file(tmp_path):
    st = FakeStore()
    work = tmp_path / "w"
    work.mkdir()
    st.files[f"{DAY}.tmp-old"], st.ids[f"{DAY}.tmp-old"] = b"held", 50
    AR._replace(st, work, DAY, AR.dumps([AR.clean(row(1)) | {"first_seen": "s"}]), None, {f"{DAY}.tmp-old": {"zzz"}}, {f"{1:012x}"}, "t")
    assert f"{DAY}.tmp-old" in st.files and DAY in st.files                                # its id is not in the confirmed file: never deleted


def test_a_listed_file_that_cannot_be_downloaded_or_a_failed_listing_writes_nothing(tmp_path):
    st = FakeStore({DAY: AR.dumps([AR.clean(row(1)) | {"first_seen": "s0"}])}, fail={"download"})
    with pytest.raises(subprocess.CalledProcessError):
        run(st, [row(2)], tmp_path)
    st2 = FakeStore({DAY: b"x"}, fail={"list"})
    with pytest.raises(subprocess.CalledProcessError):
        run(st2, [row(2)], tmp_path)
    assert not any(isinstance(e, tuple) for e in st.log + st2.log)


def test_one_run_is_bounded_but_the_one_time_backfill_is_not(tmp_path):
    rows = [row(i, f"2026-10-{15 + i % 10:02d}T05:00:00Z") for i in range(1, AR.MAX_ROWS + 50)]
    stores = {}
    done = AR.archive([(rows, "journal-backfill")], lambda t: stores.setdefault(t, FakeStore(missing=True)), tmp_path / "a", "x", windowed=False)
    assert sum(b for _a, b in done.values()) == AR.MAX_ROWS
    stores = {}
    done = AR.archive([(rows, "journal-backfill")], lambda t: stores.setdefault(t, FakeStore(missing=True)), tmp_path / "b", "y", limit=None, windowed=False)
    assert sum(b for _a, b in done.values()) == len(rows)


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
    assert AR.clean(rows[0]) == rows[0]


def test_the_news_command_writes_every_row_beyond_the_digest_cap_and_never_sends_them(cfg, tmp_path, monkeypatch):
    from quantdesk.newslink import cli as C
    from quantdesk.premarket import newsdigest as ND
    many = [row(i) for i in range(1, 200)]
    digest = {"v": 1, "asof": ASOF, "n": 80, "sources": {"A": "ok 200"}, "items": many[:80], "events": [], "_archive": many}
    monkeypatch.setattr(ND, "fetch_digest", lambda cfg, now=None, **k: dict(digest))

    class A:
        send = archive = backfill_journal = push = now = None
        out = str(tmp_path)
    C.cmd_news(cfg, A)
    sent, kept = json.loads((tmp_path / "news.json").read_text()), json.loads((tmp_path / "archive.json").read_text())
    assert "_archive" not in sent and len(sent["items"]) == 80 and len(kept["items"]) == 199 and kept["asof"] == ASOF


def test_the_archive_step_merges_several_runs_and_refuses_other_shapes(cfg, tmp_path, monkeypatch):
    from quantdesk.newslink import cli as C
    stores = {}
    monkeypatch.setattr(AR, "GhRelease", lambda tag, repo: stores.setdefault(tag, FakeStore(missing=True)))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    p1.write_text(json.dumps({"v": 1, "asof": ASOF, "items": [row(1), row(2)]}))
    p2.write_text(json.dumps({"v": 1, "asof": "2026-11-15T05:00:00Z", "items": [row(2), row(3, "2026-11-15T04:50:00Z")]}))

    class A:
        send = push = now = backfill_journal = None
        archive = [str(p1), str(p2)]
        out = str(tmp_path)
    C.cmd_news(cfg, A)
    assert len(day_rows(stores["news-archive-2026-11"])) == 3
    p1.write_text(json.dumps({"items": "not a list"}))
    with pytest.raises(SystemExit, match="not an archive rows file"):
        C.cmd_news(cfg, A)
    monkeypatch.delenv("GITHUB_REPOSITORY")
    with pytest.raises(SystemExit, match="GITHUB_REPOSITORY"):
        C.cmd_news(cfg, A)


def test_the_digest_stays_read_only_and_only_this_repos_dispatched_digest_feeds_the_archive():
    news = yaml.safe_load(Path(".github/workflows/news.yml").read_text())
    assert news["permissions"] == {"contents": "read"} and list(news["jobs"]) == ["digest"]
    up = [s for s in news["jobs"]["digest"]["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert len(up) == 1 and up[0]["with"]["path"] == "runtime/news/archive.json" and up[0]["with"]["retention-days"] == 1 and up[0]["continue-on-error"] is True
    raw = Path(".github/workflows/news-archive.yml").read_text()
    wf = yaml.safe_load(raw)
    assert wf["permissions"] == {"contents": "write", "actions": "read"} and set(wf[True]) == {"workflow_run", "workflow_dispatch"}
    assert wf[True]["workflow_run"] == {"workflows": ["News digest"], "types": ["completed"]}
    cond = " ".join(wf["jobs"]["archive"]["if"].split())
    for must in ("conclusion == 'success'", "head_branch == 'main'", "head_repository.full_name == github.repository",
                 "workflow_run.event == 'workflow_dispatch'", "workflow_run.path == '.github/workflows/news.yml'", "github.ref == 'refs/heads/main'"):
        assert must in cond
    assert "secrets." not in raw and "LIVE_" not in raw and "place_order" not in raw and "git push" not in raw and "--clobber" not in raw
    assert "|| echo" not in raw                                                            # a failed archive is red, never hidden
    for step in wf["jobs"]["archive"]["steps"]:
        if str(step.get("uses", "")).startswith("actions/checkout"):
            assert step["with"]["persist-credentials"] is False
        if "GH_TOKEN" in (step.get("env") or {}):
            assert "--archive" in step["run"] or "--backfill-journal" in step["run"]


def test_the_archive_module_never_clobbers_holds_no_secret_and_places_nothing():
    src = Path(AR.__file__).read_text()
    for bad in ("os.environ", "place_order", "LIVE_INGEST_TOKEN", "requests.post", "urlopen"):
        assert bad not in src
    up = [line for line in src.splitlines() if '"release", "upload"' in line]
    assert len(up) == 1 and "--clobber" not in up[0]                                       # an upload never clobbers (download's --clobber is the local copy)


def test_the_gh_release_calls_are_checked_and_a_missing_release_reads_as_none():
    calls = []

    class R:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    def fake(cmd, check=True, capture_output=True, text=True):
        calls.append(cmd)
        if cmd[1:3] == ["api", "repos/o/r/releases/tags/news-archive-2026-11"]:
            return R(1, "", "HTTP 404: Not Found")
        return R(0)
    g = AR.GhRelease("news-archive-2026-11", "o/r", run=fake)
    assert g.assets() is None
    g.upload(Path("/tmp/x.tmp-1"))
    assert "--clobber" not in calls[-1]
    g.delete(5)
    g.rename(6, "news_2026-11-15.jsonl.gz")
    assert calls[-2] == ["gh", "api", "-X", "DELETE", "repos/o/r/releases/assets/5"] and calls[-1][-1] == "name=news_2026-11-15.jsonl.gz"

    def broken(cmd, check=True, capture_output=True, text=True):
        return R(1, "", "HTTP 500")
    with pytest.raises(subprocess.CalledProcessError):
        AR.GhRelease("news-archive-2026-11", "o/r", run=broken).assets()
