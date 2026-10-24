"""The retrain job (P0.8 of docs/ML_PHASE0.md): refit every registered model from its dataset, in a scratch folder, and compare with the
coefficients the desk loads. A *drill*: it reproduces committed numbers, it does not replace them.

What it will not do, by construction:
- write a committed file. The report and the refits go to an output folder that must be outside every git working tree or under that
  tree's gitignored `runtime/` folder, and a registered file is never an output path.
- use the network, a credential, or the live desk (journal, engine, risk, execution). The scheduled workflow (`.github/workflows/ml-retrain.yml`)
  has `contents: read` and no secret; this module reads files and writes into the output folder only.
- accept a wider tolerance than P0.4's: `reproduce.RTOL_MAX` (1e-6). A refit that needs more is not a reproduction.
- say a model is reproduced when its inputs were not the ones it was fitted on. The rebuilt dataset's source commit, importer and 1-minute partition
  hashes are compared with the ones recorded in the committed file's provenance and reported beside the verdict.

The dataset a scheduled run uses is freshly imported, so its status is `external_unverified`: the refit reads it anyway (the report says so). That
is right for a drill and wrong for anything else; nothing here qualifies data or a model.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import build as B
from . import reproduce as R

REPO = Path(__file__).resolve().parents[2]
SCHEMA = 1
REPORT_NAME = "retrain_report.json"
RTOL, ATOL = 1e-9, 1e-12                           # P0.4's defaults: the first drill (24 Oct 2026) differed by exactly 0
PROVENANCE = "/provenance"                         # who/when/with-what a file was written; compared field by field below, not as numbers


class RetrainRefused(RuntimeError):
    """The drill would have touched, or could be mistaken for, a committed file."""


@dataclass(frozen=True)
class Refit:
    """A registered model: where its committed numbers live, the spec that pins its training, and how to refit it from a dataset."""
    id: str
    committed: Path
    spec: Path
    fit: Callable[[Path, Path], dict]              # (dataset folder, spec file) -> coefficients in the committed file's shape


def _har(dataset: Path, spec_path: Path) -> dict:
    """C_har exactly as `autolearn vol-har-fit` makes it, minus the provenance block. The study's own `volstudy.prepare` refuses a dataset that is
    not external_verified; a drill on a fresh import has to read it unverified, so the three lines of `prepare` are repeated here (a test holds them equal)."""
    from ..autolearn import volstudy as V
    from ..autolearn.prereg import spec_hash
    from ..data import external_aeron as X
    from ..intraday.harvol import fit_coefs
    spec = json.loads(Path(spec_path).read_text())
    bars = X.load(Path(dataset), "1m", spec["symbols"], use="regime_research", allow_unverified=True)
    grids = {sym: V.grid(bars[bars["symbol"] == sym]) for sym in spec["symbols"]}
    return fit_coefs(grids, dt.date.fromisoformat(spec["dev"]["end"]), spec["name"], spec_hash(Path(spec_path)), Path(dataset).name)


def registry() -> tuple[Refit, ...]:
    from ..intraday.harvol import DEFAULT_PATH
    return (Refit("c_har", Path(DEFAULT_PATH), REPO / "docs" / "prereg" / "vol_forecast_v1.json", _har),)


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(obj) -> str:
    return hashlib.sha256(_canon(obj).encode()).hexdigest()


def check_out(out: Path, models: tuple[Refit, ...]) -> Path:
    """The output folder: outside every git working tree (or under its gitignored runtime/), never a registered file's folder, never an existing report."""
    out = Path(out)
    B.refuse_tracked_tree(out, "the retrain folder")
    resolved = out.resolve()
    for m in models:
        if m.committed.resolve().parent == resolved or m.committed.resolve() == resolved:
            raise RetrainRefused(f"{out} holds a registered model file ({m.committed.name}): the drill must not write beside what the desk loads")
    if (resolved / REPORT_NAME).exists() or (resolved / REPORT_NAME).is_symlink():
        raise RetrainRefused(f"{resolved / REPORT_NAME} exists: a report is written once; use a new folder")
    return resolved


def _inputs(dataset: Path) -> dict:
    man = json.loads((Path(dataset) / "manifest.json").read_text())
    return {"dataset": man.get("dataset") or Path(dataset).name, "status": man.get("status"), "source_url": man.get("source_url"),
            "source_commit": man.get("source_commit"), "importer_version": man.get("importer_version"),
            "partitions_1m": {k: v for k, v in sorted(man.get("partitions", {}).items()) if k.startswith("1m/")}}


