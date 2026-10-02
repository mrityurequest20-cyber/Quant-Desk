# Research, paper promotion, and release gates

## Research protocol

The newest-third chronological slice remains useful for development validation, but every
weekly run has inspected it. Reports and JSON outputs call it **rolling validation** and never
call it an untouched holdout. Research candidates no longer feed the live desk's prior loader.

Routine analysis is cut off before the locked final test window **2026-10-05 through
2027-03-31**. Ordinary research excludes that period from statistics, scorecards, parameter
stability, and positioning reports. Do not change candidate code, parameters, or the window
after the final period starts. A final result is not available until the period ends; if the
candidate set or period changes after access, the test is consumed and a new future window is
required.

Every research command appends an experiment record with a unique run ID, commit,
research-code digest, data ranges and digests, hypothesis IDs, parameter values, discovery and
rolling-validation statistics, costs, and verdicts. The scheduled workflow restores and republishes
the append-only ledger from the research branch. Keep exploration changes in version control;
do not remove earlier ledger rows.

## Candidate paper gate

Research is not a promotion decision. Run a candidate in an isolated, paper-only account with the
same quote, fill, slippage, brokerage, statutory fee, and risk code intended for release. Use
recorded real market data when available; model-chain fills do not count as a paper pass.

From the repository root, evaluate a strategy with:

~~~bash
python -m quantdesk intraday paper-gate --strategy orb --since YYYY-MM-DD --account candidate-orb
~~~

The report is read-only. Promotion review requires all of these:

- At least 60 observed NSE sessions and 30 closed candidate trades.
- Positive net P&L and profit factor at least 1.15 after booked costs.
- Maximum drawdown no greater than 10% of starting capital.
- No failed risk, limit, kill-switch, or reconciliation checks in the trial.
- A passing locked final test for the pre-registered candidate, with the effect still greater than
  realistic round-trip costs.

Passing paper metrics alone returns **PAPER PASS; FINAL TEST REQUIRED**. The tool never promotes
or enables a strategy. A separate reviewed release may add a row to
`runtime/research/promoted_research.json` only with `verdict: PROMOTED`, `promotion.approved`,
`paper_gate_passed`, `locked_final_test_passed`, and a review ID. Legacy `EDGE` rows and candidate
reports are ignored by the live prior loader.

## Sealed paper trial

Before the window opens, register a candidate that has already met all cost-inclusive pre-period
paper gates in its own dedicated account:

~~~bash
python -m quantdesk intraday register-paper-candidate --strategy orb --since YYYY-MM-DD --account candidate-orb
~~~

Registration writes an exclusive manifest under `runtime/research/locked_candidate.json`, captures
the pre-period gate and a fingerprint of the paper engine and configuration, and cannot be
replaced. Registration is refused once the final window starts. The final evaluator checks only
trades opened and closed inside the sealed dates, then appends a pass or fail to
`runtime/research/experiments.jsonl`. It can run only once for that candidate and account, and it
never promotes automatically. A retained `.locked-test.lock` means the evaluation started; inspect
the ledger and lock before attempting recovery. The final result is unavailable until the window
has elapsed and qualifying real paper observations exist.

## Operational acceptance targets

| Area | Release target | Evidence |
|---|---|---|
| Desk availability | At least 95% of expected one-minute heartbeats across the latest 20 NSE sessions; no unexplained full-session outage | Journal heartbeat history and Actions runs |
| Data freshness | 95th-percentile bar age at most 2 minutes and option-chain age at most 4 minutes while entries are enabled; stale data blocks entries | Recorded timestamps, feed-failure tests, paper checks |
| Recovery point | Restore the last committed SQLite journal with no integrity errors; if the runner is lost mid-session, replay recorded bars and quote snapshots to reconcile the paper ledger | journal restore, integrity check, replay and fill audit |
| Recovery time | Resume or reach a safely stopped state within 15 minutes of incident detection, without duplicate trades | Recovery drill timing and idempotency checks |
| Paper performance | The candidate gate above; no synthetic-only result can qualify | paper-gate output and locked-test report |
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
