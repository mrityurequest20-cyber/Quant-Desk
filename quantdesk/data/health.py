"""Data health: did each data channel deliver, and is what arrived sane? (Phase 1 of docs/RENAISSANCE.md, "data you can trust".)

One report per trading day. A channel is a place data lands (the recorder's bars and option chains, the minute backfills, the NSE
warehouse, the pre-market brief, the Kite ticks). For each, the report says OK, WARN (arrived with a fault), BAD (arrived badly),
MISSING (due and not there) or PENDING (not yet due), and why, with the numbers. It only READS: public release assets, two public
branches and the public Actions API. It writes nothing, holds no secret, and fails soft: a channel it cannot look at is reported
as such, never as fine.

Thresholds come from looking at real healthy data (6 Nov 2026), not from guesses:
  * a session is 375 one-minute bars, 09:15 to 15:29; the exit criterion in the plan is 98% complete
  * NIFTY and BANKNIFTY spot sit flat for the closing auction (about 15:14 to 15:28, with volume still printing): that is the
    exchange, not the feed, so flat runs inside the closing window are ignored and flat runs elsewhere are not
  * the Kotak chain feed delivers a snapshot about every minute for every index; the tape records every fetch attempt, and about
    99.8% succeed on a healthy day
  * open interest below zero or beyond 1e12 is corruption (the real feed produced -9.08e18, an integer overflow, on one BANKNIFTY
    strike for hours): `chain_fault_mask` marks such rows so a consumer can quarantine them instead of using them

`critical` channels decide the exit code of `quantdesk data health`; the others are shown but do not fail the run.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from ..markets import sessions as MK

IST = MK.IST
OK, WARN, BAD, MISSING, PENDING = "ok", "warn", "bad", "missing", "pending"
SEVERITY = {OK: 0, PENDING: 1, WARN: 2, MISSING: 3, BAD: 3}

BAR_SYMBOLS = ("NIFTY", "BANKNIFTY", "INDIAVIX", "NIFTY-FUT", "BANKNIFTY-FUT")
CHAIN_UNDERLYINGS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")
CORE_WAREHOUSE_TABLES = ("fo_bhav", "fo_stock_opts", "participant_oi", "participant_vol", "nse_index_close", "bse_fo_bhav")
SESSION_MINUTES = 375                       # 09:15 .. 15:29
COMPLETE = 0.98                             # the plan's exit criterion
BAD_BELOW = 0.90
FLAT_RUN = 10                               # minutes of an unchanged close that is not the closing auction
CLOSING_WINDOW_START = dt.time(15, 10)
OI_ABSURD = 1e12
KITE_LOOKBACK_DAYS = 3                      # kite_artifacts lists only the newest 20 recorder runs
TAPE_WARN, TAPE_BAD = 0.05, 0.20            # share of failed fetch attempts
# when each channel is due, IST on the trading day (before that it is PENDING, not MISSING)
DUE = {"gift": dt.time(9, 0), "premarket": dt.time(9, 20), "session": dt.time(16, 30), "minutes": dt.time(18, 30),
       "kite": dt.time(16, 30), "warehouse": dt.time(21, 0),
       "evening": dt.time(7, 0),                  # the PREVIOUS evening's MCX/currency minutes (collected at 23:45): judged from 07:00 the next morning
       "history": dt.time(0, 0)}


@dataclass
class Check:
    channel: str
    status: str
    detail: str
    critical: bool = False
    metrics: dict = field(default_factory=dict)


@dataclass
class Report:
    day: str
    generated_at: str
    checks: list[Check]

    def worst(self, critical_only: bool = False) -> int:
        return max((SEVERITY[c.status] for c in self.checks if c.critical or not critical_only), default=0)

    def failed(self) -> bool:
        """True when a critical channel is BAD or MISSING."""
        return any(c.critical and c.status in (BAD, MISSING) for c in self.checks)

    def to_dict(self) -> dict:
        return {"day": self.day, "generated_at": self.generated_at, "failed": self.failed(), "checks": [asdict(c) for c in self.checks]}

    def markdown(self) -> str:
        icon = {OK: "ok", WARN: "WARN", BAD: "BAD", MISSING: "MISSING", PENDING: "pending"}
        lines = [f"### Data health, {self.day}", "", "| channel | status | detail |", "|---|---|---|"]
        for c in self.checks:
            lines.append(f"| {c.channel}{' *' if c.critical else ''} | **{icon[c.status]}** | {c.detail} |")
        lines += ["", "\\* critical: a bad or missing one fails the run.", f"_Generated {self.generated_at}._"]
        return "\n".join(lines)


# ---- where the data is read from -------------------------------------------------------------------------------------------------
def retry_delay(code: int, headers, attempt: int, cap: float = 60.0) -> float:
    """Seconds to wait before the next try: Retry-After if GitHub sent one, else until X-RateLimit-Reset when the limit is spent (rate limits
    answer 403 or 429), else a short doubling pause. Never more than `cap`."""
    h = (lambda k: headers.get(k)) if headers is not None else (lambda k: None)
    try:
        if code in (403, 429):
            if h("Retry-After"):
                return min(cap, max(0.0, float(h("Retry-After"))))
            if h("X-RateLimit-Remaining") == "0" and h("X-RateLimit-Reset"):
                return min(cap, max(0.0, float(h("X-RateLimit-Reset")) - time.time()))
    except (TypeError, ValueError):
        pass
    return min(cap, 2.0 * (2 ** attempt))


class GitHubStore:
    """Read-only access to this repository's public releases, branches and Actions runs over HTTPS. A token, if given, only raises the rate
    limit; it is sent as a header and never printed."""

    def __init__(self, repo: str = "mrityurequest20-cyber/Quant-Desk", token: str | None = None, timeout: float = 40.0):
        self.repo, self.token, self.timeout = repo, token, timeout
        self._releases: list[dict] | None = None

    def _open(self, url: str) -> bytes:
        headers = {"User-Agent": "quantdesk-data-health", "Accept": "application/vnd.github+json"}
        if self.token and "api.github.com" in url:
            headers["Authorization"] = f"Bearer {self.token}"
        last = None
        for attempt in range(3):
            delay = 0.0
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise FileNotFoundError(url) from None
                last, delay = e, retry_delay(e.code, e.headers, attempt)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last, delay = e, retry_delay(0, None, attempt)
            if attempt < 2:
                time.sleep(delay)
        raise ConnectionError(f"could not read {url.split('?')[0]} ({type(last).__name__})")

    def _releases_list(self) -> list[dict]:
        if self._releases is None:
            out, page = [], 1
            while page <= 5:
                got = json.loads(self._open(f"https://api.github.com/repos/{self.repo}/releases?per_page=100&page={page}"))
                out += got
                if len(got) < 100:
                    break
                page += 1
            self._releases = out
        return self._releases

    def tags(self, prefix: str) -> list[str]:
        return sorted(r["tag_name"] for r in self._releases_list() if r["tag_name"].startswith(prefix))

    def assets(self, tag: str) -> dict[str, dict]:
        for r in self._releases_list():
            if r["tag_name"] == tag:
                return {a["name"]: {"size": a["size"], "updated": a["updated_at"], "url": a["browser_download_url"]} for a in r["assets"]}
        return {}

    def read(self, tag: str, name: str) -> bytes:
        return self._open(self.assets(tag)[name]["url"])

    def branch_file(self, branch: str, path: str) -> bytes | None:
        try:
            return self._open(f"https://raw.githubusercontent.com/{self.repo}/{branch}/{path}")
        except FileNotFoundError:
            return None

    def kite_artifacts(self, day: dt.date) -> list[dict] | None:
        """The tick artifacts of that day's Kite recorder runs ({name, size}); None if the Actions API cannot be read."""
        try:
            runs = json.loads(self._open(f"https://api.github.com/repos/{self.repo}/actions/workflows/kite-record.yml/runs?per_page=20"))
            out = []
            for r in runs.get("workflow_runs", []):
                started = dt.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).astimezone(IST).date()
                if started != day:
                    continue
                arts = json.loads(self._open(f"https://api.github.com/repos/{self.repo}/actions/runs/{r['id']}/artifacts"))
                out += [{"name": a["name"], "size": a["size_in_bytes"], "expired": a["expired"]} for a in arts.get("artifacts", [])]
            return out
        except (ConnectionError, FileNotFoundError, ValueError):
            return None


