"""The shadow lab: the desk's own setup logic run over history at volume, offline, with nothing near the live desk.

The entry filter (ML_ROADMAP M4) needs 300 to 500 labelled setups, and the live desk produces about fourteen trades a week. This module
replays whole past sessions through the real engine (the same analyst, playbook, gates and sizing as the live loop, on the model option
chain) in a throwaway journal, broker and memory, and records every armed setup that reached its level, labelled on what the underlying did next.

What it is not: it places nothing, reads no secret, opens no socket and writes only under `--out` (outside every git tree). Option prices in a
replay come from the model chain, so a shadow trade's P&L is not real: the label of record is `r_underlying`, the outcome of the setup on the
index itself (stop, target or the horizon's last close, in multiples of the planned risk). The source minutes are third-party and unverified;
every row carries the dataset's status and tier, and nothing here is evidence for a gate, a promotion or a profitability claim (the dataset's
own `not_for`).

Point in time: a fire happens inside the minute bar that ends at `now`; its label uses only bars that start at `now` or later. Setups from one
session are not independent samples (they share the day), so rows carry `day` and counts are of ideas, not of sessions.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HORIZON_MIN = 45                     # the same window the learning memory grades armed setups over
LOOKBACK_SESSIONS = 250              # prior sessions the replayed engine can see (it only ever reads the last few days plus its quant fit)
ALLOWED_USE = "underlying_features"  # one of the dataset's declared uses (ml.intake.ALLOWED_USES)
_SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
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


def replay_day(bars: dict[str, pd.DataFrame], day: dt.date, symbols: list[str], workdir: Path, horizon: int = HORIZON_MIN) -> list[dict]:
    """Replay one session through the real engine in a throwaway journal, broker and memory under `workdir`, and return a labelled row for every armed
    setup that reached its level (taken or turned away by a gate)."""
    from ..config import DEFAULT_CONFIG, Config
    from ..journal.journal import Journal
    from .engine import IntradayEngine, run_replay
    from .feeds import ReplayFeed
    from .learning import Memory
    from .sim import IntradayBroker
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(workdir / "runtime")}})
    feed = ReplayFeed(bars, day)
    journal = Journal(workdir / "journal.db")
    engine = IntradayEngine(cfg, feed, "model", journal, IntradayBroker(cfg, starting_cash=cfg.get("intraday.capital")), recorder=None, say=None,
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
                     "weekday": int(now.weekday()), **{f"view_{k}": v for k, v in feat.items()}, **lab,
                     "desk_taken": bool(len(took)), "desk_model_chain_r": float(took["r_multiple"].iloc[0]) if len(took) and pd.notna(took["r_multiple"].iloc[0]) else None,
                     "desk_gate_note": (str(turned["detail"].iloc[0])[:200] if len(turned) else None)})
    return mark_ideas(sorted(rows, key=lambda r: (r["ts"], r["symbol"])))


# ---- workers -----------------------------------------------------------------------------------------------------------------------
def lock_down() -> None:
    """In a worker: no outbound connection can be made and no credential-like variable remains in the environment."""
    import socket

    def _blocked(*a, **k):
        raise OSError("the shadow lab opens no connection")
    socket.socket.connect = _blocked
    socket.socket.connect_ex = _blocked
    socket.getaddrinfo = _blocked
    for k in list(os.environ):
        if any(w in k.upper() for w in _SECRET_WORDS):
            del os.environ[k]


def _prior_window(bars: dict[str, pd.DataFrame], day: dt.date, lookback: int) -> dict[str, pd.DataFrame]:
    out = {}
    for s, df in bars.items():
        days = pd.Index(df.index.date)
        keep = sorted(set(days[days <= day]))[-(lookback + 1):]
        out[s] = df[np.isin(days, keep)]
    return out


def _job(args: tuple) -> tuple:
    day, ds, symbols, lookback, horizon, part_dir, loader_spec = args
    global _BARS
    if _BARS is None:
        _BARS = _load_bars(ds, symbols, loader_spec)
    try:
        with tempfile.TemporaryDirectory(prefix="shadowlab-") as tmp:
            rows = replay_day(_prior_window(_BARS, day, lookback), day, symbols, Path(tmp), horizon)
        pd.DataFrame(rows).to_parquet(Path(part_dir) / f"{day}.parquet", index=False)
        return str(day), len(rows), None
    except Exception as exc:                                         # a session that cannot be replayed is reported, never silently dropped
        return str(day), 0, f"{exc.__class__.__name__}: {exc}"[:300]


_BARS = None


def _load_bars(ds, symbols, loader_spec) -> dict[str, pd.DataFrame]:
    from ..ml import intake as I
    df = (loader_spec or I.load)(Path(ds), list(symbols), use=ALLOWED_USE, allow_unverified=True)
    out = {}
    for s, g in df.groupby("symbol"):
        g = g.set_index(pd.to_datetime(g["ts"]).dt.tz_convert("Asia/Kolkata")).sort_index()
        out[s] = g[["open", "high", "low", "close", "volume"]]
    return out


# ---- the command -------------------------------------------------------------------------------------------------------------------
def _inside_git_tree(path: Path) -> Path | None:
    p = Path(path).resolve()
    return next((a for a in (p, *p.parents) if (a / ".git").exists()), None)


def code_state() -> dict:
    try:
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "quantdesk", "config"], capture_output=True, text=True,
                               timeout=20, check=True).stdout.strip()
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
    if out.exists() and (not out.is_dir() or any(p.name not in ("parts",) for p in out.iterdir())):
        raise Refused(f"--out {out} must be a new or empty folder (a resumed run may hold only its parts folder)")
    if not (dataset / "manifest.json").is_file() and loader is None:
        raise Refused(f"{dataset}: not an ml-intake dataset (no manifest.json)")
    bars = _load_bars(dataset, symbols, loader)
    sessions = sorted(set(bars[symbols[0]].index.date))
    pool = [d for d in sessions[lookback:] if (first is None or str(d) >= first) and (last is None or str(d) <= last)]
    if not pool:
        raise Refused("no session left after the lookback and the date window")
    days = sorted(np.random.default_rng(seed).choice(len(pool), size=min(sample, len(pool)), replace=False)) if sample else range(len(pool))
    days = [pool[i] for i in days]
    parts = out / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    todo = [d for d in days if not (parts / f"{d}.parquet").exists()]
    say(f"shadow lab: {len(days)} sessions drawn ({len(days) - len(todo)} already done), {len(todo)} to replay on {jobs} workers; nothing is placed, no connection is made")
    failures = []
    if todo:
        args = [(d, str(dataset), symbols, lookback, horizon, str(parts), loader) for d in todo]
        with executor(max_workers=jobs, initializer=lock_down) as ex:
            for day, n, err in ex.map(_job, args):
                if err:
                    failures.append({"day": day, "error": err})
                say(f"  {day}: {n} setups" + (f"  FAILED {err}" if err else ""))
    frames = [pd.read_parquet(p) for p in sorted(parts.glob("*.parquet"))]
    rows = pd.concat([f for f in frames if len(f)], ignore_index=True) if any(len(f) for f in frames) else pd.DataFrame()
    rows.to_parquet(out / "shadow_setups.parquet", index=False)
    ideas = rows[rows["idea_first"]] if len(rows) else rows
    from ..ml import intake as I
    man = {"kind": "shadow_lab", "code": code_state(), "symbols": symbols, "sessions_drawn": len(days), "sessions_failed": failures,
           "rows": int(len(rows)), "ideas": int(len(ideas)), "ideas_by_symbol": ideas["symbol"].value_counts().to_dict() if len(ideas) else {},
           "horizon_min": horizon, "lookback_sessions": lookback, "seed": seed, "first": first, "last": last,
           "label": "r_underlying: the setup's outcome on the index (stop first, target, or the horizon's last close), in multiples of planned risk",
           "option_pnl": "desk_model_chain_r comes from the model option chain: not a real P&L", "chain": "model",
           "source": {"path": str(dataset), "use": ALLOWED_USE, "allowed_uses": sorted(I.ALLOWED_USES), "evidence": "external_unverified"},
           "not_for": "never evidence for a gate, a promotion, the paper gate or a profitability claim; third-party minutes stay outside the repository",
           "independence": "setups from one session share the day: count ideas, evaluate per session"}
    (out / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    say(f"shadow lab: {man['rows']} fires, {man['ideas']} labelled ideas from {len(days) - len(failures)} sessions -> {out}")
    return man
