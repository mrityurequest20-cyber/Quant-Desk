"""The shadow lab: the desk's own setup logic run over history at volume, offline, with nothing near the live desk.

The entry filter (ML_ROADMAP M4) needs 300 to 500 labelled setups, and the live desk produces about fourteen trades a week. This module
replays whole past sessions through the real engine (the same analyst, playbook, gates and sizing code as the live loop, on the model option chain) in a throwaway
journal, broker and memory (the replay's runtime folder is empty, so the live desk's research priors, warehouse flows, buyer edge and learned memory are absent: the naive engine), and records every armed setup that reached its level, labelled on what the underlying did next.

What it is not: it places nothing, reads no secret and writes only under `--out` (outside every git tree). Its workers carry an accidental-network guard (the common
socket, DNS, subprocess and credential-variable paths are closed; it is not a sandbox: the engine in replay mode makes no network call by design, and an audit of a
replay saw none). Option prices in a
replay come from the model chain, so a shadow trade's P&L is not real: the label of record is `r_underlying`, the outcome of the setup on the
index itself (stop, target or the horizon's last close, in multiples of the planned risk). The source minutes are third-party and unverified;
every row carries the dataset's status and tier, and nothing here is evidence for a gate, a promotion or a profitability claim (the dataset's
own `not_for`).

Two sources. `shadow-replay --dataset` replays years of index minutes on the model option chain (volume; the label is on the index). `shadow-replay --tape`
replays the desk's own recorded sessions on the **real recorded option quotes** (bid and ask per strike, per minute): fills are at the recorded bid or ask
plus `adverse_ticks` of slippage (the live desk uses 1; stress it with more), and each row says how good the feed was at that moment (`chain_age_min`,
`tape_ok`, `index_frozen`, `bar_gap`, and `data_clean` = none of them flagged), so a setup made on a stale or frozen feed is never mistaken for a clean one.

Point in time: a fire happens inside the minute bar that ends at `now`; its label uses only bars that start at `now` or later. Setups from one
session are not independent samples (they share the day), so rows carry `day` and counts are of ideas, not of sessions.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HORIZON_MIN = 45                     # the same window the learning memory grades armed setups over
CHAIN_STALE_MIN = 5.0                # a recorded chain snapshot older than this at the fire is stale
LOOKBACK_SESSIONS = 250              # prior sessions the replayed engine can see (it only ever reads the last few days plus its quant fit)
ALLOWED_USE = "underlying_features"  # one of the dataset's declared uses (ml.intake.ALLOWED_USES)
_SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH", "API", "COOKIE")
REPO = Path(__file__).resolve().parents[2]


class Refused(Exception):
    """A refusal before anything is replayed or written."""


# ---- labels (pure) -----------------------------------------------------------------------------------------------------------------
def label_fire(bars: pd.DataFrame, now, fill: float, invalidation: float, direction: int, reward_risk: float, min_move: float,
               horizon: int = HORIZON_MIN) -> dict | None:
    """What the index did after an armed setup filled at `fill` inside the bar that ended at `now`: the stop first when one bar touches both,
    the target when only it is touched, otherwise the last close of the horizon. R is in multiples of the planned risk |fill - invalidation|.
    Only bars that start at `now` or later are read. None when there is no bar after the fill or the plan is not valid (the playbook's own test)."""
    risk = abs(fill - invalidation)
    if risk <= 0 or (direction > 0) != (fill > invalidation):
        return None
    target = fill + direction * max(reward_risk * risk, min_move)
    now = pd.Timestamp(now)
    after = bars[(bars.index >= now) & (bars.index < now + pd.Timedelta(minutes=horizon))].dropna(subset=["close"])
    if after.empty:
        return None
    best = worst = 0.0                                               # favourable and adverse excursion, in R, before the exit bar
    exit_reason, exit_ts, r = "horizon", after.index[-1], None
    for ts, row in zip(after.index, after.itertuples()):
        hit_stop = row.low <= invalidation if direction > 0 else row.high >= invalidation
        hit_tgt = row.high >= target if direction > 0 else row.low <= target
        if hit_stop:
            exit_reason, exit_ts, r = "stop", ts, -1.0
            worst = -1.0
            break
        if hit_tgt:
            exit_reason, exit_ts, r = "target", ts, abs(target - fill) / risk
            best = r
            break
        best = max(best, direction * ((row.high if direction > 0 else row.low) - fill) / risk)
        worst = min(worst, direction * ((row.low if direction > 0 else row.high) - fill) / risk)
    if r is None:
        r = direction * (float(after["close"].iloc[-1]) - fill) / risk
    return {"r_underlying": float(r), "exit_reason": exit_reason, "exit_ts": str(exit_ts), "mfe_r": float(best), "mae_r": float(worst),
            "target": float(target), "bars_after": int(len(after))}


def mark_ideas(rows: list[dict], window_min: int = HORIZON_MIN) -> list[dict]:
    """A setup that re-arms on the same symbol, strategy and direction within its window is the same idea (the engine re-arms a level every minute):
    the first fire is the labelled idea (`idea_first`), later ones are kept but not counted. Rows are in firing order."""
    last: dict[tuple, pd.Timestamp] = {}
    for r in rows:
        key, t = (r["symbol"], r["setup"], r["direction"]), pd.Timestamp(r["ts"])
        prev = last.get(key)
        r["idea_first"] = prev is None or t - prev > pd.Timedelta(minutes=window_min)
        if r["idea_first"]:
            last[key] = t
    return rows


# ---- one replayed session ----------------------------------------------------------------------------------------------------------
def _view_features(view) -> dict:
    st = getattr(view, "state", None) or {}
    out = {"bias": getattr(view, "bias", None), "score": getattr(view, "score", None), "conviction": getattr(view, "conviction", None),
           "day_type": getattr(view, "day_type", None), "vol_view": getattr(view, "vol_view", None), "iv": getattr(view, "iv", None),
           "rv": getattr(view, "rv", None), "chg": st.get("chg"), "vwap": st.get("vwap"), "phase": st.get("phase")}
    return {k: (float(v) if isinstance(v, (int, float, np.floating)) and not isinstance(v, bool) else v) for k, v in out.items()}


def _quality(bars: pd.DataFrame, now: pd.Timestamp, symbol: str, snaps: dict | None, tape: pd.DataFrame | None) -> dict:
    """How good the feed was when the setup fired. None means not applicable (a model chain has no snapshots, a dataset has no tape log)."""
    from .feeds import frozen_minutes
    age = None
    if snaps is not None:
        prior = [pd.Timestamp(c.attrs["ts"]) for c in snaps.get(symbol, []) if pd.Timestamp(c.attrs["ts"]) <= now]
        age = float((now - max(prior)) / pd.Timedelta(minutes=1)) if prior else float("inf")
    tape_ok = None
    if tape is not None and len(tape):
        t = tape[(tape["underlying"] == symbol) & (tape["ts"] <= now)]
        tape_ok = bool(t["ok"].iloc[-1]) and int(t["quoted"].iloc[-1]) > 0 if len(t) else False
    day_bars = bars[bars.index.date == now.date()]
    last = now - pd.Timedelta(minutes=1)                                              # the bar that triggered the fire ends at `now`
    frozen = bool(last in frozen_minutes(day_bars))
    gap = bool(last not in day_bars.index)
    clean = (age is None or age <= CHAIN_STALE_MIN) and not frozen and not gap and tape_ok is not False
    return {"chain_age_min": age, "tape_ok": tape_ok, "index_frozen": frozen, "bar_gap": gap, "data_clean": bool(clean)}


def replay_day(bars: dict[str, pd.DataFrame], day: dt.date, symbols: list[str], workdir: Path, horizon: int = HORIZON_MIN, chains="model",
               adverse_ticks: int = 1, tape: pd.DataFrame | None = None, specs: dict | None = None) -> list[dict]:
    """Replay one session through the real engine in a throwaway journal, broker and memory under `workdir`, and return a labelled row for every armed
    setup that reached its level (taken or turned away by a gate). `chains` is "model" or a RecordedChains; `adverse_ticks` is the slippage on top of the
    bid/ask fills; `tape` is the day's tape health log (tape.csv) when there is one."""
    from ..config import DEFAULT_CONFIG, Config
    from ..journal.journal import Journal
    from .engine import IntradayEngine, run_replay
    from .feeds import ReplayFeed
    from .learning import Memory
    from .sim import IntradayBroker
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(workdir / "runtime")}, **({"instruments": specs} if specs else {})})
    feed = ReplayFeed(bars, day)
    journal = Journal(workdir / "journal.db")
    engine = IntradayEngine(cfg, feed, chains, journal, IntradayBroker(cfg, starting_cash=cfg.get("intraday.capital"), adverse_ticks=adverse_ticks), recorder=None, say=None,
                            underlyings=list(symbols), review_dir=workdir / "reviews", memory=Memory(workdir / "memory.json"))
    fires: list[tuple] = []
    original = engine.playbook.fire

    def logged(a, view, chain, now, S):
        fires.append((a, _view_features(view), pd.Timestamp(now), float(S)))
        return original(a, view, chain, now, S)
    engine.playbook.fire = logged
    try:
        run_replay(engine)
        decisions = journal.df("SELECT ts, symbol, strategy, action, detail FROM decisions")
        trades = journal.df("SELECT strategy, symbol, opened_at, r_multiple, exit_reason, pnl FROM trades")
    finally:
        journal.close()
    open_ts = pd.Timestamp(dt.datetime.combine(day, dt.time(9, 15)), tz="Asia/Kolkata")
    snaps = getattr(chains, "snaps", None)
    rows = []
    for a, feat, now, S in fires:
        lab = label_fire(bars[a.symbol], now, S, a.invalidation, a.direction, a.reward_risk, a.min_move, horizon)
        if lab is None:
            continue
        took = trades[(trades["symbol"] == a.symbol) & (trades["strategy"] == a.setup)
                      & (pd.to_datetime(trades["opened_at"]).dt.floor("min") == now.floor("min"))] if len(trades) else trades
        turned = decisions[(decisions["symbol"] == a.symbol) & (decisions["strategy"] == a.setup) & (decisions["action"] == "rejected")
                           & (pd.to_datetime(decisions["ts"]).dt.floor("min") == now.floor("min"))] if len(decisions) else decisions
        rows.append({"day": str(day), "ts": str(now), "symbol": a.symbol, "setup": a.setup, "direction": int(a.direction), "kind": a.kind,
                     "fill": S, "level": float(a.level), "invalidation": float(a.invalidation), "reward_risk": float(a.reward_risk),
                     "risk_pct": abs(S - a.invalidation) / S * 100.0, "minutes_since_open": int((now - open_ts) / pd.Timedelta(minutes=1)),
                     "weekday": int(now.weekday()), "chain_source": "recorded" if snaps is not None else "model", "adverse_ticks": int(adverse_ticks),
                     **_quality(bars[a.symbol], now, a.symbol, snaps, tape), **{f"view_{k}": v for k, v in feat.items()}, **lab,
                     "desk_taken": bool(len(took)), "desk_model_chain_r": float(took["r_multiple"].iloc[0]) if len(took) and pd.notna(took["r_multiple"].iloc[0]) else None,
                     "desk_gate_note": (str(turned["detail"].iloc[0])[:200] if len(turned) else None)})
    return mark_ideas(sorted(rows, key=lambda r: (r["ts"], r["symbol"])))


