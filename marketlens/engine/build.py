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
from . import expiry as X
from . import baserates as BRT
from . import macro as MX
from . import breadth as BR
from . import gamma as GM
from . import linkage as LK
from . import movement as MV
from . import narrative as N
from . import positioning as P
from . import rules as RL
from . import vol as V
from .data import Warehouse


# ---------------- JSON helpers ----------------

def _num(x, nd=5):
    """A number for the app's JSON: 5 decimals below 1 (a vol of 0.144444 keeps 0.14444), 7 significant figures from 1
    up (NIFTY's 26,029.4 and an OI of 12,500,280 keep every digit that means anything)."""
    if x is None:
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        if not math.isfinite(x):
            return None
        x = float(x)
        if abs(x) >= 1:
            return round(x, max(0, 6 - int(math.floor(math.log10(abs(x))))))
        return round(x, nd)
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


def rank_last(x: pd.Series, n: int = 252):
    """The latest value's share of the n readings before it that are lower (one convention for every rank)."""
    x = x.dropna()
    if len(x) < 127:
        return None
    h = x.iloc[-n - 1:-1]
    return float((h < x.iat[-1]).mean())


def series(df: pd.DataFrame, cols: list[str], nd=5) -> dict:
    d = df[cols].copy()
    return {"d": [str(i.date()) for i in d.index], **{c: [_num(v, nd) for v in d[c].tolist()] for c in cols}}


def _last(s: pd.Series):
    s = s.dropna()
    return (float(s.iat[-1]) if len(s) else None)


def _ago(s: pd.Series, n: int):
    s = s.dropna()
    return float(s.iat[-1 - n]) if len(s) > n else None


# ---------------- what changed, and the exchange's rules ----------------

def expiry_regimes(opt: pd.DataFrame, min_days: int = 40, min_step: int = 2) -> list[dict]:
    """Dates when the exchange changed how many option expiries it lists for this underlying (SEBI ended BANKNIFTY's
    and FINNIFTY's weeklies in Nov 2024). Total OI and PCR change level at such a date for reasons that have nothing
    to do with positioning, so the charts mark them. A change must hold for min_days sessions and be at least min_step
    expiries (a thin index flickering between one and two listed months is liquidity, not a rule). Indices only: the
    warehouse keeps two expiries per stock by construction."""
    o = opt[opt["kind"].isin(["CE", "PE"]) & (opt["expiry"] > opt["date"])]
    if o.empty:
        return []
    n = o.groupby("date")["expiry"].nunique().rolling(20, min_periods=10).median().round()
    out, cur, since = [], None, None
    vals = n.dropna()
    i = 0
    while i < len(vals):
        v = vals.iat[i]
        if cur is None:
            cur = v
        elif v != cur:
            run = vals.iloc[i:i + min_days]
            if len(run) >= min_days and (run == v).mean() >= 0.9 and abs(v - cur) >= min_step:
                out.append({"date": str(vals.index[i].date()), "from": int(cur), "to": int(v)})
                cur = v
                i += min_days
                continue
        i += 1
    return out


CHANGE_FIELDS = {"iv30": ("30-day IV", "vol pts", 100), "rr25": ("skew (25d risk reversal)", "vol pts", 100),
                 "implied_move": ("priced move to the front expiry", "% pts", 100), "rv21": ("realised vol (21d)", "vol pts", 100)}


def day_changes(df: pd.DataFrame) -> list[dict]:
    """Yesterday-to-today change of each reading, and how big that change is for this instrument: the change over the
    standard deviation of its own daily changes in the past year (a z-score; |z| >= 2 is a day in ~20 for it)."""
    out = []
    for k, (label, unit, mult) in CHANGE_FIELDS.items():
        if k not in df:
            continue
        x = df[k].dropna()
        if len(x) < 60:
            continue
        # a change "since yesterday" needs a reading on both the as-of session and the one before it
        if len(df) < 2 or x.index[-1] != df.index[-1] or x.index[-2] != df.index[-2]:
            continue
        d = x.diff().dropna()
        if k == "implied_move":            # the front expiry rolls: a move into a new expiry is not a change
            continue
        sd = d.iloc[-253:-1].std()
        now = float(d.iat[-1])
        z = now / sd if sd and np.isfinite(sd) and sd > 0 else None
        out.append({"field": k, "label": label, "chg": now * mult, "unit": unit, "z": z, "from": float(x.iat[-2]) * mult,
                    "to": float(x.iat[-1]) * mult, "date": str(x.index[-1].date())})
    return out


