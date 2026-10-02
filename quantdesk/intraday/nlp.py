"""Headline NLP: what a story is, whom it moves, whether it surprises, how sure it is, and whether it is new.

The tone of a headline (news.sentiment) says which way the words lean. What moves an index is more specific, and
this module reads it from the text:

* **event type**: a policy decision persists for hours, a market recap carries no new information, a stock-specific
  result matters in proportion to the stock's weight. Each type has its own half-life and weight.
* **surprise against expectations**: "CPI at 5.4% vs 5.0% expected" is bearish whatever the level; "Q2 profit beats
  estimates" is bullish. Numbers are parsed from the text (actual vs expected / estimate / forecast / poll), signed by
  what the event means for Indian equities (inflation above expectations hurts, growth above helps), and scaled to
  [-1, 1]; qualitative beats/misses and policy moves (cut / hike / hold) count too.
* **entities**: index heavyweights mentioned in the text, as their approximate share of NIFTY and BANKNIFTY, so a
  story about HDFC Bank (about 28% of BANKNIFTY) weighs on BANKNIFTY in proportion.
* **certainty**: "may", "sources said", "likely", previews and questions are speculation, not reported fact.
* **novelty**: TF-IDF cosine against the day's earlier stories; the fifth retelling of a story isn't news
  (news.NewsDesk applies it as stories arrive).

Rule-based and deterministic: fast on a runner, no model download, every number explainable in the read.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

# ---- event types: pattern, half-life (min), weight. First match in this order wins. ---------------------------
EVENTS = [
    ("policy", r"\b(repo rate|reverse repo|monetary policy|mpc|rbi policy|policy rate|rate (?:cut|hike)s?|cuts? (?:interest )?rates?"
               r"|hikes? (?:interest )?rates?|raises? (?:interest )?rates?|fomc|fed (?:raises|cuts|holds|decision|chair)|crr|slr)\b", 180, 1.5),
    ("geopolitics", r"\b(war|missiles?|air ?strikes?|drone strikes?|military|ceasefire|border clash\w*|sanctions?|terror\w*|invasion|troops)\b", 240, 1.4),
    ("inflation", r"\b(inflation|cpi|wpi|consumer prices?|retail prices?|wholesale prices?|price index)\b", 120, 1.3),
    ("growth", r"\b(gdp|iip|industrial output|industrial production|pmi|core sector|payrolls|jobs report|unemployment|jobless"
               r"|economic growth|growth rate|fiscal deficit|current account)\b", 120, 1.2),
    ("regulation", r"\b(sebi|budget|stt|gst council|capital gains tax|regulator|circular|ban(?:s|ned)?|curbs?)\b", 180, 1.1),
    ("flows", r"\b(fiis?|fpis?|diis?|foreign (?:investors?|funds?|portfolio)|outflows?|inflows?|net (?:sold|bought|sellers?|buyers?))\b", 120, 1.0),
    ("commodities", r"\b(crude|brent|wti|oil prices?|opec\+?|gold prices?|metal prices?)\b", 120, 1.0),
    ("earnings", r"\b(q[1-4]|quarterly|net profit|profit|revenue|earnings|ebitda|margins?|guidance|results?)\b", 90, 1.0),
    ("currency", r"\b(rupee|dollar index|forex reserves?|usd/inr)\b", 90, 0.9),
    ("global", r"\b(wall street|s&p 500|s&p|nasdaq|dow jones|dow|nikkei|hang seng|global (?:markets|cues|stocks)|us stocks"
               r"|asian (?:markets|shares|stocks)|european (?:markets|shares|stocks))\b", 60, 0.8),
    ("ratings", r"\b(upgrades?d?|downgrades?d?|target price|outperform|underperform|overweight|underweight|credit rating)\b", 60, 0.8),
    ("corporate", r"\b(merger|acquisitions?|acquires?|stake|ipo|buyback|dividend|block deal|order win|contract)\b", 90, 0.7),
]
GENERAL = ("general", 45, 0.6)
RECAP = ("market_recap", 30, 0.4)
_EVENT_RE = [(n, re.compile(p), hl, w) for n, p, hl, w in EVENTS]

# what "higher than expected" means for Indian equities, per event (default +1)
HIGHER_IS = {"inflation": -1, "commodities": -1, "currency": -1}
INVERSE_WORDS = re.compile(r"\b(unemployment|jobless|deficit|yields?|outflows?|npas?|bad loans|slippages?)\b")

# ---- index heavyweights: approximate share of each index (2025-26); aliases → (NIFTY, BANKNIFTY) --------------
HEAVY = {
    "HDFC Bank": (("hdfc bank",), 0.13, 0.28),
    "ICICI Bank": (("icici bank",), 0.09, 0.25),
    "Reliance": (("reliance industries", "ril", r"reliance(?! (?:power|capital|infra\w*|communications|home|retail ventures))"), 0.085, 0.0),
    "Infosys": (("infosys", "infy"), 0.05, 0.0),
    "Bharti Airtel": (("bharti airtel", "airtel"), 0.045, 0.0),
    "L&T": (("larsen", "l&t"), 0.04, 0.0),
    "ITC": (("itc",), 0.035, 0.0),
    "TCS": (("tcs", "tata consultancy"), 0.03, 0.0),
    "Axis Bank": (("axis bank",), 0.03, 0.08),
    "SBI": (("sbi", "state bank of india", "state bank"), 0.03, 0.09),
    "Kotak Bank": (("kotak mahindra bank", "kotak bank"), 0.028, 0.08),
    "M&M": (("mahindra & mahindra", "mahindra and mahindra", "m&m"), 0.025, 0.0),
    "Bajaj Finance": (("bajaj finance",), 0.022, 0.0),
    "HUL": (("hindustan unilever", "hul"), 0.02, 0.0),
    "Sun Pharma": (("sun pharma",), 0.015, 0.0),
    "Maruti": (("maruti",), 0.015, 0.0),
    "HCL Tech": (("hcl tech", "hcltech", "hcl technologies"), 0.015, 0.0),
    "NTPC": (("ntpc",), 0.013, 0.0),
    "Tata Motors": (("tata motors",), 0.012, 0.0),
    "Titan": (("titan",), 0.012, 0.0),
    "Tata Steel": (("tata steel",), 0.011, 0.0),
    "IndusInd Bank": (("indusind",), 0.005, 0.03),
    "Bank of Baroda": (("bank of baroda",), 0.0, 0.03),
    "PNB": (("punjab national bank", "pnb"), 0.0, 0.025),
    "Federal Bank": (("federal bank",), 0.0, 0.025),
    "IDFC First": (("idfc first",), 0.0, 0.02),
    "AU Bank": (("au small finance", "au bank"), 0.0, 0.02),
    "Canara Bank": (("canara bank",), 0.0, 0.02),
}
_HEAVY_RE = {name: re.compile(r"\b(?:" + "|".join(a if "(" in a else re.escape(a) for a in aliases) + r")\b")
             for name, (aliases, _, _) in HEAVY.items()}

# ---- certainty -------------------------------------------------------------------------------------------------
SPECULATIVE = re.compile(r"\b(may|might|could|likely|unlikely|expected to|set to|poised to|plans? to|considering|mulls?|eyes"
                         r"|weighs?|seeks?|sources? (?:said|say|says)|reportedly|report says|rumou?rs?|speculation|preview"
                         r"|ahead of|what to expect|week ahead|outlook|to watch|could see|live updates?)\b")

# ---- surprise ----------------------------------------------------------------------------------------------------
_N = r"(?<![a-z\d.])(-?\d+(?:,\d{3})*(?:\.\d+)?)"      # not the 1 in "Q1"
_EXPECT = (r"(?:expected|expectations?|estimates?d?|forecasts?|consensus(?: estimate)?|polls?(?:ed)?(?: estimate)?"
           r"|street estimates?|analysts'? estimates?)")
VS = re.compile(rf"{_N}\s*(%|per ?cent|bps|basis points|crore|cr)?\s*,?\s*(?:vs\.?|versus|against|compared (?:with|to))\s*"
                rf"(?:an?\s+|the\s+)?{_EXPECT}\s*(?:of\s+|at\s+)?(?:rs\.?\s*|₹\s*)?{_N}")
EXPECT_THEN = re.compile(rf"{_EXPECT}\s*(?:of|at|was|were|had been)?\s*(?:rs\.?\s*|₹\s*)?{_N}\s*(%|per ?cent|bps|crore|cr)?")
ACTUAL = re.compile(rf"\b(?:at|to|of|stood at|came in at|rose to|fell to|eased to|climbed to|grew|grows|expanded|"
                    rf"contracted|rises to|falls to|eases to|jumps to|slows to|accelerates to)\s+(?:rs\.?\s*|₹\s*)?{_N}\s*(%|per ?cent|bps|crore|cr)?")
VS_AFTER = re.compile(rf"{_N}\s*(%|per ?cent|bps|basis points|crore|cr)?\s*,?\s*(?:vs\.?|versus|against)\s*(?:rs\.?\s*|₹\s*)?"
                      rf"{_N}\s*(?:%|per ?cent|bps|basis points|crore|cr)?\s*(?:expected|estimated|forecast|estimates?|in an? \w* ?poll)")
BEAT = re.compile(r"\b(beats?|beating|tops?|topped|surpass(?:es|ed)?|exceed(?:s|ed)?|above|ahead of|better than)\b(?:[^.;]|\.(?=\d)){0,30}?"
                  r"\b(estimates?|expectations?|forecasts?|consensus|street|expected)\b")
MISS = re.compile(r"\b(miss(?:es|ed)?|below|short of|falls? short|lags?|lagged|worse than|disappoints?|disappointed)\b(?:[^.;]|\.(?=\d)){0,30}?"
                  r"\b(estimates?|expectations?|forecasts?|consensus|street|expected)\b")
INLINE = re.compile(r"\bin line with\s+(?:estimates|expectations|forecasts|consensus)\b")
CUT = re.compile(r"\b(cuts?|lowers?|reduces?|slash(?:es|ed)?|trims?)\b(?:[^.;]|\.(?=\d)){0,25}\b(repo|rates?|policy rate|crr)\b")
HIKE = re.compile(r"\b(hikes?|raises?|increases?|lifts?)\b(?:[^.;]|\.(?=\d)){0,25}\b(repo|rates?|policy rate|crr)\b")
HOLD = re.compile(r"\b(keeps?|holds?|leaves?|maintains?)\b(?:[^.;]|\.(?=\d)){0,30}\b(repo|rates?|policy rate)\b(?:[^.;]|\.(?=\d)){0,20}\b(unchanged|steady|on hold)\b"
                  r"|\b(status quo|pauses?|on hold)\b")


def _num(x: str) -> float:
    return float(x.replace(",", ""))


@dataclass
class Reading:
    event: str = GENERAL[0]
    half_life: float = GENERAL[1]
    weight: float = GENERAL[2]
    certainty: float = 1.0
    surprise: float | None = None          # signed for Indian equities, [-1, 1]; None: no expectation in the text
    surprise_text: str = ""
    exposure: dict = field(default_factory=dict)   # {"NIFTY": share of the index named, "BANKNIFTY": …}
    names: list = field(default_factory=list)

    def to_record(self) -> dict:
        d = asdict(self)
        d["surprise"] = None if self.surprise is None else round(self.surprise, 3)
        d["exposure"] = {k: round(v, 3) for k, v in self.exposure.items()}
        return d


def event_of(text_l: str, recap: bool = False) -> tuple[str, float, float]:
    if recap:
        return RECAP
    for name, rx, hl, w in _EVENT_RE:
        if rx.search(text_l):
            return name, hl, w
    return GENERAL


def entities(text_l: str) -> tuple[list[str], dict]:
    names = [n for n, rx in _HEAVY_RE.items() if rx.search(text_l)]
    expo = {"NIFTY": min(1.0, sum(HEAVY[n][1] for n in names)), "BANKNIFTY": min(1.0, sum(HEAVY[n][2] for n in names))}
    return names, expo


def certainty(text_l: str) -> float:
    if SPECULATIVE.search(text_l):
        return 0.5
    if text_l.rstrip().endswith("?"):
        return 0.6
    return 1.0


def surprise(text_l: str, event: str) -> tuple[float | None, str]:
    """Signed surprise for Indian equities in [-1, 1] and the phrase it came from; (None, "") without one."""
    up = HIGHER_IS.get(event, 1) * (-1 if INVERSE_WORDS.search(text_l) else 1)
    m = VS.search(text_l) or VS_AFTER.search(text_l)
    actual = expected = None
    unit = ""
    if m:
        actual, unit, expected = _num(m.group(1)), (m.group(2) or ""), _num(m.group(3))
        phrase = m.group(0)
    else:
        e, a = EXPECT_THEN.search(text_l), None
        if e:
            for c in ACTUAL.finditer(text_l):
                if c.start() < e.start() or c.start() > e.end():
                    a = c
                    break
        if e and a:
            actual, expected, unit = _num(a.group(1)), _num(e.group(1)), (a.group(2) or e.group(2) or "")
            phrase = f"{a.group(0)} … {e.group(0)}"
    if actual is not None and expected is not None:
        diff = actual - expected
        pct_like = unit.strip() in ("%", "per cent", "percent") or (abs(expected) < 25 and "crore" not in unit and "cr" != unit.strip())
        scale = 0.3 if pct_like else max(abs(expected) * 0.05, 1e-9)           # 0.3 pp, or 5% of the expectation
        return float(max(-1.0, min(1.0, up * diff / scale))), phrase.strip()
    if INLINE.search(text_l):
        return 0.0, INLINE.search(text_l).group(0)
    b, s = BEAT.search(text_l), MISS.search(text_l)
    if b and not s:
        return float(up * 0.6), b.group(0)
    if s and not b:
        return float(-up * 0.6), s.group(0)
    if event == "policy":
        if HOLD.search(text_l):
            return 0.0, HOLD.search(text_l).group(0)
        c, h = CUT.search(text_l), HIKE.search(text_l)
        if c and not h:
            return 0.6, c.group(0)
        if h and not c:
            return -0.6, h.group(0)
    return None, ""


def read(text: str, recap: bool = False) -> Reading:
    t = " ".join(str(text or "").lower().split())
    ev, hl, w = event_of(t, recap)
    if ev == GENERAL[0] and (BEAT.search(t) or MISS.search(t)):           # "misses street estimates": a results story
        ev, _, hl, w = next(e for e in _EVENT_RE if e[0] == "earnings")
    names, expo = entities(t)
    s, phrase = surprise(t, ev) if not recap else (None, "")
    return Reading(ev, float(hl), float(w), certainty(t), s, phrase, expo, names)


# ---- novelty: TF-IDF cosine against earlier stories ---------------------------------------------------------------
STOP = set("a an the to of in on for and or as at is are was were be by with from its it this that after over amid into "
           "up down says said will new more than vs per cent percent rs crore".split())
_TOK = re.compile(r"[a-z][a-z0-9&'\-]+|\d+(?:\.\d+)?")


def terms(text: str) -> list[str]:
    return [w for w in _TOK.findall(str(text or "").lower()) if w not in STOP and len(w) > 1]


class Novelty:
    """Document frequencies over the stories seen so far, and each new story's highest cosine similarity to them."""

    def __init__(self):
        self.df: Counter = Counter()
        self.docs: list[tuple[str, Counter]] = []

    def _vec(self, tf: Counter) -> dict[str, float]:
        n = len(self.docs) + 1
        return {w: c * (math.log((n + 1) / (self.df.get(w, 0) + 1)) + 1) for w, c in tf.items()}

    def score(self, key: str, text: str) -> tuple[float, str | None]:
        """(novelty in [0, 1], the closest earlier story's key), then remember this one."""
        tf = Counter(terms(text))
        v = self._vec(tf)
        nv = math.sqrt(sum(x * x for x in v.values())) or 1.0
        best, best_key = 0.0, None
        for k, otf in self.docs:
            o = self._vec(otf)
            dot = sum(v[w] * o.get(w, 0.0) for w in v)
            if dot:
                cos = dot / (nv * (math.sqrt(sum(x * x for x in o.values())) or 1.0))
                if cos > best:
                    best, best_key = cos, k
        self.docs.append((key, tf))
        self.df.update(set(tf))
        return float(max(0.0, 1.0 - best)), best_key
