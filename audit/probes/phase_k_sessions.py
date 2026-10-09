"""Phase K: reconstruct each recorded production session from persisted evidence alone (read-only).

Inputs: a copy of the journal branch (journal.db mode=ro, data/<date>/*.csv, memory.json) and the chains-2026
parquet files. For each session: market state, available information, setups seen, rejections by gate, armed
triggers and their gate outcome, execution, counterfactual outcome of the rejected plans (mid to mid to 15:15),
learning events, and subsequent use (the learned multipliers the next session's reads carried).

    python audit/probes/phase_k_sessions.py JOURNAL_DIR CHAINS_DIR > out.json
"""
import collections
import glob
import json
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quantdesk.intraday.analyst import DEFAULT_WEIGHTS  # noqa: E402

LOT = {"NIFTY": 65, "BANKNIFTY": 30}


def market(data: Path, day: str, u: str) -> dict:
    p = data / day / f"{u}_1m.csv"
    if not p.exists():
        return {}
    b = pd.read_csv(p, index_col=0, parse_dates=True)
    o, h, l, c = b["open"].iloc[0], b["high"].max(), b["low"].min(), b["close"].iloc[-1]
    mid = b[b.index.strftime("%H:%M") <= "12:20"]["close"].iloc[-1]
    rng = h - l
    return {"bars": len(b), "open_to_close_pct": round((c / o - 1) * 100, 2), "range_pct": round(rng / o * 100, 2),
            "close_location": round((c - l) / rng, 2) if rng else None,
            "am_pct": round((mid / o - 1) * 100, 2), "pm_pct": round((c / mid - 1) * 100, 2)}


