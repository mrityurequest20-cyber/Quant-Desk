"""The market read: what the options, futures and spot together say about sentiment and expectations (owner, 13 Nov 2026: "Data analyser must be strong which looks into
complete options data, futures data and spot data to understand the changes in sentiment and expectations of market").

For one underlying, from the live board (and the same board a quarter of an hour earlier):

* POSITIONING  put/call ratio by open interest and by volume; max pain (the strike where option holders lose most at expiry); the call wall above the price (the most call
               open interest: where writers defend, resistance) and the put wall below (support); how far the price is from each.
* FLOW         the future's open-interest build-up against its price: long build-up (price up, OI up: new longs), short build-up (down, up), short covering (up, down),
               long unwinding (down, down); and near-the-money writing: call OI added faster than put OI is resistance being sold (bearish), puts faster is support (bullish).
* EXPECTATIONS the implied move to expiry from the at-the-money straddle; skew (out-of-the-money put volatility over call volatility: the price of crash protection) and its
               change; the term structure (near against next expiry volatility: inverted means an event is priced); the future's premium over spot.

They are combined as BAYESIAN EVIDENCE: each reading is a signal s in [-1, 1] with a weight w (a log-likelihood ratio), and the read's probability that the market leans up is
P = 1 / (1 + exp(-(sum of w * s))). The weights are PRIORS set from what each reading is known to mean, not fitted: the lab's record is what will tell which of them carry
information, and docs/PAPER_TRADING.md says so. A read is a vote in AUTO v2's view only when P is far enough from a half (READ_VOTE_P).

Pure functions and one small class; nothing here trades. Paper package rules: standard library and the paper package only.
"""
from __future__ import annotations

import math

SKEW_OTM = 0.03          # the out-of-the-money strikes skew compares: about 3% either side of the price
BUILDUP_MIN_OI = 0.005   # a futures open-interest change under 0.5% is no build-up
BUILDUP_MIN_PX = 0.001   # nor a price change under 0.1%
LOOKBACK_S = 900         # changes are read against the board about a quarter of an hour earlier
READ_VOTE_P = 0.65       # the read votes up at P >= 0.65, down at P <= 0.35
WEIGHTS = {              # log-likelihood ratios per unit signal (priors)
    "pcr": 0.35,         # a high put/call OI ratio: puts written for support (contrarian-bullish in Indian index options)
    "pcr_chg": 0.45,     # the ratio rising over the last quarter hour
    "walls": 0.40,       # the price near its put wall (support) or its call wall (resistance)
    "buildup": 0.60,     # the future's build-up
    "writing": 0.50,     # near-the-money call versus put writing
    "skew_chg": 0.30,    # protection getting dearer is bearish
    "basis_chg": 0.25,   # the future's premium widening is bullish
    "pain": 0.15,        # a pull towards max pain into expiry
}


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _q(snap, name):
    q = (snap.get("quotes") or {}).get(name) if name else None
    return q if isinstance(q, dict) else None


def _mid(q):
    b, a = _num(q.get("bid")), _num(q.get("ask"))
    if b and a and 0 < b <= a:
        return (b + a) / 2
    lp = _num(q.get("ltp"))
    return lp if lp and lp > 0 else None


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def chain_rows(snap, chain: dict) -> list[dict]:
    """[{k, coi, poi, cvol, pvol, cmid, pmid}] for each strike of one expiry's chain ({strike: {"CE": name, "PE": name}})."""
    rows = []
    for k in sorted(chain):
        c, p = _q(snap, chain[k].get("CE")), _q(snap, chain[k].get("PE"))
        rows.append({"k": float(k), "coi": _num((c or {}).get("oi")) or 0.0, "poi": _num((p or {}).get("oi")) or 0.0, "cvol": _num((c or {}).get("vol")) or 0.0,
                     "pvol": _num((p or {}).get("vol")) or 0.0, "cmid": _mid(c) if c else None, "pmid": _mid(p) if p else None})
    return rows


def max_pain(rows: list[dict]) -> float | None:
    """The strike at which option holders, all together, would collect least at expiry."""
    if not rows or not any(r["coi"] or r["poi"] for r in rows):
        return None
    best = None
    for s in rows:
        pay = sum(r["coi"] * max(s["k"] - r["k"], 0.0) + r["poi"] * max(r["k"] - s["k"], 0.0) for r in rows)
        if best is None or pay < best[0]:
            best = (pay, s["k"])
    return best[1]


def walls(rows: list[dict], spot: float) -> tuple[float | None, float | None]:
    """(call wall at or above the price, put wall at or below it): the strikes with the most open interest on each side."""
    above = [r for r in rows if r["k"] >= spot and r["coi"] > 0]
    below = [r for r in rows if r["k"] <= spot and r["poi"] > 0]
    return (max(above, key=lambda r: r["coi"])["k"] if above else None, max(below, key=lambda r: r["poi"])["k"] if below else None)