# ---- workers -----------------------------------------------------------------------------------------------------------------------
def lock_down() -> None:
    """In a worker: an accidental-network guard. The common ways to open a connection (TCP and UDP sockets, DNS lookups, subprocess and os.system) raise, and every
    environment variable whose name suggests a credential is dropped. It is not a sandbox: a determined path (a C extension, a raw syscall) is not covered; the engine in replay
    mode makes no network call by design."""
    import socket
    import subprocess

    def _blocked(*a, **k):
        raise OSError("the shadow lab opens no connection")
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        setattr(socket.socket, name, _blocked)
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "getnameinfo", "gethostbyaddr", "create_connection"):
        setattr(socket, name, _blocked)
    subprocess.Popen.__init__ = _blocked
    os.system = _blocked
    for k in list(os.environ):
        if any(w in k.upper() for w in _SECRET_WORDS):
            del os.environ[k]


def _init_worker(work_root: str) -> None:
    """Worker start-up: the guard above, and every temporary file goes under the (already checked) output folder, never a system temp location that could sit in a git tree."""
    lock_down()
    Path(work_root).mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = work_root


def _prior_window(bars: dict[str, pd.DataFrame], day: dt.date, lookback: int) -> dict[str, pd.DataFrame]:
    out = {}
    for s, df in bars.items():
        days = pd.Index(df.index.date)
        keep = sorted(set(days[days <= day]))[-(lookback + 1):]
        out[s] = df[np.isin(days, keep)]
    return out


