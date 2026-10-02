"""The research experiment ledger and the paper gate.

Every research run is appended to a JSONL ledger with its code digest, data fingerprints, hypotheses, parameters
and verdicts, so any result can be traced to exactly what produced it. The chronological validation slice is
re-inspected by every weekly run, so it is called rolling validation, never an untouched holdout: the forward
test is the paper desk itself, and `evaluate_paper_candidate` is the bar a strategy clears there before real money.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pandas as pd

MIN_PAPER_SESSIONS = 60
MIN_PAPER_TRADES = 30
MIN_PAPER_PROFIT_FACTOR = 1.15
MAX_PAPER_DRAWDOWN_FRACTION = 0.10


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _data_fingerprint(data: dict) -> dict:
    out = {}
    groups = [(family, data.get(family) or {}) for family in ("daily", "hourly", "m5")]
    groups += [(f"global:{family}", (data.get("global") or {}).get(family) or {}) for family in ("daily", "m5")]
    for family, frames in groups:
        for symbol, frame in frames.items():
            frame = frame.sort_index()
            cols = [c for c in ("open", "high", "low", "close", "volume") if c in frame]
            digest_input = frame[cols].to_csv(float_format="%.12g", date_format="%Y-%m-%dT%H:%M:%S%z").encode()
            out[f"{family}:{symbol}"] = {
                "rows": int(len(frame)), "first": str(frame.index.min()) if len(frame) else None,
                "last": str(frame.index.max()) if len(frame) else None, "sha256": _sha256(digest_input),
            }
    return out


def _software_versions() -> dict:
    from importlib.metadata import PackageNotFoundError, version
    out = {"python": sys.version.split()[0], "platform": platform.platform()}
    for package in ("numpy", "pandas", "scipy", "pyarrow"):
        try:
            out[package] = version(package)
        except PackageNotFoundError:
            pass
    return out


def _warehouse_fingerprint(folder: str | Path | None) -> dict:
    if folder is None:
        return {}
    root = Path(folder)
    out = {}
    for path in sorted(root.glob("*.parquet")) if root.exists() else []:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        out[path.name] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    return out


def _code_fingerprint() -> str:
    root = Path(__file__).resolve().parents[2]
    files = sorted((root / "quantdesk" / "research").glob("*.py"))
    files += [root / "quantdesk" / "cli.py", root / "config" / "quantdesk.yaml",
              root / "quantdesk" / "options" / "pricing.py"]
    h = hashlib.sha256()
    for path in files:
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def _append(path: str | Path, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(_json_safe(record), ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def _revision() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2],
                              check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def start_experiment(path: str | Path, generated: str) -> dict:
    """Durably register an attempt before network loading or computation begins."""
    record = {
        "event": "research_started", "run_id": uuid.uuid4().hex, "generated": generated,
        "git_revision": _revision(), "research_code_sha256": _code_fingerprint(),
        "software": _software_versions(),
    }
    _append(path, record)
    return _json_safe(record)


def append_experiment(path: str | Path, data: dict, results, generated: str, run_id: str | None = None) -> dict:
    """Append the immutable result record for an already registered run."""
    record = {
        "event": "research_completed", "run_id": run_id or uuid.uuid4().hex, "generated": generated,
        "git_revision": _revision(), "research_code_sha256": _code_fingerprint(),
        "software": _software_versions(),
        "method": "Newey-West HAC; BH q=0.10 on discovery p-values; chronological rolling validation; costs included",
        "rolling_validation_is_final": False,
        "datasets": _data_fingerprint(data),
        "experiments": [{"id": r.id, "symbol": r.symbol, "hypothesis": r.hypothesis,
                         "parameters": r.params, "n": r.n, "effect_bps": r.effect_bps,
                         "p_discovery": r.params.get("p_discovery"), "rolling_validation_p": r.p_holdout,
                         "cost_hurdle_points": r.hurdle_pts, "verdict": r.verdict} for r in results],
    }
    _append(path, record)
    return _json_safe(record)


def append_warehouse_experiment(path: str | Path, data: dict, result: dict, generated: str,
                                run_id: str, warehouse_dir: str | Path | None = None) -> dict:
    """Append the separately-run NSE options and positioning hypotheses to the same ledger."""
    def row(item):
        return asdict(item) if is_dataclass(item) else dict(item)

    record = {
        "event": "warehouse_research_completed", "run_id": run_id, "generated": generated,
        "git_revision": _revision(), "research_code_sha256": _code_fingerprint(),
        "software": _software_versions(),
        "method": "NSE bhavcopy; Newey-West HAC; BH q=0.10 on discovery p-values; rolling validation; costs included",
        "rolling_validation_is_final": False,
        "datasets": _data_fingerprint(data),
        "warehouse_files": _warehouse_fingerprint(warehouse_dir),
        "hypotheses": {
            "vrp": [{k: row(r).get(k) for k in ("symbol", "strategy", "k", "n", "mean_pts", "t", "p",
                                                   "mean_holdout_pts", "p_holdout", "bh_pass", "verdict", "params")}
                    for r in result.get("vrp", [])],
            "positioning": [{k: row(r).get(k) for k in ("id", "symbol", "hypothesis", "n", "effect_bps", "t", "p",
                                                           "effect_holdout_bps", "p_holdout", "bh_pass", "verdict", "params")}
                            for r in result.get("positioning", [])],
        },
    }
    _append(path, record)
    return _json_safe(record)


def fail_experiment(path: str | Path, run_id: str, generated: str, error_type: str) -> None:
    """Record failures without logging potentially sensitive exception contents."""
    _append(path, {"event": "research_failed", "run_id": run_id, "generated": generated,
                   "error_type": str(error_type)[:100]})


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    return str(value)


def evaluate_paper_candidate(trades: pd.DataFrame, observed_sessions: int, risk_violations: int,
                             capital: float) -> dict:
    """Read-only, cost-inclusive check of a strategy's closed paper trades: the bar before real money."""
    closed = trades.copy()
    if "status" in closed:
        closed = closed[closed["status"] == "closed"]
    if "closed_at" in closed:
        closed = closed.sort_values("closed_at", kind="stable")
    pnl = pd.to_numeric(closed.get("pnl", pd.Series(dtype=float)), errors="coerce").dropna()
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    profit_factor = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else (math.inf if len(wins) else 0.0)
    curve = capital + pnl.cumsum()
    peaks = curve.cummax().clip(lower=capital) if len(curve) else curve
    dd = curve - peaks if len(curve) else pd.Series(dtype=float)
    drawdown = float(abs(min(0.0, float(dd.min())) / capital)) if capital > 0 and len(dd) else math.inf
    checks = {
        "minimum_60_paper_sessions": observed_sessions >= MIN_PAPER_SESSIONS,
        "minimum_30_closed_trades": len(pnl) >= MIN_PAPER_TRADES,
        "positive_net_after_costs": bool(len(pnl) and pnl.sum() > 0),
        "profit_factor_at_least_1_15": profit_factor >= MIN_PAPER_PROFIT_FACTOR,
        "max_drawdown_at_most_10_percent": drawdown <= MAX_PAPER_DRAWDOWN_FRACTION,
        "no_risk_limit_violations": risk_violations == 0,
    }
    passed = all(checks.values())
    return {
        "closed_trades": int(len(pnl)), "observed_sessions": int(observed_sessions), "net_pnl_after_costs": float(pnl.sum()),
        "profit_factor": profit_factor if math.isfinite(profit_factor) else None, "max_drawdown_fraction": drawdown,
        "risk_violations": int(risk_violations), "checks": checks,
        "status": "PAPER PASS" if passed else "NOT YET", "eligible": bool(passed),
    }
