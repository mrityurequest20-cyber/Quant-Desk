"""Laws, not strategies: is an effect found on two indices a property of option markets, or of those two histories?

A law is stated without an instrument and measured in units that don't care about the instrument: P&L in basis points
of the index, and the share of the premium sold that was kept. It is found on the discovery instruments, then tested
once on held-out instruments it never saw. The pooled test averages the held-out instruments within each expiry week,
so a shock that hits every index on the same day counts once, not five times.

expiry_eve_law_v1 (docs/prereg/expiry_eve_law_v1.json): L1, selling 20-delta options the night before expiry, on
- NSE's FINNIFTY, MIDCPNIFTY and NIFTYNXT50;
- BSE's SENSEX and BANKEX (from 2024).
NIFTY and BANKNIFTY are reported for reference.
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
from .edges import _split, hac_mean

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "prereg" / "expiry_eve_law_v1.json"
TABLES = ("fo_bhav", "bse_fo_bhav")


def load_spec(path: Path = SPEC_PATH) -> dict:
    raw = Path(path).read_bytes()
    spec = json.loads(raw)
    spec["_hash"] = hashlib.sha256(raw).hexdigest()[:12]
    return spec


def spot(opts: pd.DataFrame, symbol: str, official: pd.Series | None = None) -> pd.Series:
    """The index close by date: NSE's official close where given (`official`, from nse_index_close: v2), else the
    bhavcopy's underlying, else that day's nearest-expiry future's settle. That last is the index itself only when the
    future expires that day: on a weekly expiry it is the monthly future, basis and all (the flaw v2 fixes)."""
    o = opts[opts["symbol"] == symbol]
    und = o.dropna(subset=["underlying"]).groupby("date")["underlying"].median()
    f = o[(o["kind"] == "FUT") & (o["expiry"] >= o["date"])].copy()
    px = f["settle"] if "settle" in f else f["close"]
    f = f.assign(px=pd.to_numeric(px, errors="coerce").where(lambda x: x > 0, f["close"]))
    fut = f.sort_values("expiry").groupby("date")["px"].first()
    out = und.combine_first(fut)
    if official is not None and len(official):
        out = official.combine_first(out)
    return out.dropna().sort_index()


def lot_of(opts: pd.DataFrame, symbol: str, cfg=None) -> int:
    o = opts[(opts["symbol"] == symbol) & (opts["lot"] > 0)] if "lot" in opts else opts.iloc[:0]
    if len(o):
        return int(o["lot"].median())
    return int((cfg.instrument_spec(symbol).get("lot_size") if cfg is not None else 0) or 50)


def trades(opts: pd.DataFrame, symbol: str, spec: dict, fees_for=None, cfg=None, official=None) -> pd.DataFrame:
    strategies = {v["strategy"]: ([(int(q), r, float(d)) for q, r, d in v["legs"]], None)
                  for v in spec["structures"].values()}
    o = opts[(opts["symbol"] == symbol) & opts["kind"].isin(["CE", "PE"])]
    sp = spot(opts, symbol, official)
    if o.empty or sp.empty:
        return pd.DataFrame()
    lot = lot_of(opts, symbol, cfg)
    tr = W.build_trades(o, sp, symbol, fees_for(symbol, lot) if fees_for else None, lot=lot, strategies=strategies,
                        offsets=(1,))
    if tr.empty:
        return tr
    return tr.assign(bps=tr["pnl_pts"] / tr["S"] * 1e4, credit_bps=tr["credit_pts"] / tr["S"] * 1e4,
                     cost_bps=tr["cost_pts"] / tr["S"] * 1e4, lot=lot)


def summarize(g: pd.DataFrame) -> dict:
    g = g.sort_values("entry")
    x = g["bps"].to_numpy(dtype=float)
    m, t, _ = hac_mean(x)
    first, last = _split(pd.Series(x, index=pd.to_datetime(g["entry"])))
    srt = np.sort(x)
    k5 = max(1, int(round(0.05 * len(x))))
    return {"n": int(len(x)), "mean_bps": float(m), "t": float(t), "win": float((x > 0).mean()),
            "worst_bps": float(srt[0]), "cvar5_bps": float(srt[:k5].mean()), "credit_bps": float(g["credit_bps"].mean()),
            "kept": float(x.mean() / g["credit_bps"].mean()) if g["credit_bps"].mean() > 0 else float("nan"),
            "mean_first": float(first.mean()), "mean_last": float(last.mean()),
            "span": f"{g['entry'].min()} → {g['expiry'].max()}"}


def pooled(tr: pd.DataFrame) -> dict:
    """Held-out instruments averaged within each expiry week (ISO year-week of the expiry), then the weekly series."""
    wk = pd.to_datetime(tr["expiry"]).dt.strftime("%G-%V")
    weekly = tr.assign(wk=wk).groupby("wk")["bps"].mean().sort_index()
    m, t, _ = hac_mean(weekly.to_numpy(dtype=float))
    first, last = _split(weekly.set_axis(pd.RangeIndex(len(weekly))))
    return {"weeks": int(len(weekly)), "mean_bps": float(m), "t": float(t), "mean_first": float(first.mean()),
            "mean_last": float(last.mean())}


def evaluate(tr: pd.DataFrame, spec: dict) -> dict:
    held, disc = spec["held_out"]["instruments"], spec["discovery"]["instruments"]
    out = {"spec": spec["name"], "spec_hash": spec["_hash"], "spot_source": spec.get("spot_source", "bhavcopy"),
           "structures": {}}
    for key, v in spec["structures"].items():
        g = tr[tr["strategy"] == v["strategy"]] if len(tr) else tr
        rows = {s: summarize(x) for s, x in g.groupby("symbol") if len(x) >= 5} if len(g) else {}
        h = g[g["symbol"].isin(held)] if len(g) else g
        pool = pooled(h) if len(h) else None
        eligible = [s for s in held if s in rows and rows[s]["n"] >= 20]
        positive = [s for s in eligible if rows[s]["mean_bps"] > 0]
        replicated = bool(pool and pool["t"] > 1.645 and pool["mean_bps"] > 0 and eligible
                          and len(positive) >= 0.6 * len(eligible))
        candidates = [s for s in held if s in rows and rows[s]["n"] >= 30 and rows[s]["t"] > 1.645
                      and rows[s]["mean_first"] > 0 and rows[s]["mean_last"] > 0]
        out["structures"][key] = {"strategy": v["strategy"], "rows": rows, "pooled": pool, "eligible": eligible,
                                  "positive": positive, "replicated": replicated, "candidates": candidates,
                                  "discovery": {s: rows[s] for s in disc if s in rows}}
    return out


def fees_factory(cfg):
    """The desk's statutory fee model for one lot of an option on `sym`, or None without a config."""
    if cfg is None:
        return None
    from ..core.types import Instrument
    from ..execution.costs import CostModel
    costs, exp = CostModel(cfg), dt.date(2030, 1, 1)

    def fees_for(sym, lot):
        return lambda right, qty, price: costs.fees(Instrument.option(sym, exp, 1.0, right, lot), int(qty), float(price))[0]
    return fees_for


