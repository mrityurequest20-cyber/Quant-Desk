"""The news model (owner, 13 Nov 2026: "The news analyser must be sophisticated that it understand past and present situations well so that it can accurately predict the
future, it should [read] each and everything which can impact our vision. Models should read differently as per the instrument as these instruments are different").
PAPER MONEY ONLY; nothing here trades.

A story moves instruments through CHANNELS, not only by naming them. "Brent jumps 6% after Gulf strikes" names no Indian instrument, yet it moves crude up, the rupee
down (USD/INR up), the indices down, and gold up. The model reads each story in three steps:

1. SUBJECTS. Which economic variables it is about (crude, gold, the rupee, the dollar, US yields, the Fed, the RBI, inflation, growth, foreign flows, geopolitics, tariffs,
   China, Wall Street, the monsoon, sector news ...), from its words (SUBJECTS).
2. DIRECTION. Which way it says each one is going: "crude jumps" is crude UP; "rupee hits record low" is the rupee DOWN; "RBI cuts repo" is rates DOWN; "ceasefire" is
   geopolitical risk DOWN. Read from the direction words nearest the subject's own word (direction()).
3. CHANNELS. How each instrument responds to each subject moving up (CHANNELS: a signed sensitivity per instrument or group, with the reason). The sum over stories, each
   weighted by its impact, novelty and age, is the instrument's CHANNEL SCORE: different for every instrument, from the same news.

Then the PAST: for the events under way (the digest's event watch), the pre-market brief has measured, for EACH instrument, what it did on past episodes of the same kind,
weighting each episode by how much the market then resembled the market now (premarket/analogs.py: trend, volatility regime, drawdown). Their weighted share of up days is
a second piece of evidence, worth more the more (effective) episodes there were.

The two combine as log-odds into P(up) for the instrument (forecast()); P >= VOTE_P is a vote in AUTO v2's view (one vote: it never trades alone). Every forecast is SCORED
against what the price did over the next HORIZON_S (Brier score; calibration()), per instrument, so the desk can see whether its news reading is worth anything.

The sensitivities are PRIORS written from how these markets are known to transmit shocks (an oil importer's currency and indices, a safe haven, rate-sensitive lenders,
exporters' rupee exposure), not fitted: the Brier record is what will say which hold. Standard library only (paper package rules).
"""
from __future__ import annotations

import datetime as dt
import functools
import math
import re

INDEX = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
GROUPS = {
    "INDEX": INDEX,
    "BANKS": ("HDFCBANK", "SBIN", "ICICIBANK", "AXISBANK", "KOTAKBANK", "BANKNIFTY", "FINNIFTY"),
    "NBFC": ("BAJFINANCE", "FINNIFTY"),
    "IT": ("TCS", "INFY"),
    "AUTO": ("MARUTI", "BAJAJ-AUTO", "M&M"),
    "PHARMA": ("DIVISLAB", "LAURUSLABS"),
    "CRUDE": ("CRUDEOIL", "CRUDEOILM"),
    "GAS": ("NATURALGAS", "NATGASMINI"),
    "GOLD": ("GOLD", "GOLDM"),
    "SILVER": ("SILVER", "SILVERM"),
    "INR_PAIRS": ("USDINR", "EURINR", "GBPINR", "JPYINR"),
}