def main(jdir: Path, cdir: Path) -> dict:
    c = sqlite3.connect(f"file:{jdir / 'journal.db'}?mode=ro", uri=True)
    chains = pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{cdir}/*_chains.parquet"))], ignore_index=True)
    chains["ts"] = pd.to_datetime(chains["ts"])
    chains["expiry"] = pd.to_datetime(chains["expiry"]).dt.date
    days = sorted({r[0] for r in c.execute("SELECT DISTINCT substr(ts,1,10) FROM thoughts")})
    out = {}
    for d in days:
        S = {"market": {u: market(jdir / "data", d, u) for u in LOT}}
        ev = c.execute("SELECT ts, level, category, message FROM events WHERE substr(ts,1,10)=? ORDER BY id", (d,)).fetchall()
        rev = next((m for _, _, cat, m in ev if cat == "session_review"), "")
        feed = re.search(r"feed ([^.]+?\))", rev) or re.search(r"feed (kotak[^.\n]*)", rev)
        vix = pd.read_csv(jdir / "data" / d / "INDIAVIX_1m.csv")["close"] if (jdir / "data" / d / "INDIAVIX_1m.csv").exists() else pd.Series(dtype=float)
        S["information"] = {
            "feed": feed.group(1) if feed else None,
            "chain": re.search(r"chain source (\w+)", rev).group(1) if re.search(r"chain source (\w+)", rev) else None,
            "vix_zero_bars": f"{int((vix <= 0).sum())}/{len(vix)}",
            "news_seen_that_day_per_current_record": c.execute("SELECT COUNT(*) FROM news WHERE substr(seen_at,1,10)=?", (d,)).fetchone()[0],
            "llm_line": next((m[:150] for _, _, cat, m in ev if cat == "llm"), None),
            "warn_or_worse": collections.Counter(f"{lv} {cat}: {m[:40]}" for _, lv, cat, m in ev if lv in ("WARN", "ERROR", "CRITICAL")),
            "scheduled_events": sorted({m[:80] for _, _, cat, m in ev if "event" in cat.lower() or "RBI" in m})[:3],
        }
        th = pd.read_sql("SELECT ts, symbol, bias, score, action, evidence FROM thoughts WHERE substr(ts,1,10)=? ORDER BY id", c, params=(d,))
        kind = th["action"].fillna("").str.lower().map(lambda a: a.split(":")[0].strip()[:24])
        flips = sum((g["bias"] != g["bias"].shift()).sum() - 1 for _, g in th.groupby("symbol"))
        S["reads"] = {"thoughts": len(th), "bias": th["bias"].value_counts().to_dict(), "bias_flips": int(flips),
                      "stance": kind.value_counts().to_dict(),
                      "setups_named": sorted({m.group(1) for a in th["action"].fillna("") for m in [re.search(r"setup (\w+)", a)] if m})}
        dec = c.execute("SELECT id, ts, strategy, symbol, detail, context FROM decisions WHERE substr(ts,1,10)=? ORDER BY id", (d,)).fetchall()
        gates, armed, cf = collections.Counter(), [], []
        for i, ts, st, sym, det, ctx in dec:
            cx = json.loads(ctx)
            g = "EV floor" if det.startswith("EV below") else "no approved plan model" if "no approved plan model" in det else det[:40]
            gates[g] += 1
            if "armed" in cx:
                a = cx["armed"]
                armed.append({"ts": ts[11:19], "symbol": sym, "setup": st, "level": a["level"], "armed_at": a["armed_at"][11:19],
                              "why": a["why"], "gate": g})
            plan = cx.get("plan", "")
            m = re.match(r"(\S+) (\S+) (\d\d-\w{3}):", plan)
            legs = re.findall(r"([+−-])(\d+)(CE|PE)@([\d.]+)", plan)
            if not (m and legs):
                continue
            t0 = pd.Timestamp(ts)
            exp = pd.Timestamp(f"{m.group(3)}-{t0.year}").date()
            g2 = chains[(chains.underlying == sym) & (chains.expiry == exp) & (chains.ts.dt.date == t0.date())]
            a0, b0 = g2[g2.ts <= t0], g2[g2.ts <= pd.Timestamp(f"{t0.date()} 15:15", tz=t0.tz)]
            if a0.empty or b0.empty:
                continue
            sa, sb = a0[a0.ts == a0.ts.max()].set_index("strike"), b0[b0.ts == b0.ts.max()].set_index("strike")
            try:
                pnl = sum((1 if s == "+" else -1) * (((sb.loc[float(k), f"{r.lower()}_bid"] + sb.loc[float(k), f"{r.lower()}_ask"]) / 2)
                                                    - ((sa.loc[float(k), f"{r.lower()}_bid"] + sa.loc[float(k), f"{r.lower()}_ask"]) / 2))
                          for s, k, r, _ in legs)
                # entry at the plan's own (touch) prices, exit at the 15:15 touch (sell longs at bid, buy shorts at ask)
                touch = sum((1 if s == "+" else -1) * ((sb.loc[float(k), f"{r.lower()}_bid"] if s == "+" else sb.loc[float(k), f"{r.lower()}_ask"])
                                                      - float(px)) for s, k, r, px in legs)
            except KeyError:
                continue
            fees = (cx.get("ev") or {}).get("fees")
            cf.append({"gate": g, "structure": m.group(1), "plan": plan.split(";")[0], "pnl_per_lot_mid_to_1515": round(float(pnl) * LOT[sym], 0),
                       "pnl_per_lot_touch_to_1515": round(float(touch) * LOT[sym], 0),
                       "net_after_ev_fees": round(float(touch) * LOT[sym] - fees, 0) if fees is not None else None})
        S["decisions"] = {"rows": len(dec), "by_gate": dict(gates), "armed_triggers": armed,
                          "execution": c.execute("SELECT COUNT(*) FROM trades WHERE substr(opened_at,1,10)=?", (d,)).fetchone()[0]}
        cfd = pd.DataFrame(cf)
        S["counterfactual"] = ({"valued": len(cfd), "basis": "1 lot, held to 15:15; costs: EV fees where recorded; no slippage beyond touch",
                                "by_gate": {g: {"rows": int(len(x)), "distinct_plans": int(x["plan"].nunique()),
                                                "mid_sum": float(x["pnl_per_lot_mid_to_1515"].sum()),
                                                "touch_sum": float(x["pnl_per_lot_touch_to_1515"].sum()),
                                                "touch_winners": int((x["pnl_per_lot_touch_to_1515"] > 0).sum()),
                                                "net_after_fees_sum": (float(x["net_after_ev_fees"].sum()) if x["net_after_ev_fees"].notna().all() else None),
                                                "distinct_plan_touch_median": float(x.groupby("plan")["pnl_per_lot_touch_to_1515"].first().median())}
                                            for g, x in cfd.groupby("gate")}}
                               if len(cfd) else {"valued": 0, "note": "no chain archive for the decision times" if dec else "no decisions"})
        S["learning"] = [m[:120] for _, lv, cat, m in ev if cat == "learning"]
        mult = collections.defaultdict(list)
        for e in th["evidence"]:
            for x in json.loads(e):
                if x["factor"] in DEFAULT_WEIGHTS and x["weight"] > 0:
                    mult[x["factor"]].append(x["weight"] / DEFAULT_WEIGHTS[x["factor"]])
        S["subsequent_use_learned_multipliers_median"] = {f: round(float(pd.Series(v).median()), 3)
                                                          for f, v in sorted(mult.items()) if f in ("vix", "orb", "vwap", "pcr", "rsi", "news")}
        out[d] = S
    return out


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2])), indent=1, default=str))
