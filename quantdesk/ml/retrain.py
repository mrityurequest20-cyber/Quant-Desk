"""The retrain job (P0.8 of docs/ML_PHASE0.md): refit every registered model from its dataset, in a scratch folder, and compare with the
coefficients the desk loads. A *drill*: it reproduces committed numbers, it does not replace them.

What it will not do, by construction:
- write a committed file. The report and the refits go to an output folder that must be outside every git working tree or under that
  tree's gitignored `runtime/` folder, and a registered file is never an output path.
- use the network, a credential, or the live desk (journal, engine, risk, execution). The scheduled workflow (`.github/workflows/ml-retrain.yml`)
  has `contents: read` and no secret; this module reads files and writes into the output folder only.
- accept a wider tolerance than P0.4's: `reproduce.RTOL_MAX` (1e-6). A refit that needs more is not a reproduction.
- say a model is reproduced when its inputs were not the ones it was fitted on. The rebuilt dataset's source commit, importer and 1-minute partition
  hashes (recomputed from the Parquet files, not read from the manifest, which `X.load` does not check against the files) are compared with the ones
  recorded in the committed file's provenance and reported beside the verdict. "Reproduced" certifies repeatability, not correctness: a flaw of the fit
  itself is reproduced too, and the report says so.

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


def _spec_sha(spec: Path) -> str:
    from ..autolearn.prereg import spec_hash
    return spec_hash(Path(spec))


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
    if resolved == REPO or REPO in resolved.parents:
        if not (REPO / "runtime" == resolved or REPO / "runtime" in resolved.parents):
            raise B.ForbiddenUse(f"the retrain folder {out} is inside this repository outside its runtime/ folder")
    for name in (REPORT_NAME, *(f"{m.id}.refit.json" for m in models)):
        if (resolved / name).exists() or (resolved / name).is_symlink():
            raise RetrainRefused(f"{resolved / name} exists: a report and its refits are written once; use a new folder")
    return resolved


def _inputs(dataset: Path) -> dict:
    """What the dataset is: the manifest's identity fields, and the content hash of every 1-minute partition *recomputed from the files* (the importer's own `frame_hash`),
    beside what the manifest says. `X.load` does not check the manifest against the files, so the manifest alone would only attest itself."""
    import pandas as pd

    from ..data import external_aeron as X
    man = json.loads((Path(dataset) / "manifest.json").read_text())
    recorded = {k: v for k, v in sorted(man.get("partitions", {}).items()) if k.startswith("1m/")}
    actual, unreadable = {}, []
    for k in recorded:
        try:
            actual[k] = X.frame_hash(pd.read_parquet(Path(dataset) / k))
        except (OSError, ValueError) as exc:
            unreadable.append(f"{k}: {type(exc).__name__}")
    on_disk = sorted(str(p.relative_to(dataset)) for p in (Path(dataset) / "1m").rglob("*.parquet")) if (Path(dataset) / "1m").is_dir() else []
    return {"dataset": man.get("dataset") or Path(dataset).name, "status": man.get("status"), "source_url": man.get("source_url"),
            "source_commit": man.get("source_commit"), "importer_version": man.get("importer_version"),
            "manifest_sha256": hashlib.sha256((Path(dataset) / "manifest.json").read_bytes()).hexdigest(),
            "partitions_1m": actual, "manifest_partitions_1m": recorded, "unreadable_partitions": unreadable,
            "unlisted_partitions": sorted(set(on_disk) - set(recorded))}


def _input_findings(committed: dict, now: dict) -> list[str]:
    """How the rebuilt dataset differs from the one the committed numbers were fitted on (empty: the same source commit, importer and partitions)."""
    was = (committed.get("provenance") or {}).get("inputs") or {}
    out = []
    for k in ("source_url", "source_commit", "importer_version"):
        if was.get(k) != now.get(k):
            out.append(f"{k}: {was.get(k)!r} committed, {now.get(k)!r} rebuilt")
    if now.get("unreadable_partitions"):
        out.append(f"{len(now['unreadable_partitions'])} 1-minute partition(s) could not be read: {now['unreadable_partitions'][0]}")
    if now.get("unlisted_partitions"):
        out.append(f"{len(now['unlisted_partitions'])} 1-minute partition file(s) are not in the manifest (first: {now['unlisted_partitions'][0]})")
    if now.get("manifest_partitions_1m") != now.get("partitions_1m") and not now.get("unreadable_partitions"):
        bad = sorted(k for k in now.get("manifest_partitions_1m", {}) if now["manifest_partitions_1m"][k] != now["partitions_1m"].get(k))
        out.append(f"the manifest's hashes do not match the files for {len(bad)} partition(s) (first: {bad[0] if bad else '?'}): the dataset was changed after it was imported")
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


def _code_state() -> tuple[str | None, bool | None]:
    """(commit, whether quantdesk/ or docs/prereg had uncommitted changes), or (None, None): the same facts the committed coefficients record."""
    import subprocess
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=20).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "quantdesk", "docs/prereg"], cwd=REPO, capture_output=True, text=True, timeout=20).stdout.strip()
        return head or None, bool(dirty)
    except Exception:
        return None, None


def drill(dataset: Path, out: Path, rtol: float = RTOL, atol: float = ATOL, models: tuple[Refit, ...] | None = None, say=print) -> dict:
    """Refit every registered model from `dataset`, write each refit and the report into `out`, and return the report.
    `report["ok"]` is True only if every model's refit matches its committed file within the tolerance and the inputs were the recorded ones."""
    if not 0 <= rtol <= R.RTOL_MAX:
        raise ValueError(f"rtol {rtol:g} is outside 0 to {R.RTOL_MAX:g}: a refit that needs a wider tolerance is not a reproduction")
    if not 0 <= atol <= ATOL:                          # written so that NaN fails; P0.4 runs at exactly this absolute tolerance, so it is a cap, not a default
        raise ValueError(f"atol {atol:g} is outside 0 to {ATOL:g}")
    models = models if models is not None else registry()
    if not models:
        raise RetrainRefused("no registered model: an empty registry reproduces nothing")
    out = check_out(out, models)
    dataset = Path(dataset)
    inputs = _inputs(dataset)
    head, dirty = _code_state()
    rows = []
    for m in models:
        committed_text = m.committed.read_text()
        committed = json.loads(committed_text)
        fresh = m.fit(dataset, m.spec)
        cmp = R.compare_results({k: v for k, v in committed.items() if k != "provenance"}, {k: v for k, v in fresh.items() if k != "provenance"},
                                rtol=rtol, atol=atol, ignore=frozenset())
        if cmp.numbers == 0:
            raise RetrainRefused(f"{m.id}: no number was compared (the committed file or the refit holds none): that is not a reproduction")
        findings = _input_findings(committed, inputs)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / f"{m.id}.refit.json", "x") as fh:                                          # never follows or replaces an existing path
            fh.write(json.dumps(fresh, indent=1))
        verdict = "reproduced" if cmp.ok and not findings else ("differs" if not cmp.ok else "reproduced_on_different_inputs")
        rows.append({"id": m.id, "verdict": verdict, "committed_file": m.committed.name, "committed_sha256": hashlib.sha256(committed_text.encode()).hexdigest(),
                     "spec_sha256": _spec_sha(m.spec), "committed_numbers_sha256": _sha({k: v for k, v in committed.items() if k != "provenance"}),
                     "refit_numbers_sha256": _sha({k: v for k, v in fresh.items() if k != "provenance"}),
                     "numbers": cmp.numbers, "max_abs": cmp.max_abs, "max_rel": cmp.max_rel, "worst": cmp.worst,
                     "mismatches": cmp.mismatches[:50], "n_mismatches": len(cmp.mismatches), "input_findings": findings})
        say(f"{m.id}: {verdict.upper()} - {cmp.numbers:,} numbers, largest difference {cmp.max_abs:.3g} (relative {cmp.max_rel:.3g})"
            + "".join(f"\n  mismatch: {x}" for x in cmp.mismatches[:10]) + "".join(f"\n  inputs: {x}" for x in findings))
    report = {"schema": SCHEMA, "ok": all(r["verdict"] == "reproduced" for r in rows), "rtol": rtol, "atol": atol,
              "dataset": inputs, "note": "a drill: it reproduces the committed numbers from a rebuilt dataset and replaces nothing; "
                                         "a fresh import is external_unverified and nothing here qualifies data or a model",
              "code_commit": head, "code_has_uncommitted_changes": dirty, "versions": _versions(),
              "meaning": "repeatability, not correctness: the refit reproduces the committed numbers from the same inputs, including any flaw of the fit itself "
                         "(for example the first bars of some sessions back-filled from a later close by volstudy.grid, see docs/ML_PHASE0.md P0.3)",
              "ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "models": rows}
    with open(out / REPORT_NAME, "x") as fh:
        fh.write(json.dumps(report, indent=1))
    say(f"report {out / REPORT_NAME}: {'ALL REPRODUCED' if report['ok'] else 'NOT REPRODUCED'}")
    return report
