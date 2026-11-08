"""`quantdesk news …`: read the desk's RSS feeds with the news engine, build the digest the app's News panel shows, and (with --push) send it to the relay. Public headlines only; never a broker."""
from __future__ import annotations

import json
import os
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


def cmd_news(cfg, a):
    from ..premarket import newsdigest as ND
    if a.send:
        return _send(ND, a.send)
    t0 = time.monotonic()
    now = pd.Timestamp(a.now) if a.now else pd.Timestamp.now(tz="Asia/Kolkata")
    now = now.tz_localize("Asia/Kolkata") if now.tzinfo is None else now.tz_convert("Asia/Kolkata")
    digest = ND.fetch_digest(cfg, now)
    ok = sum(1 for v in digest["sources"].values() if str(v).startswith("ok"))
    print(f"news: {digest['n']} stories; {ok} of {len(digest['sources'])} feeds answered ({time.monotonic() - t0:.0f}s)")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "news.json").write_text(json.dumps(digest, ensure_ascii=False), encoding="utf-8")
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
    s.add_argument("--out", default="runtime/news", help="folder for news.json")
    s.add_argument("--now", help="the moment to read for (ISO, IST; default now)")
    s.set_defaults(fn=cmd_news)