def _write_part(rows: list, part_dir, key: str, cov: dict | None = None) -> None:
    """Write one session's rows atomically, with its per-symbol minute counts beside it (so a resumed session keeps its coverage): a stopped run leaves no truncated part."""
    if cov is not None:
        (Path(part_dir) / f"{key}.cov.json").write_text(json.dumps(cov))
    final = Path(part_dir) / f"{key}.parquet"
    partial = Path(part_dir) / f".{key}.parquet.tmp"
    pd.DataFrame(rows).to_parquet(partial, index=False)
    os.replace(partial, final)


def _coverage(bars: dict, day: dt.date, symbols: list[str]) -> dict:
    """Minute bars each requested symbol has on `day` (a full session has 375): incomplete coverage is recorded, not hidden."""
    return {s: int((pd.Index(bars[s].index.date) == day).sum()) if s in bars else 0 for s in symbols}


def _job(args: tuple) -> tuple:
    day, ds, symbols, lookback, horizon, part_dir, loader_spec = args
    global _BARS
    if _BARS is None:
        _BARS = _load_bars(ds, symbols, loader_spec)
    try:
        with tempfile.TemporaryDirectory(prefix="shadowlab-") as tmp:
            rows = replay_day(_prior_window(_BARS, day, lookback), day, symbols, Path(tmp), horizon)
        cov = _coverage(_BARS, day, symbols)
        _write_part(rows, part_dir, str(day), cov)
        return str(day), len(rows), None, cov
    except Exception as exc:                                         # a session that cannot be replayed is reported, never silently dropped
        return str(day), 0, f"{exc.__class__.__name__}: {exc}"[:300], {}


