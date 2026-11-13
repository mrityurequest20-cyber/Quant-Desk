"""The news digest: the day's market headlines, read by the desk's own news engine (quantdesk/intraday/news.py: de-duplication across outlets, tone with the subject taken into account, surprise
against expectations, market-move recaps told apart from news, novelty), plus which instruments each story names. Public data only (the desk's RSS sources): titles and links, never article text. The one network write, `push`, sends only our own digest to the desk's relay with a token handed in as an argument (this module reads no environment).

It is a reading aid, not a signal: it places nothing, sizes nothing and changes no desk path. The tone is a word-list reading of a headline; where the text states an expectation it is tilted by the
surprise. The app joins the stories to the live board (did the name move, are its options trading hard?), which is the part that says whether the market cared.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request

import pandas as pd

# symbol -> the names a headline uses. A term of up to five capital letters (SBI, ITC, TCS) must match in that case, so "itc" or "Tcs" in a sentence is not read as a company.
ALIASES: dict[str, list[str]] = {
    "NIFTY": ["Nifty 50", "Nifty50", "Nifty"], "BANKNIFTY": ["Bank Nifty", "BankNifty", "Nifty Bank"], "SENSEX": ["Sensex"], "FINNIFTY": ["Fin Nifty", "FinNifty", "Nifty Financial"],
    "MIDCPNIFTY": ["Midcap Select", "Nifty Midcap Select"],
    "RELIANCE": ["Reliance Industries", "Reliance", "RIL"], "HDFCBANK": ["HDFC Bank"], "ICICIBANK": ["ICICI Bank"], "INFY": ["Infosys"], "TCS": ["TCS", "Tata Consultancy"],
    "SBIN": ["State Bank of India", "SBI"], "BHARTIARTL": ["Bharti Airtel", "Airtel"], "ITC": ["ITC"], "LT": ["Larsen & Toubro", "Larsen and Toubro", "L&T"], "AXISBANK": ["Axis Bank"],
    "KOTAKBANK": ["Kotak Mahindra Bank", "Kotak Bank"], "BAJFINANCE": ["Bajaj Finance"], "MARUTI": ["Maruti Suzuki", "Maruti"], "SUNPHARMA": ["Sun Pharma", "Sun Pharmaceutical"],
    "TATASTEEL": ["Tata Steel"], "NTPC": ["NTPC"], "HINDUNILVR": ["Hindustan Unilever", "HUL"], "ADANIENT": ["Adani Enterprises"], "ONGC": ["ONGC"], "HCLTECH": ["HCLTech", "HCL Tech", "HCL Technologies"],
    "M&M": ["Mahindra & Mahindra", "Mahindra and Mahindra", "M&M"], "ADANIPORTS": ["Adani Ports"], "WIPRO": ["Wipro"], "TECHM": ["Tech Mahindra"], "POWERGRID": ["Power Grid", "PowerGrid"],
    "COALINDIA": ["Coal India"], "JSWSTEEL": ["JSW Steel"], "HINDALCO": ["Hindalco"], "VEDL": ["Vedanta"], "INDUSINDBK": ["IndusInd Bank"], "BAJAJFINSV": ["Bajaj Finserv"],
    "TITAN": ["Titan Company", "Titan Co"], "ULTRACEMCO": ["UltraTech Cement", "UltraTech"], "ASIANPAINT": ["Asian Paints"], "DLF": ["DLF"], "TRENT": ["Trent Ltd"],
    "BEL": ["Bharat Electronics"], "HAL": ["Hindustan Aeronautics"], "ETERNAL": ["Eternal Ltd", "Zomato"], "INDIGO": ["InterGlobe Aviation", "IndiGo"], "PNB": ["Punjab National Bank", "PNB"],
    "BANKBARODA": ["Bank of Baroda"], "CANBK": ["Canara Bank"], "IDFCFIRSTB": ["IDFC First Bank", "IDFC First"], "TVSMOTOR": ["TVS Motor"], "EICHERMOT": ["Eicher Motors", "Royal Enfield"],
    "DRREDDY": ["Dr Reddy's", "Dr. Reddy's", "Dr Reddys"], "CIPLA": ["Cipla"], "SBILIFE": ["SBI Life"], "TMPV": ["Tata Motors"], "BAJAJ-AUTO": ["Bajaj Auto"], "HEROMOTOCO": ["Hero MotoCorp"],
    "NESTLEIND": ["Nestle India"], "BRITANNIA": ["Britannia"], "GRASIM": ["Grasim"], "APOLLOHOSP": ["Apollo Hospitals"], "DIVISLAB": ["Divi's Laboratories", "Divis Laboratories", "Divi's Labs"],
    "LUPIN": ["Lupin"], "TATAPOWER": ["Tata Power"], "PFC": ["Power Finance Corporation", "PFC"], "RECLTD": ["REC Ltd", "REC Limited"], "IRCTC": ["IRCTC"], "JINDALSTEL": ["Jindal Steel"],
    "SAIL": ["Steel Authority of India", "SAIL"], "NMDC": ["NMDC"], "BHEL": ["Bharat Heavy Electricals", "BHEL"], "GAIL": ["GAIL"], "IOC": ["Indian Oil"], "BPCL": ["Bharat Petroleum", "BPCL"],
    "HINDPETRO": ["Hindustan Petroleum", "HPCL"], "SIEMENS": ["Siemens"], "HAVELLS": ["Havells"], "POLYCAB": ["Polycab"], "MUTHOOTFIN": ["Muthoot Finance"], "CHOLAFIN": ["Cholamandalam"],
    "SHRIRAMFIN": ["Shriram Finance"], "GODREJCP": ["Godrej Consumer"], "TATACONSUM": ["Tata Consumer"], "HDFCLIFE": ["HDFC Life"], "JIOFIN": ["Jio Financial"],
}
INDICES = ("NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY")
MAX_ITEMS = 80
MAX_AGE_H = 36


def _compile() -> dict[str, re.Pattern]:
    out = {}
    for sym, terms in ALIASES.items():
        ci = [re.escape(t) for t in terms if not (t.isupper() and len(t) <= 5 and t.isalpha())]
        cs = [re.escape(t) for t in terms if t.isupper() and len(t) <= 5 and t.isalpha()]
        out[sym] = (re.compile(r"(?<![\w&])(" + "|".join(ci) + r")(?![\w&])", re.I) if ci else None, re.compile(r"(?<![\w&])(" + "|".join(cs) + r")(?![\w&])") if cs else None)
    return out


_PATS = _compile()


def match_symbols(title: str) -> list[str]:
    """The instruments a headline names, in the order of ALIASES. 'Bank Nifty' names BANKNIFTY and not NIFTY; a single-word match must stand alone (no 'Titanic' for Titan)."""
    t = str(title or "")
    stripped = re.sub(r"(?i)\b(bank ?nifty|nifty bank|fin ?nifty|nifty financial|nifty midcap select|midcap select)\b", " ", t)
    out = []
    for sym, (ci, cs) in _PATS.items():
        text = stripped if sym == "NIFTY" else t
        if (ci and ci.search(text)) or (cs and cs.search(text)):
            out.append(sym)
    return out


def _safe_link(url: str) -> str:
    u = str(url or "").strip()
    return u if re.match(r"^https://[^\s<>\"']{4,500}$", u) else ""


def _iso(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- the event watch (owner, 13 Nov 2026: "Advanced news analyser ... analyse news and predict what could happen and what happened in the past in these kind of scenarios") ----
# The stories' own event types (intraday/nlp.py) gathered into active EVENTS: each story counts by its impact, its novelty and its type's weight, decayed by the type's half-life;
# an event's severity is the sum, its tone the weighted mean of the stories' tones. The `kind` names the past episodes the pre-market brief measures (history.macro_history:
# what NIFTY and BANKNIFTY did on them), so the app and AUTO v2 can put "what happened the last times" beside "what is happening now".
EVENT_KIND = {"geopolitics": "geopolitics", "commodities": "oil_shock", "regulation": "budget"}          # the event type -> the analogue kind (policy: rbi or fomc, by the words)
IMPACT_W = {"high": 1.0, "medium": 0.5, "low": 0.2}
EVENT_WATCH, EVENT_HIGH = 1.0, 2.5                                    # severity at which an event is listed, and at which it is "high" (AUTO v2's event regime)
EVENT_WINDOW_H = 12


def event_watch(rows: list[dict], now: pd.Timestamp) -> list[dict]:
    from ..intraday import nlp as NLP
    spec = {n: (hl, w) for n, _p, hl, w in NLP.EVENTS}
    acc: dict[str, dict] = {}
    for r in rows:
        ev = r.get("event")
        if ev not in spec or r.get("recap"):
            continue
        try:
            age_min = (now - pd.Timestamp(r["ts"])).total_seconds() / 60
        except (KeyError, ValueError, TypeError):
            continue
        if not (0 <= age_min <= EVENT_WINDOW_H * 60):
            continue
        hl, w = spec[ev]
        x = IMPACT_W.get(r.get("impact"), 0.2) * max(0.2, float(r.get("novelty") or 0.0)) * w * 0.5 ** (age_min / hl)
        a = acc.setdefault(ev, {"sev": 0.0, "tone": 0.0, "n": 0, "top": [], "kind": None})
        a["sev"] += x
        a["tone"] += x * float(r.get("tone") or 0.0)
        a["n"] += 1
        if len(a["top"]) < 3:
            a["top"].append(str(r.get("title"))[:140])
        if ev == "policy":
            t = str(r.get("title", "")).lower()
            a["kind"] = a["kind"] or ("rbi" if any(k in t for k in ("rbi", "repo", "mpc")) else "fomc" if any(k in t for k in ("fed", "fomc")) else None)
    out = []
    for ev, a in acc.items():
        if a["sev"] < EVENT_WATCH:
            continue
        out.append({"type": ev, "severity": round(a["sev"], 2), "level": "high" if a["sev"] >= EVENT_HIGH else "watch", "tone": round(a["tone"] / a["sev"], 2),
                    "n": a["n"], "top": a["top"], "kind": a["kind"] or EVENT_KIND.get(ev)})
    return sorted(out, key=lambda e: -e["severity"])[:6]


def build(items, now: pd.Timestamp, health: dict | None = None, limit: int = MAX_ITEMS, max_age_h: float = MAX_AGE_H) -> dict:
    """The digest the relay serves: newest first, at most `limit` stories from the last `max_age_h` hours."""
    rows = []
    for x in sorted(items, key=lambda i: i.ts, reverse=True):
        if now - x.ts > pd.Timedelta(hours=max_age_h) or x.ts - now > pd.Timedelta(minutes=10):
            continue
        title = " ".join(str(x.title).split())[:220]
        if not title:
            continue
        nlp = x.nlp or {}
        rows.append({
            "id": hashlib.sha1((x.link or title).encode("utf-8")).hexdigest()[:12], "ts": _iso(x.ts), "source": str(x.source)[:40], "sources": [str(s)[:40] for s in (x.sources or [x.source])][:6],
            "title": title, "link": _safe_link(x.link), "tone": round(float(max(-1.0, min(1.0, x.sentiment))), 2), "tone_from": "surprise" if nlp.get("surprise") is not None else "words",
            "impact": x.impact if x.impact in ("low", "medium", "high") else "low", "recap": bool(x.recap), "event": str(nlp.get("event") or "general")[:24],
            "novelty": round(float(x.novelty), 2), "symbols": match_symbols(title),
        })
        if len(rows) >= limit:
            break
    return {"v": 1, "asof": _iso(now), "n": len(rows), "sources": {str(k)[:40]: str(v)[:60] for k, v in (health or {}).items()}, "items": rows,
            "events": event_watch(rows, now)}


def fetch_digest(cfg, now: pd.Timestamp | None = None, fetch=None, sources=None) -> dict:
    """Fetch the desk's feeds and build the digest. `fetch` and `sources` are for tests."""
    from ..intraday.news import NewsDesk
    now = now or pd.Timestamp.now(tz="Asia/Kolkata")
    desk = NewsDesk(cfg, fetch=fetch, sources=sources)
    desk.refresh(now, force=True)
    return build(list(desk.items.values()), now.tz_convert("UTC") if now.tzinfo else now.tz_localize("UTC"), desk.health)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def push(digest: dict, live_url: str, token: str, opener=None, timeout: float = 30.0) -> dict:
    """POST the digest to the relay (/news/ingest) with the ingest key. https only; a redirect is refused (the key would follow it); the key is never in an error."""
    from ..paperlink.relay import base_of
    if not token:
        raise ValueError("no ingest token")
    body = json.dumps(digest, allow_nan=False).encode()
    req = urllib.request.Request(base_of(live_url) + "/news/ingest", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token, "User-Agent": "quantdesk-news"})
    open_ = opener or urllib.request.build_opener(_NoRedirect).open
    try:
        with open_(req, timeout=timeout) as r:
            return json.loads(r.read(65536) or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"the relay refused the news digest: HTTP {e.code}") from None
    except Exception as e:                                           # noqa: BLE001
        raise RuntimeError(f"the news digest could not be sent: {type(e).__name__}") from None
