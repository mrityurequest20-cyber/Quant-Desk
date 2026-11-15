"""Validation rounds while fixing (docs/prereg/news_parse_v1.json, development): N headlines drawn with a recorded seed from the pool, never from DEV, TEST
or an earlier round (AUDIT is outside the pool); from round 5 (TWIN_RULE_FROM), never a twin of a TEST or AUDIT row either (one contains the other, after
normalising case and spacing, or to letters and digits only). A round is labelled on the guide BEFORE any parser is run on it; its labels and score are reported in the result.
TEST is computed in memory only to be excluded, never written or printed.

    python -I docs/prereg/sims/news_parse_v1/draw_val.py <sample.py> <dir of journal-archive-*.db> <seed> <out.jsonl> [earlier round .jsonl ...]
"""
from __future__ import annotations

import glob
import importlib.util
import json
import random
import re
import sys

N_VAL = 100
TWIN_RULE_FROM = 20261123          # rounds 1-4 (seeds 20261119-20261122) were drawn by exact-string exclusion only and reproduce byte for byte under it


def norms(s: str) -> tuple[str, str]:
    a = " ".join(s.lower().split())
    return a, re.sub(r"[^a-z0-9]+", "", a)


def test_rows(smp, pool):
    rng = random.Random(smp.SEED)
    pick = rng.sample(pool, smp.N_DEV + smp.N_TEST_A)
    rng.shuffle(pick)
    drawn = set(pick)
    return pick[smp.N_DEV:] + random.Random(smp.SEED_B).sample([h for h in pool if h not in drawn], smp.N_TEST_B)


def main():
    spec = importlib.util.spec_from_file_location("sample", sys.argv[1])
    smp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smp)
    seed, out, earlier = int(sys.argv[3]), sys.argv[4], sys.argv[5:]
    allh = smp.headlines(sorted(glob.glob(f"{sys.argv[2]}/journal-archive-*.db")))
    pool = [h for h in allh if smp.POOL.search(h)]
    rng = random.Random(smp.SEED)
    pick = rng.sample(pool, smp.N_DEV + smp.N_TEST_A)
    rng.shuffle(pick)
    drawn = set(pick)
    extra = random.Random(smp.SEED_B).sample([h for h in pool if h not in drawn], smp.N_TEST_B)
    excl = drawn | set(extra)
    for f in earlier:
        excl |= {json.loads(line)["title"] for line in open(f, encoding="utf-8") if line.strip()}
    cand = [h for h in pool if h not in excl]
    if seed >= TWIN_RULE_FROM:                                                  # from round 5: no twin of a TEST or AUDIT row either (one copy longer than the other)
        outside = [h for h in allh if not smp.POOL.search(h)]
        held = [norms(x) for x in test_rows(smp, pool) + random.Random(smp.SEED_AUDIT).sample(outside, smp.N_AUDIT)]
        cand = [h for h in cand if not any(a in b or b in a for x in held for a, b in zip(norms(h), x))]
    val = random.Random(seed).sample(cand, N_VAL)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps({"i": i, "title": t}, ensure_ascii=False) + "\n" for i, t in enumerate(val)))
    print(f"round seed {seed}: {len(val)} headlines from {len(cand)} candidates (excluded DEV, TEST, {len(earlier)} earlier rounds"
          f"{' and twins of TEST or AUDIT rows' if seed >= TWIN_RULE_FROM else ''})")


if __name__ == "__main__":
    main()
