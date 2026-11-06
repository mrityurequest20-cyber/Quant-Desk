# The live view

Real-time prices in the app, refreshed every 5 seconds. **Private and display only**: Zerodha's market data is licensed to the owner, so only the owner's key reads it, and nothing on this path can place an order or reach the paper desk.

```
Kite websocket (every tick)
   |  kite-record.yml job: Recorder keeps the latest tick per symbol
   |     (1) writes every tick to Parquet, encrypted, kept as a 90-day artifact: the record
   |     (2) every 5 s POSTs only the quotes that CHANGED to the relay: the window
   v
Cloudflare Worker  /live/ingest  (needs LIVE_INGEST_TOKEN)      one Durable Object holds the latest snapshot
   v
App  "Live" tab  GET /live/snapshot  (needs LIVE_READ_TOKEN)   polls every 5 s, shows each price and its age
```

## Switch it on (once, four values)

Make two random strings of at least 24 characters, different from each other (`openssl rand -hex 24` twice). Call them INGEST and READ.

| Where | What | Value |
|---|---|---|
| Cloudflare dashboard, the `quant-desk` Worker, Settings, Variables and Secrets | secret `LIVE_INGEST_TOKEN` | INGEST |
| same place | secret `LIVE_READ_TOKEN` | READ |
| GitHub, Settings, Secrets and variables, Actions, **Secrets** | `LIVE_INGEST_TOKEN` | INGEST (the same string) |
| GitHub, same page, **Variables** | `LIVE_URL` | `https://<your worker>.workers.dev/live/ingest` |

Then open the app on the Cloudflare site, go to **Live**, and type READ once. Until the secrets exist the relay answers 503 and the recorder pushes nothing; recording is unaffected either way.

## What it shows, and what it does not

* The symbols the recorder subscribes to: Nifty 50, Bank Nifty, India VIX and the near-month Nifty and Bank Nifty futures. The wider universe (stocks, MCX, currency) joins when its recorder does.
* **Age** is measured on the Worker's clock from when each price arrived, so a dead feed shows as old whatever the phone's clock says. Green is under 15 s, amber under 2 minutes, then "No feed". Outside market hours, and in the seconds or minutes between the recorder's chained jobs, it will show as stale: that is the truth, not a fault.
* A price is only pushed when it changed, so a closed market never looks live.
* The Worker keeps only the latest snapshot. The permanent record is the encrypted Parquet artifact (90 days, GitHub's maximum). Nothing licensed is committed to the repository, written to a release, or published to Pages. Keeping the ticks longer needs a private store (Cloudflare R2): not built.

## Safety

* Two keys, two doors: the recorder's key can write but not read; the app's key can read but not write. Both are compared in constant time. Fewer than 24 characters, equal keys, or a missing one switches the whole view off (503).
* Pushes are limited to 64 KB and 100 symbols and are reduced to numbers and a timestamp; unknown fields are dropped.
* The live path is never cached by the service worker, and `cache-control: no-store` is set on every answer.
* The pusher can fail, hang for its 4-second timeout or throw without costing a recorded tick (tests pin this). Its token never appears in a log or an error.
