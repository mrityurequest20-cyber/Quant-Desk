"""The earn-in gate: a learned tilt reaches trading only once its record has held up out of sample.

The desk grades every call it makes (learning.py) and keeps a record per item: how a news event type, a source, a
reader, a factor or a setup has called what followed. D-01 showed that, so far, those records are indistinguishable
from noise, so they were recorded and not applied, which also means the desk never learns anything it acts on. This
gate is the way out of both: each item is tested on its own record, and only an item that keeps passing reaches
trading.

What the test establishes, honestly: that an item's record is **stable out of sample**, that the direction its earlier
sessions showed kept holding on the next ones, beyond what flipping the sessions at random produces. A consistently
wrong reader earns a *downward* tilt in the same way a consistently right one earns an upward one. It is not proof of a
trading edge, and with realistic intraday edges (52-55%) expect 6-12 weeks of sessions before anything passes
(research review, 16 Oct).

Per item (the D-01 follow-up's method, `docs/reports/2026-10-10_d01_followup_placebo.md`, with the research review's
corrections):

* **Excess against the day's base rate.** A call's hit counts only beyond what a coin with the same bias would have
  scored that session: `hits - n * (pi*u + (1-pi)*(1-u))`, pi = the share of bullish calls, u = the share of up moves,
  per session x index. Measured against 0.5, a bullish reader in a rising week looked skilled: the rules reader's 55%
  was its tone mix matching the days' direction (p 0.048 against 0.5; 0.999 within the sessions). Setups score real R.
* **Walk-forward lift.** Session by session, take the direction the earlier sessions' excess held and score it on this
  session's: the sum, per observation.
* **Recent record.** The last 60 sessions (`window_sessions`): an edge that has gone ages out.
* **Placebo.** Flip each session's excess at random (one session is one block: the two indices share its move) and
  re-run the walk-forward; p = the share of worlds at least as good (all 2^D worlds up to 14 sessions, else 4,000).
* **Multiplicity and repeated looks.** Benjamini-Hochberg across every item tested in a table (a lift <= 0 counts
  as p = 1, so the sign is not pre-selected); an item earns its place after passing on **two consecutive** sessions,
  and keeps it until its p exceeds twice the threshold.
* **Shrunk effect.** An earned item applies **half** its recorded tilt (winner's curse: the items that pass overstate
  their true rate). A setup's record can only resize a plan (0.75x-1.15x conviction, inside every risk cap) and never
  stands a setup aside (a stood-aside setup can't trade, so its record could never recover).

Modes (`intraday.learning.earn_in.mode`): `off` (the record is applied as before: news and reader trust live, the rest
behind `apply_factor_weights`), `shadow` (as `off`, plus the gate is computed and journaled: what it would apply),
`apply` (every learned tilt goes through the gate).
"""
from __future__ import annotations

import hashlib
import itertools

import numpy as np

# table -> how an observation scores: "hit" (called the move's direction, against the day's base rate), "mean" (R)
TABLES = {"news_reader": "hit", "news_event": "hit", "news_source": "hit", "factor": "hit", "setup": "mean"}
MODES = ("off", "shadow", "apply")
EXACT_UP_TO = 14                                             # sessions: enumerate every flip (2^14 = 16,384 worlds)
STATE_KEY = "earn_in_state"                                  # memory: per item, its streak and whether it is earned


def settings(cfg) -> dict:
    e = (cfg.get("intraday.learning", {}) or {}).get("earn_in", {}) or {}
    mode = str(e.get("mode", "shadow")).lower()
    return {"mode": mode if mode in MODES else "shadow", "min_sessions": int(e.get("min_sessions", 10)),
            "min_n": float(e.get("min_n", 30)), "alpha": float(e.get("alpha", 0.05)),
            "permutations": int(e.get("permutations", 4000)), "confirm": int(e.get("confirm_sessions", 2)),
            "window": int(e.get("window_sessions", 60))}


