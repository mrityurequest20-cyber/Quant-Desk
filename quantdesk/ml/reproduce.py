"""Reproduce a pre-registered study from its spec and its data, and compare with the result that was committed (P0.4 of docs/ML_PHASE0.md).

The exit test of P0.4 is that the harness reproduces the locked HAR result (`docs/prereg/results/vol_forecast_v1-*.json`: 8 of 8 cells) within
a stated tolerance. This is a *reproduction*, not a re-evaluation: it selects nothing, opens no lock, and writes nothing under `docs/`.

- The study is rerun by its own code (`autolearn/volstudy.run`) into a scratch folder. The lock of a spent spec is refused in the repo's
  results folder ("never again"), so the rerun is allowed only where it cannot overwrite or replace a committed result: the scratch
  folder must be **outside the repository altogether** (a result-lookalike with a spent lock must never sit in a tracked tree), after
  resolving symlinks and `..`; the output name is the one `volstudy.run` will use (the spec's name and hash), whatever the committed
  file is called; and that file must not exist, not even as a symlink.
- Every number in the two result files is compared, field by field, with a relative tolerance (default 1e-9; the margin measured on the
  first reproduction, 24 Oct 2026, was exactly 0 on 1,132 numbers, and a different CPU or numpy build may differ in the last bits). The
  tolerance may not be widened past `RTOL_MAX` (1e-6): a reproduction that needs more is not a reproduction.
  Strings, booleans, structure and the pass/fail verdict of every cell must match exactly. Only one field is ignored, by exact path:
  the time the lock was opened (the committed result holds no file path).
- The spec's own hash is checked against the committed result's `spec_sha256`: a spec edited after its result fails here.
"""
from __future__ import annotations

import json
import math
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROTECTED = REPO / "docs" / "prereg" / "results"
IGNORED = frozenset({"/lock/opened"})                          # the one field that differs by construction; nothing else, at no other depth
RTOL_MAX = 1e-6


class ReproductionRefused(RuntimeError):
    """The rerun would have touched (or could be mistaken for) a committed result."""


@dataclass
class Comparison:
    numbers: int = 0
    max_abs: float = 0.0
    max_rel: float = 0.0
    worst: str = ""
    mismatches: list[str] = field(default_factory=list)          # structure, strings, booleans, and numbers beyond the tolerance
    rtol: float = 1e-9
    notes: list[str] = field(default_factory=list)                  # facts about the run a reader should see beside the verdict

    @property
    def ok(self) -> bool:
        return not self.mismatches


