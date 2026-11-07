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
* **Kotak** needs no daily login and runs inside the Cloudflare Worker, so no GitHub runner, cron or job limit stands between it and the app. It carries the universe it is given (price, volume, open interest, percent change and a five-level book) and is the fallback for everything. **Capacity is real, not unlimited**: Kotak allows 25 instruments a quotes call and 25 requests a second (as noted in `quantdesk/intraday/kotak.py`), the poller makes at most 40 calls an alarm (the free plan allows 50 subrequests) at about 22 a second, so one cycle refreshes at most about 1,000 instruments (6 index spots one to a call, 25 per call for the rest, chains one call each). A longer universe is rotated: each instrument is refreshed every ceil(calls / 40) cycles, about 5 seconds per 1,000 instruments. The board holds at most 4,000 names.
* **Per instrument** the board keeps each source's latest quote and its own arrival time, shows the **fresher** one with its source (Kite or Kotak under the name), and fills a missing book from the other. If both are fresh (under 60 s) and their prices differ by more than 0.5% (3% for an option, whose spread is wide), the row shows **⚠ the two sources differ** and `/live/health` counts it: that is the cross-check on data correctness.
* **Fresh means moved.** A Kotak quote's arrival time is refreshed only if its price, volume, open interest or (when both have one) its book changed since the last cycle, so a holiday, a closed market or a frozen instrument grows an age instead of looking live; an instrument asked for as a quote and as a chain row is one name, so it cannot defeat this. The first time a price is seen its age is taken from Kotak's own timestamp when it has one (clamped to 12 hours), so a last-known price after a restart is as old as it really is. A Kite quote is refreshed when a new tick arrives.
* **The board cannot fill for good.** A quote not seen for 18 hours (an expired weekly option, a retired symbol) is dropped, whenever the alarm runs and when a full board is asked for a new name; names refused because the board is full are counted in `/live/health` (`kotak.refused`).
* **Kotak is not hammered.** If it refuses the key the poller backs off (a minute, doubling to 15 minutes); on a rate limit it waits 15 s; an HTTP 200 that carries a fault, or no usable rows, counts as a failure, and a redirect is never followed (the key travels in a header). The key is shared with the minute recorder and the backfills, which run on GitHub runners: together they could exceed Kotak's 25 requests a second at times, and the poller does not retry a 429 inside a cycle. If the key is removed the alarm stops.
* **Known limit, not fixed:** if Kite's re-subscribe snapshot at the open is the previous close while Kotak is already quoting a gap-up, many instruments can show the disagreement flag for a few minutes. The watchdog's disagreement alert needs more than 5% of at least 20 instruments, and its first look is at 09:50.
* **A source can die without the view dying.** If Kite has no token, or its job is between chained jobs, Kotak still fills the view; if Kotak is refused or down, Kite does. `/live/health` and the strip under the status pill say which is which. The poller's alarm always re-arms itself, whatever a cycle did; the Worker's own 10-minute cron re-arms a lost one.
* The poller calls only Kotak's two read endpoints (quotes and option chain). It holds the consumer key as a Worker secret and never logs, returns or echoes it (a test greps for this and for every order-style endpoint).
* Both live sources name an option the same way (`NIFTY12NOV2624500CE`, `option_name` in `kite_universe.py` and `optionName` in `kotak.js`; a test pins them equal), otherwise prices from the two could never land on one row.
* **Until the Kotak universe is built the poller idles** (`/live/health` says "no universe"). The builder (`quantdesk/data/kotak_universe.py`) is the next change.

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

## Switch it on (once, five values)

Make two random strings of at least 24 characters, different from each other (`openssl rand -hex 24` twice). Call them INGEST and READ.

| Where | What | Value |
|---|---|---|
| Cloudflare dashboard, the `quant-desk` Worker, Settings, Variables and Secrets | secret `LIVE_INGEST_TOKEN` | INGEST |
| same place | secret `LIVE_READ_TOKEN` | READ |
| GitHub, Settings, Secrets and variables, Actions, **Secrets** | `LIVE_INGEST_TOKEN` | INGEST (the same string) |
| GitHub, same page, **Variables** | `LIVE_URL` | `https://<your worker>.workers.dev/live/ingest` |
| Cloudflare dashboard, same Worker, Variables and Secrets | secret `KOTAK_CONSUMER_KEY` | the Kotak Neo consumer key (the one already saved as the GitHub secret of the same name) |

Then open the app on the Cloudflare site (never the github.io address: the tab refuses to send the key there), go to **Live**, and type READ once. Until the secrets exist the relay answers 503 and the recorder pushes nothing; recording is unaffected either way.

## Honest limits

* **Age** is measured on the Worker's clock from when each price arrived, so a dead feed shows as old whatever the phone's clock says. Green is under 15 s, amber under 2 minutes, then "No feed". The recorder pushes a quote when a new tick arrived for it, and the relay keeps only the latest. A price that has not ticked simply grows older. If Kite resends a last-known tick when it connects, that one tick can look fresh until the next real one arrives; the exchange timestamp `t` is sent for the core instruments so this can be checked.
* Between the recorder's chained jobs (a gap of seconds to minutes) and outside market hours the tab reads stale. That is the truth, not a fault.
* The relay holds the latest snapshot **in memory**. After a Cloudflare restart it fills again within seconds for liquid instruments; a quiet contract appears at its next tick. The permanent record is the encrypted Parquet artifact (90 days, GitHub's maximum). Nothing licensed is committed to the repository, written to a release, or published to Pages. Keeping ticks longer needs a private store (Cloudflare R2): not built.
* A 5-second snapshot of the last tick, about a second behind the exchange. Not tick by tick.

## Safety

* Two keys, two doors: the recorder's key can write but not read; the app's key can read but not write. Both are compared in constant time. Fewer than 24 characters, equal keys, or a missing one switches the whole view off (503).
* Pushes are limited to 512 KB and 3,000 symbols. The body is read as a stream and cut off at the cap, so a chunked body with no declared length is never buffered whole. The board holds at most 4,000 names, so a leaked ingest key cannot grow it without bound (a name refused for that reason is counted and reported back; the pusher records it). Quotes are reduced to numbers, a segment and a timestamp; unknown fields are dropped; one bad name or quote is skipped and counted, it does not poison the rest of a push. The ingest key is a write-everything key (it can overwrite any price shown): keep it a secret and rotate it if it leaks. A symbol called `constructor` or `__proto__` is just data.
* The pusher never follows a redirect (it would carry the token to another host). It sends in batches and, if the relay is down, loses nothing and spends one timeout a cycle.
* The live path is never cached by the service worker, and `cache-control: no-store` is set on every answer.
* The pusher can fail, hang for its 4-second timeout or throw without costing a recorded tick (tests pin this). The last Parquet part is flushed before the display's final push. Its token never appears in a log or an error.