def _sessions(blocks: dict, kind: str = "hit") -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Per session (date), in time order: (excess, n). A block key is 'YYYY-MM-DD|SYMBOL'; a block is
    [n, hits, sum, pos, up]. A hit block without pos/up (recorded before the base-rate fix) can't be scored and is left
    out: a rebuild records them."""
    by: dict[str, list[float]] = {}
    for k, v in blocks.items():
        d = str(k).split("|")[0]
        n = float(v[0])
        if kind == "mean":
            ex = float(v[2])
        else:
            if len(v) < 5 or n <= 0:
                continue
            pi, u = float(v[3]) / n, float(v[4]) / n
            ex = float(v[1]) - n * (pi * u + (1 - pi) * (1 - u))
        acc = by.setdefault(d, [0.0, 0.0])
        acc[0], acc[1] = acc[0] + ex, acc[1] + n
    days = sorted(by)
    return np.array([by[d][0] for d in days]), np.array([by[d][1] for d in days]), days


def _lift(e: np.ndarray) -> np.ndarray:
    """Walk-forward score of each row of session excesses `e` (worlds x sessions): sum over sessions of
    sign(the cumulative excess of the sessions before) x this session's excess. The first session has no past: 0."""
    prev = np.cumsum(e, axis=-1) - e
    return np.sum(np.sign(prev) * e, axis=-1)


def test_item(blocks: dict, kind: str = "hit", permutations: int = 4000, seed: str = "", window: int = 0) -> dict:
    """{n, sessions, lift (per observation), p} for one item's per-session record, its last `window` sessions only
    (0: all), so an edge that has gone stops counting instead of carrying the item on its early sessions."""
    e, n, days = _sessions(blocks, kind)
    if window and len(days) > window:
        e, n, days = e[-window:], n[-window:], days[-window:]
    N, D = float(n.sum()), len(days)
    if D < 2 or N <= 0:
        return {"n": N, "sessions": D, "lift": 0.0, "p": 1.0}
    obs = float(_lift(e[None, :])[0])
    if D <= EXACT_UP_TO:                                     # every world, the observed one included: p = share of them
        flips = np.array(list(itertools.product((1.0, -1.0), repeat=D)))
        p = float(np.mean(_lift(flips * e[None, :]) >= obs - 1e-12))
    else:
        rng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))
        null = _lift(rng.choice((1.0, -1.0), size=(permutations, D)) * e[None, :])
        p = float((1 + np.sum(null >= obs - 1e-12)) / (1 + permutations))
    return {"n": N, "sessions": D, "lift": obs / N, "p": p}


def _bh(ps: dict[str, float], alpha: float) -> set[str]:
    """Benjamini-Hochberg: the keys whose p survives a false-discovery rate of `alpha` among all of them."""
    order = sorted(ps, key=ps.get)
    m, last = len(order), -1
    for i, k in enumerate(order, 1):
        if ps[k] <= alpha * i / m:
            last = i
    return set(order[:last]) if last > 0 else set()


def evaluate(memory, cfg) -> dict:
    """{table: {key: {n, sessions, lift, p, tested, passes}}}: this session's test of every item with a record."""
    st = settings(cfg)
    out: dict = {}
    for table, kind in TABLES.items():
        res = {}
        for key, blocks in ((memory.d.get("blocks") or {}).get(table) or {}).items():
            r = test_item(blocks, kind, st["permutations"], seed=f"{table}|{key}", window=st["window"])
            r["tested"] = r["sessions"] >= st["min_sessions"] and r["n"] >= st["min_n"]
            r["eligible"] = r["tested"] and r["lift"] > 0                  # shown only; BH counts every tested item
            res[key] = r
        ps = {k: (r["p"] if r["lift"] > 0 else 1.0) for k, r in res.items() if r["tested"]}
        ok = _bh(ps, st["alpha"])
        for k, r in res.items():
            r["passes"] = k in ok
            r["holds"] = r["tested"] and r["lift"] > 0 and r["p"] <= 2 * st["alpha"]      # keeps a place once earned
        out[table] = res
    return out


def _as_of(memory) -> str:
    days = memory.d.get("days") or []
    return str(max(days)) if days else ""


