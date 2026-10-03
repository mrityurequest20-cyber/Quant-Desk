"""The desk learns from what it did: every call it made is graded against what the market did next.

* **News**: each headline's tone (and each language model's read, when one is configured) against the index's next
  30 minutes, by event type, by source and by reader (the rules, claude, gemini, ollama).
* **Evidence**: each factor in each journaled read (trend, structure, flow, options, news, global …) against the
  next 30 minutes. Reads are 5 minutes apart and the horizon is 30, so each counts 1/6 of an observation.
* **Setups**: each closed trade's R, by setup and by setup × day type.
* **Pre-break entries**: armed setups the EV gate turned down, replayed on the bars that followed (target or stop
  first, within the setup's time stop), so the desk can see whether waiting for confirmation is costing it.

What it learns changes the desk only through bounded multipliers on things it already weighs: a factor's or a news
type's weight (0.5×–1.5×) and a setup's conviction (0.6×–1.3×), each shrunk toward 1 until there's enough evidence
(a prior worth 20 observations), and a setup × day type with a clearly negative record (8+ trades, shrunk mean
below −0.3R) is stood aside from. One good or bad day can't swing it; a consistent record does.
The memory lives next to the journal (runtime/intraday/memory.json), so it carries from day to day.

Two research tables ride along (they change nothing by themselves; they're what the record says):
* **Factor IC by horizon**: each factor's direction against the index's move 5, 15, 30 and 60 minutes later, as a
  correlation (forward returns clipped at ±150 bps so one shock can't own it) with a t-stat on overlap-adjusted
  observations. A factor whose IC peaks at 60 minutes wants holding; one that peaks at 5 doesn't survive costs.
* **The buyer's edge**: each session's realised volatility (5-minute returns from the first live chain read to the
  close) against the ATM IV read then, and the session's move against the move that IV implied. A desk that only
  buys options needs realised to beat implied; over many sessions this says whether it does.
* **Relative-strength persistence** (relstrength.py): whether the index that led the other over the last 30 minutes
  leads over the next 30, from every 5-minute point of every whole session in the bars. Only once it's positive with
  t ≥ 2 does the desk prefer the leader for longs and the laggard for shorts.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

IST = "Asia/Kolkata"
PRIOR = 20.0                 # pseudo-observations at a 50% hit rate / 0R mean
HORIZON = 30                 # minutes a call is graded over
READ_EVERY = 5               # minutes between journaled reads
IC_HORIZONS = (5, 15, 30, 60)
IC_CLIP_BPS = 150.0          # forward returns clipped for the IC so one shock can't own the correlation


class Memory:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.d: dict = {"version": 1, "tables": {}, "graded": {"news": [], "thoughts_upto": {}, "trades": [], "armed": []},
                        "days": [], "lessons": []}
        if self.path and self.path.exists():
            try:
                self.d.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            g = self.d["graded"]
            g["news"], g["trades"], g["armed"] = g["news"][-5000:], g["trades"][-2000:], g["armed"][-2000:]
            self.d["lessons"] = self.d["lessons"][-20:]
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, indent=1, default=float), encoding="utf-8")
            tmp.replace(self.path)

    # ---- statistics ---------------------------------------------------------------------------------------------
    def bump(self, table: str, key: str, hit: bool, x: float, w: float = 1.0) -> None:
        r = self.d["tables"].setdefault(table, {}).setdefault(str(key), {"n": 0.0, "hits": 0.0, "sum": 0.0, "sum2": 0.0})
        r["n"] += w
        r["hits"] += w * bool(hit)
        r["sum"] += w * float(x)
        r["sum2"] += w * float(x) ** 2

    def stat(self, table: str, key: str) -> dict | None:
        return (self.d["tables"].get(table) or {}).get(str(key))

    def hit_rate(self, table: str, key: str) -> float:
        r = self.stat(table, key) or {"n": 0.0, "hits": 0.0}
        return (r["hits"] + PRIOR / 2) / (r["n"] + PRIOR)

    def reliability(self, table: str, key: str, lo: float = 0.5, hi: float = 1.5) -> float:
        """A weight multiplier from the shrunk hit rate: 50% → 1.0, 60% → 1.2, 40% → 0.8 (bounded)."""
        return float(np.clip(2 * self.hit_rate(table, key), lo, hi))

    def mean(self, table: str, key: str) -> float:
        r = self.stat(table, key) or {"n": 0.0, "sum": 0.0}
        return r["sum"] / (r["n"] + PRIOR)                              # shrunk toward 0

    def setup_mult(self, setup: str, day_type: str | None = None) -> tuple[float, str | None]:
        """(conviction multiplier, a reason to stand aside or None) from the setup's record of R."""
        key = f"{setup}|{day_type}" if day_type else setup
        for k in ([key, setup] if day_type else [setup]):
            r = self.stat("setup", k)
            if r and r["n"] >= 8:
                m = r["sum"] / (r["n"] + 8)                            # a lighter prior: trades are scarce
                if m <= -0.3:
                    return 0.0, f"{setup} has lost {m:+.2f}R a trade over {r['n']:.0f} trades" + (f" on {day_type} days" if k == key and day_type else "")
                return float(np.clip(1 + 0.5 * m, 0.6, 1.3)), None
        return 1.0, None

    def factor_weights(self) -> dict[str, float]:
        return {k: self.reliability("factor", k) for k in (self.d["tables"].get("factor") or {})}

    def news_trust(self, event: str | None, source: str | None) -> float:
        """How far to trust a headline's tone, from how that kind of story and that source have called the next
        30 minutes (both shrunk, the product bounded to 0.5×–1.5×)."""
        return float(np.clip(self.reliability("news_event", event or "general") * self.reliability("news_source", source or ""),
                             0.5, 1.5))

    def graded(self, table: str) -> float:
        return float(sum(r["n"] for r in (self.d["tables"].get(table) or {}).values()))


