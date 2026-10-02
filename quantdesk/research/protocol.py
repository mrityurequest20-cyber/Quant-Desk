"""Research lock, immutable experiment ledger, and paper promotion gates.

The recurring chronological split is development validation. It is inspected every run and
must never be described or used as an untouched final test. The final window is fixed in
advance; ordinary research excludes it permanently.
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

FINAL_TEST_START = pd.Timestamp("2026-10-05")
FINAL_TEST_END = pd.Timestamp("2027-03-31 23:59:59")
MIN_PAPER_SESSIONS = 60
MIN_PAPER_TRADES = 30
MIN_PAPER_PROFIT_FACTOR = 1.15
MAX_PAPER_DRAWDOWN_FRACTION = 0.10


def development_sample(x: pd.Series) -> pd.Series:
    """Remove the pre-registered final period and all later dates from routine research."""
    if not isinstance(x.index, pd.DatetimeIndex):
        return x.copy()
    dates = x.index.tz_localize(None) if x.index.tz is not None else x.index
    return x.loc[dates < FINAL_TEST_START]


def development_data(data: dict) -> dict:
    """Copy routine research inputs with every final-period/future row removed."""
    out = dict(data)
    for family in ("daily", "hourly", "m5"):
        frames = {}
        for symbol, frame in (data.get(family) or {}).items():
            if isinstance(frame.index, pd.DatetimeIndex):
                dates = frame.index.tz_localize(None) if frame.index.tz is not None else frame.index
                frames[symbol] = frame.loc[dates < FINAL_TEST_START].copy()
            else:
                frames[symbol] = frame.copy()
        if family in data:
            out[family] = frames
    glob = data.get("global") or {}
    locked_glob = dict(glob)
    for family in ("daily", "m5"):
        frames = {}
        for symbol, frame in (glob.get(family) or {}).items():
            if isinstance(frame.index, pd.DatetimeIndex):
                dates = frame.index.tz_localize(None) if frame.index.tz is not None else frame.index
                frames[symbol] = frame.loc[dates < FINAL_TEST_START].copy()
            else:
                frames[symbol] = frame.copy()
        if family in glob:
            locked_glob[family] = frames
    if "global" in data:
        out["global"] = locked_glob
    return out


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


def paper_strategy_fingerprint() -> str:
    """Fingerprint the paper engine, strategy code, and settings used by the locked trial."""
    root = Path(__file__).resolve().parents[2]
    files = sorted((root / "quantdesk" / "intraday").rglob("*.py"))
    files += [root / "config" / "quantdesk.yaml"]
    h = hashlib.sha256()
    for path in files:
        if path.is_file():
            h.update(path.relative_to(root).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def register_locked_candidate(path: str | Path, *, strategy: str, account: str, since: str,
                              preperiod_gate: dict, ledger: str | Path | None = None, today=None) -> dict:
    """Create a pre-window, exclusive manifest after the separate paper gate passes."""
    today = pd.Timestamp(today or pd.Timestamp.now().date()).normalize()
    since_date = pd.Timestamp(since).normalize()
    if account == "live" or not account or not strategy:
        raise ValueError("locked tests require a named, isolated paper account and strategy")
    if today >= FINAL_TEST_START:
        raise ValueError("candidate registration is sealed once the locked period starts")
    if since_date >= FINAL_TEST_START or since_date > today:
        raise ValueError("pre-period must start on or before today and before the locked period")
    if not preperiod_gate.get("eligible_for_paper_trial", False):
        raise ValueError("candidate has not passed the required cost-inclusive pre-period paper gate")
    manifest = {
        "schema": 1, "status": "registered", "strategy": strategy, "account": account,
        "preperiod_start": since_date.date().isoformat(),
        "final_start": FINAL_TEST_START.date().isoformat(),
        "final_end": FINAL_TEST_END.date().isoformat(),
        "registered_on": today.date().isoformat(),
        "preperiod_gate": _json_safe(preperiod_gate),
        "paper_strategy_sha256": paper_strategy_fingerprint(),
    }
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    manifest["manifest_sha256"] = _sha256(canonical)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("a locked candidate manifest already exists and cannot be replaced") from exc
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    if ledger is not None:
        _append(ledger, {"event": "locked_paper_test_registered", "strategy": strategy,
                         "account": account, "manifest_sha256": manifest["manifest_sha256"],
                         "registered_on": manifest["registered_on"],
                         "final_start": manifest["final_start"], "final_end": manifest["final_end"]})
    return manifest


def record_locked_final_result(ledger: str | Path, manifest: dict, final_gate: dict, *, today=None) -> dict:
    """Record one completed locked result; duplicate attempts fail closed."""
    today = pd.Timestamp(today or pd.Timestamp.now().date()).normalize()
    if today <= FINAL_TEST_END.normalize():
        raise ValueError("the locked final period has not ended")
    if manifest.get("status") != "registered":
        raise ValueError("manifest is not an active registered candidate")
    if manifest.get("paper_strategy_sha256") != paper_strategy_fingerprint():
        raise ValueError("paper strategy or configuration changed after candidate registration")
    if manifest.get("final_start") != FINAL_TEST_START.date().isoformat() or manifest.get("final_end") != FINAL_TEST_END.date().isoformat():
        raise ValueError("manifest final window does not match the sealed dates")
    path = Path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest_check = dict(manifest)
    expected_manifest_hash = manifest_check.pop("manifest_sha256", None)
    actual_manifest_hash = _sha256(json.dumps(manifest_check, ensure_ascii=False, sort_keys=True,
                                              allow_nan=False).encode())
    if not expected_manifest_hash or expected_manifest_hash != actual_manifest_hash:
        raise ValueError("locked candidate manifest integrity check failed")
    lock = path.with_name(path.name + ".locked-test.lock")
    try:
        lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("locked final evaluation is already running or stopped; inspect the lock and ledger") from exc
    try:
        registered = False
        if path.exists():
            identity = (manifest.get("strategy"), manifest.get("account"))
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (row.get("event") == "locked_paper_test_registered" and
                        (row.get("strategy"), row.get("account")) == identity and
                        row.get("manifest_sha256") == expected_manifest_hash):
                    registered = True
                if row.get("event") == "locked_paper_test_completed" and (row.get("strategy"), row.get("account")) == identity:
                    raise ValueError("a locked final result is already recorded for this candidate and account")
        if not registered:
            raise ValueError("candidate registration is missing from the experiment ledger")
        record = {
            "event": "locked_paper_test_completed", "strategy": manifest["strategy"],
            "account": manifest["account"], "final_start": manifest["final_start"],
            "final_end": manifest["final_end"], "registered_on": manifest["registered_on"],
            "paper_strategy_sha256": manifest["paper_strategy_sha256"],
            "final_gate": _json_safe(final_gate), "promotion_allowed": False,
            "result": "PASS; promotion review required" if final_gate.get("locked_final_test_passed") else "FAIL",
        }
        _append(path, record)
        return record
    finally:
        os.close(lock_fd)


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
        "locked_final_period": {"start": FINAL_TEST_START.date().isoformat(),
                                "end": FINAL_TEST_END.date().isoformat(),
                                "status": "sealed; excluded from routine research"},
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
        "locked_final_period": {"start": FINAL_TEST_START.date().isoformat(), "end": FINAL_TEST_END.date().isoformat(),
                                "status": "sealed; excluded from routine research"},
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
        "locked_final_period": {"start": FINAL_TEST_START.date().isoformat(),
                                "end": FINAL_TEST_END.date().isoformat(),
                                "status": "sealed; excluded from routine research"},
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
                             capital: float, final_test_passed: bool = False) -> dict:
    """Fail-closed release check for net, cost-inclusive paper trades of one candidate strategy."""
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
        "locked_final_test_passed": final_test_passed,
    }
    paper_only_pass = all(v for k, v in checks.items() if k != "locked_final_test_passed")
    return {
        "closed_trades": int(len(pnl)), "observed_sessions": int(observed_sessions), "net_pnl_after_costs": float(pnl.sum()),
        "profit_factor": profit_factor if math.isfinite(profit_factor) else None, "max_drawdown_fraction": drawdown,
        "risk_violations": int(risk_violations), "checks": checks,
        "status": "ELIGIBLE FOR PROMOTION REVIEW" if paper_only_pass and final_test_passed else
                  "PAPER PASS; FINAL TEST REQUIRED" if paper_only_pass else "NOT ELIGIBLE",
        "eligible_for_paper_trial": bool(paper_only_pass),
        "eligible": bool(paper_only_pass and final_test_passed),
    }