# subject -> words that name it. Direction words are read near these.
SUBJECTS = {
    "crude": r"crude|brent|wti|oil price|oil prices|opec\+?|oil output|oil supply",
    "natgas": r"natural gas|lng|henry hub",
    "gold": r"gold",
    "silver": r"silver",
    "metals": r"copper|aluminium|aluminum|zinc|base metals?|lme|metal prices?",
    "rupee": r"rupee|inr",
    "dollar": r"dollar index|dxy|greenback|the dollar|us dollar",
    "us_yields": r"treasury yields?|us yields?|bond yields?|10-year yield",
    "fed": r"fed|fomc|federal reserve|powell",
    "rbi": r"rbi|repo rate|repo|mpc|reserve bank",
    "inflation": r"inflation|cpi|wpi|consumer prices?|price index",
    "growth": r"gdp|pmi|iip|industrial output|industrial production|economic growth|core sector|payrolls|jobs report",
    "fii": r"fiis?|fpis?|foreign investors?|foreign funds?|foreign portfolio",
    "geopolitics": r"war|missiles?|air ?strikes?|drone strikes?|military|attack|invasion|troops|border clash\w*|ceasefire|truce|peace talks?|sanctions?",
    "tariffs": r"tariffs?|trade war|trade deal|trade talks|import duty|export curbs?",
    "china": r"china|chinese|beijing",
    "wall_street": r"wall street|s&p 500|s&p|nasdaq|dow jones|us stocks|us markets?",
    "monsoon": r"monsoon|rainfall|kharif",
    "it_spend": r"it services|tech spending|deal wins?|h-1b|visa fee|outsourcing",
    "auto_sales": r"auto sales|vehicle sales|car sales|two-wheeler sales|passenger vehicle",
    "usfda": r"usfda|us fda|fda",
    "telecom": r"telecom tariffs?|mobile tariffs?|arpu|spectrum",
    "fno_rules": r"f&o|derivatives? (?:rules|curbs|norms|trading)|sebi .*?(?:curbs?|norms)|expiry (?:rules|curbs)|weekly expir\w+",
    "fintech_rules": r"payments? bank|fintech|paytm|upi (?:rules|curbs|cap)",
    "bad_loans": r"bad loans|npas?|asset quality|loan defaults?|slippages?",
    "capex": r"capex|infrastructure spending|defence orders?|railway orders?|power projects?|order book",
    "electronics": r"smartphones?|electronics manufacturing|pli scheme|mobile manufacturing",
    "cigarettes": r"cigarettes?|tobacco",
}
_SUBJ = {k: re.compile(rf"\b(?:{v})\b", re.I) for k, v in SUBJECTS.items()}

UP_WORDS = (r"above normal|surplus|surges?|soars?|jumps?|rises?|rising|rose|rall(?:y|ies|ied)|gains?|climbs?|spikes?|hikes?|hiked|raises?|raised|higher|record high|highs?|strengthens?|firms?"
            r"|boosts?|beats?|accelerat\w+|expands?|expansion|escalat\w+|intensif\w+|attacks?|strikes?|invad\w+|imposes?|tightens?|tighter|tougher|upbeat|robust|strong|"
            r"buy(?:s|ing)?|bought|inflows?|approv\w+|win(?:s)?|won|tops?|up\b")
DOWN_WORDS = (r"below normal|deficient|falls?|fell|drops?|dropped|slumps?|plunges?|crash\w*|slides?|declines?|eases?|easing|cuts?|lower|weakens?|weak|record low|lows?|slips?|tumbles?|"
              r"contracts?|contraction|miss(?:es)?|ceasefire|truce|peace|de-?escalat\w+|calm|warning letter|rejects?|rejection|sell(?:s|ing)?|sold|outflows?|loosens?|relax\w*|"
              r"rolls? back|scraps?|slow(?:s|down|ing)?|down\b")
_UP, _DOWN = re.compile(rf"\b(?:{UP_WORDS})", re.I), re.compile(rf"\b(?:{DOWN_WORDS})", re.I)
DE_ESCALATION = re.compile(r"\b(?:ceasefire|truce|peace|talks?|de-?escalat\w+|deal|accord)\b", re.I)

