"""Which TEST rows were exposed before the freeze (docs/prereg/news_parse_v1.json, P_test.exposure_rule). Run at step 2, after test.jsonl is regenerated.

A TEST row is EXPOSED when, after normalising (1) case and spacing or (2) to letters and digits only, it contains or is contained in a DEV or validation-round
row, or it is contained in the text of any tracked file under tests/, quantdesk/ or docs/ (the TEST file itself is never tracked). Strings under MIN_LEN
characters (normalised) are not matched, so that a short row cannot match everything. Template siblings that share words but neither contains the other are not
exposure (they are in-period template learning, data.in_period).

    python -I exposure.py <test.jsonl> <out exposed.json>     (run from the repository root)
Prints the exposed rows' indices and the output's SHA-256; never a TEST title.
"""
from __future__ import annotations

import glob
import hashlib
import json
import re
import subprocess
import sys

MIN_LEN = 30
ROWS = ["tests/fixtures/news_parse_v1/dev.jsonl"] + sorted(glob.glob("tests/fixtures/news_parse_v1/val*.jsonl"))


def norms(s: str) -> tuple[str, str]:
    a = " ".join(s.lower().split())
    return a, re.sub(r"[^a-z0-9]+", "", a)


def main():
    test = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
    rows = [json.loads(line)["title"] for f in ROWS for line in open(f, encoding="utf-8") if line.strip()]
    tracked = subprocess.run(["git", "ls-files", "tests", "quantdesk", "docs"], capture_output=True, text=True, check=True).stdout.split()
    texts = []
    for f in tracked:
        try:
            texts.append(norms(open(f, encoding="utf-8", errors="ignore").read()))
        except OSError:
            pass
    rn = [norms(r) for r in rows]
    exposed = []
    for r in test:
        t = norms(r["title"])
        hit = False
        for k in (0, 1):
            if len(t[k]) < MIN_LEN:
                continue
            if any((t[k] in x[k]) or (len(x[k]) >= MIN_LEN and x[k] in t[k]) for x in rn) or any(t[k] in x[k] for x in texts):
                hit = True
                break
        if hit:
            exposed.append(r["i"])
    data = json.dumps({"exposed": exposed, "rule": "news_parse_v1 P_test.exposure_rule"}, sort_keys=True).encode()
    open(sys.argv[2], "wb").write(data)
    print(f"exposed TEST rows: {exposed}; {sys.argv[2]} sha256 {hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