_BARS = None


def _dataset_has(ds, symbol: str) -> bool:
    try:
        man = json.loads((Path(ds) / "manifest.json").read_text())
        return any(f"symbol={symbol}/" in k for k in man.get("partitions", {}))
    except (OSError, ValueError):
        return False


def _load_bars(ds, symbols, loader_spec) -> dict[str, pd.DataFrame]:
    """The requested symbols' minutes, plus the dataset's INDIAVIX when it holds one (the engine prices its model chain on it, as the live desk does; it is never an underlying)."""
    from ..ml import intake as I
    want = list(symbols) + (["INDIAVIX"] if loader_spec is None and "INDIAVIX" not in symbols and _dataset_has(ds, "INDIAVIX") else [])
    df = (loader_spec or I.load)(Path(ds), want, use=ALLOWED_USE, allow_unverified=True)
    out = {}
    for s, g in df.groupby("symbol"):
        g = g.set_index(pd.to_datetime(g["ts"]).dt.tz_convert("Asia/Kolkata")).sort_index()
        out[s] = g[["open", "high", "low", "close", "volume"]]
    return out


def _job_tape(args: tuple) -> tuple:
    """One recorded session on its real recorded quotes. The recorder folder is read, never written."""
    from .chains import RecordedChains
    from .recorder import SessionRecorder
    day, root, symbols, horizon, part_dir, adverse_ticks, vix = args
    try:
        rec = SessionRecorder(Path(root))
        bars = rec.load_bars(list(symbols) + [vix], upto=day)
        snaps = rec.load_chains(day)
        chains = RecordedChains(snaps) if snaps else "model"
        tape = None
        tp = rec.day_dir(day) / "tape.csv"
        if tp.is_file():
            tape = pd.read_csv(tp)
            tape["ts"] = pd.to_datetime(tape["ts"], format="mixed").dt.tz_convert("Asia/Kolkata")
            tape = tape.sort_values("ts")
        with tempfile.TemporaryDirectory(prefix="shadowlab-") as tmp:
            rows = replay_day(bars, day, list(symbols), Path(tmp), horizon, chains=chains, adverse_ticks=adverse_ticks, tape=tape)
        cov = _coverage(bars, day, list(symbols))
        _write_part(rows, part_dir, str(day), cov)
        return str(day), len(rows), None, cov
    except Exception as exc:
        return str(day), 0, f"{exc.__class__.__name__}: {exc}"[:300], {}


