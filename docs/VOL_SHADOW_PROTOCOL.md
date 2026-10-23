# HAR volatility shadow: the protocol it is judged by (fixed before the first recorded session)

Written 23 Oct 2026, in the pull request that wires the shadow in (`quantdesk/intraday/volshadow.py`), so that it is on
`main` before the shadow records anything. Research review (23 Oct) found the shadow, as first built, had no
pre-stated failure criterion and tested a different slice than the lock. This file fixes both. It is a declaration, not
a registered spec under `docs/prereg/`; the owner can promote it to one.

## What is being tested
Whether `vol_forecast_v1`'s HAR forecaster (locked 3-4 Oct 2026; 8 of 8 cells passed on 2019 to Feb 2023) forecasts the
realised variance after the opening read better than **the forecaster the desk actually uses**, in live paper sessions.

## Comparator (corrected)
"Desk" is `VolForecaster`'s live realised estimate at the read (before the implied blend). It is **not** the study's
candidate A: the live estimate uses close-to-close returns and leaves out each day's opening return (the largest-variance
minute; the committed profile has it at about 29x the mean for NIFTY), and the study's A includes it. At 09:30 the desk
figure is expected to run roughly 0.77x (NIFTY) and 0.81x (BANKNIFTY) of A, a proxy computed from the committed profile,
not measured on real bars. So a pass here means "HAR beats the desk's own number", which is the decision-relevant
question, and it is **not** a replication of the locked comparison against A.

## One decision point
One forecast per index per session: the first minute from 09:30 IST at which HAR can be computed, retried until 10:00.
The lock covered 22 decision points a day (09:30 to 15:00); the shadow tests the single 09:30 slice, which is where A was
worst in the lock (move ratio 0.82 to 0.86). A pass here does not extend to the other 21 points.

## Primary statistic (one, pre-declared)
Per session, the mean over the four horizons (30m, 60m, 120m, close) and the two indices of the QLIKE difference
`QLIKE(desk) - QLIKE(HAR)` (positive means HAR is better), using volstudy's QLIKE on the realised sum of squared
1-minute log returns. Only sessions in which **both** indices have a gradable record count. The test is one-sided: a
Newey-West t (5 lags) on the per-session series, `nw_t` in `quantdesk/autolearn/prereg.py`, read against **Student's t with
n - 1 degrees of freedom** (a normal tail is too liberal at n = 60, see below). The four horizons share one realised path and the
two indices are strongly correlated, so **the session is the unit of evidence**, not the 8 cells. In code (`volshadow._pooled`):
a session counts only with **all four horizons graded for both indices**, and the statistic uses the **first 60** counted
sessions, so a 61st cannot move it.

## Inputs pinned (a change voids the count)
The model and the comparator must not move during the run. Pinned at the merge of this file:
`quantdesk/intraday/vol_har_v1.json` sha256 `de59c4ab9496e9ae2bc828741686949bf5608a2c4af548ce064afa25b3bef56a`. A refit, any
change to that file or to `harvol.py`, or any change to the desk's `VolForecaster` (`quantdesk/intraday/quant.py`) voids the
count: it restarts from zero on the date of the change, which is recorded here. The run starts with the first session recorded
after this file is on `main`; a session recorded before that does not count.

**Enforced in code, not only stated.** Every recorded forecast carries its pins: the sha256 of the coefficient file, and one
sha256 over `harvol.py` and `quant.py`. The count is the trailing run of sessions made under one pin, and the coefficient pin must
equal the value above (`volshadow.COEF_PIN`). A session recorded without a pin never counts. Graded sessions that do not count are
reported with their number, not hidden. Any edit to `harvol.py` or `quant.py`, comments included, changes the second pin and so
restarts the count: that is deliberately strict, and it means unrelated edits to `quant.py` during the run cost sessions.

