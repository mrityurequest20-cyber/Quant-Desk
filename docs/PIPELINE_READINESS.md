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
| Stock option chains, five indices' minutes | 15:25, 15:45 | releases | Data health |
| NSE warehouse (bhavcopy, participant OI, FII/DII, events) | evenings | warehouse tables | Data health |
| Pre-market brief | 07:15 to 09:15 | `premarket` branch | Data health |

## What the live view can take

* Kite: the recorder pushes changed quotes every 5 s; Kotak: the relay polls, at most 40 calls a cycle (about 1,000 instruments a cycle, 25 a call). The board holds up to 6,000 names. Chains: index chains every cycle, stock chains in turn.
* One close a minute per instrument for the last two trading days, up to 800,000 minutes in all, kept in the relay's storage and written every five minutes.
* Two sources per name, the fresher shown, a flag when they differ by more than a spread explains.

## Gaps, in the order they matter

1. **The live prices are not a record.** The relay keeps the latest quote and two days of minute closes. If the record of a day has a hole (the recorder fell over), the live view cannot fill it afterwards. Kotak live prices are stored nowhere.
2. **Evenings are not recorded.** The recorders stop at about 15:32. MCX and currency trade until late evening and have no recorder.
3. **No daily-history charts.** A chart is today and yesterday only. Longer history exists in the warehouse and the releases but is not drawn in the app.
4. **No cross-check of the record.** Kite and Kotak are compared live (the "differ" flag) but the comparison is not stored, so there is no daily number for how often they agreed.
5. **The Today tab depends on the `premarket` branch.** It did not exist on 7 Nov (a Saturday), so Today showed "no brief"; check on a weekday morning.
6. The Kite tick content cannot be checked by the health run (encrypted); `kite-compare` measures it separately.

Next, in this order: record past 15:32 for MCX and currency (a separate live-only workflow with its own concurrency group, leaving the pre-registered Kite trial alone), then a stored daily agreement number between the two sources, then daily-history charts.