# subject -> [(instrument or GROUP, sensitivity to the subject going UP, why)]
CHANNELS = {
    "crude": [("CRUDE", 1.0, "it is crude"), ("GAS", 0.3, "energy moves together"), ("INR_PAIRS", 0.3, "a dearer import bill weakens the rupee"),
              ("INDEX", -0.3, "India imports most of its oil"), ("MIDCPNIFTY", -0.1, "costs"), ("AUTO", -0.2, "fuel costs and demand"), ("RELIANCE", 0.1, "refining margins")],
    "natgas": [("GAS", 1.0, "it is natural gas")],
    "gold": [("GOLD", 1.0, "it is gold"), ("SILVER", 0.5, "precious metals move together")],
    "silver": [("SILVER", 1.0, "it is silver"), ("GOLD", 0.3, "precious metals move together")],
    "metals": [("COPPER", 1.0, "base metals"), ("SILVER", 0.3, "industrial demand")],
    "rupee": [("INR_PAIRS", -1.0, "a stronger rupee is a lower rupee price of the currency"), ("IT", -0.3, "exporters earn in dollars"), ("INDEX", 0.1, "foreign flows")],
    "dollar": [("USDINR", 0.6, "a stronger dollar"), ("EURINR", -0.3, "the euro falls against the dollar"), ("GBPINR", -0.3, "sterling falls against the dollar"),
               ("JPYINR", -0.3, "the yen falls against the dollar"), ("GOLD", -0.4, "gold is priced in dollars"), ("SILVER", -0.4, "priced in dollars"),
               ("COPPER", -0.2, "priced in dollars"), ("CRUDE", -0.2, "priced in dollars"), ("IT", 0.2, "dollar earnings")],
    "us_yields": [("INDEX", -0.3, "money leaves emerging markets"), ("USDINR", 0.4, "outflows weaken the rupee"), ("GOLD", -0.4, "a higher return on cash"),
                  ("IT", -0.1, "US tech valuations")],
    "fed": [("INDEX", -0.4, "tighter US money"), ("USDINR", 0.5, "the dollar strengthens"), ("GOLD", -0.5, "a higher return on cash"), ("SILVER", -0.4, "the same"),
            ("IT", -0.2, "US demand")],
    "rbi": [("INDEX", -0.3, "dearer money"), ("BANKS", -0.3, "loan growth and bond losses"), ("NBFC", -0.5, "their borrowing costs"), ("AUTO", -0.4, "car loans"),
            ("USDINR", -0.3, "higher rates hold the rupee up")],
    "inflation": [("INDEX", -0.3, "rate hikes ahead"), ("BANKS", -0.2, "rates"), ("GOLD", 0.2, "a hedge"), ("USDINR", 0.2, "a weaker currency")],
    "growth": [("INDEX", 0.4, "earnings"), ("BANKS", 0.3, "credit demand"), ("AUTO", 0.3, "demand"), ("BHEL", 0.3, "capex"), ("COPPER", 0.3, "industrial demand"),
               ("CRUDE", 0.2, "fuel demand"), ("USDINR", -0.2, "inflows")],
    "fii": [("INDEX", 0.5, "foreign buying"), ("BANKS", 0.4, "their favourite sector"), ("USDINR", -0.4, "dollars coming in")],
    "geopolitics": [("INDEX", -0.6, "risk off"), ("MIDCPNIFTY", -0.6, "risk off, harder"), ("BANKS", -0.3, "risk off"), ("GOLD", 0.6, "the safe haven"),
                    ("SILVER", 0.3, "a lesser haven"), ("CRUDE", 0.5, "supply risk"), ("USDINR", 0.5, "the dollar is the haven"), ("JPYINR", 0.3, "the yen is a haven"),
                    ("DIXON", -0.2, "supply chains")],
    "tariffs": [("INDEX", -0.3, "trade"), ("IT", -0.3, "US clients"), ("COPPER", -0.4, "industrial demand"), ("CRUDE", -0.3, "demand"), ("GOLD", 0.3, "uncertainty"),
                ("USDINR", 0.3, "risk off")],
    "china": [("COPPER", 0.6, "the largest buyer"), ("CRUDE", 0.3, "demand"), ("SILVER", 0.2, "industrial demand")],
    "wall_street": [("INDEX", 0.4, "global risk"), ("IT", 0.4, "US tech")],
    "monsoon": [("M&M", 0.5, "tractors and rural demand"), ("AUTO", 0.3, "rural demand"), ("ITC", 0.2, "rural demand"), ("INDEX", 0.1, "consumption")],
    "it_spend": [("IT", 0.8, "their revenue")],
    "auto_sales": [("AUTO", 0.8, "their volumes")],
    "usfda": [("PHARMA", 0.6, "US approvals")],
    "telecom": [("BHARTIARTL", 0.8, "revenue per user")],
    "fno_rules": [("BSE", -0.8, "derivatives volumes are its revenue"), ("INDEX", -0.1, "liquidity")],
    "fintech_rules": [("PAYTM", -0.8, "its licence and business")],
    "bad_loans": [("BANKS", -0.6, "provisions"), ("NBFC", -0.5, "provisions")],
    "capex": [("BHEL", 0.6, "its orders"), ("INDEX", 0.1, "investment")],
    "electronics": [("DIXON", 0.6, "its orders")],
    "cigarettes": [("ITC", -0.8, "a tax on cigarettes is a tax on its profit")],
}
# subjects whose words are themselves a direction (a story about F&O rules is about tightening them, a story about bad loans is about more of them) unless it says otherwise
DEFAULT_UP = frozenset({"geopolitics", "tariffs", "fno_rules", "fintech_rules", "bad_loans", "cigarettes"})

