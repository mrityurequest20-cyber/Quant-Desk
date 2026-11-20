"""The headline archive (docs/NEWS_ENGINE.md, L0): every headline the news job reads is kept, so the desk has a history to learn from and to test against.

Nothing had stored headlines since 6 Nov 2026 (the weekly archive job went with #196; the relay keeps only the newest digest). This module keeps them again: each
run's items (the digest's own cleaned rows, before the digest's 80-item cap) are merged into one file per day, `news_<YYYY-MM-DD>.jsonl.gz` (the day in India), on a
release per month, `news-archive-<YYYY-MM>`. A row is keyed by its digest id (a hash of the link or title); the first time a story is seen wins and keeps its
`first_seen`, so a day's file only ever grows.

Public RSS titles and links and the desk's own tags (tone, impact, novelty, symbols); never article text, never anything private. Every kept field is type- and
length-checked, and a run's rows must lie in that run's own window (`asof` - 48 h to `asof` + 1 h), so a bad artifact cannot write into past days.

Never deleting data (RENAISSANCE invariant 5): a day's file is replaced only through a verified superset. The merged file (every old row plus the new ones) is
uploaded under a temporary name, confirmed listed with its exact size, and only then is the old asset deleted and the new one renamed into place, and confirmed
again. If a run stops between those steps, the next run finds the temporary copy and finishes from it. A failed listing or download stops the archive before any
write. The only assets ever deleted are ones whose every row is in a confirmed-uploaded file.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import math
import re
import subprocess
from pathlib import Path

TAG_PREFIX = "news-archive"
MAX_ROWS = 5000                                   # per run, a sanity bound (a day is about 425 distinct stories)
WINDOW_BEFORE, WINDOW_AFTER = dt.timedelta(hours=48), dt.timedelta(hours=1)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
_ID = re.compile(r"^[0-9a-f]{6,40}$")
_SYM = re.compile(r"^[A-Z0-9&\-]{1,20}$")
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


def _short(v, n: int) -> bool:
    return isinstance(v, str) and len(v) <= n


def _num(v, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


def clean(row) -> dict | None:
    """The archived fields of one digest row, each checked; None for a row that is not one. A field that fails its check is dropped, not the row."""
    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not _ID.match(row["id"]) or _ts(row.get("ts")) is None:
        return None
    title = row.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 220:
        return None
    out = {"id": row["id"], "ts": row["ts"], "title": title}
    link = row.get("link")
    if isinstance(link, str) and len(link) <= 500 and (link.startswith("https://") or link == ""):
        out["link"] = link
    if _short(row.get("source"), 40):
        out["source"] = row["source"]
    src = row.get("sources")
    if isinstance(src, list) and len(src) <= 6 and all(_short(s, 40) for s in src):
        out["sources"] = src
    if _num(row.get("tone"), -1.0, 1.0):
        out["tone"] = row["tone"]
    if row.get("tone_from") in ("surprise", "words"):
        out["tone_from"] = row["tone_from"]
    if row.get("impact") in ("low", "medium", "high"):
        out["impact"] = row["impact"]
    if isinstance(row.get("recap"), bool):
        out["recap"] = row["recap"]
    if _short(row.get("event"), 24):
        out["event"] = row["event"]
    if _num(row.get("novelty"), 0.0, 1.0):
        out["novelty"] = row["novelty"]
    sym = row.get("symbols")
    if isinstance(sym, list) and len(sym) <= 20 and all(isinstance(s, str) and _SYM.match(s) for s in sym):
        out["symbols"] = sym
    if row.get("from") == "journal":
        out["from"] = "journal"
    return out


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


class GhRelease:
    """One release, through the gh CLI (GH_TOKEN), with the operations a safe replace needs. Every call is checked; a failure raises."""

    def __init__(self, tag: str, repo: str, run=subprocess.run, title: str = "", notes: str = ""):
        self.tag, self.repo, self._run, self.title, self.notes = tag, repo, run, title or TITLE.format(month=tag[len(TAG_PREFIX) + 1:]), notes or NOTES

    def _gh(self, *args, check=True):
        return self._run(["gh", *args], check=check, capture_output=True, text=True)

    def assets(self) -> dict[str, dict] | None:
        """{name: {"id", "size"}}, or None when the release does not exist. Any other failure raises."""
        r = self._gh("api", f"repos/{self.repo}/releases/tags/{self.tag}", check=False)
        if r.returncode != 0:
            if "Not Found" in (r.stdout or "") + (r.stderr or ""):
                return None
            raise subprocess.CalledProcessError(r.returncode, "gh api releases/tags")
        return {a["name"]: {"id": a["id"], "size": a["size"]} for a in json.loads(r.stdout).get("assets", [])}

    def ensure(self) -> None:
        self._gh("release", "create", self.tag, "-R", self.repo, "--title", self.title, "--latest=false", "--notes", self.notes)

    def download(self, name: str, dest: Path) -> None:
        self._gh("release", "download", self.tag, "-R", self.repo, "--pattern", name, "--dir", str(dest), "--clobber")

    def upload(self, path: Path) -> None:
        self._gh("release", "upload", self.tag, "-R", self.repo, str(path))                     # no clobber flag: gh would delete the old asset first

    def delete(self, asset_id: int) -> None:
        self._gh("api", "-X", "DELETE", f"repos/{self.repo}/releases/assets/{int(asset_id)}")

    def rename(self, asset_id: int, name: str) -> None:
        self._gh("api", "-X", "PATCH", f"repos/{self.repo}/releases/assets/{int(asset_id)}", "-f", f"name={name}")


def _replace(store, work: Path, name: str, data: bytes, old: dict | None, leftovers: dict, token: str) -> None:
    """Put `data` (a superset of `old`) in place of `name`, never losing a row: upload as a temporary, confirm, delete the old, rename, confirm."""
    tmp = f"{name}.tmp-{token}"
    (work / tmp).write_bytes(data)
    store.upload(work / tmp)
    have = store.assets() or {}
    if have.get(tmp, {}).get("size") != len(data):
        raise RuntimeError(f"{tmp} is not listed with its size after the upload: the old file is left in place")
    if old is not None and name in have:
        store.delete(have[name]["id"])
    store.rename(have[tmp]["id"], name)
    have = store.assets() or {}
    if have.get(name, {}).get("size") != len(data):
        raise RuntimeError(f"{name} is not listed with its size after the rename (the data is in {tmp})")
    for n in leftovers:                                    # earlier temporaries: every row they held is in the confirmed file
        if n in have and n != name:
            store.delete(have[n]["id"])


def archive(batches: list[tuple[list, str]], store_for, work: Path, token: str, limit: int | None = MAX_ROWS, windowed: bool = True) -> dict[str, tuple[int, int]]:
    """Merge [(rows, seen_at)] into their days' files. store_for(tag) gives a GhRelease-like object. `limit` bounds one run; `windowed` keeps a run's rows to
    its own window (seen_at - 48 h to seen_at + 1 h). The one-time backfill passes limit=None, windowed=False. Returns {day: (rows before, rows after)}."""
    by_day: dict[dt.date, list[tuple[dict, str]]] = {}
    for rows, seen_at in batches:
        asof = _ts(seen_at)
        for r in (clean(x) for x in (rows if limit is None else rows[:limit])):
            if r is None:
                continue
            if windowed and (asof is None or not (asof - WINDOW_BEFORE <= _ts(r["ts"]) <= asof + WINDOW_AFTER)):
                continue
            by_day.setdefault(day_of(r["ts"]), []).append((r, seen_at))
    work.mkdir(parents=True, exist_ok=True)
    done = {}
    for day in sorted(by_day):
        tag, name = tag_for(day), asset_for(day)
        store = store_for(tag)
        have = store.assets()
        if have is None:
            store.ensure()
            have = {}
        temps = sorted(n for n in have if n.startswith(name + ".tmp-"))
        source = name if name in have else (temps[-1] if temps else None)       # a run that stopped mid-replace left its superset as a temporary
        existing = []
        if source:
            store.download(source, work)
            if not (work / source).exists():
                raise RuntimeError(f"{source} is listed on {tag} but could not be downloaded: not writing")
            existing = loads((work / source).read_bytes())
        merged = existing
        for r, seen_at in by_day[day]:
            merged = merge(merged, [r], seen_at)
        if len(merged) == len(existing) and source == name and not temps:
            done[day.isoformat()] = (len(existing), len(merged))
            continue
        assert {r["id"] for r in existing} <= {r["id"] for r in merged}
        _replace(store, work, name, dumps(merged), have.get(name), {n: have[n] for n in temps}, token)
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
            row["novelty"] = round(max(0.0, min(1.0, float(nlp["novelty"]))), 2)
        out.append(row)
    con.close()
    return out
