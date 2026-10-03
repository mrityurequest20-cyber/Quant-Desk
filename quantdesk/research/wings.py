"""expiry_wings_v1 (docs/prereg/expiry_wings_v1.json): can far wings cap the expiry-eve strangle's tail and keep its edge?

The strangle sold the session before expiry is the one effect that survived costs in 2019–26 NSE prices. It earns
on ordinary days and gives most of it back on a few shock days: 2% of BANKNIFTY trades lost ₹2.06L of a ₹3.52L total
(Covid, the Ukraine invasion, HDFC Bank's results). Those days are mostly unpredictable, so no filter removes them.
A wing bought far out of the money costs little at one day to expiry, and it turns "unlimited" into a known number.

This study runs three wing distances against the two registered sleeves:
- same conventions (warehouse_research.build_trades);
- sized by a per-trade loss budget at ₹5L;
- the selection rule fixed in the spec before any number was seen.

It also shows each variant on the strangle's worst days, which is the insurance actually paying out.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import warehouse_research as W
from .edges import LOT, _split, hac_mean

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "prereg" / "expiry_wings_v1.json"


def load_spec(path: Path = SPEC_PATH) -> dict:
    raw = Path(path).read_bytes()
    spec = json.loads(raw)
    spec["_hash"] = hashlib.sha256(raw).hexdigest()[:12]
    return spec


def strategies(spec: dict) -> dict:
    """{strategy name: (legs, None)} in build_trades' format, from the spec."""
    return {v["strategy"]: ([(int(q), r, float(d)) for q, r, d in v["legs"]], None) for v in spec["variants"].values()}