class MemoryStore:
    """The same reads over dictionaries, for tests."""

    def __init__(self, releases: dict[str, dict[str, bytes]] | None = None, branches: dict[str, dict[str, bytes]] | None = None,
                 kite: list[dict] | None = None):
        self.releases, self.branches, self.kite = releases or {}, branches or {}, kite

    def tags(self, prefix: str) -> list[str]:
        return sorted(t for t in self.releases if t.startswith(prefix))

    def assets(self, tag: str) -> dict[str, dict]:
        return {n: {"size": len(b), "updated": "", "url": ""} for n, b in self.releases.get(tag, {}).items()}

    def read(self, tag: str, name: str) -> bytes:
        return self.releases[tag][name]

    def branch_file(self, branch: str, path: str) -> bytes | None:
        return self.branches.get(branch, {}).get(path)

    def kite_artifacts(self, day: dt.date) -> list[dict] | None:
        return self.kite


def _find(store, prefix: str, tag_prefix: str, suffix: str, exclude: tuple = ()) -> list[tuple[str, str]]:
    out = []
    for tag in store.tags(tag_prefix):
        for name in store.assets(tag):
            if name.startswith(prefix) and name.endswith(suffix) and not any(x in name for x in exclude):
                out.append((tag, name))
    return sorted(out)


