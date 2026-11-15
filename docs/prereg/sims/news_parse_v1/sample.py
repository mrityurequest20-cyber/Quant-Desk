"""The headline sets of docs/prereg/news_parse_v1.json: 300 real headlines from the desk's own journal archives, drawn before the parser is changed.

The pool is every distinct headline in the archives' `news` table that names a subject the news model reads, by the model's own subject words OR by a wider list of
plain words for the same things (oil, dollar, yields, interest rates, bullion ...), so that headlines the current parser misses are drawn too: a sample of only what
the parser already catches would hide its blind spots. 300 are drawn with a fixed seed, shuffled, and split: the first 200 are DEV (the parser is fixed against them),
the last 100 are the first half of TEST; a second draw (SEED_B) of 100 more from the rest of the pool is its second half (TEST: 200). A third draw (SEED_AUDIT)
of 50 from the headlines OUTSIDE the pool is the audit set (descriptive: what the pool's word lists miss).

TEST and the audit set are not written, and not read, until the parser is frozen: without --test only dev.jsonl is written, and the other two sets are hashed
in memory (their SHA-256 is registered in the spec; regenerating them after the freeze must reproduce it).

    python -I docs/prereg/sims/news_parse_v1/sample.py <dir of journal-archive-*.db> <out dir> [--test]
Prints counts and the SHA-256 of each archive and of each set; never a test or audit headline.
"""
from __future__ import annotations

import glob
import hashlib
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

SEED, SEED_B, SEED_AUDIT = 20261115, 20261116, 20261117
N_DEV, N_TEST_A, N_TEST_B, N_AUDIT = 200, 100, 100, 50
WIDER = (r"crude|brent|wti|oil|opec|natural gas|lng|gold|bullion|yellow metal|silver|copper|aluminium|aluminum|zinc|metals?|rupee|inr|₹|dollar|dxy|greenback|"
         r"yields?|treasur(?:y|ies)|bonds?|fed|fomc|federal reserve|powell|rbi|repo|mpc|reserve bank|interest rates?|rate (?:cut|hike)s?|inflation|cpi|wpi|"
         r"prices?|gdp|pmi|iip|growth|economy|payrolls|jobs|fiis?|fpis?|foreign (?:investors?|funds?|portfolio)|war|missiles?|strikes?|military|attack|invasion|"
         r"troops|border|ceasefire|truce|peace|sanctions?|tariffs?|trade (?:war|deal|talks)|duty|export|import|china|chinese|beijing|wall street|s&p|nasdaq|dow|"
         r"us (?:stocks|markets?)|monsoon|rain\w*|kharif|it services|deal wins?|h-1b|visa|outsourcing|auto sales|vehicle sales|car sales|two-wheeler|"
         r"usfda|fda|telecom|tariff|arpu|spectrum|f&o|derivatives?|sebi|expiry|fintech|paytm|upi|payments? bank|bad loans|npas?|asset quality|defaults?|"
         r"capex|infrastructure|defence|railway|power projects?|order book|smartphones?|electronics|pli|cigarettes?|tobacco")
POOL = re.compile(rf"\b(?:{WIDER})\b", re.IGNORECASE)


def headlines(paths: list[str]) -> list[str]:
    seen, out = set(), []
    for p in sorted(paths):
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        for (title,) in db.execute("SELECT title FROM news WHERE title IS NOT NULL ORDER BY ts, id"):
            t = " ".join(str(title).split())
            k = t.lower()
            if t and k not in seen:
                seen.add(k)
                out.append(t)
        db.close()
    return out


def sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def jsonl(rows: list[str]) -> bytes:
    return "".join(json.dumps({"i": i, "title": t}, ensure_ascii=False) + "\n" for i, t in enumerate(rows)).encode("utf-8")


def main():
    src, out = sys.argv[1], Path(sys.argv[2])
    paths = sorted(glob.glob(f"{src}/journal-archive-*.db"))
    for p in paths:
        print(f"archive {Path(p).name}: sha256 {sha(p)}")
    allh = headlines(paths)
    pool = [h for h in allh if POOL.search(h)]
    rng = random.Random(SEED)
    pick = rng.sample(pool, N_DEV + N_TEST_A)
    rng.shuffle(pick)
    dev, test = pick[:N_DEV], pick[N_DEV:]
    drawn = set(pick)
    rest = [h for h in pool if h not in drawn]
    rng_b = random.Random(SEED_B)
    extra = rng_b.sample(rest, N_TEST_B)
    rng_b.shuffle(extra)
    test = test + extra
    outside = [h for h in allh if not POOL.search(h)]
    rng_a = random.Random(SEED_AUDIT)
    audit = rng_a.sample(outside, N_AUDIT)
    out.mkdir(parents=True, exist_ok=True)
    write_all = "--test" in sys.argv[3:]
    for name, rows in (("dev", dev), ("test", test), ("audit", audit)):
        data = jsonl(rows)
        if name == "dev" or write_all:
            (out / f"{name}.jsonl").write_bytes(data)
        print(f"{name}: {len(rows)} headlines, sha256 {hashlib.sha256(data).hexdigest()}{'' if name == 'dev' or write_all else ' (hashed in memory, not written)'}")
    print(f"test first half (the original draw): sha256 {hashlib.sha256(jsonl(test[:N_TEST_A])).hexdigest()}")
    print(f"distinct headlines {len(allh)}, in the pool {len(pool)}, outside it {len(outside)}, seeds {SEED} {SEED_B} {SEED_AUDIT}; python {sys.version.split()[0]}")


if __name__ == "__main__":
    main()