# ---- grading ---------------------------------------------------------------------------------------------------------
def forward(bars: pd.DataFrame | None, t, minutes: int = HORIZON, from_open: bool = False, with_start: bool = False):
    """Log return of the close from the first bar at/after t to the bar `minutes` later, same session only.
    `from_open`: something seen outside market hours (overnight news) is graded from the next session's first bar,
    the first moment the desk could act on it (up to a weekend later)."""
    if bars is None or bars.empty:
        return None
    t = pd.Timestamp(t)
    t = t.tz_localize(IST) if t.tzinfo is None else t.tz_convert(IST)
    idx = bars.index
    i = idx.searchsorted(t)
    if i >= len(idx):
        return None
    first_of_day = i == 0 or idx[i - 1].date() != idx[i].date()
    late = (idx[i] - t) > pd.Timedelta(minutes=5)
    if late and not (from_open and first_of_day and (idx[i] - t) <= pd.Timedelta(hours=66)):
        return None
    j = idx.searchsorted(idx[i] + pd.Timedelta(minutes=minutes))
    if j >= len(idx) or idx[j].date() != idx[i].date():
        return None
    a, b = float(bars["close"].iloc[i]), float(bars["close"].iloc[j])
    fr = math.log(b / a) if a > 0 and b > 0 else None
    return (fr, idx[i]) if with_start and fr is not None else (None if with_start else fr)


def grade_news(mem: Memory, news: pd.DataFrame, bars: dict, min_rel: float = 2.0, min_tone: float = 0.15) -> int:
    """Each headline's tone (each reader's) against the index's next 30 minutes from when the desk could act on it.
    Headlines that share that window are one observation between them, not one each: a night's forty stories are
    all judged on the same opening move, and counting them forty times would make one lucky morning look like a
    record (3 Oct 2026: 403 stories on 29 Sep scored "66% right" and ×1.31 trust before this)."""
    done = set(mem.d["graded"]["news"])
    rows = []
    for r in news.itertuples():
        if r.id in done:
            continue
        about = json.loads(r.about) if isinstance(r.about, str) and r.about else (r.about or {})
        nlp_ = json.loads(r.nlp) if isinstance(getattr(r, "nlp", None), str) and r.nlp else (getattr(r, "nlp", None) or {})
        graded = False
        for sym in ("NIFTY", "BANKNIFTY"):
            if (about.get(sym) or 0) < min_rel:
                continue
            got = forward(bars.get(sym), r.ts, from_open=True, with_start=True)
            if got is None:
                continue
            fr, t0 = got
            graded = True
            llm_ = ((nlp_.get("llm") or {}).get("readers") or {})
            for reader, tone in [("rules", r.sentiment)] + [(k, (v or {}).get(sym)) for k, v in llm_.items()]:
                if tone is None or not tone == tone or abs(tone) < min_tone:
                    continue
                rows.append((reader, sym, t0.floor(f"{HORIZON}min"), float(tone), fr, nlp_.get("event", "general"), r.source))
        if graded:
            mem.d["graded"]["news"].append(r.id)
    share: dict = {}
    for reader, sym, win, *_ in rows:
        share[(reader, sym, win)] = share.get((reader, sym, win), 0) + 1
    for reader, sym, win, tone, fr, event, source in rows:
        w = 1.0 / share[(reader, sym, win)]
        s = float(np.sign(tone))
        hit, bps = s * fr > 0, s * fr * 1e4
        mem.bump("news_reader", reader, hit, bps, w)
        if reader == "rules":
            mem.bump("news_event", event, hit, bps, w)
            mem.bump("news_source", source, hit, bps, w)
    return len(rows)