def _frames(store, files) -> pd.DataFrame:
    parts = [pd.read_parquet(io.BytesIO(store.read(t, n))) for t, n in files]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _to_ist(s: pd.Series) -> pd.Series:
    s = pd.to_datetime(s)
    return s.dt.tz_localize(IST) if s.dt.tz is None else s.dt.tz_convert(IST)


def _grid(day: dt.date, end: dt.time = dt.time(15, 29)) -> pd.DatetimeIndex:
    return pd.date_range(dt.datetime.combine(day, dt.time(9, 15), tzinfo=IST), dt.datetime.combine(day, end, tzinfo=IST), freq="min")


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _longest_gap(present: pd.DatetimeIndex, grid: pd.DatetimeIndex) -> int:
    miss = ~grid.isin(present)
    best = run = 0
    for m in miss:
        run = run + 1 if m else 0
        best = max(best, run)
    return best


def _flat_runs(d: pd.DataFrame) -> list[tuple[str, int]]:
    """Runs of an unchanged close of FLAT_RUN minutes or more that do not sit inside the closing auction window."""
    d = d.sort_values("min")
    grp = ((d["close"] != d["close"].shift()) | (d["min"].diff() != pd.Timedelta(minutes=1))).cumsum()      # a missing minute ends a run
    out = []
    for _, g in d.groupby(grp):
        if len(g) >= FLAT_RUN and g["min"].iloc[0].time() < CLOSING_WINDOW_START:
            out.append((g["min"].iloc[0].strftime("%H:%M"), len(g)))
    return out


# ---- the session recorder: bars, chains, tape, gift --------------------------------------------------------------------------------
def check_bars(store, day: dt.date) -> Check:
    files = _find(store, f"{day}_", "chains-", "_bars.parquet")
    if not files:
        return Check("session bars", MISSING, "no bars file for the day", True)
    b = _frames(store, files)
    b["ts"] = _to_ist(b["ts"])
    b["min"] = b["ts"].dt.floor("min")
    conflicts = int((b.groupby(["symbol", "min"])["close"].nunique() > 1).sum())          # the morning and afternoon jobs overlap: they must agree
    d = b.sort_values("ts").drop_duplicates(["symbol", "min"], keep="last")
    grid = _grid(day)
    per, issues, worst = {}, [], 1.0
    for s in BAR_SYMBOLS:
        x = d[d["symbol"] == s]
        if x.empty:
            per[s] = {"completeness": 0.0}
            issues.append(f"{s}: no bars")
            worst = 0.0
            continue
        have = x["min"][x["min"].isin(grid)].nunique()
        comp = have / SESSION_MINUTES
        bad_ohlc = int(((x["high"] < x[["open", "close"]].max(axis=1) - 1e-9) | (x["low"] > x[["open", "close"]].min(axis=1) + 1e-9)
                        | (x[["open", "high", "low", "close"]].isna().any(axis=1)) | (x[["open", "high", "low", "close"]] <= 0).any(axis=1)).sum())
        flat = _flat_runs(x)
        per[s] = {"completeness": round(comp, 4), "longest_gap_min": _longest_gap(pd.DatetimeIndex(x["min"]), grid), "bad_ohlc": bad_ohlc, "flat_runs": flat}
        worst = min(worst, comp)
        if comp < COMPLETE:
            issues.append(f"{s} {_pct(comp)} complete (longest gap {per[s]['longest_gap_min']} min)")
        if bad_ohlc:
            issues.append(f"{s}: {bad_ohlc} bars with an impossible price")
        if flat:
            issues.append(f"{s}: price flat for {flat[0][1]} min from {flat[0][0]}")
    if conflicts:
        issues.append(f"{conflicts} minutes where two jobs recorded different closes")
    status = BAD if worst < BAD_BELOW else WARN if issues else OK
    return Check("session bars", status, "; ".join(issues) if issues else f"{len(BAR_SYMBOLS)} symbols, every one {_pct(worst)} or more of {SESSION_MINUTES} minutes, no gaps or faults",
                 True, {"symbols": per, "conflicts": conflicts, "files": len(files)})


