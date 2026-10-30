"""P0.6: the independent check of an imported index-minute dataset, under the rules fixed in docs/ml/P0_6_criteria.md (version 1).

The criteria file is hashed and pinned (`intake.VERIFICATION_CRITERIA`): this code refuses to run against a criteria file that is not the one committed
before any result. The check is run **once**: a run that produced comparisons writes `verification.json` (pass or fail) and never overwrites it; a run
that could not fetch a reference completely is *void*: it writes `void_run_<time>.json` with the reason and nothing else, and the check may be run again
under the same rules. A void is only ever an exception or an HTTP error raised by this code, never a judgment.

Passing writes the record only. Flipping the manifest's status to `external_verified` is a separate, status-only step (`flip_status`) that copies `passed`
from the existing record and re-compares nothing; the loader then accepts the dataset for the symbols the record lists (`symbols_verified`) and no others.
Reference rows (Yahoo, NSE) are never written into the record: it keeps the aggregates, the failing days with their relative differences, and the sha256
of every reference file.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from . import intake

CHECK = "p06-v1"
CRITERIA_PATH = Path(__file__).resolve().parents[2] / "docs" / "ml" / "P0_6_criteria.md"
DATASET_DIGEST = "47d28d6376ca63af6f435c7a7fab16dc403cc99a7c49ab954ded2c68ed98e9b8"          # the manifest digest docs/ml/P0_6_criteria.md names: any other dataset is refused
AERON_DATASET = "aeron7-2-906fc2378b"                                                      # the verified reference the criteria name for C
AERON_MANIFEST_SHA256 = "d149dc2937d9859b7d6cdb7ab26593ff3fabbb26612d926f2140b47bc60b3708"   # its manifest file, as imported and verified
SYMBOLS = ("NIFTY", "BANKNIFTY")                                    # INDIAVIX is not covered by any claim
YAHOO = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}
NSE_ROW = {"NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank"}
NSE_URL = "https://archives.nseindia.com/content/indices/ind_close_all_{ddmmyyyy}.csv"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
NEW_START, WINDOW_END = dt.date(2023, 3, 1), dt.date(2026, 5, 15)
TOL_A = {"high": 0.002, "low": 0.002, "close": 0.003}               # the tolerances of external_aeron.TOLERANCE
TOL_C = 0.001                                                       # two minute vendors: a few basis points
GROSS = 0.015
MIN_SESSIONS, PASS_RATE, UNCOMPARED_MAX, ACCEPTED_FLOOR = 500, 0.95, 0.01, 0.97
MONTH_FLOOR, MONTH_MIN, MAX_RUN = 0.80, 10, 5
C_COVERAGE, CORR_SESSION, CORR_SHARE, CORR_MEDIAN, MIN_COMMON_MINUTES = 0.95, 0.95, 0.90, 0.98, 30
MAX_404_SHARE = 0.10
PRIOR_EXPOSURE = ("On 2026-10-25, before the counted run, the engineer rehearsed this code on a copy of the real Kaggle dataset with SYNTHETIC Yahoo and NSE references built from the dataset's "
                  "own bars (code identical to commit a76684bf of ml-p06-verify2). Check C compares two local datasets, so it necessarily ran against the real aeron7 data (manifest sha256 "
                  "d149dc29…): NIFTY C passed (worst month 2015-08 at 81%, close to the 80% floor), BANKNIFTY C failed only the month rule (2020-03: 15 of 19 compared sessions agree, 16 "
                  "would pass). THIS RECORD IS THEREFORE EXPECTED TO BE passed:false WITH NO SYMBOL LICENSED, whatever A and B show. The internal auditor reproduced the C numbers "
                  "independently on 2026-10-25 and fetched a few NSE files and a Yahoo window only to check formats, NaN rows and duplicates (none found), with no A/B comparison. No rule, "
                  "threshold or verifier logic was changed because of any of this, and the rehearsal's files were deleted. The counted run is not blind for C; A and B had not been seen "
                  "against any real reference. Any later criteria v2 is post hoc.")
SCOPE = {"new_window": "2023-03-01 to 2026-05-15: the DAILY ENVELOPE only (high, low, close against Yahoo; close against NSE's official file). Nothing independent checks minute timestamps "
                       "or the intraday path in this window. B is nearly the same quantity as A's close (Yahoo's index data derive from NSE's), so it is not a second vendor.",
         "overlap": "sessions also in the verified aeron7 data (to Feb 2023): daily envelope to 0.1% and 1-minute return correlation. This is consistency with aeron7, not independent accuracy: "
                    "the two vendors may share an upstream feed.",
         "not_covered": "Kaggle-only sessions before 2023-03-01 that aeron7 lacks, and the gap between aeron7's last day and 2023-03-01, are counted (`only_here_not_gating`) but not checked by anything; "
                        "15 May to early Sep 2026 does not exist in the dataset. A pass allows up to 5% of compared sessions to disagree on the daily envelope. The label `external_verified` "
                        "means this scope and nothing more, and it covers NIFTY and BANKNIFTY only (not INDIAVIX, and not option, bid/ask, IV or execution data).",
         "review_and_rejected": "listed, not run through A and B: the loaded partitions do not hold those sessions' minutes (the criteria's information-only runs on them are not possible from the import)"}


class VoidRun(RuntimeError):
    """The run could not fetch or read a reference completely: it is void, nothing is concluded, and the check may be run again."""


class CriteriaChanged(RuntimeError):
    pass


class AlreadyChecked(RuntimeError):
    pass


def criteria_sha256() -> str:
    return hashlib.sha256(CRITERIA_PATH.read_bytes()).hexdigest()


def pinned_criteria_sha256() -> str:
    return intake.VERIFICATION_CRITERIA[CHECK]


# ---- the daily bar from minutes -------------------------------------------------------------------------------------------------------
def daily(m1: pd.DataFrame) -> pd.DataFrame:
    """High, low and last close of each session, and the mean of the 15:00 to 15:29 minute closes (NSE's close is computed from the last 30 minutes)."""
    m1 = m1.sort_values("ts")
    g = m1.groupby(m1["ts"].dt.date)
    last30 = m1[(m1["ts"].dt.hour == 15) & (m1["ts"].dt.minute < 30)]
    base = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})
    base["close30"] = last30.groupby(last30["ts"].dt.date)["close"].mean()
    return base


