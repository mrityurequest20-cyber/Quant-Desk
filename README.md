# QuantDesk

A research and data platform for Indian index and stock options. It records the market every session, keeps a
warehouse of NSE data since 2019, runs pre-registered research on it, and briefs the morning before the open.

**It does not trade.** On 6 Nov 2026 the owner retired the paper desk: every pre-registered test of intraday
direction failed, so the engine, the direction brain, the learning loop and the expiry sleeves were removed. They are
preserved on the branch `archive/pre-cleanup-2026-11-06`, and the full history stays in git. Trading comes back only
through a new, separately tested system: the spike detector (docs/PREMARKET.md, Next).

## What runs by itself

| Workflow | What |
|---|---|
| `record.yml` | Every session: index and futures 1-minute bars, option chains every minute (the chain tape), archived to the `chains-YYYY` release; then option and stock minutes. See docs/RECORDING.md. |
| `kite-record.yml` | Kite websocket ticks with depth, encrypted (data only; the owner's daily token from `kite-token.yml`). |
| `collect-wide.yml` | Stock option chains and all five indices' option minutes, every evening. |
| `data.yml` | The NSE warehouse: bhavcopy, every F&O stock's options, participant OI, FII/DII, the event calendar. |
| `oi-daily.yml`, `ml-retrain.yml` | The OI shadow grading and the registered models' refit drill. |
| `research.yml`, `study.yml` | Edge research and the pre-registered studies and audits, on demand or nightly. |
| `premarket.yml` | 07:15 to 09:15 IST: the pre-market brief (events, every F&O company's results against its own history, overnight markets, a ranked watch-list of every F&O instrument); the app's Today tab. See docs/PREMARKET.md. |
| `site.yml` | The read-only app (GitHub Pages behind Cloudflare). |
| `scheduler.yml`, `wake.yml` | Start the recorder on time when GitHub's cron is late. |

## Commands

```
python -m quantdesk premarket brief                         today's brief for every F&O instrument
python -m quantdesk data record-session [--until HH:MM]   record the session (no orders of any kind)
python -m quantdesk data update --release warehouse        fetch missing NSE days into the warehouse
python -m quantdesk intraday tape | doctor | kotak-check    the chain tape; can this machine record; what Kotak sees
python -m quantdesk laws | law-audit | wings | entry-check  the pre-registered expiry-eve research
python -m quantdesk ml import | build | reproduce | oi ...  the offline ML platform (docs/ML_PHASE0.md)
python -m quantdesk experiments                             what was tested and how beliefs moved
```

## What the research found (short)

* **Direction is not forecastable** from the desk's inputs: every pre-registered direction test failed.
* **Volatility is**: HAR beat the desk's forecaster in 8 of 8 locked cells (docs/prereg, vol_forecast_v1, the HAR
  one-shot).
* **The expiry-eve premium replicates** (expiry_eve_law v1/v2 and their audits).
* **Option spikes** cluster on expiry days, where buying loses, and on stock results, where options already price
  them (docs/PREMARKET.md). Catching spikes needs in-move detection on the recorded intraday data.

## Rules that do not change

* No secret in the repository. Licensed data (Kite ticks, third-party datasets) is never committed.
* Pre-registered specs and results in `docs/prereg/` are never edited after a result exists.
* `docs/AUTONOMY.md` is the owner's.
* Every safety-relevant change gets an independent review of its exact head. Required checks: `tests`, `doctor`,
  `Learnbot guard`.
