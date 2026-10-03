"""Durable files for the learning loop: an append-only, hash-chained JSONL log and atomic JSON writes.

Every line of a log carries `seq`, `prev` (the previous line's hash) and `hash` (SHA-256 of the canonical record
without `hash`). Appends are O_APPEND + fsync, so a crash leaves at most one torn last line; `recover()` moves that
line to a .corrupt file (never deletes it) and the chain verifies again. Nothing here rewrites a written line.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path


def canon(obj) -> str:
    return json.dumps(_safe(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(obj) -> str:
    return hashlib.sha256((obj if isinstance(obj, str) else canon(obj)).encode()).hexdigest()


def _safe(v):
    if isinstance(v, dict):
        return {str(k): _safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_safe(x) for x in v]
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        return _safe(v.item())
    if v is None or isinstance(v, (str, int, bool, float)):
        return v
    return str(v)


def write_json(path: Path, obj) -> None:
    """Atomic: write a temp file, fsync, rename over the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(_safe(obj), ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return f.read().splitlines()


class ChainLog:
    """One append-only log file (or its gzipped, closed form)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._tail: tuple[int, str] | None = None

    def _last(self) -> tuple[int, str]:
        if self._tail is None:
            seq, prev = 0, ""
            for ln in _lines(self.path):
                try:
                    r = json.loads(ln)
                    seq, prev = int(r["seq"]), r["hash"]
                except (ValueError, KeyError, TypeError):
                    raise LogCorrupt(f"{self.path.name}: unreadable line after seq {seq}; run `autolearn recover`")
            self._tail = (seq, prev)
        return self._tail

    def append(self, record: dict) -> dict:
        if self.path.suffix == ".gz":
            raise LogCorrupt(f"{self.path.name} is closed (compressed); it can't be appended to")
        seq, prev = self._last()
        rec = {**_safe(record), "seq": seq + 1, "prev": prev}
        rec["hash"] = sha(rec)
        line = (canon(rec) + "\n").encode()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._tail = (rec["seq"], rec["hash"])
        return rec

    def read(self) -> list[dict]:
        out = []
        for ln in _lines(self.path):
            out.append(json.loads(ln))
        return out

    def verify(self) -> list[str]:
        """Problems with the chain (empty: intact)."""
        bad, prev, seq = [], "", 0
        for i, ln in enumerate(_lines(self.path), 1):
            try:
                r = json.loads(ln)
            except ValueError:
                bad.append(f"{self.path.name}:{i}: not JSON (torn write?)")
                continue
            h = r.pop("hash", None)
            if r.get("seq") != seq + 1:
                bad.append(f"{self.path.name}:{i}: seq {r.get('seq')} after {seq}")
            if r.get("prev") != prev:
                bad.append(f"{self.path.name}:{i}: chain broken (prev hash mismatch)")
            if h != sha(r):
                bad.append(f"{self.path.name}:{i}: record altered (hash mismatch)")
            seq, prev = int(r.get("seq") or seq + 1), h or ""
        return bad

    def recover(self) -> int:
        """Move unreadable trailing lines (a torn write) to <file>.corrupt; returns how many were moved. A broken line in
        the middle is not touched: that needs a person (`verify` reports it)."""
        if self.path.suffix == ".gz" or not self.path.exists():
            return 0
        raw = self.path.read_bytes()
        lines = raw.decode("utf-8", "replace").split("\n")
        keep = len(lines)
        while keep and (not lines[keep - 1].strip() or not _json_ok(lines[keep - 1])):
            keep -= 1
        torn = [ln for ln in lines[keep:] if ln.strip()]
        if not torn:
            return 0
        with open(self.path.with_suffix(self.path.suffix + ".corrupt"), "a", encoding="utf-8") as f:
            f.write("\n".join(torn) + "\n")
        good = "\n".join(lines[:keep]) + ("\n" if keep else "")
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(good, encoding="utf-8")
        os.replace(tmp, self.path)
        self._tail = None
        return len(torn)

    def close(self) -> Path:
        """Compress a finished log (its chain verifies the same)."""
        if self.path.suffix == ".gz" or not self.path.exists():
            return self.path
        gz = self.path.with_suffix(self.path.suffix + ".gz")
        with open(self.path, "rb") as src, gzip.open(gz, "wb") as dst:
            dst.write(src.read())
        os.remove(self.path)
        return gz


def _json_ok(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except ValueError:
        return False


class LogCorrupt(RuntimeError):
    pass
