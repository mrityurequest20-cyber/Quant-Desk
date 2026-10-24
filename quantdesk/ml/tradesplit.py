"""Read-only split of the paper desk's closed trades (docs/ML_RESEARCH_PLAN.md, section 6 item 3, and 7b): by sleeve, by how far out of the money the long leg is, by day,
and a closer look at one sleeve's trades (the VWAP check).

Descriptive only. The buckets are fixed here, before the sample is large enough to mean anything, so a rerun in January is the same question as today's:
- strike distance = the long leg's distance out of the money as a percentage of the entry spot (a call: strike over spot; a put: spot over strike); an
  in-the-money leg counts in the first bucket. Buckets: up to 0.25%, 0.25% to 0.75%, over 0.75%.
- a cell with fewer than `MIN_CELL` trades is printed with its numbers and labelled "too few"; the whole report says "no claim" until the desk has
  `MIN_TRADES` closed trades, and never says more than "descriptive" after that: a finding is a pre-registered spec (`docs/ML_ROADMAP.md`), not this report.
- intervals are a bootstrap over *days* (trades on a day share a market), 90%, fixed seed. The win rate carries a Wilson interval.
- concentration is always shown: the total with and without the three best trades.

It reads the journal through a read-only SQLite connection (`mode=ro`) and writes nothing. It never changes a rule: any change a split suggests enters as a new
pre-registered version, never an edit of a locked one.
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import numpy as np

BUCKETS = ((None, 0.25, "up to 0.25% OTM"), (0.25, 0.75, "0.25% to 0.75% OTM"), (0.75, None, "over 0.75% OTM"))
MIN_CELL = 20
MIN_TRADES = 100
BOOT = 2000
SEED = 20261024


class JournalError(RuntimeError):
    pass


def load_closed(journal: Path) -> list[dict]:
    """Closed trades from a journal database, opened read-only. Raises JournalError for a missing file, a missing table or a missing column."""
    p = Path(journal)
    if not p.is_file():
        raise JournalError(f"no journal at {p}")
    try:
        with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM trades WHERE status = 'closed' ORDER BY opened_at, id").fetchall()
    except sqlite3.Error as exc:
        raise JournalError(f"{p}: {exc}") from exc
    need = {"id", "strategy", "symbol", "direction", "kind", "opened_at", "entry_underlying", "exit_underlying", "pnl", "fees", "exit_reason", "legs"}
    out = [dict(r) for r in rows]
    if out and not need <= set(out[0]):
        raise JournalError(f"{p}: the trades table lacks {sorted(need - set(out[0]))}")
    return out


def long_leg_distance_pct(trade: dict) -> float | None:
    """The long option leg's distance out of the money, % of the entry spot (negative: in the money), or None if the trade has no long option leg or no spot."""
    spot = trade.get("entry_underlying")
    try:
        legs = json.loads(trade.get("legs") or "[]")
    except (TypeError, ValueError):
        return None
    if not spot or not math.isfinite(float(spot)) or float(spot) <= 0:
        return None
    best = None
    for leg in legs if isinstance(legs, list) else []:
        if not isinstance(leg, dict) or not isinstance(leg.get("instrument") or {}, dict):
            continue
        ins = leg.get("instrument") or {}
        if ins.get("kind") != "option" or not (leg.get("qty") or 0) > 0 or ins.get("strike") is None:
            continue
        k, right = float(ins["strike"]), ins.get("right")
        d = (k - float(spot)) / float(spot) * 100 if right == "CE" else (float(spot) - k) / float(spot) * 100 if right == "PE" else None
        if d is not None and (best is None or d < best):          # several long legs: the one nearest the money, so the trade is not counted further out than it is
            best = d
    return best


def bucket(d: float | None) -> str:
    if d is None:
        return "no long option leg"
    for lo, hi, name in BUCKETS:
        if (lo is None or d >= lo) and (hi is None or d < hi):
            return name
    return BUCKETS[-1][2]


def day_of(trade: dict) -> str:
    return str(trade["opened_at"])[:10]


def wilson(k: int, n: int, z: float = 1.645) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def day_bootstrap(trades: list[dict], key=lambda t: t["pnl"], level: float = 0.90) -> tuple[float, float]:
    """Interval for the mean of `key` per trade, resampling whole days."""
    days: dict[str, list[float]] = {}
    for t in trades:
        days.setdefault(day_of(t), []).append(float(key(t)))
    names = sorted(days)
    if len(names) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(SEED)
    sums = np.array([sum(days[d]) for d in names])
    cnt = np.array([len(days[d]) for d in names])
    idx = rng.integers(0, len(names), size=(BOOT, len(names)))
    means = sums[idx].sum(1) / cnt[idx].sum(1)
    a = (1 - level) / 2
    return (float(np.quantile(means, a)), float(np.quantile(means, 1 - a)))