def _input_findings(committed: dict, now: dict) -> list[str]:
    """How the rebuilt dataset differs from the one the committed numbers were fitted on (empty: the same source commit, importer and partitions)."""
    was = (committed.get("provenance") or {}).get("inputs") or {}
    out = []
    for k in ("source_url", "source_commit", "importer_version"):
        if was.get(k) != now.get(k):
            out.append(f"{k}: {was.get(k)!r} committed, {now.get(k)!r} rebuilt")
    a, b = was.get("partitions_1m") or {}, now.get("partitions_1m") or {}
    if not a:
        out.append("the committed file records no 1-minute partition hashes: the inputs cannot be compared")
    else:
        bad = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        if bad:
            out.append(f"{len(bad)} of {len(set(a) | set(b))} 1-minute partitions differ from the ones the committed fit read (first: {bad[0]})")
    return out


def _versions() -> dict:
    import numpy
    import pandas
    import scipy
    return {"python": platform.python_version(), "numpy": numpy.__version__, "pandas": pandas.__version__, "scipy": scipy.__version__,
            "platform": platform.platform()}


def _code_commit() -> str | None:
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=20)
        return r.stdout.strip() or None
    except Exception:
        return None


def drill(dataset: Path, out: Path, rtol: float = RTOL, atol: float = ATOL, models: tuple[Refit, ...] | None = None, say=print) -> dict:
    """Refit every registered model from `dataset`, write each refit and the report into `out`, and return the report.
    `report["ok"]` is True only if every model's refit matches its committed file within the tolerance and the inputs were the recorded ones."""
    if not 0 <= rtol <= R.RTOL_MAX:
        raise ValueError(f"rtol {rtol:g} is outside 0 to {R.RTOL_MAX:g}: a refit that needs a wider tolerance is not a reproduction")
    if atol < 0 or atol > 1e-9:
        raise ValueError(f"atol {atol:g} is outside 0 to 1e-9")
    models = models if models is not None else registry()
    out = check_out(out, models)
    dataset = Path(dataset)
    inputs = _inputs(dataset)
    rows = []
    for m in models:
        committed_text = m.committed.read_text()
        committed = json.loads(committed_text)
        fresh = m.fit(dataset, m.spec)
        cmp = R.compare_results({k: v for k, v in committed.items() if k != "provenance"}, {k: v for k, v in fresh.items() if k != "provenance"},
                                rtol=rtol, atol=atol, ignore=frozenset())
        findings = _input_findings(committed, inputs)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{m.id}.refit.json").write_text(json.dumps(fresh, indent=1))
        verdict = "reproduced" if cmp.ok and not findings else ("differs" if not cmp.ok else "reproduced_on_different_inputs")
        rows.append({"id": m.id, "verdict": verdict, "committed_file": m.committed.name, "committed_sha256": hashlib.sha256(committed_text.encode()).hexdigest(),
                     "committed_numbers_sha256": _sha({k: v for k, v in committed.items() if k != "provenance"}),
                     "refit_numbers_sha256": _sha({k: v for k, v in fresh.items() if k != "provenance"}),
                     "numbers": cmp.numbers, "max_abs": cmp.max_abs, "max_rel": cmp.max_rel, "worst": cmp.worst,
                     "mismatches": cmp.mismatches[:50], "n_mismatches": len(cmp.mismatches), "input_findings": findings})
        say(f"{m.id}: {verdict.upper()} - {cmp.numbers:,} numbers, largest difference {cmp.max_abs:.3g} (relative {cmp.max_rel:.3g})"
            + "".join(f"\n  mismatch: {x}" for x in cmp.mismatches[:10]) + "".join(f"\n  inputs: {x}" for x in findings))
    report = {"schema": SCHEMA, "ok": all(r["verdict"] == "reproduced" for r in rows), "rtol": rtol, "atol": atol,
              "dataset": inputs, "note": "a drill: it reproduces the committed numbers from a rebuilt dataset and replaces nothing; "
                                         "a fresh import is external_unverified and nothing here qualifies data or a model",
              "code_commit": _code_commit(), "versions": _versions(),
              "ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "models": rows}
    (out / REPORT_NAME).write_text(json.dumps(report, indent=1))
    say(f"report {out / REPORT_NAME}: {'ALL REPRODUCED' if report['ok'] else 'NOT REPRODUCED'}")
    return report
