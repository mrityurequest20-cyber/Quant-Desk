# Learning memory rebuild, 16 Oct 2026: candidate vs live (NOT installed)

Owner-approved rebuild (handoff section 6). This report regenerates the 11 Oct report's numbers on the current
journal, under the grading rules that will be live once PR #62 merges: #49's (NULL `nlp` no longer crashes the
rebuild; `vix` reads taken while India VIX was served as 0.00 are not graded) plus C-07 (a news read is graded from
when the desk could act on it: the rules tone from `seen_at`, each language model's from its own read time).

**Status: candidate only. Not installed.** It is installed between runs (after a close, before a morning run), and
only after #62 is on `main`; otherwise `main` would keep grading new sessions under the old news rule on top of a
memory graded under the new one. The evidence snapshots are untouched (`claude/evidence-journal-pre-memory-rebuild-2026-10-10`,
`claude/evidence-journal-2026-10-09`).

## Inputs

| | |
|---|---|
| Journal | `journal@dc836b7` (close save, 16 Oct 15:31 IST), read-only copy |
| Live memory | sha256 `81023d64da6393bcf12398d7f9d158428c6813e0bf93987093bbdd19e78d9ab7` |
| Code | branch `ccr-0cac7edf-61t1mr` @ `8050ab0` (main `1d5c8c9` + C-07) |
| Command | `python -m quantdesk intraday learn --rebuild` (LLM keys unset; no network reads) |
| Candidate | sha256 prefix `5097edbeca1f99de` (regenerated at install time from the then-current journal head) |

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
