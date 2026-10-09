# QuantDesk Architecture Map (Phase A1)

As-built map, traced from runtime entry points, not from the README. Code `main@c96909f`, state
`journal@ecd03156` (2026-10-09 12:20 IST). Finding IDs refer to `QUANTDESK_FINDINGS_REGISTER.md`.

## 1. What actually runs, and who starts it

There is no long-lived server in the default deployment. **GitHub Actions is the operating system.** Each workflow
starts a fresh runner, restores state from git, runs, and force-pushes the state back.

### 1.1 Alarm clocks: three layers, because GitHub cron is unreliable here

| Starter | File | Schedule | Does |
|---|---|---|---|
| Cloudflare Worker cron | `wrangler.jsonc`, `deploy/cloudflare/worker.js` | */10 min 07:30–15:20 IST Mon–Fri; Sun 17:30 | Dispatches `scheduler.yml` (needs Worker secret `GH_DISPATCH_TOKEN`; README: "probably not set yet") |
| `scheduler.yml` | `deploy/scheduler.py` | `*/10 * * * 0-5` (best-effort) | Dispatches `live.yml` if it's a trading day 08:25–14:45, nothing queued, running or done, and no cancel today; arms `wake.yml` overnight |
| `wake.yml` | `deploy/scheduler.py --wake` | dispatched | Sleeps on a runner until 08:30 IST, then runs the scheduler check |
| `live.yml` own cron | — | `22 3 * * 1-5` (08:52 IST) | Starts the desk directly. README: it arrived 6½–7 h late on 29 Sep – 1 Oct |

### 1.2 Workflows that run code, ordered by the trading day

| Workflow | Trigger | Concurrency group | Entry point(s) | Reads | Writes |
|---|---|---|---|---|---|
| `data.yml` | cron 20:15 + 08:10 IST | `warehouse` | `quantdesk data update --release warehouse`, `data status` | NSE archives/API, BSE | `warehouse` release assets (`--clobber`) |
| `live.yml` → `morning` | cron / dispatch | `live-desk` | `intraday doctor`; `journal.sh restore`; `research.sh`; `warehouse-context.sh`; `intraday learn --bootstrap --if-empty`; `run-session.sh --until 12:20 --handover` → **`intraday live`** + **`intraday tape`** (background) + `export-site` every 6 min | journal branch, research branch, warehouse release, Kotak, Yahoo, NSE, RSS, LLM APIs | journal branch (`push -f`), gh-pages (`push -f`), run artifact (90 d), `chains-YYYY` release |
| `live.yml` → `afternoon` | `needs: morning` | `live-desk` | the same restore + **`intraday live`** to 15:30; `intraday sleeves`; `intraday progress`; `data archive-session`; `data kotak-backfill --days 3` | same | same, plus `option-minutes-YYYY` release |
| `autolearn.yml` | cron 16:10 IST (observed 23:05) | `live-desk` | `autolearn verify` (`recover` on failure); **`autolearn cycle`**; `autolearn research`; `autolearn status` | journal branch, Yahoo 5m, `chains-*` release | journal branch |
| `learn.yml` | dispatch | `live-desk` | `intraday learn --bootstrap` | journal, Yahoo | journal branch |
| `selfreview.yml` | cron 17:10 + workflow_run | `self-review` | `intraday self-review --issues` | journal (read) | GitHub issues |
| `org.yml` | cron 17:20 Mon–Sat, Sun 09:00 | `org-rota` | `org rota --issues`, `org scorecard` | repo docs | GitHub issues |
| `research.yml` | cron Sat 09:47 | — | **`quantdesk research`** (edges + warehouse research) | Yahoo daily/hourly/5m, warehouse | `research` branch (`push -f`) |
| `progress.yml` | cron Sat 10:40 | — | `intraday progress --issue` | journal (read) | issue |
| `study.yml` | dispatch (rota) | — | `laws` / `law-audit` / `warehouse-audit` / `entry-check` / `wings` | warehouse release, journal (read) | artifacts |
| `restate.yml` | dispatch | **`journal-admin`** (≠ `live-desk`; A-10) | `intraday restate-trade` | journal | journal branch, gh-pages |
| `site.yml` | push to main (`quantdesk/web/**`) | `site-publish` | `export-site` | journal (read) | gh-pages |
| `external-data.yml`, `kotak-backfill.yml`, `chain-archive.yml` | dispatch | various | `data external-import/verify`, `autolearn direction-study`, `data kotak-backfill`, `data archive-session` | external repo, Kotak | releases |
| `whatif.yml`, `audit.yml` | dispatch | — | `deploy/whatif.py`, `deploy/audit_fills.py` | journal, run artifacts | summary only |
| `ci.yml` | push / PR | — | `pytest`, `node --check`, `deploy/check_workflows.py`, `pip-audit`, `intraday doctor` | — | — |
| `ai-check.yml`, `broker-check.yml`, `data-probe.yml` | dispatch | — | diagnostics | APIs | summary |

