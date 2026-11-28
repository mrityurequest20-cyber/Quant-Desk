"""News phase P0: which news sources answer from the machine that will use them (GitHub Actions), how far back each one
goes, whether a live feed supports cheap conditional polling (ETag / Last-Modified: the 30-second poll), and whether the
Anthropic key works. `python -m marketlens news-probe`. Prints a report and never fails, so the answer is in the log.

History candidates (the labelled corpus needs years, not weeks):
  * NSE corporate announcements (exact timestamps, structured subjects: results, board meetings, M&A, ratings ...)
  * BSE corporate announcements (the same filings, a second door)
  * Google News RSS with after:/before: dates (headlines from any past window, up to 100 a query)
  * GDELT's DOC API (world news, filtered to Indian sources)
  * RBI press releases
Live feeds: the RSS list the desk's digest already reads.

The key is read from the environment (ANTHROPIC_API_KEY, filled from the GitHub secret CLAUDE_API) and never printed: the check sends one
16-token request to the cheapest model and reports only whether it answered and the model id that served it.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
ITEM = re.compile(rb"<item[\s>]")
TITLE = re.compile(rb"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.S)
PUBDATE = re.compile(rb"<pubDate>(.*?)</pubDate>", re.S)


def _get(url, headers=None, n_head=160, **kw):
    try:
        r = requests.get(url, headers={**UA, **(headers or {})}, timeout=25, **kw)
        b = r.content
        out = {"status": r.status_code, "bytes": len(b), "etag": bool(r.headers.get("ETag")),
               "last_modified": bool(r.headers.get("Last-Modified")), "cache_control": r.headers.get("Cache-Control", "")[:60]}
        if ITEM.search(b):
            titles = [t.decode("utf-8", "replace").strip()[:90] for t in TITLE.findall(b)[1:4]]
            dates = [d.decode().strip() for d in PUBDATE.findall(b)]
            out.update({"items": len(ITEM.findall(b)), "sample": titles, "oldest": dates[-1] if dates else None, "newest": dates[0] if dates else None})
        else:
            out["head"] = b[:n_head].decode("utf-8", "replace")
        return out, r
    except Exception as e:                                       # noqa: BLE001 - a probe reports, it never raises
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}, None


def conditional(url):
    """Does a second GET with If-None-Match / If-Modified-Since answer 304 (a cheap 30-second poll)?"""
    first, r = _get(url)
    if r is None:
        return first
    h = {}
    if r.headers.get("ETag"):
        h["If-None-Match"] = r.headers["ETag"]
    if r.headers.get("Last-Modified"):
        h["If-Modified-Since"] = r.headers["Last-Modified"]
    if h:
        second, r2 = _get(url, headers=h)
        first["second_status"] = second.get("status")
    return first


def history() -> dict:
    out = {}
    from quantdesk.data import nse as N
    c = N.NSE()
    for span in (("01-01-2019", "07-01-2019"), ("02-01-2023", "06-01-2023")):
        try:
            j, raw, url = c.api(f"/api/corporate-announcements?index=equities&from_date={span[0]}&to_date={span[1]}")
            rows = j if isinstance(j, list) else j.get("data", [])
            keys = sorted(rows[0].keys()) if rows else []
            out[f"nse_announcements:{span[0]}"] = {"ok": bool(rows), "n": len(rows), "keys": keys[:20],
                                                   "sample": [{k: str(r.get(k))[:80] for k in ("symbol", "desc", "an_dt", "sort_date")} for r in rows[:3]]}
        except Exception as e:                                   # noqa: BLE001
            out[f"nse_announcements:{span[0]}"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    for day in ("20190102", "20230103"):
        o, r = _get("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1"
                    f"&strPrevDate={day}&strScrip=&strSearch=P&strToDate={day}&strType=C&subcategory=-1",
                    headers={"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"})
        if r is not None and r.status_code == 200:
            try:
                j = r.json()
                rows = j.get("Table", [])
                o = {"status": 200, "n_page1": len(rows), "total": (j.get("Table1") or [{}])[0].get("ROWCNT"),
                     "keys": sorted(rows[0].keys())[:25] if rows else [],
                     "sample": [{k: str(x.get(k))[:80] for k in ("SLONGNAME", "NEWSSUB", "CATEGORYNAME", "NEWS_DT", "DissemDT")} for x in rows[:3]]}
            except Exception as e:                               # noqa: BLE001
                o["parse_error"] = f"{type(e).__name__}: {str(e)[:100]}"
        out[f"bse_announcements:{day}"] = o
    for q, label in (("Reliance Industries after:2019-03-01 before:2019-03-31", "gnews:reliance_2019_03"),
                     ("RBI repo rate after:2020-03-20 before:2020-04-05", "gnews:rbi_2020_03"),
                     ("Nifty OR Sensex after:2021-06-01 before:2021-06-03", "gnews:nifty_2021_06")):
        url = "https://news.google.com/rss/search?q=" + requests.utils.quote(q) + "&hl=en-IN&gl=IN&ceid=IN:en"
        out[label] = _get(url)[0]
    out["gdelt_doc:2019"] = _get("https://api.gdeltproject.org/api/v2/doc/doc?query=%28nifty%20OR%20sensex%29%20sourcecountry%3AIN"
                                 "&mode=artlist&format=json&maxrecords=5&startdatetime=20190102000000&enddatetime=20190110000000")[0]
    out["gdelt_doc:recent"] = _get("https://api.gdeltproject.org/api/v2/doc/doc?query=%28nifty%20OR%20sensex%29%20sourcecountry%3AIN"
                                   "&mode=artlist&format=json&maxrecords=5&timespan=3d")[0]
    out["gdelt_raw_2019"] = _get("http://data.gdeltproject.org/gdeltv2/20190102000000.gkg.csv.zip", stream=True)[0]
    out["rbi_archive"] = _get("https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx")[0]
    return out


def live() -> dict:
    from quantdesk.intraday.news import DEFAULT_SOURCES
    feeds = list(DEFAULT_SOURCES) + [
        {"name": "NSE announcements RSS", "url": "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"},
        {"name": "BSE announcements (latest)", "url": "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1&strPrevDate=&strScrip=&strSearch=P&strToDate=&strType=C&subcategory=-1"},
        {"name": "Reuters India (Google News)", "url": "https://news.google.com/rss/search?q=site%3Areuters.com%20India%20when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen"},
    ]
    return {f["name"]: conditional(f["url"]) for f in feeds}


def key_check() -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return {"ok": False, "why": "ANTHROPIC_API_KEY is not set in this job"}
    try:
        import anthropic
        c = anthropic.Anthropic()
        r = c.messages.create(model="claude-haiku-5-5", max_tokens=16, output_config={"effort": "low"},
                              messages=[{"role": "user", "content": "Reply with the single word: ready"}])
        text = "".join(b.text for b in r.content if b.type == "text").strip()[:20]
        out = {"ok": True, "model": r.model, "reply": text, "input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens}
        try:
            ids = [m.id for m in c.models.list(limit=40)]
            out["models_visible"] = [m for m in ids if m in ("claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5")]
        except Exception as e:                                   # noqa: BLE001
            out["models_error"] = type(e).__name__
        return out
    except Exception as e:                                       # noqa: BLE001 - the SDK's errors never carry the key
        return {"ok": False, "error": type(e).__name__, "status": getattr(e, "status_code", None), "message": str(getattr(e, "message", ""))[:160]}


def main() -> int:
    rep = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "key_secret": os.environ.get("KEY_FROM", "?"), "anthropic": key_check(), "history": history(), "live": live()}
    print(json.dumps(rep, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