def grade_factors(mem: Memory, thoughts: pd.DataFrame, bars: dict) -> int:
    upto = mem.d["graded"]["thoughts_upto"]
    n = 0
    for r in thoughts.itertuples():
        last = upto.get(r.symbol, "")
        if str(r.ts) <= last:
            continue
        if last and pd.Timestamp(r.ts) - pd.Timestamp(last) < pd.Timedelta(minutes=READ_EVERY - 0.5):
            continue                                                # extra reads (a flip, a trade) aren't new evidence
        fr = forward(bars.get(r.symbol), r.ts)
        if fr is None:
            continue
        for e in json.loads(r.evidence or "[]"):
            d = float(e.get("direction") or 0)
            if abs(d) < 0.1:
                continue
            mem.bump("factor", e.get("factor"), d * fr > 0, d * fr * 1e4, READ_EVERY / HORIZON)
            n += 1
        upto[r.symbol] = max(upto.get(r.symbol, ""), str(r.ts))
    return n


def _settled(b: pd.DataFrame | None, t: pd.Timestamp) -> bool:
    """Every horizon of a read at `t` is knowable: the bars run an hour past it, or its session has closed."""
    if b is None or b.empty:
        return False
    last = b.index[-1]
    return last >= t + pd.Timedelta(minutes=max(IC_HORIZONS)) or last.date() > t.date() or \
        (last.hour, last.minute) >= (15, 25)


def grade_ic(mem: Memory, thoughts: pd.DataFrame, bars: dict) -> int:
    """Accumulate each factor's correlation with the forward move at each horizon (weighted sums, so it's incremental:
    a read counts min(1, 5/h) of an observation at horizon h, since reads 5 minutes apart overlap)."""
    up = mem.d["graded"].setdefault("ic_upto", {})
    ic = mem.d.setdefault("ic", {})
    n = 0
    for r in thoughts.itertuples():
        t = pd.Timestamp(r.ts)
        t = t.tz_localize(IST) if t.tzinfo is None else t.tz_convert(IST)
        last = up.get(r.symbol, "")
        if str(r.ts) <= last or (last and t - pd.Timestamp(last).tz_convert(IST) < pd.Timedelta(minutes=READ_EVERY - 0.5)):
            continue
        b = bars.get(r.symbol)
        if not _settled(b, t):
            continue
        frs = {h: forward(b, t, minutes=h) for h in IC_HORIZONS}
        for e in json.loads(r.evidence or "[]"):
            d = float(e.get("direction") or 0)
            if abs(d) < 0.1 or not e.get("factor"):
                continue
            for h, fr in frs.items():
                if fr is None:
                    continue
                y, w = float(np.clip(fr * 1e4, -IC_CLIP_BPS, IC_CLIP_BPS)), min(1.0, READ_EVERY / h)
                s_ = ic.setdefault(str(e["factor"]), {}).setdefault(str(h), [0.0] * 6)
                for k, v in enumerate((w, w * d, w * y, w * d * d, w * y * y, w * d * y)):
                    s_[k] += v
        n += 1
        up[r.symbol] = str(t)
    return n