def _bad(x, lim) -> bool:
    return not (abs(x) <= lim)                                      # NaN is bad


def _rel(a, b) -> float:
    return (float(a) / float(b) - 1) if b else float("nan")


def compare(ours: pd.DataFrame, ref: pd.DataFrame, days, kind: str) -> pd.DataFrame:
    """One row per day: not compared if either side lacks it; else the relative differences and whether the day agrees / is a gross error.
    kind 'A': Yahoo high, low, and the close under either definition; 'B': the NSE close only; 'C': aeron7 high, low, close, each to 0.1%."""
    rows = []
    for d in days:
        if d not in ours.index or d not in ref.index:
            rows.append({"day": d, "compared": False, "pass": False, "gross": False})
            continue
        r = {"day": d, "compared": True}
        if kind == "B":
            r["close_rel"], r["close30_rel"] = _rel(ours.at[d, "close"], ref.at[d, "close"]), _rel(ours.at[d, "close30"], ref.at[d, "close"])
            ok = (abs(r["close_rel"]) <= TOL_A["close"]) or (abs(r["close30_rel"]) <= TOL_A["close"])
            gross = _bad(r["close_rel"], GROSS) and _bad(r["close30_rel"], GROSS)
        else:
            r["high_rel"], r["low_rel"] = _rel(ours.at[d, "high"], ref.at[d, "high"]), _rel(ours.at[d, "low"], ref.at[d, "low"])
            r["close_rel"] = _rel(ours.at[d, "close"], ref.at[d, "close"])
            if kind == "A":
                r["close30_rel"] = _rel(ours.at[d, "close30"], ref.at[d, "close"])
                close_ok = (abs(r["close_rel"]) <= TOL_A["close"]) or (abs(r["close30_rel"]) <= TOL_A["close"])
                ok = abs(r["high_rel"]) <= TOL_A["high"] and abs(r["low_rel"]) <= TOL_A["low"] and close_ok
                gross = _bad(r["high_rel"], GROSS) or _bad(r["low_rel"], GROSS) or (_bad(r["close_rel"], GROSS) and _bad(r["close30_rel"], GROSS))
            else:
                ok = all(abs(r[k]) <= TOL_C for k in ("high_rel", "low_rel", "close_rel"))
                gross = any(_bad(r[k], GROSS) for k in ("high_rel", "low_rel", "close_rel"))
        r["pass"], r["gross"] = bool(ok), bool(gross)
        rows.append(r)
    return pd.DataFrame(rows)


