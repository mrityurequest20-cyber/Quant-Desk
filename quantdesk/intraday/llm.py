"""Language models as second readers of the news, and an end-of-day reflection.

The rule-based NLP (nlp.py) reads every headline instantly and the same way every time. A language model reads
context the rules can't: what a story means for Indian equities, whether it's already priced, whether it's a
retelling. Each configured provider is a separate **reader**. Claude (the Anthropic SDK), Gemini and Ollama (their
REST APIs) each give, per headline, the likely direction of NIFTY and BANKNIFTY over the next 30-60 minutes, signed
-1..+1, with a confidence. The learning loop (learning.py) grades every reader against what the index did next,
and the news tone trusts each reader by its record, the rules included. A reader that keeps being wrong fades.

Reads run on a background thread, so a slow API never holds the trading loop. A read counts from the moment it
arrived (`at`), never from the headline's publish time, so replays don't see a read before the desk had it.
Calls are batched and capped per provider per day. Without a key a provider is simply absent, and the desk runs on
the rules as before.

The reflection: after the close, Claude reads the session review and the learning record and writes a few
lessons. They go into the review and the memory for the human. They never touch orders, sizing or risk.

Claude is paid from a fixed credit (ClaudeBudget): every call's real `usage` is priced and added to a ledger in the
journal, a day's allowance is the credit left over the sessions left (so underspending carries forward), a slice of it
is held back for the reflection, and when the credit is gone Claude simply stops: one INFO event, no errors, and the
desk carries on with the other readers and everything it learned. Claude is advisory (news.py), so none of it can
reach the tone, a signal, a size or a limit.

Keys come from the environment, never from files, and are never printed (`key_for` returns the variable's name for
reports). Each provider accepts a few common names for its variable, so a repository secret works under any of them.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import queue
import threading
import time

import pandas as pd

log = logging.getLogger(__name__)
IST = "Asia/Kolkata"

KEY_NAMES = {        # the first name set wins; a repository secret works under any of these (spaces become _)
    "claude": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "CLAUDE_KEY", "CLAUDE_API", "CLOUD_API_KEY", "CLOUD_API",
               "CLAUDE_API_TOKEN", "ANTHROPIC_API", "ANTHROPIC_KEY", "ANTHROPIC", "CLAUDE", "CLOUDE_API",
               "CLOUDE_API_KEY", "CLAUDE_AI_API_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_API", "GOOGLE_AI_API_KEY", "GOOGLE_GENAI_API_KEY",
               "GEMINI_KEY", "GEMINI_API", "GEMINI", "GOOGLE_KEY", "GOOGLE", "GOOGLEAPI", "GOOGLE_API_TOKEN",
               "GOOGLE_GEMINI_API_KEY", "GOOGLE_AI_KEY", "GOOGLE_AI_STUDIO_KEY"),
    "ollama": ("OLLAMA_API_KEY", "OLLAMA_KEY", "OLAMA_API_KEY", "OLLAMA_API", "OLLAMA_TOKEN", "OLLAMA", "OLAMA_API",
               "OLAMA"),
}

EVENTS = ["policy", "inflation", "growth", "earnings", "flows", "geopolitics", "commodities", "currency", "regulation",
          "global_markets", "ratings", "corporate", "market_recap", "general"]

READ_SCHEMA = {
    "type": "object",
    "properties": {"reads": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "nifty": {"type": "number"}, "banknifty": {"type": "number"},
                       "confidence": {"type": "number"}, "event": {"type": "string", "enum": EVENTS},
                       "why": {"type": "string"}},
        "required": ["id", "nifty", "banknifty", "confidence", "event", "why"],
        "additionalProperties": False}}},
    "required": ["reads"],
    "additionalProperties": False,
}

READ_SYSTEM = """You read market news for an intraday NIFTY / BANKNIFTY options desk in India.

For each headline, judge its likely effect on each index over the next 30-60 minutes after it was published:
a number from -1 (strongly bearish) to +1 (strongly bullish), 0 when the headline carries no new information for the
index. Most headlines deserve a value near 0; reserve |x| > 0.5 for clear, surprising, index-moving news.