def buildup(px_chg: float | None, oi_chg: float | None) -> tuple[str | None, float]:
    """The future's build-up from its price and open-interest changes (fractions): (label, signal in [-1, 1])."""
    if px_chg is None or oi_chg is None or abs(px_chg) < BUILDUP_MIN_PX or abs(oi_chg) < BUILDUP_MIN_OI:
        return None, 0.0
    if px_chg > 0 and oi_chg > 0:
        return "long build-up", 1.0
    if px_chg < 0 and oi_chg > 0:
        return "short build-up", -1.0
    if px_chg > 0:
        return "short covering", 0.5
    return "long unwinding", -0.5


def chain_read(snap, chain: dict, spot: float, T: float, r: float, iv_fn) -> dict:
    """The static part of the read for one expiry: positioning and expectations. `iv_fn(price, S, K, T, r, right)` gives an implied volatility."""
    rows = chain_rows(snap, chain)
    coi, poi = sum(x["coi"] for x in rows), sum(x["poi"] for x in rows)
    cvol, pvol = sum(x["cvol"] for x in rows), sum(x["pvol"] for x in rows)
    out = {"pcr": poi / coi if coi > 0 else None, "pcr_vol": pvol / cvol if cvol > 0 else None, "max_pain": max_pain(rows), "coi": coi, "poi": poi}
    out["call_wall"], out["put_wall"] = walls(rows, spot)
    atm = min(rows, key=lambda x: abs(x["k"] - spot)) if rows else None
    out["implied_move"] = ((atm["cmid"] + atm["pmid"]) / spot) if atm and atm["cmid"] and atm["pmid"] and spot > 0 else None
    out["atm_iv"] = None
    if atm and T > 0:
        ivs = [v for v in (iv_fn(atm["cmid"], spot, atm["k"], T, r, "CE") if atm["cmid"] else None, iv_fn(atm["pmid"], spot, atm["k"], T, r, "PE") if atm["pmid"] else None) if v]
        out["atm_iv"] = sum(ivs) / len(ivs) if ivs else None
    out["skew"] = None
    if rows and T > 0:
        put = min(rows, key=lambda x: abs(x["k"] - spot * (1 - SKEW_OTM)))
        call = min(rows, key=lambda x: abs(x["k"] - spot * (1 + SKEW_OTM)))
        if put["k"] < spot < call["k"] and put["pmid"] and call["cmid"]:
            pv, cv = iv_fn(put["pmid"], spot, put["k"], T, r, "PE"), iv_fn(call["cmid"], spot, call["k"], T, r, "CE")
            out["skew"] = (pv - cv) if pv and cv else None
    # near-the-money open interest, for the writing reading: the strikes within the implied move
    band = (out["implied_move"] or 0.02) * spot
    out["near_coi"] = sum(x["coi"] for x in rows if abs(x["k"] - spot) <= band)
    out["near_poi"] = sum(x["poi"] for x in rows if abs(x["k"] - spot) <= band)
    return out


