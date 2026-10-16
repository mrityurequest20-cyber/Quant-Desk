"""The earn-in gate: a learned tilt reaches trading only after it has beaten a placebo out of sample.

The desk grades every call it makes (learning.py) and keeps a record per item: how a news event type, a source, a
reader, a factor or a setup has called what followed. D-01 showed that, so far, those records are indistinguishable
from noise, so they were recorded and not applied, which also means the desk never learns anything it acts on. This
gate is the way out of both: each item is tested on its own record, and only an item that passes reaches trading.

The test, per item (the D-01 follow-up's method, `docs/reports/2026-10-10_d01_followup_placebo.md`):

* **Walk-forward lift.** Session by session, take the direction the record held on the *earlier* sessions only (the
  item called the next 30 minutes better or worse than a coin) and score it on this session's outcome. The lift is the
  sum, per observation. A record that is only fitting its own past has no lift; one that keeps calling it right does.
* **Placebo.** Flip each session's outcome at random (the two indices share a session's move, so a session is one
  block) and re-run the whole walk-forward. p = the share of flipped worlds that do at least as well: exact over every
  flip up to 14 sessions, else a seeded sample.
* **Earned** = enough sessions and observations, a positive lift, and a p that survives Benjamini-Hochberg across every
  item tested in the same table (hundreds of news sources are tested at once; most would pass by chance otherwise).

Earned items apply their recorded value; everything else is neutral (1.0x). It is re-tested every session, so an item
loses its place as soon as its record stops holding up. A setup's record can only resize a plan (0.6x-1.3x conviction,
inside every risk cap); it never stands a setup aside, since a stood-aside setup can't trade and so its record could
never recover (the absorbing state D-01 measured).

Modes (`intraday.learning.earn_in.mode`): `off` (the record is applied as before: news and reader trust live, the rest
behind `apply_factor_weights`), `shadow` (as `off`, plus the gate is computed and journaled: what it would apply),
`apply` (every learned tilt goes through the gate).
"""
from __future__ import annotations

import hashlib
import itertools

import numpy as np

# table -> how an observation scores: "hit" (called the move's direction; block excess = hits - n/2), "mean" (R)
TABLES = {"news_reader": "hit", "news_event": "hit", "news_source": "hit", "factor": "hit", "setup": "mean"}
MODES = ("off", "shadow", "apply")
EXACT_UP_TO = 14                                             # sessions: enumerate every flip (2^14 = 16,384 worlds)


def settings(cfg) -> dict:
    e = (cfg.get("intraday.learning", {}) or {}).get("earn_in", {}) or {}
    mode = str(e.get("mode", "shadow")).lower()
    return {"mode": mode if mode in MODES else "shadow", "min_sessions": int(e.get("min_sessions", 10)),
            "min_n": float(e.get("min_n", 30)), "alpha": float(e.get("alpha", 0.05)),
            "permutations": int(e.get("permutations", 4000))}


def _sessions(blocks: dict) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Per session (date), in time order: (excess, n). A block key is 'YYYY-MM-DD|SYMBOL'."""
    by: dict[str, list[float]] = {}
    for k, (n, hits, s) in blocks.items():
        d = str(k).split("|")[0]
        v = by.setdefault(d, [0.0, 0.0, 0.0])
        v[0], v[1], v[2] = v[0] + n, v[1] + hits, v[2] + s
    days = sorted(by)
    return (np.array([by[d][1] - by[d][0] / 2 for d in days]), np.array([by[d][0] for d in days]), days)


def _lift(e: np.ndarray) -> np.ndarray:
    """Walk-forward score of each row of session excesses `e` (worlds x sessions): sum over sessions of
    sign(the cumulative excess of the sessions before) x this session's excess. The first session has no past: 0."""
    prev = np.cumsum(e, axis=-1) - e
    return np.sum(np.sign(prev) * e, axis=-1)


