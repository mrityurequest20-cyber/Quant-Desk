# Data pipelines and the app: what is ready, what is not (7 Nov 2026)

A read of the code and the workflows, not a test run on a trading day. Anything marked **not verified** has not been seen working on a live session.

## The app (four tabs)

| Tab | What it is | Where its data comes from |
|---|---|---|
| Live | Every price the recorder and the Kotak poller watch, every 5 s; per instrument a one-minute chart and, for an underlying, its option chain | the Worker's `/live/*` (private, your key), see `docs/LIVE.md` |
| Today | The pre-market brief | the `premarket` branch, built 07:15 to 09:15 IST |
| History | The record of the retired paper desk: trades by day, performance, session reviews. Read-only | `data.json` on the published site |
| Data | Whether each feed is delivering, and what each recorder keeps | the relay's `/live/health`, the brief, and the standing description below |

The header pill shows the live feeds' state on every tab (Live, Delayed, No feed, Closed, Relay off, Key?, Public copy). Desk, Chart, Brain and Feed were removed: the desk that fed them stopped on 6 Nov 2026 and they showed frozen data.

## What is recorded

| Channel | When (IST) | Kept as | Judged by |
|---|---|---|---|
| Index and futures minutes, option-chain snapshot a minute, chain tape | 09:15 to 15:30 | Parquet on the `chains-YYYY` releases | Data health (19:00, 22:15) |
| Kite ticks with depth | to 14:45, then 14:45 to 15:32 (two chained jobs) | encrypted artifacts (never published) | arrival only: the content is encrypted |
| Stock option chains (once, 15:25), five indices' minutes, and **stock option minutes** (±5 strikes, nearest 2 expiries, 20 stocks) | 15:25, 15:45 | releases (`option-minutes-*`) | Data health (the stock option minutes since 7 Nov) |
| Stock cash, near-month and **next-month** futures minutes (50 stocks; the next month is a separate file, `stocks_futures_next`, built 7 Nov) | after the close | `stock-minutes-*` | Data health |
| FX majors and rupee crosses: 1-minute bars (the last 5 days re-read each night) and daily history from 2003 | `fx-minutes.yml` (22:30 UTC weekdays), `fx-daily.yml` (by hand) | `fx-minutes-YYYY`, `fx-daily` | Data health; the daily series also checked against the ECB's reference rates |
| MCX and currency evening minutes (nearest two futures of each name, with open interest) | `kite-evening.yml`, 00:05 IST Tue to Sat, from Kite's historical API (built 7 Nov, **not yet run on a real session**); Kotak's candle API cannot do it (HTTP 422), so `evening-minutes.yml` stays a manual tool | encrypted artifact (`kite-evening-data`, licensed data) plus a counts-only manifest on `evening-minutes-YYYY` | Data health (the manifest) |
| NSE warehouse (bhavcopy, participant OI, FII/DII, events) | evenings | warehouse tables | Data health |
| Pre-market brief | 07:15 to 09:15 | `premarket` branch | Data health |

## What the live view can take

* Kite: the recorder pushes changed quotes every 5 s; Kotak: the relay polls, at most 40 calls a cycle (about 1,000 instruments a cycle, 25 a call). The board holds up to 6,000 names. Chains: index chains every cycle, stock chains in turn.
* One close a minute per instrument for the last two trading days, up to 800,000 minutes in all, kept in the relay's storage and written every five minutes.
* Two sources per name, the fresher shown, a flag when they differ by more than a spread explains.

## Gaps, in the order they matter

1. **The live prices are not a record.** The relay keeps the latest quote and two days of minute closes. If the record of a day has a hole (the recorder fell over), the live view cannot fill it afterwards. Kotak live prices are stored nowhere.
2. **Evenings are collected after the close, not recorded live (built 7 Nov, not yet run).** MCX (to 23:30) and currency (to 17:00) futures are subscribed and recorded as ticks in the Kite wide universe only while the Kite recorder runs (to 15:32). Kotak cannot fill the evening: its candle API answered all 38 MCX and currency requests of the 7 Nov probe with HTTP 422 (its scrip master and chain endpoints do work for both segments, so Kotak could serve them *live*). The evening job reads Kite's historical candles after midnight (`kite-evening.yml`): a third automatic login of the day, which the gate allows only on a day the recorder's own login succeeded, so it does nothing until Monday's first Kite session proves the login path. Candles are licensed, so they are encrypted artifacts and only a counts-only manifest is public. Still no live evening prices, and no MCX or currency options.
3. **No daily-history charts.** A chart is today and yesterday only. Longer history exists in the warehouse and the releases but is not drawn in the app.
4. **Kite and Kotak agreement is now stored (built 7 Nov, not yet run).** The relay tallies it every cycle of the session and `agreement.yml` keeps one file a day (counts only); Data health judges it. It starts counting once the Worker redeploys and the Kotak poller is on. What it does not do: compare the recorded minute bars of the two sources, only the live prices.
5. **The Today tab depends on the `premarket` branch.** It had never been built (the workflow had never run); a manual run on 7 Nov created it and the brief is public. It rebuilds every weekday from 05:30 IST.
7. **The Kite recorder has never recorded a session.** All five earlier runs started after the close; Monday 9 Nov is the first run of the automatic login, and the scheduler starts it once a day and never retries (a wrong password retried would lock the account).
8. **Stock option breadth.** Minute candles cover 20 stocks of about 200.
6. The Kite tick content cannot be checked by the health run (encrypted); `kite-compare` measures it separately.

Next, in this order: record past 15:32 for MCX and currency (a separate live-only workflow with its own concurrency group, leaving the pre-registered Kite trial alone), then a stored daily agreement number between the two sources, then daily-history charts.

## History (added 7 Nov 2026)

| Series | Where | From | Verified by |
|---|---|---|---|
| Daily OHLCV, 8 indices and the F&O stocks, split/bonus adjusted | `daily-history` release (`daily-history.yml`, by hand) | 2013 | Yahoo is the source on a cloud runner (NSE blocks it); the warehouse's own NSE files are the independent cross-check: every NSE index from 2019, and stocks from 8 Jul 2024 (the first month `fo_stock_opts` carries the underlying price). The manifest records the span each check covers. SENSEX and BANKEX stay unverified: there is no independent BSE index source. |
| NSE end-of-day tables (F&O bhavcopy, index closes, participant OI, FII/DII) | `warehouse` release (`data.yml`, daily) | 2019 | current to the last trading day |
| Index and futures minutes, option-chain snapshots | `chains-YYYY` releases (`record.yml`) | Oct 2026 | Data health |
| Option, index and stock minutes (Kotak backfill) | `option-minutes-*`, `stock-minutes-*` | about 30 days back at each run | Data health |
| NIFTY and BANKNIFTY index minutes | `external-aeron7` | 2007 to early 2023 | research only: see docs/EXTERNAL_DATA.md |

Known holes: no index minutes between early 2023 and Oct 2026; no MCX or currency-futures history (forex spot has its own record from the first run of `fx-daily.yml`); stock cross-checks cover July 2024 onward only.
