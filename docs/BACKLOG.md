# Backlog: what the desk builds next, ranked

The desk engineer (docs/AUTONOMY.md) works open `desk-request` issues first. When none are open, it takes the
**first unblocked item** below. Each item ends in a pre-registered result, whether it passes or fails, or in plumbing
that unblocks one.

**Ranking:** expected edge × how soon real evidence can exist.

**Rules for every item:**
- the spec is committed alone, before code or results;
- real point-in-time quotes are the only evidence that qualifies anything;
- nothing goes live or changes size without the owner.

## Where the evidence stands (4 Oct 2026)

| | Evidence | Verdict |
|---|---|---|
| Index direction (7 rules, 13 years of minutes) | real minutes | failed the lock: no edge |
| Option buying (0–5 DTE) | real bhavcopy | loses: 17 of 20 setups |
| Move-size forecast (HAR) | real minutes | **validated**: 13–35% better than the desk's forecaster |
| Expiry-eve premium sale | real bhavcopy, 7.7 y | **the one edge**: strangle t 2.9–3.3, but its tail eats most of it |
| Far-wing condor, BANKNIFTY (W5) | real bhavcopy | **passed**: keeps 60% of the mean and cuts the worst trade from −₹50.7k to −₹20.9k → sleeve C |
| Far wings, NIFTY | real bhavcopy | t 1.99 against a 2.0 bar: not qualified |

**Forward tests running:**
- expiry_seller_v1, sleeves A and B on NIFTY and BANKNIFTY;
- expiry_seller_v2, sleeve C on BANKNIFTY;
- both on real quotes, from 5 Oct 2026.

## The queue

1. **Stack the one edge across more expiry days.**
   - *Why:* the edge is the same economic effect: weekly option sellers are paid for one night's gap risk. Every
     independent expiry adds trades a year without raising size per trade. SENSEX weeklies (BSE, Thursday) would
     double the weekly count, and BANKEX, FINNIFTY and MIDCPNIFTY monthlies add more.
   - *Steps:*
     - probe Kotak for BSE F&O chains (`bse_fo`) and FINNIFTY / MIDCPNIFTY with the data-probe workflow;
     - add the BSE F&O bhavcopy to the warehouse;
     - run the expiry-eve study on SENSEX history with expiry_wings_v1's variants and selection rule (a new spec);
     - add the qualifiers to the chain tape and a forward spec.
   - *Done when:* each new index has a pre-registered result on real history, and the passers have a forward sleeve.
2. **Event-aware expiry selling.**
   - *Why:* some shock days were scheduled:
     - HDFC Bank's results the evening before the 17 Jan 2024 expiry cost the BANKNIFTY strangle −₹45.8k/lot;
     - the Feb 2026 budget week.
   - *Steps:* one rule, pre-registered: skip when a heavyweight's results (top 3 index weights) or a policy event
     falls between entry and settlement. Test it on 2019–26 with the corporate-event data. One test, once.
   - *Done when:* the result is recorded, and a v3 spec exists if the rule passes.
3. **The validated vol forecast in the live read (shadow).**
   - *Steps:*
     - wire vol_forecast_v1's HAR model (`autolearn/volstudy.py`) next to the desk's VolForecaster, logged but not
       used, for 20 sessions;
     - then pre-register: does selling only when implied variance exceeds forecast variance by k improve the expiry
       sleeves (history first, then forward)?
   - *Done when:* the shadow log exists and the filter has a result.
4. **Expiry-day 0-DTE decay.**
   - *Blocked until:* the tape holds 8 expiry days.
   - *Then:* pre-register selling the 0.20/0.05 condor at 10:00 on expiry day, out at 15:15 or a 2× credit stop,
     evaluated on the tape's real quotes.
5. **Overnight theta.**
   - *Blocked until:* 20 tape sessions.
   - *Then:* pre-register selling at 15:25 and buying back at 09:20, real quotes at both ends.
6. **Plan research on the real tape:** at the milestones the self-review files (10, 20, 40 sessions).
7. **Term structure:** calendar spreads from the tape's three NIFTY expiries, once 20 sessions exist.
8. **Day-type model.**
   - *Question:* is the day a range day or a trend day? Use 13 years of minutes (aeron7) and the Kotak backfill.
   - *Use:* it picks a structure, never a direction.
9. **Portfolio sizing.**
   - *Blocked until:* two sleeves are eligible.
   - *Then:*
     - a risk-budgeted allocator: per-trade max loss ≤ 4% of equity, correlation-aware, capped at half-Kelly;
     - lots compound with equity;
     - a proposal to the owner, never applied by itself.
10. **Live execution through Kotak.**
    - *Blocked until:* a sleeve passes paper and the owner says go.
    - *Needs:* defined-risk structures only, a hard max-loss guard, the kill switch, and fill reconciliation against
      the tape.

## Data wanted (the owner can help)
- **TrueData's API** (not Velocity):
  - if the plan includes historical options, credentials as repository secrets let a workflow pull option history
    directly;
  - real minute quotes for past expiries would turn months of waiting into a backtest.
- **BSE F&O bhavcopy:** public; to be added by item 1.
- **Corporate results calendar history:** for item 2; the warehouse has part of it.
