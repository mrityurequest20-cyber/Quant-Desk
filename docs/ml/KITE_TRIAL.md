# Kite Connect market-data trial: criteria (written before any Kite data exists: nothing has run yet, the shake-down included)

> **Amendment v2, 25 Oct 2026, before any Kite data exists (owner decision).** The websocket is **attached directly to the running paper desk**, not recorded in shadow: when
> `KITE_API_KEY` and the day's access token are present, Kite serves the index bars and the live index price, and the existing feeds (Kotak, then Yahoo) are the automatic
> fallback for every minute Kite lacks, for any minute whose close differs from the fallback's by more than 0.5%, and for any failure. History, the futures volume on index bars
> and the option chain stay as they are, and no tick-level order flow is added (that would change vote inputs and is its own reviewed step). Live trading stays off; no order
> method is used. The trial now asks whether to **keep** the attachment and the subscription, on the measures below. The separate tick recorder described further down is
> optional and secondary: it measures latency (C3) and real order flow (C4) and is not needed for the decision.
>
> **Amendments of 30 Oct 2026 (review fixes, still before any Kite data: the code is not on `main` and no session has run).** Each changes how a measure is read and is listed here for the owner to accept knowingly. *Can make a pass easier:* (1) **C3 latency is reported, no longer a pass condition**, because Kite's exchange stamps are whole seconds (about +0.5 s of rounding bias) and the recorder cannot measure the runner clock's offset; (2) **E1 is a per-session 99% and the decision judges 90% of sessions**, which replaces the contradictory "99% in every session"; (3) **a session with fewer than 20 flat late-session minutes is not measured for E3**, is judged on E1, E2 and E4 and stays in the denominator, and KEEP needs E3 measured in at least 5 sessions; (4) **EXTEND is defined** (once, then REMOVE if still short), and the decision is made in a fixed order (below); (5) **E3 is judged inside each session's E1-to-E4 test, where it was measured, and has no second test of its own**. *Tightenings:* (6) time no runner covers counts as unserved (apart from the hand-over, 11), and E1 and E2 are read over the whole 09:20 to 15:00 window; (7) E3's denominator is the other feeds' flat minutes whether or not Kite had a bar; (8) a session in which nothing was compared fails E4; (9) **a new rule: E6 is judged per session, and KEEP needs it in at least 90% of counted sessions**; (10) an extension cannot use sessions past 24 Nov without a new written authorisation and a reviewed code change (below). (11) **the scheduled hand-over window, 12:20 to 12:25, is excluded from the E1 and E2 denominators, which can make a pass easier**: measured on 30 Oct, the morning job's engine step ended at 12:20:18 IST and the afternoon job's began at 12:21:23, but counter events fire only on minutes divisible by 5, so the morning runner's last event is at 12:20 and the afternoon runner's first at 12:25 at the earliest; that leaves 5 minutes × 3 symbols = 15 of the 1,020 symbol-minutes uncovered (1.47%) on a perfect day, which would cap E1 at 98.5% against its 99% and make KEEP unreachable. Any other uncovered time, including an afternoon runner that is late after 12:25, stays unserved. *E2 margin, as the rule reads it (first event to last event at or before 15:00):* on a clean single-runner replay day (the end-to-end test, 1,020 polls) E2 was 4 polls, 0.39%, and E1 100% (7 polls, 0.69%, on the all-day cumulative counters, which the rule does not use; a runner's first polls of each symbol come before its first event).
>
> **Credentials under v2 (supersedes the "Operating notes" below).** `KITE_API_KEY` and `KITE_API_SECRET` are repository secrets (added by the owner on 25 Oct). Inside jobs they are
> exposed only as `KITE_DATA_KEY`, `KITE_DATA_SECRET` and `KITE_DATA_TOKEN`, **never** as the names the broker adapter (`execution/kite.py`) reads, so the day's token cannot switch that
> adapter's credentials on. The API secret is read by exactly these steps: the daily "Kite token" workflow (one step: it exchanges the owner's single-use `request_token` for the day's access token and encrypts it),
> the live desk's optional "Kite token" step (it decrypts the file; the library install is a separate step with no secret), and, in the tick recorder's two jobs, five steps: each job's
> token step (it decrypts the same file) and tick-encryption step, and the second job's step that decrypts the first job's ticks for the session measures (the recorder workflow arrives with its own pull request). The `--feed kite` option of
> the intraday command (`KiteIntradayFeed`, which reads the broker adapter's names) is not used by any workflow and is untouched; the attachment reads only the `KITE_DATA_*` names. The access token is stored
> AES-256 encrypted, with a key derived from the API secret, as one file on a `kite-token` branch of this (public) repository; every day's ciphertext stays in git history, the token expires
> within a day, and CBC carries no integrity check, so the desk accepts only a decrypted value of token shape (16 to 64 letters and digits) before exporting it. No password or TOTP is stored. No
> order method is called in `kitelive.py` (a test greps that file for it). These are data-only credentials used on the owner's explicit instruction of 25 Oct; the exception is recorded in
> `docs/AUTONOMY.md` (owner-authorised, ending 25 Nov 2026), and the feed itself does not start from that date (`kitelive.AUTHORITY_ENDS`).
>
> **Licence.** Kite market data is the subscriber's. Minutes served from Kite are kept out of the recorder (`unrecorded`), so they do not reach the public run artifacts or the `chains-YYYY`
> release; the app's Data panel shows how old each tick is, never a Kite price. What cannot be avoided: the desk's own decisions, trades and its Markets view are computed from the index level
> whatever feed served it, as they were with Kotak and Yahoo. If the owner reads the licence more strictly than that, the answer is `intraday.kite.live: false`.
>
> **What changes for registered paper evaluations.** `intraday_direction_v1` and `oi_shadow_v1` read the desk's own record; sessions that ran on the Kite feed are marked by the heartbeat's
> feed name and the counter events below. Their pre-registered definitions are unchanged.
>
> **Counted sessions (replaces the v1 definition).** Every trading weekday from 2 Nov, **whether or not a token was loaded**: a day without a token fails E1 and E6 and is not excluded. 26 to 30
> Oct are shake-down and not counted. Read-out 20 Nov.
>
> **The settlement window is not Kite's (15:00 to 15:29).** The expiry sleeves settle on the mean of the *recorded* 15:00 to 15:29 closes and on the 15:29 close (`sleeves.settlement_price`,
> `official_close`). To change nothing they read, no poll that reaches 15:00 is answered from Kite alone: the other feeds are asked and their bars stand for every minute they have; Kite is
> compared with them, never overlaid, and not even a minute they lack is supplied by Kite (their next poll may bring it; Kite's live price still serves exits). Kite's minutes before 15:00 are kept out of the recorder (licence), and the other feeds' own history for today fills those holes every
> 30 minutes and at the close (`fill_bars` adds only what is missing), **those two fills only before 15:00**. The one fill at session start has no cutoff, but it reads the same history a plain day reads: `KiteBackedFeed.history` is the wrapped feed's own (Kite's historical candles are not wired into the desk, and `--feed kite`, which would use them, is not what the attached desk runs). So the recorded 15:00 to 15:29 bars are what a plain day would have recorded, holes included. An end-to-end test runs one day plain and one day under Kite and asserts that the recorded
> 15:00 to 15:29 bars, the settlement price and the official close are identical. Kite's live price still serves exits after 15:00, and Kite remains the *measure* of whether the late index is
> frozen (E3).
>
> **Measures for the attached desk (fixed now).** Read from the journal's INFO events of category `feed` whose message starts `kite feed counters` (written every 5 minutes by the engine, one per
> minute, as JSON of the feed's own counters). The counters are cumulative **per process**: each event carries `started`, the runner's start stamp, and the morning and the afternoon runner are read
> separately. Rates are read from **differences between a runner's first event and its last event at or before 15:00**, so a runner that starts at 12:20 is not credited with the morning and the
> five-minute reading resolution is the only unmeasured margin. **Time no runner covers is unserved time, not excluded time:** the day's E1 denominator is every minute from 09:20 to 15:00 (3 symbols each) except the scheduled hand-over window 12:20 to 12:25 (the morning job's last event is at 12:20 and the afternoon job's first at 12:25 at the earliest, because events fire on multiples of five minutes), a minute counts as served only if a runner's window (first event to last event at or before 15:00) contains it and Kite served it, so a runner that starts late, dies early or never logs an event costs the day its E1 (and the hole counts in E2 as polls not served from Kite).
>
> | # | Measure | How it is read | Pass if |
> |---|---|---|---|
> | E1 | **Kite share of minutes** | the day's value = Σ over the day's runners of Δ`minutes` (from the runner's first event to its last event at or before 15:00, clipped to 09:20 to 15:00) ÷ (3 symbols × 335 minutes: the 09:20 to 15:00 window less the 12:20 to 12:25 hand-over): a runner with fewer than two events adds nothing, and any other time no runner covers stays in the denominator | at least 99% in a session for that session to pass E1 |
> | E2 | **Fallback dependence** | (Σ over runners of Δ(`fallback_polls` − `sampled_polls`) + the minutes of 09:20 to 15:00 that no runner covers, apart from the 12:20 to 12:25 hand-over, each counted as a poll Kite did not serve) ÷ (Σ Δ`polls` + those uncovered minutes): polls on which the other feeds had to be asked because Kite could not serve (every tenth otherwise-Kite-only poll asks them on purpose, to give E4 a denominator, and is counted apart) | at most 1% of polls |
> | E3 | **Late-session index** | Σ over the day's runners (each identified by its `started` stamp) of the counters at that runner's last event, `late_kite_moved` ÷ `late_fb_flat` (a runner that ends before 15:15 adds 0 to both): of the minutes from 15:15 to 15:28 in which the other feeds' NIFTY or BANKNIFTY bar was flat (open = high = low = close; Kotak's frozen window), the share in which Kite's bar was not. "Flat" is deliberately simpler than C1's `frozen_minutes`, which also needs equality with the previous close and a run of three: a flat minute that is not part of a frozen run is counted in the denominator too: it lowers the ratio if Kite was flat in it and raises it if Kite moved, and that difference is accepted as it is | at least 90% for that session to pass E3. The denominator is the other feeds' flat minutes whether or not Kite had a bar, so a Kite outage in that window fails it. If `late_fb_flat` is under 20 in a session, that session is "not measured" for E3: it is left out of E3's count (neither a pass nor a fail), and KEEP needs E3 measured in at least 5 counted sessions |
> | E4 | **Disagreement** | Σ over runners of Δ`rejected` ÷ Σ Δ`compared`, each over the runner's window; a session with Σ Δ`compared` = 0 fails E4 (nothing was checked). A Kite minute is *compared* when the other feeds have a bar for it (its close is compared with that bar's close, its high and low with that bar's), or, for a minute they lack, with the close of the minute before it as that poll's merged series holds it (which may already be a Kite close; failing that the latest earlier close in the series, then the last close the feed returned for that symbol from any source); a minute with no adjacent earlier minute is a hole, not a comparison. It is *rejected* (not used) when its close differs by more than 0.5%, or its high or low is more than 0.5% from the other bar's. The counters count evaluations: a minute evaluated on more than one poll is counted on each. Checks happen on a symbol's first poll, on every poll the fast path cannot serve (a hole, an unhealthy socket, a jump) and on one otherwise-Kite-only poll in ten (`SAMPLE_EVERY` = 10), so a Kite minute served on an unchecked poll is not compared. Live-price rejections are counted apart (`ltp_rejected`). Each runner lists its first 60 rejected minutes by stamp, never price, in `rejected_minutes`; those are cross-checked by hand against Kite's own historical candle for that day (more than 60 in a runner: the first 60 are checked) | at most 0.5%, and none that the hand check shows was Kite right and the other feed wrong |
> | E5 | **No harm** | the counter `faults` (a fault inside the Kite logic that was handed to the other feeds) and any engine ERROR or CRITICAL event naming `kitelive` | none |
> | E6 | **Manual steps** | the daily request_token run (D2 below) and any restart | a session passes E6 if it has a token and at most one manual step: the daily request_token run is that one, and a *restart* is a second (a runner started or re-dispatched by hand, or a failed runner started again, beyond the two scheduled runners: the morning job to the 12:20 hand-over and the afternoon job, which are not restarts). Read from the live workflow's run history: the day's "Kite token" step exported a token = *has a token*; a second dispatch of the live workflow that day, or a run attempt above 1 = a *restart*; cross-checked by the counter events (more than two distinct `started` stamps in the day is a restart). A day with no token fails E1 and E6 |
>
> Kite minutes are not served on a minute whose first tick came more than 15 s after the minute began (a late connect or a reconnect) and only inside 09:15 to 15:29; a live price more than 0.5%
> from the last served close is used only if the other feed's price agrees; none of these is a trial measure, they are the safeguards the review required.
>
> **Decision on 20 Nov (fixed now), taken in this order.** *Definitions:* N = counted sessions; M = counted sessions in which E3 was measured; a session **passes E1 to E4** if E1 (99%), E2, E4 and, where it was measured, E3 each pass (a session in which E3 was not measured is judged on E1, E2 and E4 alone and stays in N; there is no second test on E3); P = the share of counted sessions that pass E1 to E4; Q = the share that pass E6; E5 fails if it fails in any counted session; if N = 0, P = Q = 0 and the verdict is REMOVE.
>
> 1. **REMOVE** the attachment (one config line, `intraday.kite.live: false`) and do not renew the subscription if E5 fails.
> 2. **EXTEND** once, if E5 has no failure, P and Q are each at least 90% on the sessions in hand, and the only shortfall is sessions: N < 10 or M < 5. The extension adds exactly the sessions missing from 10 counted or from 5 E3-measured (whichever needs more), counted from 20 Nov; the decision is then taken on **all** counted sessions, the earlier ones included, with the rules of 3 and 4, on the first trading day after the last added session and not later than 25 Nov. An extension may use sessions only up to 24 Nov: the feed does not start from 25 Nov (`kitelive.AUTHORITY_ENDS`, which the exception in `docs/AUTONOMY.md` mirrors). Sessions beyond that need the owner's new written authorisation **and** a reviewed change to `AUTHORITY_ENDS` and to the exception; unless both exist, the extension is cut at 24 Nov, and if the missing sessions are not reached by then the verdict is REMOVE (not enough sessions).
> 3. **KEEP** if N ≥ 10, M ≥ 5, E5 has no failure, and P and Q are each at least 90%.
> 4. Otherwise **REMOVE**.
>
> A hand-checked candle comparison (Kite's own
> historical minutes against the desk's bars, as B1 below) is run on the first and last counted weeks as a cross-check on E4. The separate tick recorder described further down is optional and
> secondary: it measures latency (C3) and real order flow (C4) and is not needed for the decision.

**Status:** criteria v1, committed alone before any code or data. Registered 24 Oct 2026. The owner pays for one month of Kite Connect market data; the engineer records it
from Monday 26 Oct for four weeks and reports on 20 Nov. **Nothing in this trial places a live order or changes a live-trading feed, a limit or a gate.** Under amendment v2 the paper desk's own decisions, and so the inputs of the registered paper evaluations, can change (see v2). Live trading stays off.

## Why a trial

Three weaknesses of the desk's current data are visible in its own journal (week of 19 to 23 Oct):

1. **Yahoo as a fallback.** On 19 Oct, 190 of 570 polls came from Yahoo; Yahoo returned no bars from 15:04 and the engine's three-failures rule halted entries (F-19-1).
2. **Kotak's index series freezes** from 15:15 to 15:28 in every session while the future keeps trading (F-02); those minutes are kept out of grading.
3. **Order flow is approximated.** CVD comes from where a minute bar closes, not from trades.

Kite Connect offers a websocket with exchange timestamps, full-mode ticks (last price, volume, open interest, market depth) and its own historical minute candles. The trial asks, with
numbers fixed in advance, whether it is better than what the desk has, and what keeping it would cost in effort.

## What is recorded (a separate process, never the trading path)

> **This section describes the optional tick recorder, whose workflow (`.github/workflows/kite-record.yml`) arrives with its own pull request and is not on `main`; every statement about it is to be verified there, and it decides nothing about the subscription.**

- **Instruments:** NIFTY 50, NIFTY BANK, INDIA VIX (indices), and the near-month future of NIFTY and BANKNIFTY. Options are not recorded in the first two weeks.
- **Per tick:** instrument token, exchange timestamp, receipt time (the recorder's clock), last price, last traded quantity, cumulative volume, open interest (futures), best bid and ask and
  the day's total buy and sell quantities; and for the **futures, all five levels of market depth on each side (price, quantity, number of orders)**. Indices carry no depth. One-minute bars are
  built from the ticks by the measures and kept beside the raw ticks.
- **After the close:** Kite's own historical minute candles for the same instruments are fetched once, as the reference for the comparison.
- **Where it lives (v2):** this repository is public, so a "private release" does not exist. The recorder runs on a hosted runner (`.github/workflows/kite-record.yml`, scheduled 08:55 IST on
  trading days, in two jobs), and its raw ticks are **encrypted on the runner with the owner's Kite API secret (AES-256) before anything is uploaded**; the uploaded workflow artifacts
  (`kite-raw-1`, `kite-raw-2`, 90 days) are ciphertext that only the owner can open, with `deploy/kite-decrypt.sh` on their own machine. Kite market data is licensed to the subscriber: it never
  enters the repository, a release or a model card unencrypted, and no derived table is published. The run summary and the `kite-metrics` artifact carry **counts and ratios only** (the numbers
  below). Longer retention than 90 days is the owner's to arrange by downloading the artifacts.
- **No extra manual step.** The recorder uses the same day's token the "Kite token" workflow stores for the desk; with no token it records nothing and the run succeeds. Kite allows three websocket
  connections per key: the desk uses one, the recorder one.
- **How it runs:** its own process, started beside the desk, with the data-only credentials (`KITE_DATA_KEY`, `KITE_DATA_TOKEN`, and `KITE_DATA_SECRET` for the encryption of its raw ticks). A recorder failure, a token that has expired or a dropped
  connection never reaches the desk: no shared state, no import from the engine, no exception that propagates. The credential is read from the environment; nothing is written to a log.

## Counted sessions

A **counted session** is a weekday on which the exchange traded and the recorder started. **Sessions 1 to 5 (26 Oct to 30 Oct) are the shake-down and are not counted**: a first run
against a real API will find faults, and fixing them is the point. A session counts from 2 Nov. The read-out on 20 Nov covers 2 Nov to 19 Nov (14 trading days at most). If fewer than 10
sessions were counted by then, the verdict is "inconclusive" and the trial is extended by the missing sessions, once; the thresholds are not changed.

## Measures and thresholds (all fixed now)

For each counted session and each recorded index and future, over the minutes 09:15 to 15:29 IST (375 minutes):

| # | Measure | Definition | Pass if |
|---|---|---|---|
| A1 | **Coverage** | share of the 375 minutes with at least one tick | at least 99.5% |
| A2 | **Longest gap** | longest run of minutes with no tick, in minutes | at most 3 |
| B1 | **Bar accuracy** | share of minutes whose tick-built close is within 0.02% of Kite's historical candle close | at least 99% |
| B2 | **Bar range** | share of minutes whose tick-built high and low are each within 0.05% of the candle's | at least 97% |
| C1 | **Late-session index** | share of 15:15 to 15:28 index minutes that are **not** frozen by `feeds.frozen_minutes` (open = high = low = close = previous close, runs of 3 or more) | at least 90%, where Kotak's is about 0% |
| C2 | **Yahoo dependence** | of the minutes the desk journal shows as served by Yahoo or missing from Kotak, the share the Kite bars cover | at least 99% (if there are none that session, not measured) |
| C3 | **Latency** | receipt time minus exchange timestamp, per tick. Exchange stamps are whole seconds, so the figure carries about +0.5 s median and +1 s p99 of rounding bias, and the recorder does not measure the runner clock's offset | **reported, not a pass condition** (an uncorrected timestamp delta, not a measurement of latency: the runner clock's offset is not known and the exchange stamps are rounded; the attached desk's decision does not use it) |
| C4 | **Real order flow** | descriptive only: correlation of the minute CVD built from tick-rule trades with the desk's close-location CVD; no threshold | reported |
| D1 | **Reconnects** | websocket disconnections per session | reported; a disconnection that leaves a run of more than 3 minutes without ticks fails A2 |
| D2 | **Manual steps** | times the owner had to act (new access token, restart) | at most one per trading day (the daily token) |
| D3 | **Volume** | recorded size per session | reported (the ticks are 90-day workflow artifacts, encrypted; there is no size guard, so the figure is watched. The in-memory buffer is capped at 1,000,000 ticks: past the cap the recorder drops further ticks, counts them and writes an `overflow` event with `dropped_ticks`. A session with an overflow event is **not excluded** and not repaired: it is judged on the ticks that were recorded, as if the dropped ticks had never arrived: no minute is excluded or recomputed because of them (dropped ticks can only lower A1 and lengthen A2; their effect on B1 and B2 is not claimed), and `dropped_ticks`, summed over the session's `overflow` events, is reported) |

A session **passes** if A1, A2, B1 and B2 pass for every recorded instrument (indices and futures). C3 (latency) is reported and is not a pass condition. The trial **has value** if C1 passes in at least 90% of counted
sessions, or C2 passes in every counted session in which it was measured, because either would fix a weakness the desk has today.

## The decision on 20 Nov (the rule is fixed now; nobody chooses after seeing the data)

> **Superseded by amendment v2.** The attached desk's KEEP / REMOVE / EXTEND rule at the top of this document ("Decision on 20 Nov" under the measures E1 to E6) is the one rule that governs the subscription on 20 Nov. The bullets below are the v1 rule for the separate shadow recorder (A to D) and decide nothing about the subscription or the attachment.

- **CONTINUE as a shadow source** (still no effect on trading) if at least 90% of counted sessions pass, the trial has value, and D2 holds. A **separate, independently reviewed change**
  would then propose making Kite a primary source, with its own replay evidence; this trial cannot make that change.
- **STOP** otherwise; the subscription is not renewed, and the report says which measures failed.
- **EXTEND once** (by the missing sessions) only under the inconclusive rule above.
- A failure of the owner's side (no token that day) is a session lost to D2, not a session excluded. A session is never dropped for its outcome.

## Operating notes (the owner's side)

- The access token expires every day and needs a login; the trial assumes one manual step a day (D2). **The login is not automated with a stored password or TOTP.**
- Credentials: **superseded by amendment v2 (the "Credentials under v2" paragraph at the top); do not follow the v1 instruction.** v1 said to store `KITE_API_KEY` and `KITE_ACCESS_TOKEN` as repository secrets and to keep the API secret off the runners; under v2 the API key and secret are repository secrets used only through the `KITE_DATA_*` names, the day's token is an encrypted file, and `KITE_ACCESS_TOKEN` (a name the broker adapter reads) is never set.
- Cost: the subscription fee is the owner's; if the trial stops, the subscription is simply not renewed.

## What this trial does not decide

Orders (Kite's order API is not used), options data from Kite, making Kite the desk's only or primary feed (under v2 the attached feed keeps the existing feeds as its fallback, and KEEP decides only whether the attachment and the subscription stay), or any change to a limit, gate or size. Each is its own reviewed change if the trial earns it.
