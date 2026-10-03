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

## The learning loop (`runtime/intraday/autolearn`)

Every command here is safe to rerun.

| Situation | Commands | What happens |
|---|---|---|
| Corrupted journal | `deploy/journal.sh restore`, then `python -m quantdesk autolearn verify` | The restore checks SQLite integrity. While `PRAGMA quick_check` fails, the live engine halts entries and the cycle refuses to ingest trades. Restore the last good journal (above) before anything else. |
| A torn or edited learning record | `python -m quantdesk autolearn verify` (exit 1 names the file and line), then `python -m quantdesk autolearn recover` | `recover` moves a torn trailing line to `<file>.corrupt` (never deletes it) and rebuilds the registry state from its event log. An edited line in the middle is not repaired automatically: restore the journal branch and investigate. |
| Incomplete training or cycle | `python -m quantdesk autolearn recover`, then `python -m quantdesk autolearn cycle` | Stages left `running` or `failed` are reset and rerun. Finished stages with unchanged inputs are skipped. A lock older than 3 hours is taken over, on the record. |
| Failed promotion | `python -m quantdesk autolearn status`, then `python -m quantdesk autolearn promote` | Promotion is fail-closed: nothing changed. The registry's `events.jsonl` has a `promotion_refused` or `deferred` event naming every failed gate. |
| Stale feeds | `python -m quantdesk intraday doctor` | The desk takes no new entries while the last bar is more than `stale_feed_min` minutes old, and resumes on its own when bars flow again. The cycle validates and quarantines bad sessions before learning from them. |
| Champion misbehaving | `python -m quantdesk autolearn rollback --reason "…"` | The previous champion, verified first, is champion again on the next session. If there is no rollback target, it refuses. |
| Halt everything now | `touch runtime/KILL` (remove it to resume) | The running desk flattens every paper position once and takes no new entries. |
| "Broker and journal disagree" at start | `python -m quantdesk intraday stats`, then compare `runtime/intraday/broker.json` positions with today's open trades | Entries stay halted for the session until the difference is explained. Typical cause: a crash between a fill and its journal entry. Restore the last saved journal and broker state together (`deploy/journal.sh restore`), or square off with `python -m quantdesk intraday live --close-out`. |
| Plan research failed or was interrupted | `python -m quantdesk autolearn research` | Safe to rerun: each run writes a new `plan/studies/<id>/`. `plan/trials.jsonl` and `plan/lock_access.jsonl` are append-only, and a rerun never reopens a lock that was opened (`lock.json` records it). Never delete `plan/lock.json` or `lock_access.jsonl`: they are the record that the locked period was looked at once. |
| "plan champion … has no real point-in-time evidence" | `python -m quantdesk autolearn status`; the plan registry's `plan/registry/events.jsonl` | The live learner refuses a plan champion whose card doesn't say `real_point_in_time` (fail closed: entries halt). Restore the journal branch's `plan/registry` from the last good save; never edit a card by hand to clear it. |
| No directional trades at all | the thought feed: "no approved plan model" | Expected until a plan model is promoted on real point-in-time evidence (`autolearn.require_approved_model`). It is not a fault. |
| Safe mode | the journal's CRITICAL `risk` events and `health.last_error` in the heartbeat | Three failed minutes in a row squared off every position and halted entries for the rest of the session. Fix the cause before the next session; the next session starts clean. |

After any recovery, run `python -m quantdesk autolearn status`. Its "recovery point" line gives the registry event
number, the ledger record count and an integrity verdict. Then save with `deploy/journal.sh save "recovery …"`.