def cell(trades: list[dict]) -> dict:
    n = len(trades)
    net = [float(t["pnl"]) - 0.0 for t in trades]
    wins = sum(1 for x in net if x > 0)
    lo, hi = wilson(wins, n)
    top3 = sorted(net, reverse=True)[:3]
    b = day_bootstrap(trades)
    return {"n": n, "wins": wins, "win_rate": wins / n if n else float("nan"), "win_ci90": [lo, hi], "pnl": sum(net), "fees": sum(float(t["fees"] or 0) for t in trades),
            "mean_pnl": sum(net) / n if n else float("nan"), "mean_pnl_ci90_by_day": list(b), "pnl_without_top3": sum(net) - sum(top3) if n > 3 else float("nan"),
            "top3": top3, "days": len({day_of(t) for t in trades}), "too_few": n < MIN_CELL}


def split(trades: list[dict]) -> dict:
    """The fixed splits of the closed trades."""
    for t in trades:
        t["_dist"] = long_leg_distance_pct(t)
        t["_bucket"] = bucket(t["_dist"])
    groups = {"all": {"all": trades}}
    groups["sleeve"] = _by(trades, lambda t: t["strategy"])
    groups["strike_distance"] = _by(trades, lambda t: t["_bucket"])
    groups["day"] = _by(trades, day_of)
    groups["symbol"] = _by(trades, lambda t: t["symbol"])
    groups["exit_reason"] = _by(trades, lambda t: t["exit_reason"])
    out = {k: {name: cell(v) for name, v in g.items()} for k, g in groups.items()}
    out["total_trades"] = len(trades)
    out["claim"] = ("no claim: fewer than %d closed trades" % MIN_TRADES) if len(trades) < MIN_TRADES else "descriptive only: a finding needs a pre-registered spec"
    return out


def _by(trades, key) -> dict:
    g: dict = {}
    for t in trades:
        g.setdefault(key(t), []).append(t)
    return dict(sorted(g.items()))


def sleeve_check(trades: list[dict], sleeve: str) -> dict:
    """The close look at one sleeve (the VWAP check): was the underlying right and the trade still lost (exit, theta and cost rules), or was the underlying wrong (the logic)?"""
    mine = [t for t in trades if t["strategy"] == sleeve]
    rows = []
    for t in mine:
        move = float(t["direction"]) * (float(t["exit_underlying"]) - float(t["entry_underlying"])) / float(t["entry_underlying"]) * 100 if t["exit_underlying"] and t["entry_underlying"] else float("nan")
        pnl, fees = float(t["pnl"]), float(t["fees"] or 0)
        rows.append({"id": t["id"], "day": day_of(t), "symbol": t["symbol"], "exit_reason": t["exit_reason"], "underlying_move_in_trade_direction_pct": move,
                     "pnl": pnl, "fees": fees, "pnl_before_fees": pnl + fees,
                     "verdict": ("underlying wrong" if move < 0 else "underlying right, trade lost: exit/theta/cost" if pnl <= 0 else "won") if move == move else "no exit price"})
    return {"sleeve": sleeve, "trades": rows, "n": len(rows), "wins": sum(1 for r in rows if r["pnl"] > 0),
            "underlying_wrong": sum(1 for r in rows if r["verdict"] == "underlying wrong"),
            "underlying_right_trade_lost": sum(1 for r in rows if r["verdict"].startswith("underlying right")), "fees": sum(r["fees"] for r in rows)}


def render(rep: dict, check: dict | None = None) -> str:
    f = lambda x: "n/a" if x != x else f"{x:,.0f}"
    L = [f"{rep['total_trades']} closed trades; {rep['claim']}.", ""]
    for title, key in (("By sleeve", "sleeve"), ("By long-leg strike distance", "strike_distance"), ("By symbol", "symbol"), ("By exit reason", "exit_reason"), ("By day", "day")):
        L.append(f"{title}:")
        for name, c in rep[key].items():
            lo, hi = c["win_ci90"]
            ci = c["mean_pnl_ci90_by_day"]
            L.append(f"  {name}: {c['n']} trades on {c['days']} days, {c['wins']} wins ({c['win_rate']:.0%}, 90% {lo:.0%} to {hi:.0%}), P&L {f(c['pnl'])} "
                     f"(mean {f(c['mean_pnl'])}, 90% by day {f(ci[0])} to {f(ci[1])}), without the best three {f(c['pnl_without_top3'])}, fees {f(c['fees'])}"
                     + ("  [too few]" if c["too_few"] else ""))
        L.append("")
    if check:
        L.append(f"Close look at {check['sleeve']}: {check['n']} trades, {check['wins']} wins; underlying wrong {check['underlying_wrong']}, underlying right but the trade lost {check['underlying_right_trade_lost']}; fees {f(check['fees'])}")
        for r in check["trades"]:
            L.append(f"  {r['day']} {r['symbol']} {r['exit_reason']}: underlying {r['underlying_move_in_trade_direction_pct']:+.2f}% in the trade's direction, P&L {f(r['pnl'])} "
                     f"(before fees {f(r['pnl_before_fees'])}) - {r['verdict']}")
    return "\n".join(L)
