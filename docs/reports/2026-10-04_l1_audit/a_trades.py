"""Audit step A: rebuild v1 and v2 trades from the raw warehouse (read-only), into the scratch folder."""
import time
from pathlib import Path
from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.research import laws as L
OUT = Path(__file__).parent
W = Path("/home/user/quant-desk/runtime/warehouse")
cfg = Config.load(DEFAULT_CONFIG)
for name in ("expiry_eve_law_v1", "expiry_eve_law_v2"):
    t = time.time()
    spec = L.load_spec(Path(f"/home/user/quant-desk/docs/prereg/{name}.json"))
    syms = spec["discovery"]["instruments"] + spec["held_out"]["instruments"]
    opts = L.load(W, spec)
    tr = L.all_trades(opts, spec, syms, L.fees_factory(cfg), cfg, L.official_closes(W, spec))
    tr.to_csv(OUT / f"{name}_trades.csv.gz", index=False)
    print(name, spec["_hash"], len(tr), "trades", f"{time.time()-t:.0f}s")