def compare_results(committed, fresh, rtol: float = 1e-9, atol: float = 1e-12, ignore=IGNORED) -> Comparison:
    """Walk two decoded result files together. Numbers match within `atol + rtol * max(|a|, |b|)`; everything else must be identical.
    `ignore`: exact paths ("/lock/opened") that are skipped."""
    out = Comparison(rtol=rtol)

    def num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    def walk(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in a:
                if f"{path}/{k}" in ignore:
                    continue
                if k not in b:
                    out.mismatches.append(f"{path}/{k}: missing from the reproduction")
                    continue
                walk(a[k], b[k], f"{path}/{k}")
            for k in b:
                if k not in a and f"{path}/{k}" not in ignore:
                    out.mismatches.append(f"{path}/{k}: not in the committed result")
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                out.mismatches.append(f"{path}: {len(a)} items committed, {len(b)} reproduced")
                return
            for i, (p, q) in enumerate(zip(a, b)):
                walk(p, q, f"{path}[{i}]")
        elif num(a) and num(b):
            out.numbers += 1
            if math.isnan(a) or math.isnan(b) or math.isinf(a) or math.isinf(b):          # a NaN or an infinity matches only itself
                if not (a == b or (math.isnan(a) and math.isnan(b))):
                    out.mismatches.append(f"{path}: {a!r} committed, {b!r} reproduced")
                return
            d = abs(a - b)
            rel = d / max(abs(a), abs(b), 1e-300)
            if d > out.max_abs or (d == out.max_abs and rel > out.max_rel):
                out.max_abs, out.max_rel, out.worst = d, rel, path
            if d > atol + rtol * max(abs(a), abs(b)):
                out.mismatches.append(f"{path}: {a!r} committed, {b!r} reproduced (difference {d:.3g})")
        elif type(a) is not type(b) or a != b:
            out.mismatches.append(f"{path}: {a!r} committed, {b!r} reproduced")

    walk(committed, fresh, "")
    return out


def reproduce(dataset: Path, spec_path: Path, committed_path: Path, results_dir: Path | None = None, rtol: float = 1e-9, say=print) -> Comparison:
    """Rerun `volstudy.run` (with its lock, in a scratch folder outside the repository) and compare with the committed result. Never writes
    to the repo."""
    from ..autolearn import volstudy as V
    from ..autolearn.prereg import spec_hash

    if not 0 <= rtol <= RTOL_MAX:
        raise ValueError(f"rtol {rtol:g} is outside 0 to {RTOL_MAX:g}: a reproduction that needs a wider tolerance is not a reproduction")
    spec_path, committed_path = Path(spec_path), Path(committed_path)
    committed = json.loads(committed_path.read_text())
    h = spec_hash(spec_path)
    if h != committed.get("spec_sha256"):
        raise ReproductionRefused(f"{spec_path.name} no longer hashes to the spec the result was produced from "
                                  f"({h[:12]} ≠ {str(committed.get('spec_sha256'))[:12]}): a spec edited after its result")
    if not committed.get("lock"):
        raise ReproductionRefused(f"{committed_path.name} has no opened lock to reproduce")
    scratch = Path(results_dir) if results_dir else Path(tempfile.mkdtemp(prefix="reproduce-"))
    resolved = scratch.resolve()
    if REPO in (resolved, *resolved.parents):
        raise ReproductionRefused(f"{scratch} is inside the repository ({REPO}): a reproduction carries a spent lock and must be written "
                                  "outside any tracked tree, never beside the committed results")
    try:
        name = f"{json.loads(spec_path.read_text())['name']}-{h[:12]}.json"             # the file volstudy.run will write
    except (KeyError, TypeError) as exc:
        raise ReproductionRefused(f"{spec_path.name} has no name") from exc
    out_file = scratch / name
    if out_file.is_symlink() or out_file.exists():
        raise ReproductionRefused(f"{out_file} already exists: use an empty folder so a stale file is not mistaken for a reproduction")
    if out_file.resolve() == committed_path.resolve():
        raise ReproductionRefused("the reproduction would overwrite the committed result")
    rep = V.run(None, Path(dataset), spec_path, scratch, open_lock=True, say=say)
    return compare_results(committed, json.loads(Path(rep["path"]).read_text()), rtol=rtol)


def provenance_line(dataset: Path) -> str:
    """What a reproduction ran on: the dataset (its name and manifest digest when it has one) and the library versions that can move a last bit."""
    import platform
    import numpy
    import pandas
    import scipy
    digest = ""
    try:
        man = json.loads((Path(dataset) / "manifest.json").read_text())
        digest = f", manifest digest {str(man.get('digest') or man.get('sha256') or 'none recorded')[:16]}"
    except (OSError, ValueError):
        digest = ", no readable manifest"
    return (f"ran on dataset {Path(dataset).name}{digest}; python {platform.python_version()}, numpy {numpy.__version__}, "
            f"pandas {pandas.__version__}, scipy {scipy.__version__}")


def render(cmp: Comparison, committed: dict) -> str:
    cells = committed.get("lock", {}).get("tests", {})
    L = [f"Reproduction of {committed.get('spec')} (spec {str(committed.get('spec_sha256'))[:12]}): "
         f"{'MATCHES' if cmp.ok else 'DOES NOT MATCH'}",
         f"{cmp.numbers:,} numbers compared; largest absolute difference {cmp.max_abs:.3g} (relative {cmp.max_rel:.3g}) at {cmp.worst or '-'}; "
         f"tolerance {cmp.rtol:g}" + (" (WIDER than the default 1e-9)." if cmp.rtol > 1e-9 else "."),
         f"{len(cells)} locked cells: " + (", ".join(f"{k} {v['selected']} t {v.get('dm_t', float('nan')):+.2f}" for k, v in cells.items()) or "none")]
    L += [f"  note: {n}" for n in cmp.notes]
    L += [f"  mismatch: {m}" for m in cmp.mismatches[:20]]
    if len(cmp.mismatches) > 20:
        L.append(f"  ... and {len(cmp.mismatches) - 20} more")
    return "\n".join(L)