def ic_table(mem: Memory, min_n: float = 10.0) -> list[dict]:
    """[{factor, by horizon: {n, ic, t}}], strongest first (largest |t| at any horizon with ≥ min_n observations)."""
    out = []
    for f, hs in (mem.d.get("ic") or {}).items():
        row = {}
        for h, (W, Sx, Sy, Sxx, Syy, Sxy) in hs.items():
            if W < min_n:
                continue
            vx, vy = Sxx / W - (Sx / W) ** 2, Syy / W - (Sy / W) ** 2
            if vx <= 1e-12 or vy <= 1e-12:
                continue
            r = float(np.clip((Sxy / W - Sx * Sy / W ** 2) / math.sqrt(vx * vy), -0.999, 0.999))
            row[str(h)] = {"n": round(W, 1), "ic": round(r, 4), "t": round(r * math.sqrt(max(W - 2, 0) / (1 - r * r)), 2)}
        if row:
            out.append({"factor": f, "h": row})
    out.sort(key=lambda x: -max(abs(v["t"]) for v in x["h"].values()))
    return out


def record_move(mem: Memory, day, symbol: str, bars: pd.DataFrame | None, opening: dict | None) -> dict | None:
    """The session's realised volatility and move from the first live chain read to the close, against the ATM IV
    read then (the buyer's edge). `opening`: chainflow.ChainFlow.opening(symbol)."""
    if bars is None or bars.empty or not opening or not opening.get("atm_iv"):
        return None
    t0 = pd.Timestamp(opening["ts"])
    b = bars[(bars.index >= t0) & (bars.index.date == t0.date())]["close"]
    if len(b) < 60:
        return None
    r5 = np.log(b.resample("5min").last().dropna()).diff().dropna()
    if len(r5) < 12:
        return None
    iv = float(opening["atm_iv"])
    rv = float(r5.std(ddof=1) * math.sqrt(75 * 252) * 100)               # annualised, in IV's units (%)
    left = (b.index[-1] - b.index[0]).total_seconds() / 60 / (375 * 252)  # the session left, in years
    exp_move = iv / 100 * math.sqrt(max(left, 1e-9)) * math.sqrt(2 / math.pi)
    move = abs(math.log(float(b.iloc[-1]) / float(b.iloc[0])))
    rec = {"iv": round(iv, 2), "rv": round(rv, 2), "rv_iv": round(rv / iv, 3) if iv > 0 else None,
           "move": round(move, 5), "exp_move": round(exp_move, 5), "move_ratio": round(move / exp_move, 3) if exp_move else None}
    mem.d.setdefault("moves", {}).setdefault(str(day)[:10], {})[symbol] = rec
    return rec


def buyer_edge(mem: Memory, n: int = 20) -> dict:
    """Per index over the last `n` sessions: mean realised/implied vol, share of sessions where realised beat implied,
    and the mean |move| against the move the open's IV implied."""
    days = sorted(mem.d.get("moves") or {})[-n:]
    out = {}
    for d in days:
        for sym, r in mem.d["moves"][d].items():
            if r.get("rv_iv") is not None:
                out.setdefault(sym, []).append(r)
    res = {}
    for sym, rs in out.items():
        ratio = [r["rv_iv"] for r in rs]
        mv = [r["move_ratio"] for r in rs if r.get("move_ratio") is not None]
        res[sym] = {"sessions": len(rs), "rv_iv": round(float(np.mean(ratio)), 3),
                    "rv_above": round(float(np.mean([x > 1 for x in ratio])), 3),
                    "move_ratio": round(float(np.mean(mv)), 3) if mv else None}
    return res


def grade_trades(mem: Memory, trades: pd.DataFrame) -> int:
    done, n = set(mem.d["graded"]["trades"]), 0
    for r in trades.itertuples():
        if r.id in done or r.status != "closed" or r.r_multiple is None or not r.r_multiple == r.r_multiple:
            continue
        ctx = json.loads(r.context or "{}") if isinstance(r.context, str) else (r.context or {})
        R = float(np.clip(r.r_multiple, -3, 5))
        mem.bump("setup", r.strategy, R > 0, R)
        if ctx.get("regime"):
            mem.bump("setup", f"{r.strategy}|{ctx['regime']}", R > 0, R)
        mem.d["graded"]["trades"].append(r.id)
        n += 1
    return n