Judge it the way an experienced Indian equity derivatives trader would:
- Against expectations, not levels: inflation above the forecast is bearish even if it fell; a rate cut that was
  fully expected moves little.
- Signs for Indian equities: crude, US yields, the dollar and a weaker rupee rising are bearish; FII buying,
  falling crude, rate cuts and strong domestic data are bullish.
- Banks drive BANKNIFTY (HDFC Bank, ICICI Bank, SBI, Kotak, Axis); NIFTY is broader (Reliance, Infosys, TCS, ITC,
  L&T too). A story about one heavyweight moves its index by roughly its weight.
- A recap of the market's own move ("Sensex tumbles 700 points") is not news: 0, event market_recap.
- Speculation, previews, "may", "sources say" deserve less; say so in a lower confidence.

confidence: 0 to 1, how sure you are of the direction. why: at most 20 words."""

REFLECT_SCHEMA = {
    "type": "object",
    "properties": {"lessons": {"type": "array", "items": {"type": "string"}},
                   "watch_tomorrow": {"type": "array", "items": {"type": "string"}}},
    "required": ["lessons", "watch_tomorrow"],
    "additionalProperties": False,
}

REFLECT_SYSTEM = """You review one trading session of a paper-trading intraday options desk (NIFTY / BANKNIFTY, a
small account). You get the session review it wrote (its reads, trades and why) and the record of what it has learned
from grading its own calls.

Write the lessons a careful head trader would take from this session: what the desk read right or wrong and why,
whether its trades followed from its reads, what it missed, and what in its record deserves attention. Be specific to
this session (levels, times, setups, factors); no generic trading advice. At most 5 lessons of at most 40 words each,
and at most 3 things to watch at tomorrow's open. If the session is too thin to learn from, say that in one lesson."""


def key_for(provider: str) -> tuple[str | None, str | None]:
    """(the environment variable's name, its value) for a provider, or (None, None)."""
    for name in KEY_NAMES.get(provider, ()):
        v = os.environ.get(name, "").strip()
        if v:
            return name, v
    return None, None


def _clip(x, lo=-1.0, hi=1.0) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(lo, min(hi, x)) if x == x else 0.0


def _out_of_range(x, lo=-1.0, hi=1.0) -> bool:
    """A value a model gave that isn't a number in [lo, hi]: the read is malformed, not strong (G-03). Missing is fine."""
    if x is None:
        return False
    if isinstance(x, bool):                               # JSON true is not +1.0
        return True
    try:
        x = float(x)
    except (TypeError, ValueError):
        return True
    return not lo <= x <= hi                              # NaN fails both comparisons


def _payload(items: list[dict]) -> str:
    lines = [f'{it["id"]} | {it["ts"]} | {it["source"]} | {it["title"]}' + (f' — {it["summary"]}' if it.get("summary") else "")
             for it in items]
    return ("Headlines (id | published IST | source | title — summary). Return one read per id.\n\n" + "\n".join(lines))


JSON_SHAPE = ('\n\nAnswer with JSON only, no prose, exactly this shape: {"reads": [{"id": "<id>", "nifty": <-1..1>, '
              '"banknifty": <-1..1>, "confidence": <0..1>, "event": "<one of: ' + ", ".join(EVENTS) + '>", "why": "<≤20 words>"}]}')
_NUM = r"[^\d+\-−\n]{0,12}([+\-−]?\d*\.?\d+)"
_VIEW = _NUM + r"(?![\d.]*\s*(?:%|per\s*cent\b|percent\b|pct\b))"   # "fell 0.8%" / "0.8 per cent" is a move, not a view
_BANK = r"\b(?:bank[\s-]*nifty|nifty\s*bank)\b"                          # Bank Nifty, Bank-Nifty, Nifty Bank (NSE's name)
# "NIFTY 50"/"Nifty50" is the name; any spelling of Bank Nifty isn't NIFTY
_NIFTY = r"(?<!bank\s)(?<!bank\s\s)(?<!bank-)(?:\bnifty\s*50\b|\bnifty\b(?!\s*50\b))(?!\s*bank\b)"