### 1.3 Self-hosted alternative (documented, not evidenced in use)

`docker-compose.yml` runs `desk` (`intraday live --forever --quiet`) and `web` (`quantdesk serve`), sharing
`./runtime`. The systemd units in `deploy/` do the same. No evidence in the state that this path ran.

## 2. CLI surface (dispatch: `quantdesk/cli.py:main` → `a.fn`)

| Group | Registered in | Commands that run in production (✓) or exist only (·) |
|---|---|---|
| top level | `quantdesk/cli.py:250-355` | ✓ `research`, ✓ `laws`, ✓ `warehouse-audit`, ✓ `law-audit`, ✓ `entry-check`, ✓ `wings`, ✓ `org`, ✓ `experiments` (doc). Daily desk: · `analyze`, · `scan`, · `options`, · `backtest`, · `walkforward`, · `paper`, · `journal`, · `risk`, · `schedule`, · `serve`, · `demo` |
| `intraday` | `quantdesk/intraday/cli.py:693-797` | ✓ `live`, ✓ `tape`, ✓ `sleeves`, ✓ `progress`, ✓ `self-review`, ✓ `doctor`, ✓ `learn`, ✓ `export-site`, ✓ `review`, ✓ `trades`, ✓ `reset-account`, ✓ `restate-trade`, ✓ `ai-check`, ✓ `kotak-check`; · `replay`, · `command`, · `paper-gate`, · `stocks`, · `thoughts`, · `stats` |
| `data` | `quantdesk/data/cli.py:104-158` | ✓ `update`, ✓ `status`, ✓ `archive-session`, ✓ `kotak-backfill`, ✓ `external-import`, ✓ `external-verify`; · `truedata-*` |
| `autolearn` | `quantdesk/autolearn/cli.py:11-53` | ✓ `cycle`, ✓ `research`, ✓ `status`, ✓ `verify`, ✓ `recover`, ✓ `direction-study`; · `prereg`, · `rollback` |

**Two separate trading systems live in one repo.**

- **The daily multi-strategy desk:** `engine/`, `strategies/`, `risk/`, `execution/`, `backtest/` (README sections 1–7).
  No workflow runs `paper run` or `paper premarket`. It is exercised only by CI tests and by hand.
- **The intraday options desk:** `intraday/`, plus `autolearn/` and the sleeves. This is what runs every trading day.

Unless stated otherwise, this audit's later phases concern the **intraday** desk, because that is what produces the
persisted state.

## 3. Module map: the intraday desk at runtime

```
                         ┌──────────────────────── intraday live (one process per job) ───────────────────────────┐
 Kotak REST ──► kotak.KotakIntradayFeed ─┐  (per-minute fallback to Yahoo, A-04)                                  │
 Yahoo yfinance ► feeds.YahooIntradayFeed┼─► engine.IntradayEngine.step()  every minute                           │
 Kite (untested) ► feeds.KiteIntradayFeed┘     │                                                                   │
 Kotak/NSE chain ► chains.FallbackChain ───────┤ _refresh_chain ─► chainflow, chain analytics                       │
 RSS feeds ──► news.NewsDesk (+ llm.LLMDesk) ──┤ _refresh_news  ─► journal.news_add(seen_at=now)                    │
 Yahoo globals ► brain.GlobalFeed / Brain ─────┤ _think_globally                                                    │
 Kotak quotes ► breadth.Breadth ───────────────┤ breadth.state                                                      │
 warehouse (EOD) ► ivhist, brain.load_flows ───┤ (session start)                                                    │
 research branch ► edges.json / links.json ────┤ (session start: priors, brain links, hist_edge)                    │
 memory.json ──► learning.Memory ──────────────┤ factor/news/setup multipliers (_apply_memory)                      │
 autolearn registry ► autolearn.live.LiveLearner┤ on_bar (inert: A-01), entry_filter, plan_gate                      │
                                               ▼                                                                   │
                 features.session_state ─► analyst.assess ─► playbook ─► quant.EVEngine ─► risk ─► sim.IntradayBroker │
                                               │                                                                   │
                 journal.Journal (SQLite: thoughts, decisions, trades, fills, events, news, equity, state)         │
                 recorder.SessionRecorder (data/<day>/<SYM>_1m.csv, chains/*.csv)                                  │
                 at the close: learning.grade_session ─► memory.json; review ─► reviews/<day>.md                   │
                 └──────────────────────────────────────────────────────────────────────────────────────────────────┘
 beside it:  intraday tape (tape.py): Kotak chains every minute for 3 + 2 expiries → data/<day>/chains/
 after it:   intraday sleeves (sleeves.py) → sleeves/<spec>.jsonl ; autolearn cycle → autolearn/*
```

