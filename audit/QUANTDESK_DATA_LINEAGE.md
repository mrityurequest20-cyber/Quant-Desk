# QuantDesk Data Lineage and Point-in-Time Audit (Phases A2, A3)

Traced from code and checked against the persisted state: `journal@ecd03156`, the 2026-10-09 12:20 IST hand-over
snapshot. Finding IDs refer to `QUANTDESK_FINDINGS_REGISTER.md`.

---

## A2. Lineage, stage by stage

Each chain reads: source → ingestion → raw storage → normalization → canonical → features → research/decision →
paper execution → outcome → learning.

### L1. Intraday index bars (the desk's primary input)

| Stage | Where | What happens | Evidence / defects |
|---|---|---|---|
| Source | Kotak `market-data/1.0/historical/details` 1-minute candles (`kotak.py:194-204`); Yahoo `^NSEI` / `^NSEBANK` 1m (`feeds.py:106-118`); Kite ticks (untested) | Kotak today; Yahoo for prior sessions, and for any minute Kotak fails | A-04: per-minute substitution, no per-bar mark |
| Ingestion | `IntradayEngine.start_session` → `feed.history(sym, 6)` (`engine.py:196-200`); `step()` → `feed.poll(sym, last_ts)` each minute (`engine.py:245-256`) | in-memory `self.bars[sym]` = Yahoo history ⊕ Kotak polls | Kotak timestamps claimed to be bar start (`kotak.py:195`): **UNVERIFIED** (Q-01) |
| Normalization | `normalise_bars` (`feeds.py:39-49`): tz → IST, floor to the minute, de-dup keep-last, clip to 09:15–15:30. `completed()`: `index + 1 min <= now` | index unit inherits the provider's (`s` from Yahoo under pandas 3) | A-02 |
| Raw storage | `SessionRecorder.record_bars` → `data/<day>/<SYM>_1m.csv` (whole-file rewrite) | only *polled* bars are written, never restored history | A-06 (12:20–12:21 hole every session); not atomic |
| Futures volume | `_with_futures` (`kotak.py:388-406`): near-month futures 1m volume grafted onto index bars; futures bars kept as `<SYM>-FUT` | missing futures minute → volume 0 | A-16 |
| Canonical (learning) | autolearn `gather()` (`cycle.py:184-218`): store → Yahoo 5m (55 d) → recorded 1m→5m; later source wins a whole session if ≥ 60 bars; `validate_bars` (dups, OHLC, session, holidays, > 5% jumps quarantined, gaps counted) → `bars5/*.parquet` | one source per session, not recorded as such | A-04 (no source column), A-12 (Yahoo values move intraday) |
| Features (live) | `features.session_state` (analyst; clock-based completion, `intraday/features.py:131-152`); `_quant_state` / `LiveLearner.on_bar` → `to_5m(today.iloc[:n5*5])` | row-count bucketing in the two model paths | A-05 |
| Features (training) | `build_samples` (`autolearn/features.py:143-176`) on clock-bucketed 5m bars | `FEATURE_VERSION` = hash of feature names + code | parity broken by A-05 / A-06 |
| Decision | analyst → playbook → EV → risk → `plan_gate` | Phase B | — |
| Outcome / learning | `learning.grade_session` (factor reads vs the next 30 min); `Ledger.resolve` (autolearn) | catch-up path crashes (A-02); the ledger is empty (A-01) | — |

**Observed in the snapshot.**
- Recorded sessions: 09-29 (374/375 minutes, volume all 0), 09-30 (10 minutes only, from 15:20: the late start the
  README describes), 10-05 … 10-08 (373/375, missing 12:20–12:21), 10-09 (morning only).
- No duplicate timestamps.
- Feed provenance for 10-09: `"kotak+yahoo (1 of 558 polls from Yahoo)"`. Which minute came from Yahoo is not
  recoverable.

### L2. Option chains

