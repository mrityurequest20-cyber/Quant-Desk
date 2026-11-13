# The live view

Real-time prices in the app, refreshed every 5 seconds, for **everything the Kite recorder watches**: not five symbols but the whole F&O universe. **Private and display only**: Zerodha's market data is licensed to the owner, so only the owner's key reads it, and nothing on this path can place an order or reach the paper desk.

```
Kite websocket (every tick)                       Kotak Neo REST (consumer key: no daily login)
   | kite-record.yml (GitHub job)                    | polled INSIDE the Worker's Durable Object, on an alarm, every ~5 s
   |  (1) every tick -> Parquet, encrypted: the record|  quotes (price, 5-level book, volume, OI) + index option chains
   |  (2) every 5 s POSTs changed quotes, in batches  |  what to poll: the "universe", built daily and pushed to /live/universe
   v  source "z"                                      v  source "k"
              Cloudflare Worker + one Durable Object: per instrument the latest quote of EACH source
              fresher source shown, the other one kept; both fresh and apart by more than a spread = flagged
                                          v
              App "Live" tab   GET /live/snapshot (needs LIVE_READ_TOKEN), every 5 s;  GET /live/health: the state of each source
```

## Two sources, so one cannot be the single point of failure

* **Kite** gives real ticks and depth for the busiest instruments, and the permanent record (Parquet). It needs a fresh token every morning, and its recorder runs as chained GitHub jobs (hours and hand-over gaps below).
* **Kotak** needs no daily login and runs inside the Cloudflare Worker, so no GitHub runner, cron or job limit stands between it and the app. It carries the universe it is given (price, volume, open interest, percent change and a five-level book) and is the fallback for everything. **Capacity is real, not unlimited**: Kotak allows 25 instruments a quotes call and 25 requests a second (as noted in `quantdesk/intraday/kotak.py`), the poller makes at most 40 calls an alarm (the free plan allows 50 subrequests) at about 22 a second, so one cycle refreshes at most about 1,000 instruments (7 index spots one to a call, 25 per call for the rest, chains one call each). A longer universe is rotated: the quote calls and the index chains run in every cycle, and the stock chains (below) take the remaining slots in turn, so each stock chain is refreshed every ceil(chains / free slots) cycles, a few minutes, while spot and futures prices stay on the fast cycle. The board holds at most 6,000 names.
* **Per instrument** the board keeps each source's latest quote and its own arrival time, shows the **fresher** one with its source (Kite or Kotak under the name), and fills a missing book from the other. If both are fresh (under 60 s) and their prices differ by more than 0.5% (3% for an option, whose spread is wide), the row shows **⚠ the two sources differ** and `/live/health` counts it: that is the cross-check on data correctness.
* **Fresh means moved.** A Kotak quote's arrival time is refreshed only if its price, volume, open interest or (when both have one) its book changed since the last cycle, so a holiday, a closed market or a frozen instrument grows an age instead of looking live; an instrument asked for as a quote and also covered by a chain is taken from the quote only (the chain row is dropped), so two endpoints that differ a little cannot alternate and look like movement. The first time a price is seen its age is taken from Kotak's own timestamp when it has one (clamped to 12 hours), so a last-known price after a restart is as old as it really is. A Kite quote is refreshed when a new tick arrives.
* **The board cannot fill for good.** A quote not seen for 4 days (an expired weekly option, a retired symbol) is dropped (shorter would empty the board over a weekend, when the last prices are worth showing, aged), whenever the alarm runs and when a full board is asked for a new name; names refused because the board is full are counted in `/live/health` (`kotak.refused`).
* **Kotak is not hammered.** If it refuses the key the poller backs off (a minute, doubling to 15 minutes); on a rate limit it waits 15 s; an HTTP 200 that carries a fault, or no usable rows, counts as a failure, and a redirect is never followed (the key travels in a header). The key is shared with the minute recorder and the backfills, which run on GitHub runners: together they could exceed Kotak's 25 requests a second at times, and the poller does not retry a 429 inside a cycle. If the key is removed the alarm stops.
* **Known limit, not fixed:** if Kite's re-subscribe snapshot at the open is the previous close while Kotak is already quoting a gap-up, many instruments can show the disagreement flag for a few minutes. The watchdog's disagreement alert needs more than 5% of at least 20 instruments, and its first look is at 09:50.
* **A source can die without the view dying.** If Kite has no token, or its job is between chained jobs, Kotak still fills the view; if Kotak is refused or down, Kite does. `/live/health` and the strip under the status pill say which is which. The poller's alarm always re-arms itself, whatever a cycle did; the Worker's own 10-minute cron re-arms a lost one.
* The poller calls only Kotak's two read endpoints (quotes and option chain). It holds the consumer key as a Worker secret and never logs, returns or echoes it (a test greps for this and for every order-style endpoint).
* Both live sources name an option the same way (`NIFTY12NOV2624500CE`, `option_name` in `kite_universe.py` and `optionName` in `kotak.js`; a test pins them equal), otherwise prices from the two could never land on one row.
* **What Kotak is asked for (the universe)** is built by `python -m quantdesk data kotak-universe --push` (`quantdesk/data/kotak_universe.py`, workflow `.github/workflows/kotak-universe.yml`, 08:00 and 09:00 IST on weekdays): the index spots by name, the cash price of every NSE F&O stock, the near-month future of every F&O underlying (stocks and the four NSE indices) and the nearest two expiries' option chains of each index (a chain call returns every strike near the money with last price, volume and open interest). It uses the same names as the Kite universe, so both sources meet on one row. It is fail-soft by part (a gap is counted, not fatal) and pushes to `/live/universe` with the ingest token.
* **If the build is late or fails**, the relay keeps the last universe it was given (it is stored), and its own 10-minute cron **asks GitHub to run the workflow** whenever today's universe is missing on a weekday after 08:00 (at most once in 40 minutes). Until a first universe exists the poller idles and `/live/health` says "no universe". An expired futures contract in yesterday's universe simply returns no row.
* The GitHub secret `KOTAK_CONSUMER_KEY` already exists (the minute recorder uses it); `LIVE_URL` and `LIVE_INGEST_TOKEN` are the ones from the table below.

