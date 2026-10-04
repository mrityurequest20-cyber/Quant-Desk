# Backlog: what the desk builds next, ranked

The desk engineer (docs/AUTONOMY.md) works open `desk-request` issues first. When none are open, it takes the
**first unblocked item** below. Each item ends in a pre-registered result, whether it passes or fails, or in plumbing
that unblocks one.

**Ranking:** expected edge × how soon real evidence can exist.

**Rules for every item:**
- the spec is committed alone, before code or results;
- real point-in-time quotes are the only evidence that qualifies anything;
- nothing goes live or changes size without the owner.

## Where the evidence stands (4 Oct 2026, evidence level 2/4)

[principles.json](principles.json) is the ledger. In short:
- **L1, the expiry-eve premium, has replicated.** It was found on NIFTY and BANKNIFTY. Every one of five instruments
  it never saw was positive: FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX. Pooled t is 4.46 over 286 weeks.
- **L2, far wings as crash insurance, has replicated pooled** (t 3.28). It is strong on BANKNIFTY alone.
- **L3, move size is forecastable:** found, and locked out of sample in time on NIFTY and BANKNIFTY.
- **L4, buyers of short-dated options overpay:** found.
- **N1, index direction from price patterns:** rejected.

**Forward tests on real quotes:**
- expiry_seller_v1, sleeves A and B: NIFTY, BANKNIFTY;
- expiry_seller_v2, sleeve C: BANKNIFTY far-wing condor;
- expiry_seller_v3, sleeves D and E: FINNIFTY, MIDCPNIFTY, SENSEX, naked and insured.

## The queue

1. **L1 and L4 on stock options** (fo_stock_opts, backfilling from 2019).
   - *Why:* about 180 stocks are about 180 more held-out instruments. If L1 is a law of option markets, it should
     show up there too.
   - *The catch:* stock options settle physically. Measure the premium from the eve's close to the expiry-day
     close at 15:20 (exit before settlement), not to settlement.
   - *Steps:* pre-register; pool by expiry month; liquid names only (a premium-turnover floor); costs from the cost
     model with stock-option spreads.
   - *Done when:* a registered result is in the ledger, whichever way it goes.
2. **Event-aware expiry selling** (L1's tail).
   - *Why:* a heavyweight's results or a policy event between entry and settlement caused some of the worst days,
     e.g. HDFC Bank on 17 Jan 2024.
   - *Steps:* one pre-registered rule, tested on all 7 index instruments at once (the law table).
3. **L3 everywhere.**
   - *Steps:*
     - wire the HAR forecaster in shadow next to the desk's, for 20 sessions;
     - test it pooled across the indices and liquid stocks: a law of volatility, not of NIFTY.
   - *Then:* a pre-registered filter. Sell only when implied variance exceeds forecast variance by k.
4. **Expiry-day 0-DTE decay.**
   - *Blocked until:* 8 expiry days of tape, across all taped instruments (NIFTY, BANKNIFTY, SENSEX, FINNIFTY,
     MIDCPNIFTY).
5. **Overnight theta.**
   - *Blocked until:* 20 tape sessions.
   - *Then:* sell at 15:25, buy back at 09:20, on every taped instrument, pooled.
6. **Earnings IV crush on stocks.**
   - *Needs:* fo_stock_opts and historical results dates (corp_events history; NSE's board-meeting archive).
   - *Then:* pre-register selling straddles the day before results and buying back the day after, pooled across stocks.
7. **Plan research on the real tape** at the self-review's milestones (10, 20, 40 sessions).
8. **Data scout (weekly, standing).** One web search a week for a public source that would test a principle on new
   ground. Examples: index options on another exchange, a longer history, results and policy calendars. File it as a
   `desk-request` with a fetch plan, then build the fetcher (docs/AUTONOMY.md, "Going outside").
9. **Portfolio sizing**, once two sleeves are eligible:
   - a risk-budgeted allocator: per-trade max loss ≤ 4% of equity, correlation-aware, half-Kelly cap;
   - a proposal to the owner, never applied by itself.
10. **Live execution through Kotak.** Last. Only after a sleeve passes paper and the owner says go.

## Data the desk now collects by itself
- **NSE F&O bhavcopy, daily since 2019:**
  - every index option (fo_bhav);
  - every stock option and future (fo_stock_opts, no longer discarded).
- **BSE F&O bhavcopy since 2024:** SENSEX and BANKEX (bse_fo_bhav).
- **The chain tape:** real Kotak bid/ask every minute, for NIFTY, BANKNIFTY, SENSEX, FINNIFTY and MIDCPNIFTY.
- **Kotak 1-minute option candles:** the 30 days Kotak keeps, then every session (option-minutes releases).

Nothing here needs the owner. Paid feeds were ruled out: TrueData has no API on the owner's plan.