def rules_block(opt: pd.DataFrame, asof, inst: U.Instrument, curve: list[dict], holidays=()) -> dict:
    """What the exchange's own contract data says about this instrument's contracts today: upcoming expiries, a lot
    size that differs between expiries (a revision already listed), and physical settlement for stocks near expiry."""
    o = opt[opt["date"] == asof]
    lots = (o.groupby("expiry")["lot"].agg(lambda x: x.mode().iat[0] if len(x.mode()) else np.nan)
            .dropna().sort_index())
    out = {"expiries": [str(pd.Timestamp(e).date()) for e in sorted(o["expiry"].unique())][:6], "notes": []}
    if len(lots) >= 2 and lots.nunique() > 1:
        first = lots.iat[0]
        for e, l in lots.items():
            if l != first:
                out["notes"].append({"kind": "lot", "text": f"Lot size changes from {first:,.0f} to {l:,.0f} for the "
                                     f"{pd.Timestamp(e).date()} contracts (the exchange has already listed them so)."})
                out["lot_change"] = {"from": float(first), "to": float(l), "expiry": str(pd.Timestamp(e).date())}
                break
    out["lot"] = float(lots.iat[0]) if len(lots) else None
    fut = o[o["kind"] == "FUT"]
    if len(fut):
        nxt = pd.Timestamp(fut["expiry"].min())
        # NSE trading days, not weekdays: the exchange's holidays between now and expiry are not sessions
        sessions = int(np.busday_count(pd.Timestamp(asof).date(), nxt.date(), holidays=[pd.Timestamp(h).date() for h in holidays]))
        out["front_expiry"] = str(nxt.date())
        out["sessions_to_expiry"] = sessions
        if inst.kind == "stock" and sessions <= 5:
            out["notes"].append({"kind": "settlement", "text": f"Expiry is {sessions} session{'s' if sessions != 1 else ''} "
                                 f"away ({nxt.date()}). Stock futures and in-the-money stock options held into expiry "
                                 f"are settled by delivery of shares, not in cash."})
    return out


# ---------------- one instrument ----------------

