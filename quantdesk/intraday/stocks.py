"""F&O stocks where options can actually be traded: ranked by how liquid their near-month options are, from the
daily bhavcopy (warehouse table `fo_stocks`), with what one position would cost this account.

Liquidity, per stock, as the median over the last `days` sessions:
* **premium traded** in near-month options, ₹ (a fill near the mid needs other people trading the same strikes);
* **active strikes**: near-month strikes that traded at least 100 contracts (a spread needs two of them);
* **futures contracts** and open interest (the hedge and the flow read).
A stock qualifies with at least 10 active strikes and ₹5 crore of premium a day. It is ranked by premium traded.

What it costs: the narrowest defined-risk position is one lot of a debit spread one strike wide at the money,
whose cost (and worst loss) is about half the strike step × the lot. RELIANCE (lot 500, ₹10 strikes) is about
₹2,500 a lot: 12.5% of a ₹20,000 account, over the desk's 8% risk budget (`intraday.risk.risk_per_trade`). So most
stock options are watch-list material at this size, and the ranking says which ones fit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_STRIKES = 10
MIN_PREMIUM = 5e7                # ₹5 crore of near-month premium a day


def rank(fo_stocks: pd.DataFrame, days: int = 20, top: int = 25) -> pd.DataFrame:
    """The most liquid F&O stocks, most liquid first (medians over each stock's last `days` sessions)."""
    if fo_stocks is None or fo_stocks.empty:
        return pd.DataFrame()
    df = fo_stocks.copy()
    df["date"] = pd.to_datetime(df["date"])
    last = sorted(df["date"].unique())[-days:]
    df = df[df["date"].isin(last)]
    g = df.groupby("symbol")
    out = pd.DataFrame({
        "sessions": g.size(),
        "premium_cr": g["opt_premium"].median() / 1e7,
        "active_strikes": g["active_strikes"].median(),
        "opt_contracts": g["opt_contracts"].median(),
        "fut_contracts": g["fut_contracts"].median(),
        "fut_oi": g["fut_oi"].median(),
        "atm_straddle": g["atm_straddle"].median(),
        "lot": g["lot"].last(),
        "price": g["underlying"].last(),
        "strike_step": g["strike_step"].last(),
        **{c: g[c].last() for c in ("atm_call", "atm_put", "otm2_call", "otm2_put") if c in df.columns},
    })
    out["liquid"] = (out["active_strikes"] >= MIN_STRIKES) & (out["premium_cr"] * 1e7 >= MIN_PREMIUM)
    out["min_spread_risk"] = 0.5 * out["strike_step"] * out["lot"]          # one lot, one strike wide, at the money
    out["lot_notional"] = out["lot"] * out["price"]
    out = out.sort_values(["liquid", "premium_cr"], ascending=[False, False])
    return out.head(top)


def fits(row, capital: float, max_loss_frac: float) -> tuple[bool, str]:
    """Can the account hold the smallest defined-risk position in this stock within its loss budget?"""
    r = float(row["min_spread_risk"])
    if not r == r:
        return False, "no strike step known"
    budget = capital * max_loss_frac
    pct = r / capital
    if r <= budget:
        return True, f"one lot of a 1-strike spread risks ≈₹{r:,.0f} ({pct:.1%} of the account)"
    return False, f"one lot of a 1-strike spread risks ≈₹{r:,.0f} ({pct:.1%}), over the ₹{budget:,.0f} budget"


def fits_long(row, capital: float, max_loss_frac: float, outlay_frac: float = 0.35, stop: float = 0.30) -> tuple[bool, str]:
    """Can the account buy one lot of a call or put: the premium within the outlay cap, and the loss at the premium stop
    within the risk budget? Tries the at-the-money option, then the one two strikes out (cheaper, lower delta)."""
    lot = float(row.get("lot") or 0)
    best = None
    for col, what in (("atm_call", "ATM call"), ("atm_put", "ATM put"), ("otm2_call", "call 2 strikes out"),
                      ("otm2_put", "put 2 strikes out")):
        prem = row.get(col)
        if prem is None or not prem == prem or prem <= 0 or not lot:
            continue
        cost = prem * lot
        if cost <= capital * outlay_frac and cost * stop <= capital * max_loss_frac:
            if best is None or (what.startswith("ATM") and not best[1].startswith("ATM")):
                best = (cost, what, prem)
    if best is None:
        cheapest = min((row.get(c) for c in ("otm2_call", "otm2_put") if row.get(c) == row.get(c) and row.get(c)), default=None)
        return False, (f"cheapest option one lot ≈₹{cheapest * lot:,.0f} (stop at {stop:.0%}: ₹{cheapest * lot * stop:,.0f})"
                       if cheapest else "no option premiums in the data")
    cost, what, prem = best
    return True, f"{what} ₹{prem:,.2f} × {lot:,.0f} = ₹{cost:,.0f} a lot; {stop:.0%} stop risks ₹{cost * stop:,.0f}"


def table(ranked: pd.DataFrame, capital: float, max_loss_frac: float) -> list[str]:
    lines = [f"{'stock':<12}{'premium ₹cr':>12}{'strikes':>9}{'fut ctr':>9}{'straddle':>10}{'lot':>7}{'price':>10}  fits ₹{capital:,.0f}?"]
    for sym, r in ranked.iterrows():
        ok, why = fits(r, capital, max_loss_frac)
        lok, lwhy = fits_long(r, capital, max_loss_frac) if "atm_call" in r.index else (False, "")
        lines.append(f"{sym:<12}{r.premium_cr:>12,.1f}{r.active_strikes:>9.0f}{r.fut_contracts:>9,.0f}"
                     f"{(r.atm_straddle if r.atm_straddle == r.atm_straddle else np.nan):>10.2%}{r.lot:>7,.0f}{r.price:>10,.1f}  "
                     + (("BUY OK: " + lwhy) if lok else ("spread ok: " + why) if ok else ("no: " + (lwhy or why)))
                     + ("" if r.liquid else " · below the liquidity bar"))
    return lines