def grade_armed(mem: Memory, decisions: pd.DataFrame, bars: dict, horizon: int = 45) -> int:
    """Armed entries the EV gate rejected: what would have happened, target or stop first."""
    done, n = set(mem.d["graded"]["armed"]), 0
    for r in decisions.itertuples():
        key = f"{r.ts}|{r.symbol}|{r.strategy}"
        if key in done or "reached its level" not in str(r.detail):
            continue
        ctx = json.loads(r.context or "{}") if isinstance(r.context, str) else (r.context or {})
        a, b = ctx.get("armed") or {}, bars.get(r.symbol)
        lvl, stop, tgt, d = a.get("level"), a.get("invalidation"), ctx.get("target"), a.get("direction")
        if b is None or None in (lvl, stop, tgt, d):
            continue
        t = pd.Timestamp(r.ts)
        after = b[(b.index > t) & (b.index <= t + pd.Timedelta(minutes=horizon))]
        if after.empty:
            continue
        out = 0.0
        for row in after.itertuples():
            hit_stop = row.low <= stop if d > 0 else row.high >= stop
            hit_tgt = row.high >= tgt if d > 0 else row.low <= tgt
            if hit_stop:                                            # the stop first when a bar touches both
                out = -1.0
                break
            if hit_tgt:
                out = abs(tgt - lvl) / max(abs(lvl - stop), 1e-9)
                break
        else:
            last = float(after["close"].iloc[-1])
            out = d * (last - lvl) / max(abs(lvl - stop), 1e-9)
        mem.bump("armed_rejected", r.strategy, out > 0, out)
        mem.d["graded"]["armed"].append(key)
        n += 1
    return n


def grade_session(mem: Memory, journal, bars: dict, day) -> dict:
    """Grade everything from `day` (and anything older not yet graded); returns what was graded."""
    since = str(pd.Timestamp(day) - pd.Timedelta(days=7))[:10]
    news = journal.df("SELECT * FROM news WHERE ts >= ?", (since,))
    th = journal.df("SELECT ts, symbol, evidence FROM thoughts WHERE ts >= ? ORDER BY ts", (since,))
    tr = journal.df("SELECT * FROM trades WHERE opened_at >= ?", (since,))
    dec = journal.df("SELECT * FROM decisions WHERE ts >= ?", (since,))
    out = {"news": grade_news(mem, news, bars), "factors": grade_factors(mem, th, bars),
           "trades": grade_trades(mem, tr), "armed": grade_armed(mem, dec, bars)}
    grade_ic(mem, th, bars)
    from . import relstrength
    out["rs"] = relstrength.grade(mem, bars)
    if str(day) not in mem.d["days"]:
        mem.d["days"].append(str(day))
    return out


def rebuild(mem: Memory, journal, bars: dict) -> dict:
    """Forget everything graded and grade the whole journal again (after a change to the grading rules)."""
    keep, moves = mem.d.get("lessons", []), mem.d.get("moves", {})
    mem.d = Memory().d
    mem.d["lessons"], mem.d["moves"] = keep, moves             # a session's moves aren't re-derivable from the journal
    news = journal.df("SELECT * FROM news ORDER BY ts")
    th = journal.df("SELECT ts, symbol, evidence FROM thoughts ORDER BY ts")
    tr = journal.df("SELECT * FROM trades ORDER BY opened_at")
    dec = journal.df("SELECT * FROM decisions ORDER BY ts")
    out = {"news": grade_news(mem, news, bars), "factors": grade_factors(mem, th, bars),
           "trades": grade_trades(mem, tr), "armed": grade_armed(mem, dec, bars)}
    grade_ic(mem, th, bars)
    from . import relstrength
    out["rs"] = relstrength.grade(mem, bars)
    mem.d["days"] = sorted({str(t)[:10] for t in th["ts"]}) if not th.empty else []
    return out


