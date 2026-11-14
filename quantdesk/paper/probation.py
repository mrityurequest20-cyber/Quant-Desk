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

import datetime as dt
import math

K, H, RHO_REG, SD_FLOOR = 0.25, 5.0, 0.45, 0.5
RELEASE_TRADES, RELEASE_SESSIONS, REPEAT_WINDOW = 8, 8, 60
HIT_HORIZON_SESSIONS = 20
REVIEW_MIN_DEMOTIONS, REVIEW_FIRST_SESSIONS, REVIEW_ROLL_SESSIONS, REVIEW_Z = 20, 120, 60, 1.2816   # one-sided 90%
G_DECIMALS = 2
EVENTS_SHOWN = 300                     # the latest events kept whole for the app; every event is also counted
FOLLOW_MAX = 200                       # open hit-rate windows; a demotion past it is not measured and is counted (`unmeasured`)


def is_day(x) -> bool:
    """A real calendar date as YYYY-MM-DD (storage is not trusted: '2026-02-30' is not a day)."""
    if not (isinstance(x, str) and len(x) == 10):
        return False
    try:
        return dt.date.fromisoformat(x).isoformat() == x
    except ValueError:
        return False


def _fin(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _int(x, lo=0) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= lo


class Ctx:
    """What probation reads from AUTO v2: the cumulative record, the proof bar, the calendar and what a strategy is."""

    def __init__(self, stats, min_trades, sessions_between, struct, hold, watched):
        self.stats, self.min_trades, self.sessions_between = stats, min_trades, sessions_between
        self.struct, self.hold, self.watched = struct, hold, watched


class Probation:
    def __init__(self):
        # what decides (kept with the open shadow book; who is in probation is also kept with the record, so it survives losing the book)
        self.st: dict[str, dict] = {}       # sid -> {"g", "pend": [day, k, sum R, sum R^2] | None, "P": None | {...}, "rel": day | None, "rep": int}
        self.first_day: str | None = None   # the first session watched (the review's clock)
        # what is measured (kept with the open shadow book; the first thing shed if it must shrink)
        self.events: list[list] = []         # the latest EVENTS_SHOWN [day, sid, "demoted" | "released", detail]
        self.counts = {"demoted": 0, "released": 0, "unmeasured": 0}
        self.follow: list[dict] = []         # demotions whose hit-rate window is open
        self.hits: dict[str, dict] = {}     # demotion day -> hold -> [paired differences n, their sum, excluded]
        self.left_out = 0                    # g values left out of the last save for its size bound
        self.ver = 0                         # bumped on every change (what the shadow book keeps)
        self.pver = 0                        # bumped when who is in probation changes (what the record keeps)

    # ---- the rule ------------------------------------------------------------------------------------------------------------------------------------
    def blocked(self, sid: str) -> bool:
        e = self.st.get(sid)
        return bool(e and e.get("P"))

    def close(self, sid: str, r: float, day: str, ctx: Ctx) -> None:
        """A closed shadow trade, BEFORE it is added to the cumulative record (so the record still says what it said before this session)."""
        self.ver += 1
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
        self.ver += 1
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
        if n0 <= 0 or n0 < ctx.min_trades(sid):
            return
        mean = s0 / n0
        sd = max(math.sqrt(max(q0 / n0 - mean * mean, 0.0)), SD_FLOOR)
        z = x / (sd * math.sqrt(1 / k + RHO_REG * (1 - 1 / k)))
        e["g"] = max(0.0, e["g"] - z - K)
        if e["g"] > H:
            quick = bool(e.get("rel")) and ctx.sessions_between(e["rel"], day) <= REPEAT_WINDOW
            rep = e.get("rep", 0) + 1 if quick else 0
            e["rep"] = rep
            e["P"] = {"since": day, "n": 0, "ses": 0, "sm": 0.0, "mult": 2 if rep == 1 else 1, "owner": rep >= 2}
            self._event(day, sid, "demoted", {"g": round(e["g"], 2), "repeat": rep, "owner_release": rep >= 2})
            if len(self.follow) < FOLLOW_MAX:
                self.follow.append({"sid": sid, "struct": ctx.struct(sid), "hold": ctx.hold(sid), "day": day, "own": [0, 0.0], "ctrl": {}})
            else:
                self.counts["unmeasured"] += 1

    def owner_release(self, sid: str, day: str) -> bool:
        """The owner's release (the only way out after a third demotion)."""
        e = self.st.get(sid)
        if not (e and e.get("P")):
            return False
        e["P"], e["g"], e["rel"] = None, 0.0, day
        self._event(day, sid, "released", {"by": "owner"})
        return True

    def _event(self, day, sid, kind, detail) -> None:
        self.ver += 1
        self.pver += 1
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.events.append([day, sid, kind, detail])
        del self.events[:-EVENTS_SHOWN]

    # ---- the hit rate (measured, monthly; the review is descriptive) ------------------------------------------------------------------------------------
    def _follow(self, sid: str, r: float, day: str, ctx: Ctx) -> None:
        for f in self.follow:
            if day <= f["day"]:
                continue                                                                # the window is the sessions AFTER the demotion
            if sid == f["sid"]:
                f["own"][0] += 1
                f["own"][1] += r
            elif ctx.struct(sid) == f["struct"] and not self.blocked(sid):
                c = f["ctrl"].setdefault(sid, [0, 0.0])
                c[0] += 1
                c[1] += r

    def _close_follows(self, today: str, ctx: Ctx) -> None:
        keep = []
        if self.follow:
            self.ver += 1
        for f in self.follow:
            if ctx.sessions_between(f["day"], today) <= HIT_HORIZON_SESSIONS:
                keep.append(f)
                continue
            ctrl = [s / n for n, s in f["ctrl"].values() if n > 0]
            h = self.hits.setdefault(f["day"], {}).setdefault(f["hold"] or "?", [0, 0.0, 0])
            if f["own"][0] > 0 and ctrl:
                h[0] += 1
                h[1] += f["own"][1] / f["own"][0] - sum(ctrl) / len(ctrl)
            else:
                h[2] += 1                                                               # nothing to compare: excluded, and counted
        self.follow = keep

    def report(self, today: str | None = None, sessions_between=None) -> dict:
        """Aggregates only (counts, shares, means): what may be published (the spec's `publication`). Per strategy, it stays on the relay."""
        on = [sid for sid, e in self.st.items() if e.get("P")]
        by = {d: v["overnight"] for d, v in self.hits.items() if "overnight" in v}
        n = sum(v[0] for v in by.values())
        review = {"demotions": n, "excluded": sum(v[2] for v in by.values()), "status": "INSUFFICIENT"}
        if n >= REVIEW_MIN_DEMOTIONS:
            mean = sum(v[1] for v in by.values()) / n
            groups = [v for v in by.values() if v[0]]
            G = len(groups)
            resid = [v[1] - mean * v[0] for v in groups]                                 # each starting session's sum, about the mean: the clustered spread
            se = math.sqrt(G / (G - 1) * sum(x * x for x in resid)) / n if G > 1 else float("inf")
            upper = mean + REVIEW_Z * se
            review.update({"mean_diff": round(mean, 4), "upper90": round(upper, 4) if math.isfinite(upper) else None, "clusters": G,
                           "status": "WORKING" if upper < 0 else "NOT WORKING (the owner decides)"})
        due = None
        if today and self.first_day and sessions_between:
            k = sessions_between(self.first_day, today)
            due = k >= REVIEW_FIRST_SESSIONS and (k - REVIEW_FIRST_SESSIONS) % REVIEW_ROLL_SESSIONS == 0
        return {"watched": len(self.st), "in_probation": len(on), "owner_only": sum(1 for sid in on if self.st[sid]["P"]["owner"]),
                "demotions": self.counts.get("demoted", 0), "releases": self.counts.get("released", 0), "unmeasured": self.counts.get("unmeasured", 0),
                "open_windows": len(self.follow), "review": review, "review_due": due, "left_out": self.left_out}

    def listing(self, top: int = 12) -> list[dict]:
        """For the private app panel: the strategies in probation now, longest first."""
        rows = [{"sid": sid, "since": e["P"]["since"], "trades": e["P"]["n"], "sessions": e["P"]["ses"], "mult": e["P"]["mult"], "owner": e["P"]["owner"]}
                for sid, e in self.st.items() if e.get("P")]
        rows.sort(key=lambda r: r["since"])
        return rows[:top]

    # ---- kept on the relay: what decides, what is measured, and the backstop ------------------------------------------------------------------------------
    def pset(self) -> dict:
        """Who is in probation, as small as it can be: kept with the strategy record, so losing the shadow book can never release a strategy."""
        return {sid: [e["P"]["since"], e["P"]["mult"], e["P"]["owner"]] for sid, e in self.st.items() if e.get("P")}

    def decision(self, max_g: int | None = None, pend: bool = True) -> dict:
        """The state that decides. g values are kept largest first, `max_g` of them when the store must shrink (the rest read back as zero, which only delays a
        demotion); without `pend` a session not yet applied is left out (it is then skipped, which also only delays). Probation states are always kept."""
        gs = sorted(((sid, round(e["g"], G_DECIMALS)) for sid, e in self.st.items() if round(e["g"], G_DECIMALS) > 0), key=lambda kv: -kv[1])
        keep_g = dict(gs if max_g is None else gs[:max_g])
        self.left_out = len(gs) - len(keep_g)
        st = {}
        for sid, e in self.st.items():
            row = {}
            if sid in keep_g:
                row["g"] = keep_g[sid]
            if pend and e.get("pend"):
                row["p"] = [e["pend"][0], e["pend"][1], round(e["pend"][2], 4), round(e["pend"][3], 4)]
            if e.get("P"):
                row["P"] = {**e["P"], "sm": round(e["P"]["sm"], 4)}
            if e.get("rel"):
                row["r"] = e["rel"]
            if e.get("rep"):
                row["k"] = e["rep"]
            if row:
                st[sid] = row
        return {"st": st, "f0": self.first_day, "g_total": len(gs)}

    def measurement(self) -> dict:
        return {"ev": self.events, "n": dict(self.counts), "hi": {d: {h: [v[0], round(v[1], 4), v[2]] for h, v in hv.items()} for d, hv in self.hits.items()},
                "fo": [{**f, "own": [f["own"][0], round(f["own"][1], 4)], "ctrl": {k: [v[0], round(v[1], 4)] for k, v in f["ctrl"].items()}} for f in self.follow]}

    def restore(self, decision, measurement, pset, known) -> int:
        """Read back validated, row by row (storage is not trusted). Whatever is in `pset` (the record's list) is in probation whatever the rest says: a
        probation can only be lost by the owner's release. `known(sid)`: a strategy in the catalogue."""
        self.__init__()
        d = decision if isinstance(decision, dict) else {}
        rows = d.get("st") if isinstance(d.get("st"), dict) else {}
        for sid, row in rows.items():
            try:
                if not (isinstance(sid, str) and known(sid) and isinstance(row, dict)):
                    continue
                e = {"g": 0.0, "pend": None, "P": None, "rel": None, "rep": 0}
                if _fin(row.get("g")) and 0 <= row["g"] <= 1e6:
                    e["g"] = float(row["g"])
                p = row.get("p")
                if isinstance(p, list) and len(p) == 4 and is_day(p[0]) and _int(p[1], 1) and _fin(p[2]) and _fin(p[3]) and p[3] >= 0:
                    e["pend"] = [p[0], p[1], float(p[2]), float(p[3])]
                P = row.get("P")
                if (isinstance(P, dict) and is_day(P.get("since")) and _int(P.get("n")) and _int(P.get("ses")) and _fin(P.get("sm"))
                        and P.get("mult") in (1, 2) and isinstance(P.get("owner"), bool)):
                    e["P"] = {"since": P["since"], "n": P["n"], "ses": P["ses"], "sm": float(P["sm"]), "mult": P["mult"], "owner": P["owner"]}
                elif P is not None:
                    e["P"] = {"since": "1970-01-01", "n": 0, "ses": 0, "sm": 0.0, "mult": 1, "owner": True}   # unreadable: still a probation, the owner's
                if is_day(row.get("r")):
                    e["rel"] = row["r"]
                if _int(row.get("k")) and row["k"] <= 10:
                    e["rep"] = row["k"]
                self.st[sid] = e
            except Exception:                                                           # noqa: BLE001 - one bad row costs only itself
                continue
        if is_day(d.get("f0")):
            self.first_day = d["f0"]
        for sid, v in (pset.items() if isinstance(pset, dict) else ()):             # the backstop: in probation whatever the book said
            if not (isinstance(sid, str) and known(sid)):
                continue
            e = self.st.setdefault(sid, {"g": 0.0, "pend": None, "P": None, "rel": None, "rep": 0})
            if not e.get("P"):
                ok = isinstance(v, list) and len(v) == 3 and is_day(v[0]) and v[1] in (1, 2) and isinstance(v[2], bool)
                e["P"] = {"since": v[0] if ok else "1970-01-01", "n": 0, "ses": 0, "sm": 0.0, "mult": v[1] if ok else 1, "owner": v[2] if ok else True}
        m = measurement if isinstance(measurement, dict) else {}
        for ev in m.get("ev") if isinstance(m.get("ev"), list) else []:
            if isinstance(ev, list) and len(ev) == 4 and is_day(ev[0]) and isinstance(ev[1], str) and ev[2] in ("demoted", "released") and isinstance(ev[3], dict):
                self.events.append(ev)
        self.events = self.events[-EVENTS_SHOWN:]
        if isinstance(m.get("n"), dict):
            for k in self.counts:
                if _int(m["n"].get(k)):
                    self.counts[k] = m["n"][k]
        for f in m.get("fo") if isinstance(m.get("fo"), list) else []:
            try:
                if not (isinstance(f, dict) and isinstance(f.get("sid"), str) and known(f["sid"]) and isinstance(f.get("struct"), str)
                        and isinstance(f.get("hold"), str) and is_day(f.get("day")) and isinstance(f.get("own"), list) and len(f["own"]) == 2
                        and _int(f["own"][0]) and _fin(f["own"][1]) and isinstance(f.get("ctrl"), dict)):
                    continue
                ctrl = {k: [v[0], float(v[1])] for k, v in f["ctrl"].items() if isinstance(k, str) and isinstance(v, list) and len(v) == 2 and _int(v[0]) and _fin(v[1])}
                self.follow.append({"sid": f["sid"], "struct": f["struct"], "hold": f["hold"], "day": f["day"], "own": [f["own"][0], float(f["own"][1])], "ctrl": ctrl})
            except Exception:                                                           # noqa: BLE001
                continue
        self.follow = self.follow[:FOLLOW_MAX]
        for day, hv in (m.get("hi").items() if isinstance(m.get("hi"), dict) else ()):
            if is_day(day) and isinstance(hv, dict):
                for hold, v in hv.items():
                    if isinstance(hold, str) and isinstance(v, list) and len(v) == 3 and _int(v[0]) and _fin(v[1]) and _int(v[2]):
                        self.hits.setdefault(day, {})[hold] = [v[0], float(v[1]), v[2]]
        return len(self.st)
