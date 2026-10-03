"""Index breadth: how many of the index's own stocks are moving with it.

A NIFTY move carried by three heavyweights while most of the fifty fall is fragile; a move most of them join is
broad. Per index (NIFTY 50, Nifty Bank), once a minute from Kotak's quotes (≈57 stocks: 3 calls of 25):

* **advancers**: the share of members above yesterday's close (Kotak's `per_change`);
* **above VWAP**: the share trading above their own session VWAP (Kotak's `avg_cost`, the day's average traded
  price): who is being bought *today*, not just carried by a gap;
* **equal weight vs the index**: the members' average move minus the index's own (cap-weighted) move. Negative: the
  index is being carried by its largest names; positive: the broad market is ahead of them;
* the same shares 30 minutes earlier, for thrusts.

Two directional reads go to the analyst **on probation** (graded live from the first session; a vote only once 30
graded reads at 1.15× reliability earn it, as for the other probation factors):

* `breadth`: participation, the shares above VWAP and advancing centred on one half;
* `breadth_div`: a narrow move, the index up on the day while most of its members are down (or carried by its
  largest names), leans against the index; and the reverse.

Members come from NSE's published index lists (…/content/indices/ind_nifty50list.csv), else the built-in lists below
(as of late 2025; the state's `members_source` says which). Tokens: each stock future's `pAssetCode` in Kotak's F&O
scrip master is the stock's cash-market token (RELIANCE 2885, seen on a runner on 3 Oct 2026), quoted as
`nse_cm|<token>`; the cash scrip master (`pTrdSymbol` SYMBOL-EQ) fills any gap.
"""
from __future__ import annotations

import io
from collections import deque
from typing import Callable

import numpy as np
import pandas as pd

KEEP_MIN = 120                       # minutes of breadth history kept per index
TREND_MIN = 30                       # the window thrusts are measured over
MIN_COVERAGE = 0.6                   # below this share of members quoted, no read
NAMES = {"NIFTY": "NIFTY 50", "BANKNIFTY": "Nifty Bank"}

# fallbacks when NSE's list can't be fetched (late 2025: after the Sep-2025 rebalance and the Tata Motors demerger)
NIFTY50 = ("ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE",
           "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK",
           "HDFCLIFE", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDIGO", "INFY", "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK",
           "LT", "M&M", "MARUTI", "MAXHEALTH", "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN",
           "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATASTEEL", "TCS", "TECHM", "TITAN", "TMPV", "TRENT", "ULTRACEMCO",
           "WIPRO")
NIFTYBANK = ("AUBANK", "AXISBANK", "BANKBARODA", "CANBK", "FEDERALBNK", "HDFCBANK", "ICICIBANK", "IDFCFIRSTB",
             "INDUSINDBK", "KOTAKBANK", "PNB", "SBIN")
LISTS = {"NIFTY": ("ind_nifty50list.csv", NIFTY50), "BANKNIFTY": ("ind_niftybanklist.csv", NIFTYBANK)}


def _f(x) -> float:
    try:
        v = float(str(x).replace(",", "")) if x is not None else float("nan")
    except ValueError:
        return float("nan")
    return v if np.isfinite(v) else float("nan")


# ---- who is in the index, and their tokens ---------------------------------------------------------------------------
def parse_index_list(b: bytes) -> list[str]:
    """NSE's index constituent CSV (Company Name, Industry, Symbol, Series, ISIN Code) → symbols."""
    df = pd.read_csv(io.BytesIO(b))
    col = next((c for c in df.columns if str(c).strip().lower() == "symbol"), None)
    if col is None:
        raise ValueError(f"no Symbol column in the index list: {list(df.columns)[:6]}")
    return [str(s).strip().upper() for s in df[col].dropna() if str(s).strip()]