def analyse(wh: Warehouse, inst: U.Instrument, vix: pd.Series, ev_cal: pd.DataFrame, limits=None) -> dict:
    t0 = time.time()
    opt = wh.options(inst.symbol)
    if opt.empty:
        return {}
    asof = opt["date"].max()
    lots = opt.groupby("date")["lot"].median()
    spot_raw = wh.spot(inst.symbol)
    spot, splits = V.adjust_splits(spot_raw, lots, inst.kind)
    spot = spot[spot.index <= asof].copy()
    close = spot["close"]

    t, ivrows = V.expiry_table(opt)
    actions = []
    if inst.kind == "stock":
        market = wh.spot("NIFTY")["close"]
        actions = V.corporate_actions(opt, spot_raw["close"], market)
        t = V.drop_action_windows(t, actions)
        # a demerger's drop is value handed to shareholders, not a market move: take it out of the price history
        # (net of the market's own move that day), as adjust_splits does for splits and bonuses
        rm = np.log(market).diff()
        for a in actions:
            d = pd.Timestamp(a["date"])
            jump = a["move"] - (rm.get(d, 0.0) if np.isfinite(rm.get(d, np.nan)) else 0.0)
            spot.loc[spot.index < d, ["open", "high", "low", "close"]] *= np.exp(jump)
            a["adjusted"] = round(float(jump), 4)
        close = spot["close"]
    iv30 = V.constant_maturity(t, 30)
    reach = t[t["days"] >= 2].groupby("date")["days"].max()

    def cm(target):
        """Constant-maturity IV only where the listed expiries reach (near) the horizon: flat extrapolation past
        the last expiry would label a 2-month vol as a 3-month one."""
        x = V.constant_maturity(t, target)
        return x.where(reach.reindex(x.index) >= 0.85 * target)
    iv60, iv90 = cm(60), cm(90)
    # each monthly contract's own ATM IV and skew, by its place (current / near / far month)
    by_month = {}
    if "series" in t:
        for i, name in enumerate(("current month", "near month", "far month"), 1):
            m = t[t["series"] == name].drop_duplicates("date").set_index("date")
            by_month[f"iv_m{i}"], by_month[f"rr_m{i}"], by_month[f"days_m{i}"] = m["atm_iv"], m["rr25"], m["days"]
    fr = V.front(t)
    rv = V.realised(spot)
    pcr = P.pcr_history(opt)
    # futures are raw prices: compare them with the RAW spot (the exchange adjusts both together on an action day);
    # the adjusted series is for returns and history only. Action days get no build-up read.
    raw_close = spot_raw["close"][spot_raw.index <= asof]
    act_days = [x["date"] for x in splits] + [x["date"] for x in actions]
    book = P.futures_book(opt, raw_close, act_days)
    if "true_spot" in spot and not book.empty:          # no basis or carry against a futures-price "spot"
        proxy = ~spot["true_spot"].reindex(book.index).fillna(True).astype(bool)
        book.loc[proxy, ["basis", "carry"]] = np.nan

    # gamma by strike: concentration for every instrument; the hedgers' net only for indices (NSE's participant
    # file is one figure for all stocks together, so it cannot sign a single stock's book)
    poi = wh.participants()
    w_hist = GM.weights_history(poi, "index") if inst.kind == "index" else pd.DataFrame(columns=["calls", "puts"])
    w_now = GM.weights(poi, asof, "index") if inst.kind == "index" else None
    gmap = GM.profile(opt, t, ivrows, asof, float(raw_close.iat[-1]), w_now,
                      band=0.06 if inst.kind == "index" else 0.12, grid=0.05 if inst.kind == "index" else 0.10)
    ghist = GM.history(opt, t, ivrows, w_hist, sorted(t["date"].unique()))
    if inst.kind != "index":
        ghist = ghist.drop(columns=["gamma_net"], errors="ignore")
    if gmap is not None and inst.kind == "index":
        gmap["study"] = GM.regime_study(ghist, rv["ret"], iv30)

    # how much of a stock's moves are the market's, its sector's, or its own (adjusted closes: returns, not prices)
    link = None
    if inst.kind == "stock":
        ic = wh.index_close()
        sec_name = LK.SECTOR_INDEX.get(inst.sector)
        get = lambda n: ic[ic["index"] == n].drop_duplicates("date", keep="last").set_index("date")["close"].sort_index()
        nifty_c = get("Nifty 50")
        sec_c = get(sec_name) if sec_name else None
        lk = LK.rolling(close, nifty_c, sec_c if sec_c is not None and len(sec_c) > 300 else None)
        lk = lk[lk.index <= asof]
        if len(lk):
            last = lk.iloc[-1]
            link = {"sector_index": sec_name if "beta_s" in lk else None,
                    **{k: (float(last[k]) if k in lk and np.isfinite(last[k]) else None) for k in ("beta_n", "corr_n", "beta_s", "corr_s", "r2", "own")},
                    "own_p": P.latest_pct(lk["own"], 252)}

    # how it moves: range, gaps, compression, participation (indices: NSE's index OHLC; stocks: the cash bhavcopy)
    move_now, mv = None, None
    if inst.kind == "index":
        src = spot_raw[spot_raw.index <= asof]
    else:
        cash = wh.cash(inst.symbol)
        src = cash[cash.index <= asof] if len(cash) else pd.DataFrame()
    if len(src) > 60 and {"open", "high", "low"} <= set(src.columns) and src["open"].notna().sum() > 60:
        mv = MV.measures(MV.prepare(src, splits if inst.kind == "stock" else (), [a["date"] for a in actions]))
        last = mv.iloc[-1]
        g = mv["gap"].dropna()
        move_now = {
            **{k: (float(last[k]) if k in mv and pd.notna(last[k]) else None)
               for k in ("atr14", "cc21", "pk21", "gk21", "yz21", "ovn_share", "rng20", "rng20_rank", "bbw", "bbw_rank",
                         "vol_z", "deliv", "deliv_rank", "amihud", "amihud_rank")},
            "nr7": bool(last["nr7"]), "since": str(mv.index[0].date()),
            "atr_rank": rank_last(mv["atr14"]),
            "gap_p50": float(g.abs().iloc[-252:].median()) if len(g) > 60 else None,
            "gap_p95": float(g.abs().iloc[-252:].quantile(.95)) if len(g) > 60 else None,
            "big_gaps": [{"date": str(d.date()), "gap": float(x)} for d, x in g.iloc[-252:].abs().sort_values().tail(6)[::-1].items()
                         if pd.notna(x)],
            "study": MV.compression_study(mv, iv30),
        }
        move_now["big_gaps"] = [dict(x, gap=float(g.loc[pd.Timestamp(x["date"])])) for x in move_now["big_gaps"]]

    # the expiry in front, and what past expiries did (raw prices: strikes are raw)
    xfront = X.front(opt, t, asof, float(raw_close.iat[-1]))
    if xfront is not None:
        xfront["study"] = X.pin_study(opt, t, raw_close, asof)

    df = pd.DataFrame(index=close.index)
    df["close"] = close
    df["iv30"] = iv30
    df["iv_front"] = fr["atm_iv"]
    df["iv60"], df["iv90"] = iv60, iv90
    df["term_60_30"] = df["iv60"] - df["iv30"]
    for k, v in by_month.items():
        df[k] = v
    df["rr25"] = V.front(t, min_days=7)["rr25"]        # skew from an expiry at least a week out: expiry-week wings are noise
    df["implied_move"] = fr["implied_move"]
    for c in ("rv5", "rv21", "rv63", "fwd_rv21"):
        df[c] = rv[c]
    if "pk21" in rv:
        df["pk21"] = rv["pk21"]
    for c in ("gamma_call", "gamma_put", "gamma_net"):
        if c in ghist:
            df[c] = ghist[c]
    if link is not None:
        df["own"], df["beta_n"] = lk["own"], lk["beta_n"]
    if mv is not None:
        for c in ("atr14", "cc21", "gk21", "yz21", "ovn_share", "rng20_rank", "bbw_rank", "vol_z", "deliv", "amihud", "gap"):
            if c in mv:
                df["mv_" + c] = mv[c]
    df["pcr_oi"] = pcr["pcr_oi"]
    df["pcr_vol"] = pcr["pcr_vol"]
    df["opt_oi"] = pcr["opt_oi"]
    if not book.empty:
        for c in ("carry", "basis", "fut_oi", "roll_share", "cal_spread", "cal_carry"):
            if c in book:
                df[c] = book[c]
    if inst.kind == "index" and inst.symbol == "NIFTY":
        df["vix"] = vix.reindex(df.index) / 100
    df = df[df.index >= t["date"].min()] if len(t) else df
    df["vrp"] = df["iv30"] - df["rv21"]
    # OI counts shares: a bonus or split multiplies it overnight. Restate the history in today's units, like price.
    for sp_ in splits:
        d0 = pd.Timestamp(sp_["date"])
        for c in ("opt_oi", "fut_oi"):
            if c in df:
                df.loc[df.index < d0, c] *= sp_["ratio"]
    regimes = expiry_regimes(opt) if inst.kind == "index" else []
    since = str(df.index.min().date())

    # percentiles
    # a headline is today's reading or nothing: a series whose last value is older than 2 sessions (NIFTYNXT50's IV
    # when its thin options fail the liquidity checks) is withheld, and the page says when it was last read, instead
    # of showing an old number as today's. Every headline read below goes through these two helpers.
    stale = {}
    pos_now = len(df) - 1

    def fresh(c):
        if c not in df:
            return None
        s_ = df[c]
        lv = s_.last_valid_index()
        if lv is None:
            return None
        if pos_now - df.index.get_loc(lv) > 2:
            stale[c] = str(lv.date())
            return None
        return s_.loc[:lv]

    def cur(c):
        s_ = fresh(c)
        return float(s_.iat[-1]) if s_ is not None and len(s_) else None

    def pctl(c, w=None):
        s_ = fresh(c)
        return P.latest_pct(s_, w) if s_ is not None else None

    # one convention across the app: every headline percentile is against the past year (252 sessions); the
    # all-history rank is kept beside it for the analyst view
    iv_p1y = pctl("iv30", 252)
    iv_pall = pctl("iv30")
    rv_p = pctl("rv21", 252)
    vrp_p = pctl("vrp", 252)
    rr_p = pctl("rr25", 252)
    # positioning readings are judged against the last year: their levels moved with the market's structure (NIFTY's
    # PCR ran ~1.4 in 2019 and ~0.95 since 2022; weekly expiries were cut in Nov 2024), so all-history ranks mislead
    pcr_p = pctl("pcr_oi", 252)
    carry_p = pctl("carry", 252) if "carry" in df else None
    carry_med = float(df["carry"].dropna().iloc[-253:-1].median()) if "carry" in df and df["carry"].notna().sum() > 60 else None
    df["comp"] = df["rv5"] / df["rv63"]
    comp_p = pctl("comp", 252)
    try:
        lab = BRT.lab(df, B=500) if not stale.get("iv30") else None        # today's state must be today's
    except Exception:                                                 # an extra: never stops the instrument
        lab = None
    # the curve between months: constant-maturity 60-day over 30-day IV, and the futures roll rate between months
    months_curve = {"iv60": cur("iv60") if "iv60" in df else None, "iv90": cur("iv90") if "iv90" in df else None,
             "term_60_30": cur("term_60_30") if "term_60_30" in df else None,
             "term_p": pctl("term_60_30", 252) if "term_60_30" in df else None,
             "cal_carry": cur("cal_carry") if "cal_carry" in df else None,
             "cal_carry_p": pctl("cal_carry", 252) if "cal_carry" in df else None,
             "cal_spread": cur("cal_spread") if "cal_spread" in df else None,
             "months": {k: cur(k) for k in ("iv_m1", "iv_m2", "iv_m3", "rr_m1", "rr_m2", "rr_m3") if k in df}}
    hist = df.dropna(subset=["iv30", "fwd_rv21"])
    rich_share = float((hist["iv30"] > hist["fwd_rv21"]).mean()) if len(hist) > 50 else None

    # term structure now / 1w / 1m ago
    days = sorted(t["date"].unique())

    def curve(d):
        g = t[(t["date"] == d) & (t["days"] >= 2)].sort_values("days")     # an expiry tomorrow is all gamma, no vol
        return [{"expiry": str(r.expiry.date()), "days": int(r.days), "iv": r.atm_iv, "move": r.implied_move,
                 "straddle": r.straddle, "F": r.F, "series": r.series} for r in g.itertuples()]

    # "now" is the as-of session (or the one before): a curve last readable a week ago is not today's curve
    sess = list(df.index)
    recent = set(sess[-2:])
    term = {"now": curve(days[-1]) if days and days[-1] in recent else []}
    if not term["now"] and days:
        stale["term"] = str(pd.Timestamp(days[-1]).date())
    if len(sess) > 5:
        term["week_ago"] = curve(sess[-6])
    if len(sess) > 21:
        term["month_ago"] = curve(sess[-22])
    evv = V.event_vol(t, asof)
    if evv and inst.kind == "stock" and not ev_cal.empty:
        # name the cause only when the exchange's calendar has one inside the front expiry
        due = ev_cal[(ev_cal["symbol"] == inst.symbol) & (ev_cal["date"] > asof)
                     & (ev_cal["date"] <= pd.Timestamp(evv["front_expiry"]))]
        if len(due):
            evv["cause"] = "results"
            evv["cause_date"] = str(due["date"].iat[0].date())
    tn = term["now"]
    front_iv = tn[0]["iv"] if tn else None
    later = tn[1:]
    back = next((x for x in later if x["days"] >= 25), later[-1] if later else None)

    # smiles (latest day, nearest 3 expiries)
    smiles = []
    lt = ivrows[ivrows["date"] == asof]
    on_curve = set(t.loc[t["date"] == asof, "expiry"])                 # only expiries that passed the curve's checks
    ser = t[t["date"] == asof].set_index("expiry")["series"].to_dict()
    readable = [x for x in sorted(lt["expiry"].unique()) if x in on_curve]
    # the two nearest expiries, plus every monthly contract (current, near, far): the smiles a trader rolls between
    pick = [x for i, x in enumerate(readable) if i < 2 or str(ser.get(x, "")).endswith(" month")]
    for e in pick:
        g = lt[lt["expiry"] == e].sort_values("strike")
        F = float(g["F"].iat[0])
        g = g[(g["strike"] / F).between(0.85, 1.15) & g["liquid"]]     # liquid traded strikes: no stale wing prints
        smiles.append({"expiry": str(pd.Timestamp(e).date()), "days": int((pd.Timestamp(e) - asof).days), "F": F,
                       "series": ser.get(e),
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
                             "roll_share": r.roll_share, "days": r.days,
                             # the live layer compares the live near-month future with these, the same contract:
                             "near_oi": r.near_oi, "fut_expiry": str(pd.Timestamp(r.fut_expiry).date())})
        recent_bu = [r["buildup"] for r in fut_rows[-5:]]
        fcard_row = fut_rows[-1] if fut_rows else None
        rolls = P.roll_history(book)
    fut_months = P.futures_months(opt, raw_close, asof)

    # events
    results = []
    if inst.kind == "stock" and not ev_cal.empty:
        e = ev_cal[ev_cal["symbol"] == inst.symbol]
        results = E.results_study(e, close, t, df["iv_front"], asof)
    ret = rv["ret"]
    macro = MX.study(close, df["iv_front"] if "iv_front" in df else None, macro_events(wh), asof)

    # cards
    vix_now = _last(vix) if inst.symbol == "NIFTY" else None
    cards = {
        "iv": N.iv_card(inst.symbol, cur("iv30"), iv_p1y, iv_pall, since, vix_now),
        "vrp": N.vrp_card(inst.symbol, cur("iv30"), cur("rv21"), vrp_p, rich_share, since),
        "term": N.term_card(inst.symbol, front_iv, back["iv"] if back else None, tn[0]["days"] if tn else None,
                            back["days"] if back else None, evv),
        "skew": N.skew_card(inst.symbol, cur("rr25"), rr_p),
        "realised": N.realised_card(inst.symbol, cur("rv21"), rv_p, cur("rv5"), cur("rv63"), comp_p),
        "oi": N.oi_card(inst.symbol, prof, spot_now, pcr_p),
        "futures": N.futures_card(inst.symbol, fcard_row, carry_p, recent_bu, carry_med),
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
        story.append(N.event_sentence(inst.symbol, evv))

    hi52 = float(close.tail(252).max())
    lo52 = float(close.tail(252).min())
    chg = float(close.iat[-1] / close.iat[-2] - 1) if len(close) > 1 else None
    up_res = next((r for r in results if r["upcoming"]), None)
    changes = day_changes(df)
    try:
        hol = list(pd.to_datetime(wh.holidays()["date"]))
    except Exception:                               # no holiday table: weekdays, as before
        hol = []
    rules = rules_block(opt, asof, inst, tn, hol)
    if inst.kind == "stock" and limits is not None:
        pl = RL.stock_block(inst.symbol, *limits)
        if pl:
            rules["position_limit"] = pl
            txt = RL.sentence(pl)
            if txt:
                rules["notes"].insert(0, {"kind": "ban" if pl.get("in_ban") else "mwpl", "text": txt})
    metrics = {
        "symbol": inst.symbol, "name": inst.name, "kind": inst.kind, "sector": inst.sector,
        "spot": spot_now, "chg": chg, "iv30": cur("iv30"), "iv30_chg5": (
            cur("iv30") - _ago(df["iv30"], 5)) if cur("iv30") is not None and _ago(df["iv30"], 5) else None,
        "iv_p1y": iv_p1y, "iv_pall": iv_pall, "rv21": cur("rv21"), "rv_p": rv_p,
        "vrp": cur("vrp"), "vrp_p": vrp_p, "rr25": cur("rr25"), "rr_p": rr_p,
        "move": tn[0]["move"] if tn else None, "move_days": tn[0]["days"] if tn else None,
        "pcr": cur("pcr_oi"), "pcr_p": pcr_p, "carry": cur("carry") if "carry" in df else None,
        "carry_p": carry_p, "fut_oi_chg": fcard_row["d_oi"] if fcard_row else None,
        "buildup": fcard_row["buildup"] if fcard_row else None, "event": (evv or {}).get("cause", "premium") if evv else None,
        "results": up_res["date"] if up_res else None, "comp_p": comp_p,
        "mwpl_util": (rules.get("position_limit") or {}).get("util"), "in_ban": (rules.get("position_limit") or {}).get("in_ban"),
        "inside": score.get("inside_all"), "changes": changes, "pos52": (spot_now - lo52) / (hi52 - lo52) if hi52 > lo52 else None,
    }
    cols = [c for c in ["close", "iv30", "iv_front", "rv21", "rv5", "rv63", "pk21", "fwd_rv21", "vrp", "rr25",
                        "pcr_oi", "pcr_vol", "opt_oi", "carry", "basis", "fut_oi", "roll_share", "vix",
                        "implied_move", "gamma_call", "gamma_put", "gamma_net", "iv60", "iv90", "term_60_30",
                        "iv_m1", "iv_m2", "iv_m3", "rr_m1", "rr_m2", "rr_m3", "days_m1", "cal_spread", "cal_carry", "own", "beta_n",
                        "mv_atr14", "mv_cc21", "mv_gk21", "mv_yz21", "mv_ovn_share", "mv_rng20_rank", "mv_bbw_rank",
                        "mv_vol_z", "mv_deliv", "mv_amihud", "mv_gap"] if c in df]
    out = {
        "meta": {"symbol": inst.symbol, "name": inst.name, "kind": inst.kind, "sector": inst.sector,
                 "exchange": inst.exchange, "asof": str(asof.date()), "since": since, "splits": splits, "actions": actions,
                 "stale": stale,
                 "regimes": regimes,
                 "build_seconds": round(time.time() - t0, 1)},
        "headline": {"spot": spot_now, "chg": chg, "hi52": hi52, "lo52": lo52, "metrics": metrics},
        "story": story, "cards": cards, "series": series(df, cols),
        "term": term, "smiles": smiles, "cone": cone, "scorecard": score,
        "scorecard_series": series(sc_series.set_index("date"), ["implied_move", "realised"]) if sc_series is not None and len(sc_series) else None,
        "oi_profile": prof, "gamma": gmap, "curve": months_curve, "expiry": xfront, "link": link, "movement": move_now, "lab": lab, "futures": fut_rows, "fut_months": fut_months, "rolls": rolls, "results": results, "macro": macro,
        "big_days": E.big_days(ret), "changes": changes, "rules": rules,
    }
    out = clean(out)
    # the daily panel the news reactions read (marketlens/news/reactions.py): a Parquet file beside the JSON, never in it
    keep = [c for c in ("close", "iv_front", "iv30", "rv21", "implied_move", "rr25", "beta_n", "own", "fut_oi", "basis", "pcr_oi", "opt_oi", "mv_gap")
            if c in df]
    out["_panel"] = df[keep].astype("float64")
    return out


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
                      f"long side: {N.level(fii['pct1y'])} for them against the past year ({N.ordinal(fii['pct1y'])} "
                      f"percentile; {N.ordinal(fii['pct'])} against every day since 2019).")
    if cli and cli["now"] is not None:
        simple.append(f"Retail and other individual traders (Clients) are {N.pct(cli['now'], 0)} long in index futures, "
                      f"{N.level(cli['pct1y'])} for them against the past year.")
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


