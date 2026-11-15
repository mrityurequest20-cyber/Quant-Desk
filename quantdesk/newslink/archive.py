"""The headline archive (docs/NEWS_ENGINE.md, L0): every headline the news job reads is kept, so the desk has a history to learn from and to test against.

Nothing has stored headlines since 6 Nov 2026 (the weekly archive job went with #196; the relay keeps only the newest digest). This module keeps them again: each run's
items (the digest's own cleaned rows, before the digest's 80-item cap) are merged into one file per day, `news_<YYYY-MM-DD>.jsonl.gz` (the day in India), on a
release per month, `news-archive-<YYYY-MM>`. A row is keyed by its digest id (a hash of the link or title); the first time a story is seen wins and keeps its
`first_seen`, so a day's file only ever grows.

Public RSS titles and links and the desk's own tags (tone, impact, novelty, symbols); never article text, never anything private. The step that runs this reads
only our own JSON file and holds only the repository token (news.yml, job `archive`).

Safety: a day's file is replaced only after the release's asset list was read without error and, if the day's file is listed, it was downloaded and parsed. A
failed listing or download stops the archive (the digest is unaffected) rather than overwrite a day with one run's rows.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import re
import subprocess
from pathlib import Path

TAG_PREFIX = "news-archive"
FIELDS = ("id", "ts", "source", "sources", "title", "link", "tone", "tone_from", "impact", "recap", "event", "novelty", "symbols", "from")
MAX_ROWS = 5000                                   # per run, a sanity bound (a day is about 425 distinct stories)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
_ID = re.compile(r"^[0-9a-f]{6,40}$")
TITLE = "Headline archive {month}"
NOTES = ("Every headline the desk's news job read, one gzip JSON-lines file per day (India time); public RSS titles and links and the desk's own tags, never "
         "article text (quantdesk/newslink/archive.py). Not a software release.")


def _ts(s) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def day_of(ts: str) -> dt.date:
    return _ts(ts).astimezone(IST).date()


def tag_for(day: dt.date) -> str:
    return f"{TAG_PREFIX}-{day:%Y-%m}"


def asset_for(day: dt.date) -> str:
    return f"news_{day.isoformat()}.jsonl.gz"


def clean(row) -> dict | None:
    """The archived fields of one digest row, or None for a row that is not one."""
    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not _ID.match(row["id"]) or _ts(row.get("ts")) is None:
        return None
    title = row.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 400:
        return None
    return {k: row[k] for k in FIELDS if k in row}


def merge(existing: list[dict], new: list[dict], seen_at: str) -> list[dict]:
    """Rows by id; a story already archived keeps its row (and first_seen); new stories get first_seen = seen_at. Sorted by (ts, id): deterministic."""
    out = {r["id"]: r for r in existing}
    for r in new:
        if r["id"] not in out:
            out[r["id"]] = {**r, "first_seen": seen_at}
    return sorted(out.values(), key=lambda r: (r["ts"], r["id"]))


def dumps(rows: list[dict]) -> bytes:
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")
    return gzip.compress(body, mtime=0)


def loads(data: bytes) -> list[dict]:
    rows = [json.loads(line) for line in gzip.decompress(data).decode("utf-8").splitlines() if line.strip()]
    if not all(isinstance(r, dict) and isinstance(r.get("id"), str) for r in rows):
        raise ValueError("not an archive file")
    return rows


def _listed(store) -> list[str]:
    """The release's assets, read strictly; a release that does not exist yet is created (then it is empty)."""
    try:
        return store.assets(strict=True)
    except subprocess.CalledProcessError:
        store.ensure()
        return store.assets(strict=True)


def archive(rows: list, seen_at: str, store_for, work: Path, limit: int | None = MAX_ROWS) -> dict[str, tuple[int, int]]:
    """Merge rows into their days' files. store_for(tag) gives a ReleaseStore-like object. `limit` bounds one news run; the one-time backfill passes None.
    Returns {day: (rows before, rows after)}."""
    good = [r for r in (clean(x) for x in (rows if limit is None else rows[:limit])) if r]
    by_day: dict[dt.date, list[dict]] = {}
    for r in good:
        by_day.setdefault(day_of(r["ts"]), []).append(r)
    work.mkdir(parents=True, exist_ok=True)
    done = {}
    for day in sorted(by_day):
        tag, name = tag_for(day), asset_for(day)
        store = store_for(tag)
        existing = []
        if name in _listed(store):
            got = store.pull(work, [name])
            if name not in got or not (work / name).exists():
                raise RuntimeError(f"{name} is listed on {tag} but could not be downloaded: not overwriting it")
            existing = loads((work / name).read_bytes())
        merged = merge(existing, by_day[day], seen_at)
        if len(merged) == len(existing):
            done[day.isoformat()] = (len(existing), len(merged))
            continue                                  # nothing new: no upload
        (work / name).write_bytes(dumps(merged))
        store.push(work, [name], clobber=True)
        done[day.isoformat()] = (len(existing), len(merged))
    return done


def from_journal(db_path: str) -> list[dict]:
    """Rows of the journal's `news` table (origin/journal, 15 Oct to 6 Nov 2026) in the archive's shape, for the one-time backfill. Read-only."""
    import hashlib
    import sqlite3
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(news)")}
    want = [c for c in ("ts", "title", "link", "source", "sentiment", "impact", "nlp") if c in cols]
    out = []
    for rec in con.execute(f"SELECT {', '.join(want)} FROM news WHERE title IS NOT NULL ORDER BY ts"):
        r = dict(zip(want, rec))
        title = " ".join(str(r["title"]).split())[:220]
        try:
            when = dt.datetime.fromisoformat(str(r["ts"]))
        except ValueError:
            continue
        when = when.replace(tzinfo=IST) if when.tzinfo is None else when
        try:
            nlp = json.loads(r.get("nlp") or "{}")
        except ValueError:
            nlp = {}
        nlp = nlp if isinstance(nlp, dict) else {}
        row = {"id": hashlib.sha1((r.get("link") or title).encode("utf-8")).hexdigest()[:12],
               "ts": when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "title": title, "source": str(r.get("source") or "")[:40],
               "link": str(r.get("link") or "")[:500], "from": "journal"}
        if isinstance(r.get("sentiment"), (int, float)):
            row["tone"] = round(max(-1.0, min(1.0, float(r["sentiment"]))), 2)
        if r.get("impact") in ("low", "medium", "high"):
            row["impact"] = r["impact"]
        if isinstance(nlp.get("event"), str):
            row["event"] = nlp["event"][:24]
        if isinstance(nlp.get("novelty"), (int, float)):
            row["novelty"] = round(float(nlp["novelty"]), 2)
        out.append(row)
    con.close()
    return out