def chain_fault_mask(c: pd.DataFrame) -> pd.Series:
    """True for chain rows that must not be used: open interest below zero or beyond 1e12 (decoding corruption), a crossed quote, a spot
    price that is not positive, or a strike that is not a positive number. A consumer should drop these rows (quarantine them)."""
    oi_bad = pd.Series(False, index=c.index)
    for col in ("ce_oi", "pe_oi"):
        if col in c:
            oi_bad |= (c[col] < 0) | (c[col] > OI_ABSURD)
    crossed = pd.Series(False, index=c.index)
    for side in ("ce", "pe"):
        if f"{side}_bid" in c and f"{side}_ask" in c:
            crossed |= (c[f"{side}_bid"] > c[f"{side}_ask"]) & (c[f"{side}_ask"] > 0)
    spot_bad = ~(c["spot"] > 0) if "spot" in c else pd.Series(False, index=c.index)
    strike_bad = ~(c["strike"] > 0) if "strike" in c else pd.Series(False, index=c.index)
    return oi_bad | crossed | spot_bad | strike_bad


def check_chains(store, day: dt.date) -> Check:
    files = _find(store, f"{day}_", "chains-", "_chains.parquet", exclude=("wide-eod",))
    if not files:
        return Check("option chains", MISSING, "no chain files for the day", True)
    c = _frames(store, files)
    c["ts"] = _to_ist(c["ts"])
    c["min"] = c["ts"].dt.floor("min")
    grid = _grid(day, dt.time(15, 30))
    expected = len(grid)
    per, issues, worst = {}, [], 1.0
    for u in CHAIN_UNDERLYINGS:
        x = c[c["underlying"] == u]
        comp = x["min"][x["min"].isin(grid)].nunique() / expected if len(x) else 0.0
        per[u] = {"completeness": round(comp, 4), "rows": int(len(x))}
        worst = min(worst, comp)
        if comp < COMPLETE:
            issues.append(f"{u} {_pct(comp)} of minutes have a snapshot")
    mask = chain_fault_mask(c)
    n_bad = int(mask.sum())
    if n_bad:
        oi = int((((c.get("ce_oi", 0) < 0) | (c.get("pe_oi", 0) < 0) | (c.get("ce_oi", 0) > OI_ABSURD) | (c.get("pe_oi", 0) > OI_ABSURD))).sum())
        keys = c.loc[mask, ["underlying", "expiry", "strike"]].drop_duplicates()
        issues.append(f"{n_bad} rows to quarantine ({oi} with corrupt open interest) on {len(keys)} strikes, e.g. "
                      + ", ".join(f"{r.underlying} {pd.Timestamp(r.expiry):%d%b} {r.strike:g}" for r in keys.head(3).itertuples()))
    dups = int(c.duplicated(["ts", "underlying", "expiry", "strike"]).sum())
    if dups:
        issues.append(f"{dups} duplicated rows")
    fallback = float((c["source"] != "kotak").mean()) if "source" in c else 0.0
    status = BAD if worst < BAD_BELOW else WARN if issues else OK
    return Check("option chains", status, "; ".join(issues) if issues else f"{len(c):,} rows, every index {_pct(worst)} or more of minutes covered, nothing to quarantine",
                 True, {"underlyings": per, "rows": int(len(c)), "quarantine_rows": n_bad, "duplicate_rows": dups, "non_kotak_share": round(fallback, 4)})


def check_tape(store, day: dt.date) -> Check:
    files = _find(store, f"{day}_", "chains-", "_tape.parquet")
    if not files:
        return Check("fetch tape", MISSING, "no tape file for the day")
    t = _frames(store, files)
    if t.empty:
        return Check("fetch tape", MISSING, "the tape file has no fetch attempts")
    ok = float(t["ok"].astype(bool).mean())
    fail = 1 - ok
    errs = t["error"].dropna().astype(str).str.slice(0, 80).value_counts().head(3).to_dict() if "error" in t else {}
    status = BAD if fail > TAPE_BAD else WARN if fail > TAPE_WARN else OK
    return Check("fetch tape", status, f"{len(t):,} attempts, {_pct(ok)} succeeded" + (f"; most common error: {next(iter(errs))}" if errs and fail else ""),
                 False, {"attempts": int(len(t)), "ok_share": round(ok, 4), "errors": errs})


