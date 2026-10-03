# Research, paper promotion, and release gates

## Research protocol

The newest-third chronological slice is useful for development validation, but every weekly run has
inspected it. Reports and JSON outputs call it **rolling validation** and never an untouched holdout.
The forward test is the paper desk: results that survive discovery, rolling validation,
false-discovery control and the cost hurdle are labelled **PAPER CANDIDATE**, and the paper desk
uses them (today, the D1 intraday drift prior), so live paper trading is where they prove out.

Every research command appends an experiment record with a unique run ID, commit, research-code
digest, data ranges and digests, hypothesis IDs, parameter values, discovery and rolling-validation
statistics, costs, and verdicts. The scheduled workflow restores and republishes the append-only
ledger from the research branch. Do not remove earlier ledger rows.

## Paper gate: the bar before real money

Run a strategy in the paper account with the same quote, fill, slippage, brokerage, statutory fee
and risk code intended for release. Use recorded real market data; model-chain fills do not count.
The command enforces this: only trades filled at the live book on both entry and exit (real point-in-time
quotes) are counted. The rest are excluded and the count is reported (`excluded_not_real_point_in_time`).

~~~bash
python -m quantdesk intraday paper-gate --strategy orb --since YYYY-MM-DD
~~~

The report is read-only and never enables anything. It passes (**PAPER PASS**) only with all of:

- At least 60 observed NSE sessions and 30 closed trades of the strategy.
- Positive net P&L and profit factor at least 1.15 after booked costs.
- Maximum drawdown no greater than 10% of starting capital.
- No failed risk, limit, kill-switch, or reconciliation checks in the trial.

## The self-learning loop's gates

`quantdesk/autolearn` retrains challengers after every session. A challenger can replace the champion only after all
of the following, every one measurable and recorded in the registry's event log:

1. **Walk-forward.** Out of sample on day-grouped, purged, embargoed folds, against the thresholds in
   `docs/ARCHITECTURE.md` (sample, calibration beyond noise, net expectancy after costs with a block-bootstrap
   P > 0.80, profit factor, drawdown, turnover).
2. **The locked final test.** It is created once and never used for selection. Each look is logged.
3. **The live shadow (paper) record.** At least 10 sessions and 60 signals, positive net expectancy, and better than
   the champion on common sessions.
4. **Risk.** Zero risk-limit violations, and the artifact must verify.

The champion it replaces stays as the rollback target. None of this enables real money: the paper gate above
remains the minimum for that, and it is a separate, human decision.

## Plan-level research and the directional-entry gate

[PLAN_RESEARCH.md](PLAN_RESEARCH.md). Only `real_point_in_time` plan outcomes, from the desk's own recorded books, can:
- qualify a configuration;
- spend the locked final period;
- register or promote a plan model;
- support a DTE or horizon change.

Modelled-chain results are **scenario analysis only**. Bhavcopy end-of-day results are descriptive.

A directional option trade needs a plan champion promoted on real point-in-time evidence and a positive expected net R
from it (`autolearn.require_approved_model`). Without one the desk takes no directional trade, and its reads stay
advisory.

## Operational acceptance targets

| Area | Release target | Evidence |
|---|---|---|
| Desk availability | At least 95% of expected one-minute heartbeats across the latest 20 NSE sessions; no unexplained full-session outage | Journal heartbeat history and Actions runs |
| Data freshness | 95th-percentile bar age at most 2 minutes and option-chain age at most 4 minutes while entries are enabled; stale data blocks entries | Recorded timestamps, feed-failure tests, paper checks |
| Recovery point | Restore the last committed SQLite journal with no integrity errors; if the runner is lost mid-session, replay recorded bars and quote snapshots to reconcile the paper ledger | journal restore, integrity check, replay and fill audit |
| Recovery time | Resume or reach a safely stopped state within 15 minutes of incident detection, without duplicate trades | Recovery drill timing and idempotency checks |
| Paper performance | The paper gate above; no synthetic-only result can qualify | paper-gate output |
| Mobile UX | Test iOS Safari and Android Chrome at 360, 390, and 430 CSS-pixel widths; no clipped controls or horizontal page scroll; stale, closed, offline, and cached states must be distinct | Mobile browser checks and offline drill |

CI enforces deterministic software gates: the full test suite, JavaScript syntax, workflow
permissions and immutable action references, dependency vulnerability audit, risk limits,
deployment configuration, journal integrity/recovery, and paper-broker integration. Live uptime,
data freshness, and candidate performance are measured from paper-operation evidence; CI cannot
claim those from synthetic fixtures.

## Public app and research disclosure

The current Pages app is intentionally a **full paper-performance disclosure**. It publishes the
paper account's balance and P&L, open and closed paper positions, trade-level fills/rationales for
up to 150 recent trades, session reviews, the last two sessions of desk reads, headlines, and
charts. The public research branch publishes aggregate research reports and the experiment ledger.
This contains no real broker account, personal identity, or credentials. Treat every published
value and narrative as public and permanent.

Broker and service credentials belong only in GitHub Actions **Secrets** or local environment
variables. Never put them in YAML, the Pages payload, commit history, logs, or report artifacts.
The only current broker secret is KOTAK_CONSUMER_KEY; no order credentials are required for the
paper desk. Revisit this disclosure before adding user accounts, live orders, private notes, or
any non-paper balance.

## Incident recovery

1. Stop the paper runner using the workflow cancel control or the configured kill switch. Confirm
   no second run owns the journal.
2. Restore the journal branch with deploy/journal.sh restore. The script fails closed if the
   remote cannot be fetched and checks SQLite integrity before allowing the session to resume.
3. If the runner died mid-session, recover the run's session-data artifact or chains-YYYY
   archive, replay the recorded bars/chains through the paper engine, and run the fill audit.
   Do not delete or reset the old journal to make a restart succeed.
4. Resume only after broker-state/journal reconciliation, risk checks, and the kill-switch state
   are understood. Save the journal after the recovery run and record the incident in the review.
5. If SQLite integrity fails, preserve a copy of the damaged database and restore the last known
   good journal before replaying missing data. Never overwrite the only copy.
