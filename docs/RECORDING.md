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
| `evening-minutes.yml` | by hand only | MCX and currency futures' minutes from Kotak's candle API: **not scheduled**, because Kotak answers every MCX and currency candle request with HTTP 422 ("Historical data is not supported for this exchange", found on its first run, 7 Nov 2026). The MCX and currency evenings need Kite (historical candles, or ticks past 15:32). |
| `fx-minutes.yml` | 22:30 UTC (04:00 IST), Mon to Fri | 1-minute bars of the FX majors and the rupee crosses (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, USDINR, EURINR, GBPINR, JPYINR, DXY) from Yahoo, UTC, re-reading the last five days (Yahoo keeps seven). `fx-minutes-YYYY` release. Public source, no secret. |
| `fx-daily.yml` | by hand | The same pairs' daily history from 2003, checked against the rate the ECB's reference rates imply (2% tolerance: a sanity check; weekdays most of a group of pairs lack are market holidays, not gaps; a one-day spike that reverses is set aside as a bad print and listed in the manifest's `quarantined`; any other move beyond 5% is flagged until a person lists it under `fx.accepted_moves`; the dollar index is checked against the ECB's rates through ICE's basket formula). `verified` is about the values; missing days are reported separately as `coverage` (`gappy` above 1% of weekdays) and do not fail a series. `fx-daily` release, one immutable dataset per run. |
| `data.yml` | evening | The NSE warehouse (bhavcopy, participant OI, FII/DII, the event calendar). |
| `premarket.yml` | 07:15 to 09:15 | The pre-market brief (on its own branch until merged). |

`scheduler.yml` and `wake.yml` start `record.yml` on time when GitHub's cron is late. Cancelling a recorder run keeps
it stopped for the day. The Cloudflare watchdog now checks the recorder (W1, W3), not the desk's heartbeat.

Sources: Kotak Neo (consumer key only: no login, no orders) when `KOTAK_CONSUMER_KEY` is set, else Yahoo bars and
NSE's public chain. The recorder never reads the Kite feed (licensed to the subscriber).