def all_trades(opts: pd.DataFrame, spec: dict, syms, fees_for=None, cfg=None, official: dict | None = None) -> pd.DataFrame:
    official = official or {}
    parts = [trades(opts, s, spec, fees_for, cfg, official.get(s)) for s in syms if len(opts) and (opts["symbol"] == s).any()]
    return pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else pd.DataFrame()


def load(folder: Path, spec: dict) -> pd.DataFrame:
    syms = spec["discovery"]["instruments"] + spec["held_out"]["instruments"]
    return W.load_options(folder, syms, TABLES, extra=("settle", "lot"))


def official_closes(folder: Path, spec: dict) -> dict:
    """{symbol: official close by date} when the spec takes its spot from NSE's official closes (v2), else {}."""
    if spec.get("spot_source") != "nse_index_close":
        return {}
    from ..data.audit import official_closes as oc
    ic = oc(folder)
    if ic.empty:
        raise FileNotFoundError(f"{spec['name']} needs nse_index_close_*.parquet in {folder}")
    return {s: g.assign(date=pd.to_datetime(g["date"]).dt.date).set_index("date")["close"].sort_index()
            for s, g in ic.groupby("symbol")}                        # keyed like the options' dates (datetime.date)


def run(folder: Path, cfg=None, spec: dict | None = None) -> tuple[dict, pd.DataFrame]:
    spec = spec or load_spec()
    syms = spec["discovery"]["instruments"] + spec["held_out"]["instruments"]
    tr = all_trades(load(folder, spec), spec, syms, fees_factory(cfg), cfg, official_closes(folder, spec))
    return evaluate(tr, spec), tr


def render(res: dict) -> str:
    def f(x, d=1):
        return "–" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:+,.{d}f}"
    out = [f"# Law L1 across instruments · {res['spec']} · spec {res['spec_hash']}", "",
           ("Index levels from NSE's official closes (nse_index_close). " if res.get("spot_source") == "nse_index_close" else "")
           + "Selling 20-delta options at the close the night before expiry, held to settlement; real bhavcopy prices. "
           "P&L in basis points of the index (instrument-neutral); 'kept' is the share of the premium sold that was "
           "kept. Discovery instruments are for reference; the test is on the held-out ones.", ""]
    for key, s in res["structures"].items():
        out += [f"## {key}: {s['strategy']}", "",
                "| instrument | role | n | mean bps | t | win | worst bps | CVaR5 bps | credit bps | kept | first ⅔ / last ⅓ | span |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for sym, r in s["rows"].items():
            role = "discovery" if sym in s["discovery"] else ("candidate ✅" if sym in s["candidates"] else "held out")
            out.append(f"| {sym} | {role} | {r['n']} | {f(r['mean_bps'], 2)} | {r['t']:.2f} | {r['win']:.0%} | "
                       f"{f(r['worst_bps'], 0)} | {f(r['cvar5_bps'], 0)} | {r['credit_bps']:.1f} | {r['kept']:.0%} | "
                       f"{f(r['mean_first'], 2)} / {f(r['mean_last'], 2)} | {r['span']} |")
        p = s["pooled"]
        out += ["", (f"Pooled held-out (weekly mean across instruments): {p['weeks']} weeks, mean {f(p['mean_bps'], 2)} bps, "
                     f"t {p['t']:.2f}, first ⅔ {f(p['mean_first'], 2)} / last ⅓ {f(p['mean_last'], 2)}." if p else
                     "Pooled held-out: no held-out trades."),
                f"Positive mean on {len(s['positive'])} of {len(s['eligible'])} held-out instruments with ≥ 20 trades.",
                f"**Verdict: L1 ({key}) {'REPLICATES' if s['replicated'] else 'does not replicate'}** on held-out "
                f"instruments; tape and forward-sleeve candidates: {', '.join(s['candidates']) or 'none'}.", ""]
    return "\n".join(out)
