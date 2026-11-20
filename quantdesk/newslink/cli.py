"""`quantdesk news …`: read the desk's RSS feeds with the news engine, build the digest the app's News panel shows, and (with --push) send it to the relay. Public headlines only; never a broker."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pandas as pd


def _send(ND, path: str) -> None:
    """Send a digest file made by an earlier step. No feed is read here: this is the only step that holds the ingest key, and it parses no third-party text beyond our own JSON."""
    try:
        digest = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit("news: the digest file could not be read") from None
    if not (isinstance(digest, dict) and digest.get("v") == 1 and isinstance(digest.get("items"), list) and len(digest["items"]) <= 200 and isinstance(digest.get("asof"), str)):
        raise SystemExit("news: that file is not a digest")
    url, token = (os.environ.get("LIVE_URL") or "").strip(), (os.environ.get("LIVE_INGEST_TOKEN") or "").strip()
    if not (url and token):
        raise SystemExit("news --send needs LIVE_URL and LIVE_INGEST_TOKEN")
    try:
        ans = ND.push(digest, url, token)
    except (RuntimeError, ValueError) as e:
        raise SystemExit(f"news: {e}") from None
    print(f"news: sent to the relay ({ans.get('n', '?')} stories held)")


def _archive(paths: list[str] | None, backfill_db: str | None, work: str) -> None:
    """Keep every headline (newslink/archive.py). Reads only our own JSON files (or the journal's database, read-only); the repository token is the one secret
    here. Several digest runs' files can be given: a run whose archive job was cancelled is merged again by the next one (merging is idempotent)."""
    from . import archive as AR
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise SystemExit("news --archive needs GITHUB_REPOSITORY (owner/name)")
    if backfill_db:
        batches, limit, windowed = [(AR.from_journal(backfill_db), "journal-backfill")], None, False
    else:
        batches, limit, windowed = [], AR.MAX_ROWS, True
        for path in paths or []:
            try:
                doc = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise SystemExit(f"news --archive: {path} could not be read") from None
            if not (isinstance(doc, dict) and doc.get("v") == 1 and isinstance(doc.get("items"), list) and isinstance(doc.get("asof"), str)):
                raise SystemExit(f"news --archive: {path} is not an archive rows file")
            batches.append((doc["items"], doc["asof"]))
    token = re.sub(r"[^0-9a-z]", "", (os.environ.get("GITHUB_RUN_ID") or str(int(time.time()))).lower())[:20] or "run"
    store_for = lambda tag: AR.GhRelease(tag, repo)  # noqa: E731
    try:
        done = AR.archive(batches, store_for, Path(work), token, limit=limit, windowed=windowed)
    except Exception as e:                                                                  # noqa: BLE001
        raise SystemExit(f"news --archive: {type(e).__name__}: {str(e)[:200]}") from None
    added = sum(b - a for a, b in done.values())
    print(f"news archive: {sum(len(r) for r, _ in batches)} rows read from {len(batches)} run(s), {added} new stories kept, "
          f"days {', '.join(f'{d} {a}->{b}' for d, (a, b) in done.items()) or 'none'}")


def cmd_news(cfg, a):
    from ..premarket import newsdigest as ND
    if a.send:
        return _send(ND, a.send)
    arch, back = getattr(a, "archive", None), getattr(a, "backfill_journal", None)
    if arch or back:
        return _archive(arch, back, str(Path(a.out) / "_archive"))
    t0 = time.monotonic()
    now = pd.Timestamp(a.now) if a.now else pd.Timestamp.now(tz="Asia/Kolkata")
    now = now.tz_localize("Asia/Kolkata") if now.tzinfo is None else now.tz_convert("Asia/Kolkata")
    digest = ND.fetch_digest(cfg, now, archive=True)
    rows = digest.pop("_archive", None) or digest["items"]
    ok = sum(1 for v in digest["sources"].values() if str(v).startswith("ok"))
    print(f"news: {digest['n']} stories; {ok} of {len(digest['sources'])} feeds answered ({time.monotonic() - t0:.0f}s)")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "news.json").write_text(json.dumps(digest, ensure_ascii=False), encoding="utf-8")
    (out / "archive.json").write_text(json.dumps({"v": 1, "asof": digest["asof"], "items": rows}, ensure_ascii=False), encoding="utf-8")
    if ok == 0:
        raise SystemExit("news: no feed answered: nothing to send")
    if a.push:
        url, token = (os.environ.get("LIVE_URL") or "").strip(), (os.environ.get("LIVE_INGEST_TOKEN") or "").strip()
        if not (url and token):
            raise SystemExit("news --push needs LIVE_URL and LIVE_INGEST_TOKEN")
        try:
            ans = ND.push(digest, url, token)
        except (RuntimeError, ValueError) as e:
            raise SystemExit(f"news: {e}") from None
        print(f"news: sent to the relay ({ans.get('n', '?')} stories held)")


def register(sub):
    s = sub.add_parser("news", help="the news digest: read the desk's RSS feeds and (--push) send the digest to the relay (public headlines only)")
    s.add_argument("--push", action="store_true", help="send the digest to the relay (env LIVE_URL, LIVE_INGEST_TOKEN)")
    s.add_argument("--send", metavar="FILE", help="send a digest file made earlier (no feed is read): the step that holds the ingest key")
    s.add_argument("--out", default="runtime/news", help="folder for news.json and archive.json")
    s.add_argument("--archive", metavar="FILE", nargs="+", help="keep the rows of archive.json files made by digest runs in the headline archive (needs GH_TOKEN, GITHUB_REPOSITORY; no feed is read)")
    s.add_argument("--backfill-journal", metavar="DB", help="one-time: keep the journal database's headlines (origin/journal) in the headline archive (needs GH_TOKEN)")
    s.add_argument("--now", help="the moment to read for (ISO, IST; default now)")
    s.set_defaults(fn=cmd_news)