def check_gift(store, day: dt.date) -> Check:
    files = _find(store, f"{day}_", "chains-", "_gift.parquet")
    if not files:
        return Check("GIFT Nifty pre-open", MISSING, "no pre-open prints for the day")
    g = _frames(store, files)
    g["ts"] = _to_ist(g["ts"])
    g = g[g["ts"].dt.date == day].drop_duplicates("ts")
    return Check("GIFT Nifty pre-open", OK if len(g) >= 3 else WARN, f"{len(g)} prints from {g['ts'].min():%H:%M} to {g['ts'].max():%H:%M}" if len(g) else "no prints today",
                 False, {"prints": int(len(g))})


# ---- the minute backfills ------------------------------------------------------------------------------------------------------------
def _manifest(store, day: dt.date, tag_prefix: str, name: str) -> dict | None:
    files = [(t, n) for t in store.tags(tag_prefix) for n in store.assets(t) if n == name]
    return json.loads(store.read(*files[-1])) if files else None


def check_option_minutes(store, day: dt.date) -> Check:
    m = _manifest(store, day, "option-minutes-", f"{day}_manifest.json")
    if m is None:
        return Check("option minutes", MISSING, "no manifest for the day")
    if not m.get("underlyings"):
        return Check("option minutes", BAD, "the manifest lists no underlyings: nothing was backfilled")
    issues, worst, lasts = [], 1.0, []
    for u, d in (m.get("underlyings") or {}).items():
        asked, served = d.get("asked") or 0, d.get("served") or 0
        ratio = served / asked if asked else 0.0
        worst = min(worst, ratio)
        if d.get("failed"):
            issues.append(f"{u}: {d['failed']} contracts failed")
        if ratio < COMPLETE and not d.get("failed"):
            issues.append(f"{u}: {served} of {asked} contracts served")
        if d.get("last"):
            lasts.append(pd.Timestamp(d["last"]))
    if lasts and min(lasts).date() != day:
        issues.append(f"the newest bar is from {min(lasts):%d %b}, not {day:%d %b}")
    status = BAD if worst < BAD_BELOW else WARN if issues else OK
    return Check("option minutes", status, "; ".join(issues[:4]) if issues else f"{len(m.get('underlyings') or {})} underlyings, every contract asked for was served",
                 False, {"worst_served_ratio": round(worst, 4)})


def check_stock_minutes(store, day: dt.date) -> Check:
    m = _manifest(store, day, "stock-minutes-", f"{day}_stocks_manifest.json")
    if m is None:
        return Check("stock minutes", MISSING, "no manifest for the day")
    issues, worst = [], 1.0
    for kind in ("cash", "futures"):
        t = (m.get("totals") or {}).get(kind) or {}
        asked, served = t.get("asked") or 0, t.get("served") or 0
        ratio = served / asked if asked else 0.0
        worst = min(worst, ratio)
        if ratio < COMPLETE:
            issues.append(f"{kind}: {served} of {asked} stocks served ({t.get('failed', 0)} failed, {t.get('not_attempted', 0)} not attempted)")
    if m.get("stopped"):
        issues.append(f"stopped early: {m['stopped']}")
    status = BAD if worst < BAD_BELOW else WARN if issues else OK
    return Check("stock minutes", status, "; ".join(issues) if issues else f"{(m.get('universe') or {}).get('n', '?')} stocks, cash and futures all served",
                 False, {"worst_served_ratio": round(worst, 4)})


def check_stock_option_minutes(store, day: dt.date) -> Check:
    """The stocks' near-the-money option minutes (collect-wide.yml's 15:45 job): per stock, how many of the contracts asked for were served."""
    m = _manifest(store, day, "option-minutes-", f"{day}_stock_manifest.json")
    if m is None:
        return Check("stock option minutes", MISSING, "no stock manifest for the day")
    st = m.get("stocks") or {}
    if not st:
        return Check("stock option minutes", BAD, "the manifest lists no stocks: nothing was collected")
    issues, worst, lasts, asked_all, served_all = [], 1.0, [], 0, 0
    for sym, d in st.items():
        asked, served = d.get("asked") or 0, d.get("served") or 0
        asked_all, served_all = asked_all + asked, served_all + served
        ratio = served / asked if asked else 0.0
        worst = min(worst, ratio)
        if ratio < COMPLETE:
            issues.append(f"{sym}: {served} of {asked} contracts served" + (f" ({d['failed']} failed)" if d.get("failed") else ""))
        if d.get("last"):
            ts = pd.Timestamp(d["last"])
            lasts.append(ts.tz_localize(IST) if ts.tzinfo is None else ts.tz_convert(IST))          # a manifest's times are IST; a missing offset is read as IST, never compared naive
    if lasts and min(lasts).date() != day:
        issues.append(f"the newest bar is from {min(lasts):%d %b}, not {day:%d %b}")
    status = BAD if worst < BAD_BELOW else WARN if issues else OK
    return Check("stock option minutes", status, "; ".join(issues[:4]) if issues else f"{len(st)} stocks, {served_all:,} contracts, every one served",
                 False, {"worst_served_ratio": round(worst, 4), "stocks": len(st)})


