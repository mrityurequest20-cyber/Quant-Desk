"""Build the app's data: one JSON per instrument plus an overview (market pulse, screener, participants, flows,
calendar). Everything comes from the warehouse folder; nothing here touches a broker or the network."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .. import universe as U
from . import events as E
from . import narrative as N
from . import positioning as P
from . import vol as V
from .data import Warehouse


# ---------------- JSON helpers ----------------

def _num(x, nd=5):
    if x is None:
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        if not math.isfinite(x):
            return None
        return round(float(x), nd)
    if isinstance(x, (pd.Timestamp,)):
        return str(x.date())
    return x


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return [clean(v) for v in o.tolist()]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    return _num(o)


def series(df: pd.DataFrame, cols: list[str], nd=5) -> dict:
    d = df[cols].copy()
    return {"d": [str(i.date()) for i in d.index], **{c: [_num(v, nd) for v in d[c].tolist()] for c in cols}}


def _last(s: pd.Series):
    s = s.dropna()
    return (float(s.iat[-1]) if len(s) else None)


def _ago(s: pd.Series, n: int):
    s = s.dropna()
    return float(s.iat[-1 - n]) if len(s) > n else None


# ---------------- one instrument ----------------

def analyse(wh: Warehouse, inst: U.Instrument, vix: pd.Series, ev_cal: pd.DataFrame) -> dict:
    t0 = time.time()
    opt = wh.options(inst.symbol)
    if opt.empty:
        return {}
    asof = opt["date"].max()
    lots = opt.groupby("date")["lot"].median()
    spot_raw = wh.spot(inst.symbol)
    spot, splits = V.adjust_splits(spot_raw, lots, inst.kind)
    spot = spot[spot.index <= asof]
    close = spot["close"]

    t, ivrows = V.expiry_table(opt)
    iv30 = V.constant_maturity(t, 30)
    fr = V.front(t)
    rv = V.realised(spot)
    pcr = P.pcr_history(opt)
    book = P.futures_book(opt, close)

    df = pd.DataFrame(index=close.index)
    df["close"] = close
    df["iv30"] = iv30
    df["iv_front"] = fr["atm_iv"]
    df["rr25"] = V.front(t, min_days=7)["rr25"]        # skew from an expiry at least a week out: expiry-week wings are noise
    df["implied_move"] = fr["implied_move"]
    for c in ("rv5", "rv21", "rv63", "fwd_rv21"):
        df[c] = rv[c]
    if "pk21" in rv:
        df["pk21"] = rv["pk21"]
    df["pcr_oi"] = pcr["pcr_oi"]
    df["pcr_vol"] = pcr["pcr_vol"]
    df["opt_oi"] = pcr["opt_oi"]
    if not book.empty:
        for c in ("carry", "basis", "fut_oi", "roll_share"):
            df[c] = book[c]
    if inst.kind == "index" and inst.symbol == "NIFTY":
        df["vix"] = vix.reindex(df.index) / 100
    df = df[df.index >= t["date"].min()] if len(t) else df
    df["vrp"] = df["iv30"] - df["rv21"]
    since = str(df.index.min().date())

    # percentiles
    iv_p1y = P.latest_pct(df["iv30"], 252)
    iv_pall = P.latest_pct(df["iv30"])
    rv_p = P.latest_pct(df["rv21"])
    vrp_p = P.latest_pct(df["vrp"])
    rr_p = P.latest_pct(df["rr25"])
    pcr_p = P.latest_pct(df["pcr_oi"])
    carry_p = P.latest_pct(df["carry"]) if "carry" in df else None
    comp = (df["rv5"] / df["rv63"])
    comp_p = P.latest_pct(comp)
    hist = df.dropna(subset=["iv30", "fwd_rv21"])
    rich_share = float((hist["iv30"] > hist["fwd_rv21"]).mean()) if len(hist) > 50 else None

    # term structure now / 1w / 1m ago
    days = sorted(t["date"].unique())

    def curve(d):
        g = t[(t["date"] == d) & (t["days"] >= 2)].sort_values("days")     # an expiry tomorrow is all gamma, no vol
        return [{"expiry": str(r.expiry.date()), "days": int(r.days), "iv": r.atm_iv, "move": r.implied_move,
                 "straddle": r.straddle, "F": r.F} for r in g.itertuples()]

    term = {"now": curve(days[-1])}
    if len(days) > 5:
        term["week_ago"] = curve(days[-6])
    if len(days) > 21:
        term["month_ago"] = curve(days[-22])
    evv = V.event_vol(t, asof)
    tn = term["now"]
    front_iv = tn[0]["iv"] if tn else None
    later = tn[1:]
    back = next((x for x in later if x["days"] >= 25), later[-1] if later else None)

    # smiles (latest day, nearest 3 expiries)
    smiles = []
    lt = ivrows[ivrows["date"] == asof]
    for e in sorted(lt["expiry"].unique())[:3]:
        g = lt[lt["expiry"] == e].sort_values("strike")
        F = float(g["F"].iat[0])
        g = g[(g["strike"] / F).between(0.85, 1.15) & g["traded"]]     # settlement-only strikes are model prices
        smiles.append({"expiry": str(pd.Timestamp(e).date()), "days": int((pd.Timestamp(e) - asof).days), "F": F,
                       "strike": g["strike"].tolist(), "iv": g["iv"].round(5).tolist(),
                       "traded": g["traded"].tolist()})

    score = V.move_scorecard(t, close)
    sc_series = score.pop("series", None)
    cone = V.cone(rv[rv.index >= df.index.min()])
    spot_now = float(close.iat[-1])
    prof = P.strike_profile(opt, asof, spot_now, n_expiries=3, band=0.10 if inst.kind == "index" else 0.15)

    # futures
    fut_rows, recent_bu, fcard_row, rolls = [], [], None, []
    if not book.empty:
        bk = book[book.index <= asof].tail(30)
        for d, r in bk.iterrows():
            fut_rows.append({"date": str(d.date()), "fut": r.fut, "basis": r.basis, "carry": r.carry,
                             "fut_oi": r.fut_oi, "d_price": r.d_price, "d_oi": r.d_oi, "buildup": r.buildup,
                             "roll_share": r.roll_share, "days": r.days})
        recent_bu = [r["buildup"] for r in fut_rows[-5:]]
        fcard_row = fut_rows[-1] if fut_rows else None
        rolls = P.roll_history(book)

    # events
    results = []
    if inst.kind == "stock" and not ev_cal.empty:
        e = ev_cal[ev_cal["symbol"] == inst.symbol]
        for r in e.itertuples():
            item = {"date": str(r.date.date()), "purpose": r.purpose, "upcoming": bool(r.date > asof)}
            if not item["upcoming"]:
                i = close.index.searchsorted(r.date)
                if 0 < i < len(close):
                    j = i if close.index[i] >= r.date else i + 1
                    j = min(j, len(close) - 1)
                    # results come after the close more often than not: the reaction is the next session's
                    nxt = min(j + 1, len(close) - 1) if close.index[j] == r.date else j
                    item["move_next"] = float(close.iat[nxt] / close.iat[nxt - 1] - 1)
                    pre = t[(t["date"] == close.index[max(j - 1, 0)])]
                    ev_pre = V.event_vol(t, close.index[max(j - 1, 0)]) if len(pre) else None
                    if ev_pre:
                        item["implied_event_move"] = ev_pre["event_move"]
                    f_pre = fr["implied_move"].reindex([close.index[max(j - 1, 0)]]).iat[0] if len(fr) else None
                    item["front_implied_move"] = f_pre
                    after = df["iv_front"].reindex(close.index[min(nxt, len(close) - 1):min(nxt + 1, len(close))])
                    before = df["iv_front"].reindex([close.index[max(j - 1, 0)]])
                    if len(after) and len(before) and np.isfinite(after.iat[0]) and np.isfinite(before.iat[0]):
                        item["iv_crush"] = float(after.iat[0] - before.iat[0])
            results.append(item)
    ret = rv["ret"]
    macro = E.macro_study(ret) if inst.kind == "index" else []

    # cards
    vix_now = _last(vix) if inst.symbol == "NIFTY" else None
    cards = {
        "iv": N.iv_card(inst.symbol, _last(df["iv30"]), iv_p1y, iv_pall, since, vix_now),
        "vrp": N.vrp_card(inst.symbol, _last(df["iv30"]), _last(df["rv21"]), vrp_p, rich_share, since),
        "term": N.term_card(inst.symbol, front_iv, back["iv"] if back else None, tn[0]["days"] if tn else None,
                            back["days"] if back else None, evv),
        "skew": N.skew_card(inst.symbol, _last(df["rr25"]), rr_p),
        "realised": N.realised_card(inst.symbol, _last(df["rv21"]), rv_p, _last(df["rv5"]), _last(df["rv63"]), comp_p),
        "oi": N.oi_card(inst.symbol, prof, spot_now, pcr_p),
        "futures": N.futures_card(inst.symbol, fcard_row, carry_p, recent_bu),
    }
    if tn:
        f0 = tn[0]
        cards["move"] = N.move_card(inst.symbol, f0["expiry"], f0["days"], f0["move"], f0["F"],
                                    score.get("inside_all"), score.get("n", 0), score.get("since", since))
    cards = {k: v for k, v in cards.items() if v}

    # the story: the most unusual readings first
    ranked = sorted([(abs((p if p is not None else .5) - .5), k) for k, p in
                     [("iv", iv_p1y), ("vrp", vrp_p), ("skew", rr_p), ("realised", rv_p), ("oi", pcr_p),
                      ("futures", carry_p)] if k in cards], reverse=True)
    story = [cards["move"]["simple"]] if "move" in cards else []
    story += [cards[k]["simple"] for _, k in ranked[:3]]
    if evv:
        story.append(f"The option curve is pricing an event before {evv['front_expiry']}: about "
                     f"±{N.pct(evv['event_move'], 1)} on the day, against {N.pct(evv['normal_day_move'], 2)} normally.")

    hi52 = float(close.tail(252).max())
    lo52 = float(close.tail(252).min())
    chg = float(close.iat[-1] / close.iat[-2] - 1) if len(close) > 1 else None
    up_res = next((r for r in results if r["upcoming"]), None)
    metrics = {
        "symbol": inst.symbol, "name": inst.name, "kind": inst.kind, "sector": inst.sector,
        "spot": spot_now, "chg": chg, "iv30": _last(df["iv30"]), "iv30_chg5": (
            _last(df["iv30"]) - _ago(df["iv30"], 5)) if _ago(df["iv30"], 5) else None,
        "iv_p1y": iv_p1y, "iv_pall": iv_pall, "rv21": _last(df["rv21"]), "rv_p": rv_p,
        "vrp": _last(df["vrp"]), "vrp_p": vrp_p, "rr25": _last(df["rr25"]), "rr_p": rr_p,
        "move": tn[0]["move"] if tn else None, "move_days": tn[0]["days"] if tn else None,
        "pcr": _last(df["pcr_oi"]), "pcr_p": pcr_p, "carry": _last(df["carry"]) if "carry" in df else None,
        "carry_p": carry_p, "fut_oi_chg": fcard_row["d_oi"] if fcard_row else None,
        "buildup": fcard_row["buildup"] if fcard_row else None, "event": bool(evv),
        "results": up_res["date"] if up_res else None, "comp_p": comp_p,
        "inside": score.get("inside_all"), "pos52": (spot_now - lo52) / (hi52 - lo52) if hi52 > lo52 else None,
    }
    cols = [c for c in ["close", "iv30", "iv_front", "rv21", "rv5", "rv63", "pk21", "fwd_rv21", "vrp", "rr25",
                        "pcr_oi", "pcr_vol", "opt_oi", "carry", "basis", "fut_oi", "roll_share", "vix",
                        "implied_move"] if c in df]
    out = {
        "meta": {"symbol": inst.symbol, "name": inst.name, "kind": inst.kind, "sector": inst.sector,
                 "exchange": inst.exchange, "asof": str(asof.date()), "since": since, "splits": splits,
                 "build_seconds": round(time.time() - t0, 1)},
        "headline": {"spot": spot_now, "chg": chg, "hi52": hi52, "lo52": lo52, "metrics": metrics},
        "story": story, "cards": cards, "series": series(df, cols),
        "term": term, "smiles": smiles, "cone": cone, "scorecard": score,
        "scorecard_series": series(sc_series.set_index("date"), ["implied_move", "realised"]) if sc_series is not None and len(sc_series) else None,
        "oi_profile": prof, "futures": fut_rows, "rolls": rolls, "results": results, "macro": macro,
        "big_days": E.big_days(ret),
    }
    return clean(out)


# ---------------- market-wide ----------------

def participants_block(wh: Warehouse) -> dict:
    w = P.participant_books(wh.participants())
    if w.empty:
        return {}
    rows = []
    labels = {"idx_fut_net": "Index futures, net contracts", "idx_fut_long_share": "Index futures, long share",
              "idx_opt_stance": "Index options stance (calls net - puts net)", "stk_fut_net": "Stock futures, net"}
    for who in P.PARTS:
        for k, lab in labels.items():
            c = f"{k}:{who}"
            if c not in w:
                continue
            s = w[c].dropna()
            rows.append({"who": who, "metric": k, "label": lab, "now": _last(s), "chg5": (_last(s) - _ago(s, 5)) if _ago(s, 5) is not None else None,
                         "pct": P.latest_pct(s), "pct1y": P.latest_pct(s, 252)})
    keep = [c for c in w.columns if c.split(":")[0] in ("idx_fut_net", "idx_fut_long_share", "idx_opt_stance", "stk_fut_net")]
    fii = next((r for r in rows if r["who"] == "FII" and r["metric"] == "idx_fut_long_share"), None)
    cli = next((r for r in rows if r["who"] == "Client" and r["metric"] == "idx_fut_long_share"), None)
    simple = []
    if fii and fii["now"] is not None:
        simple.append(f"Foreign investors (FIIs) hold {N.pct(fii['now'], 0)} of their index-futures positions on the "
                      f"long side, {N.level(fii['pct'])} against every day since 2019 ({N.ordinal(fii['pct'])} percentile).")
    if cli and cli["now"] is not None:
        simple.append(f"Retail and other individual traders (Clients) are {N.pct(cli['now'], 0)} long in index futures, "
                      f"{N.level(cli['pct'])} for them.")
    simple.append("FIIs often hold futures shorts against the shares they own, so a low long share is partly hedging, "
                  "not a forecast. Extremes matter more than the level.")
    return clean({"since": str(w.index.min().date()), "asof": str(w.index.max().date()), "rows": rows,
                  "series": series(w, keep), "simple": simple})


def flows_block(wh: Warehouse) -> dict:
    f = wh.fii_dii()
    if f.empty:
        return {}
    w = f.pivot_table(index="date", columns="category", values="net").sort_index()
    out = {"since": str(w.index.min().date()), "asof": str(w.index.max().date()),
           "series": series(w, [c for c in ("FII", "DII") if c in w], 2)}
    simple = []
    for c, lab in (("FII", "Foreign investors"), ("DII", "Domestic institutions")):
        if c in w:
            s = w[c].dropna()
            last5 = s.tail(5).sum()
            streak = 0
            sign = np.sign(s.iat[-1])
            for v in s.values[::-1]:
                if np.sign(v) == sign:
                    streak += 1
                else:
                    break
            out[c] = {"last": float(s.iat[-1]), "sum5": float(last5), "sum20": float(s.tail(20).sum()), "streak": streak,
                      "streak_side": "buying" if sign > 0 else "selling"}
            simple.append(f"{lab} {'bought' if s.iat[-1] > 0 else 'sold'} Rs {abs(s.iat[-1]):,.0f} cr of shares on the last day; "
                          f"{'net buyers' if last5 > 0 else 'net sellers'} of Rs {abs(last5):,.0f} cr over 5 sessions "
                          f"({streak} {'day' if streak == 1 else 'days'} of {out[c]['streak_side']} in a row).")
    out["simple"] = simple
    out["note"] = (f"NSE publishes only the latest day of this data, so its history here starts {out['since']}, "
                   f"when collection began. It is the cash market (shares), not derivatives.")
    return clean(out)


def calendar_block(wh: Warehouse, asof, sym_data: dict, ev_cal: pd.DataFrame) -> dict:
    items = []
    for s, d in sym_data.items():
        if d.get("meta", {}).get("kind") == "index":
            for c in d.get("term", {}).get("now", [])[:2]:
                if pd.Timestamp(c["expiry"]) <= asof:
                    continue
                items.append({"date": c["expiry"], "type": "expiry", "symbol": s,
                              "text": f"{s} expiry: options price ±{N.pct(c['move'], 1)} to it"})
    for r in ev_cal.itertuples():
        if r.date > asof:
            dd = sym_data.get(r.symbol, {})
            mv = dd.get("headline", {}).get("metrics", {}).get("move")
            items.append({"date": str(r.date.date()), "type": "results", "symbol": r.symbol,
                          "text": f"{r.symbol} results" + (f" (front expiry prices ±{N.pct(mv, 1)})" if mv else "")})
    h = wh.holidays()
    for r in h.itertuples():
        if r.date > asof:
            items.append({"date": str(r.date.date()), "type": "holiday", "symbol": "", "text": f"Market holiday: {r.description}"})
    items = sorted(items, key=lambda x: x["date"])
    # one row per symbol per date
    seen, out = set(), []
    for i in items:
        k = (i["date"], i["type"], i["symbol"])
        if k not in seen:
            seen.add(k)
            out.append(i)
    return {"items": out[:80]}


def pulse(sym_data: dict, vix: pd.Series, parts: dict, flows: dict) -> list[str]:
    out = []
    n = sym_data.get("NIFTY", {})
    m = n.get("headline", {}).get("metrics", {})
    v = vix.dropna()
    if len(v) > 300:
        vp = float((v.iloc[-253:-1] < v.iat[-1]).mean())
        out.append(f"Fear gauge: India VIX is {v.iat[-1]:.1f}, {N.level(vp)} against the past year "
                   f"({N.ordinal(vp)} percentile). The market expects NIFTY to move about "
                   f"{v.iat[-1] / 100 / math.sqrt(252) * 100:.2f}% a day over the next month.")
    if m.get("vrp") is not None:
        out.append(("Options are priced above what NIFTY has actually been moving: the usual state, with sellers paid a premium."
                    if m["vrp"] > 0 else "NIFTY has been moving more than its options price: an unusual state that often comes with stress."))
    if m.get("move"):
        out.append(f"To the next expiry ({m['move_days']} days) NIFTY options price a move of ±{N.pct(m['move'], 1)}.")
    hot = sorted([d["headline"]["metrics"] for d in sym_data.values() if d.get("headline")],
                 key=lambda x: -(x.get("iv_p1y") or 0))
    hot = [x for x in hot if (x.get("iv_p1y") or 0) >= 0.85][:4]
    if hot:
        out.append("Unusually expensive options right now: " + ", ".join(f"{x['symbol']} ({N.ordinal(x['iv_p1y'])} pct)" for x in hot) + ".")
    cold = [d["headline"]["metrics"] for d in sym_data.values() if d.get("headline")]
    cold = [x for x in sorted(cold, key=lambda x: (x.get("iv_p1y") if x.get("iv_p1y") is not None else 1)) if (x.get("iv_p1y") or 1) <= 0.12][:4]
    if cold:
        out.append("Unusually cheap options: " + ", ".join(f"{x['symbol']} ({N.ordinal(x['iv_p1y'])} pct)" for x in cold) + ".")
    out += (parts.get("simple") or [])[:1]
    out += (flows.get("simple") or [])[:1]
    return out


def build(warehouse: Path, out: Path, symbols: list[str] | None = None, say=print) -> dict:
    wh = Warehouse(warehouse)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sym").mkdir(exist_ok=True)
    vix = wh.spot("INDIAVIX")["close"]
    ev = wh.corp_events()
    ev_cal = E.results_calendar(ev, [s.symbol for s in U.STOCKS], None)
    insts = [i for i in U.ALL if not symbols or i.symbol in symbols]
    data = {}
    for inst in insts:
        try:
            d = analyse(wh, inst, vix, ev_cal)
        except Exception as e:                      # one bad instrument never stops the build
            say(f"  {inst.symbol}: FAILED {type(e).__name__}: {e}")
            continue
        if not d:
            say(f"  {inst.symbol}: no data")
            continue
        data[inst.symbol] = d
        (out / "sym" / f"{U.slug(inst.symbol)}.json").write_text(json.dumps(d, separators=(",", ":")))
        say(f"  {inst.symbol}: {d['meta']['since']} .. {d['meta']['asof']} ({d['meta']['build_seconds']}s)")
    asof = max(pd.Timestamp(d["meta"]["asof"]) for d in data.values())
    parts = participants_block(wh)
    flows = flows_block(wh)
    v = vix.dropna()
    overview = {
        "asof": str(asof.date()), "built": pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M IST"),
        "pulse": pulse(data, vix, parts, flows),
        "screener": [d["headline"]["metrics"] | {"slug": U.slug(s)} for s, d in data.items()],
        "vix": clean({"now": float(v.iat[-1]), "p1y": float((v.iloc[-253:-1] < v.iat[-1]).mean()),
                      "series": series(v.to_frame("vix")[v.index >= "2019-01-01"], ["vix"], 3)}),
        "participants": parts, "flows": flows,
        "calendar": calendar_block(wh, asof, data, ev_cal),
        "universe": [{"symbol": i.symbol, "name": i.name, "kind": i.kind, "sector": i.sector, "slug": U.slug(i.symbol)}
                     for i in insts if i.symbol in data],
    }
    (out / "overview.json").write_text(json.dumps(clean(overview), separators=(",", ":")))
    return overview