def _parse_text_reads(text: str, ids: set) -> dict[str, dict]:
    """A model that ignored the JSON format and wrote "**t1** - NIFTY impact: +0.6 - BANKNIFTY …": read it anyway."""
    import re
    out = {}
    marks = sorted((m.start(), i) for i in ids for m in re.finditer(r"(?<!\w)" + re.escape(i) + r"(?!\w)", text or ""))
    for k, (pos, hid) in enumerate(marks):
        if hid in out:
            continue
        block = text[pos:marks[k + 1][0] if k + 1 < len(marks) else len(text)]
        def num(label, value=_NUM):
            m = re.search(label + value, block, re.I)
            return float(m.group(1).replace("−", "-")) if m else None
        n, b, c = num(_NIFTY, _VIEW), num(_BANK, _VIEW), num(r"\bconfidence\b")
        if n is None and b is None or _out_of_range(n) or _out_of_range(b) or _out_of_range(c, 0.0, 1.0):
            continue
        ev = re.search(r"\bevent\b[^a-z\n]{0,12}([a-z_]+)", block, re.I)
        why = re.search(r"\bwhy\b[^a-z\n]{0,12}(.+)", block, re.I)
        out[hid] = {"NIFTY": _clip(n), "BANKNIFTY": _clip(b), "confidence": _clip(c if c is not None else 0.5, 0.0, 1.0),
                    "event": ev.group(1).lower() if ev and ev.group(1).lower() in EVENTS else "general",
                    "why": (why.group(1).strip() if why else "")[:200]}
    return out


