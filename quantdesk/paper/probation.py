"""Probation (docs/prereg/evolution_probation_v1.json, B; docs/EVOLUTION.md, phase 2).

A strategy that has earned paper money and starts losing goes to PROBATION: it keeps trading in the shadow book and may not trade paper money until it proves itself
again on new trades. Every number below is registered in the spec and may not change without a new spec (evolution_probation_v2).

The statistic: a CUSUM on "losing on average", updated ONCE per strategy per session in which it closed at least one shadow trade. With x the mean R of the k trades it
closed that session, sd the population standard deviation of its cumulative R before that session (floored at SD_FLOOR):
    z = x / (sd * sqrt(1/k + RHO_REG * (1 - 1/k))),   g <- max(0, g - z - K),   demoted at g > H.
A session's update is applied once the session is over: at the strategy's first close of a later session, or at a flush (the first load of a later session, and
before every day plan). g is frozen while in probation. Release: at least RELEASE_TRADES trades over RELEASE_SESSIONS sessions since the demotion with the mean of
those sessions' means above zero (twice that after a demotion within REPEAT_WINDOW sessions of a release; a third leaves it to the owner). Release restores the
strategy's ordinary rules, never more. Convexity strategies are not watched. It only tightens: nothing here sizes a trade, starts one, or moves a limit.
Standard library only (paper package rules)."""
from __future__ import annotations

import math
import re

K, H, RHO_REG, SD_FLOOR = 0.25, 5.0, 0.45, 0.5
RELEASE_TRADES, RELEASE_SESSIONS, REPEAT_WINDOW = 8, 8, 60
HIT_HORIZON_SESSIONS = 20
REVIEW_MIN_DEMOTIONS, REVIEW_FIRST_SESSIONS, REVIEW_ROLL_SESSIONS, REVIEW_Z = 20, 120, 60, 1.2816   # one-sided 90%
G_DECIMALS = 2
EVENTS_MAX, FOLLOW_MAX, HITS_MAX = 300, 30, 400
CTRL_MAX = 200                               # control strategies kept per demotion window (a storage bound; when it binds, it is counted)
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Ctx:
    """What probation reads from AUTO v2: the cumulative record, the proof bar, the calendar and what a strategy is."""

    def __init__(self, stats, min_trades, sessions_between, struct, hold, watched):
        self.stats, self.min_trades, self.sessions_between = stats, min_trades, sessions_between
        self.struct, self.hold, self.watched = struct, hold, watched