## What is watched (quantdesk/data/kite_universe.py)

| Segment | What | How many (about) |
|---|---|---|
| Index | Nifty 50, Bank Nifty, India VIX (core) and FINNIFTY, MIDCPNIFTY, NIFTY NEXT 50, SENSEX, BANKEX | 8 |
| Futures | the near-month future of **every** NSE F&O underlying (indices and stocks), plus the BSE index futures | 200+ |
| Stocks | the cash price of every F&O stock | 200 |
| MCX | the near-month future of every MCX commodity | tens |
| Currency | the near-month future of every currency pair (CDS) | a handful |
| Options | NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY: the nearest two expiries, 10 strikes each side of the money, calls and puts | about 340 |

* An index option chain is thousands of contracts, so only the window around the money is streamed. The full chains of the five indices are recorded every minute by the Kotak recorder.
* Kite allows a limited number of instruments on one websocket (3,000 as far as I know; Kite's documentation cannot be reached from the build machine, so this is **not verified**). The list is cut at 2,500 and options go first, so a futures or spot price is never the one dropped.
* The five core instruments (Nifty, Bank Nifty, VIX and the two index futures) are recorded in Kite's FULL mode, which carries five levels of depth and the exchange timestamp. Everything else is in QUOTE mode (price, volume, quantities, open/high/low/close, no depth, no open interest): bid and ask show under the name only for the core.
* **Hours.** The recorder's two chained jobs run from about 08:55 to 15:32 IST, so today the Live tab has data for NSE and BSE F&O hours only. MCX trades until 23:30 (23:55 in US daylight time) and currency until 17:00; those instruments are subscribed and recorded while the jobs run, but their evening hours are **not covered until the recorder chain is extended** (the planned chained jobs from `quantdesk/markets`, M3/M4). Outside the jobs the tab reads stale.
* **Where the wide data is stored.** The pre-registered Kite trial (`docs/ml/KITE_TRIAL.md`) measures five instruments, and its measures and thresholds must not change mid-trial. So the wide universe is recorded **apart**: its own slim rows (price, quantities, open/high/low/close, percent change, about 1 KB each) and its own bounded buffer, written to `wide/wide_<tag>_<part>.parquet` inside the same encrypted artifact. `tokens.json`, `ticks_*.parquet` and the folder's top-level parquet bytes are the trial's five instruments only; the wide token map lives in `universe.json`. A wide write that fails or overflows is an event in `events.jsonl` (`wide`, `wide_overflow`) and never fails the run; the five core instruments' rules (a lost tick fails the run) are unchanged. A test runs the trial's own `session_report` on a session that has both.
* If a whole segment, or the wide universe, cannot be built (a missing exchange list, an unreadable price), that part is skipped and written to `universe.json` beside the ticks; the five core instruments and the recording never depend on it. `KITE_WIDE=0` switches the wide part off.

## Charts and option chains (the instrument view)

Tap any row on the Live tab. The view shows the quote (last, change, bid and ask with sizes, volume, open interest, the other source's price), a **chart of today's prices**, links to what the instrument relates to (an option to its underlying and future, a stock to its future), and for an underlying its **option chain**: the expiries the feeds carry, calls and puts side by side, the strike nearest the price shaded, near-the-money by default and "show all" for the rest.

* The chain is built in the app from the names already on the board (`NIFTY12NOV2624500CE` is NIFTY, 12 Nov 2026, strike 24,500, call). It shows exactly the strikes the feeds carry: index options near the money (Kite) and the nearest two expiries of each index chain (Kotak). A stock's chain (nearest expiry, the seven strikes around the money) comes from the Kotak universe, below, and refreshes much more slowly than the prices.
* The chart is **one close per minute**, kept by the relay (`deploy/cloudflare/series.js`) from the moment a *changed* price arrived at the relay's clock. A quiet instrument or a dead feed leaves a flat stretch or a gap, never invented points. Day high and low are the highest and lowest of those closes, not the exchange's figures, and the view says so.
* The relay keeps the **last two trading days** of each instrument (the previous close is the baseline for the day's change), at most 16 hours a day and 800,000 minutes in all (about 29 MB of the object's 128 MB). Once that total is reached a name that is already charted gives up its own oldest minute for each new one, and a new name is not charted until room is made (a new trading day, or a name unseen for 4 days leaving). It is stored in 48 shards in the object's storage, written at most every five minutes, one shard at a time and only if changed (a shard that fails to write is retried, and does not stop the others), and read back (re-checked, because storage is not trusted) after an eviction, so a chart opened in the evening still has the day. An instrument not seen for 4 days loses its chart with its price.
* `GET /live/series?name=NIFTY` answers only to the read key, only for a plain instrument name. It is display only, like everything here.
## Stock option chains (Kotak)

Kite's wide universe carries index options only. For the **F&O stocks** (up to 250, about 200 exist) the Kotak universe (`quantdesk/data/kotak_universe.py`) asks for the **nearest unexpired expiry's chain**, and the poller keeps the **middle seven strikes** of what comes back, calls and puts: about 14 option names a stock at a time, about 2,800 for 200 stocks **to start with**: that is an initial figure, not a ceiling, because when the money moves and the window of strikes moves with it, the strikes it left stay on the board (showing their age) until they go stale (4 days) or expire. "Middle" is an **approximation** of three either side of the money: the API returns the strikes around the money, but a strike with no price is dropped before the middle is taken, so on an uneven list the shaded row can be a strike or two off. They have one source (Kotak), so there is no second price to cross-check.

* Refresh rate, honestly: the quote calls and the index chains run in **every** cycle (a few seconds); the stock chains take the calls that are left in turn. At the expected size about 4 calls a cycle are free, so each stock chain comes round in about 4 to 6 minutes; **when the prices leave only one call free it can be up to 20 to 25 minutes**, and the option rows' age on the Live tab can show it. Note what that age is: how long since the price last **changed**, so an option that has not traded looks old whatever the poll interval. Prices stay on the fast cycle either way. If the prices and index chains alone use all 40 calls of a cycle, there is no tier and everything rotates together, slower.
* The board's cap is 6,000 names (it held 4,000 before this) and a universe may carry 400 chains. At a roll, **expired option contracts leave the board** (from the day after their expiry; the expiry day itself is still shown), so the old expiry's names do not keep the room the new expiry needs.
* A stock whose expiries cannot be read is skipped and counted in the build's gaps, never named; the rest are unaffected. **Two limits mean some stocks can have no chain:** the build stops after **10 expiry lookups fail in a row** (Kotak refusing or not answering: the stocks after that point get none that day, one gap line says how many), and it covers at most **250** stocks. A stock name the relay would not accept (a dot or more than 24 characters) is counted as excluded, never silently dropped.
* Not verified from the build machine: that Kotak's chain endpoint answers for stock underlyings the way it does for indices, and the exact strike window it returns. The first real build (Monday) shows the counts; `/live/health` has the universe's chains and the poller's errors.

## Switch it on (once, five values)

Make two random strings of at least 24 characters, different from each other (`openssl rand -hex 24` twice). Call them INGEST and READ.

| Where | What | Value |
|---|---|---|
| Cloudflare dashboard, the `quant-desk` Worker, Settings, Variables and Secrets | secret `LIVE_INGEST_TOKEN` | INGEST |
| same place | secret `LIVE_READ_TOKEN` | READ |
| GitHub, Settings, Secrets and variables, Actions, **Secrets** | `LIVE_INGEST_TOKEN` | INGEST (the same string) |
| GitHub, same page, **Variables** | `LIVE_URL` | `https://<your worker>.workers.dev/live/ingest` |
| Cloudflare dashboard, same Worker, Variables and Secrets | secret `KOTAK_CONSUMER_KEY` | the Kotak Neo consumer key (the one already saved as the GitHub secret of the same name) |

All three Cloudflare values must be saved as **Secrets** (Type: Secret), not plain Text variables: every deploy of the Worker removes a Text variable that `wrangler.jsonc` does not list, and secrets survive. If `https://<your worker>.workers.dev/live/snapshot` answers `{"error":"the live view is not switched on"}`, the same answer has a `why` saying which piece is missing (the Durable Object, either token, a token under 24 characters, or the two being the same string) and the names of the Worker's own `LIVE*` / `KOTAK*` settings, so a misspelt name shows. It never shows a value. `{"error":"no"}` (a 401) means it is switched on and only the key is missing.

Then open the app on the Cloudflare site (never the github.io address: the tab refuses to send the key there), go to **Live**, and type READ once. Until the secrets exist the relay answers 503 and the recorder pushes nothing; recording is unaffected either way.

## Honest limits

* **Age** is measured on the Worker's clock from when each price arrived, so a dead feed shows as old whatever the phone's clock says. Green is under 15 s, amber under 2 minutes, then "No feed". The recorder pushes a quote when a new tick arrived for it, and the relay keeps only the latest. A price that has not ticked simply grows older. If Kite resends a last-known tick when it connects, that one tick can look fresh until the next real one arrives; the exchange timestamp `t` is sent for the core instruments so this can be checked.
* Between the recorder's chained jobs (a gap of seconds to minutes) and outside market hours the tab reads stale. That is the truth, not a fault.
* The relay holds the latest snapshot in memory **and in its storage** (since 13 Nov 2026: 32 shards, written every five minutes, only the shards that changed). Before that it was memory only, so an eviction after the close, or the redeploy every merge to main makes, left the app with nothing until the next open. Now a restart reads the board and the order books back, every quote re-checked as a push is and each with its own arrival time: after hours the app shows the last prices, aged, never as live. Kotak and the feeds still refresh it as they tick. The permanent record is the encrypted Parquet artifact (90 days, GitHub's maximum). Nothing licensed is committed to the repository, written to a release, or published to Pages. Keeping ticks longer needs a private store (Cloudflare R2): not built.
* A 5-second snapshot of the last tick, about a second behind the exchange. Not tick by tick.

## Safety

* Two keys, two doors: the recorder's key can write but not read; the app's key can read but not write. Both are compared in constant time. Fewer than 24 characters, equal keys, or a missing one switches the whole view off (503).
* Pushes are limited to 512 KB and 3,000 symbols. The body is read as a stream and cut off at the cap, so a chunked body with no declared length is never buffered whole. The board holds at most 6,000 names, so a leaked ingest key cannot grow it without bound (a name refused for that reason is counted and reported back; the pusher records it). Quotes are reduced to numbers, a segment and a timestamp; unknown fields are dropped; one bad name or quote is skipped and counted, it does not poison the rest of a push. The ingest key is a write-everything key (it can overwrite any price shown): keep it a secret and rotate it if it leaks. A symbol called `constructor` or `__proto__` is just data.
* The pusher never follows a redirect (it would carry the token to another host). It sends in batches and, if the relay is down, loses nothing and spends one timeout a cycle.
* The live path is never cached by the service worker, and `cache-control: no-store` is set on every answer.
* The pusher can fail, hang for its 4-second timeout or throw without costing a recorded tick (tests pin this). The last Parquet part is flushed before the display's final push. Its token never appears in a log or an error.

## The paper-order queue (`/paper/*`, 8 Nov 2026)

The same Worker and Durable Object also hold the owner's **paper** orders until the paper runner (`quantdesk paper run`, docs/RECORDING.md "The paper runner") takes them through the risk gate. Paper money only: no broker is called from here, and no price, secret or credential is stored. The relay validates the *shape* of what crosses it and stamps the queue time with its own clock; whether a trade happens is the Python risk gate's decision alone.

| Route | Key | What |
|---|---|---|
| `POST /paper/order` | READ | queue one order (`id`, `side`, `symbol`, `lots`, buy: `strategy` and `thesis`, optional `limit`, `group`); 409 if the id was used, 429 if 20 are waiting |
| `POST /paper/kill` | READ | `{on: true/false}`: the kill flag; the runner mirrors it to the gate's kill file, and while it is on everything held is sold and nothing opens |
| `GET /paper/state` | READ | the summary (equity, positions with their theses, the last ledger rows), the last 30 results, the pending orders, the kill flag. Never the full ledger |
| `GET /paper/queue` | INGEST | `{kill, orders, now}` for the runner |
| `POST /paper/result` | INGEST | what happened to an order (`filled`, `refused`, `expired`, `invalid`, `done`); removes it from the queue |
| `POST /paper/state` | INGEST | `{summary, account?}`: the account is stored in pieces; **a shorter ledger, or one that does not extend the held one hash for hash, is refused (409)**, so a confused runner cannot overwrite history |
| `GET /paper/state?full=1` | INGEST | the full saved account, for the runner to restore from |

Storage: the queue, the results, the kill flag and the list of used order ids each have their own key and are bounded (20 waiting orders; the last 50 results, 5 reasons of 200 characters each; the last 1000 used ids), so none can crowd out another and the kill flag is never lost to a big value. A storage read that fails is never treated as empty: the route answers 503 and changes nothing; a write is made before memory changes, so a failed write (500) changes nothing and a retry is not told the id was used. The saved account is ASCII only (the runner escapes everything else).

The READ key can queue a paper order and set the kill flag; it cannot write a result or a state. The INGEST key cannot queue an order. Nothing new is needed on the Worker: the same two secrets.


## The news digest (`/news`, 8 Nov 2026)

The desk's own news engine (`quantdesk/intraday/news.py`: de-duplication across outlets, a finance word list that knows the subject matters, surprise against stated expectations, market-move recaps told apart from news, novelty) reads the public RSS feeds every ten minutes in the session (`news.yml`, started by the scheduler) and `quantdesk news --push` sends the **digest** to the relay: for each story its title (cut to 220 characters), an https link, the outlets that carried it, a tone from -1 to 1 (`words`, or `surprise` where the text states an expectation), an impact (low, medium, high), whether it is a recap of the market's own move, the event type, and which instruments it names (`quantdesk/premarket/newsdigest.py`: a name table for every recorded symbol; a test fails when a recorded symbol has no names). **Headlines and links only: no article text, no price, no account.**

| Route | Key | What |
|---|---|---|
| `POST /news/ingest` | INGEST | the digest. Everything is re-cleaned to known fields (an unsafe link becomes none, a bad item is dropped, the digest is cut oldest-first to 60,000 characters); one digest is kept and the newest replaces the last |
| `GET /news` | READ | `{digest, stored_at, now}`; `digest` is null before the first one arrives |

A storage failure is a 503 (never "no news") and changes nothing. The news job holds only the INGEST key and `contents: read`. In the app, the Build tab's **News and the board** panel joins each story to the live board: how far each named instrument has moved today and whether its options are trading hard ("the market reacted"). The tone is a word-list reading, a hint and not a view.
