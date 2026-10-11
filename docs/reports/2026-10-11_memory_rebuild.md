# Learning-memory rebuild, 11 Oct 2026

The owner approved rebuilding the learning memory ("keep the right ones in place and rebuild it") with the earlier
evidence preserved first. Nothing earlier was deleted.

## Evidence kept
- Branches `claude/evidence-journal-pre-memory-rebuild-2026-10-10` and `claude/evidence-journal-2026-10-09` hold the
  journal branch as it was at commit 9cdfbeb, including `intraday/memory.json`.
- sha256 of the memory before the rebuild: `a89ec3027838484fbda46bf71fa462bd31f0d6375eb95923d517bc4f1dd2853e`.
- sha256 of the rebuilt memory: `b1b8dc22e501eba4a9ccd5ec5ed57ba3e3ec97c447ff53bf1a52438bc0d3bdd9`.

## What was wrong
1. **Dead VIX reads.** Kotak serves INDIAVIX as zeros. The `vix` factor voted a constant +1.0 ("India VIX 0.00 (-100.0%
   today)") on 742 of the 743 `vix` reads in the 5-9 Oct journal. The old record had graded 217 of them as evidence.
   `learning._dead_read` now skips a `vix` read whose observation is 0.00 or below, in both `grade_factors` and
   `grade_ic`. The rebuilt `vix` row holds the one real read (14.16).
2. **`learn --rebuild` could not finish.** 907 of the 4,071 headlines have a NULL `nlp` column. pandas returns NaN
   (truthy) for it, so `(nlp or {})` stayed NaN and `.get` raised. `learning._obj` now reads a JSON column as a dict.
3. **An older grading rule.** News from before the "a night of headlines is one observation" fix was still counted
   per story in the old tables. The rebuild regrades every headline under the current rule.

## What changed in the record
| | before | after |
|---|---|---|
| sessions in the record | 11 (6 were a bootstrap replay) | 5 (the live journal, 5-9 Oct) |
| `vix` graded observations | 217.2 | 0.17 |
| rules reader | n 263, 55% right, ×1.095 | n 141, 51% right, ×1.023 |
| ollama reader | n 117, 49% right, ×0.983 | n 101, 53% right, ×1.045 |
| gemini reader | n 109, 57% right, ×1.115 | n 82, 56% right, ×1.102 |

The factor counts roughly halve because the old tables also held the bootstrap reads. The bootstrap's six days
(24 Sep to 1 Oct) cannot be replayed now: Yahoo serves a week of 1-minute bars and only 29-30 Sep survive in
the recorded data, as partial days. Those reads stay in the preserved snapshot. `moves` and `lessons` are carried over
unchanged. Learned factor weights are still recorded, not applied (D-01); the news and reader trust tables are the
live-applied part of the record.