def _parse_reads(text: str, ids: set) -> dict[str, dict]:
    """Lenient: a JSON object with `reads`, or a bare list; unknown ids, junk and out-of-range numbers dropped. Prose
    with the numbers in it is read too (_parse_text_reads)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        s, e = (text or "").find("{"), (text or "").rfind("}")
        try:
            data = json.loads(text[s:e + 1]) if s >= 0 and e > s else {}
        except ValueError:
            data = {}
    rows = data.get("reads", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    out = {}
    for r in rows:
        if not isinstance(r, dict) or str(r.get("id")) not in ids:
            continue
        if _out_of_range(r.get("nifty")) or _out_of_range(r.get("banknifty")) or _out_of_range(r.get("confidence"), 0, 1):
            continue
        ev = r.get("event") if r.get("event") in EVENTS else "general"
        out[str(r["id"])] = {"NIFTY": _clip(r.get("nifty")), "BANKNIFTY": _clip(r.get("banknifty")),
                             "confidence": _clip(r.get("confidence"), 0.0, 1.0), "event": ev,
                             "why": str(r.get("why") or "")[:200]}
    # a read for a known id that was dropped doesn't come back as prose; JSON without one (an example, a wrong key) is
    # no read, so the prose is still read
    known = any(isinstance(r, dict) and str(r.get("id")) in ids for r in rows)
    return out if known else _parse_text_reads(text or "", ids)


# ---- the Claude credit ---------------------------------------------------------------------------------------------
BUDGET_KEY = "llm_claude_spend"                             # journal state: {total_usd, by_day, calls, sessions_used, ...}
BUDGET_NOTE = ("daily Claude budget", "Claude credit")      # errors the desk files that aren't failures
EST_REFLECT, EST_MIN = 0.05, 0.02                           # $: a reflection before one has been priced; the least a call costs


def usage_usd(u, p: dict) -> float:
    """What one response's `usage` cost, $ per million tokens in `p`. The API reports input_tokens without the cached
    tokens (cache_read_input_tokens and cache_creation_input_tokens are separate), and output_tokens includes thinking."""
    g = (lambda k: (u.get(k) if isinstance(u, dict) else getattr(u, k, 0)) or 0)
    return (g("input_tokens") * p["in"] + g("output_tokens") * p["out"] + g("cache_read_input_tokens") * p["cr"]
            + g("cache_creation_input_tokens") * p["cw"]) / 1e6


class ClaudeBudget:
    """A hard-capped, paced credit for Claude (intraday.llm.claude.budget_usd; 0 = no budget, no limit). The ledger lives
    in the journal so a restart, the 12:20 hand-over and tomorrow's session all see it. Today's allowance is the
    credit left at the start of the day over the sessions left, minus a reflection's cost held back for the close."""

    def __init__(self, cfg, journal=None, clock=None):
        c = cfg.get("intraday.llm.claude", {}) or {}
        self.usd = float(c.get("budget_usd", 0) or 0)
        self.start = str(c.get("budget_start", "") or "")[:10]
        self.sessions = max(1, int(c.get("budget_sessions", 60) or 60))
        self.reserve = bool(c.get("reserve_reflection", True))
        pin = float(c.get("price_in", 4.0))
        self.p = {"in": pin, "out": float(c.get("price_out", 20.0)), "cr": float(c.get("price_cache_read", pin / 10)),
                  "cw": float(c.get("price_cache_write", pin * 1.25))}
        self.j, self.clock, self.lock = journal, clock or (lambda: pd.Timestamp.now(tz=IST)), threading.RLock()
        self._mem: dict = {}

    @property
    def enabled(self) -> bool:
        return self.usd > 0

    def _load(self) -> dict:
        """The ledger, validated: a non-dict state, or a field of the wrong type, degrades to its default. Never raises."""
        try:
            st = (self.j.get_state(BUDGET_KEY) if self.j is not None else self._mem) or {}
        except Exception:
            st = {}
        st = st if isinstance(st, dict) else {}
        num = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None
        nums = lambda d: {str(k): x for k, v in d.items() if (x := num(v)) is not None} if isinstance(d, dict) else {}
        txt = lambda v: v if isinstance(v, str) else None
        return {"total_usd": max(0.0, num(st.get("total_usd")) or 0.0), "by_day": nums(st.get("by_day")),
                "calls": max(0, int(num(st.get("calls")) or 0)), "sessions_used": max(0, int(num(st.get("sessions_used")) or 0)),
                "day": txt(st.get("day")), "last": nums(st.get("last")), "reflected": txt(st.get("reflected")),
                "closed": st.get("closed") is True}

    def _save(self, st: dict) -> None:
        if self.j is not None:
            self.j.set_state(BUDGET_KEY, st)
        else:
            self._mem = st

    def _day(self, st: dict) -> str:
        day = str(self.clock().date())
        if day >= self.start and st["day"] != day:          # a session is used the first time it is looked at
            st["day"], st["sessions_used"] = day, st["sessions_used"] + 1
        return day

    def _est(self, st: dict, kind: str) -> float:
        return float((st["last"] or {}).get(kind) or (EST_REFLECT if kind == "reflect" else 0.0))

    def allowance(self, st: dict, day: str) -> float:
        """Today's: what was left when the day began over the sessions left (today's included)."""
        began = self.usd - st["total_usd"] + float(st["by_day"].get(day, 0))
        # never more than twice the even pace: once the sessions run out (or past) the divisor stops at 1, which would
        # otherwise hand over everything left in a single day
        return min(max(0.0, began) / max(1, self.sessions - max(0, st["sessions_used"] - 1)), 2 * self.usd / self.sessions)

    def _close(self, st: dict) -> None:
        if not st["closed"] and self.usd - st["total_usd"] < EST_MIN:
            st["closed"] = True
            if self.j is not None:
                self.j.event(self.clock(), "INFO", "llm", f"Claude credit used up (${self.usd:.2f}); the desk continues on "
                             "Gemini/Ollama and keeps everything learned", {"total_usd": round(st["total_usd"], 4)})

    def deny(self, kind: str):
        """None to go ahead; else why not: a note for the review, or '' to stay quiet (not started, used up)."""
        if not self.enabled:
            return None
        with self.lock:
            st = self._load()
            before = json.dumps(st, sort_keys=True, default=str)
            day, why = self._day(st), None
            self._close(st)
            left = self.usd - st["total_usd"]
            if day < self.start or st["closed"]:
                why = ""
            elif left < self._est(st, kind):
                why = f"Claude credit nearly used (${left:.2f} left)"
            elif kind == "read":
                spent = float(st["by_day"].get(day, 0))
                hold = self._est(st, "reflect") if self.reserve and st["reflected"] != day else 0.0
                allow = self.allowance(st, day)
                if spent + self._est(st, "read") > allow - hold + 1e-9:
                    why = f"daily Claude budget reached (${spent:.2f} of ${allow:.2f} today)"
            if json.dumps(st, sort_keys=True, default=str) != before:
                self._save(st)
            return why

    def charge(self, usage, kind: str) -> float:
        """Price one response's usage and add it to the ledger; returns the cost."""
        cost = usage_usd(usage, self.p)
        if not self.enabled:
            return cost
        with self.lock:
            st = self._load()
            day = self._day(st)
            st["total_usd"] = round(st["total_usd"] + cost, 6)
            st["by_day"][day] = round(float(st["by_day"].get(day, 0)) + cost, 6)
            st["by_day"] = dict(sorted(st["by_day"].items())[-200:])
            st["calls"] += 1
            st["last"] = {**(st["last"] or {}), kind: cost}
            if kind == "reflect":
                st["reflected"] = day
            self._close(st)
            self._save(st)
        return cost

    def line(self) -> str:
        """'Claude: $0.31 today, $4.20 of $20.00 used, ~52 sessions left at this pace' for the review and the heartbeat."""
        if not self.enabled:
            return ""
        try:                                                # a display: whatever is wrong with the ledger, never raise
            with self.lock:
                st = self._load()
            day = str(self.clock().date())
            if st["closed"]:
                return f"Claude: credit used up (${st['total_usd']:.2f} of ${self.usd:.2f}); the desk runs on the other readers"
            if day < self.start:
                return f"Claude: starts {self.start}, ${self.usd:.2f} over {self.sessions} sessions"
            pace = st["total_usd"] / max(1, st["sessions_used"])
            left = (self.usd - st["total_usd"]) / pace if pace > 0 else max(0, self.sessions - st["sessions_used"])
            return (f"Claude: ${float(st['by_day'].get(day, 0)):.2f} today, ${st['total_usd']:.2f} of ${self.usd:.2f} used, "
                    f"~{left:.0f} sessions left at this pace")
        except Exception:
            return ""