# ---- stocks ------------------------------------------------------------------------------------------------------------------------
_STEPS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0, 250.0, 500.0)
STOCK_IV_BETA = 1.6                  # a stock's implied vol against the index's: typical, not measured
MIN_COVERAGE = 300                   # of 375 minutes: a thinner symbol-session is listed in the manifest as incomplete
MIN_STOCK_BARS = 300                 # of 375: a thinner session is skipped and said so
MIN_PRIOR_SESSIONS = 3


def stock_spec(price: float) -> dict:
    """An APPROXIMATE contract spec for a stock the registry does not carry: lot 1, a strike step near 0.6% of the price, monthly expiry,
    a typical IV beta. Setups are found and labelled on the underlying, which none of this touches; it only lets the model chain price the
    desk's hypothetical option (the `desk_*` columns, flagged not real)."""
    return {"kind": "equity", "lot_size": 1, "strike_step": min(_STEPS, key=lambda x: abs(x - 0.006 * price)), "weekly_expiry": False,
            "expiry_weekday": 1, "iv_beta": STOCK_IV_BETA, "approx": True}


def load_stock_bars(stock_dir: Path, vix_dir: Path | None = None, vix: str = "INDIAVIX") -> dict[str, pd.DataFrame]:
    """The union of the release's `*_stocks_cash.parquet` files (each a rolling window of recent sessions): one OHLCV frame per stock, plus the
    recorded INDIAVIX when `vix_dir` (the desk's recorder folder) has it."""
    frames = [pd.read_parquet(f) for f in sorted(Path(stock_dir).glob("*_stocks_cash.parquet"))]
    if not frames:
        raise Refused(f"{stock_dir}: no *_stocks_cash.parquet files")
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_convert("Asia/Kolkata")
    df = df.drop_duplicates(["symbol", "ts"]).sort_values(["symbol", "ts"])
    out = {s: g.set_index("ts")[["open", "high", "low", "close", "volume"]] for s, g in df.groupby("symbol")}
    if vix_dir is not None:
        from .recorder import SessionRecorder
        out.update(SessionRecorder(Path(vix_dir)).load_bars([vix]))
    return out


def _job_stock(args: tuple) -> tuple:
    day, sym, stock_dir, vix_dir, horizon, part_dir = args
    global _STOCK_BARS
    if _STOCK_BARS is None:
        _STOCK_BARS = load_stock_bars(Path(stock_dir), Path(vix_dir) if vix_dir else None)
    key = f"{day}_{sym}"
    try:
        b = _STOCK_BARS[sym]
        prior = _prior_window({sym: b}, day, 30)[sym]
        bars = {sym: prior}
        if "INDIAVIX" in _STOCK_BARS:
            bars["INDIAVIX"] = _prior_window({"INDIAVIX": _STOCK_BARS["INDIAVIX"]}, day, 30)["INDIAVIX"]
        price = float(b[b.index.date == day]["close"].iloc[0])
        with tempfile.TemporaryDirectory(prefix="shadowlab-") as tmp:
            rows = replay_day(bars, day, [sym], Path(tmp), horizon, specs={sym: stock_spec(price)})
        for r in rows:
            r["instrument_kind"] = "stock"
            r["spec_approx"] = True
        cov = _coverage(bars, day, [sym])
        _write_part(rows, part_dir, key, cov)
        return key, len(rows), None, cov
    except Exception as exc:
        return key, 0, f"{exc.__class__.__name__}: {exc}"[:300], {}


_STOCK_BARS = None