def longest_failing_run(passes: list[bool]) -> int:
    best = run = 0
    for ok in passes:
        run = 0 if ok else run + 1
        best = max(best, run)
    return best


def judge(t: pd.DataFrame, asked: int) -> tuple[dict, list[str]]:
    """The pass rate, gross errors, calendar-month rule and failing-run rule of A and C over the compared days (an uncompared day neither breaks nor extends a run)."""
    c = t[t["compared"]].sort_values("day") if len(t) else t
    reasons: list[str] = []
    s = {"asked": int(asked), "compared": int(len(c)), "pass_rate": float(c["pass"].mean()) if len(c) else 0.0,
         "failing_run": longest_failing_run(list(c["pass"])) if len(c) else 0,
         "gross_errors": [str(d) for d in c.loc[c["gross"], "day"]][:40] if len(c) else [], "n_gross": int(c["gross"].sum()) if len(c) else 0}
    months = (c.assign(m=[d.strftime("%Y-%m") for d in c["day"]]).groupby("m")["pass"].agg(["mean", "size"]) if len(c)
              else pd.DataFrame(columns=["mean", "size"]))
    judged = months[months["size"] >= MONTH_MIN]
    s["months_reported_not_judged"] = [str(m) for m in months[months["size"] < MONTH_MIN].index]
    s["worst_month"] = (str(judged["mean"].idxmin()), float(judged["mean"].min())) if len(judged) else None
    s["failures"] = ([{"day": str(r["day"]), **{k: round(float(r[k]), 6) for k in r.index if str(k).endswith("_rel")}} for _, r in c[~c["pass"]].head(40).iterrows()]
                     if len(c) else [])
    if s["pass_rate"] < PASS_RATE:
        reasons.append(f"{s['pass_rate']:.1%} of compared sessions agree, at least {PASS_RATE:.0%} needed")
    if s["n_gross"]:
        reasons.append(f"{s['n_gross']} gross error(s) (more than {GROSS:.1%} off), e.g. {', '.join(s['gross_errors'][:3])}")
    if s["worst_month"] and s["worst_month"][1] < MONTH_FLOOR:
        reasons.append(f"month {s['worst_month'][0]} has {s['worst_month'][1]:.0%} agreeing, at least {MONTH_FLOOR:.0%} needed")
    if s["failing_run"] > MAX_RUN:
        reasons.append(f"{s['failing_run']} consecutive failing sessions, at most {MAX_RUN} allowed")
    return s, reasons


def coverage(accepted: list, ref_days: set, nse_days: set, label: str) -> tuple[dict, list[str]]:
    """The coverage rules of A and B: no phantom session, at most 1% of accepted sessions uncompared, at least 500 and 95% compared, and accepted
    sessions at least 97% of the days NSE published an index file for."""
    accepted = sorted(accepted)
    phantom = [d for d in accepted if d not in nse_days]
    uncompared = [d for d in accepted if d not in ref_days]
    compared = len(accepted) - len(uncompared)
    s = {"accepted": len(accepted), "phantom": [str(d) for d in phantom][:40], "n_phantom": len(phantom), "uncompared": [str(d) for d in uncompared][:100],
         "n_uncompared": len(uncompared), "nse_days": len(nse_days),
         "accepted_share_of_nse_days": (len(accepted) / len(nse_days)) if nse_days else 0.0}
    reasons: list[str] = []
    if phantom:
        reasons.append(f"{label}: {len(phantom)} accepted session(s) on a day with no NSE index file (phantom), e.g. {phantom[0]}")
    if accepted and len(uncompared) / len(accepted) > UNCOMPARED_MAX:
        reasons.append(f"{label}: {len(uncompared)} of {len(accepted)} accepted sessions have no reference row, at most {UNCOMPARED_MAX:.0%} allowed")
    if compared < MIN_SESSIONS or (accepted and compared / len(accepted) < PASS_RATE):
        reasons.append(f"{label}: only {compared} of {len(accepted)} accepted sessions compared, at least {MIN_SESSIONS} and {PASS_RATE:.0%} needed")
    if s["accepted_share_of_nse_days"] < ACCEPTED_FLOOR:
        reasons.append(f"{label}: accepted sessions are {s['accepted_share_of_nse_days']:.1%} of NSE's index days, at least {ACCEPTED_FLOOR:.0%} needed")
    return s, reasons


