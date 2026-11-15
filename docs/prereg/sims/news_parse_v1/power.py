"""Operating characteristic of P's bar (docs/prereg/news_parse_v1.json, P_test): the chance that the observed TEST accuracy is at least 0.90, by the parser's
true accuracy. TEST has 200 headlines; the number of scored pairs per headline is drawn from DEV's labels (130 nonzero pairs on 200 headlines, plus a false
reading on 5% of headlines: about 140 pairs, the size a near-0.90 parser gives). Within a headline, pairs are right together with correlation RHO (one misread
clause often costs two pairs), so the headline is the unit.

    python -I docs/prereg/sims/news_parse_v1/power.py tests/fixtures/news_parse_v1/dev_labels.json
"""
from __future__ import annotations

import json
import random
import sys

N_TEST, BAR, SIMS, SEED, RHO, FALSE_READ = 200, 0.90, 20_000, 20261115, 0.3, 0.05


def main():
    rows = json.load(open(sys.argv[1], encoding="utf-8"))
    counts = [sum(1 for v in r["labels"].values() if int(v) != 0) for r in rows]
    rng = random.Random(SEED)
    print(f"DEV: {len(rows)} headlines, {sum(counts)} nonzero label pairs; simulated TEST: {N_TEST} headlines, about "
          f"{N_TEST * (sum(counts) / len(rows) + FALSE_READ):.0f} pairs")
    print("true accuracy  P(observed >= 0.90)  [independent pairs | pairs correlated within a headline, rho 0.3]")
    for p in (0.80, 0.85, 0.88, 0.90, 0.92, 0.95):
        out = []
        for rho in (0.0, RHO):
            ok = 0
            for _ in range(SIMS):
                right = tot = 0
                for _ in range(N_TEST):
                    k = rng.choice(counts) + (rng.random() < FALSE_READ)
                    if not k:
                        continue
                    common = rng.random() < p                                    # a headline-level draw shared with probability rho
                    for _ in range(k):
                        right += common if rng.random() < rho else (rng.random() < p)
                    tot += k
                ok += right / tot >= BAR
            out.append(ok / SIMS)
        print(f"  {p:.2f}          {out[0]:.3f} | {out[1]:.3f}")


if __name__ == "__main__":
    main()