def run_stocks(stock_dir: Path, out: Path, vix_dir: Path | None = None, symbols: list[str] | None = None, first: str | None = None, last: str | None = None,
               jobs: int = 3, horizon: int = HORIZON_MIN, say=print, executor=ProcessPoolExecutor) -> dict:
    """Replay every (stock, session) with enough minutes and prior sessions: the same real engine and the same labels as the index runs.
    `stock_dir` holds the `stock-minutes-2026` release's cash parquets (downloaded; public traded-bar minutes). Stock option quotes are not
    recorded per minute, so the chain is the model chain and the `desk_*` columns are not real."""
    stock_dir, out = Path(stock_dir), Path(out)
    if (g := _inside_git_tree(out)) is not None:
        raise Refused(f"--out {out} is inside a git working tree ({g}): the rows are derived from broker minutes and stay outside")
    if out.exists() and (not out.is_dir() or any(p.name not in ("parts", ".work") for p in out.iterdir())):
        raise Refused(f"--out {out} must be a new or empty folder (a resumed run may hold only its parts folder)")
    bars = load_stock_bars(stock_dir, Path(vix_dir) if vix_dir else None)
    stocks = sorted(s for s in bars if s != "INDIAVIX" and (symbols is None or s in symbols))
    if symbols and (absent := [s for s in symbols if s not in bars]):
        raise Refused(f"{stock_dir}: no minutes for {', '.join(absent)}")
    jobs_list, skipped = [], []
    for sym in stocks:
        b = bars[sym]
        sessions = sorted(set(b.index.date))
        for i, d in enumerate(sessions):
            if (first and str(d) < first) or (last and str(d) > last):
                continue
            n = int((pd.Index(b.index.date) == d).sum())
            if i < MIN_PRIOR_SESSIONS or n < MIN_STOCK_BARS:
                skipped.append({"stock": sym, "day": str(d), "why": f"{n} minutes, {i} prior sessions"})
                continue
            jobs_list.append((d, sym))
    if not jobs_list:
        raise Refused("no (stock, session) with enough minutes and prior sessions")
    parts = out / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    _bind_parts(parts, {"kind": "stocks", "path": str(stock_dir), "code": code_state(), "horizon": horizon, "vix": str(vix_dir), "stocks": stocks})
    keys = [f"{d}_{s}" for d, s in jobs_list]
    todo = [(d, s) for d, s in jobs_list if not (parts / f"{d}_{s}.parquet").exists()]
    say(f"shadow lab (stocks): {len(stocks)} stocks, {len(keys)} stock-sessions ({len(keys) - len(todo)} already done), {len(todo)} to replay on {jobs} workers; {len(skipped)} skipped")
    failures = []
    if todo:
        with executor(max_workers=jobs, initializer=_init_worker, initargs=(str(out / ".work"),)) as ex:
            for key, n, err, cov in ex.map(_job_stock, [(d, s, str(stock_dir), str(vix_dir) if vix_dir else None, horizon, str(parts)) for d, s in todo]):
                if err:
                    failures.append({"key": key, "error": err})
                say(f"  {key}: {n} setups" + (f"  FAILED {err}" if err else ""))
    return _finish(out, parts, keys, failures, {"symbols": stocks, "horizon_min": horizon, "chain": "model", "adverse_ticks": 1, "skipped": skipped,
                   "engine_vix": "recorded INDIAVIX when the recorder folder had it, else a constant 14.0 fallback",
                   "stock_spec": "approximate (lot 1, strike step near 0.6% of price, IV beta 1.6): the desk_* columns are not real; labels are on the underlying",
                   "source": {"path": str(stock_dir), "kind": "Kotak traded 1-minute cash bars of liquid F&O stocks (stock-minutes-2026 release)", "evidence": "broker traded minutes, a few sessions of history"}}, say)


# ---- the command -------------------------------------------------------------------------------------------------------------------
def _inside_git_tree(path: Path) -> Path | None:
    p = Path(path).resolve()
    return next((a for a in (p, *p.parents) if (a / ".git").exists()), None)


def _digest(ds) -> str | None:
    try:
        return json.loads((Path(ds) / "manifest.json").read_text()).get("digest")
    except (OSError, ValueError):
        return None