| Stage | Where | Notes |
|---|---|---|
| Source | Kotak option chain + quotes (`KotakOptionChain.chain`, `kotak.py:231-292`); NSE v3 chain fallback (`chains.NSEOptionChain`); model chain as last resort | `FallbackChain`: NSE at most every 3 min |
| Timestamp | `attrs["ts"] = pd.Timestamp.now(tz=IST)` after the fetch | fetch time, not quote time (A-11) |
| Derived | `fill_iv`: IV back-solved from mid, else **from the LTP** | a stale LTP becomes a valid-looking IV (A-11) |
| Storage | recorder + tape → `data/<day>/chains/<U>_<expiry>_<HHMM>.csv` with `_ts`, `_source` (temp + rename) | excluded from the journal branch; 90-day artifact + `chains-YYYY` release Parquet (`data archive-session`) |
| Consumers | engine (live pricing, fills), `RecordedChains` (replay: newest ≤ ts, V-04), plan research (`at()` newest ≤ t within the max age, V-04), sleeves (15:20 eve quotes), `deploy/audit_fills.py` | — |

### L3. News and LLM reads

| Stage | Where | Notes |
|---|---|---|
| Source | RSS: ET Markets/Stocks, Moneycontrol, Mint, BS, Google News, RBI (`news.DEFAULT_SOURCES`) every 4 min | — |
| Timestamp | `ts` = RSS `pubDate`, else fetch time. A naive timestamp is assumed IST. Items > 5 min in the future are dropped; `ts = min(ts, now)` (`news.py:275-295`) | publish time |
| Seen time | `journal.news_add(fresh, now)` stores `seen_at` (`engine.py:389-390`, `journal.py:192-199`) | median in-session publish→seen lag **74 min** |
| Live visibility | an item enters `NewsDesk.items` only after its fetch → effectively seen-time (V-08) | — |
| LLM reads | background thread; `rd["at"]` = arrival; ignored before arrival (`news.py:398-401`) | V-08 |
| Learning | `grade_news` grades from **`ts`** (publish) (`learning.py:139-180`) | A-09 |
| What-if replay | visible at `seen_at` (`deploy/whatif.py:89`) | V-07 |

### L4. End-of-day warehouse (NSE public files)

| Stage | Where | Notes |
|---|---|---|
| Source | NSE archives: F&O bhavcopy (two formats), participant OI/vol, `ind_close_all`; NSE API: FII/DII, GIFT, events, holidays; BSE bhavcopy | `data.yml` 20:15 + 08:10 IST |
| Raw | **not stored**; `manifest` keeps URL, SHA-256, bytes, rows, status (`warehouse.py:182-195`) | re-download needed to re-parse |
| Normalized | `parse_*` (`data/nse.py`) → `Warehouse.upsert` keep-last on keys | A-14 |
| Storage | `warehouse` release assets `{table}_{period}.parquet`, `--clobber` | no versioning |
| Consumers (live) | `deploy/warehouse-context.sh` pulls `corp_events`, `participant_oi`, `fii_dii`, 13 months of `fo_bhav` → `ivhist.load(end=day−1)`, `brain.load_flows(end=day−1)` (V-05) | PIT-safe |
| Consumers (research) | `research/warehouse_research.py`, `laws.py`, `law_audit.py`, `entry_check.py`, `wings.py`, `autolearn/research.py` (EOD track) | Phase E |
| Audit | `quantdesk warehouse-audit` (`data/audit.py`) checks coverage, duplicates, expiries and settlement vs official closes | Phase E/H |

### L5. Research priors → live

`research.yml` (Saturday) runs `quantdesk research` on Yahoo daily/hourly/5m and the warehouse, then force-pushes
`edges.json`, `links.json`, `buyer_edge.json`, `vrp_positioning.json` and `experiment_log.jsonl` to the `research`
branch. Each live job (`deploy/research.sh`) copies those into `runtime/research/`; the engine reads them at session
start. Temporal order: computed on data up to the Saturday run, used the following week, so forward only. The
snapshot seen is from 2026-10-03. Whether each prior is used in a decision is Phase B.

### L6. Global markets and heavyweights

Yahoo daily and 5m for 18 markets (`brain.GlobalFeed`). Prior session = the last daily bar dated before the IST day
(`brain.py:165`). Intraday 5m bars count only after their close (`brain.py:150-151, 173-176`). Live PIT is fine (V-05).
Exchange date labelling for futures (ES=F) is assumed, not verified.

### L7. Paper execution → outcome → learning (for the lineage view only; details in Phases B/D/F)

```
plan → sim.IntradayBroker fill (Kotak bid/ask at that moment or model) → journal.trades/fills
     → close: review/grade → learning.grade_session (setups) → memory.json
     → autolearn ingest: closed trades → autolearn/paper_trades.jsonl (once each)
```

