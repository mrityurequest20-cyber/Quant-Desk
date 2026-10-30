# Kite Connect market-data trial: criteria (written before any Kite data exists)

> **Amendment v2, 25 Oct 2026, before any Kite data exists (owner decision).** The websocket is **attached directly to the running paper desk**, not recorded in shadow: when
> `KITE_API_KEY` and the day's access token are present, Kite serves the index bars and the live index price, and the existing feeds (Kotak, then Yahoo) are the automatic
> fallback for every minute Kite lacks, for any minute whose close differs from the fallback's by more than 0.5%, and for any failure. History, the futures volume on index bars
> and the option chain stay as they are, and no tick-level order flow is added (that would change vote inputs and is its own reviewed step). Live trading stays off; no order
> method is used. The trial now asks whether to **keep** the attachment and the subscription, on the measures below. The separate tick recorder described further down is
> optional and secondary: it measures latency (C3) and real order flow (C4) and is not needed for the decision.
>
> **Credentials under v2 (supersedes the "Operating notes" below).** `KITE_API_KEY` and `KITE_API_SECRET` are repository secrets (added by the owner on 25 Oct). Inside jobs they are
> exposed only as `KITE_DATA_KEY`, `KITE_DATA_SECRET` and `KITE_DATA_TOKEN`, **never** as the names the broker adapter (`execution/kite.py`) reads, so the day's token cannot switch that
> adapter's credentials on. The API secret is read by exactly these steps: the daily "Kite token" workflow (it exchanges the owner's single-use `request_token` for the day's access token),
> the same workflow's encryption step, the live desk's optional "Kite token" step (it decrypts the file; the library install is a separate step with no secret), and, in each of the
> tick recorder's two jobs, its token step (it decrypts the same file) and its tick-encryption step (the recorder workflow arrives with its own pull request). The `--feed kite` option of
> the intraday command (`KiteIntradayFeed`, which reads the broker adapter's names) is not used by any workflow and is untouched; the attachment reads only the `KITE_DATA_*` names. The access token is stored
> AES-256 encrypted, with a key derived from the API secret, as one file on a `kite-token` branch of this (public) repository; every day's ciphertext stays in git history, the token expires
> within a day, and CBC carries no integrity check, so the desk accepts only a decrypted value of token shape (16 to 64 letters and digits) before exporting it. No password or TOTP is stored. No
> order method is called anywhere (a test greps for it). **Disclosed for the owner's decision:** `docs/AUTONOMY.md` says the engineer never touches broker credentials; these are
> data-only credentials used on the owner's explicit instruction, and the owner may wish to write that exception into their own file.
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
> compared with them, never overlaid, and fills only a minute they lack. Kite's minutes are kept out of the recorder (licence), and the other feeds' own history for today fills those holes every
> 30 minutes and at the close (`fill_bars` adds only what is missing), so the recorded file is whole. An end-to-end test runs one day plain and one day under Kite and asserts that the recorded
> 15:00 to 15:29 bars, the settlement price and the official close are identical. Kite's live price still serves exits after 15:00, and Kite remains the *measure* of whether the late index is
> frozen (E3).
>
> **Measures for the attached desk (fixed now).** Read from the journal's INFO events of category `feed` whose message starts `kite feed counters` (written every 5 minutes by the engine, one per
> minute, as JSON of the feed's own counters). The counters are cumulative **per process**: each event carries `started`, the runner's start stamp, and the morning and the afternoon runner are read
> separately. Rates are read from **differences between a runner's first event and its last event at or before 15:00**, so a runner that starts at 12:20 is not credited with the morning and the
> five-minute reading resolution is the only unmeasured margin. **Time no runner covers is unserved time, not excluded time:** the day's E1 denominator is every minute from 09:20 to 15:00 (3 symbols each), a minute counts as served only if a runner's window (first event to last event at or before 15:00) contains it and Kite served it, so a runner that starts late, dies early or never logs an event costs the day its E1 (and the hole counts in E2 as polls not served from Kite).
>
> | # | Measure | How it is read | Pass if |
> |---|---|---|---|
> | E1 | **Kite share of minutes** | Δ`minutes` ÷ (3 symbols × Δ minutes elapsed between the runner's first event and its last event at or before 15:00); the day's value weights each runner by its elapsed minutes | at least 99% in a session for that session to pass E1 |
> | E2 | **Fallback dependence** | Δ(`fallback_polls` − `sampled_polls`) ÷ Δ`polls`, same window: polls on which the other feeds had to be asked because Kite could not serve (every tenth otherwise-Kite-only poll asks them on purpose, to give E4 a denominator, and is counted apart) | at most 1% of polls |
> | E3 | **Late-session index** | at the day's last event, `late_kite_moved` ÷ `late_fb_flat`: of the minutes from 15:15 to 15:28 in which the other feeds' NIFTY or BANKNIFTY bar was flat (open = high = low = close; Kotak's frozen window), the share in which Kite's bar was not | at least 90% for that session to pass E3. The denominator is the other feeds' flat minutes whether or not Kite had a bar, so a Kite outage in that window fails it. If `late_fb_flat` is under 20 in a session, that session is "not measured" for E3: it is left out of E3's count (neither a pass nor a fail), and KEEP needs E3 measured in at least 5 counted sessions |
> | E4 | **Disagreement** | Δ`rejected` ÷ Δ`compared`, same window as E1: Kite minutes not used because they differed from the other feeds' bar by more than 0.5% (or, for a minute they lack, from the minute before it), over the minutes checked. Checks happen on the first poll, on every hole and on one poll in ten. Live-price rejections are counted apart (`ltp_rejected`). The rejected minutes (listed by stamp, never price, in the counters' `rejected_minutes`) are cross-checked by hand against Kite's own historical candle for that day | at most 0.5%, and none that the hand check shows was Kite right and the other feed wrong |
> | E5 | **No harm** | the counter `faults` (a fault inside the Kite logic that was handed to the other feeds) and any engine ERROR or CRITICAL event naming `kitelive` | none |
> | E6 | **Manual steps** | the daily request_token run (D2 below) and any restart | at most one per trading day; a day with no token counts against E1 and E6 |
>
> Kite minutes are not served on a minute whose first tick came more than 15 s after the minute began (a late connect or a reconnect) and only inside 09:15 to 15:29; a live price more than 0.5%
> from the last served close is used only if the other feed's price agrees; none of these is a trial measure, they are the safeguards the review required.
>
> **Decision on 20 Nov (fixed now):** KEEP if E1 to E4 pass in at least 90% of counted sessions (E3 over the sessions in which it was measured, and at least 5 of those; "a session passes E1 to E4" means each of its four thresholds, E1 at 99%), E5 has no failure, and E6 holds; otherwise REMOVE the attachment (one config line,
> `intraday.kite.live: false`) and do not renew the subscription. EXTEND once, by the sessions missing from 10 counted or from 5 E3-measured sessions (whichever needs more; the subscription ends about 25 Nov, so an extension is decided by the owner), if fewer than 10 were counted or fewer than 5 had E3 measured; after the one extension, REMOVE if still short. A hand-checked candle comparison (Kite's own
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
| C3 | **Latency** | receipt time minus exchange timestamp, per tick. Exchange stamps are whole seconds, so the figure carries about +0.5 s median and +1 s p99 of rounding bias, and the recorder does not measure the runner clock's offset | **reported, not a pass condition** (an upper bound on latency, not its measurement; the attached desk's decision does not use it) |
| C4 | **Real order flow** | descriptive only: correlation of the minute CVD built from tick-rule trades with the desk's close-location CVD; no threshold | reported |
| D1 | **Reconnects** | websocket disconnections per session | reported; a disconnection that leaves a run of more than 3 minutes without ticks fails A2 |
| D2 | **Manual steps** | times the owner had to act (new access token, restart) | at most one per trading day (the daily token) |
| D3 | **Volume** | recorded size per session | reported (a release asset must stay under 2 GB) |

A session **passes** if A1, A2, B1 and B2 pass for every recorded instrument (indices and futures). C3 (latency) is reported and is not a pass condition. The trial **has value** if C1 passes in at least 90% of counted
sessions, or C2 passes in every counted session in which it was measured, because either would fix a weakness the desk has today.

## The decision on 20 Nov (the rule is fixed now; nobody chooses after seeing the data)

- **CONTINUE as a shadow source** (still no effect on trading) if at least 90% of counted sessions pass, the trial has value, and D2 holds. A **separate, independently reviewed change**
  would then propose making Kite a primary source, with its own replay evidence; this trial cannot make that change.
- **STOP** otherwise; the subscription is not renewed, and the report says which measures failed.
- **EXTEND once** (by the missing sessions) only under the inconclusive rule above.
- A failure of the owner's side (no token that day) is a session lost to D2, not a session excluded. A session is never dropped for its outcome.

## Operating notes (the owner's side)

- The access token expires every day and needs a login; the trial assumes one manual step a day (D2). **The login is not automated with a stored password or TOTP.**
- Credentials: `KITE_API_KEY` and `KITE_ACCESS_TOKEN` as repository secrets; the API secret never leaves the owner's machine.
- Cost: the subscription fee is the owner's; if the trial stops, the subscription is simply not renewed.

## What this trial does not decide

Orders (Kite's order API is not used), options data from Kite, a switch of the desk's feed, or any change to a limit, gate or size. Each is its own reviewed change if the trial earns it.
