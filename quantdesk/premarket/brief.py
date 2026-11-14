"""Assemble the pre-market brief from the universe, the calendar, history, global cues and headlines.

Everything here is a pure function of its inputs (the network fetches live in `sources.py`), so a brief can be
rebuilt for any past morning from the same files, and every number in it says where it came from.

The watch-list is the desk deciding what to read: every F&O underlying gets a score from reasons it can state
(results today, a reaction day, options cheap or rich against the company's own history, headlines, a futures OI
shift, liquidity), and the recording plan spends Kite's own subscription budget (3,000 instruments per connection)
on the names in that order: the brief sets no cap of its own. The plan is advisory: no recorder reads it yet.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..intraday import events as EV
from . import history as H
from . import universe as U

IST = "Asia/Kolkata"
CLOSE = dt.time(15, 30)
MIN_EVENTS = 3                                   # past calendar results a company needs before any comparison
OI_SHIFT = 0.10                                  # |futures OI change| over yesterday's OI that counts as a shift
KITE_TOKENS_PER_CONNECTION, KITE_CONNECTIONS = 3000, 3
EXPIRY_NOTE = ("Exploratory, NIFTY/BANKNIFTY 2019-2026 bhavcopy, options picked with what is known at the open (3 Nov "
               "2026): a near-money option closed at 3x its open on 20% of expiry symbol-sessions against 9% of others, "
               "but buying near-money options at the open on an expiry day lost 31% to 49% on average before costs. "
               "Lottery tickets, not an edge.")
RESULTS_NOTE = ("Exploratory, F&O results meetings of Oct 2026 (n = 119 to 151 by measure): the stock moved about twice as far "
                "as usual (median 3.3% from D-1 to D+1 against 1.6%), and options priced more too. An ATM straddle bought at "
                "D-1's close and sold at D+1's had a median of -10.8% and a mean of +2.5% before costs, against +1.3% for "
                "the control: the difference is not significant (t 0.3), and both lose after a 4% round trip. The label "
                "compares the move the options price today with the company's own past results moves (NSE's calendar "
                "only), and names cheap or rich only when the gap is outside what a fairly priced company would show by "
                "chance 90% of the time with that few events. A hypothesis, not a tested rule.")
WORDS_NOT_NAMES = {"IDEA", "POWER", "STEEL", "BANK", "INDIA", "INDIAN", "STATE", "NATIONAL", "UNITED", "GROUP", "CAPITAL",
                   "FINANCE", "ENERGY", "MOTORS", "LIFE", "HOUSING", "GAS", "OIL", "TATA", "BAJAJ", "ADANI", "HINDUSTAN",
                   "MAHINDRA", "BHARAT", "GODREJ", "AVENUE", "TRENT", "JUBILANT", "MAX", "ABB", "PAGE"}


def _f(x, nd=4):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(v) else round(v, nd)


def next_session(now: pd.Timestamp, holidays=()) -> dt.date:
    """The session this brief is for: today until the close, else the next weekday that is not a holiday."""
    now = pd.Timestamp(now)
    now = now.tz_localize(IST) if now.tzinfo is None else now.tz_convert(IST)
    d = now.date() if now.time() < CLOSE else now.date() + dt.timedelta(days=1)
    hol = {pd.Timestamp(h).date() for h in holidays}
    while d.weekday() >= 5 or d in hol:
        d += dt.timedelta(days=1)
    return d


@dataclass
class Inputs:
    now: pd.Timestamp
    stock_opts: pd.DataFrame | None = None
    index_bhav: pd.DataFrame | None = None
    corp_events: pd.DataFrame | None = None
    index_close: pd.DataFrame | None = None
    implied: pd.DataFrame | None = None           # history.atm_implied of stock_opts (computed when None)
    history: pd.DataFrame | None = None           # history.results_history (computed when None)
    macro_events: list = field(default_factory=list)   # intraday.events.Event, from config calendar.events
    holidays: tuple = ()
    globals_: list | None = None                  # [{key, name, last, change}] from sources.fetch_globals
    headlines: list | None = None                 # [{ts, source, title, link}] from sources.fetch_headlines
    health: dict = field(default_factory=dict)    # source -> "ok ..." / "fail ..."
    tails: dict | None = None                     # tailrisk.build: each paper underlying's conditional EVT model (quantdesk/paper/tails.py)
    news_analogs: dict | None = None              # analogs.build: each paper underlying's past episodes of each kind, weighted by today's situation


def _company_aliases(corp_events: pd.DataFrame | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if corp_events is None or len(corp_events) == 0 or "company" not in corp_events:
        return out
    for sym, name in corp_events.dropna(subset=["company"]).drop_duplicates("symbol")[["symbol", "company"]].itertuples(index=False):
        clean = re.sub(r"\b(limited|ltd\.?|\(india\)|india limited)\s*$", "", str(name), flags=re.I).strip(" .,")
        al = [clean] if len(clean) >= 4 else []
        first = clean.split()[0] if clean.split() else ""
        if len(first) >= 6 and first.upper() not in WORDS_NOT_NAMES:
            al.append(first)
        out[str(sym)] = al
    return out


def match_headlines(headlines: list | None, symbols: list[str], aliases: dict[str, list[str]]) -> dict[str, list[dict]]:
    """symbol -> headlines that name it (the symbol itself, 5+ letters and not an ordinary word, or the company's name)."""
    if not headlines:
        return {}
    pats = {}
    for s in symbols:
        terms = [a for a in aliases.get(s, [])]
        if len(s) >= 5 and s.isalpha() and s.upper() not in WORDS_NOT_NAMES:
            terms.append(s)
        if terms:
            pats[s] = re.compile(r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b", re.I)
    out: dict[str, list[dict]] = {}
    for h in headlines:
        title = str(h.get("title", ""))
        for s, p in pats.items():
            if p.search(title):
                out.setdefault(s, []).append({k: h.get(k) for k in ("ts", "source", "title", "link")})
    return out


def _results_rows(inp: Inputs, day: dt.date, last_close: pd.Timestamp, implied: pd.DataFrame, hist: pd.DataFrame,
                  sessions: list) -> list[dict]:
    c = H.results_meetings(inp.corp_events)
    if c.empty:
        return []
    c["date"] = pd.to_datetime(c["date"]).dt.date
    fo = set(implied["symbol"]) if len(implied) else set()
    rows = []
    for r in c[c["symbol"].isin(fo)].itertuples():
        if r.date == day:
            when = "results today (board meeting; NSE does not say whether in or after market hours)"
        elif last_close.date() <= r.date < day:
            when = "reaction day: results came at or after the last close"
        else:
            continue
        imp = implied[(implied["symbol"] == r.symbol) & (implied["date"] <= last_close)].sort_values("date")
        if imp.empty:
            continue
        a = imp.iloc[-1]
        prev = imp.iloc[-2] if len(imp) >= 2 else None
        crushed = prev is not None and prev["expiry"] == a["expiry"] and a["iv"] / prev["iv"] - 1 <= H.CRUSH
        typ = (imp["spot"] / imp["spot"].shift() - 1).abs().iloc[-21:-1].median()
        jumped = prev is not None and typ == typ and typ > 0 and abs(a["spot"] / prev["spot"] - 1) >= H.JUMP * typ
        ivb = H.base_iv(implied, r.symbol, a["date"], sessions, event=pd.Timestamp(r.date))
        iem = _f(H.event_implied_move(a["iv"], ivb, a["dte"]))
        priced = _f(H.priced_abs_move(iem if iem is not None else float("nan"), ivb))
        prof = {k: (_f(v) if isinstance(v, float) else v) for k, v in H.profile(hist, r.symbol, sources=("calendar",)).items()}
        inferred = {k: (_f(v) if isinstance(v, float) else v) for k, v in H.profile(hist, r.symbol, sources=("inferred",)).items()}
        n, mean = prof.get("n", 0), prof.get("mean_move")
        ratio = mean / priced if priced and mean is not None and n else float("nan")
        band = H.chance_band(n) if n >= MIN_EVENTS else None
        more = f" ({inferred['n']} more inferred from the data, biased toward big moves)" if inferred.get("n") else ""
        if crushed and jumped:
            label, why = "already out", "implied volatility collapsed and the stock jumped at the last close: the result is probably already in the price"
        elif priced is None:
            label, why = "no implied move", ("no clean pre-event IV window (an expiry ending before the event, sessions 30 to 10 back) "
                                             "or no traded at-the-money straddle")
        elif n < MIN_EVENTS:
            label, why = "no history", f"{n} past results on NSE's calendar: too few to compare{more}"
        elif ratio >= band[1]:
            label, why = "cheap", (f"options price an expected move of {priced:.1%}; its past results moves averaged {mean:.1%} ({n} events), "
                                   f"above the {band[1]:.2f}x a fairly priced company reaches by chance")
        elif ratio <= band[0]:
            label, why = "rich", (f"options price an expected move of {priced:.1%}; its past results moves averaged {mean:.1%} ({n} events), "
                                  f"below the {band[0]:.2f}x a fairly priced company falls to by chance")
        else:
            label, why = "within chance", (f"options price {priced:.1%}; its past results moves averaged {mean:.1%} ({n} events): "
                                           f"{ratio:.2f}x, inside the {band[0]:.2f}x to {band[1]:.2f}x a fairly priced company shows by chance")
        if iem == 0 and label not in ("already out",):
            why += " (options price no event premium above the stock's normal IV)"
        rows.append({"symbol": r.symbol, "company": getattr(r, "company", None), "meeting": r.date.isoformat(), "when": when,
                     "spot": _f(a["spot"], 2), "expiry": pd.Timestamp(a["expiry"]).date().isoformat(), "dte": int(a["dte"]),
                     "implied_move_to_expiry": _f(a["move"]), "iv": _f(a["iv"]), "iv_normal": _f(ivb), "event_implied_move": iem,
                     "priced_abs_move": priced, "past": prof, "past_inferred": inferred, "move_over_priced": _f(ratio, 2),
                     "chance_band": [round(band[0], 2), round(band[1], 2)] if band else None, "label": label, "why": why})
    order = {"cheap": 0, "rich": 1, "within chance": 2, "no history": 3, "no implied move": 4, "already out": 5}
    return sorted(rows, key=lambda x: (order[x["label"]], -(x["move_over_priced"] or 0)))


def _macro(inp: Inputs, day: dt.date, last_close: dt.date) -> list[dict]:
    book = EV.EventBook(list(inp.macro_events))
    dates = H.macro_dates()
    mh = H.macro_history(inp.index_close, dates)
    out = []
    since = book.since_last_close(day, last_close)
    for e, rel in [(e, "since the last close") for e in since] + [(e, "today") for e in book.on(day) if e not in since]:
        kind = H.kind_of(e.name)
        spec = dates["kinds"].get(kind, {}) if kind else {}
        out.append({"name": e.name, "time": e.time.strftime("%H:%M") if e.time else None, "when": rel,
                    "in_session": e.in_session and rel == "today", "kind": kind, "history": mh.get(kind, {}),
                    "evidence": spec.get("evidence")})
    return out


def _analogs(inp: Inputs) -> dict:
    """{kind: {symbol: {n, median_move, median_ret, share_down, worst, median_5d, ...}}} for every kind in macro_dates.json (geopolitics and oil shocks included)."""
    try:
        return H.macro_history(inp.index_close, H.macro_dates())
    except Exception:                                                   # noqa: BLE001 - no analogue table is a thinner brief, never a failed one
        return {}


def _calendar(inp: Inputs, now: pd.Timestamp, expiring: list, results: list) -> list[dict]:
    """The scheduled-events calendar (quantdesk/paper/eventcal.py): the owner's dates, the recurring releases by rule, today's expiries and results."""
    from ..paper import eventcal as EC
    try:
        cfg_events = [(e.day, e.time, e.name) for e in inp.macro_events or [] if getattr(e, "source", "calendar") == "calendar"]
        return EC.build(now.to_pydatetime(), cfg_events, days=7, expiring=expiring, results=results)
    except Exception:                                                   # noqa: BLE001 - no calendar is a thinner brief, never a failed one
        return []


def _expiries(index_bhav: pd.DataFrame | None, day: dt.date) -> list[dict]:
    if index_bhav is None or len(index_bhav) == 0:
        return []
    b = index_bhav[index_bhav["kind"].isin(["CE", "PE"])]
    ex = pd.to_datetime(b["expiry"]).dt.date
    return [{"symbol": s, "note": EXPIRY_NOTE} for s in sorted(b.loc[ex == day, "symbol"].unique())]


def _watch(univ: pd.DataFrame, results: list[dict], news: dict, expiring: set) -> list[dict]:
    res = {r["symbol"]: r for r in results}
    out = []
    for u in univ.itertuples():
        score, why = 0.0, []
        if u.segment == "index":
            score += 5
            why.append("index" + (" (options expire today)" if u.symbol in expiring else ""))
        r = res.get(u.symbol)
        if r:
            today = r["when"].startswith("results today")
            score += 4 if today else 3
            why.append("results today" if today else "reacts today to results after the last close")
            if r["label"] == "cheap":
                score += 2
                why.append("options cheap against its own results history")
            elif r["label"] == "rich":
                score += 1
                why.append("options rich against its own results history (a seller's look)")
        n = news.get(u.symbol, [])
        if n:
            score += min(len(n), 2)
            why.append(f"in the news: {n[0]['title'][:90]}")
        if u.fut_oi_chg_pct == u.fut_oi_chg_pct and abs(u.fut_oi_chg_pct) >= OI_SHIFT:
            score += 1
            why.append(f"futures OI {'rose' if u.fut_oi_chg_pct > 0 else 'fell'} {abs(u.fut_oi_chg_pct):.0%} yesterday")
        lr = u.liq_rank if u.liq_rank == u.liq_rank else 0.0
        score += 2 * lr
        if lr >= 0.9:
            why.append("among the most traded options")
        if u.segment == "stock" and u.active_strikes < 5:
            score -= 2
            why.append("thin options (fewer than 5 active strikes)")
        out.append({"symbol": u.symbol, "segment": u.segment, "score": round(score, 2), "why": why,
                    "price": _f(u.price, 2), "lot": _f(u.lot, 0), "strike_step": _f(u.strike_step, 2),
                    "opt_premium_cr": _f(u.opt_premium_cr, 2), "active_strikes": int(u.active_strikes),
                    "fut_oi_chg_pct": _f(u.fut_oi_chg_pct, 3)})
    return sorted(out, key=lambda x: -x["score"])


def record_plan(watch: list[dict], tokens: int = KITE_TOKENS_PER_CONNECTION * KITE_CONNECTIONS) -> dict:
    """Spend Kite's subscription budget down the watch-list: indices get 20 strikes a side on two expiries, the top 50
    other names 10 a side, the next 5, the rest 2 (each name also takes its cash and future)."""
    left, plan = tokens, []
    for i, w in enumerate(watch):
        if w["segment"] == "index":
            k, ex = 20, 2
        else:
            rank = sum(1 for x in watch[:i] if x["segment"] != "index")
            k, ex = (10 if rank < 50 else 5 if rank < 120 else 2), 1
        need = 2 + ex * 2 * (2 * k + 1)
        if need > left:
            k = max(0, (left - 2) // (ex * 2) // 2 - 1) if left > 2 + ex * 2 else 0
            need = 2 + ex * 2 * (2 * k + 1) if k else 2
            if need > left:
                break
        left -= need
        plan.append({"symbol": w["symbol"], "strikes_each_side": int(k), "expiries": ex, "tokens": int(need)})
    return {"budget": tokens, "used": tokens - left, "names": len(plan), "of": len(watch), "plan": plan}


def build(inp: Inputs) -> dict:
    now = pd.Timestamp(inp.now)
    now = now.tz_localize(IST) if now.tzinfo is None else now.tz_convert(IST)
    day = next_session(now, inp.holidays)
    so = inp.stock_opts if inp.stock_opts is not None else pd.DataFrame()
    univ = U.fo_universe(so if len(so) else None, inp.index_bhav)
    implied = inp.implied if inp.implied is not None else H.atm_implied(so)
    sessions = H.sessions_of(implied) if len(implied) else []
    last_close = pd.Timestamp(max(sessions)) if sessions else pd.Timestamp(now.date())
    hist = inp.history
    if hist is None:
        cal = H.results_calendar(inp.corp_events, sessions, symbols=set(implied["symbol"]) if len(implied) else None)
        hist = H.results_history(so, implied, cal, H.inferred_results(implied))
    results = _results_rows(inp, day, last_close, implied, hist, sessions) if len(implied) else []
    macro = _macro(inp, day, last_close.date())
    expiring = _expiries(inp.index_bhav, day)
    aliases = _company_aliases(inp.corp_events)
    news = match_headlines(inp.headlines, list(univ["symbol"]) if len(univ) else [], aliases)
    watch = _watch(univ, results, news, {e["symbol"] for e in expiring}) if len(univ) else []
    stale = (pd.Timestamp(day) - last_close.normalize()).days > 4
    brief = {
        "generated_at": now.isoformat(timespec="seconds"), "session": day.isoformat(), "last_close": last_close.date().isoformat(),
        "data_stale": bool(stale),
        "universe": {"indices": int((univ["segment"] == "index").sum()) if len(univ) else 0,
                     "stocks": int((univ["segment"] == "stock").sum()) if len(univ) else 0},
        "expiring": expiring, "macro": macro, "results": results, "results_note": RESULTS_NOTE,
        "analogs": _analogs(inp),                                       # what NIFTY and BANKNIFTY did on past episodes of each kind (the news analyser's "what happened before")
        "tails": inp.tails or {},                                       # extreme value theory: each paper underlying's tail model (AUTO v2's tail check reads it)
        "news_analogs": inp.news_analogs or {},                         # every instrument's own past episodes, most like today first (the news model reads it)
        "calendar": _calendar(inp, now, expiring, results),             # the scheduled events of the next week, each with the instruments it touches (paper/eventcal.py)
        "global": inp.globals_ or [], "headlines": {"total": len(inp.headlines or []), "named": {k: v[:3] for k, v in news.items()}},
        "watch": watch, "record_plan": record_plan(watch) if watch else {"budget": 0, "used": 0, "names": 0, "of": 0, "plan": []},
        "history": {"events": int(len(hist)), "calendar": int((hist["source"] == "calendar").sum()) if len(hist) else 0,
                    "inferred": int((hist["source"] == "inferred").sum()) if len(hist) else 0,
                    "from": str(pd.Timestamp(hist["event"].min()).date()) if len(hist) else None,
                    "to": str(pd.Timestamp(hist["event"].max()).date()) if len(hist) else None},
        "health": inp.health,
        "not_for": "context only: places nothing, sizes nothing; labels are untested hypotheses",
    }
    brief["summary"] = summary(brief)
    return brief


def summary(b: dict) -> list[str]:
    s = [f"Session {pd.Timestamp(b['session']):%a %d %b %Y}; last close {b['last_close']}"
         + (" (data is stale: check the warehouse)" if b["data_stale"] else "") + "."]
    if b["expiring"]:
        s.append(f"Options expire today: {', '.join(e['symbol'] for e in b['expiring'])}.")
    if b["macro"]:
        s.append("Macro: " + "; ".join(f"{m['name']}{' at ' + m['time'] if m['time'] else ''} ({m['when']})" for m in b["macro"]) + ".")
    else:
        s.append("Macro: nothing scheduled.")
    if b["results"]:
        lab = pd.Series([r["label"] for r in b["results"]]).value_counts().to_dict()
        s.append(f"Results: {len(b['results'])} F&O companies report today or react today ("
                 + ", ".join(f"{v} {k}" for k, v in lab.items()) + ").")
    g = [x for x in b["global"] if x.get("change") is not None]
    if g:
        s.append("Overnight: " + ", ".join(f"{x['name']} {x['change']:+.1%}" for x in g[:6]) + ".")
    nxt = [e for e in b.get("calendar") or [] if e.get("impact") in ("high", "medium") and e.get("source") != "brief"][:4]
    if nxt:
        s.append("Coming up: " + "; ".join(f"{e['name']} {pd.Timestamp(e['at']):%a %d %b %H:%M}" + (" (by rule: check)" if e.get("source") == "rule" else "") for e in nxt) + ".")
    from .tailrisk import summary_line
    tl = summary_line(b.get("tails") or {})
    if tl:
        s.append(tl)
    top = [w for w in b["watch"] if w["segment"] == "stock"][:5]
    if top:
        s.append("Watch first: " + "; ".join(f"{w['symbol']} ({', '.join(w['why'][:2])})" for w in top) + ".")
    return s


def to_markdown(b: dict) -> str:
    L = [f"# Pre-market brief: {pd.Timestamp(b['session']):%a %d %b %Y}", "", f"_Generated {b['generated_at']}. {b['not_for']}._", ""]
    L += [f"- {x}" for x in b["summary"]] + [""]
    if b["expiring"]:
        L += ["## Expiry today", "", EXPIRY_NOTE, ""]
    if b["macro"]:
        L += ["## Macro events", ""]
        for m in b["macro"]:
            L.append(f"**{m['name']}**{' at ' + m['time'] + ' IST' if m['time'] else ''} ({m['when']})")
            for sym, h in (m["history"] or {}).items():
                L.append(f"- {sym}: {h['n']} past sessions, median move {h['median_move']:.2%} (all sessions {h['median_move_all']:.2%}); "
                         f"moved >1% on {h['share_over_1pct']:.0%} (all {h['share_over_1pct_all']:.0%})")
            if m.get("evidence"):
                L.append(f"- {m['evidence']}")
            L.append("")
    if b["results"]:
        L += ["## Results", "", RESULTS_NOTE, "",
              "| Stock | When | Priced expected move | Past mean move (NSE calendar) | Events | Ratio | Chance band | Inferred (biased up) | Label |",
              "|---|---|---|---|---|---|---|---|---|"]
        for r in b["results"]:
            p, q, band = r["past"], r.get("past_inferred") or {}, r.get("chance_band")
            L.append(f"| {r['symbol']} | {r['when'].split(':')[0].split(' (')[0]} | {_pct(r['priced_abs_move'])} | "
                     f"{_pct(p.get('mean_move'))} | {p.get('n', 0)} | {r['move_over_priced'] if r['move_over_priced'] is not None else '-'} | "
                     f"{f'{band[0]}-{band[1]}' if band else '-'} | {q.get('n', 0)} ({_pct(q.get('mean_move'))}) | {r['label']} |")
        L += [""] + [f"- **{r['symbol']}**: {r['why']}" for r in b["results"]]
        L.append("")
    if b["global"]:
        L += ["## Overnight", ""] + [f"- {x['name']}: {_pct(x.get('change'), signed=True)}" for x in b["global"]] + [""]
    L += ["## Watch-list (the desk's own ranking, every F&O underlying)", "", "| # | Symbol | Score | Why |", "|---|---|---|---|"]
    for i, w in enumerate(b["watch"][:40], 1):
        L.append(f"| {i} | {w['symbol']} | {w['score']:.1f} | {'; '.join(w['why']) or '-'} |")
    rp = b["record_plan"]
    L += ["", f"Recording plan: {rp['names']} of {rp['of']} names fit Kite's budget of {rp['budget']} instruments "
              f"({rp['used']} used). Advisory: the recorders do not read it yet.", ""]
    if b["health"]:
        L += ["## Sources", ""] + [f"- {k}: {v}" for k, v in b["health"].items()]
    return "\n".join(L) + "\n"


def _pct(x, signed=False):
    return "-" if x is None or x != x else (f"{x:+.1%}" if signed else f"{x:.1%}")


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, (pd.Timestamp, dt.date)):
        return o.isoformat()
    return o