def macro_events(wh: Warehouse) -> pd.DataFrame:
    """The global macro calendar (warehouse macro_events) with the desk's checked list of past macro days, cached."""
    if "macro_ev" not in wh._cache:
        from quantdesk.data import macro as QM
        try:
            raw = wh.macro_events()
        except Exception:                                # an unreadable table is the same as none
            raw = pd.DataFrame()
        parts = [x for x in (raw, QM.checked_history()) if len(x)]
        wh._cache["macro_ev"] = MX.events(pd.concat(parts, ignore_index=True) if parts else pd.DataFrame())
    return wh._cache["macro_ev"]


def event_risk(wh: Warehouse, asof, days: int = 7) -> list[dict]:
    """The high-impact macro events of the coming week: Market pulse's line and the calendar's top."""
    return MX.upcoming(macro_events(wh), asof, days=days, min_impact="High")


def calendar_block(wh: Warehouse, asof, sym_data: dict, ev_cal: pd.DataFrame) -> dict:
    items = []
    for m in MX.upcoming(macro_events(wh), asof, days=60, min_impact="Medium"):
        items.append({"date": m["date"], "type": "macro", "symbol": "", "country": m["country"], "impact": m["impact"], "time": m["time"],
                      "kind": m["kind"], "text": m["title"] + (f" (forecast {m['forecast']}, previous {m['previous']})" if m["forecast"] else
                                                               f" (previous {m['previous']})" if m["previous"] else ""),
                      "rule": m["source"] == "rule"})
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
    for s, d in sym_data.items():
        lc = d.get("rules", {}).get("lot_change")
        if lc:
            items.append({"date": lc["expiry"], "type": "lot", "symbol": s,
                          "text": f"{s} lot size {lc['from']:,.0f} -> {lc['to']:,.0f} from this expiry"})
    h = wh.holidays()
    for r in h.itertuples():
        if r.date > asof:
            items.append({"date": str(r.date.date()), "type": "holiday", "symbol": "", "text": f"Market holiday: {r.description}"})
    items = sorted(items, key=lambda x: x["date"])
    # one row per symbol per date
    seen, out = set(), []
    for i in items:
        k = (i["date"], i["type"], i["symbol"], i.get("text") if i["type"] == "macro" else "")
        if k not in seen:
            seen.add(k)
            out.append(i)
    return {"items": out[:160]}


