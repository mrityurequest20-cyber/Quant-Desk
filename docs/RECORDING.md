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
| `kite-record.yml` | the session | Kite websocket ticks with depth, encrypted (data only, the owner's daily token). |
| `collect-wide.yml` | 15:25, 15:45 | Stock option chains, and minutes for all five indices. |
| `data.yml` | evening | The NSE warehouse (bhavcopy, participant OI, FII/DII, the event calendar). |
| `premarket.yml` | 07:15 to 09:15 | The pre-market brief (on its own branch until merged). |

`scheduler.yml` and `wake.yml` start `record.yml` on time when GitHub's cron is late. Cancelling a recorder run keeps
it stopped for the day. The Cloudflare watchdog now checks the recorder (W1, W3), not the desk's heartbeat.

Sources: Kotak Neo (consumer key only: no login, no orders) when `KOTAK_CONSUMER_KEY` is set, else Yahoo bars and
NSE's public chain. The recorder never reads the Kite feed (licensed to the subscriber).
