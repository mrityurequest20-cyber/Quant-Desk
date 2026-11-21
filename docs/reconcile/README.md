# Reconciling the paper record

A plan here books paper fills the relay never received, as reconstructed rows appended to the paper account. It exists because of audit K-01: on 20 Nov 2026 the relay refused the runner's state, each part of the day ended with fills it never held, and the next part started from its shorter copy.

**What a plan holds:** what the run logs show happened (time, side, contract, lots). It never holds a fill price, a fee or a P&L, because this repository is public. An opening's strategy may carry the public index level and volatility its stop is measured from (`p` and `d`, as AUTO v2 writes them for an overnight hold).

**Who applies one:** the owner, on their written decision. A dry run changes nothing; like any manual workflow, only someone with write access to the repository can start it, and it reads the relay with the same keys.

**How each event is priced** (`quantdesk/paperlink/reconcile.py`):
- the quote comes from the recorded chain files of that moment;
- the price follows the paper broker's own rules: a buy or cover at the offer plus the modelled impact, a sale at the bid less it;
- the fees come from the desk's cost model.

**How rows are booked:** each row is appended, so no existing row is touched. Its thesis is tagged `[reconstructed …]` with the quote it was priced on, how old that quote was, and the original time.

## Running one

The workflow is **Paper reconcile** (`paper-reconcile.yml`). It is started by hand only, on `main`. It is queued with the paper runner, so the two never run together.

1. Run it with the plan's id (for example `2026-11-20`) and `apply` off.
   - This dry run prints how many rows it would book, the ledger's length before and after, and a fingerprint.
   - It changes nothing.
2. Run it again with `apply` on and the plan's id typed in `confirm`.
   - It sends the reconciled account to the relay and reads it back.
   - The relay only accepts a ledger that extends its own.

The run refuses, and changes nothing, in any of these cases:
- the relay's ledger is not exactly the one the plan continues: its length and the time of its last row. This includes a second run.
- a recorded quote is missing, crossed, or older than the plan's limit.
- a close names a position that is not held.

## Plans

| Plan | Rows | Why |
| --- | --- | --- |
| `2026-11-20.json` | 12 | The 10:16 IST MIDCPNIFTY buy (morning part), and the afternoon part's package and 9 exits. All were lost when the relay refused the state. It must be applied before the runner's next start (after it, the ledger no longer matches and the plan is refused). It leaves one position open, the MIDCPNIFTY 23 Nov 14200 put: AUTO v2 sells it by 15:15 IST on 23 Nov at the latest (its expiry rule; its take-profit or volatility stop can sell it earlier, and the runner's 15:20 sale and 15:31 settlement are the backstop) (had the afternoon part known of it, it would have sold it at 15:15 on 20 Nov; no log shows that sale, so none is booked). |