def index_members(u: str, fetch: Callable[[str], bytes] | None = None) -> tuple[list[str], str]:
    """(members of `u`'s index, where the list came from). `fetch(path)` → bytes from NSE's archives, or None."""
    name, fallback = LISTS[u]
    if fetch is not None:
        try:
            syms = parse_index_list(fetch(f"/content/indices/{name}"))
            if len(syms) >= 0.8 * len(fallback):
                return syms, f"NSE {name}"
        except Exception:
            pass
    return list(fallback), "built-in list (late 2025)"


def nse_list_fetcher(nse) -> Callable[[str], bytes]:
    """fetch(path) for index_members: NSE's archives (…/content/indices/<file>), then niftyindices.com's copy."""
    def fetch(path: str) -> bytes:
        try:
            return nse.archive(path)[0]
        except Exception:
            r = nse.s.get("https://www.niftyindices.com/IndexConstituent/" + path.rsplit("/", 1)[-1], timeout=20)
            if r.status_code != 200 or b"Symbol" not in r.content[:400]:
                raise RuntimeError(f"niftyindices answered HTTP {r.status_code}")
            return r.content
    return fetch


def cash_tokens(fo_master: pd.DataFrame | None, symbols, cm_master: pd.DataFrame | None = None) -> dict[str, str]:
    """{symbol: cash-market token}: each stock future's pAssetCode in the F&O scrip master, then SYMBOL-EQ rows of the
    cash scrip master for anything missing."""
    want = {str(s).upper() for s in symbols}
    out: dict[str, str] = {}
    if fo_master is not None and len(fo_master):
        c = {k.lower(): k for k in fo_master.columns}
        sym, typ, asset = c.get("psymbolname"), c.get("pinsttype"), c.get("passetcode")
        if sym and typ and asset:
            f = fo_master[fo_master[typ].astype(str).str.upper().eq("FUTSTK")]
            f = f[f[sym].astype(str).str.upper().isin(want)]
            for s, a in zip(f[sym].astype(str).str.upper(), f[asset]):
                a = _f(a)
                if a > 0:
                    out.setdefault(s, str(int(a)))
    missing = want - set(out)
    if missing and cm_master is not None and len(cm_master):
        c = {k.lower(): k for k in cm_master.columns}
        trd, tok = c.get("ptrdsymbol"), c.get("psymbol")
        if trd and tok:
            eq = cm_master[cm_master[trd].astype(str).str.upper().isin({f"{m}-EQ" for m in missing})]
            for t, k in zip(eq[trd].astype(str).str.upper(), eq[tok]):
                k = _f(k)
                if k > 0:
                    out.setdefault(t[:-3], str(int(k)))
    return out


def quote_row(q: dict) -> dict | None:
    """One Kotak quote → {ltp, chg (vs yesterday's close), vwap (the day's average traded price)}."""
    ltp = _f(q.get("ltp"))
    if not ltp > 0:
        return None
    pc, ch = _f(q.get("per_change")), _f(q.get("change"))
    if pc == pc:
        chg = pc / 100
    elif ch == ch and ltp - ch > 0:
        chg = ch / (ltp - ch)
    else:
        return None
    vwap = _f(q.get("avg_cost"))
    return {"ltp": ltp, "chg": float(chg), "vwap": vwap if vwap > 0 else float("nan")}


class KotakBreadthSource:
    """`source(now)` for Breadth: the members' quotes from Kotak, `client.batch` per call."""

    def __init__(self, client, tokens: dict[str, str]):
        self.k, self.tokens = client, dict(tokens)
        self.by_token = {t: s for s, t in self.tokens.items()}

    def __call__(self, now) -> dict[str, dict]:
        out = {}
        for q in self.k.quotes([("nse_cm", t) for t in self.tokens.values()], "all"):
            s = self.by_token.get(str(q.get("exchange_token", "")))
            row = quote_row(q) if s else None
            if row:
                out[s] = row
        return out


