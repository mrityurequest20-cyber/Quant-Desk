# Recording the session (after the paper desk)

On 6 Nov 2026 the owner stopped paper trading. Direction prediction tested as random, and the desk will trade again
only once the spike detector (docs/PREMARKET.md, Next) is built and tested. Everything that chose, gated or placed
paper trades was removed:

* the intraday engine, analyst, brain, playbook, learning memory and the LLM readers and teacher;
* the learning loop and its plan models (`autolearn` cycle, policy, plans, live gate);
* the expiry sleeves;
* the AI organisation (org, progress, self-review) and the learning bot's inventory;
* the old daily backtest system (`engine/`, `strategies/`, `backtest/`, `reporting/`, the GoCharting server);
* the Kite live-broker adapter.

The pre-cleanup code is preserved on the branch `archive/pre-cleanup-2026-11-06`. The journal branch, every release
and every pre-registered spec and result are untouched.

## What still records, every trading day

| Workflow | When (IST) | What |
|---|---|---|
| `record.yml` | 09:15 to 15:30 | Index and futures 1-minute bars and an option-chain snapshot a minute (`data record-session`), plus the chain tape (several expiries a minute, `intraday tape`). Kept as an artifact and as Parquet on `chains-YYYY`. After the close: option minutes (`option-minutes-*`) and liquid stocks' minutes (`stock-minutes-*`). |
| `kite-record.yml` | the session | Kite websocket ticks with depth, encrypted. Logs in to Kite by itself (`deploy/kite_autologin.py`, data only). No cron of its own: the scheduler starts it once a day; only the day's first run may log in (`deploy/kite_login_gate.py`), so a bad password costs at most one failed login a day. A manual **Kite token** run with no input also logs in: that is the owner's own act, and no agent runs it to retry after a failed login. |
| `collect-wide.yml` | 15:25, 15:45 | Stock option chains, and minutes for all five indices. |
| `record-stocks.yml` | 09:02 IST Mon to Fri (cron, best-effort) and the scheduler | **Every-minute option chains of every F&O stock** (about 200: each underlying with a stock future in Kotak's scrip master), 09:15 to 15:30 IST: the nearest expiry, 10 strikes each side of the money, with LTP, volume, open interest, best bid/offer and sizes, and the spot and implied volatility (a stock has no index quote, so its spot is taken from the chain's own put-call parity, marked as such in the snapshot), AND the five-level order book of every contract in that window. About 3 Kotak calls a chain, so the stocks are split over 10 parallel shards (each its own job and client, staggered inside the minute), two halves (hand-over 12:20). A job that holds no secret merges the day into three Parquet files (`<day>_stock_chains`, `_stock_depth`, `_stock_tape`) and a counts-only manifest on the `stock-chains-YYYYQn` release. Kotak only, data only. **Size, to watch:** a day is likely a few hundred MB compressed, tens of GB a year; the first real day sets the number. Coverage and failed attempts are in the manifest and in Data health. **Rate safety:** each shard paces itself (at most 2.5 Kotak calls a second), starts staggered inside the minute, and stops calling Kotak for 3 minutes after 6 failed chains in a row (a circuit breaker); a late scheduled start (after 15:00) does nothing; a day's files are written once and a later run cannot replace them. **Known small gaps:** the afternoon shards start only when every morning shard has uploaded (about 3 to 5 minutes around 12:20, roughly 1% of a day), and a late shard may file a stock's last stagger-offset minute under the next minute. **Rollback:** run the workflow by hand with `every_min` = 2 or 3, or disable it and remove `STOCK_WORKFLOW` from `deploy/scheduler.py`. |
| `evening-minutes.yml` | by hand only | MCX and currency futures' minutes from Kotak's candle API: **not scheduled**, because Kotak answers every MCX and currency candle request with HTTP 422 ("Historical data is not supported for this exchange", found on its first run, 7 Nov 2026). The MCX and currency evenings need Kite (historical candles, or ticks past 15:32). |
| `kite-evening.yml` | 00:05 IST Tue to Sat (cron, best-effort), or by hand | **MCX and currency evenings from Kite's historical API**: 1-minute candles with open interest of the nearest two futures of every MCX commodity and currency pair for the last 3 days (a run with `days` = 55 backfills; `daily_days` = 1900 adds the continuous daily history). A third automatic Kite login of the day, so a stricter gate than the recorder's (`deploy/kite_evening_gate.py`): first attempt only, the first run of the session day, and only if that day's `kite-record.yml` run succeeded with its login step succeeded. Kite's candles are licensed, so they are AES-256 encrypted with the API secret and kept as a 90-day artifact (`kite-evening-data`, decrypt with `deploy/kite-decrypt.sh`); the `evening-minutes-YYYY` release gets only the run's manifest (counts and statuses, never a price). The job that writes the release holds no Kite secret. A run without a proven login collects nothing, and Data health says the manifest is missing. |
| `agreement.yml` | 16:20 IST Mon to Fri (cron, best-effort), or by hand | **How often Kite and Kotak agree, one number a day.** The relay counts, in every Kotak cycle of the session, the instruments for which both sources hold a fresh price and how many differ by more than a spread explains (equities, futures, indices 0.5%, options 3%: the app's "differ" rule); it keeps the last week of days. This reads them with the read-only relay key and keeps one file a day on the `agreement-YYYY` release: counts and percentages, no price, no name. Two jobs: the one with the key cannot write, the one that writes holds no secret. Needs the Kotak poller on. |
| `fx-minutes.yml` | 22:30 UTC (04:00 IST), Mon to Fri | 1-minute bars of the FX majors and the rupee crosses (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, USDINR, EURINR, GBPINR, JPYINR, DXY) from Yahoo, UTC, re-reading the last five days (Yahoo keeps seven). `fx-minutes-YYYY` release. Public source, no secret. |
| `fx-daily.yml` | by hand | The same pairs' daily history from 2003, checked against the rate the ECB's reference rates imply (2% tolerance: a sanity check; weekdays most of a group of pairs lack are market holidays, not gaps; a one-day spike that reverses is set aside as a bad print and listed in the manifest's `quarantined`; any other move beyond 5% is flagged until a person lists it under `fx.accepted_moves`; the dollar index is checked against the ECB's rates through ICE's basket formula). `verified` is about the values; missing days are reported separately as `coverage` (`gappy` above 1% of weekdays) and do not fail a series. `fx-daily` release, one immutable dataset per run. |
| `data.yml` | evening | The NSE warehouse (bhavcopy, participant OI, FII/DII, the event calendar). |
| `premarket.yml` | 07:15 to 09:15 | The pre-market brief (on its own branch until merged). |

`scheduler.yml` and `wake.yml` start `record.yml` on time when GitHub's cron is late. Cancelling a recorder run keeps
it stopped for the day. The Cloudflare watchdog now checks the recorder (W1, W3), not the desk's heartbeat.

Sources: Kotak Neo (consumer key only: no login, no orders) when `KOTAK_CONSUMER_KEY` is set, else Yahoo bars and
NSE's public chain. The recorder never reads the Kite feed (licensed to the subscriber).

## Index chains: what the tape keeps (7 Nov 2026)

For NIFTY, BANKNIFTY, SENSEX, FINNIFTY and MIDCPNIFTY the chain tape (`record.yml`, `intraday.tape` in the config) records every minute 09:15 to 15:30: the nearest expiries (NIFTY 3, BANKNIFTY 2, SENSEX 2, FINNIFTY 1, MIDCPNIFTY 1) **and always the nearest monthly expiry** (`monthly: true`), ±20 strikes, with LTP, volume, open interest, best bid/offer and sizes, implied volatility, **and the five-level order book of every contract** (`depth_levels: 5`: it comes in the same Kotak quotes response, so no extra call). The books are archived beside the chains as `<day>_<part>_depth.parquet` on `chains-YYYY`. Data health: "index order books".

## Data sources and licences (decided 7 Nov 2026)

| Data | Source | Where it is kept | Why |
|---|---|---|---|
| Kite ticks, Kite historical candles (MCX/currency evenings) | Zerodha Kite Connect, licensed to the subscriber | **encrypted artifacts only** (AES-256, the owner's API secret), never a release or the repository; releases carry counts and statuses only | the licence; this repository is public |
| Kotak minutes, chains, bars | Kotak Neo market-data key | public releases (`chains-*`, `option-minutes-*`, `stock-minutes-*`) | existing arrangement, unchanged |
| NSE bhavcopy and other NSE files | NSE public files | `warehouse` release | public files |
| Daily history (indices, F&O stocks), FX daily and minutes | Yahoo Finance via `yfinance`; FX cross-checked against the ECB's public reference rates | public releases (`daily-history`, `fx-daily`, `fx-minutes-*`) | **decided 7 Nov 2026, delegated by the owner.** Asked whether Yahoo-derived data may sit in public releases, the owner answered, verbatim: "Okay, Rahu redistribution. If you feel that is fine, it's fine." ("Rahu" is the owner's dictation of "Yahoo".) The engineer judged it acceptable, as an **exception to rule 5 of `docs/ML_PHASE0.md`** (a restrictive-licence source is decided with the owner; here the owner delegated the call). Yahoo's terms are for personal use and do not grant redistribution, so this is an accepted, low, non-zero risk (at worst a takedown request), not a clearance. It is reversible: the datasets are rebuilt by one workflow run, and moving them to encrypted artifacts is a small change. Each manifest names its source. Nothing here is sold or served as a product. |

Rule of thumb for any new source: if its terms forbid redistribution and it is paid for or contractual (Kite), it stays encrypted; if it is public or merely discouraged (Yahoo), it may be published with its source named, and the choice is recorded here.

## The Build tab: a strategy builder (7 Nov 2026, paper only)

The app has a fifth tab, **Build**. Pick an index (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX), an expiry from the live board, and one of ten structures (long call/put, straddle, strangle, bull/bear call and put spreads, iron condor, iron butterfly); it prices the legs from the live quotes (buys at the offer, sells at the bid, the last trade flagged when there is no book), and shows what you pay or receive, the worst loss, the best profit, the break-evens, a payoff chart (at expiry and today), the Greeks, the costs to get in and out, and a tick-box list against the desk's own limits (risk per trade, premium outlay, lots, margin estimate, spreads). "Size it to the limits" picks the most lots that pass.

* **Defined risk only:** a structure that would leave a short call uncovered is refused.
* **One source of truth:** the limits, the cost model, the slippage model, the risk-free rate, the paper account's size and each index's lot size and strike step are read from `config/quantdesk.yaml` at publish time (`window.QD_TRADE`); a test compares the cost formula with `execution/costs.py`'s `CostModel` to the paisa, and the builder's built-in defaults with the config.
* **It sends no order, ticket or journal write.** The only network call is a read of the live board (`/live/snapshot`, with your key). It is a what-if tool; the paper ticket is a separate, reviewed piece.
* **Two checklists, kept apart.** The *sizing guide* uses the intraday desk's limits (`intraday.risk`) plus data quality: a leg counts as having a book only when both sides are quoted and not crossed (`0 < bid <= ask`), every quote (and the index price) must be at most `paper.max_quote_age_s` old (30 s; an unknown age fails), and the risk check counts the worst loss **plus the entry fees**, like the paper gate. *Could the paper desk open this today?* mirrors the paper gate (`quantdesk/paper/risk.py`): long options only (any structure with a short leg shows as a what-if, not open-able), an underlying on `paper.underlyings` (so SENSEX is a what-if), risk with fees, two-sided books, fresh quotes. The ticket still checks the day's loss budget, the drawdown halt and the displayed size against the live account.
* A crossed book, or a structure that would profit at every price (a bad quote, not a trade), is shown as a data error, never as a result.
* Known simplifications: worst loss and best profit leave out costs; held to expiry, an in-the-money long pays exercise STT (`costs.exercise_stt`), which is not modelled; Black-Scholes uses no dividend yield. If the page is published without the config (`QD_TRADE` missing) it says so and uses built-in defaults.
* The prices come from the private live relay, so the tab works only on the Cloudflare site with your key, like the Live tab.

## Keeping the schedule honest (7 Nov 2026)

- **First-run smoke tests.** A workflow that has never run is run once by hand on a weekend before its first trading day: the install, the secrets, the archive step. The 7 Nov smoke test of `record.yml` found that its recording step went red whenever the chain tape had already ended by itself (`kill` of a finished process fails under `bash -e`), which would have shown as a failed index recorder and a false P1 alarm every day; fixed, and a test now runs the workflow's own step script against stub processes.
- **Holidays.** The cron starts the index recorder on every weekday; it now also stops on an NSE holiday (10 Nov and 24 Nov 2026 are in the calendar), as the stock recorder, the tape and the scheduler already did.
- **Watchdog.** The Worker's watchdog now also checks that the stock chain recorder and the Kite tick recorder started (09:20) and ran (16:00) on every trading day, beside the index recorder, the wide collection and the warehouse.
