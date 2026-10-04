"""Can the warehouse be trusted? An audit of the option tables against an independent calendar and the exchange's own
settlement values, so a study's numbers can be traced to complete, consistent data.

**The calendar.** NSE's official index-close file (nse_index_close) exists exactly on NSE trading days, so it is the
expected-days list. Where it is missing, the union of days any table has stands in.

For each option table (fo_bhav: NSE index options and futures; bse_fo_bhav: BSE's):
- **coverage:** expected trading days versus days present: the missing ones, and any file on a non-trading day;
- **partial files:** days whose row count for a symbol is under half its 20-day median;
- **duplicates** on the table's key;
- **contracts:**
  - an expiry that isn't a trading day;
  - rows after their own expiry;
  - expiries with no rows on the expiry day itself (nothing to settle from);
  - negative prices, non-positive strikes;
  - traded closes outside the day's low–high range;
- **closes that are not trades:** the share of rows with a close but no contracts traded (theoretical prices);
- **lot changes** per symbol, which must match the exchange's circulars.

**Settlement**, the anomalies that matter most for an expiry study:
- the bhavcopy's `underlying` against NSE's official close;
- expiring options' settle price against their intrinsic value at the official close;
- on days without an `underlying` column (NSE before 8 Jul 2024), how far the nearest future's settle sits from the
  official close (the basis), split by monthly expiry days (where the future itself expires and settles at the index)
  and weekly expiry days (where it doesn't);
- for BSE, how many expiring options carry no price (the file puts the index value in their price columns).

**NSE vs BSE normalisation:** the columns and types the two tables share and where their conventions still differ.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from . import warehouse as W

OPTION_TABLES = ("fo_bhav", "bse_fo_bhav")
COLS = ["date", "symbol", "kind", "expiry", "strike", "high", "low", "close", "settle", "underlying", "contracts", "lot", "src"]


def load(folder: Path, table: str, cols=None) -> pd.DataFrame:
    files = sorted(Path(folder).glob(f"{table}_*.parquet"))
    if not files:
        return pd.DataFrame()
    import pyarrow.parquet as pq
    parts = []
    for f in files:
        have = pq.ParquetFile(f).schema.names
        parts.append(pd.read_parquet(f, columns=[c for c in (cols or have) if c in have]))
    df = pd.concat(parts, ignore_index=True)
    for c in ("date", "expiry"):
        if c in df:
            df[c] = pd.to_datetime(df[c]).dt.normalize()
    return df


def calendar(folder: Path) -> tuple[list[pd.Timestamp], str]:
    ic = load(folder, "nse_index_close", ["date"])
    if len(ic):
        return sorted(pd.to_datetime(ic["date"].unique())), "nse_index_close"
    days = set()
    for t in OPTION_TABLES:
        days |= set(pd.to_datetime(load(folder, t, ["date"]).get("date", pd.Series(dtype="datetime64[ns]")).unique()))
    return sorted(days), "union of the option tables (no index-close file yet)"


def official_closes(folder: Path) -> pd.DataFrame:
    ic = load(folder, "nse_index_close", ["date", "symbol", "close"])
    return ic[ic["symbol"].astype(str) != ""] if len(ic) else ic


def _coverage(df: pd.DataFrame, days: list, start=None) -> dict:
    present = set(pd.to_datetime(df["date"].unique()))
    first, last = min(present), max(present)
    first = max(first, pd.Timestamp(start)) if start else first
    expected = {d for d in days if first <= d <= last}
    missing = sorted(expected - present)
    extra = sorted(d for d in present - expected if days and first <= d <= max(days))
    return {"first": str(first.date()), "last": str(last.date()), "expected": len(expected),
            "present": len(present & expected), "missing": [str(d.date()) for d in missing],
            "on_non_trading_days": [str(d.date()) for d in extra]}


def _partial_days(df: pd.DataFrame) -> list[dict]:
    out = []
    o = df[df["kind"].isin(["CE", "PE"])]
    for sym, g in o.groupby("symbol"):
        n = g.groupby("date").size().sort_index()
        med = n.rolling(20, min_periods=10).median().shift(1)
        bad = n[(med > 0) & (n < 0.5 * med)]
        out += [{"symbol": sym, "date": str(d.date()), "rows": int(v), "median": float(med[d])} for d, v in bad.items()]
    return out


def _contracts(df: pd.DataFrame, days: list) -> dict:
    o = df[df["kind"].isin(["CE", "PE"])]
    dayset = set(days)
    last = df["date"].max()
    exps = o[["symbol", "expiry"]].drop_duplicates()
    past = exps[exps["expiry"] <= last]
    on_day = set(zip(o.loc[o["date"] == o["expiry"], "symbol"], o.loc[o["date"] == o["expiry"], "expiry"]))
    traded = o[(o["contracts"] > 0) & (o["high"] > 0)]
    lots = []
    if "lot" in df:
        for sym, g in df[df["lot"] > 0].groupby("symbol"):
            s = g.groupby("date")["lot"].median().sort_index()
            ch = s[s != s.shift()].iloc[1:]
            lots += [{"symbol": sym, "date": str(d.date()), "lot": float(v), "was": float(s[s.index < d].iloc[-1])}
                     for d, v in ch.items()]
    return {
        "expiries": int(len(past)),
        "expiry_not_trading_day": [f"{s} {e.date()}" for s, e in past.itertuples(index=False) if days and e not in dayset
                                   and e >= min(days)],
        "rows_after_expiry": int((o["date"] > o["expiry"]).sum()),
        "expiries_without_expiry_day_rows": [f"{s} {e.date()}" for s, e in past.itertuples(index=False)
                                             if (s, e) not in on_day],
        "expiry_day_gaps": _classify_gaps(o, past, on_day, dayset),
        "negative_prices": int((o[["close", "settle"]] < 0).any(axis=1).sum()),
        "bad_strikes": int((o["strike"] <= 0).sum()),
        "close_outside_range": int(((traded["close"] > traded["high"] + 1e-6) | (traded["close"] < traded["low"] - 1e-6)).sum()),
        "theoretical_close_share": float(((o["close"] > 0) & (o["contracts"] <= 0)).mean()) if len(o) else 0.0,
        "lot_changes": lots,
    }



def _classify_gaps(o: pd.DataFrame, past: pd.DataFrame, on_day: set, dayset: set) -> dict:
    """Why an expiry has no rows dated on it:
    - holiday_shifted: the nominal expiry is a holiday, and the exchange settled it the trading day before;
    - redated: the contracts stop appearing more than 3 days before the nominal date, because the exchange moved
      the expiry weekday and relisted them under a new date (FINNIFTY Oct 2021, MIDCPNIFTY 2023, NIFTY and
      BANKNIFTY Sep 2025);
    - missing: neither; data that should be there and isn't."""
    last_seen = o.groupby(["symbol", "expiry"])["date"].max()
    out = {"holiday_shifted": [], "redated": [], "missing": []}
    for s_, e in past.itertuples(index=False):
        if (s_, e) in on_day:
            continue
        seen = last_seen.get((s_, e))
        if dayset and e not in dayset:
            out["holiday_shifted"].append(f"{s_} {e.date()}")
        elif seen is not None and (e - seen).days > 3:
            out["redated"].append(f"{s_} {e.date()}")
        else:
            out["missing"].append(f"{s_} {e.date()}")
    return out

