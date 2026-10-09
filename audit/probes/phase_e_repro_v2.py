"""Reproduce expiry_eve_law_v2 from a warehouse folder, restricted to the registered sample (expiry <= cutoff)."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
REPO = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(REPO))
from quantdesk.config import Config, DEFAULT_CONFIG
from quantdesk.research import laws as L
wh, cutoff = Path(sys.argv[1]), pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2026-10-01")
spec = L.load_spec(REPO / "docs/prereg/expiry_eve_law_v2.json")
cfg = Config.load(DEFAULT_CONFIG)
res_all, tr = L.run(wh, cfg, spec)
reg = json.load(open(REPO / "docs/prereg/results/expiry_eve_law_v2-a3ff6d83a18e.json"))
cut = tr[pd.to_datetime(tr["expiry"]) <= cutoff]
res = L.evaluate(cut, spec)
out = {}
for k in res["structures"]:
    a, b = res["structures"][k], reg["structures"][k]
    out[k] = {"pooled_now": a["pooled"], "pooled_reg": b["pooled"], "replicated_now": a["replicated"],
              "rows": {s: (a["rows"][s]["n"], b["rows"].get(s, {}).get("n"), round(a["rows"][s]["mean_bps"] - b["rows"].get(s, {}).get("mean_bps", np.nan), 6))
                       for s in a["rows"]}}
    pa = res_all["structures"][k]["pooled"]
    out[k]["pooled_all_data_today"] = pa
print(json.dumps(out, indent=1, default=str))
cut.to_csv(Path(sys.argv[3]) if len(sys.argv) > 3 else "/dev/null", index=False)