def check_a(ours: pd.DataFrame, yahoo: pd.DataFrame, accepted: list, nse_days: set) -> dict:
    cov, r1 = coverage(accepted, set(yahoo.index), nse_days, "A")
    s, r2 = judge(compare(ours, yahoo, accepted, "A"), len(accepted))
    reasons = r1 + ["A: " + x for x in r2]
    return {**s, "coverage": cov, "passed": not reasons, "reasons": reasons}


def check_b(ours: pd.DataFrame, nse: pd.DataFrame, accepted: list, nse_days: set) -> dict:
    cov, r1 = coverage(accepted, set(nse.index), nse_days, "B")
    t = compare(ours, nse, accepted, "B")
    c = t[t["compared"]] if len(t) else t
    reasons = list(r1)
    rate = float(c["pass"].mean()) if len(c) else 0.0
    n_gross = int(c["gross"].sum()) if len(c) else 0
    if rate < PASS_RATE:
        reasons.append(f"B: {rate:.1%} of compared closes agree, at least {PASS_RATE:.0%} needed")
    if n_gross:
        reasons.append(f"B: {n_gross} gross error(s) (more than {GROSS:.1%} off)")
    fails = ([{"day": str(r["day"]), "close_rel": round(float(r["close_rel"]), 6), "close30_rel": round(float(r["close30_rel"]), 6)}
              for _, r in c[~c["pass"]].head(40).iterrows()] if len(c) else [])
    return {"asked": len(accepted), "compared": int(len(c)), "pass_rate": rate, "n_gross": n_gross, "coverage": cov, "failures": fails,
            "passed": not reasons, "reasons": reasons}


