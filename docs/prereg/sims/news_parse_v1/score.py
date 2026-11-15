"""The scorer of docs/prereg/news_parse_v1.json (frozen with the spec: its SHA-256 is registered there).

A parser is loaded from a FILE (a newsmodel.py: the baseline is `git show 72af8ea:quantdesk/paper/newsmodel.py`, the fixed one is the frozen file), so both are
scored by the same code. Only the 28 subjects of newsmodel.SUBJECTS at 72af8ea are scored (KEYS); any other key a parser gives is ignored, and one in a label file stops the run.

Metric (spec "metric"): for each headline, the KEYS that either the labels or the parser give a NONZERO direction; a pair is right when the two directions agree
(a subject one side does not give counts as 0). Accuracy = right / pairs.

    python -I score.py score   --set <set.jsonl> --parser <newsmodel.py> --labels <labels.json> [--errors] [--boot]
    python -I score.py agree   --set <set.jsonl> --labels <a.json> --labels2 <b.json>
    python -I score.py compare --set <set.jsonl> --parser <baseline.py> --parser2 <fixed.py> --labels <labels.json>

A labels file is a JSON list of {"i": n, "title": "...", "labels": {"subject": -1 | 0 | 1, ...}}. Every labels file is checked against the set it labels (--set,
required): one row per set row, the same `i` and the same title, every value -1, 0 or 1; anything else stops the run. A parser file must be standard-library
only, with no relative imports (it is loaded on its own, outside the package).
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import math
import random
from collections import Counter

KEYS = ("crude", "natgas", "gold", "silver", "metals", "rupee", "dollar", "us_yields", "fed", "rbi", "inflation", "growth", "fii", "geopolitics", "tariffs",
        "china", "wall_street", "monsoon", "it_spend", "auto_sales", "usfda", "telecom", "fno_rules", "fintech_rules", "bad_loans", "capex", "electronics",
        "cigarettes")
BOOT_N, BOOT_SEED = 10_000, 20261115


def load_labels(path: str, set_path: str) -> list[dict]:
    rows = json.load(open(path, encoding="utf-8"))
    want = [json.loads(line) for line in open(set_path, encoding="utf-8") if line.strip()]
    if not isinstance(rows, list) or len(rows) != len(want):
        raise SystemExit(f"{path}: {len(rows) if isinstance(rows, list) else 'not a list'} rows, the set has {len(want)}")
    for r, w in zip(sorted(rows, key=lambda r: r.get("i", -1)), want):
        if r.get("i") != w["i"] or r.get("title") != w["title"]:
            raise SystemExit(f"{path}: row i={r.get('i')} does not match the set's row i={w['i']}")
        lab = r.get("labels")
        if not isinstance(lab, dict) or any(v not in (-1, 0, 1) or isinstance(v, bool) for v in lab.values()):
            raise SystemExit(f"{path}: row i={r['i']} has a label that is not -1, 0 or 1")
        bad = [k for k in lab if k not in KEYS]
        if bad:
            raise SystemExit(f"{path}: row i={r['i']} labels unknown subject(s) {bad}")
    return sorted(rows, key=lambda r: r["i"])


def load_parser(path: str):
    loader = importlib.machinery.SourceFileLoader("newsmodel_under_test", path)      # any file name: a snapshot may be stored as .py.txt
    spec = importlib.util.spec_from_loader("newsmodel_under_test", loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def nonzero(d) -> dict:
    return {k: int(v) for k, v in dict(d).items() if k in KEYS and int(v) != 0}


def read(parser, title: str) -> dict:
    return nonzero(parser.subjects(title))


def pairs(lab: dict, got: dict) -> list[tuple[str, int, int]]:
    return [(k, lab.get(k, 0), got.get(k, 0)) for k in sorted(set(lab) | set(got))]


def per_headline(rows, parser) -> list[tuple[int, int, int, int, int]]:
    """[(right, pairs, parser nonzero, labels nonzero, right among the labels' nonzero)] per headline."""
    out = []
    for r in rows:
        lab, got = nonzero(r["labels"]), read(parser, r["title"])
        ps = pairs(lab, got)
        out.append((sum(a == b for _, a, b in ps), len(ps), len(got), len(lab), sum(1 for k, v in lab.items() if got.get(k) == v)))
    return out


def summary(h) -> dict:
    right, n, pn, ln, good = (sum(x[j] for x in h) for j in range(5))
    return {"pairs": n, "right": right, "accuracy": round(right / n, 4) if n else None,
            "precision": round(good / pn, 4) if pn else None, "recall": round(good / ln, 4) if ln else None}


def boot_ci(h, n=BOOT_N, seed=BOOT_SEED) -> tuple[float, float]:
    """95% percentile interval of accuracy, resampling HEADLINES (pairs of one headline move together)."""
    rng, acc = random.Random(seed), []
    for _ in range(n):
        s = [h[rng.randrange(len(h))] for _ in h]
        tot = sum(x[1] for x in s)
        if tot:
            acc.append(sum(x[0] for x in s) / tot)
    acc.sort()
    return round(acc[int(0.025 * len(acc))], 4), round(acc[int(0.975 * len(acc)) - 1], 4)


def cmd_score(a):
    rows, parser = load_labels(a.labels, a.set), load_parser(a.parser)
    h = per_headline(rows, parser)
    s = summary(h)
    by = Counter()
    for r in rows:
        for k, x, y in pairs(nonzero(r["labels"]), read(parser, r["title"])):
            if x != y:
                by[k] += 1
    s["errors_by_subject"] = dict(by.most_common())
    if a.boot:
        s["ci95_headline_bootstrap"] = boot_ci(h)
    print(json.dumps(s))
    if a.errors:
        for r in rows:
            lab, got = nonzero(r["labels"]), read(parser, r["title"])
            if any(x != y for _, x, y in pairs(lab, got)):
                print(f"{r['i']:3d} {r['title'][:100]!r}\n      label {lab}  parser {got}")


def cmd_agree(a):
    """Agreement over the metric's own pairs (either labeller nonzero) and Cohen's kappa on those pairs (categories -1, 0, +1)."""
    A = {r["i"]: nonzero(r["labels"]) for r in load_labels(a.labels, a.set)}
    B = {r["i"]: nonzero(r["labels"]) for r in load_labels(a.labels2, a.set)}
    xs = [(x, y) for i in sorted(A) for _, x, y in pairs(A[i], B[i])]
    n = len(xs)
    po = sum(x == y for x, y in xs) / n if n else float("nan")
    ca, cb = Counter(x for x, _ in xs), Counter(y for _, y in xs)
    pe = sum(ca[c] * cb[c] for c in (-1, 0, 1)) / n ** 2 if n else float("nan")
    kappa = (po - pe) / (1 - pe) if n and pe < 1 else float("nan")
    dis = [(i, k, x, y) for i in sorted(A) for k, x, y in pairs(A[i], B[i]) if x != y]
    print(json.dumps({"pairs": n, "agreement": round(po, 4), "kappa": round(kappa, 4), "disagreements": len(dis)}))
    for i, k, x, y in dis:
        print(f"  headline {i}: {k} {x:+d} vs {y:+d}")


def cmd_compare(a):
    """Paired: on the same headlines and labels, pairs the fixed parser gets right and the baseline wrong (b) and the reverse (c); exact one-sided sign test."""
    rows, p0, p1 = load_labels(a.labels, a.set), load_parser(a.parser), load_parser(a.parser2)
    b = c = 0
    for r in rows:
        lab, g0, g1 = nonzero(r["labels"]), read(p0, r["title"]), read(p1, r["title"])
        for k in set(lab) | set(g0) | set(g1):
            r0, r1 = lab.get(k, 0) == g0.get(k, 0), lab.get(k, 0) == g1.get(k, 0)
            b += r1 and not r0
            c += r0 and not r1
    n = b + c
    p = sum(math.comb(n, j) for j in range(b, n + 1)) / 2 ** n if n else 1.0
    print(json.dumps({"fixed_right_baseline_wrong": b, "baseline_right_fixed_wrong": c, "sign_test_p_one_sided": round(p, 6)}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("score", "agree", "compare"))
    ap.add_argument("--set", required=True)
    ap.add_argument("--parser")
    ap.add_argument("--parser2")
    ap.add_argument("--labels")
    ap.add_argument("--labels2")
    ap.add_argument("--errors", action="store_true")
    ap.add_argument("--boot", action="store_true")
    a = ap.parse_args()
    if a.cmd in ("score", "compare") and not (a.parser and a.labels) or a.cmd == "compare" and not a.parser2 or a.cmd == "agree" and not (a.labels and a.labels2):
        ap.error("missing --parser / --parser2 / --labels / --labels2 for this command")
    {"score": cmd_score, "agree": cmd_agree, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    main()