def summarize(tr: pd.DataFrame, symbol: str, key: str, spec: dict) -> dict | None:
    v = spec["variants"][key]
    lot = LOT[symbol]
    g = tr[(tr["symbol"] == symbol) & (tr["strategy"] == v["strategy"])].sort_values("entry")
    if len(g) < 20:
        return None
    x = g["pnl_pts"].to_numpy(dtype=float) * lot
    m, t, _ = hac_mean(x)
    srt = np.sort(x)
    k5 = max(1, int(round(0.05 * len(x))))
    first, last = _split(pd.Series(x, index=pd.to_datetime(g["entry"])))
    ml = g["max_loss_pts"].to_numpy(dtype=float) * lot
    defined = bool(np.isfinite(ml).any())
    acct = spec["account"]
    budget = acct["equity"] * acct["per_trade_loss_budget"]
    p01 = float(np.quantile(x, 0.01))
    basis = float(np.nanmedian(ml)) if defined else -p01
    lots = int(budget // basis) if basis > 0 else 0
    per_year = lots * m * acct["trades_per_year_now"][symbol]
    years = g.assign(y=pd.to_datetime(g["entry"]).dt.year, rs=x).groupby("y")["rs"].sum()
    return {"symbol": symbol, "key": key, "strategy": v["strategy"], "role": v["role"], "n": int(len(x)),
            "mean": float(m), "sd": float(x.std(ddof=1)), "t": float(t), "win": float((x > 0).mean()),
            "worst": float(srt[0]), "p01": p01, "cvar5": float(srt[:k5].mean()),
            "max_loss_median": float(np.nanmedian(ml)) if defined else None,
            "credit": float(g["credit_pts"].mean() * lot), "mean_first": float(first.mean()), "mean_last": float(last.mean()),
            "first_span": f"{first.index.min():%Y-%m}→{first.index.max():%Y-%m}",
            "last_span": f"{last.index.min():%Y-%m}→{last.index.max():%Y-%m}",
            "by_year": {int(y): round(float(s)) for y, s in years.items()},
            "lots": lots, "size_basis": basis, "per_year": float(per_year), "worst_at_size": float(lots * srt[0])}


def select(rows: list[dict]) -> dict:
    """The spec's rule, per index: t ≥ 2 and a positive mean in both parts; the most rupees a year at ₹5L wins."""
    out = {}
    for sym in sorted({r["symbol"] for r in rows}):
        ok = [r for r in rows if r["symbol"] == sym and r["role"] == "candidate" and r["t"] >= 2
              and r["mean_first"] > 0 and r["mean_last"] > 0]
        out[sym] = max(ok, key=lambda r: r["per_year"])["key"] if ok else None
    return out


def shock_days(tr: pd.DataFrame, symbol: str, spec: dict, n: int = 6) -> pd.DataFrame:
    """The strangle's n worst expiries, and what every variant made or lost on each (₹ per lot)."""
    lot = LOT[symbol]
    names = {v["strategy"]: k for k, v in spec["variants"].items()}
    g = tr[(tr["symbol"] == symbol) & tr["strategy"].isin(names)]
    wide = g.assign(rs=g["pnl_pts"] * lot, key=g["strategy"].map(names)).pivot_table(
        index="expiry", columns="key", values="rs", aggfunc="first")
    if "B0" not in wide:
        return pd.DataFrame()
    moves = g.drop_duplicates("expiry").set_index("expiry").eval("(S_T / S - 1) * 100").rename("move_%")
    return wide.join(moves).nsmallest(n, "B0")


def build(opts: pd.DataFrame, spots: dict, spec: dict, fees_for=None) -> pd.DataFrame:
    parts = []
    for sym, sp in spots.items():
        o = opts[(opts["symbol"] == sym) & opts["kind"].isin(["CE", "PE"])]
        if len(o):
            parts.append(W.build_trades(o, sp, sym, fees_for(sym) if fees_for else None, strategies=strategies(spec),
                                        offsets=(1,)))
    return pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else pd.DataFrame()


def run(folder: Path, daily: dict, cfg=None, spec: dict | None = None) -> dict:
    spec = spec or load_spec()
    opts = W.load_options(folder)
    fees_for = None
    if cfg is not None:
        from ..core.types import Instrument
        from ..execution.costs import CostModel
        costs, exp = CostModel(cfg), dt.date(2030, 1, 1)

        def fees_for(sym):
            return lambda right, qty, price: costs.fees(Instrument.option(sym, exp, 1.0, right, LOT[sym]), int(qty), float(price))[0]
    spots = {s: W.spot_series(opts, s, daily.get(s)) for s in ("NIFTY", "BANKNIFTY") if len(opts) and (opts["symbol"] == s).any()}
    tr = build(opts, spots, spec, fees_for)
    return evaluate(tr, spec)


def evaluate(tr: pd.DataFrame, spec: dict) -> dict:
    rows = [r for sym in ("NIFTY", "BANKNIFTY") for key in spec["variants"]
            if (r := summarize(tr, sym, key, spec)) is not None] if len(tr) else []
    return {"spec": spec["name"], "spec_hash": spec["_hash"], "rows": rows, "selected": select(rows),
            "shocks": {s: shock_days(tr, s, spec) for s in ("NIFTY", "BANKNIFTY")} if len(tr) else {},
            "span": f"{min(tr['entry'])} → {max(tr['expiry'])}" if len(tr) else "no data", "trades": tr}


def render(res: dict) -> str:
    def rs(x):
        return "–" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"₹{x:+,.0f}"
    out = [f"# Far wings on the expiry-eve sale · {res['spec']} · spec {res['spec_hash']}", "",
           f"Real NSE bhavcopy, {res['span']}; entry at the close one session before expiry, held to settlement; ₹ per lot "
           "after spreads, fees and exercise STT. 3 new candidates on top of the original study's 40 configurations.", ""]
    for sym in ("NIFTY", "BANKNIFTY"):
        rows = [r for r in res["rows"] if r["symbol"] == sym]
        if not rows:
            continue
        out += [f"## {sym}", "",
                "| variant | n | mean | t | win | worst | 1% | CVaR 5% | max loss | credit | first ⅔ / last ⅓ | lots @₹5L | ₹/yr @₹5L | worst @size |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for r in rows:
            mark = " ✅" if res["selected"].get(sym) == r["key"] else ""
            out.append(f"| {r['key']} {r['strategy']}{mark} | {r['n']} | {rs(r['mean'])} | {r['t']:.2f} | {r['win']:.0%} | "
                       f"{rs(r['worst'])} | {rs(r['p01'])} | {rs(r['cvar5'])} | {rs(r['max_loss_median'])} | ₹{r['credit']:,.0f} | "
                       f"{rs(r['mean_first'])} / {rs(r['mean_last'])} | {r['lots']} | {rs(r['per_year'])} | {rs(r['worst_at_size'])} |")
        sh = res["shocks"].get(sym)
        if sh is not None and len(sh):
            cols = [c for c in ("B0", "A0", "W5", "W3", "W2") if c in sh]
            out += ["", "The strangle's worst expiries, and each variant on the same day (₹/lot):", "",
                    "| expiry | move | " + " | ".join(cols) + " |", "|---|---:|" + "---:|" * len(cols)]
            for e, row in sh.iterrows():
                out.append(f"| {e} | {row['move_%']:+.1f}% | " + " | ".join(rs(row[c]) for c in cols) + " |")
        out += ["", "By year (₹/lot): " + "; ".join(f"{r['key']} " + ", ".join(f"{y}: {v:+,}" for y, v in r["by_year"].items())
                                                    for r in rows), ""]
    sel = res["selected"]
    out += ["## Selection (rule fixed in the spec)", ""] + [
        f"- {s}: " + (f"**{k}** becomes sleeve C (forward test on real quotes, expiry_seller_v2)" if k else
                      "no candidate qualified; sleeve A stays as registered") for s, k in sel.items()]
    return "\n".join(out)