# ---- providers ---------------------------------------------------------------------------------------------------
class ClaudeReader:
    """Claude through the official SDK. Low effort for headlines (thinking can't be off on Opus 5.5; effort keeps it
    short), structured output so every read parses, and server-side fallbacks so a declined request is re-run on
    Anthropic's recommended fallback model instead of failing."""
    name = "claude"

    def __init__(self, key: str, model: str = "claude-opus-5-5", effort: str = "low", timeout: float = 60.0,
                 client=None, budget: "ClaudeBudget | None" = None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=2)
        self.client, self.model, self.effort, self.budget = client, model, effort, budget
        self.usage = {"calls": 0, "in": 0, "out": 0, "cr": 0, "cw": 0}
        self.last_raw: dict = {}
        self.charge_error: str | None = None                # set when the ledger could not be charged for a read

    def _call(self, system: str, user: str, schema: dict, effort: str, max_tokens: int, kind: str = "read") -> str | None:
        r = self.client.beta.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        self.usage["calls"] += 1
        u = getattr(r, "usage", None)
        self.usage["in"] += int(getattr(u, "input_tokens", 0) or 0)
        self.usage["out"] += int(getattr(u, "output_tokens", 0) or 0)      # thinking is billed as output
        self.usage["cr"] += int(getattr(u, "cache_read_input_tokens", 0) or 0)
        self.usage["cw"] += int(getattr(u, "cache_creation_input_tokens", 0) or 0)
        if self.budget is not None:                         # the credit: priced from what the API says it billed
            try:
                self.budget.charge(u, kind)
                self.charge_error = None
            except Exception as exc:                        # the read was paid for: keep it, and say the spend is unledgered
                self.charge_error = f"spend not ledgered ({type(exc).__name__}: {str(exc)[:120]})"
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        self.last_raw = {"content": text[:600], "stop_reason": r.stop_reason}
        if r.stop_reason == "refusal":                      # the whole fallback chain declined: no read
            return None
        return text or None

    def read(self, items: list[dict]) -> dict[str, dict]:
        text = self._call(READ_SYSTEM, _payload(items), READ_SCHEMA, self.effort, 4000)
        return _parse_reads(text, {it["id"] for it in items}) if text else {}

    def reflect(self, review: str, record: list[str]) -> dict | None:
        user = ("Session review:\n\n" + review[:24000] + "\n\nWhat the desk has learned so far:\n"
                + ("\n".join(record) if record else "(nothing graded yet)"))
        text = self._call(REFLECT_SYSTEM, user, REFLECT_SCHEMA, "medium", 6000, "reflect")
        try:
            d = json.loads(text) if text else None
        except ValueError:
            return None
        if not isinstance(d, dict):
            return None
        return {"lessons": [str(x)[:400] for x in d.get("lessons", [])][:5],
                "watch_tomorrow": [str(x)[:300] for x in d.get("watch_tomorrow", [])][:3]}