The snapshot has 0 rows in `trades` and `fills`. The account was reset to ₹5L on 2026-10-05, and no trade happened
since (Q-05). This lineage is therefore unexercised in the persisted state.

### L8. Failure → valid-looking data (the A2 rule)

| Failure | What the system does | Visible? |
|---|---|---|
| Kotak candle call fails | Yahoo bars served for that minute | aggregate count only (A-04) |
| Futures bars missing a minute | index bar volume = 0 | no (A-16) |
| No two-sided option quote | IV solved from the LTP | no (A-11) |
| Chain fetch stale | stamped with fetch time | no (A-11) |
| Kite tick without exchange time | wall clock | no (A-17) |
| Grading raises | whole pass skipped, WARN event | yes, as a WARN event only (A-02) |
| Yahoo revises past bars | different model fit, different AUC | no fingerprint (A-12) |
| Warehouse refetch differs | rows replaced keep-last | only via result data digests (A-14) |
| Hand-over minutes | never recorded | no (A-06) |

---

## A3. Point-in-time and leakage

| # | Vector | Verdict | Evidence |
|---|---|---|---|
| 1 | Future bars in model features | **Clean** (row-causal) | `_day_features` uses bars ≤ i, plus the previous session; `or_pos` zero until the OR is known (`quant.py:136-138`); probe (A-08) + `tests/test_causality.py` |
| 2 | Future bars in non-model sample columns | **Leak, evaluation only** | `sig5` / `day_ret` back-fill (A-08) → regime breakdowns |
| 3 | Labels | **Clean** | `y` = close 6 bars ahead > close, same session only; NaN past the close (`quant.py:171-174`, `features.py:157-176`); `label_end` = exit bar end |
| 4 | Train/test contamination (walk-forward) | **Clean** | day-grouped expanding window; lockbox days excluded; purge/embargo correctly inert (V-02) |
| 5 | Locked final test integrity | **Weak** | verify bypass on a row-count change (A-07); never accessed yet (`lockbox_access.jsonl`: only `created`) |
| 6 | Feature definition: live vs training | **Broken (latent)** | row-count bucketing (A-05) + hand-over hole (A-06) |
| 7 | Future option-chain info | **Clean** in replay and plan research | newest snapshot ≤ t (V-04); snapshot ts = fetch completion (conservative) |
| 8 | Future OI / volume | **Clean** for live (polled, completed bars). Futures volume is grafted on the same minute's index bar | `_with_futures` → `self.completed(...)` |
| 9 | Future news (live) | **Clean** | V-08 |
| 10 | Future news (learning) | **Clock mismatch** | graded from publish time, which the desk never had (A-09). Not lookahead past the publish time, but credit for moves before the desk saw the story |
| 11 | Future news (replays) | **Clean** in what-if (`seen_at`, V-07). The bootstrap does not grade news by replay, it uses `grade_news` (A-09) | — |
| 12 | Future regime / EOD info intraday | **Clean** | V-05 |
| 13 | Persistence leakage: live | **Clean as ordered**: memory updated at the close, used the next day | `engine._learn` at close; `_apply_memory` |
| 14 | Persistence leakage: replays | **Leak** | replay memory carries later lessons into earlier dates (A-15) |
| 15 | Research priors | **Forward only** | computed on Saturday, used the next week (L5). Phase E checks the in-sample selection inside the research itself |
| 16 | Paper / live timing | the stale-feed halt uses `realtime_age` (`feeds.py:78-85`); armed triggers on 5 s LTP or each new bar's range | Phase B5 |
| 17 | Outcome resolution | **Clean** (code) | `Ledger.resolve`: `before` = bars complete by ts; `after` = bars starting ≥ ts; waits for a full window (`ledger.py:155-185`). Unexercised (A-01) |
| 18 | Feature/label versioning | **Partial** | `FEATURE_VERSION` hashes the feature code but not the bucketing or the source (A-05, A-04) |

**A3 bottom line.**
- No classic lookahead was found in model features, labels, splits, chain replay or EOD context.
- The PIT defects are of a different kind:
  - the live features are built differently from the training features (A-05, A-06);
  - news learning runs on the wrong clock (A-09);
  - replay memory crosses time (A-15);
  - one integrity check can be silently bypassed (A-07);
  - one evaluation-only column back-fills (A-08).
- Most of the autolearn PIT machinery (the ledger guards) is correct, and unexercised.