class MarketRead:
    """Keeps a quarter hour of each underlying's readings, so the read can say what CHANGED; and turns the readings into evidence and a probability."""

    def __init__(self, lookback_s: float = LOOKBACK_S):
        self.lookback = lookback_s
        self.hist: dict[str, list[tuple[float, dict]]] = {}
        self.last: dict[str, dict] = {}
        self.pending: dict[str, list[tuple[float, float, float]]] = {}    # (time, P(up), price) awaiting their outcome
        self.scored: dict[str, list[float]] = {}                            # [n, sum of squared errors] per underlying: the Brier score

    def _score(self, u: str, t: float, price: float | None, p: float) -> None:
        """CALIBRATION by a proper scoring rule: each read's P(up) against what the price did over the next look-back window, as the Brier score (mean of (P - outcome)^2;
        0.25 is a coin toss, lower is better). A move under BUILDUP_MIN_PX is no outcome. This is how the prior WEIGHTS will be judged."""
        if not price:
            return
        q = self.pending.setdefault(u, [])
        while q and t - q[0][0] >= self.lookback:
            t0, p0, px0 = q.pop(0)
            mv = price / px0 - 1
            if abs(mv) >= BUILDUP_MIN_PX:
                sc = self.scored.setdefault(u, [0, 0.0])
                sc[0] += 1
                sc[1] += (p0 - (1.0 if mv > 0 else 0.0)) ** 2
        if not q or t - q[-1][0] >= 60:
            q.append((t, p, price))

    def calibration(self) -> dict:
        """{underlying: {"n", "brier"}} and the pooled figure under "all"."""
        out = {u: {"n": n, "brier": round(e / n, 4)} for u, (n, e) in self.scored.items() if n}
        n, e = sum(v[0] for v in self.scored.values()), sum(v[1] for v in self.scored.values())
        if n:
            out["all"] = {"n": n, "brier": round(e / n, 4)}
        return out

    def _then(self, u: str, t: float) -> dict | None:
        """The earliest reading kept from within the look-back window: what the board looked like about a quarter of an hour ago."""
        h = self.hist.get(u) or []
        old = [x for ts, x in h if t - ts >= self.lookback * 0.5]
        return old[-1] if old else (h[0][1] if h and t - h[0][0] >= 60 else None)

    def update(self, u: str, t: float, snap, chain: dict, spot: float, T: float, r: float, iv_fn, fut_name: str | None = None, next_chain: dict | None = None,
               T_next: float | None = None, spot_name: str | None = None) -> dict:
        cr = chain_read(snap, chain, spot, T, r, iv_fn)
        fq = _q(snap, fut_name)
        fut, foi = (_mid(fq), _num(fq.get("oi"))) if fq else (None, None)
        sp = _num((_q(snap, spot_name) or {}).get("ltp")) if spot_name else None
        cur = {**cr, "spot": spot, "fut": fut, "foi": foi, "basis": ((fut / sp - 1) if fut and sp else None)}
        if next_chain and T_next:
            nxt = chain_read(snap, next_chain, spot, T_next, r, iv_fn)
            cur["term"] = (cur["atm_iv"] - nxt["atm_iv"]) if cur["atm_iv"] and nxt["atm_iv"] else None
        then = self._then(u, t)
        h = self.hist.setdefault(u, [])
        h.append((t, cur))
        while h and t - h[0][0] > self.lookback * 1.5:
            h.pop(0)
        read = self.evidence(cur, then)
        self._score(u, t, fut or spot, read["p_up"])
        self.last[u] = read
        return read

    @staticmethod
    def evidence(cur: dict, then: dict | None) -> dict:
        """Each reading as a signal and a reason; their weighted sum as log-odds; P(up)."""
        sig, why = {}, []
        spot = cur.get("spot")
        pcr = cur.get("pcr")
        if pcr is not None:
            sig["pcr"] = _clip((pcr - 1.0) / 0.4)
            if abs(sig["pcr"]) >= 0.5:
                why.append(f"put/call OI {pcr:.2f}")
        cw, pw = cur.get("call_wall"), cur.get("put_wall")
        if spot and cw and pw and cw > pw:
            pos = (spot - pw) / (cw - pw)                                               # 0 at the put wall, 1 at the call wall
            sig["walls"] = _clip(1 - 2 * pos)
            if abs(sig["walls"]) >= 0.5:
                why.append(f"near the {'put wall (support) ' + format(pw, 'g') if pos < 0.5 else 'call wall (resistance) ' + format(cw, 'g')}")
        mp = cur.get("max_pain")
        if spot and mp:
            sig["pain"] = _clip((mp - spot) / spot / 0.01)
        label = None
        if then:
            if pcr is not None and then.get("pcr") is not None:
                sig["pcr_chg"] = _clip((pcr - then["pcr"]) / 0.1)
                if abs(sig["pcr_chg"]) >= 0.5:
                    why.append(f"put/call OI {'up' if sig['pcr_chg'] > 0 else 'down'} {then['pcr']:.2f} to {pcr:.2f}")
            if cur.get("fut") and then.get("fut") and cur.get("foi") and then.get("foi"):
                label, sig["buildup"] = buildup(cur["fut"] / then["fut"] - 1, cur["foi"] / then["foi"] - 1)
                if label:
                    why.append(f"futures {label}")
            dc, dp = cur.get("near_coi", 0) - then.get("near_coi", 0), cur.get("near_poi", 0) - then.get("near_poi", 0)
            if dc > 0 or dp > 0:
                tot = (cur.get("near_coi", 0) + cur.get("near_poi", 0)) or 1.0
                sig["writing"] = _clip((dp - dc) / tot / 0.02)
                if abs(sig["writing"]) >= 0.5:
                    why.append("puts written near the money (support)" if sig["writing"] > 0 else "calls written near the money (resistance)")
            if cur.get("skew") is not None and then.get("skew") is not None:
                sig["skew_chg"] = _clip(-(cur["skew"] - then["skew"]) / 0.01)
                if abs(sig["skew_chg"]) >= 0.5:
                    why.append(f"protection {'dearer' if sig['skew_chg'] < 0 else 'cheaper'} (skew {then['skew'] * 100:+.1f} to {cur['skew'] * 100:+.1f} vol pts)")
            if cur.get("basis") is not None and then.get("basis") is not None:
                sig["basis_chg"] = _clip((cur["basis"] - then["basis"]) / 0.001)
        logit = sum(WEIGHTS[k] * v for k, v in sig.items())
        p = 1 / (1 + math.exp(-logit))
        r2 = lambda x, n=4: round(x, n) if isinstance(x, float) else x                 # noqa: E731
        return {"p_up": round(p, 3), "vote": 1 if p >= READ_VOTE_P else -1 if p <= 1 - READ_VOTE_P else 0, "why": why[:5], "signals": {k: round(v, 2) for k, v in sig.items()},
                "pcr": r2(pcr, 3), "max_pain": mp, "call_wall": cw, "put_wall": pw, "implied_move": r2(cur.get("implied_move")), "skew": r2(cur.get("skew")),
                "term": r2(cur.get("term")), "buildup": label, "event_priced": bool(cur.get("term") is not None and cur["term"] > 0.02)}
