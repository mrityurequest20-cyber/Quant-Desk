# Lessons

Every penalty on the scorecard (docs/org/scorecard.jsonl) writes its lesson here. The engineer reads this file at the
start of every shift, before any other work. A lesson is a rule for next time, not an apology.

## 2026-10-04: everything wrong with L1's evidence was found because the owner asked

1. **A law the desk relies on gets audited on a schedule, not on request.** Research's Wednesday audit re-attacks the
   top caveat of a relied-on principle every week (docs/ORG.md).
2. **Every convention a backtest uses must be checked against the live path:** entry price, settlement price, index
   level, costs. A difference is a finding, even when nobody asked.
3. **Count the effective sample, not the list.** Report each instrument's weight in a pooled mean and how many periods
   rest on a single instrument.
4. **A guard that rewording can beat is not a guard.** Every guard gets a test that tries to evade it.
5. **A result without provenance can't be reproduced.** Every result carries its code commit and data digests.
6. **Report what wasn't traded next to what was.** Skips, exclusions and missing days go in front of the results.
7. **A question the desk can answer is not a question for the owner.** Decide, record the decision, carry on.
