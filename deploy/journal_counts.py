"""journal_counts.py DB [--not-below RESTORED.json]: the journal's size on the record, as JSON (C-01).

Without --not-below it prints {table: n} for the append-only tables and {table_max_id: id} for the ones that may be
archived and pruned (thoughts, news: their ids only ever grow). With it, it exits 1 naming every figure that is lower
than the restored snapshot's, so a save can refuse to replace the only copy with a smaller one.
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
    return out


def main(argv: list[str]) -> int:
    now = figures(argv[1])
    if len(argv) >= 4 and argv[2] == "--not-below":
        with open(argv[3], encoding="utf-8") as f:
            before = json.load(f)
        lower = {k: (v, now.get(k, 0)) for k, v in before.items() if now.get(k, 0) < v}
        for k, (b, n) in lower.items():
            print(f"journal: {k} is {n}, below the {b} restored", file=sys.stderr)
        return 1 if lower else 0
    print(json.dumps(now))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