# ---- the read --------------------------------------------------------------------------------------------------------
def summarize(members, snap: dict[str, dict]) -> dict | None:
    rows = [snap[m] for m in members if m in snap and snap[m].get("chg") == snap[m].get("chg")]
    if not members or len(rows) < MIN_COVERAGE * len(members):
        return None
    chg = np.array([r["chg"] for r in rows])
    vw = [(r["ltp"], r["vwap"]) for r in rows if r.get("vwap") == r.get("vwap")]
    return {"n": len(rows), "members": len(members), "adv": float((chg > 0).mean()), "dec": float((chg < 0).mean()),
            "above_vwap": float(np.mean([p > v for p, v in vw])) if len(vw) >= MIN_COVERAGE * len(members) else None,
            "ew_chg": float(chg.mean()), "median_chg": float(np.median(chg))}


class Breadth:
    """One per desk. `refresh(now)` polls the source at most every `refresh_min` minutes; `state(u, index_chg, now)`
    is the read for the analyst and the app."""

    def __init__(self, members: dict[str, list[str]], source: Callable, refresh_min: float = 1.0,
                 members_source: dict[str, str] | None = None):
        self.members = {u: list(m) for u, m in members.items() if m}
        self.source, self.refresh_min = source, float(refresh_min)
        self.members_source = members_source or {}
        self.snap: dict[str, dict] = {}
        self.at: pd.Timestamp | None = None
        self.day = None
        self.hist: dict[str, deque] = {u: deque() for u in self.members}
        self.health = ""

    def refresh(self, now: pd.Timestamp, force: bool = False) -> bool:
        if not force and self.at is not None and now - self.at < pd.Timedelta(minutes=self.refresh_min):
            return False
        self.at = now
        if self.day != now.date():
            self.day, self.hist = now.date(), {u: deque() for u in self.members}
        try:
            snap = self.source(now) or {}
        except Exception as exc:
            self.health = f"fail {exc!s:.120}"
            return False
        self.snap = snap
        self.health = f"ok {len(snap)} quotes"
        for u, m in self.members.items():
            s = summarize(m, snap)
            if s is None:
                continue
            h = self.hist[u]
            h.append((now, s))
            while h and now - h[0][0] > pd.Timedelta(minutes=KEEP_MIN):
                h.popleft()
        return True

    def state(self, u: str, index_chg: float | None, now: pd.Timestamp) -> dict | None:
        h = self.hist.get(u)
        if not h or now - h[-1][0] > pd.Timedelta(minutes=10):        # nothing, or a read too old to use
            return None
        ts, cur = h[-1]
        out = {**cur, "index": NAMES.get(u, u), "ts": str(ts), "members_source": self.members_source.get(u, "")}
        if index_chg is not None and index_chg == index_chg:
            out["index_chg"] = float(index_chg)
            out["ew_gap"] = cur["ew_chg"] - float(index_chg)
        ago = next((s for t, s in reversed(h) if t <= now - pd.Timedelta(minutes=TREND_MIN)), None)
        if ago is None and now - h[0][0] >= pd.Timedelta(minutes=TREND_MIN * 0.8):
            ago = h[0][1]
        if ago is not None:
            out["adv_chg30"] = cur["adv"] - ago["adv"]
            if cur.get("above_vwap") is not None and ago.get("above_vwap") is not None:
                out["vwap_chg30"] = cur["above_vwap"] - ago["above_vwap"]
        moves = sorted(((m, self.snap[m]["chg"]) for m in self.members[u] if m in self.snap), key=lambda x: x[1])
        out["up"] = [(m, round(c, 5)) for m, c in reversed(moves[-3:]) if c > 0]
        out["down"] = [(m, round(c, 5)) for m, c in moves[:3] if c < 0]
        return out


