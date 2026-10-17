"""journal_counts.py DB [--not-below RESTORED.json [--pruned PERMIT.json --restored-sha SHA]]: the journal's size on the
record, as JSON (C-01).

Without --not-below it prints {table: n} for the append-only tables and {table_max_id: id} for the ones that may be
archived and pruned (thoughts, news: their ids only ever grow). With it, it exits 1 naming every figure that is lower
than the restored snapshot's, so a save can refuse to replace the only copy with a smaller one.

One narrow exception (C-02): `--pruned PERMIT.json --restored-sha SHA`. The retention step writes the permit only after
the rows it deleted were archived, downloaded back from their release and verified (quantdesk/journal/durable.py). For
a table the permit names (thoughts, news) the max-id figure is then not compared (VACUUM may renumber news rowids);
instead the rows now plus the rows pruned must still cover the rows restored. trades, fills, decisions and events, and
any table the permit does not name, are compared exactly as before. A permit for another restored commit is ignored.
"""
import json
import sqlite3
import sys

COUNTED = ("trades", "fills", "decisions", "events")
MAX_ID = ("thoughts", "news")


def figures(path: str) -> dict:
    out = {}
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in COUNTED:
            if t in have:
                out[t] = int(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
        for t in MAX_ID:
            if t in have:
                out[f"{t}_max_id"] = int(db.execute(f"SELECT COALESCE(MAX(rowid), 0) FROM {t}").fetchone()[0])
                out[f"{t}_rows"] = int(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])   # only read with a permit
    return out


def pruned_rows(permit: str, restored_sha: str) -> dict:
    """{table: rows} a verified prune took out of thoughts/news; {} unless the permit is for exactly the commit restored."""
    try:
        with open(permit, encoding="utf-8") as f:
            p = json.load(f)
        if p.get("version") != 1 or not restored_sha or p.get("restored_sha") != restored_sha:
            return {}
        return {t: n for t, n in p["pruned"].items() if t in MAX_ID and isinstance(n, int) and n > 0}
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return {}


def main(argv: list[str]) -> int:
    now = figures(argv[1])
    if len(argv) >= 4 and argv[2] == "--not-below":
        with open(argv[3], encoding="utf-8") as f:
            before = json.load(f)
        opts = dict(zip(argv[4::2], argv[5::2]))
        allow = pruned_rows(opts["--pruned"], opts.get("--restored-sha", "")) if "--pruned" in opts else {}
        lower = {k: (v, now.get(k, 0)) for k, v in before.items()
                 if not k.endswith("_rows") and k.removesuffix("_max_id") not in allow and now.get(k, 0) < v}
        for t, n in allow.items():                     # a verified prune: rows now + rows pruned must cover rows restored
            had = before.get(f"{t}_rows", 10 ** 12)    # a snapshot without row counts cannot vouch for it: refuse
            if now.get(f"{t}_rows", 0) + n < had:
                lower[f"{t}_rows"] = (had - n, now.get(f"{t}_rows", 0))
        for k, (b, n) in lower.items():
            print(f"journal: {k} is {n}, below the {b} restored", file=sys.stderr)
        return 1 if lower else 0
    print(json.dumps(now))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