def bootstrap(cfg, mem: Memory, bars: dict, journal=None, min_bars: int = 300, max_sessions: int = 8, say=print) -> dict:
    """Seed a memory from history so the desk doesn't start every factor at "no record".

    Each full session in `bars` (real 1-minute bars: recorded, or Yahoo's last week) is replayed through the same
    engine and analyst on a scratch journal, and every read's factors are graded against what the index did next:
    the same grading as live, point in time. Headlines in `journal` are graded too. Setups are not: a replay's fills
    come from a model chain, and the setup record should be built from the desk's own trades."""
    from ..journal.journal import Journal
    from .engine import IntradayEngine, run_replay
    from .feeds import ReplayFeed
    from .sim import IntradayBroker
    nifty = bars.get("NIFTY")
    if nifty is None or nifty.empty:
        return {"sessions": 0, "factors": 0, "news": 0}
    counts = pd.Series(nifty.index.date).value_counts()
    days = sorted(d for d, n in counts.items() if n >= min_bars)[-max_sessions:]
    scratch = Journal()
    for d in days:
        say(f"  replaying {d} for the record …")
        eng = IntradayEngine(cfg, ReplayFeed(bars, d), "model", scratch, IntradayBroker(cfg, starting_cash=500000), say=None)
        run_replay(eng)
    th = scratch.df("SELECT ts, symbol, evidence FROM thoughts ORDER BY ts")
    got = {"sessions": len(days), "factors": grade_factors(mem, th, bars), "news": 0}
    grade_ic(mem, th, bars)
    from . import relstrength
    got["rs"] = relstrength.grade(mem, bars)
    if journal is not None:
        got["news"] = grade_news(mem, journal.df("SELECT * FROM news ORDER BY ts"), bars)
    mem.d["bootstrap"] = {**got, "days": [str(d) for d in days]}
    for d in days:
        if str(d) not in mem.d["days"]:
            mem.d["days"].append(str(d))
    return got


def summary(mem: Memory, top: int = 6) -> list[str]:
    """What the desk has learned so far, in lines for the session review."""
    L = []
    T = mem.d["tables"]

    def rows(table, label, unit="bps"):
        out = []
        for k, r in sorted((T.get(table) or {}).items(), key=lambda kv: -kv[1]["n"])[:top]:
            if r["n"] < 1:
                continue
            out.append(f"{label} {k}: {r['n']:.0f} graded, right {r['hits'] / r['n']:.0%}, "
                       f"{r['sum'] / r['n']:+.1f} {unit} avg → weight ×{mem.reliability(table, k):.2f}")
        return out

    L += rows("factor", "factor")
    L += rows("news_event", "news")
    L += rows("news_reader", "reader")
    for k, r in sorted((T.get("setup") or {}).items(), key=lambda kv: -kv[1]["n"])[:top]:
        m, why = mem.setup_mult(*k.split("|", 1)) if "|" in k else mem.setup_mult(k)
        L.append(f"setup {k}: {r['n']:.0f} trades, {r['hits'] / r['n']:.0%} won, {r['sum'] / r['n']:+.2f}R avg → "
                 + (f"stand aside ({why})" if why else f"conviction ×{m:.2f}"))
    for k, r in (T.get("armed_rejected") or {}).items():
        L.append(f"pre-break {k} entries the EV gate refused: {r['n']:.0f}, would have won {r['hits'] / r['n']:.0%}, "
                 f"{r['sum'] / r['n']:+.2f}R avg")
    for row in ic_table(mem)[:top]:
        best = max(row["h"].items(), key=lambda kv: abs(kv[1]["t"]))
        L.append(f"IC {row['factor']}: " + ", ".join(f"{h}m {v['ic']:+.3f}" for h, v in sorted(row["h"].items(), key=lambda kv: int(kv[0])))
                 + f" (strongest at {best[0]}m, t {best[1]['t']:+.1f}, n {best[1]['n']:.0f})")
    from .relstrength import earned, record
    rs = record(mem)
    if rs:
        L.append(f"relative strength (BANKNIFTY/NIFTY): the last 30 minutes' leader then led the next 30 with IC "
                 f"{rs['ic']:+.3f} (t {rs['t']:+.1f}, n {rs['n']:.0f} over {rs['days']} sessions): "
                 + ("used to pick the index" if earned(rs) else "not used yet"))
    for sym, e in buyer_edge(mem).items():
        L.append(f"buyer's edge {sym}: realised/implied vol {e['rv_iv']:.2f}× over {e['sessions']} sessions, realised above "
                 f"implied in {e['rv_above']:.0%}" + (f", moves {e['move_ratio']:.2f}× what the open's IV implied" if e["move_ratio"] else ""))
    return L