def check_evening_minutes(store, day: dt.date) -> Check:
    """MCX and currency minutes collected after their sessions (evening-minutes.yml, 23:45 IST): judged for the latest weekday before `day`'s morning."""
    d = day - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    m = _manifest(store, d, "evening-minutes-", f"{d}_manifest.json")
    if m is None:
        return Check("MCX/currency minutes", MISSING, f"no evening manifest for {d:%a %d %b}")
    issues, worst, got = [], 1.0, 0
    for seg, rep in (m.get("segments") or {}).items():
        if rep.get("error"):
            issues.append(f"{seg}: {rep['error'][:90]}")
            worst = 0.0
            continue
        t = (m.get("totals") or {}).get(seg) or {}
        asked, served = t.get("asked") or 0, t.get("served") or 0
        got += served
        ratio = served / asked if asked else 0.0
        worst = min(worst, ratio)
        if ratio < COMPLETE:
            issues.append(f"{seg}: {served} of {asked} futures served ({t.get('failed', 0)} failed, {t.get('empty', 0)} empty, {t.get('not_attempted', 0)} not attempted)")
    if not m.get("segments"):
        issues.append("the manifest lists no segments")
        worst = 0.0
    if m.get("stopped"):
        issues.append(f"stopped early: {m['stopped']}")
    status = BAD if worst < BAD_BELOW else WARN if issues else OK
    return Check("MCX/currency minutes", status, "; ".join(issues[:4]) if issues else f"{d:%a %d %b}: {got} futures, every one served", False,
                 {"worst_served_ratio": round(worst, 4), "futures": got})


AGREE_WARN, AGREE_BAD = 97.0, 90.0          # percent of fresh Kite+Kotak pairs within a spread of each other


def check_agreement(store, day: dt.date) -> Check:
    """How often the two live sources agreed on `day` (agreement.yml reads the relay's tally after the close): the share of fresh Kite+Kotak pairs within a spread of each other."""
    m = _manifest(store, day, "agreement-", f"{day}_agreement.json")
    if m is None:
        return Check("Kite vs Kotak agreement", MISSING, f"no agreement record for {day:%a %d %b}: the relay's tally (Kotak poller on?) or agreement.yml did not deliver")
    pct, pairs, cycles = m.get("agree_pct"), int(m.get("pairs") or 0), int(m.get("cycles") or 0)
    if pct is None or not pairs:
        return Check("Kite vs Kotak agreement", WARN, f"{cycles:,} cycles but no instrument held a fresh price from both sources (one source is off)", False, {"cycles": cycles})
    issues = []
    if m.get("partial"):
        issues.append(f"only {cycles:,} cycles (a full session is about 4,500)")
    if pct < AGREE_WARN:
        issues.append(f"{pct}% of {pairs:,} pairs agree (options {m.get('opt_agree_pct')}%, worst cycle {m.get('worst_cycle_pct')}% apart)")
    status = BAD if pct < AGREE_BAD else WARN if issues else OK
    return Check("Kite vs Kotak agreement", status, "; ".join(issues) if issues else f"{pct}% of {pairs:,} pairs agree over {cycles:,} cycles (options {m.get('opt_agree_pct')}%)", False,
                 {"agree_pct": pct, "pairs": pairs, "cycles": cycles})


def check_daily_history(store, day: dt.date, tag: str = "daily-history", channel: str = "daily history", workflow: str = "Daily history") -> Check:
    """A history release (daily-history.yml, fx-daily.yml; by hand): that a dataset exists, how old it is, and how many series passed every check."""
    files = [(t, n) for t in store.tags(tag) for n in store.assets(t) if n.endswith("_manifest.json")]
    if not files:
        return Check(channel, MISSING, f"no dataset on the {tag} release: run the {workflow} workflow")
    t, n = sorted(files, key=lambda f: f[1])[-1]
    m = json.loads(store.read(t, n))
    age = (day - dt.date.fromisoformat(str(m.get("as_of") or n[:10])[:10])).days
    bad = m.get("unverified_series") or []
    series = len(m.get("series") or {})
    issues = []
    if age > 45:
        issues.append(f"the newest dataset is {age} days old")
    if bad:
        issues.append(f"{len(bad)} of {series} series are not verified ({', '.join(bad[:6])}{'…' if len(bad) > 6 else ''})")
    gappy = m.get("gappy_series") or []                       # holes in the record: a coverage note, not a failure (the values that exist were checked)
    note = f" ({len(gappy)} with missing days: {', '.join(gappy[:6])}{'…' if len(gappy) > 6 else ''})" if gappy else ""
    return Check(channel, WARN if issues else OK, "; ".join(issues) if issues else f"{series} series, all verified, {age} days old{note}", False,
                 {"series": series, "unverified": len(bad), "age_days": age, "gappy": len(gappy)})


