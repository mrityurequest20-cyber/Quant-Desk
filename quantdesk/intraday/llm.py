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

Keys come from the environment, never from files, and are never printed (`key_for` returns the variable's name for
reports). Each provider accepts a few common names for its variable, so a repository secret works under any of them.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
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


def _payload(items: list[dict]) -> str:
    lines = [f'{it["id"]} | {it["ts"]} | {it["source"]} | {it["title"]}' + (f' — {it["summary"]}' if it.get("summary") else "")
             for it in items]
    return ("Headlines (id | published IST | source | title — summary). Return one read per id.\n\n" + "\n".join(lines))


JSON_SHAPE = ('\n\nAnswer with JSON only, no prose, exactly this shape: {"reads": [{"id": "<id>", "nifty": <-1..1>, '
              '"banknifty": <-1..1>, "confidence": <0..1>, "event": "<one of: ' + ", ".join(EVENTS) + '>", "why": "<≤20 words>"}]}')
_NUM = r"[^\d+\-−\n]{0,12}([+\-−]?\d*\.?\d+)"


def _parse_text_reads(text: str, ids: set) -> dict[str, dict]:
    """A model that ignored the JSON format and wrote "**t1** - NIFTY impact: +0.6 - BANKNIFTY …": read it anyway."""
    import re
    out = {}
    marks = sorted((m.start(), i) for i in ids for m in re.finditer(r"(?<!\w)" + re.escape(i) + r"(?!\w)", text or ""))
    for k, (pos, hid) in enumerate(marks):
        if hid in out:
            continue
        block = text[pos:marks[k + 1][0] if k + 1 < len(marks) else len(text)]
        def num(label):
            m = re.search(label + _NUM, block, re.I)
            return float(m.group(1).replace("−", "-")) if m else None
        n, b = num(r"\bnifty\b"), num(r"\bbank ?nifty\b")
        if n is None and b is None:
            continue
        ev = re.search(r"\bevent\b[^a-z\n]{0,12}([a-z_]+)", block, re.I)
        why = re.search(r"\bwhy\b[^a-z\n]{0,12}(.+)", block, re.I)
        out[hid] = {"NIFTY": _clip(n), "BANKNIFTY": _clip(b), "confidence": _clip(num(r"\bconfidence\b") or 0.5, 0.0, 1.0),
                    "event": ev.group(1).lower() if ev and ev.group(1).lower() in EVENTS else "general",
                    "why": (why.group(1).strip() if why else "")[:200]}
    return out


def _parse_reads(text: str, ids: set) -> dict[str, dict]:
    """Lenient: a JSON object with `reads`, or a bare list; unknown ids and junk dropped, numbers clipped. Prose
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
        ev = r.get("event") if r.get("event") in EVENTS else "general"
        out[str(r["id"])] = {"NIFTY": _clip(r.get("nifty")), "BANKNIFTY": _clip(r.get("banknifty")),
                             "confidence": _clip(r.get("confidence"), 0.0, 1.0), "event": ev,
                             "why": str(r.get("why") or "")[:200]}
    return out or _parse_text_reads(text or "", ids)


# ---- providers ---------------------------------------------------------------------------------------------------
class ClaudeReader:
    """Claude through the official SDK. Low effort for headlines (thinking can't be off on Opus 5.5; effort keeps it
    short), structured output so every read parses, and server-side fallbacks so a declined request is re-run on
    Anthropic's recommended fallback model instead of failing."""
    name = "claude"

    def __init__(self, key: str, model: str = "claude-opus-5-5", effort: str = "low", timeout: float = 60.0,
                 client=None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=2)
        self.client, self.model, self.effort = client, model, effort
        self.usage = {"calls": 0, "in": 0, "out": 0}
        self.last_raw: dict = {}

    def _call(self, system: str, user: str, schema: dict, effort: str, max_tokens: int) -> str | None:
        r = self.client.beta.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        self.usage["calls"] += 1
        u = getattr(r, "usage", None)
        self.usage["in"] += int(getattr(u, "input_tokens", 0) or 0)
        self.usage["out"] += int(getattr(u, "output_tokens", 0) or 0)
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
        text = self._call(REFLECT_SYSTEM, user, REFLECT_SCHEMA, "medium", 6000)
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

    def __init__(self, cfg, readers: list | None = None, sync: bool = False, clock=None):
        lc = cfg.get("intraday.llm", {}) or {}
        self.readers = make_readers(cfg) if readers is None else readers
        self.batch = int(lc.get("batch", 12))
        self.max_calls = int(lc.get("max_calls_per_day", 40))
        self.min_relevance = float(lc.get("min_relevance", 2.0))
        self.sync = sync
        self.clock = clock or (lambda: pd.Timestamp.now(tz=IST))
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
            self.calls[r.name] = self.calls.get(r.name, 0) + 1
            try:
                reads = r.read(chunk)
            except Exception as exc:
                self.errors[r.name] = f"{type(exc).__name__}: {str(exc)[:160]}"
                continue
            at = self.clock()
            for hid, rd in reads.items():
                self._out.put((hid, r.name, {**rd, "at": str(at)}))

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
        usd = u["in"] / 1e6 * float(p.get("in", 0)) + u["out"] / 1e6 * float(p.get("out", 0))
        parts.append(f"{name} {u['calls']} calls, {u['in'] / 1000:.0f}k in / {u['out'] / 1000:.0f}k out"
                     + (f" ≈ ${usd:.2f}" if p else ""))
    return "; ".join(parts)