def limits_block(limits, sym_data: dict) -> dict:
    """Market-wide: today's F&O ban list (all stocks, not only covered ones) and covered stocks near the limit."""
    if limits is None:
        return {"available": False}
    ban, mw = limits
    out: dict = {"available": True}
    read = ban.loc[ban["symbol"] == "", "date"] if len(ban) else pd.Series(dtype="datetime64[ns]")
    if len(read):
        last = read.max()
        out["ban_date"] = str(pd.Timestamp(last).date())
        out["ban"] = sorted(ban.loc[(ban["date"] == last) & (ban["symbol"] != ""), "symbol"].tolist())
    near = []
    for s, d in sym_data.items():
        pl = d.get("rules", {}).get("position_limit")
        if pl and pl.get("util") is not None and (pl["util"] >= 0.6 or pl.get("in_ban")):
            near.append({"symbol": s, "util": pl["util"], "in_ban": bool(pl.get("in_ban")), "chg5": pl.get("util_chg5")})
    out["near"] = sorted(near, key=lambda x: -x["util"])
    if len(mw):
        out["mwpl_date"] = str(pd.Timestamp(mw["date"].max()).date())
    return out


def live_base(d: dict) -> dict:
    """What the live layer compares against, per instrument, at the last close: each expiry's ATM IV and priced move
    (live IV is compared with the SAME expiry's close), the near-month future's close and OI (same contract), the
    front-expiry IV of the past year (for a live percentile), and the near-money OI by strike of the front expiries."""
    tn = d.get("term", {}).get("now", [])
    fr = (d.get("futures") or [None])[-1]
    ser = d.get("series", {})
    return {
        "asof": d["meta"]["asof"], "close": d["headline"]["spot"], "kind": d["meta"]["kind"],
        "term": [{"expiry": c["expiry"], "iv": c["iv"], "move": c["move"], "F": c["F"], "series": c.get("series")} for c in tn],
        "fut_months": [{"expiry": m["expiry"], "fut": m["fut"], "oi": m["oi"]} for m in d.get("fut_months") or []],
        "expiry_mp": ({"expiry": d["expiry"]["expiry"], "max_pain": d["expiry"]["max_pain"]} if d.get("expiry") else None),
        "fut": ({"fut": fr["fut"], "near_oi": fr["near_oi"], "fut_expiry": fr["fut_expiry"]} if fr else None),
        "iv_front": (ser.get("iv_front") or [])[-252:],
        # for live 30-day IV, its percentile and the live premium over realised vol (realised: at the last close)
        "iv30": (ser.get("iv30") or [])[-252:],
        "vrp": (ser.get("vrp") or [])[-252:],
        "rv21": next((x for x in reversed(ser.get("rv21") or []) if x is not None), None),
        "carry": [x for x in (ser.get("carry") or [])[-252:] if x is not None],
        # the gamma map's participant weights (indices) and its close-of-day net and flip, for the live comparison
        "gamma": ({k: (d.get("gamma") or {}).get(k) for k in ("weights", "net_total", "flip", "call_total", "put_total")}
                  if d.get("gamma") else None),
        "oi": [{"expiry": p["expiry"], "strikes": p["strikes"], "call_oi": p["call_oi"], "put_oi": p["put_oi"]}
               for p in d.get("oi_profile", [])[:2]],
    }


