"""The vote watch (docs/prereg/evolution_probation_v1.json, C; docs/EVOLUTION.md, phase 2).

What the market read and the news model contribute to a trade is a VOTE (P >= VOTE_P up, P <= 1 - VOTE_P down), so their votes are scored as calls: one vote per model
and instrument per scoring window (the first vote cast after the previous scored window ended), right when the price moved its way over the model's own window
(WINDOW_S), no outcome when it moved less than MIN_MOVE. Into an exponentially weighted hit rate (ALPHA per vote), started at the plain mean of the first MIN_VOTES.

Decided once a session, for the session ahead (at the first look of a new IST day, so from the scores up to the last segment's close): muted below MUTE_BELOW,
unmuted at UNMUTE_AT or above, otherwise unchanged; never with fewer than MIN_VOTES scored votes. A muted vote no longer counts TOWARDS an agreement; it still counts
AGAINST one and as a reading (auto2.py applies that). Every number is registered in the spec. Standard library only (paper package rules)."""
from __future__ import annotations

import math

VOTE_P = 0.65
WINDOW_S = {"read": 900, "news": 3600}
MIN_MOVE = 0.001
ALPHA, MIN_VOTES, MUTE_BELOW, UNMUTE_AT = 0.02, 50, 0.50, 0.53
MODELS = tuple(WINDOW_S)
MAX_KEYS = 120                                # two models by the desk's instruments
RESOLVE_TOL_S = 300                           # a vote is judged at its window's end: within this of it, the same IST day, or it has no outcome
IST_OFFSET_S = 19800


def _ist_day(t: float) -> int:
    return int((t + IST_OFFSET_S) // 86400)


class VoteWatch:
    def __init__(self):
        self.k: dict[str, dict] = {}         # "model|u" -> {"n", "first", "ew", "up", "muted", "pend": [t, dir, price] | None, "free": t}
        self.decided: str | None = None      # the IST day the mutes were last decided for
        self.ver = 0                         # bumped on every change

    @staticmethod
    def _key(model: str, u: str) -> str:
        return f"{model}|{u}"

    def observe(self, model: str, u: str, t: float, p: float | None, price: float | None) -> None:
        """Every look at an instrument: resolve the pending vote when its window has passed, and take a new vote when one is cast and none is pending."""
        if model not in WINDOW_S or not price or not math.isfinite(price) or price <= 0:
            return
        key = self._key(model, u)
        e = self.k.get(key)
        if e is None:
            if len(self.k) >= MAX_KEYS:
                return
            e = self.k[key] = {"n": 0, "first": 0.0, "ew": None, "up": 0, "muted": False, "pend": None, "free": 0.0}
        w = WINDOW_S[model]
        if e["pend"] and t - e["pend"][0] >= w:
            self.ver += 1
            t0, d, px0 = e["pend"]
            e["pend"], e["free"] = None, t0 + w
            if t - (t0 + w) > RESOLVE_TOL_S or _ist_day(t) != _ist_day(t0):
                e["late"] = e.get("late", 0) + 1                                        # not seen at its window's end (a gap, the close): no outcome
            else:
                mv = price / px0 - 1
                if abs(mv) >= MIN_MOVE:
                    e["up"] += 1 if mv > 0 else 0
                    self._score(e, 1.0 if (mv > 0) == (d > 0) else 0.0)
        if p is not None and e["pend"] is None and t >= e["free"] and (p >= VOTE_P or p <= 1 - VOTE_P):
            e["pend"] = [t, 1 if p >= VOTE_P else -1, float(price)]
            self.ver += 1

    @staticmethod
    def _score(e: dict, y: float) -> None:
        e["n"] += 1
        if e["n"] <= MIN_VOTES:
            e["first"] += y
            if e["n"] == MIN_VOTES:
                e["ew"] = e["first"] / MIN_VOTES
        else:
            e["ew"] = (1 - ALPHA) * e["ew"] + ALPHA * y

    def decide(self, day: str) -> None:
        """Once a session: the mutes for the session ahead, from the scores so far."""
        if self.decided == day:
            return
        self.ver += 1
        for e in self.k.values():
            if e["n"] >= MIN_VOTES and e["ew"] is not None:
                e["muted"] = e["ew"] < UNMUTE_AT if e["muted"] else e["ew"] < MUTE_BELOW
            else:
                e["muted"] = False
        self.decided = day

    def muted(self, model: str, u: str) -> bool:
        e = self.k.get(self._key(model, u))
        return bool(e and e["muted"])

    def report(self) -> dict:
        """Per model and instrument: scored votes, the weighted hit rate, the base rate (the share of up moves in the scored windows) and the mute. Private."""
        out: dict[str, dict] = {}
        for key, e in self.k.items():
            model, u = key.split("|", 1)
            out.setdefault(model, {})[u] = {"n": e["n"], "hit": None if e["ew"] is None else round(e["ew"], 3),
                                            "base_up": round(e["up"] / e["n"], 3) if e["n"] else None, "muted": e["muted"]}
        return {"decided": self.decided, "models": out, "muted": sum(1 for e in self.k.values() if e["muted"])}

    def export(self) -> dict:
        return {"d": self.decided, "k": {key: [e["n"], round(e["first"], 4), None if e["ew"] is None else round(e["ew"], 5), e["up"], e["muted"], e["pend"],
                                               round(e["free"], 1)] for key, e in self.k.items()}}

    def restore(self, d) -> int:
        """Read back validated (storage is not trusted)."""
        self.__init__()
        if not isinstance(d, dict):
            return 0
        fin = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)     # noqa: E731
        intn = lambda x: isinstance(x, int) and not isinstance(x, bool) and x >= 0                        # noqa: E731
        for key, v in (d.get("k") or {}).items() if isinstance(d.get("k"), dict) else ():
            if len(self.k) >= MAX_KEYS:
                break
            if not (isinstance(key, str) and key.split("|", 1)[0] in WINDOW_S and "|" in key and len(key) <= 40 and isinstance(v, list) and len(v) == 7):
                continue
            n, first, ew, up, muted, pend, free = v
            if not (intn(n) and fin(first) and 0 <= first <= n and (ew is None or (fin(ew) and 0 <= ew <= 1)) and intn(up) and up <= n and isinstance(muted, bool)
                    and fin(free)):
                continue
            if n >= MIN_VOTES and ew is None:
                continue
            ok_p = pend is None or (isinstance(pend, list) and len(pend) == 3 and fin(pend[0]) and pend[1] in (1, -1) and fin(pend[2]) and pend[2] > 0)
            if not ok_p:
                continue
            self.k[key] = {"n": n, "first": float(first), "ew": None if ew is None else float(ew), "up": up, "muted": muted and n >= MIN_VOTES,
                           "pend": None if pend is None else [float(pend[0]), pend[1], float(pend[2])], "free": float(free)}
        if isinstance(d.get("d"), str) and len(d["d"]) == 10:
            self.decided = d["d"]
        return len(self.k)