def _settlement(df: pd.DataFrame, ic: pd.DataFrame, monthly_expiries: dict) -> dict:
    """NSE: the bhavcopy against NSE's own official closes."""
    out = {}
    if ic.empty:
        return {"note": "no nse_index_close table: settlement could not be checked"}
    off = ic.set_index(["symbol", "date"])["close"]
    und = df.dropna(subset=["underlying"]).groupby(["symbol", "date"])["underlying"].median()
    j = pd.concat([und.rename("und"), off.rename("off")], axis=1, join="inner")
    if len(j):
        dev = (j["und"] / j["off"] - 1).abs()
        out["underlying_vs_official"] = {"days": int(len(j)), "max_pct": float(dev.max() * 100),
                                         "over_0.05pct": int((dev > 5e-4).sum())}
    offd = off.rename("off").reset_index()
    o = df[df["kind"].isin(["CE", "PE"]) & (df["date"] == df["expiry"])].merge(offd, on=["symbol", "date"])
    o = o.dropna(subset=["off", "settle"])
    if len(o):
        # an expiring option's settle is the index's final settlement value (what it exercises against); old-format
        # files before 2021 often carry 0 there instead
        carried = o[o["settle"] > 0]
        dev = (carried["settle"] / carried["off"] - 1).abs()
        by_year = carried.assign(ok=dev < 1e-4).groupby(carried["date"].dt.year)["ok"].mean()
        out["expiring_settle_is_official_close"] = {
            "contracts": int(len(o)), "carry_a_value": int(len(carried)),
            "match_within_0.01pct": float((dev < 1e-4).mean()) if len(carried) else None,
            "mismatched_symbol_days": int(carried.loc[dev >= 1e-4, ["symbol", "date"]].drop_duplicates().shape[0]),
            "match_by_year": {int(k): round(float(v), 4) for k, v in by_year.items()}}
    f = df[(df["kind"] == "FUT") & (df["expiry"] >= df["date"])].sort_values("expiry").groupby(["symbol", "date"]).first()
    has_und = df.groupby(["symbol", "date"])["underlying"].count()
    no_und = has_und[has_und == 0].index
    exp_days = set(zip(df.loc[df["kind"].isin(["CE", "PE"]), "symbol"], df.loc[df["kind"].isin(["CE", "PE"]), "expiry"]))
    b = f.loc[f.index.intersection(no_und)].reset_index().merge(offd, on=["symbol", "date"])
    rows = []
    if len(b):
        px = b["settle"].where(b["settle"] > 0, b["close"])
        b = b.assign(basis_pct=(px / b["off"] - 1) * 100, future_expires=b["expiry"] == b["date"],
                     expiry_day=[(s_, d_) in exp_days or d_ in monthly_expiries.get(s_, set())
                                 for s_, d_ in zip(b["symbol"], b["date"])])
        rows = b[["symbol", "date", "basis_pct", "future_expires", "expiry_day"]].to_dict("records")
    if rows:
        b = pd.DataFrame(rows)
        ex = b[b["expiry_day"]]

        def stats(x):
            return {"days": int(len(x)), "mean_pct": float(x["basis_pct"].mean()) if len(x) else None,
                    "max_abs_pct": float(x["basis_pct"].abs().max()) if len(x) else None}
        out["futures_fallback_basis"] = {
            "all_days": stats(b),
            "expiry_days_future_expires": stats(ex[ex["future_expires"]]),
            "expiry_days_future_does_not_expire": stats(ex[~ex["future_expires"]]),
            "by_symbol_weekly_expiry_days": {s: stats(g) for s, g in ex[~ex["future_expires"]].groupby("symbol")},
        }
    return out


