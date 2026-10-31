# The scout's journal (snapshot)

`journal.jsonl` is the tamper-evident, append-only log of the asymmetry scout (shadow, offline research; see `docs/ASYMMETRY_SCOUT.md` on `main`).
One JSON line per entry, each carrying the hash of the one before. Verify it:

    python -m quantdesk intraday scout-log verify --journal journal.jsonl

`SUMMARY.md` is the readable index: everything tried so far (the running trial total), the hypotheses with their latest status, the plans, the runs.

- Evidence label: **external_unverified** (third-party index minutes, underlying price, not option P&L, assumed costs).
- Not for: a gate, a promotion, the paper gate or a profitability claim. A research candidate only.
- Aggregates and parameters only: no raw prices or minute bars are in this branch.
- Entries marked `backfill` were written after the fact from the run folders; the rest were written by the commands as they ran.
- This is a snapshot kept by hand until the scout runs on the desk's runner, when `runtime/intraday/scout/journal.jsonl` rides the existing `journal` branch save.
- The December 2026 review reads this whole file; any claim made then is judged against the full trial total in `SUMMARY.md`.
