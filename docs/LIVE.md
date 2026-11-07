# The live view

Real-time prices in the app, refreshed every 5 seconds, for **everything the Kite recorder watches**: not five symbols but the whole F&O universe. **Private and display only**: Zerodha's market data is licensed to the owner, so only the owner's key reads it, and nothing on this path can place an order or reach the paper desk.

```
Kite websocket (every tick)
   |  kite-record.yml job: Recorder keeps the latest tick per instrument
   |     (1) writes every tick to Parquet, encrypted, kept as a 90-day artifact: the record
   |     (2) every 5 s POSTs only the quotes that CHANGED, in batches, to the relay: the window
   v
Cloudflare Worker  /live/ingest  (needs LIVE_INGEST_TOKEN)      one Durable Object holds the latest snapshot, in memory
   v
App  "Live" tab  GET /live/snapshot  (needs LIVE_READ_TOKEN)   polls every 5 s; search, segment filters, sorting
```

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

## Switch it on (once, four values)

Make two random strings of at least 24 characters, different from each other (`openssl rand -hex 24` twice). Call them INGEST and READ.

| Where | What | Value |
|---|---|---|
| Cloudflare dashboard, the `quant-desk` Worker, Settings, Variables and Secrets | secret `LIVE_INGEST_TOKEN` | INGEST |
| same place | secret `LIVE_READ_TOKEN` | READ |
| GitHub, Settings, Secrets and variables, Actions, **Secrets** | `LIVE_INGEST_TOKEN` | INGEST (the same string) |
| GitHub, same page, **Variables** | `LIVE_URL` | `https://<your worker>.workers.dev/live/ingest` |

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
