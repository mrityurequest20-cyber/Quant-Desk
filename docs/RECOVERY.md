# Journal and session recovery

The paper account consists of the SQLite journal, broker state, session reviews, and recorded
one-minute bars under `runtime/intraday/`. The scheduled runner restores and saves this directory
on the `journal` branch. Chain snapshots are stored as workflow artifacts because they are too
large for Git.

## Restore the last saved journal

1. Stop or cancel the runner and confirm no other process owns the account journal.
2. From a checkout with access to the repository's journal branch, run:

   ```bash
   deploy/journal.sh restore
   ```

   The script refuses to start from an empty journal if the branch exists but cannot be fetched.
   It checks `PRAGMA integrity_check` before reporting a restored journal. If the check fails,
   preserve a copy of the restored files and stop; do not reset or overwrite the only copy.
3. Inspect state with `python -m quantdesk intraday stats`, `trades`, and `review` before
   restarting the paper runner. Compare broker cash/positions with open journal trades.

## Recover a runner that stopped mid-session

1. Keep the failed run's artifacts. Retrieve its recorded bars from the journal branch and its
   option-chain snapshot from that failed Actions run's artifact named `chains-YYYY-MM-DD`.
2. Restore the journal, broker state, and session data first. Confirm that the interrupted session
   is not already closed or owned by another runner.
3. Replay the exact recorded session through the paper engine and run the fill/reconciliation
   checks. Session and trade IDs are used to avoid creating duplicate journal entries.
4. If replay cannot reconcile, leave the paper account stopped and investigate from a copy of the
   journal. Never delete a session or start with a fresh account to make the mismatch disappear.

## Resume safely

Resume only after journal integrity passes, broker cash and positions reconcile with journal fills,
all open trades have known stops, the daily risk budget and kill switch are in the expected state,
and the feed is fresh. Confirm a fresh heartbeat after restart and inspect the first paper fills.
The target is a safely stopped or reconciled session within 15 minutes of detection; do not meet
that target by bypassing a failed check.

Record the incident, detection time, recovery time, missing data, replay result, and any duplicate
or rejected fills in the session review. Keep a copy of damaged files until the recovered account
has been reviewed and saved successfully with `deploy/journal.sh save "recovery YYYY-MM-DD"`.