def check_fx_daily(store, day: dt.date) -> Check:
    return check_daily_history(store, day, "fx-daily", "FX daily history", "FX daily history")


def check_fx_minutes(store, day: dt.date) -> Check:
    """The FX 1-minute bars (fx-minutes.yml, 22:30 UTC on weekdays): judged for the latest weekday before `day`'s morning."""
    d = day - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    m = _manifest(store, d, "fx-minutes-", f"{d}_manifest.json")
    if m is None:
        return Check("FX minutes", MISSING, f"no FX manifest for {d:%a %d %b}")
    pairs = m.get("pairs") or {}
    if not pairs:
        return Check("FX minutes", BAD, "the manifest lists no pairs: nothing was collected")
    issues, served = [], 0
    for sym, r in pairs.items():
        if r.get("status") != "served":
            issues.append(f"{sym}: {r.get('status') or 'not served'}")
            continue
        served += 1
        if (r.get("rows") or 0) < 500:
            issues.append(f"{sym}: only {r.get('rows')} bars")
        elif r.get("last") and pd.Timestamp(r["last"]).tz_convert("UTC").date() < d:
            issues.append(f"{sym}: the newest bar is from {pd.Timestamp(r['last']):%d %b}, not {d:%d %b}")
    ratio = served / len(pairs)
    status = BAD if ratio < BAD_BELOW else WARN if issues else OK
    return Check("FX minutes", status, "; ".join(issues[:4]) if issues else f"{d:%a %d %b}: {served} pairs, every one served", False, {"served_ratio": round(ratio, 4), "pairs": len(pairs)})


# ---- the NSE warehouse ----------------------------------------------------------------------------------------------------------------
def prev_trading_day(cal: MK.Calendars, day: dt.date, include: bool = False) -> dt.date:
    d = day if include else day - dt.timedelta(days=1)
    while MK.session("nse_fo", d, cal) is None:
        d -= dt.timedelta(days=1)
    return d


def trading_days_between(cal: MK.Calendars, a: dt.date, b: dt.date) -> int:
    """Trading days after `a` up to and including `b`."""
    n, d = 0, a
    while d < b:
        d += dt.timedelta(days=1)
        n += MK.session("nse_fo", d, cal) is not None
    return n


def check_warehouse(store, day: dt.date, cal: MK.Calendars, now: dt.datetime) -> Check:
    try:
        m = pd.read_parquet(io.BytesIO(store.read("warehouse", f"manifest_{day.year}.parquet")))
    except (KeyError, FileNotFoundError):
        return Check("NSE warehouse", MISSING, f"no manifest for {day.year}", True)
    m["date"] = pd.to_datetime(m["date"]).dt.date
    due = dt.datetime.combine(day, DUE["warehouse"], tzinfo=IST)
    expected = day if now >= due else prev_trading_day(cal, day)
    issues, per, worst = [], {}, 0
    for t in CORE_WAREHOUSE_TABLES:
        ok = m[(m["table"] == t) & (m["status"] == "ok")]
        if ok.empty:
            per[t] = {"last_ok": None}
            issues.append(f"{t}: nothing fetched")
            worst = max(worst, 3)
            continue
        last = ok["date"].max()
        lag = trading_days_between(cal, last, expected) if last < expected else 0
        recent = ok[ok["date"] <= last].tail(21)
        rows, med = int(recent["rows"].iloc[-1]), float(recent["rows"].iloc[:-1].median()) if len(recent) > 1 else 0.0
        per[t] = {"last_ok": str(last), "lag_trading_days": lag, "rows": rows, "median_rows": med}
        if lag >= 2:
            issues.append(f"{t}: newest {last:%d %b}, {lag} trading days behind")
            worst = max(worst, 3)
        elif lag == 1:
            issues.append(f"{t}: newest {last:%d %b}, one trading day behind")
            worst = max(worst, 2)
        if med and rows < 0.5 * med:
            issues.append(f"{t}: the newest file has {rows:,} rows against a usual {med:,.0f}")
            worst = max(worst, 2)
    status = BAD if worst >= 3 else WARN if issues else OK
    return Check("NSE warehouse", status, "; ".join(issues[:4]) if issues else f"all {len(CORE_WAREHOUSE_TABLES)} daily tables current to {expected:%d %b}",
                 True, {"expected_through": str(expected), "tables": per})


