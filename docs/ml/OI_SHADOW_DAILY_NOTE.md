# OI shadow: the daily check workflow (a note beside `docs/prereg/oi_shadow_v1.json`, 31 Oct 2026)

**This note records a deviation from one sentence of a registered spec. It does not edit the spec.**

## What the spec says

`docs/prereg/oi_shadow_v1.json`, `deployment.mode`: "... nothing new runs in the live process and **nothing is added to a workflow**. `python -m quantdesk ml oi ...`
grades one session after the close ... the desk engineer runs it after each close ... A missing session is therefore visible, never silently dropped".

## What was added

`.github/workflows/oi-daily.yml` and `python -m quantdesk ml oi-daily` (`quantdesk/ml/oi_daily.py`): a **monitoring-only** weekday job that downloads the chain
tape from the `chains-YYYY` releases, grades every forward weekday (from 2026-10-26) with the same `ml oi` code into scratch tables that die with the runner, and fails the
run on a trading day with no tape, a partial session or a session that does not grade. `contents: read`, no secret, a counts-only text summary kept 30 days.

## What it does not change

The test's definitions, features, windows, thresholds, promotion rule, the pinned code hash (`quantdesk/ml/oi.py` is untouched) and every table the read-out uses.
It writes no table anyone reads, and `ml oi-daily` refuses the read-out folder (`runtime/ml_oi`) as its output.

## The owner's decision

The owner listed "daily ml oi grading job" among the parked items on 24 Oct 2026, and on 31 Oct 2026 told the session "Complete the parked items" and, before a flight
with no connection, "Take any decision you want. Don't wait for me." This job is that item. The owner has not been shown the wording difference above individually: the
risk-compliance review of the exact head found no change to anything the spec registers as the test and asked that this record exist before merge.

**To undo it:** delete `.github/workflows/oi-daily.yml` (the `ml oi-daily` command can stay). Nothing else depends on it.

## For the owner, later

From 1 Jan 2027 every tape-less weekday is `unknown` (a warning, not a failure) until the 2027 NSE holiday list is in `config/quantdesk.yaml`, so a genuinely lost day
would only warn until then. Enter the 2027 list (the daily self-review asks for it from 1 December, and the watchdog's W9 check on 15 December).