def changes_feed(sym_data: dict, n: int = 10) -> list[dict]:
    """The day's most unusual changes across all instruments, each measured against that instrument's own history."""
    rows = []
    for s, d in sym_data.items():
        for c in d.get("changes", []):
            if c.get("z") is None:
                continue
            up = c["chg"] > 0
            verb = {"iv30": ("options got pricier" if up else "options got cheaper"),
                    "rr25": ("downside protection got cheaper relative to calls" if up else "downside protection got dearer"),
                    "rv21": ("it has been moving more" if up else "it has been moving less")}.get(c["field"], c["label"])
            rows.append({"symbol": s, "field": c["field"], "z": c["z"], "chg": c["chg"], "unit": c["unit"],
                         "text": f"{s}: {verb}. {c['label']} {c['from']:.1f} -> {c['to']:.1f} ({c['chg']:+.1f} {c['unit']}), "
                                 f"a {abs(c['z']):.1f}-sigma day for {s}."})
    rows.sort(key=lambda r: -abs(r["z"]))
    return [r for r in rows if abs(r["z"]) >= 1.5][:n]


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


def health_block(wh: Warehouse, data: dict, asof) -> dict:
    """What the app was built from: each warehouse table's latest day (from its newest file only), how many sessions that
    is behind the build's as-of day, and each instrument's own as-of day and the readings it had to leave blank."""
    from .data import TABLES
    sess = pd.bdate_range(end=asof, periods=30)
    tables = []
    for t in TABLES:
        files = wh.files(t)
        if not files:
            tables.append({"table": t, "files": 0, "last": None, "behind": None})
            continue
        try:
            df = pd.read_parquet(files[-1])
            col = "date" if "date" in df else ("ts" if "ts" in df else None)
            last = pd.to_datetime(df[col]).max() if col and len(df) else None
            if last is not None and getattr(last, "tzinfo", None) is not None:
                last = last.tz_localize(None)
        except Exception:                            # an unreadable file is itself a health finding
            last = None
        behind = None if last is None else int(((sess > pd.Timestamp(last).normalize()) & (sess <= asof)).sum())
        tables.append({"table": t, "files": len(files), "last": None if last is None else str(pd.Timestamp(last).date()), "behind": behind})
    inst = [{"symbol": s_, "asof": d["meta"]["asof"], "stale": d["meta"].get("stale") or {}, "seconds": d["meta"].get("build_seconds"),
             "since": d["meta"].get("since")} for s_, d in data.items()]
    return {"asof": str(pd.Timestamp(asof).date()), "tables": tables, "instruments": inst}