The B-phases will verify each arrow (detected → used → weighted → stored → learned). Phase A only establishes that
they exist and where they persist.

## 4. Data stores, registries and journals

| Store | Location | Written by | Format / guarantees as built | Read by |
|---|---|---|---|---|
| Journal DB | `runtime/intraday/journal.db` → `journal` branch | engine (autocommit every write in live, `intraday/cli.py:90`) | SQLite; `PRAGMA integrity_check` on restore (`journal.sh`) and `quick_check` at session start | site export, review, learning, autolearn ingest, self-review |
| Paper broker | `runtime/intraday/broker.json` | `sim.IntradayBroker` | atomic JSON | engine |
| Learning memory | `runtime/intraday/memory.json` | `learning.Memory.save` (temp + rename) | JSON tables (factor, news_*, setup, …), graded-id lists truncated to the last 5,000 / 2,000 | engine `_apply_memory`, NewsDesk trust, site |
| Recorded bars | `runtime/intraday/data/<day>/<SYM>_1m.csv` (+`-FUT`, gift, tape) | `SessionRecorder.record_bars` (whole-file rewrite, not atomic) | CSV, **no source column** (A-04), 12:20–12:21 hole (A-06) | replays, autolearn `gather`, plan research, bootstrap |
| Chain snapshots | `runtime/intraday/data/<day>/chains/*.csv` | recorder + tape (temp + rename) | CSV with `_ts` (fetch time, A-11) and `_source` | replays, plan research, sleeves, fill audit. **Excluded from the journal branch** (`journal.sh` `--exclude ./data/*/chains`); kept as a 90-day artifact and on the `chains-YYYY` release |
| Autolearn ledger | `runtime/intraday/autolearn/ledger/{predictions,outcomes}-YYYY-MM.jsonl` | `LiveLearner.on_bar`, `Ledger.resolve` | hash-chained JSONL | cycle `paper`, `promote`. **Does not exist (A-01)** |
| Autolearn registry | `autolearn/registry/` (+ `plan/registry/`) | `Registry` | `state.json` + events log + content-addressed models | LiveLearner, cycle. **Empty: no champion ever** |
| Lockbox | `autolearn/lockbox.json`, `lockbox_access.jsonl` | `LockBox.ensure` | days 2026-09-22 … 10-01, 0 accesses | cycle validate (A-07) |
| Bar store | `autolearn/bars5/{NIFTY,BANKNIFTY,INDIAVIX}.parquet` | cycle ingest | merged 5-minute bars, no source column | cycle dataset |
| Datasets / runs / cycles | `autolearn/datasets/*.parquet`, `runs/<day>/`, `cycles/<day>.json`, `cycles/audit.jsonl` | cycle | fingerprints, fold layout hash, per-stage state | status, recovery |
| Plan research | `autolearn/plan/studies/*`, `trials.jsonl`, `latest.json` | `autolearn research` | real / scenario / EOD kept apart | LiveLearner `plan_gate` (via the plan registry) |
| Sleeves ledgers | `runtime/intraday/sleeves/expiry_seller_v{1,3}.jsonl` | `intraday sleeves` | "append-only" (A-10 caveat) | sleeves report, entry-check |
| Progress | `runtime/intraday/progress/history.jsonl` | `intraday progress` | JSONL | progress issue |
| Research priors | `research` branch: `edges.json`, `links.json`, `buyer_edge.json`, `vrp_positioning.json`, `experiment_log.jsonl` | `research.yml` (`push -f`) | snapshot; the experiment log is carried over by `deploy/research-ledger.sh` | engine (priors, brain wiring, buyer's edge) |
| Warehouse | `warehouse` release assets: `{table}_{period}.parquet` + `manifest` | `data update` | upsert keep-last, `--clobber` (A-14) | research, studies, the live desk's EOD context |
| Pre-registrations | `docs/prereg/*.json`, `docs/prereg/results/*` | humans / agents, committed to `main` | git history (real, unlike the journal) | laws, sleeves, studies |
| Principles / research memory | `docs/principles.json`, `research/memory.py` | committed | git | `experiments` |
| Org scorecard | `docs/org/scorecard.jsonl` | committed | git | `org` |
| Public site | `gh-pages` (`data.json` ≈ 2.5 MB) | `export-site` + `push-dir.sh` | snapshot, public | phone app, Cloudflare Worker |

**Key architectural property (A-10).** Everything under `runtime/intraday` is one snapshot. It is replaced wholesale
by a parentless commit and `git push -f` after every job, so the journal branch has no history. All "append-only"
and "hash-chained" guarantees therefore hold *within* a snapshot only.

## 5. External providers

| Provider | Used for | Auth | Fallback | Failure mode as built |
|---|---|---|---|---|
| Kotak Neo REST (`intraday/kotak.py`) | 1-minute index candles, futures candles and volume/OI, option chain with 5-level quotes, live LTP every 5 s, breadth quotes, minute backfill | consumer key only (`KOTAK_CONSUMER_KEY`) | bars → Yahoo per minute (rested 15 min after 5 failures); chain → NSE (`FallbackChain`, at most every 3 min) | silent per-minute substitution (A-04); aggregate counts in the feed and chain names |
| Yahoo (yfinance) | prior-session 1-minute history, 5-minute training history, global markets, heavyweights, research daily/hourly/5m | none | none (empty frame) | `datetime64[s]` index under pandas 3 (A-02); intraday revisions (A-12) |
| NSE public site/API | option-chain fallback, GIFT Nifty, archives (bhavcopy, participant OI, index close), holidays, events | cookies | none | often blocked from US runners (README) |
| BSE | SENSEX/BANKEX bhavcopy | none | — | — |
| RSS (ET, Moneycontrol, Mint, BS, Google News, RBI) | headlines | none | per-source health | publish→seen lag: median 74 min (A-09) |
| Anthropic / Gemini / Ollama (`intraday/llm.py`) | second news readers, after-close reflection | API keys | each reader independent; Ollama `advisory_only` | timeouts recorded in `events` (Gemini 45 s, Ollama 90 s); Phase G |
| Kite Connect | alternative feed, chain and live broker | API key + token | — | untested per README |
| GitHub (Actions, releases, branches) | compute, scheduling, all persistence | `GITHUB_TOKEN` | — | throttled cron (README; cycle 2026-10-08 ran 23:05 vs the 16:10 schedule) |
| Cloudflare Worker | alarm clock, site proxy | `GH_DISPATCH_TOKEN` | scheduler + wake | token "probably not set" (README) |

## 6. Decision authority (as configured, to be verified in Phase B)

`config/quantdesk.yaml`:

| Setting | Value |
|---|---|
| `account.mode` | `paper` |
| `intraday.feed` / `intraday.chain` | `kotak` / `kotak` |
| `autolearn.enabled` | true |
| `autolearn.gate_entries` | true |
| `autolearn.require_approved_model` | **true** |
| `intraday.llm.advisory_only` | `[ollama]` |

With `require_approved_model: true`, `LiveLearner.plan_gate` (`autolearn/live.py:176-189`) removes every
**directional** plan unless a plan champion exists. The plan registry is empty, and its real track reports "5 real
sessions, 28 needed" (`plan/latest.json`). So, as configured, directional option trades are structurally impossible
until ≥ 23 more fully recorded sessions accumulate and a model passes. Non-directional plans pass this gate. Whether
any exist and reach execution is Phase B (Q-03).

Real-money path: `execution/kite.py` needs `account.mode: live`, plus `--live`, plus Kite credentials, plus
`kiteconnect`. Phase F/H will check it; no workflow passes `--live`.

## 7. Dependencies and environment

- Python 3.11 on runners; `requirements.txt` has lower bounds only. In Phase A the runner-equivalent install resolved
  pandas 3.0.6, numpy 2.5.3, yfinance 1.7.0, scipy 1.18.1, pyarrow 25.0.1 (A-03).
- Actions are pinned by commit SHA (good). The Python packages are not.
- `deploy/check_workflows.py` lints the workflows in CI.

## 8. Size

| Area | Lines of Python |
|---|---|
| `quantdesk/intraday` | 9,920 |
| `quantdesk/autolearn` | 5,250 |
| `quantdesk/research` | 3,020 |
| `quantdesk/data` | 3,020 |
| daily desk (`engine`, `strategies`, `risk`, `execution`, `backtest`, `analytics`, `options`) | 4,150 |
| `tests` | 8,150 (53 files) |

`intraday/engine.py` alone is 1,636 lines.
