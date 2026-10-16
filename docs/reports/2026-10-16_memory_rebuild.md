# Learning memory rebuild, 16 Oct 2026: candidate vs live (INSTALLED 16 Oct, `journal@8816dd0`)

Owner-approved rebuild (handoff section 6). This report regenerates the 11 Oct report's numbers on the current
journal, under the grading rules that will be live once PR #62 merges: #49's (NULL `nlp` no longer crashes the
rebuild; `vix` reads taken while India VIX was served as 0.00 are not graded) plus C-07 (a news read is graded from
when the desk could act on it: the rules tone from `seen_at`, each language model's from its own read time).

**Status: installed 2026-10-16 ~17:20 UTC** as `journal@8816dd0`, a fast-forward on the learning cycle's `fbaebaf`. That cycle changed only `intraday/autolearn/`; `journal.db` and `memory.json` were byte-identical to `dc836b7`. The rebuild on `fbaebaf` reproduced the same file. Below, the original plan as written before the install: It is installed between runs (after a close, before a morning run), and
only after #62 is on `main`; otherwise `main` would keep grading new sessions under the old news rule on top of a
memory graded under the new one. The evidence snapshots are untouched (`claude/evidence-journal-pre-memory-rebuild-2026-10-10`,
`claude/evidence-journal-2026-10-09`).

## Inputs

| | |
|---|---|
| Journal | `journal@dc836b7` (close save, 16 Oct 15:31 IST), read-only copy |
| Live memory | sha256 `81023d64da6393bcf12398d7f9d158428c6813e0bf93987093bbdd19e78d9ab7` |
| Code | `0828211` = main `3ccdc8d` (#62 merged): #49 + C-07 + per-session `blocks` for the earn-in gate. The tables below were first produced at `8050ab0`; adding blocks left every table identical |
| Command | `python -m quantdesk intraday learn --rebuild` (LLM keys unset; no network reads) |
| Candidate (installed) | sha256 `a9d82381eb21c0b9b651f748196be24668ea8e326d999ffe9071ce9ccd6aae6e`. Reproduced byte-identical 3 times: from `dc836b7`, from `fbaebaf`, and once by the internal auditor with no network. (`5097edbe…` was the `8050ab0` file, before blocks) |

## What changes

| | Live | Candidate | Why |
|---|---|---|---|
| Sessions in the record | 16 | 10 | the 24 Sep - 1 Oct bootstrap replay can't be re-created (Yahoo keeps a week of 1-minute bars); those reads stay only in the evidence snapshot |
| `bootstrap` key | present | dropped | as designed (`--rebuild`) |
| Lessons kept | 5 | 5 | lessons and moves are carried over |
| Factor observations (all) | 4,470.8 | 3,323.0 | bootstrap days and dead VIX reads gone |
| `vix` factor observations | 295.8 | 79.8 | the 5-9 Oct reads taken while VIX was 0.00 were a constant +1 vote (#49) |
| News-graded headlines | 3,189 | 3,031 | |
| Setup records | 28 obs, 11 keys | 28 obs, 11 keys | identical (the 14 trades are all in the journal) |

### Reader reliability (`news_reader`, multiplier on a reader's weight)

| Reader | Live n | Live × | Candidate n | Candidate × |
|---|---|---|---|---|
| rules | 446.0 | 1.083 | 250.0 | 1.074 |
| gemini | 211.0 | 1.015 | 173.0 | **0.943** |
| ollama | 243.0 | 1.007 | 198.0 | **0.928** |
| claude | 54.0 | 0.818 | 56.0 | 0.827 |

Graded from when its read actually arrived, each language model loses the credit it took for moves that happened
before it spoke: both live readers fall below 1. Claude is `advisory_only` (never weighed) either way.

### News event trust (`news_event`, top by observations)

| Event | Live × (n) | Candidate × (n) |
|---|---|---|
| market_recap | 1.083 (194.9) | 1.131 (124.8) |
| general | 1.143 (101.2) | 1.005 (40.5) |
| policy | 1.028 (48.5) | 0.903 (25.6) |
| commodities | 0.988 (19.5) | 0.918 (12.0) |
| currency | 1.036 (16.8) | 0.981 (10.8) |
| inflation | 0.933 (17.6) | 1.070 (10.5) |

## Install procedure (unchanged from the handoff; never a force-push)

1. #62 merged; the journal branch head checked (a weekend learning cycle may have written it).
2. Re-run the rebuild on that head; re-diff; independent review of the diff.
3. One commit on top of `origin/journal` whose tree differs only in `intraday/memory.json` (temp index:
   `read-tree`, `hash-object -w`, `update-index --cacheinfo`, `write-tree`, `commit-tree -p origin/journal`), pushed as a
   fast-forward. The desk's next save leases on the commit it restores (C-12), so it builds on this one.
4. Verify the morning run restores it (`Memory` loads, 10 + new sessions in `days`, no `learning memory unreadable`
   event).

## Independent review (internal-auditor, 16 Oct): INSTALL WITH CONDITIONS

Every number in the tables above was checked against the candidate and the live file, and all match. For every
table and key, the per-session blocks sum to the table totals; `armed_rejected` has no blocks, by design. The earn-in
gate in shadow on the candidate gives "0 of 336 earned, 35 tested". Disclosures:

1. **News is not "10 sessions".** 269 of the 3,031 graded headlines (8.9%) were published 28-29 Sep, before the first
   session day (5 Oct). They are graded against real 29 Sep bars (a full 374 minutes), so the tone grades are valid,
   but their blocks fall outside `days`. They feed `news_event/general` (about 20 of its 40.5 observations: ×1.005,
   against ×0.959 without them) and the rules reader (20 of 250). Without them the gate would test 33 items, not 35.
   Nothing is earned either way.
2. **Headlines with NULL `nlp` are filed under event `general`.** #49 fixed the crash on them; it does not skip them.
   The live grading path does the same, so the rebuild and live agree. Follow-up: file them as `unclassified`.
3. **What the install changes on Monday** (shadow mode, so only the raw news and reader trust are live; factor
   weights and setup records stay recorded-only):
   - Readers weighed: rules 1.083 → 1.074, gemini 1.015 → 0.943. ollama and claude are `advisory_only`.
   - Events: general 1.143 → 1.005, policy 1.028 → 0.903, market_recap 1.083 → 1.131, inflation 0.933 → 1.070.
   - Sources: 69 of 292 move by more than 0.02.
   - No setup is stood aside, before or after.
   - The range of news-trust products narrows: 0.813-1.34 live, 0.848-1.304 now. Nothing can exceed the risk caps;
     conviction only scales size inside them.
4. **Rebuild vs live accumulation:** about +2% factor observations on the same 10 days, because news dedupe weights
   are computed per call. Accepted.
