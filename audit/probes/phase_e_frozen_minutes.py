"""How often do the recorded 1-minute index bars freeze (O=H=L=C unchanged across consecutive minutes) and what does
that do to the 15:00-15:29 settlement mean vs the 15:29 bar (read-only over a journal data copy)."""
import sys
from pathlib import Path
import pandas as pd
root = Path(sys.argv[1])
for day in sorted(p.name for p in root.iterdir() if p.is_dir()):
    for u in ("NIFTY", "BANKNIFTY"):
        f = root / day / f"{u}_1m.csv"
        if not f.exists():
            continue
        d = pd.read_csv(f)
        flat = (d.open == d.high) & (d.high == d.low) & (d.low == d.close)
        same = flat & (d.close == d.close.shift(1))
        run = same.groupby((~same).cumsum()).cumsum().max()
        late = d[d.ts.str[11:16].between("15:00", "15:29")]
        lf = (same & d.ts.str[11:16].between("15:00", "15:29")).sum()
        mean = late.close.mean() if len(late) else float("nan")
        last = late.close.iloc[-1] if len(late) else float("nan")
        print(f"{day} {u:9s} bars {len(d):3d} frozen-repeat {int(same.sum()):3d} longest-run {int(run):3d} "
              f"in-15:00-29 {int(lf):2d}  mean15 {mean:,.2f} last {last:,.2f} gap {(mean/last-1)*1e4:+.1f} bps")
