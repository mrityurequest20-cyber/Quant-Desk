"""Provenance for a recorded result: which code and which data produced it.

A result in docs/prereg/results says what was found. This says what it was found *with*: the git commit (and whether
the working tree had uncommitted changes) and a digest of every data file the study read, so anyone can tell whether
two runs saw the same inputs. Results recorded before 4 Oct 2026 carry none; the L1 evidence audit
(docs/reports/2026-10-04_l1_evidence_audit.md) recorded the digests for those it reproduced.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def code_commit(root: Path = ROOT) -> dict:
    def git(*args):
        try:
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:
            return ""
    head = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    return {"commit": head[:12] or None, "dirty": dirty}


def data_digest(folder: Path, patterns) -> dict:
    """{pattern: {"files": n, "digest": first 16 hex of sha256 over (name, sha256(bytes)) of each file, sorted}}."""
    out = {}
    for pat in patterns:
        files = sorted(Path(folder).glob(pat))
        h = hashlib.sha256()
        for f in files:
            h.update(f.name.encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
        out[pat] = {"files": len(files), "digest": h.hexdigest()[:16] if files else None}
    return out


def stamp(folder: Path, patterns) -> dict:
    return {"code": code_commit(), "data": data_digest(folder, patterns),
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


WAREHOUSE_TABLES = ("fo_bhav_*.parquet", "bse_fo_bhav_*.parquet", "nse_index_close_*.parquet")