IMPACT_W = {"high": 1.0, "medium": 0.5, "low": 0.2}
HALF_LIFE_MIN = 120
MAX_AGE_S = 6 * 3600
W_CHANNEL, CH_SCALE = 1.5, 1.0        # the channel score enters as W * tanh(score / scale)
W_ANALOG, ANALOG_N0 = 1.0, 4.0        # an analogue's log-odds, weighted by n_eff / (n_eff + n0)
VOTE_P = 0.65
HORIZON_S = 3600                      # a forecast is scored against the next hour


def members(target: str) -> tuple:
    return GROUPS.get(target, (target,))


def sensitivity(u: str, subject: str) -> list[tuple[float, str]]:
    """[(sensitivity, why)] of instrument `u` to `subject` going up (a group and a member can both apply: their sum is the instrument's)."""
    return [(s, why) for target, s, why in CHANNELS.get(subject, ()) if u in members(target)]


def direction(title: str, m: re.Match, subject: str) -> int:
    """+1 / -1 / 0: the direction word nearest the subject's own word (either side, within 60 characters), or the subject's default."""
    if subject == "geopolitics" and DE_ESCALATION.search(title):
        return -1
    best, dist = 0, 61
    for rx, sgn in ((_UP, 1), (_DOWN, -1)):
        for w in rx.finditer(title):
            if w.start() <= m.start() < w.end():
                continue
            d = (m.start() - w.end()) if w.end() <= m.start() else (w.start() - m.end())
            if 0 <= d < dist:
                best, dist = sgn, d
    if best == 0 and subject in DEFAULT_UP:
        return 1
    return best


@functools.lru_cache(maxsize=4096)
def subjects(title: str) -> tuple[tuple[str, int], ...]:
    """((subject, direction), ...) a headline is about (cached: a story is read once, not once per instrument per cycle)."""
    return tuple(_subjects(title))


def _subjects(title: str) -> list[tuple[str, int]]:
    t = str(title or "")
    out = []
    for name, rx in _SUBJ.items():
        m = rx.search(t)
        if m:
            out.append((name, direction(t, m, name)))
    if any(n == "rupee" for n, _ in out):                    # "the rupee falls against the dollar": the dollar is where the rupee is measured from, not a second story
        out = [(n, d) for n, d in out if n != "dollar"]
    return out