def test_item(blocks: dict, kind: str = "hit", permutations: int = 4000, seed: str = "") -> dict:
    """{n, sessions, lift (per observation), p} for one item's per-session record."""
    if kind == "mean":                                       # R: the excess is the session's summed R
        days = sorted({str(k).split("|")[0] for k in blocks})
        e = np.array([sum(v[2] for k, v in blocks.items() if str(k).split("|")[0] == d) for d in days])
        n = np.array([sum(v[0] for k, v in blocks.items() if str(k).split("|")[0] == d) for d in days])
    else:
        e, n, days = _sessions(blocks)
    N, D = float(n.sum()), len(days)
    if D < 2 or N <= 0:
        return {"n": N, "sessions": D, "lift": 0.0, "p": 1.0}
    obs = float(_lift(e[None, :])[0])
    if D <= EXACT_UP_TO:
        flips = np.array(list(itertools.product((1.0, -1.0), repeat=D)))
    else:
        rng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))
        flips = rng.choice((1.0, -1.0), size=(permutations, D))
    null = _lift(flips * e[None, :])
    p = float((1 + np.sum(null >= obs - 1e-12)) / (1 + len(null)))
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
    """{table: {key: {n, sessions, lift, p, earned}}} for every item with a per-session record."""
    st = settings(cfg)
    out: dict = {}
    for table, kind in TABLES.items():
        res = {}
        for key, blocks in ((memory.d.get("blocks") or {}).get(table) or {}).items():
            r = test_item(blocks, kind, st["permutations"], seed=f"{table}|{key}")
            r["eligible"] = r["sessions"] >= st["min_sessions"] and r["n"] >= st["min_n"] and r["lift"] > 0
            res[key] = r
        ok = _bh({k: r["p"] for k, r in res.items() if r["eligible"]}, st["alpha"])
        for k, r in res.items():
            r["earned"] = k in ok
        out[table] = res
    return out


class Gate:
    """What trading may use from the record: an earned item's value, 1.0x otherwise."""

    def __init__(self, memory, cfg):
        self.memory, self.cfg = memory, cfg
        self.st = settings(cfg)
        self.mode = self.st["mode"]
        self.results = evaluate(memory, cfg) if memory is not None and self.mode != "off" else {}

    def earned(self, table: str, key) -> bool:
        return bool(((self.results.get(table) or {}).get(str(key)) or {}).get("earned"))

    def reliability(self, table: str, key) -> float:
        return self.memory.reliability(table, key) if self.earned(table, key) else 1.0

    def news_trust(self, event: str | None, source: str | None) -> float:
        return float(np.clip(self.reliability("news_event", event or "general") * self.reliability("news_source", source or ""),
                             0.5, 1.5))

    def factor_weights(self) -> dict[str, float]:
        return {k: self.memory.reliability("factor", k) for k in (self.memory.d["tables"].get("factor") or {})
                if self.earned("factor", k)}

    def setup_mult(self, setup: str, day_type: str | None = None) -> tuple[float, str | None]:
        """A conviction multiplier from an earned setup record (the regime-specific one first); never a stand-aside."""
        for k in ([f"{setup}|{day_type}", setup] if day_type else [setup]):
            r = self.memory.stat("setup", k)
            if r and r["n"] and self.earned("setup", k):
                m = r["sum"] / (r["n"] + 8)                    # the same lighter prior as Memory.setup_mult
                return float(np.clip(1 + 0.5 * m, 0.6, 1.3)), None
        return 1.0, None

    def earned_items(self) -> list[tuple[str, str, float]]:
        """(table, key, the value it would apply), for the journal."""
        out = []
        for table, res in self.results.items():
            for k, r in res.items():
                if r.get("earned"):
                    v = self.setup_mult(k.split("|")[0], k.split("|")[1] if "|" in k else None)[0] if table == "setup" \
                        else self.memory.reliability(table, k)
                    out.append((table, k, round(v, 3)))
        return sorted(out)

    def summary(self) -> str:
        tested = sum(len(r) for r in self.results.values())
        eligible = sum(1 for r in self.results.values() for x in r.values() if x["eligible"])
        items = self.earned_items()
        head = (f"earn-in ({self.mode}): {len(items)} of {tested} learned item(s) earned a place "
                f"({eligible} had the data to be tested: >= {self.st['min_sessions']} sessions, >= {self.st['min_n']:.0f} obs, "
                f"positive walk-forward lift; Benjamini-Hochberg at {self.st['alpha']:.0%})")
        if not items:
            return head + ("; nothing learned is applied yet" if self.mode == "apply" else "")
        return head + ": " + ", ".join(f"{t}:{k} x{v:.2f}" for t, k, v in items[:12]) + ("…" if len(items) > 12 else "")

