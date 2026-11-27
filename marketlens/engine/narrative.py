"""Words for numbers: every card carries a plain-language reading ("simple") and the analyst's reading ("analyst").

Rules the sentences follow:
  * never a direction or a trade; say what is priced, how unusual it is, and what history says happened next
  * every "high"/"low" is against the instrument's own history, and says which history
  * numbers are shown the way a trader says them (vol points, % a day, index points)
"""
from __future__ import annotations

import math


def level(p: float | None) -> str:
    if p is None or not math.isfinite(p):
        return "unknown"
    if p < 0.10:
        return "very low"
    if p < 0.30:
        return "low"
    if p <= 0.70:
        return "normal"
    if p <= 0.90:
        return "high"
    return "very high"


def tone(p: float | None) -> str:
    """A colour key for the UI: how unusual (not good or bad)."""
    if p is None or not math.isfinite(p):
        return "muted"
    d = abs(p - 0.5)
    return "extreme" if d >= 0.4 else "elevated" if d >= 0.2 else "normal"


def pct(x, d=1):
    return "—" if x is None or not math.isfinite(x) else f"{x * 100:.{d}f}%"


def ordinal(p):
    if p is None or not math.isfinite(p):
        return "—"
    n = int(round(p * 100))
    n = min(max(n, 0), 100)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def daily(iv):
    return iv / math.sqrt(252)


def iv_card(name, iv30, p1y, pall, since, vix=None):
    simple = (f"Options on {name} are priced for moves of about {pct(daily(iv30), 2)} a day. "
              f"That is {level(p1y)} for {name} compared with the past year.")
    analyst = (f"30-day constant-maturity ATM IV {pct(iv30)}: {ordinal(p1y)} percentile of 1 year, "
               f"{ordinal(pall)} of all days since {since}.")
    if vix is not None:
        analyst += f" India VIX {vix:.2f} (VIX includes the wings, so it usually prints above ATM IV)."
    return {"simple": simple, "analyst": analyst, "tone": tone(p1y)}


def vrp_card(name, iv30, rv21, spread_p, rich_share, since):
    if iv30 is None or rv21 is None:
        return None
    gap = iv30 - rv21
    if gap > 0.005:
        s = (f"Options cost more than {name}'s recent actual movement justifies: they price {pct(iv30)} a year "
             f"while it has been moving at {pct(rv21)}.")
    elif gap < -0.005:
        s = (f"Options are cheap compared with how much {name} has actually been moving: they price {pct(iv30)} a year "
             f"while the last month realised {pct(rv21)}.")
    else:
        s = f"Options are priced close to how much {name} has really been moving (about {pct(iv30)} a year)."
    a = (f"IV30 - RV21 = {gap * 100:+.1f} vol points, {ordinal(spread_p)} percentile of history. "
         f"Since {since}, IV30 was above the volatility that actually followed over the next 21 sessions on "
         f"{pct(rich_share, 0)} of days: option sellers are usually paid a premium for carrying the risk, "
         f"and the gap is what that premium looks like today.")
    return {"simple": s, "analyst": a, "tone": tone(spread_p)}


def term_card(name, front_iv, back_iv, front_days, back_days, ev):
    if front_iv is None or back_iv is None:
        return None
    slope = back_iv - front_iv
    if slope < -0.01:
        s = (f"Near-term options on {name} are pricier than longer ones. The market expects something soon: an event, "
             f"or stress that it thinks will pass.")
    elif slope > 0.01:
        s = f"Longer-dated options on {name} cost more than near ones: the normal, calm shape."
    else:
        s = f"Near and far options on {name} are priced about the same: nothing special is expected soon."
    a = (f"Term structure: {front_days}d {pct(front_iv)} -> {back_days}d {pct(back_iv)} "
         f"({slope * 100:+.1f} vol pts). ")
    if ev:
        a += (f"Front-expiry variance above the forward curve, expressed as one day: about ±{pct(ev['event_move'], 1)} "
              f"against {pct(ev['normal_day_move'], 2)} on a normal day (forward vol {pct(ev['fwd_vol'])})"
              + (f"; the exchange calendar has results on {ev['cause_date']} inside that expiry." if ev.get("cause") == "results"
                 else "; no scheduled event in the data explains it."))
    return {"simple": s, "analyst": a, "tone": "elevated" if slope < -0.01 else "normal"}