class GeminiReader:
    """Google's Gemini through its REST API (generateContent, JSON response)."""
    name = "gemini"
    base = "https://generativelanguage.googleapis.com/v1beta"

    FALLBACK = ("gemini-flash-latest", "gemini-3-flash-preview", "gemini-flash-lite-latest", "gemini-2.5-flash-lite",
                "gemini-pro-latest", "gemma-4-31b-it", "gemini-2.5-flash")

    def __init__(self, key: str, model: str = "gemini-flash-latest", timeout: float = 45.0, session=None):
        import requests
        self.key, self.model, self.timeout = key, model, timeout
        self.http = session or requests.Session()
        self.usage = {"calls": 0, "in": 0, "out": 0}
        self.last_raw: dict = {}

    def read(self, items: list[dict]) -> dict[str, dict]:
        body = {"systemInstruction": {"parts": [{"text": READ_SYSTEM}]},
                "contents": [{"role": "user", "parts": [{"text": _payload(items) + JSON_SHAPE}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
        tried = []
        for m in (self.model,) + tuple(x for x in self.FALLBACK if x != self.model):
            for attempt in (0, 1):                          # a busy model gets one more try after a second
                r = self.http.post(f"{self.base}/models/{m}:generateContent", json=body, timeout=self.timeout,
                                   headers={"x-goog-api-key": self.key})
                code = getattr(r, "status_code", 200)
                if code not in (429, 500, 503) or attempt:
                    break
                time.sleep(1.0)
            tried.append(f"{m} {code}")
            if code not in (404, 429, 500, 503):            # retired (404s while still listed) or busy (503, 3 Oct
                self.model = m                              # 2026): try the next model
                break
        self.last_raw = {"tried": tried}
        r.raise_for_status()
        d = r.json()
        self.usage["calls"] += 1
        um = d.get("usageMetadata") or {}
        self.usage["in"] += int(um.get("promptTokenCount") or 0)
        self.usage["out"] += int(um.get("candidatesTokenCount") or 0)
        parts = ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        self.last_raw = {"tried": tried, "content": text[:600], "finish": ((d.get("candidates") or [{}])[0]).get("finishReason")}
        return _parse_reads(text, {it["id"] for it in items})

    def models(self) -> list[str]:
        r = self.http.get(f"{self.base}/models", timeout=self.timeout, headers={"x-goog-api-key": self.key})
        r.raise_for_status()
        return [m["name"].split("/", 1)[-1] for m in r.json().get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]


class OllamaReader:
    """An Ollama model (Ollama's cloud with an API key, or a local server) through its chat API with a JSON schema."""
    name = "ollama"

    def __init__(self, key: str | None, model: str = "gpt-oss:120b", host: str = "https://ollama.com",
                 timeout: float = 90.0, session=None):
        import requests
        self.key, self.model, self.host, self.timeout = key, model, host.rstrip("/"), timeout
        self.http = session or requests.Session()
        self.usage = {"calls": 0, "in": 0, "out": 0}
        self.last_raw: dict = {}

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    def read(self, items: list[dict]) -> dict[str, dict]:
        body = {"model": self.model, "stream": False, "format": READ_SCHEMA, "options": {"temperature": 0.2, "num_predict": 4096},
                "messages": [{"role": "system", "content": READ_SYSTEM}, {"role": "user", "content": _payload(items) + JSON_SHAPE}]}
        r = self.http.post(f"{self.host}/api/chat", json=body, timeout=self.timeout, headers=self._headers())
        r.raise_for_status()
        d = r.json()
        self.usage["calls"] += 1
        self.usage["in"] += int(d.get("prompt_eval_count") or 0)
        self.usage["out"] += int(d.get("eval_count") or 0)
        m = d.get("message") or {}
        text = m.get("content") or ""
        if not text.strip() and "{" in (m.get("thinking") or ""):   # some reasoning models answer in the thinking field
            text = m["thinking"]
        self.last_raw = {"content": (m.get("content") or "")[:600], "thinking_chars": len(m.get("thinking") or ""),
                         "done_reason": d.get("done_reason")}
        return _parse_reads(text, {it["id"] for it in items})

    def models(self) -> list[str]:
        r = self.http.get(f"{self.host}/api/tags", timeout=self.timeout, headers=self._headers())
        r.raise_for_status()
        return [m.get("name") or m.get("model") for m in r.json().get("models", [])]


def make_readers(cfg) -> list:
    """Every provider that's enabled in the config and has a key in the environment."""
    lc = cfg.get("intraday.llm", {}) or {}
    if not lc.get("enabled", True):
        return []
    out = []
    for name in lc.get("readers", ["claude", "gemini", "ollama"]):
        pc = lc.get(name, {}) or {}
        _, key = key_for(name)
        if not key and not (name == "ollama" and pc.get("host", "").startswith("http://")):
            continue
        try:
            if name == "claude":
                out.append(ClaudeReader(key, pc.get("model", "claude-opus-5-5"), pc.get("effort", "low")))
            elif name == "gemini":
                out.append(GeminiReader(key, pc.get("model", "gemini-flash-latest")))
            elif name == "ollama":
                out.append(OllamaReader(key, pc.get("model", "gpt-oss:120b"), pc.get("host", "https://ollama.com")))
        except Exception as exc:                            # e.g. the SDK isn't installed: that reader is absent
            log.warning("llm reader %s unavailable: %s", name, exc)
    return out


# ---- the desk: batches, a budget, a background thread --------------------------------------------------------------
class LLMDesk:
    """Queues headlines for every reader and hands back reads as they arrive. `sync=True` reads inline (tests)."""

    def __init__(self, cfg, readers: list | None = None, sync: bool = False, clock=None, journal=None):
        lc = cfg.get("intraday.llm", {}) or {}
        self.readers = make_readers(cfg) if readers is None else readers
        self.batch = int(lc.get("batch", 12))
        self.max_calls = int(lc.get("max_calls_per_day", 40))
        self.min_relevance = float(lc.get("min_relevance", 2.0))
        self.sync = sync
        self.clock = clock or (lambda: pd.Timestamp.now(tz=IST))
        # with a journal, Claude is held to its credit (ClaudeBudget); without one (replays, tests) it is as before
        self.budget = (ClaudeBudget(cfg, journal, self.clock)
                       if journal is not None and any(r.name == "claude" for r in self.readers) else None)
        if self.budget is not None and not self.budget.enabled:
            self.budget = None
        for r in self.readers:
            if r.name == "claude" and self.budget is not None:
                r.budget = self.budget
        self.calls: dict[str, int] = {}
        self.day: dt.date | None = None
        self.errors: dict[str, str] = {}
        self._in: queue.Queue = queue.Queue()
        self._out: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self.seen: set = set()

    @property
    def active(self) -> bool:
        return bool(self.readers)

    def submit(self, items, now) -> int:
        """Queue the headlines worth a second read (about an index, not a recap); returns how many were queued."""
        if not self.readers:
            return 0
        want = [x for x in items if x.id not in self.seen and not x.recap
                and max(x.about.get("NIFTY", 0), x.about.get("BANKNIFTY", 0)) >= self.min_relevance]
        for x in want:
            self.seen.add(x.id)
        rows = [{"id": x.id, "ts": f"{pd.Timestamp(x.ts):%Y-%m-%d %H:%M}", "source": x.source, "title": x.title,
                 "summary": (x.summary or "")[:240]} for x in want]
        for i in range(0, len(rows), self.batch):
            chunk = rows[i:i + self.batch]
            if self.sync:
                self._work(chunk)
            else:
                self._in.put(chunk)
                self._ensure_thread()
        return len(rows)

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="llm-reader", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            chunk = self._in.get()
            try:
                self._work(chunk)
            except Exception as exc:                        # never let the thread die
                log.warning("llm desk: %s", exc)

    def _work(self, chunk: list[dict]) -> None:
        today = self.clock().date()
        if today != self.day:
            self.day, self.calls = today, {}
        for r in self.readers:
            if self.calls.get(r.name, 0) >= self.max_calls:
                self.errors[r.name] = f"daily cap of {self.max_calls} calls reached"
                continue
            if r.name == "claude" and self.budget is not None:
                try:
                    why = self.budget.deny("read")          # '' = not started / credit used up: quiet, never an error
                except Exception as exc:                    # can't check the credit: no Claude call, the others carry on
                    self.errors[r.name] = f"budget check failed: {type(exc).__name__}: {str(exc)[:120]}"
                    continue
                if why is not None:
                    if why:
                        self.errors[r.name] = why
                    continue
                if str(self.errors.get(r.name, "")).startswith(BUDGET_NOTE):
                    del self.errors[r.name]
            self.calls[r.name] = self.calls.get(r.name, 0) + 1
            try:
                reads = r.read(chunk)
            except Exception as exc:
                self.errors[r.name] = f"{type(exc).__name__}: {str(exc)[:160]}"
                continue
            at = self.clock()
            for hid, rd in reads.items():
                self._out.put((hid, r.name, {**rd, "at": str(at)}))
            if getattr(r, "charge_error", None):
                self.errors[r.name] = r.charge_error

    def drain(self) -> list[tuple[str, str, dict]]:
        out = []
        while True:
            try:
                out.append(self._out.get_nowait())
            except queue.Empty:
                return out

    def usage(self) -> dict:
        return {r.name: dict(r.usage) for r in self.readers}

    def wait(self, timeout: float = 30.0) -> None:
        """Until the queue is empty (the end of a session or a test)."""
        end = time.time() + timeout
        while not self._in.empty() and time.time() < end:
            time.sleep(0.05)


def cost_line(usage: dict, prices: dict) -> str:
    """'claude 12 calls, 31k in / 9k out ≈ $0.31; gemini 12 calls …' with prices in $ per million tokens."""
    parts = []
    for name, u in usage.items():
        if not u.get("calls"):
            continue
        p = prices.get(name) or {}
        usd = (u["in"] * float(p.get("in", 0)) + u["out"] * float(p.get("out", 0)) + u.get("cr", 0) * float(p.get("cr", 0))
               + u.get("cw", 0) * float(p.get("cw", 0))) / 1e6
        parts.append(f"{name} {u['calls']} calls, {u['in'] / 1000:.0f}k in / {u['out'] / 1000:.0f}k out"
                     + (f" (+{u['cr'] / 1000:.0f}k cached)" if u.get("cr") else "") + (f" ≈ ${usd:.2f}" if p else ""))
    return "; ".join(parts)