class Probation:
    def __init__(self):
        self.st: dict[str, dict] = {}       # sid -> {"g", "pend": [day, k, sum R, sum R^2] | None, "P": None | {...}, "rel": day | None, "rep": int}
        self.events: list[list] = []         # [day, sid, "demoted" | "released", detail]
        self.follow: list[dict] = []         # demotions whose hit-rate window is open
        self.hits: list[list] = []           # [demotion day, sid, hold, own mean R - control mean R] | [day, sid, hold, None] when excluded
        self.first_day: str | None = None    # the first session watched (the review's clock)
        self.left_out = 0                    # g values left out of the last save for the record's size bound
        self.capped = 0                      # demotion windows whose control reached CTRL_MAX strategies

    # ---- the rule ------------------------------------------------------------------------------------------------------------------------------------
    def blocked(self, sid: str) -> bool:
        e = self.st.get(sid)
        return bool(e and e.get("P"))

    def close(self, sid: str, r: float, day: str, ctx: Ctx) -> None:
        """A closed shadow trade, BEFORE it is added to the cumulative record (so the record still says what it said before this session)."""
        self._follow(sid, r, day, ctx)
        if not ctx.watched(sid):
            return
        e = self.st.setdefault(sid, {"g": 0.0, "pend": None, "P": None, "rel": None, "rep": 0})
        if e["pend"] and e["pend"][0] != day:
            self._finalize(sid, e, ctx)
        if self.first_day is None:
            self.first_day = day
        p = e["pend"] or [day, 0, 0.0, 0.0]
        p[1], p[2], p[3] = p[1] + 1, p[2] + r, p[3] + r * r
        e["pend"] = p

    def flush(self, today: str, ctx: Ctx) -> None:
        """Apply every session that is over (before today): at load, and before the day plan is built."""
        for sid, e in self.st.items():
            if e.get("pend") and e["pend"][0] < today:
                self._finalize(sid, e, ctx)
        self._close_follows(today, ctx)

    def _finalize(self, sid: str, e: dict, ctx: Ctx) -> None:
        day, k, s, q = e["pend"]
        e["pend"] = None
        if k <= 0:
            return
        x = s / k
        P = e.get("P")
        if P:                                                                           # in probation: g frozen; the trades since the demotion count towards release
            P["n"] += k
            P["ses"] += 1
            P["sm"] += x
            if not P["owner"] and P["n"] >= RELEASE_TRADES * P["mult"] and P["ses"] >= RELEASE_SESSIONS * P["mult"] and P["sm"] > 0:
                e["P"], e["g"], e["rel"] = None, 0.0, day
                self._event(day, sid, "released", {"trades": P["n"], "sessions": P["ses"], "mean_of_session_means": round(P["sm"] / P["ses"], 4)})
            return
        row = ctx.stats(sid)
        if not row:
            return
        n0, s0, q0 = row[0] - k, row[1] - s, row[2] - q                                 # the record before this session (this session's trades are already in it)
        if n0 < ctx.min_trades(sid) or n0 <= 0:
            return
        mean = s0 / n0
        sd = max(math.sqrt(max(q0 / n0 - mean * mean, 0.0)), SD_FLOOR)
        z = x / (sd * math.sqrt(1 / k + RHO_REG * (1 - 1 / k)))
        e["g"] = max(0.0, e["g"] - z - K)
        if e["g"] > H:
            rep = e.get("rep", 0) + 1 if e.get("rel") and ctx.sessions_between(e["rel"], day) <= REPEAT_WINDOW else 0
            e["rep"] = rep
            e["P"] = {"since": day, "n": 0, "ses": 0, "sm": 0.0, "mult": 2 if rep == 1 else 1, "owner": rep >= 2}
            self._event(day, sid, "demoted", {"g": round(e["g"], 2), "repeat": rep, "owner_release": rep >= 2})
            if len(self.follow) < FOLLOW_MAX:
                self.follow.append({"sid": sid, "struct": ctx.struct(sid), "hold": ctx.hold(sid), "day": day, "own": [0, 0.0], "ctrl": {}})

    def owner_release(self, sid: str, day: str) -> bool:
        """The owner's release (the only way out after a third demotion)."""
        e = self.st.get(sid)
        if not (e and e.get("P")):
            return False
        e["P"], e["g"], e["rel"] = None, 0.0, day
        self._event(day, sid, "released", {"by": "owner"})
        return True

    def _event(self, day, sid, kind, detail) -> None:
        self.events.append([day, sid, kind, detail])
        del self.events[:-EVENTS_MAX]

    # ---- the hit rate (measured, monthly; the review is descriptive) ------------------------------------------------------------------------------------
    def _follow(self, sid: str, r: float, day: str, ctx: Ctx) -> None:
        for f in self.follow:
            if day <= f["day"]:
                continue                                                                # the window is the sessions AFTER the demotion
            if sid == f["sid"]:
                f["own"][0] += 1
                f["own"][1] += r
            elif ctx.struct(sid) == f["struct"] and not self.blocked(sid):
                if sid not in f["ctrl"] and len(f["ctrl"]) >= CTRL_MAX:
                    f["capped"] = True
                    continue
                c = f["ctrl"].setdefault(sid, [0, 0.0])
                c[0] += 1
                c[1] += r

    def _close_follows(self, today: str, ctx: Ctx) -> None:
        keep = []
        for f in self.follow:
            if ctx.sessions_between(f["day"], today) <= HIT_HORIZON_SESSIONS:
                keep.append(f)
                continue
            ctrl = [s / n for n, s in f["ctrl"].values() if n > 0]
            diff = (f["own"][1] / f["own"][0] - sum(ctrl) / len(ctrl)) if f["own"][0] > 0 and ctrl else None
            self.hits.append([f["day"], f["sid"], f["hold"], None if diff is None else round(diff, 4)])
            self.capped += 1 if f.get("capped") else 0
            del self.hits[:-HITS_MAX]
        self.follow = keep

    def report(self, today: str | None = None, sessions_between=None) -> dict:
        """Aggregates only (counts, shares, means): what may be published (the spec's `publication`). Per strategy, it stays on the relay."""
        on = [sid for sid, e in self.st.items() if e.get("P")]
        dem = [e for e in self.events if e[2] == "demoted"]
        rel = [e for e in self.events if e[2] == "released"]
        night = [h for h in self.hits if h[2] == "overnight"]
        used = [h for h in night if h[3] is not None]
        review = {"demotions": len(used), "excluded": len(night) - len(used), "status": "INSUFFICIENT"}
        if len(used) >= REVIEW_MIN_DEMOTIONS:
            by: dict[str, list] = {}
            for h in used:
                by.setdefault(h[0], []).append(h[3])
            mean = sum(h[3] for h in used) / len(used)
            G = len(by)
            resid = [sum(v) - mean * len(v) for v in by.values()]
            se = math.sqrt(G / (G - 1) * sum(x * x for x in resid)) / len(used) if G > 1 else float("inf")
            upper = mean + REVIEW_Z * se
            review.update({"mean_diff": round(mean, 4), "upper90": round(upper, 4) if math.isfinite(upper) else None, "clusters": G,
                           "status": "WORKING" if upper < 0 else "NOT WORKING (the owner decides)"})
        due = None
        if today and self.first_day and sessions_between:
            n = sessions_between(self.first_day, today)
            due = n >= REVIEW_FIRST_SESSIONS and (n - REVIEW_FIRST_SESSIONS) % REVIEW_ROLL_SESSIONS == 0
        return {"watched": len(self.st), "in_probation": len(on), "owner_only": sum(1 for sid in on if self.st[sid]["P"]["owner"]),
                "demotions": len(dem), "releases": len(rel), "review": review, "review_due": due, "left_out": self.left_out, "control_capped": self.capped}

    def listing(self, top: int = 12) -> list[dict]:
        """For the private app panel: the strategies in probation now, longest first."""
        rows = [{"sid": sid, "since": e["P"]["since"], "trades": e["P"]["n"], "sessions": e["P"]["ses"], "mult": e["P"]["mult"], "owner": e["P"]["owner"]}
                for sid, e in self.st.items() if e.get("P")]
        rows.sort(key=lambda r: r["since"])
        return rows[:top]

    # ---- kept with the private strategy record ----------------------------------------------------------------------------------------------------
    def export(self, max_g: int | None = None) -> dict:
        """The state as the record keeps it. Probation states, pending sessions and the measurement are always kept; g values are kept largest first,
        `max_g` of them when the record must shrink (the rest read back as zero, which only delays a demotion)."""
        gs = sorted(((sid, round(e["g"], G_DECIMALS)) for sid, e in self.st.items() if round(e["g"], G_DECIMALS) > 0), key=lambda kv: -kv[1])
        keep_g = dict(gs if max_g is None else gs[:max_g])
        self.left_out = len(gs) - len(keep_g)
        st = {}
        for sid, e in self.st.items():
            row = {}
            if sid in keep_g:
                row["g"] = keep_g[sid]
            if e.get("pend"):
                row["p"] = [e["pend"][0], e["pend"][1], round(e["pend"][2], 4), round(e["pend"][3], 4)]
            if e.get("P"):
                row["P"] = {**e["P"], "sm": round(e["P"]["sm"], 4)}
            if e.get("rel"):
                row["r"] = e["rel"]
            if e.get("rep"):
                row["k"] = e["rep"]
            if row:
                st[sid] = row
        return {"st": st, "ev": self.events, "fo": self.follow, "hi": self.hits, "f0": self.first_day, "cc": self.capped}

    def restore(self, d, known) -> int:
        """Read back validated (storage is not trusted): unknown strategies, bad dates and bad numbers are dropped. `known(sid)`: a strategy in the catalogue."""
        self.__init__()
        if not isinstance(d, dict):
            return 0
        fin = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)     # noqa: E731
        day = lambda x: isinstance(x, str) and bool(DAY.match(x))                                          # noqa: E731
        for sid, row in (d.get("st") or {}).items() if isinstance(d.get("st"), dict) else ():
            if not (isinstance(sid, str) and known(sid) and isinstance(row, dict)):
                continue
            e = {"g": 0.0, "pend": None, "P": None, "rel": None, "rep": 0}
            if fin(row.get("g")) and 0 <= row["g"] <= 1e6:
                e["g"] = float(row["g"])
            p = row.get("p")
            if isinstance(p, list) and len(p) == 4 and day(p[0]) and isinstance(p[1], int) and not isinstance(p[1], bool) and p[1] > 0 and fin(p[2]) and fin(p[3]):
                e["pend"] = [p[0], p[1], float(p[2]), float(p[3])]
            P = row.get("P")
            if (isinstance(P, dict) and day(P.get("since")) and all(isinstance(P.get(x), int) and not isinstance(P.get(x), bool) and P[x] >= 0 for x in ("n", "ses"))
                    and fin(P.get("sm")) and P.get("mult") in (1, 2) and isinstance(P.get("owner"), bool)):
                e["P"] = {"since": P["since"], "n": P["n"], "ses": P["ses"], "sm": float(P["sm"]), "mult": P["mult"], "owner": P["owner"]}
            elif P is not None:
                e["P"] = {"since": "1970-01-01", "n": 0, "ses": 0, "sm": 0.0, "mult": 1, "owner": True}   # a probation that cannot be read stays a probation, the owner's
            if day(row.get("r")):
                e["rel"] = row["r"]
            if isinstance(row.get("k"), int) and not isinstance(row["k"], bool) and 0 <= row["k"] <= 10:
                e["rep"] = row["k"]
            self.st[sid] = e
        for ev in d.get("ev") or [] if isinstance(d.get("ev"), list) else []:
            if isinstance(ev, list) and len(ev) == 4 and day(ev[0]) and isinstance(ev[1], str) and ev[2] in ("demoted", "released") and isinstance(ev[3], dict):
                self.events.append(ev)
        self.events = self.events[-EVENTS_MAX:]
        for f in d.get("fo") or [] if isinstance(d.get("fo"), list) else []:
            if (isinstance(f, dict) and isinstance(f.get("sid"), str) and known(f["sid"]) and isinstance(f.get("struct"), str) and isinstance(f.get("hold"), str)
                    and day(f.get("day")) and isinstance(f.get("own"), list) and len(f["own"]) == 2 and isinstance(f.get("ctrl"), dict)):
                ctrl = {k: [int(v[0]), float(v[1])] for k, v in f["ctrl"].items()
                        if isinstance(k, str) and isinstance(v, list) and len(v) == 2 and isinstance(v[0], int) and not isinstance(v[0], bool) and fin(v[1])}
                if isinstance(f["own"][0], int) and fin(f["own"][1]):
                    self.follow.append({"sid": f["sid"], "struct": f["struct"], "hold": f["hold"], "day": f["day"], "own": [int(f["own"][0]), float(f["own"][1])],
                                        "ctrl": dict(list(ctrl.items())[:CTRL_MAX]), **({"capped": True} if f.get("capped") is True else {})})
        self.follow = self.follow[:FOLLOW_MAX]
        for h in d.get("hi") or [] if isinstance(d.get("hi"), list) else []:
            if isinstance(h, list) and len(h) == 4 and day(h[0]) and isinstance(h[1], str) and isinstance(h[2], str) and (h[3] is None or fin(h[3])):
                self.hits.append(h)
        self.hits = self.hits[-HITS_MAX:]
        if day(d.get("f0")):
            self.first_day = d["f0"]
        if isinstance(d.get("cc"), int) and not isinstance(d["cc"], bool) and d["cc"] >= 0:
            self.capped = d["cc"]
        return len(self.st)