def code_state() -> dict:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}                # a read-only look: never refresh the index
    try:
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20, check=True, env=env).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "quantdesk", "config"], capture_output=True, text=True,
                               timeout=20, check=True, env=env).stdout.strip()
        return {"commit": head or None, "dirty": bool(dirty)}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def run(dataset: Path, out: Path, symbols: list[str] | None = None, sample: int | None = None, seed: int = 20261031, first: str | None = None,
        last: str | None = None, jobs: int = 3, lookback: int = LOOKBACK_SESSIONS, horizon: int = HORIZON_MIN, say=print, loader=None,
        executor=ProcessPoolExecutor) -> dict:
    """Replay `sample` sessions (a seeded random draw from `first` to `last`, or all of them) and write `shadow_setups.parquet` and
    `manifest.json` under `out`. Resumable: a session already written under `out/parts` is not replayed again."""
    dataset, out = Path(dataset), Path(out)
    symbols = list(symbols or ["NIFTY", "BANKNIFTY"])
    if (g := _inside_git_tree(out)) is not None:
        raise Refused(f"--out {out} is inside a git working tree ({g}): the rows are derived from third-party minutes and stay outside")
    if out.exists() and (not out.is_dir() or any(p.name not in ("parts", ".work") for p in out.iterdir())):
        raise Refused(f"--out {out} must be a new or empty folder (a resumed run may hold only its parts folder)")
    if not (dataset / "manifest.json").is_file() and loader is None:
        raise Refused(f"{dataset}: not an ml-intake dataset (no manifest.json)")
    bars = _load_bars(dataset, symbols, loader)
    if absent := [s for s in symbols if s not in bars]:
        raise Refused(f"{dataset}: no minutes for {', '.join(absent)}")
    sessions = sorted(set(bars[symbols[0]].index.date))
    pool = [d for d in sessions[lookback:] if (first is None or str(d) >= first) and (last is None or str(d) <= last)]
    if not pool:
        raise Refused("no session left after the lookback and the date window")
    days = sorted(np.random.default_rng(seed).choice(len(pool), size=min(sample, len(pool)), replace=False)) if sample else range(len(pool))
    days = [pool[i] for i in days]
    parts = out / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    _bind_parts(parts, {"kind": "dataset", "path": str(dataset), "digest": _digest(dataset), "code": code_state(), "symbols": symbols, "lookback": lookback,
                        "horizon": horizon, "adverse_ticks": 1})
    todo = [d for d in days if not (parts / f"{d}.parquet").exists()]
    say(f"shadow lab: {len(days)} sessions drawn ({len(days) - len(todo)} already done), {len(todo)} to replay on {jobs} workers; nothing is placed, no connection is made")
    failures = []
    if todo:
        args = [(d, str(dataset), symbols, lookback, horizon, str(parts), loader) for d in todo]
        with executor(max_workers=jobs, initializer=_init_worker, initargs=(str(out / ".work"),)) as ex:
            for day, n, err, cov in ex.map(_job, args):
                if err:
                    failures.append({"day": day, "error": err})
                say(f"  {day}: {n} setups" + (f"  FAILED {err}" if err else ""))
    return _finish(out, parts, [str(d) for d in days], failures, {"symbols": symbols, "horizon_min": horizon, "lookback_sessions": lookback, "seed": seed,
                   "first": first, "last": last, "chain": "model", "adverse_ticks": 1,
                   "engine_vix": "the dataset's INDIAVIX minutes when the dataset holds them (the model chain is priced on it, point in time), else the engine's constant 14.0 fallback",
                   "source": {"path": str(dataset), "use": ALLOWED_USE, "evidence": "external_unverified"}}, say)


def _bind_parts(parts: Path, params: dict) -> None:
    """A resumed run may only add to parts made with the same parameters: the first run writes them down, later runs must match."""
    f = parts / "fingerprint.json"
    want = json.dumps(params, sort_keys=True, default=str)
    if f.exists():
        if f.read_text() != want:
            raise Refused(f"{parts}: these parts were made with other parameters ({f.read_text()[:200]}); use a new --out")
    else:
        f.write_text(want)


