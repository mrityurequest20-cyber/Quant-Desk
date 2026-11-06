"""`quantdesk autolearn vol-har-fit`: the one command kept from the retired learning loop (6 Nov 2026).

It fits vol_forecast_v1's HAR coefficients (quantdesk/intraday/vol_har_v1.json), whose provenance names this exact
command; ml retrain's drill refits through it. The cycle, research, prereg, status and recovery commands went with
the loop (branch archive/pre-cleanup-2026-11-06).
"""
from __future__ import annotations

import json
import sys


def register(sub):
    s = sub.add_parser("autolearn", help="vol-har-fit: fit vol_forecast_v1's HAR coefficients (the rest of the learning loop was retired)")
    ss = s.add_subparsers(dest="acmd", required=True)
    x = ss.add_parser("vol-har-fit", help="fit vol_forecast_v1's C_har on the external minutes (the spec's training window) and "
                                          "store the coefficients the desk's HAR volatility forecast reads")
    x.add_argument("--out", help="external data root (default runtime/external)")
    x.add_argument("--spec", default="docs/prereg/vol_forecast_v1.json")
    x.add_argument("--to", help="coefficients file (default: the committed quantdesk/intraday/vol_har_v1.json)")
    x.add_argument("--asset-sha256", help="sha256 of the dataset archive the folder came from (recorded in the provenance)")
    x.set_defaults(fn=cmd_vol_har_fit)
    return s


def cmd_vol_har_fit(cfg, a):
    import datetime as dt
    from pathlib import Path

    from ..data import external_aeron as X
    from ..intraday.harvol import DEFAULT_PATH, fit_coefs, provenance, save_coefs
    from . import volstudy
    from .prereg import spec_hash
    ds = X.latest(Path(a.out) if a.out else Path(cfg.runtime_dir) / "external")
    if ds is None:
        sys.exit("no imported external dataset: run `data external-import` first")
    spec = json.loads(Path(a.spec).read_text())
    grids = volstudy.prepare(ds, spec["symbols"])
    dev_end = dt.date.fromisoformat(spec["dev"]["end"])
    sha = spec_hash(Path(a.spec))
    prov = provenance(spec, sha, a.spec, ds, grids, dev_end, a.asset_sha256, sys.argv[1:])
    coefs = fit_coefs(grids, dev_end, spec["name"], sha, ds.name, provenance=prov)
    to = Path(a.to) if a.to else DEFAULT_PATH
    save_coefs(to, coefs)
    print(f"{to}: " + ", ".join(f"{s} {e['sessions']} sessions to {e['trained_through']}" for s, e in coefs["symbols"].items()))