def update_state(memory, results: dict, confirm: int) -> dict:
    """Advance each item's streak once per graded session: earned after `confirm` passing sessions in a row, kept
    while it still holds (p <= 2 alpha), lost otherwise. The state lives in the memory, so it spans runners."""
    state = memory.d.setdefault(STATE_KEY, {})
    as_of = _as_of(memory)
    for table, res in results.items():
        for k, r in res.items():
            s = state.setdefault(f"{table}|{k}", {"streak": 0, "earned": False, "as_of": ""})
            if s["as_of"] == as_of:                         # this session was already counted (several calls a day)
                r["earned"] = s["earned"]
                continue
            s["as_of"] = as_of
            if s["earned"]:
                s["earned"] = bool(r["holds"])
                s["streak"] = s["streak"] + 1 if r["passes"] else 0
            else:
                s["streak"] = s["streak"] + 1 if r["passes"] else 0
                s["earned"] = s["streak"] >= confirm
            r["earned"] = s["earned"]
    return state


class Gate:
    """What trading may use from the record: half an earned item's tilt, 1.0x otherwise."""

    def __init__(self, memory, cfg):
        self.memory, self.cfg = memory, cfg
        self.st = settings(cfg)
        self.mode = self.st["mode"]
        self.results = {}
        if memory is not None and self.mode != "off":
            self.results = evaluate(memory, cfg)
            update_state(memory, self.results, self.st["confirm"])

    def earned(self, table: str, key) -> bool:
        return bool(((self.results.get(table) or {}).get(str(key)) or {}).get("earned"))

    def reliability(self, table: str, key) -> float:
        """Half the recorded tilt of an earned item (1 + (rel - 1) / 2), else 1.0."""
        return 1 + 0.5 * (self.memory.reliability(table, key) - 1) if self.earned(table, key) else 1.0

    def news_trust(self, event: str | None, source: str | None) -> float:
        return float(np.clip(self.reliability("news_event", event or "general") * self.reliability("news_source", source or ""),
                             0.5, 1.5))

    def factor_weights(self) -> dict[str, float]:
        return {k: self.reliability("factor", k) for k in (self.memory.d["tables"].get("factor") or {})
                if self.earned("factor", k)}

    def setup_mult(self, setup: str, day_type: str | None = None) -> tuple[float, str | None]:
        """A conviction multiplier from an earned setup record (the regime-specific one first), at half the tilt the
        old rule used; never a stand-aside."""
        for k in ([f"{setup}|{day_type}", setup] if day_type else [setup]):
            r = self.memory.stat("setup", k)
            if r and r["n"] and self.earned("setup", k):
                m = r["sum"] / (r["n"] + 8)                    # the same lighter prior as Memory.setup_mult
                return float(np.clip(1 + 0.25 * m, 0.75, 1.15)), None
        return 1.0, None

    def earned_items(self) -> list[tuple[str, str, float]]:
        """(table, key, the value it would apply), for the journal."""
        out = []
        for table, res in self.results.items():
            for k, r in res.items():
                if r.get("earned"):
                    v = self.setup_mult(k.split("|")[0], k.split("|")[1] if "|" in k else None)[0] if table == "setup" \
                        else self.reliability(table, k)
                    out.append((table, k, round(v, 3)))
        return sorted(out)

    def summary(self) -> str:
        tested = sum(len(r) for r in self.results.values())
        eligible = sum(1 for r in self.results.values() for x in r.values() if x["tested"])
        passing = sum(1 for r in self.results.values() for x in r.values() if x["passes"])
        items = self.earned_items()
        head = (f"earn-in ({self.mode}): {len(items)} of {tested} learned item(s) have earned a place; {eligible} had the "
                f"data to be tested (>= {self.st['min_sessions']} sessions, >= {self.st['min_n']:.0f} obs), {passing} "
                f"passed today (walk-forward vs a session placebo, Benjamini-Hochberg at {self.st['alpha']:.0%}; "
                f"{self.st['confirm']} sessions in a row to earn)")
        if not items:
            return head + ("; nothing learned is applied yet" if self.mode == "apply" else "")
        return head + ": " + ", ".join(f"{t}:{k} x{v:.2f}" for t, k, v in items[:12]) + ("…" if len(items) > 12 else "")