def dispersion_block(wh: Warehouse, asof, iv_panel, say=print) -> dict:
    """Implied against realised correlation for each index whose members can be listed (engine/dispersion.py)."""
    from . import dispersion as DS
    out = {}
    if iv_panel is None:
        return out
    ic = wh.index_close()
    for idx in DS.LISTS:
        try:
            mem, src = DS.members(idx)
            if not mem:
                continue
            rm = DS.returns({s: wh.cash(s) for s in mem})
            if rm.shape[1] < 0.8 * len(mem):
                say(f"  dispersion {idx}: only {rm.shape[1]} of {len(mem)} members have cash data")
                continue
            close = ic[ic["index"] == DS.INDEX_NAME[idx]].drop_duplicates("date", keep="last").set_index("date")["close"].sort_index()
            ri = np.log(close).diff()
            ivi = BR.straddle_iv(wh.options(idx).assign(symbol=idx)).set_index("date")["iv"]
            st = DS.study(idx, ri, rm, ivi, iv_panel.reindex(columns=mem), asof)
            if st:
                st["members_source"] = src
                out[idx] = st
                say(f"  dispersion {idx}: fit R2 {st['fit_r2']:.4f}, implied correlation {st['implied']}")
        except Exception as e:                      # one index failing skips only itself
            say(f"  dispersion {idx}: FAILED {type(e).__name__}: {e}")
    return out