def skew_card(name, rr, p):
    if rr is None or not math.isfinite(rr):
        return None
    if rr < 0:
        s = (f"Protection against a fall costs more than a bet on a rise, by {abs(rr) * 100:.1f} vol points. "
             f"That gap is {level(p)} for {name}.")
    else:
        s = (f"Upside calls cost more than downside puts, which is unusual. Traders are paying up for a sharp move "
             f"higher (this happens in squeezes and in stocks with a big pending event).")
    a = (f"25-delta risk reversal {rr * 100:+.2f} vol pts (front month), {ordinal(p)} percentile of history. "
         f"More negative = more demand for downside insurance relative to upside.")
    return {"simple": s, "analyst": a, "tone": tone(p)}


def move_card(name, exp, days, move, F, inside, n, since):
    lo, hi = F * (1 - move), F * (1 + move)
    s = (f"Until {exp} ({days} days), options price {name} to move about ±{pct(move, 1)}, roughly "
         f"{lo:,.0f} to {hi:,.0f}.")
    if inside is not None:
        s += f" In the past, the price ended inside the range priced this way {pct(inside, 0)} of the time."
    a = (f"ATM straddle / forward = {pct(move, 2)} (forward {F:,.1f}). Scored on {n:,} days since {since} against the "
         f"official close on each expiry; a straddle is the market's mean absolute move, so about 57% inside is what "
         f"a fair price would give.")
    return {"simple": s, "analyst": a, "tone": "normal"}


def oi_card(name, prof, spot, pcr_p):
    if not prof:
        return None
    p0 = prof[0]
    cw, pw = p0.get("call_wall"), p0.get("put_wall")
    parts = []
    if cw:
        parts.append(f"the biggest pile of call positions is at {cw:,.0f} ({(cw / spot - 1) * 100:+.1f}% away)")
    if pw:
        parts.append(f"the biggest pile of put positions is at {pw:,.0f} ({(pw / spot - 1) * 100:+.1f}%)")
    s = f"For the {p0['expiry']} expiry, " + " and ".join(parts) + "." if parts else "No open interest concentration."
    s += " Option sellers defend these levels, so price often slows near them, but they shift as positions change."
    a = (f"Front-expiry PCR (OI) {p0['pcr']:.2f}" if p0.get("pcr") else "PCR n/a")
    a += (f"; all-expiry OI PCR at the {ordinal(pcr_p)} percentile of history." if pcr_p is not None else ".")
    a += (f" Today's change: calls {p0['call_add']:+,.0f}, puts {p0['put_add']:+,.0f} (OI units, i.e. shares or index quantity). A high PCR in India "
          f"mostly reflects put writing, so it is read as crowding, not as a signal.")
    return {"simple": s, "analyst": a, "tone": tone(pcr_p)}


def futures_card(name, row, carry_p, recent):
    if row is None:
        return None
    carry = row.get("carry")
    b = row.get("basis")
    s = (f"{name} futures trade {abs(b):,.1f} points {'above' if b >= 0 else 'below'} the price itself. ")
    if carry is not None and math.isfinite(carry):
        s += (f"That works out to {pct(carry)} a year: "
              + ("about the cost of money, so nothing unusual." if 0.04 <= carry <= 0.085 else
                 "richer than the cost of money: buyers are paying up to hold longs." if carry > 0.085 else
                 "below the cost of money: hedgers or short sellers are leaning on the futures."))
    a = (f"Near-month basis {b:+,.1f}, annualised carry {pct(carry)} ({ordinal(carry_p)} percentile). "
         f"Last 5 sessions (price x OI): {', '.join(recent)}. Build-up labels describe what happened to positions; "
         f"they do not say who is right.")
    return {"simple": s, "analyst": a, "tone": tone(carry_p)}


def realised_card(name, rv21, p, rv5, rv63, comp_p):
    s = f"{name} has actually been moving about {pct(daily(rv21), 2)} a day this past month: {level(p)} for it."
    if rv5 is not None and rv63 and rv5 / rv63 < 0.6:
        s += " The last week has been unusually quiet. Quiet spells tend to end with bigger moves, in either direction."
    a = (f"RV21 {pct(rv21)} ({ordinal(p)} pct), RV5 {pct(rv5)}, RV63 {pct(rv63)}; "
         f"RV5/RV63 compression at the {ordinal(comp_p)} percentile.")
    return {"simple": s, "analyst": a, "tone": tone(p)}


def event_sentence(name, ev):
    if ev.get("cause") == "results":
        return (f"The option curve prices {name}'s results ({ev['cause_date']}) at about ±{pct(ev['event_move'], 1)} on "
                f"the day, against {pct(ev['normal_day_move'], 2)} on a normal day.")
    return (f"Near-term {name} options carry an extra premium: the expiry to {ev['front_expiry']} prices one day worth "
            f"about ±{pct(ev['event_move'], 1)}, against {pct(ev['normal_day_move'], 2)} normally. No scheduled event "
            f"in the data explains it: the market is paying for near-term risk.")