def breadth_signal(b: dict | None) -> tuple[float, str] | None:
    """Participation as a direction: the shares above VWAP and advancing, each centred on one half (70% and 70% →
    +0.6; 80% and 80% → +0.9). None when it's close to even."""
    if not b:
        return None
    vw = b["above_vwap"] if b.get("above_vwap") is not None else b["adv"]
    d = float(np.clip(((vw - 0.5) + (b["adv"] - 0.5)) * 1.5, -1, 1))
    if abs(d) < 0.15:
        return None
    n = b["n"]
    obs = (f"{b['index']} breadth: {round(b['adv'] * n)} of {n} stocks up on the day"
           + (f", {round(b['above_vwap'] * n)} above their VWAP" if b.get("above_vwap") is not None else ""))
    if b.get("vwap_chg30") is not None and abs(b["vwap_chg30"]) >= 0.1:
        obs += f" ({b['vwap_chg30']:+.0%} above VWAP in 30 min)"
    if b.get("ew_gap") is not None:
        obs += f"; equal weight {b['ew_chg']:+.2%} vs the index {b['index_chg']:+.2%}"
    return d, obs


def divergence_signal(b: dict | None, min_move: float = 0.0015, gap: float = 0.002) -> tuple[float, str] | None:
    """A narrow move leans against the index: up on the day with most members down (or the equal-weight average well
    behind the index: carried by its largest names), and the reverse. None when the move is broad or small."""
    if not b or b.get("index_chg") is None or abs(b["index_chg"]) < min_move:
        return None
    s = float(np.sign(b["index_chg"]))
    against = (0.45 - b["adv"]) if s > 0 else (b["adv"] - 0.55)            # members going the other way
    carried = -s * b.get("ew_gap", 0.0) - gap                              # the index ahead of its own average
    if against <= 0 and carried <= 0:
        return None
    strength = max(against, 0) / 0.25 + max(carried, 0) / 0.006
    d = -s * float(np.clip(0.3 + 0.7 * strength, 0.3, 1.0))
    what = "rally" if s > 0 else "sell-off"
    names = ", ".join(m for m, _ in (b.get("up") if s > 0 else b.get("down")) or []) or "a few names"
    return d, (f"narrow {what}: {b['index']} {b['index_chg']:+.2%} but {b['adv']:.0%} of its stocks up, equal weight "
               f"{b['ew_chg']:+.2%}, carried by {names} → leans against the move")


def make_breadth(cfg, client, nse=None, say=print) -> Breadth | None:
    """The live desk's breadth: members from NSE (or the built-in lists), tokens from Kotak's scrip master. None when
    too few tokens resolve (the desk then simply reads without breadth)."""
    from .kotak import scrip_master
    bc = cfg.get("intraday.breadth", {}) or {}
    unders = [u for u in (cfg.get("intraday.underlyings") or []) if u in LISTS]
    fetch = nse_list_fetcher(nse) if nse is not None else None
    members, src = {}, {}
    for u in unders:
        members[u], src[u] = index_members(u, fetch)
    want = sorted({m for ms in members.values() for m in ms})
    try:
        fo = scrip_master(client, "nse_fo")
    except Exception as exc:
        say(f"breadth: F&O scrip master unavailable ({exc!s:.120})")
        fo = None
    toks = cash_tokens(fo, want)
    if len(toks) < len(want):
        try:
            toks = cash_tokens(fo, want, scrip_master(client, "nse_cm"))
        except Exception:
            pass
    missing = sorted(set(want) - set(toks))
    members = {u: [m for m in ms if m in toks] for u, ms in members.items()}
    if not toks or any(len(ms) < MIN_COVERAGE * len(LISTS[u][1]) for u, ms in members.items()):
        say(f"breadth: off ({len(toks)} of {len(want)} tokens found)")
        return None
    say(f"breadth: {len(toks)} stocks ({', '.join(f'{u} {len(m)} from {src[u]}' for u, m in members.items())})"
        + (f"; no token for {', '.join(missing)}" if missing else ""))
    return Breadth(members, KotakBreadthSource(client, toks), float(bc.get("refresh_min", 1)), src)