def news_block(wh, news: Path | None, asof, out: Path, say=print) -> list[dict]:
    """The News page (news/cards.py): situation cards from the news corpus and the warehouse, rebuilt every day (no
    Claude here; the Opus briefs are read from the folder if they were written). Writes news.json; returns the overview's
    short list of what is flaring or active."""
    if news is None or not any(Path(news).glob("news_*.parquet")):
        return []
    try:
        from ..news import cards as NCD, corpus as NC, situations as NS
        stories = NC.Corpus(Path(news)).read()
        nj = NCD.build(stories, *NS.inputs(wh), briefs=NCD.load_briefs(Path(news)), asof=asof)
        (out / "news.json").write_text(json.dumps(nj, separators=(",", ":")))
        say(f"  news: {nj['stories']} stories, {len(nj['situations'])} situations, "
            f"{sum(1 for c in nj['situations'] if c['brief'])} with a brief")
        return [{"id": c["id"], "name": c["name"], "heat": c["activity"]["heat"], "last7": c["activity"]["last7"],
                 "typical7": c["activity"]["typical7"]} for c in nj["situations"] if c["activity"]["heat"] != "quiet"][:4]
    except Exception as e:                          # the news is extra: it never stops the build
        say(f"  news: FAILED {type(e).__name__}: {e}")
        return []


def build(warehouse: Path, out: Path, symbols: list[str] | None = None, say=print, news: Path | None = None) -> dict:
    wh = Warehouse(warehouse)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sym").mkdir(exist_ok=True)
    vix = wh.spot("INDIAVIX")["close"]
    ev = wh.corp_events()
    ev_cal = E.results_calendar(ev, [s.symbol for s in U.STOCKS], None)
    insts = [i for i in U.ALL if not symbols or i.symbol in symbols]
    limits = RL.load(warehouse)
    limits = limits if (len(limits[0]) or len(limits[1])) else None
    data = {}
    for inst in insts:
        try:
            d = analyse(wh, inst, vix, ev_cal, limits)
        except Exception as e:                      # one bad instrument never stops the build
            say(f"  {inst.symbol}: FAILED {type(e).__name__}: {e}")
            continue
        if not d:
            say(f"  {inst.symbol}: no data")
            continue
        panel = d.pop("_panel", None)
        data[inst.symbol] = d
        (out / "sym" / f"{U.slug(inst.symbol)}.json").write_text(json.dumps(d, separators=(",", ":")))
        if panel is not None and len(panel):
            (out / "panels").mkdir(exist_ok=True)
            panel.rename_axis("date").to_parquet(out / "panels" / f"{U.slug(inst.symbol)}.parquet")
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
        "event_risk": event_risk(wh, asof),
        "news_top": news_block(wh, news, asof, out, say),
        "changes": changes_feed(data),
        "live_base": {s: live_base(d) for s, d in data.items()},
        "limits": limits_block(limits, data),
        "health": health_block(wh, data, asof),
        "universe": [{"symbol": i.symbol, "name": i.name, "kind": i.kind, "sector": i.sector, "slug": U.slug(i.symbol)}
                     for i in insts if i.symbol in data],
    }
    # the heavy parts each page does not need go in their own files: the participant history (Who holds what) and the
    # live baseline (live mode and the Worker's alerts); every page loads the overview, so it stays small
    (out / "participants.json").write_text(json.dumps(clean({"series": overview["participants"].pop("series", {})}), separators=(",", ":")))
    (out / "live_base.json").write_text(json.dumps(clean(overview.pop("live_base")), separators=(",", ":")))
    (out / "overview.json").write_text(json.dumps(clean(overview), separators=(",", ":")))
    # MCX commodities' public side: the international benchmarks they track (engine/commodities.py), own file
    try:
        from . import commodities as CMD
        cm = CMD.board(wh.globals_(), asof)
        (out / "commodities.json").write_text(json.dumps(clean(cm), separators=(",", ":")))
        say(f"  commodities: {len(cm.get('contracts', {}))} contracts with a benchmark" if cm else "  commodities: no global_daily yet")
    except Exception as e:                          # never stops the build
        say(f"  commodities: FAILED {type(e).__name__}: {e}")
    # the whole F&O market: its own file, read only by the breadth page
    try:
        br = BR.market(Path(warehouse), asof)
        br["sectors"] = BR.sector_board(wh.index_close(), asof)
        br["dispersion"] = dispersion_block(wh, asof, getattr(BR.market, "iv_panel", None), say)
        br["asof"] = str(asof.date())
        (out / "breadth.json").write_text(json.dumps(clean(br), separators=(",", ":")))
        say(f"  breadth: {br['today']['n_iv']} stocks with a vol reading, {br['today']['n_fut']} with a futures read")
    except Exception as e:                          # breadth is extra: it never stops the build
        say(f"  breadth: FAILED {type(e).__name__}: {e}")
    return overview