## How many sessions, and why
The lock implies, for NIFTY, 40 to 53 sessions for 80% power at one-sided alpha 0.05 (daily SD implied by the reported
Newey-West t); for BANKNIFTY alone 57 to 290. 20 sessions gives about 50% power on NIFTY and 16 to 43% on BANKNIFTY. So:
**no read before 60 sessions with both indices recorded.** The pooled statistic has less power than the best single cells:
the research review (23 Oct) puts it at about 0.65 to 0.80 (0.64 if the eight cells were perfectly correlated, 0.80 at a
correlation of 0.6), not 80%, and BANKNIFTY is the weak part of the pool. The effect used is an all-day average from the lock; the
09:30 effect is not in the recorded result.
Interim output (`intraday vol-shadow`) is progress reporting only: until 60 sessions with both indices are graded it
withholds the primary statistic and the per-cell DM t. Looking earlier and stopping on a good number is not allowed.

## Stopping rule and backstop
The test is read **exactly once**, at the 60th counted session, by `intraday vol-shadow` (the statistic is computed in
`volshadow._pooled`, not by hand). **In code:** the first run on the live journal with 60 counted sessions computes the verdict,
stores it in the journal's state (`vol_shadow:primary_read`) and prints it; every later run prints that stored record and does not
recompute it, whatever `--since` says or however many sessions have been added. If fewer than 60 are counted by **31 Mar 2027**,
the first run after that date stores "NOT CONFIRMED (underpowered, n = ...)". The shadow is neither extended nor re-read without
a new protocol. Limit: the record lives in the journal state, so restoring an older journal copy would let the read be taken
again; this is a convention with code behind it, not a cryptographic seal.

## Failure rule (so that it can fail)
At 60 sessions: PASS only if the primary statistic's mean is positive **and** its one-sided Newey-West p < 0.05.
Otherwise it is **not confirmed**. In both cases:
- `docs/principles.json` L3 stays at its present rung; a pass moves it only through the normal review (research-reviewer),
  and a not-confirmed result is recorded as "live shadow not confirmed at n=60", never "replicated".
- There is no apply mode. A pass lets the owner consider building one, as a separate reviewed change; it does not
  apply anything. A not-confirmed result is recorded on L3 as "live shadow not confirmed at n=60" (or "underpowered at n"), the shadow is not
  extended or re-read, and no apply mode is considered.
- A skipped or short session never counts as a pass or a fail; it is shown in the report (see below).
- The size of the test: with a normal tail, a simulation under the null at n = 60 and 5 lags gave a false-pass rate of about 7%
  (no autocorrelation) to 9.5% (AR(1) 0.5), against a nominal 5%. The Student-t tail used here lowers that but it has not been
  re-measured, so a PASS means "p < 0.05 nominally, realised false-pass rate roughly 5 to 9%", never an edge claim on its own.

## Visibility of what is not recorded
`intraday vol-shadow` prints the shadow's WARNs by reason: no HAR forecast by 10:00, a late start (the engine first reached
the opening read after 10:00), the desk had no estimate, coefficients missing or unusable, could not start, a bad
`vol_forecast` setting, error. They are sessions or index-sessions without a gradable record. A session in which the engine
never ran leaves nothing to journal and cannot be listed. The header counts sessions with both indices graded, the only ones
that count toward 60. Cells with more than 20% missing bars, or a missing last bar of the horizon, are not graded (the second
condition is stricter than the study's rule).

## Known limits, stated now
- The live feed (Kotak or Yahoo, with futures) differs from the vendor minutes the HAR coefficients were fitted on; the
  opening bar and gap terms are the most sensitive. The shadow tests the model and the feed together.
- The graded numbers exclude the desk's 30% implied-volatility blend, so a pass says nothing about the blend or about
  option plans.
- `vol_har_v1.json` records `code_commit 363f2e1d...`, which is not reachable in this repository. The spec hash and
  session counts in it verify against the locked result; the dataset digests are self-reported.
- The 2023-03 to 2026-10 period is in neither the lock nor the shadow (the lock's sessions end 28 Feb 2023).
- The comparator and the 09:30 slice were chosen after seeing the lock, where candidate A was worst. The desk's 09:30 figure runs
  low (about 0.77x of A for NIFTY), so a pass may be partly a scale correction rather than better information. Candidate A is not
  logged alongside, so this is not separated; adding it as a descriptive, non-gating column is a possible follow-up.
- The protocol is a declaration in the repository, not a hash-pinned registered spec; the owner can promote it to `docs/prereg/`.