def _finish(out: Path, parts: Path, keys: list, failures: list, extra: dict, say) -> dict:
    """Merge the per-session parts of exactly the sessions drawn into `shadow_setups.parquet` and write `manifest.json`."""
    days = list(keys)
    frames = [pd.read_parquet(parts / f"{k}.parquet") for k in keys if (parts / f"{k}.parquet").exists()]
    rows = pd.concat([f for f in frames if len(f)], ignore_index=True) if any(len(f) for f in frames) else pd.DataFrame()
    rows.to_parquet(out / "shadow_setups.parquet", index=False)
    ideas = rows[rows["idea_first"]] if len(rows) else rows
    clean = ideas[ideas["data_clean"]] if len(ideas) and "data_clean" in ideas else ideas
    cov = {k: json.loads((parts / f"{k}.cov.json").read_text()) for k in keys if (parts / f"{k}.cov.json").exists()}
    thin = {k: v for k, v in cov.items() if any(n < MIN_COVERAGE for n in v.values())}
    from ..ml import intake as I
    man = {"kind": "shadow_lab", "code": code_state(), "sessions_drawn": len(days), "sessions_failed": failures,
           "rows": int(len(rows)), "ideas": int(len(ideas)), "ideas_data_clean": int(len(clean)),
           "coverage_recorded_for": len(cov), "coverage_incomplete": thin,
           "ideas_by_symbol": ideas["symbol"].value_counts().to_dict() if len(ideas) else {},
           "label": "r_underlying: the setup's outcome on the index (stop first, target, or the last close of the horizon or of the session if that comes first), in multiples of planned risk",
           "replay_inputs": "the replay's runtime folder is empty: no research priors, warehouse flows, buyer edge or learned memory reach the engine (the naive engine)",
           "option_pnl": "desk_model_chain_r is the paper desk's R on the chain it was replayed on (model: not a real P&L; recorded: real bid/ask fills plus adverse ticks)",
           "allowed_uses": sorted(I.ALLOWED_USES),
           "not_for": "never evidence for a gate, a promotion, the paper gate or a profitability claim; third-party minutes stay outside the repository",
           "independence": "setups from one session share the day: count ideas, evaluate per session", **extra}
    shutil.rmtree(out / ".work", ignore_errors=True)
    (out / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    say(f"shadow lab: {man['rows']} fires, {man['ideas']} labelled ideas ({man['ideas_data_clean']} on a clean feed) from {len(days) - len(failures)} sessions -> {out}")
    return man


def run_tape(recorder_dir: Path, out: Path, symbols: list[str] | None = None, first: str | None = None, last: str | None = None,
             adverse_ticks: int = 1, jobs: int = 3, horizon: int = HORIZON_MIN, say=print, executor=ProcessPoolExecutor, vix: str = "INDIAVIX") -> dict:
    """Replay the desk's own recorded sessions on their real recorded option quotes. `recorder_dir` is the data folder the live jobs upload
    (`<day>/<SYMBOL>_1m.csv`, `<day>/chains/*.csv`, `<day>/tape.csv`)."""
    from .recorder import SessionRecorder
    recorder_dir, out = Path(recorder_dir), Path(out)
    symbols = list(symbols or ["NIFTY", "BANKNIFTY"])
    if (g := _inside_git_tree(out)) is not None:
        raise Refused(f"--out {out} is inside a git working tree ({g}): the rows are derived from recorded broker quotes and stay outside")
    if out.exists() and (not out.is_dir() or any(p.name not in ("parts", ".work") for p in out.iterdir())):
        raise Refused(f"--out {out} must be a new or empty folder (a resumed run may hold only its parts folder)")
    if not recorder_dir.is_dir():
        raise Refused(f"{recorder_dir}: no recorder folder")
    all_days = SessionRecorder(recorder_dir).days()
    days = [d for d in all_days if (first is None or str(d) >= first) and (last is None or str(d) <= last)
            and (recorder_dir / str(d) / "chains").is_dir() and all((recorder_dir / str(d) / f"{s}_1m.csv").is_file() for s in symbols)]
    if not days:
        raise Refused("no recorded session with bars and chain snapshots in the window")
    parts = out / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    _bind_parts(parts, {"kind": "tape", "path": str(recorder_dir), "code": code_state(), "symbols": symbols, "horizon": horizon, "adverse_ticks": adverse_ticks, "vix": vix})
    todo = [d for d in days if not (parts / f"{d}.parquet").exists()]
    say(f"shadow lab (recorded quotes): {len(days)} sessions ({len(days) - len(todo)} already done), {len(todo)} to replay on {jobs} workers, adverse ticks {adverse_ticks}")
    failures = []
    if todo:
        with executor(max_workers=jobs, initializer=_init_worker, initargs=(str(out / ".work"),)) as ex:
            for day, n, err, cov in ex.map(_job_tape, [(d, str(recorder_dir), symbols, horizon, str(parts), adverse_ticks, vix) for d in todo]):
                if err:
                    failures.append({"day": day, "error": err})
                say(f"  {day}: {n} setups" + (f"  FAILED {err}" if err else ""))
    return _finish(out, parts, [str(d) for d in days], failures, {"symbols": symbols, "horizon_min": horizon, "chain": "recorded", "adverse_ticks": adverse_ticks,
                                                "first": first, "last": last, "source": {"path": str(recorder_dir), "kind": "the desk's own recorded sessions", "evidence": "recorded broker quotes (not third-party minutes)",
                                                "quotes": "real bid and ask per strike per minute (Kotak), recorded beside the desk"}}, say)