# ---- the brief and Kite ---------------------------------------------------------------------------------------------------------------
def check_premarket(store, day: dt.date, today: dt.date | None = None) -> Check:
    raw = store.branch_file("premarket", "brief.json")
    if raw is None:
        return Check("pre-market brief", MISSING, "the premarket branch or its brief.json does not exist")
    try:
        b = json.loads(raw)
    except ValueError:
        return Check("pre-market brief", BAD, "brief.json is not valid JSON")
    got = str(b.get("session"))[:10]
    if got > str(day) and (today or day) > day:
        return Check("pre-market brief", PENDING, f"a newer brief ({got}) replaced it; a past day's brief is not kept, so not judged")
    if got != str(day):
        return Check("pre-market brief", MISSING, f"the newest brief is for {got}, not {day}")
    return Check("pre-market brief", OK, f"built {str(b.get('generated_at', ''))[11:16]} IST for {got}", False, {"generated_at": b.get("generated_at")})


def check_kite(store, day: dt.date, today: dt.date | None = None) -> Check:
    arts = store.kite_artifacts(day)
    if arts is None:
        return Check("Kite ticks", PENDING, "could not read the Actions API; not judged")
    real = [a for a in arts if a["name"].startswith("kite-raw") and a["size"] > 1000 and not a["expired"]]
    if not real and today is not None and (today - day).days > KITE_LOOKBACK_DAYS:
        return Check("Kite ticks", PENDING, f"older than the {KITE_LOOKBACK_DAYS} days of recorder runs that are listed; not judged")
    if not real:
        return Check("Kite ticks", MISSING, "no tick artifact: the recorder had no token for the day, or started after the close")
    return Check("Kite ticks", OK, f"{len(real)} encrypted tick artifact(s), {sum(a['size'] for a in real) / 1e6:.1f} MB (content is encrypted: arrival is all that can be checked)",
                 False, {"artifacts": len(real)})


# ---- the report ---------------------------------------------------------------------------------------------------------------------------
def _due(day: dt.date, key: str, now: dt.datetime) -> bool:
    return now >= dt.datetime.combine(day, DUE[key], tzinfo=IST)


def build_report(store, cfg, day: dt.date, now: dt.datetime | None = None) -> Report:
    now = (now or dt.datetime.now(IST)).astimezone(IST)
    cal = MK.Calendars(cfg)
    gen = now.isoformat(timespec="seconds")
    if MK.session("nse_fo", day, cal) is None:
        return Report(str(day), gen, [Check("market", OK, f"{day:%a %d %b} is not an NSE trading day: nothing is due")])
    plan = [("gift", lambda: check_gift(store, day), "GIFT Nifty pre-open", False), ("premarket", lambda: check_premarket(store, day, now.date()), "pre-market brief", False),
            ("session", lambda: check_bars(store, day), "session bars", True), ("session", lambda: check_chains(store, day), "option chains", True),
            ("session", lambda: check_tape(store, day), "fetch tape", False), ("minutes", lambda: check_option_minutes(store, day), "option minutes", False),
            ("minutes", lambda: check_stock_minutes(store, day), "stock minutes", False), ("minutes", lambda: check_stock_option_minutes(store, day), "stock option minutes", False),
            ("evening", lambda: check_evening_minutes(store, day), "MCX/currency minutes", False), ("history", lambda: check_daily_history(store, day), "daily history", False),
            ("history", lambda: check_fx_daily(store, day), "FX daily history", False), ("evening", lambda: check_fx_minutes(store, day), "FX minutes", False),
            ("kite", lambda: check_kite(store, day, now.date()), "Kite ticks", False),
            ("session", lambda: check_agreement(store, day), "Kite vs Kotak agreement", False),
            ("warehouse", lambda: check_warehouse(store, day, cal, now), "NSE warehouse", True)]
    checks = []
    for key, fn, name, critical in plan:
        if key != "warehouse" and not _due(day, key, now):
            checks.append(Check(name, PENDING, f"due after {DUE[key]:%H:%M} IST", critical))
            continue
        try:
            c = fn()
        except Exception as e:                                                         # noqa: BLE001 - a check that cannot run is reported, never skipped
            c = Check(name, BAD if critical else WARN, f"the check could not run ({type(e).__name__}: {str(e)[:100]})", critical)
        c.critical = critical
        checks.append(c)
    return Report(str(day), gen, checks)