def _bse_quirk(df: pd.DataFrame) -> dict:
    o = df[df["kind"].isin(["CE", "PE"]) & (df["date"] == df["expiry"])]
    return {"expiring_rows": int(len(o)), "expiring_rows_without_price": int(o["close"].isna().sum())}


def schema(nse: pd.DataFrame, bse: pd.DataFrame) -> dict:
    both = [c for c in nse.columns if c in bse.columns]
    dt_diff = {c: (str(nse[c].dtype), str(bse[c].dtype)) for c in both if str(nse[c].dtype) != str(bse[c].dtype)}

    def steps(df):
        o = df[df["kind"].isin(["CE", "PE"])]
        return {s: float(np.median(np.diff(np.unique(g["strike"].to_numpy()))) or 0) for s, g in o.groupby("symbol")
                if g["strike"].nunique() > 2}
    return {"only_nse": [c for c in nse.columns if c not in bse.columns],
            "only_bse": [c for c in bse.columns if c not in nse.columns],
            "dtype_differences": dt_diff,
            "src": {"nse": sorted(nse["src"].dropna().unique().tolist()), "bse": sorted(bse["src"].dropna().unique().tolist())},
            "strike_steps": {**steps(nse), **steps(bse)},
            "conventions": [
                "both tables: one row per contract per day, prices in index points, `contracts` = contracts traded, "
                "`oi` in units (shares), `lot` = the contract's lot that day (NSE's old pre-Jul-2024 format has no lot)",
                "BSE's expiring options carry the index value in their price columns on expiry day; the parser blanks "
                "them, so BSE settles on the expiring future or the index, never on those rows",
                "NSE's `underlying` exists only from 8 Jul 2024 (UDiFF); BSE's file always has it",
            ]}


def run(folder: Path) -> dict:
    folder = Path(folder)
    days, source = calendar(folder)
    ic = official_closes(folder)
    res = {"generated": str(dt.date.today()), "calendar": {"source": source, "days": len(days),
                                                          "first": str(days[0].date()) if days else None,
                                                          "last": str(days[-1].date()) if days else None},
           "tables": {}}
    frames = {}
    for t in OPTION_TABLES:
        df = load(folder, t, COLS)
        if df.empty:
            continue
        frames[t] = df
        key = W.TABLES[t][1]
        r = {"rows": int(len(df)), "symbols": sorted(df["symbol"].unique().tolist()),
             "coverage": _coverage(df, days), "duplicates": int(df.duplicated(key).sum()),
             "partial_days": _partial_days(df), "contracts": _contracts(df, days)}
        if t == "fo_bhav":
            monthly = {s: set(pd.to_datetime(g.loc[g["kind"] == "FUT", "expiry"].unique())) for s, g in df.groupby("symbol")}
            r["settlement"] = _settlement(df, ic, monthly)
        else:
            r["settlement"] = _bse_quirk(df)
        res["tables"][t] = r
    if len(frames) == 2:
        res["schema"] = schema(frames["fo_bhav"], frames["bse_fo_bhav"])
    res["verdict"] = verdict(res)
    return res


