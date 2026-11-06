# What is in docs/

Start with **[RENAISSANCE.md](RENAISSANCE.md)**: the plan, its rules and its phases. Everything else supports it.
Older plans (the master plans, the 2027 roadmaps, the paper desk's architecture) were removed on 6 Nov 2026 and are
kept, unchanged, on the branches `archive/pre-cleanup-2026-11-06` and `archive/pre-cleanup-2-2026-11-06`.

## Rules

| File | What it is |
|---|---|
| [RENAISSANCE.md](RENAISSANCE.md) | The plan: invariants, the change gate, phases 0 to 7 |
| [AUTONOMY.md](AUTONOMY.md) | The owner's rulebook for what the builder may and may not do |
| [principles.json](principles.json) | The research principles and their evidence ladder (read by `learnbot` and `research.memory`) |
| [LEARNBOT.md](LEARNBOT.md) | The weekly research bot: what it may propose, and its guard |

## Data and recording

| File | What it is |
|---|---|
| `quantdesk/paper` | The paper desk's money and brakes: the account with a hash-chained ledger, the risk gate (loss caps, kill switch, fail-closed checks) and the paper broker. Long options only; paper money only |
| `quantdesk/markets` | The market map: which segment trades when, the MCX close that follows the US clock change, and the chained jobs that cover a day (`python -m quantdesk markets today\|plan`) |
| `quantdesk/data/health.py` | Data health: did each data channel deliver today and is it sane, with the quarantine rule for corrupt chain rows (`python -m quantdesk data health`, `docs/DATA_HEALTH.md`) |
| `quantdesk/data/live_push.py`, `deploy/cloudflare/live.js` | The live view: the recorder's latest prices pushed every 5 s to a private relay and shown in the app's Live tab (`docs/LIVE.md`) |
| [RECORDING.md](RECORDING.md) | The session recorder (`record.yml`): what it records, where it goes |
| [WATCHDOG.md](WATCHDOG.md) | The Cloudflare watchdog: which jobs it checks and when it alerts |
| [EXTERNAL_DATA.md](EXTERNAL_DATA.md) | The imported index-minute dataset and its restrictions |
| [data/INTAKE_2026-10-24.md](data/INTAKE_2026-10-24.md) | The data intake review: what each source can be trusted for |
| [ml/KITE_TRIAL.md](ml/KITE_TRIAL.md) | The Kite tick recorder trial and its pre-registered criteria |

## Research and ML

| File | What it is |
|---|---|
| [prereg/](prereg/) | Pre-registered specs and their locked results. **Never edited after a result exists.** |
| [reports/](reports/) | Dated study reports and audits (results, not plans) |
| [ML_ROADMAP.md](ML_ROADMAP.md), [ML_PHASE0.md](ML_PHASE0.md), [ML_RESEARCH_PLAN.md](ML_RESEARCH_PLAN.md) | The ML programme's rules, platform work and handover |
| [ml/](ml/) | ML criteria, results, the prediction-event design, spec and model-card templates |
| [VOL_SHADOW_PROTOCOL.md](VOL_SHADOW_PROTOCOL.md) | How the HAR volatility shadow is graded (Phase 2 builds on it) |
| [ASYMMETRY_SCOUT.md](ASYMMETRY_SCOUT.md) | The diagnosis behind the spike goal: trades that pay several times their risk |

## The organisation (kept because AUTONOMY.md names them)

| File | What it is |
|---|---|
| [ORG.md](ORG.md), [org/](org/) | The review departments and their scorecard |
| [BACKLOG.md](BACKLOG.md) | The old ranked backlog; RENAISSANCE.md's phases now set the order |