def _ts(x) -> float | None:
    try:
        return dt.datetime.strptime(str(x), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        return None


def channel_score(digest, u: str, t: float) -> tuple[float, list[str]]:
    """(the instrument's channel score, its strongest reasons). Each story counts by impact x novelty x half-life decay; recaps do not count."""
    items = digest.get("items") if isinstance(digest, dict) and isinstance(digest.get("items"), list) else []
    score, parts = 0.0, []
    for it in items:
        if not isinstance(it, dict) or it.get("recap") is True:
            continue
        ts = _ts(it.get("ts"))
        if ts is None or not (0 <= t - ts <= MAX_AGE_S):
            continue
        nov = it.get("novelty")
        w = IMPACT_W.get(it.get("impact"), 0.2) * max(0.2, float(nov) if isinstance(nov, (int, float)) else 0.5) * 0.5 ** ((t - ts) / 60 / HALF_LIFE_MIN)
        title = str(it.get("title") or "")
        syms = it.get("symbols") if isinstance(it.get("symbols"), list) else []
        if u in syms:                                                                    # the story names the instrument: its own tone
            tone = it.get("tone")
            if isinstance(tone, (int, float)) and -1 <= tone <= 1 and tone:
                score += w * tone
                parts.append((abs(w * tone), f"named: {title[:70]}"))
        for subj, d in subjects(title):
            if not d:
                continue
            for s, why in sensitivity(u, subj):
                x = w * d * s
                score += x
                parts.append((abs(x), f"{subj.replace('_', ' ')} {'up' if d > 0 else 'down'} ({why}): {title[:60]}"))
    parts.sort(key=lambda p: -p[0])
    return score, [p[1] for p in parts[:3]]


def touches(u: str, event: dict) -> float:
    """How strongly a digest event (event watch) bears on `u`: the largest |sensitivity| over the subjects of its top stories."""
    best = 0.0
    for title in event.get("top") or []:
        for subj, _ in subjects(title):
            for s, _ in sensitivity(u, subj):
                best = max(best, abs(s))
    return best


def analog_evidence(u: str, digest, analogs: dict | None) -> tuple[float, list[str]]:
    """(log-odds, reasons) from the past episodes of the kinds now under way, for this instrument (premarket/analogs.py), weighted by their effective number."""
    if not isinstance(analogs, dict):
        return 0.0, []
    lo, why = 0.0, []
    for ev in (digest.get("events") if isinstance(digest, dict) else None) or []:
        if not isinstance(ev, dict) or ev.get("level") not in ("high", "watch"):
            continue
        a = ((analogs.get(ev.get("kind")) or {}).get(u)) if ev.get("kind") else None
        if not isinstance(a, dict) or not isinstance(a.get("p_up"), (int, float)) or not isinstance(a.get("n_eff"), (int, float)):
            continue
        p = min(max(a["p_up"], 0.05), 0.95)
        k = a["n_eff"] / (a["n_eff"] + ANALOG_N0)
        lo += W_ANALOG * k * math.log(p / (1 - p))
        why.append(f"in {a.get('n', '?')} past {ev['kind']} episodes most like today (effective {a['n_eff']:.1f}), {u} rose {p * 100:.0f}% of the time"
                   + (f", median {a['median_ret'] * 100:+.1f}%" if isinstance(a.get("median_ret"), (int, float)) else ""))
    return lo, why


def forecast(u: str, digest, analogs: dict | None, t: float) -> dict:
    """{"p_up", "vote", "score", "why"}: the channel score (present) and the analogues (past) as log-odds."""
    sc, why_ch = channel_score(digest, u, t)
    lo_an, why_an = analog_evidence(u, digest, analogs)
    logit = W_CHANNEL * math.tanh(sc / CH_SCALE) + lo_an
    p = 1 / (1 + math.exp(-logit))
    return {"p_up": round(p, 3), "vote": 1 if p >= VOTE_P else -1 if p <= 1 - VOTE_P else 0, "score": round(sc, 3), "why": (why_ch + why_an)[:4]}


class Scorer:
    """Each forecast with an opinion (|P - 0.5| >= 0.05), at most one per instrument per quarter hour, scored against the price HORIZON_S later: the Brier score."""

    def __init__(self):
        self.pending: dict[str, list[tuple[float, float, float]]] = {}
        self.scored: dict[str, list[float]] = {}

    def add(self, u: str, t: float, p: float, price: float | None) -> None:
        q = self.pending.setdefault(u, [])
        while q and t - q[0][0] >= HORIZON_S:
            t0, p0, px0 = q.pop(0)
            if price and px0 and abs(price / px0 - 1) >= 0.001:
                y = 1.0 if price > px0 else 0.0
                n_se = self.scored.setdefault(u, [0, 0.0])
                n_se[0] += 1
                n_se[1] += (p0 - y) ** 2
        if price and abs(p - 0.5) >= 0.05 and (not q or t - q[-1][0] >= 900):
            q.append((t, p, price))

    def calibration(self) -> dict:
        out = {u: {"n": int(n), "brier": round(se / n, 4)} for u, (n, se) in self.scored.items() if n}
        n = sum(v[0] for v in self.scored.values())
        if n:
            out["all"] = {"n": int(n), "brier": round(sum(v[1] for v in self.scored.values()) / n, 4)}
        return out