# ---- C: the overlap with the verified aeron7 minutes --------------------------------------------------------------------------------------
def minute_corr(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    """Per session, the correlation of 1-minute log returns of the close, taken only between consecutive minutes present in both series (NaN if
    fewer than MIN_COMMON_MINUTES such returns, or if either series is flat)."""
    m = a[["ts", "close"]].merge(b[["ts", "close"]], on="ts", suffixes=("_a", "_b")).sort_values("ts")
    out = {}
    for d, g in m.groupby(m["ts"].dt.date):
        ts = g["ts"].to_numpy()
        adjacent = (ts[1:] - ts[:-1]) == np.timedelta64(1, "m")
        ra, rb = np.diff(np.log(g["close_a"].to_numpy()))[adjacent], np.diff(np.log(g["close_b"].to_numpy()))[adjacent]
        out[d] = float(np.corrcoef(ra, rb)[0, 1]) if len(ra) >= MIN_COMMON_MINUTES and ra.std() > 0 and rb.std() > 0 else float("nan")
    return out


def corr_verdict(vals) -> tuple[float, float, list[str]]:
    """The 1-minute-return correlation rule of C: at least CORR_SHARE of common sessions at CORR_SESSION or better, and the median at CORR_MEDIAN or better; an undefined
    correlation (NaN) counts as a failure in both."""
    vals = np.asarray(vals, float)
    filled = np.nan_to_num(vals, nan=-1.0)
    share = float((filled >= CORR_SESSION).mean()) if len(vals) else 0.0
    med = float(np.median(filled)) if len(vals) else float("nan")
    reasons = []
    if share < CORR_SHARE:
        reasons.append(f"C: {share:.1%} of common sessions have minute-return correlation >= {CORR_SESSION}, at least {CORR_SHARE:.0%} needed")
    if not (med >= CORR_MEDIAN):
        reasons.append(f"C: median minute-return correlation {med:.4f}, at least {CORR_MEDIAN} needed")
    return share, med, reasons


def check_c(ours_m1: pd.DataFrame, ref_m1: pd.DataFrame) -> dict:
    od, rd = daily(ours_m1), daily(ref_m1)
    ours_days, ref_days = set(od.index), set(rd.index)
    common = sorted(ours_days & ref_days)
    in_overlap = {d for d in ref_days if d >= min(ours_days)} if ours_days else set()
    cov_share = (len(in_overlap & ours_days) / len(in_overlap)) if in_overlap else 0.0
    s, reasons = judge(compare(od, rd, common, "C"), len(common))
    reasons = ["C: " + x for x in reasons]
    if len(common) < MIN_SESSIONS:
        reasons.append(f"C: only {len(common)} sessions in common, at least {MIN_SESSIONS} needed")
    if cov_share < C_COVERAGE:
        reasons.append(f"C: {cov_share:.1%} of aeron7's accepted sessions in the overlap are also accepted here, at least {C_COVERAGE:.0%} needed")
    corr = minute_corr(ours_m1, ref_m1)
    vals = np.array([corr.get(d, float("nan")) for d in common])
    share, med, r3 = corr_verdict(vals)
    reasons += r3
    return {**s, "common_sessions": len(common), "coverage_of_aeron7": cov_share, "only_here_not_gating": len(ours_days - ref_days),
            "corr_share_ok": share, "corr_median": med, "corr_undefined": int(np.isnan(vals).sum()), "passed": not reasons, "reasons": reasons}


def check_d(man: dict, loaded: dict[str, pd.DataFrame]) -> dict:
    """Integrity only, not evidence: the loader enforces it already; it is listed so a failure is on the record."""
    reasons = []
    if intake.dataset_digest(man) != man.get("digest"):
        reasons.append("D: the manifest does not hash to its own digest")
    for sym, m1 in loaded.items():
        want = {s["day"] for s in man["sessions"] if s["symbol"] == sym and s["status"] in ("accepted", "accepted_reviewed")}
        have = {str(d) for d in m1["ts"].dt.date.unique()}
        if want != have:
            reasons.append(f"D: {sym}: {len(want ^ have)} sessions differ between the manifest's accepted list and the loaded minutes")
    return {"passed": not reasons, "reasons": reasons}


def info_only(man: dict) -> dict:
    """Never gating: the sessions the importer sent to review or rejected, and the ones a reviewer admitted (whose evidence may have cited Yahoo or NSE)."""
    out = {}
    for sym in SYMBOLS:
        ss = [s for s in man["sessions"] if s["symbol"] == sym]
        out[sym] = {k: {"n": len(v), "days": v[:60]} for k, v in
                    ((k, sorted(s["day"] for s in ss if s["status"] == k)) for k in ("review", "rejected", "accepted_reviewed"))}
    return out


# ---- the NSE archive files --------------------------------------------------------------------------------------------------------------------
def http_fetch(url: str, timeout: int = 30) -> bytes | None:
    """The file's bytes, None for HTTP 404 (NSE published no index file that day); anything else (another status, a timeout) raises."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def parse_nse(raw: bytes, day: dt.date) -> dict[str, float]:
    """{symbol: closing value} from one archive file. The file's Index Date must equal `day` and both rows must be there, or the run is void."""
    try:
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        out = {}
        for sym, name in NSE_ROW.items():
            hit = [r for r in rows if (r.get("Index Name") or "").strip().lower() == name.lower()]
            if len(hit) != 1:
                raise VoidRun(f"NSE file for {day}: {len(hit)} rows named {name}")
            d = dt.datetime.strptime(hit[0]["Index Date"].strip(), "%d-%m-%Y").date()
            if d != day:
                raise VoidRun(f"NSE file for {day} says Index Date {d}")
            v = float(hit[0]["Closing Index Value"])
            if not np.isfinite(v) or v <= 0:
                raise VoidRun(f"NSE file for {day}: {name} close {v}")
            out[sym] = v
        return out
    except VoidRun:
        raise
    except (KeyError, ValueError, UnicodeDecodeError, csv.Error, AttributeError) as exc:
        raise VoidRun(f"NSE file for {day} could not be read: {exc!s:.120}") from exc


def fetch_nse(days: list, cache: Path, fetch=http_fetch, say=print) -> tuple[dict, dict, list]:
    """Fetch (or read from `cache`) the index file of each day. Returns ({symbol: DataFrame(close) by day}, {file name: sha256}, days with no file). More than
    10% of the weekdays answering 404 voids the run: the archive layout has changed, not NSE's calendar."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    closes: dict[str, dict] = {s: {} for s in SYMBOLS}
    files, none = {}, []
    for d in days:
        name = f"ind_close_all_{d:%d%m%Y}.csv"
        p = cache / name
        raw = p.read_bytes() if p.exists() else None
        fetched = raw is None
        if fetched:
            try:
                raw = fetch(NSE_URL.format(ddmmyyyy=f"{d:%d%m%Y}"))
            except Exception as exc:                                # any failure to fetch is a void run, not a verdict
                raise VoidRun(f"NSE file for {d} could not be fetched: {exc!s:.120}") from exc
            if raw is None:
                none.append(d)
                continue
        try:
            parsed = parse_nse(raw, d)
        except VoidRun:
            if not fetched:
                p.unlink(missing_ok=True)                           # a bad file already in the cache must not void every rerun: the next run fetches it afresh
            raise
        if fetched:
            p.write_bytes(raw)                                      # only a file that parsed is kept
        files[name] = hashlib.sha256(raw).hexdigest()
        for sym, v in parsed.items():
            closes[sym][d] = v
    weekdays = [d for d in days if d.weekday() < 5]
    n404 = sum(1 for d in none if d.weekday() < 5)
    if weekdays and n404 / len(weekdays) > MAX_404_SHARE:
        raise VoidRun(f"{n404} of {len(weekdays)} weekdays have no NSE file: the archive layout changed")
    say(f"  NSE: {len(files)} files, {len(none)} days with none")
    return {s: pd.DataFrame({"close": pd.Series(v, dtype=float)}) for s, v in closes.items()}, files, none


def yahoo_daily(symbol: str, start, end) -> pd.DataFrame:
    """Yahoo Finance daily high, low, close, not adjusted, for [start, end]."""
    import yfinance as yf
    d = yf.download(YAHOO[symbol], start=str(pd.Timestamp(start).date()), end=str((pd.Timestamp(end) + pd.Timedelta(days=1)).date()), interval="1d",
                    progress=False, auto_adjust=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d = d.rename(columns=lambda c: str(c).lower())
    if not (len(d) and {"high", "low", "close"} <= set(d.columns)):
        raise VoidRun(f"Yahoo returned no usable daily bars for {symbol}")
    d.index = pd.to_datetime(d.index).date
    return d[["high", "low", "close"]]


def clean_yahoo(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """A Yahoo row with a missing or non-positive number is a session with no reference row (not compared). Two rows for one date are ambiguous: the run is void."""
    if df.index.has_duplicates:
        raise VoidRun(f"Yahoo returned two rows for one date for {symbol}")
    bad = df[["high", "low", "close"]].isna().any(axis=1) | (df[["high", "low", "close"]] <= 0).any(axis=1)
    return df[~bad]


def _sha_csv(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.round(6).to_csv().encode()).hexdigest()


def reference_files(nse: dict, files: dict, cache: Path) -> dict:
    """The `date,symbol,close` CSV built from the NSE files and a manifest of the files, both saved beside the cache, with their sha256."""
    rows = sorted((str(d), sym, float(v)) for sym, df in nse.items() for d, v in df["close"].items())
    csv_text = "date,symbol,close\n" + "".join(f"{d},{sym},{v!r}\n" for d, sym, v in rows)
    man_text = json.dumps({"files": files, "source": NSE_URL}, sort_keys=True, indent=1)
    (Path(cache) / "nse_closes.csv").write_text(csv_text)
    (Path(cache) / "nse_files_manifest.json").write_text(man_text)
    return {"closes_csv_sha256": hashlib.sha256(csv_text.encode()).hexdigest(), "files_manifest_sha256": hashlib.sha256(man_text.encode()).hexdigest()}


def _yf_version() -> str:
    try:
        from importlib.metadata import version
        return version("yfinance")
    except Exception:
        return "unknown"


def check_pins(man: dict, ref_man: dict, aeron_ds: Path) -> None:
    """The run is about one named dataset and one named reference. Anything else is refused before a single fetch."""
    if man.get("digest") != DATASET_DIGEST:
        raise ValueError(f"{man.get('dataset')}: its digest is not the one docs/ml/P0_6_criteria.md names ({DATASET_DIGEST[:12]}…): refused")
    if ref_man.get("dataset") != AERON_DATASET:
        raise ValueError(f"the C reference must be {AERON_DATASET}, not {ref_man.get('dataset')}")
    if hashlib.sha256((Path(aeron_ds) / "manifest.json").read_bytes()).hexdigest() != AERON_MANIFEST_SHA256:
        raise ValueError(f"{AERON_DATASET}: its manifest is not the one that was verified and named in the criteria: refused")
    verify_aeron_partitions(aeron_ds, ref_man)


def verify_aeron_partitions(aeron_ds: Path, ref_man: dict) -> None:
    """The manifest's word is not enough: every 1-minute partition of the two symbols is re-hashed from its file."""
    from ..data import external_aeron as ea
    parts = {k: v for k, v in (ref_man.get("partitions") or {}).items() if k.startswith(tuple(f"1m/symbol={s}/" for s in SYMBOLS))}
    for s in SYMBOLS:
        if not any(k.startswith(f"1m/symbol={s}/") for k in parts):
            raise ValueError(f"the aeron7 manifest lists no 1-minute partitions for {s}")
    for k, want in sorted(parts.items()):
        if ea.frame_hash(pd.read_parquet(Path(aeron_ds) / k)) != want:
            raise ValueError(f"aeron7 partition {k} no longer hashes to its manifest: refused")


def _write_once(path: Path, obj) -> None:
    """Exclusive create: a second writer (a concurrent run, a copied folder racing) fails instead of replacing the first record."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str, sort_keys=True))
    try:
        try:
            os.link(tmp, path)                                      # fails if `path` exists
        except FileExistsError as exc:
            raise AlreadyChecked(f"{path} appeared while this run was computing: this check is run once") from exc
        except OSError:                                             # a filesystem without hard links: exclusive create still refuses an existing file
            try:
                with open(path, "x") as fh:
                    fh.write(tmp.read_text())
            except FileExistsError as exc:
                raise AlreadyChecked(f"{path} appeared while this run was computing: this check is run once") from exc
    finally:
        tmp.unlink(missing_ok=True)


# ---- the run ----------------------------------------------------------------------------------------------------------------------------------
def window_days(accepted: dict[str, list]) -> list:
    """Every weekday of the window, and every accepted session on a weekend (a Budget or Muhurat special session)."""
    days = {d.date() for d in pd.bdate_range(NEW_START, WINDOW_END)}
    for v in accepted.values():
        days |= set(v)
    return sorted(days)


def run(ds: Path, aeron_ds: Path, cache: Path, yahoo=yahoo_daily, fetch=http_fetch, say=print) -> dict:
    """The one run. Returns the record; raises `VoidRun` after writing `void_run_<time>.json` if a reference could not be fetched or read."""
    if criteria_sha256() != pinned_criteria_sha256():
        raise CriteriaChanged("docs/ml/P0_6_criteria.md is not the file committed before any result (intake.VERIFICATION_CRITERIA): refused")
    from ..data import external_aeron as ea
    ds, aeron_ds = Path(ds), Path(aeron_ds)
    vp = ds / "verification.json"
    if vp.exists() or (ds / f"verification_{CHECK}.json").exists():
        raise AlreadyChecked(f"{vp} exists: this check is run once; a changed rule is a new criteria file, written after a failed v1")
    man = json.loads((ds / "manifest.json").read_text())
    ref_man = json.loads((aeron_ds / "manifest.json").read_text())
    if ref_man.get("status") != ea.VERIFIED:
        raise ValueError("the aeron7 dataset used for check C must itself be external_verified")
    check_pins(man, ref_man, aeron_ds)
    try:
        rec = _run(ds, aeron_ds, man, ref_man, cache, yahoo, fetch, say, ea)
    except Exception as exc:                                        # any exception the code raises is a void run: logged with its reason, nothing else written, the check may be run again
        stamp = pd.Timestamp.now(tz=intake.IST).strftime("%Y%m%dT%H%M%S%f")                  # to the microsecond, and written exclusively: a void log never replaces another
        _write_once(ds / f"void_run_{stamp}.json", {"check": CHECK, "dataset": man["dataset"], "digest": man["digest"],
                                                   "void": f"{type(exc).__name__}: {exc!s:.300}", "at": stamp})
        raise exc if isinstance(exc, VoidRun) else VoidRun(f"{type(exc).__name__}: {exc!s:.200}") from exc
    _write_once(vp, rec)
    for sym in SYMBOLS:                                             # shown only once the record exists: a verdict is never seen before it is final
        for k, v in rec["symbols"][sym].items():
            say(f"  {sym} {k}: " + ("pass" if v["passed"] else "FAIL " + "; ".join(v["reasons"])))
    return rec


def _run(ds, aeron_ds, man, ref_man, cache, yahoo, fetch, say, ea) -> dict:
    loaded, accepted = {}, {}
    for sym in SYMBOLS:
        m1 = intake.load(ds, [sym], use="development_folds", allow_unverified=True, expected_digest=DATASET_DIGEST)
        loaded[sym] = m1
        accepted[sym] = sorted(d for d in m1["ts"].dt.date.unique() if NEW_START <= d <= WINDOW_END)
    wdays = window_days(accepted)
    nse, files, no_file = fetch_nse(wdays, cache, fetch, say)
    nse_days = set(wdays) - set(no_file)
    ref_hashes = reference_files(nse, files, Path(cache))
    rec = {"check": CHECK, "criteria_sha256": pinned_criteria_sha256(), "dataset": man["dataset"], "digest": man["digest"], "code": intake.code_commit(),
           "scope": SCOPE, "prior_exposure": PRIOR_EXPOSURE, "references": {"yahoo": f"Yahoo Finance daily OHLC (^NSEI, ^NSEBANK), yfinance {_yf_version()}, auto_adjust=False, fetched {pd.Timestamp.now(tz=intake.IST).date()}",
                                          "nse": {"source": NSE_URL, "files": len(files), "days_without_a_file": [str(d) for d in no_file],
                                                  **ref_hashes, "file_hashes": files},
                                          "aeron7": {"dataset": ref_man["dataset"], "manifest_sha256": AERON_MANIFEST_SHA256, "source_commit": ref_man.get("source_commit")}},
           "at": str(pd.Timestamp.now(tz=intake.IST)), "symbols": {}, "info_only": info_only(man), "reasons": []}
    yd, refs = {}, {}
    for sym in SYMBOLS:                                                  # every fetch and every read happens before anything is computed or shown: a void can then never follow a verdict
        days = accepted[sym]
        try:
            raw_y = yahoo(sym, days[0], days[-1]) if days else pd.DataFrame(columns=["high", "low", "close"])
        except VoidRun:
            raise
        except Exception as exc:
            raise VoidRun(f"Yahoo for {sym} could not be fetched: {exc!s:.120}") from exc
        yd[sym] = clean_yahoo(raw_y, sym)
        rec["references"].setdefault("yahoo_frames", {})[sym] = {"sha256": _sha_csv(raw_y), "rows": int(len(raw_y)), "rows_unusable": int(len(raw_y) - len(yd[sym])),
                                                              "requested": [str(days[0]), str(days[-1])] if days else None}
        refs[sym] = ea.load(aeron_ds, "1m", [sym], use="development_folds")
    for sym in SYMBOLS:
        od = daily(loaded[sym])
        days = accepted[sym]
        rec["symbols"][sym] = {"A": check_a(od, yd[sym], days, nse_days), "B": check_b(od, nse[sym], days, nse_days), "C": check_c(loaded[sym], refs[sym])}
    rec["D"] = check_d(man, loaded)
    for sym, checks in rec["symbols"].items():
        rec["reasons"] += [f"{sym} {r}" for v in checks.values() for r in v["reasons"]]
    rec["reasons"] += rec["D"]["reasons"]
    rec["passed"] = not rec["reasons"]
    rec["symbols_verified"] = [s for s in SYMBOLS if all(v["passed"] for v in rec["symbols"][s].values())] if rec["passed"] else []     # no partial licence: all rules for both symbols
    return rec


def flip_status(ds: Path) -> str:
    """The status-only step after a pass: copy `passed` from the existing record into the manifest status. Re-compares nothing. Refuses unless the record
    names this manifest's digest, passed, carries this check's pinned criteria hash and lists symbols. Returns the status the loader now gives the symbols."""
    ds = Path(ds)
    try:
        man = json.loads((ds / "manifest.json").read_text())
        rec = json.loads((ds / "verification.json").read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"{ds}: no readable manifest.json and verification.json") from exc
    if not (isinstance(rec, dict) and rec.get("digest") == man.get("digest") and rec.get("passed") is True and rec.get("check") == CHECK
            and rec.get("criteria_sha256") == pinned_criteria_sha256() and rec.get("symbols_verified")
            and set(rec["symbols_verified"]) <= set(SYMBOLS) and not rec.get("reasons") and (rec.get("D") or {}).get("passed") is True
            and all(v.get("passed") is True for s_ in SYMBOLS for v in (rec.get("symbols") or {}).get(s_, {"x": {}}).values())
            and set(rec.get("symbols") or {}) >= set(SYMBOLS)):
        raise ValueError(f"{ds.name}: the verification record does not name this digest, did not pass, or is not a p06-v1 record with its scope: status unchanged")
    if man.get("status") != intake.VERIFIED:
        man["status"] = intake.VERIFIED
        intake._write_json(ds / "manifest.json", man)
        q = intake.quality(man)
        intake._write_json(ds / "quality.json", q)
        (ds / "quality.md").write_text(intake.render_quality(q, man))
    return intake.effective_status(ds, man, rec["symbols_verified"])
