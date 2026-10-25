# Kite Connect market-data trial: criteria (written before any Kite data exists)

> **Amendment v2, 25 Oct 2026, before any Kite data exists (owner decision).** The websocket is **attached directly to the running paper desk**, not recorded in shadow: when
> `KITE_API_KEY` and the day's access token are present, Kite serves the index bars and the live index price, and the existing feeds (Kotak, then Yahoo) are the automatic
> fallback for every minute Kite lacks, for any minute whose close differs from the fallback's by more than 0.5%, and for any failure. History, the futures volume on index bars
> and the option chain stay as they are, and no tick-level order flow is added (that would change vote inputs and is its own reviewed step). Live trading stays off; no order
> method is used. The trial now asks whether to **keep** the attachment and the subscription, on the measures below. The separate tick recorder described further down is
> optional and secondary: it measures latency (C3) and real order flow (C4) and is not needed for the decision.
>
> **Credentials under v2 (supersedes the "Operating notes" below).** `KITE_API_KEY` and `KITE_API_SECRET` are repository secrets (added by the owner on 25 Oct). The API secret is read by
> exactly three steps: the daily "Kite token" workflow (it exchanges the owner's single-use `request_token` for the day's access token), the same workflow's encryption step, and the
> live desk's optional "Kite token" step (it decrypts the file). The access token is stored AES-256 encrypted, with a key derived from the API secret, as one file on a `kite-token`
> branch, and is masked in the logs before it is exported; it expires within a day. No password or TOTP is stored. No order method is called anywhere (a test greps for it).
>
> > **Measures for the attached desk (fixed now), over counted sessions (a weekday on which the websocket started; 26 to 30 Oct are shake-down and not counted; read-out 20 Nov):**
>
> | # | Measure | Source | Pass if |
> |---|---|---|---|
> | E1 | **Kite share of minutes** | the feed's own counters, in the session review: minutes served from Kite over minutes in the session | at least 99% of the session's minutes, in every counted session |
> | E2 | **Yahoo dependence** | polls served by Yahoo, in the review (19 Oct: 190 of 570) | at most 1% of polls |
> | E3 | **Late-session index** | `frozen_minutes` on the desk's recorded index bars for 15:15 to 15:28 (Kotak alone: 14 of 14 frozen) | at most 10% of those minutes frozen |
> | E4 | **Disagreement** | Kite minutes rejected for differing from the fallback by more than 0.5%, from the review | at most 0.5% of minutes, and none that a later check shows was Kite right and the fallback wrong |
> | E5 | **No harm** | engine ERROR or CRITICAL events whose text names the Kite feed; sessions where a Kite fault changed a trade the fallback would not have | none |
> | E6 | **Manual steps** | the daily request_token run (D2 below) | at most one per trading day |
>
> **Decision on 20 Nov (fixed now):** KEEP if E1 to E4 pass in at least 90% of counted sessions, E5 has no failure, and E6 holds; otherwise REMOVE the attachment (one config line,
> `intraday.kite.live: false`) and do not renew the subscription. EXTEND once by the missing sessions if fewer than 10 were counted. A hand-checked candle comparison (Kite's own
> historical minutes against the desk's recorded bars, as B1 below) is run on the first and last counted weeks as a cross-check on E4.

**Status:** criteria v1, committed alone before any code or data. Registered 24 Oct 2026. The owner pays for one month of Kite Connect market data; the engineer records it
from Monday 26 Oct for four weeks and reports on 20 Nov. **Nothing in this trial places an order, changes a feed the desk trades on, a limit or a gate.** Live trading stays off.

## Why a trial

Three weaknesses of the desk's current data are visible in its own journal (week of 19 to 23 Oct):

1. **Yahoo as a fallback.** On 19 Oct, 190 of 570 polls came from Yahoo; Yahoo returned no bars from 15:04 and the engine's three-failures rule halted entries (F-19-1).
2. **Kotak's index series freezes** from 15:15 to 15:28 in every session while the future keeps trading (F-02); those minutes are kept out of grading.
3. **Order flow is approximated.** CVD comes from where a minute bar closes, not from trades.

Kite Connect offers a websocket with exchange timestamps, full-mode ticks (last price, volume, open interest, market depth) and its own historical minute candles. The trial asks, with
numbers fixed in advance, whether it is better than what the desk has, and what keeping it would cost in effort.

## What is recorded (a separate process, never the trading path)

- **Instruments:** NIFTY 50, NIFTY BANK, INDIA VIX (indices), and the near-month future of NIFTY and BANKNIFTY. Options are not recorded in the first two weeks.
- **Per tick:** instrument token, exchange timestamp, receipt time (the recorder's clock), last price, cumulative volume, open interest (futures), best bid and ask. One-minute bars are
  built from the ticks by the recorder and kept beside the raw ticks.
- **After the close:** Kite's own historical minute candles for the same instruments are fetched once, as the reference for the comparison.
- **Where it lives:** a private release asset set (`kite-trial-YYYY`) and nowhere else. Kite market data is licensed to the subscriber: it never enters the repository, a public
  release or a model card, and no derived table is published. Only counts and ratios (the numbers below) may be quoted in the repository.
- **How it runs:** its own process, started beside the desk, with its own credentials. A recorder failure, a token that has expired or a dropped connection never reaches the desk: no
  shared state, no import from the engine, no exception that propagates. The credential is read from the environment; nothing is written to a log.

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
| C3 | **Latency** | receipt time minus exchange timestamp, per tick | median at most 1.0 s and 99th percentile at most 3.0 s |
| C4 | **Real order flow** | descriptive only: correlation of the minute CVD built from tick-rule trades with the desk's close-location CVD; no threshold | reported |
| D1 | **Reconnects** | websocket disconnections per session | reported; a session with a disconnection longer than 60 s fails A2 anyway |
| D2 | **Manual steps** | times the owner had to act (new access token, restart) | at most one per trading day (the daily token) |
| D3 | **Volume** | recorded size per session | reported (a release asset must stay under 2 GB) |

A session **passes** if A1, A2, B1 and B2 pass for every recorded instrument (indices and futures) and C3 passes. The trial **has value** if C1 passes in at least 90% of counted
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