def verdict(res: dict) -> list[str]:
    """Plain findings, worst first: what a study must account for."""
    out = []
    for t, r in res["tables"].items():
        c, k = r["coverage"], r["contracts"]
        if c["missing"]:
            out.append(f"{t}: {len(c['missing'])} trading day(s) missing ({', '.join(c['missing'][:6])}"
                       f"{' …' if len(c['missing']) > 6 else ''})")
        if r["duplicates"]:
            out.append(f"{t}: {r['duplicates']:,} duplicate rows on the key")
        if k["rows_after_expiry"]:
            out.append(f"{t}: {k['rows_after_expiry']:,} rows dated after their expiry")

        gaps = k.get("expiry_day_gaps", {})
        if gaps.get("missing"):
            out.append(f"{t}: {len(gaps['missing'])} expiries have no rows on the expiry day and no explanation "
                       f"({', '.join(gaps['missing'][:5])})")
        if k["close_outside_range"]:
            out.append(f"{t}: {k['close_outside_range']:,} traded closes outside the day's range")
        if r["partial_days"]:
            out.append(f"{t}: {len(r['partial_days'])} symbol-days look partial (under half the usual rows)")
        s = r.get("settlement", {})
        fb = s.get("futures_fallback_basis", {}).get("expiry_days_future_does_not_expire")
        if fb and fb["days"]:
            out.append(f"{t}: on {fb['days']} weekly expiry days before Jul 2024 there is no underlying column and no "
                       f"expiring future: the nearest future sits {fb['mean_pct']:+.2f}% from the official close on "
                       f"average (max {fb['max_abs_pct']:.2f}%). Settle such days on nse_index_close, not the future")
        ue = s.get("underlying_vs_official")
        if ue and ue["over_0.05pct"]:
            out.append(f"{t}: the bhavcopy underlying differs from NSE's official close by > 0.05% on "
                       f"{ue['over_0.05pct']} of {ue['days']} days")
        si = s.get("expiring_settle_is_official_close")
        if si and si["mismatched_symbol_days"]:
            out.append(f"{t}: on {si['mismatched_symbol_days']} symbol-days an expiring option's settle value differs "
                       "from NSE's official close")
    return out or ["no anomalies found"]


def render(res: dict) -> str:
    cal = res["calendar"]
    out = ["# Warehouse audit", "",
           f"Calendar: {cal['days']:,} trading days {cal['first']} → {cal['last']}, from {cal['source']}.", "",
           "## Findings, worst first", ""] + [f"- {x}" for x in res["verdict"]] + [""]
    for t, r in res["tables"].items():
        c, k = r["coverage"], r["contracts"]
        out += [f"## {t}", "",
                f"- {r['rows']:,} rows; symbols: {', '.join(r['symbols'])}",
                f"- coverage {c['first']} → {c['last']}: {c['present']:,} of {c['expected']:,} trading days present; "
                f"missing {len(c['missing'])}; files on non-trading days {len(c['on_non_trading_days'])}",
                f"- duplicates on the key: {r['duplicates']:,}; partial symbol-days: {len(r['partial_days'])}",
                f"- expiries (past): {k['expiries']:,}; rows after expiry: {k['rows_after_expiry']:,}; without "
                f"expiry-day rows: {len(k['expiries_without_expiry_day_rows'])}, of which holiday-shifted "
                f"{len(k['expiry_day_gaps']['holiday_shifted'])}, re-dated by the exchange "
                f"{len(k['expiry_day_gaps']['redated'])}, unexplained {len(k['expiry_day_gaps']['missing'])}",
                f"- negative prices {k['negative_prices']}, bad strikes {k['bad_strikes']}, traded closes outside the "
                f"range {k['close_outside_range']:,}; closes with no trade (theoretical): {k['theoretical_close_share']:.0%}",
                "- lot changes: " + (", ".join(f"{x['symbol']} {x['was']:.0f}→{x['lot']:.0f} on {x['date']}"
                                               for x in k["lot_changes"]) or "none"), ""]
        s = r.get("settlement", {})
        if t == "fo_bhav" and s:
            out.append("**Settlement against NSE's official closes**")
            out.append("")
            for name, v in s.items():
                out.append(f"- {name}: {v}")
            out.append("")
        elif s:
            out += [f"**Expiry-day quirk:** {s['expiring_rows_without_price']:,} of {s['expiring_rows']:,} expiring "
                    "rows carry no price, by design (the file puts the index value there)", ""]
    if "schema" in res:
        sc = res["schema"]
        out += ["## NSE vs BSE", "",
                f"- columns only in NSE: {sc['only_nse'] or 'none'}; only in BSE: {sc['only_bse'] or 'none'}; "
                f"type differences: {sc['dtype_differences'] or 'none'}",
                f"- sources: {sc['src']}",
                "- strike steps: " + ", ".join(f"{s} {v:g}" for s, v in sc["strike_steps"].items())]
        out += [f"- {x}" for x in sc["conventions"]]
        out.append("")
    return "\n".join(out)
