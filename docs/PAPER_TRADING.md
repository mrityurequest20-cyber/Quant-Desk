# Paper trading by hand: the owner's runbook

**Paper money only.** Nothing here can reach a broker. Real money needs the owner's separate, explicit yes, and is not built.

## The picture

```
Build tab (you)  ->  relay queue  ->  paper runner (GitHub Actions)  ->  risk gate  ->  paper broker  ->  ledger
                                              ^ the gate decides; the app and the runner only carry the order
```

* You choose and size a trade in the **Build** tab (the market read, the news and the ideas are above the builder), write **why**, review it, and send it.
* The **paper runner** (started by the scheduler on trading days at 06:00 IST and running to midnight, in four parts) takes it through the risk gate within seconds, fills it at the **offer** (a buy) or the **bid** (a sell) with the real costs, and writes it into a hash-chained ledger.
* The **Paper** tab shows the account, the positions with your thesis, the orders and why any was refused, and the **kill switch**.

## The very first time (once, before the first trade)

The runner refuses to start without a saved account (a lost state must never silently begin the history again). Start it once by hand:
GitHub, Actions, **Paper runner**, Run workflow: tick **new_account**, set **handover** to about 5 minutes from now (IST, HH:MM), leave **until** as it is. When it is green, the account is on the relay and every later start finds it. Check the Paper tab shows an equity of 5,00,000.

## Placing a trade

1. Build tab: pick the index, the expiry and a structure (or use *Ideas for your view*). Only structures the paper desk can open show **Send as a paper order**: long options on NIFTY, BANKNIFTY, FINNIFTY or MIDCPNIFTY, and, since 8 Nov 2026 (`paper.allow_short_legs: true`, the owner's order), **hedged packages with sold legs** (verticals, condors, butterflies): they go as ONE order, every leg opens together or none does, and the gate judges the worst case (a naked short call or a calendar is always refused; the long that covers a sold option cannot be sold before the sold option is bought back). A sold option never goes alone: only as a leg of a package. If the switch is turned off in the config, a structure with a sold leg is a what-if again.
2. Write the **strategy name** and the **thesis**: why this trade, now, and what would make you wrong (at least 20 characters; it is kept with the trade).
3. **Review order**: each leg, its price limit (two ticks or 2% above the offer you saw), the most you can lose. **Send paper order**.
4. Open the **Paper** tab. A fill shows under *Orders* as `filled`; a refusal shows the gate's reasons.

## What a refusal means

| It says | What it means |
|---|---|
| the quote is N s old / no usable two-sided quote | the price was not fresh (30 s) or had no bid and offer: wait, or pick a busier strike |
| it would risk X (the whole premium plus fees), over 2.5% of equity | too big: fewer lots |
| … would be lost against a loss budget | the open positions plus this one could take equity under today's 5% floor or the 10% drawdown floor |
| closed / does not trade today | outside 09:15-15:30 IST or a holiday |
| expired (waited N s) | the runner was not running for 2 minutes after you sent it (for example a hand-over at 11:50, 17:40 or 23:30): nothing was bought; send it again |
| the offer is X, above your limit | the price ran away from what you saw: nothing was bought |
| new orders wait: the relay could not be given the latest fills | the runner could not save to the relay for 30 s: exits still work |

## The brakes (you do not have to remember them)

* **Daily loss limit 5%** of the day's starting equity: no new entries for the day and everything held is sold.
* **Drawdown halt 10%** below the high-water mark: no new entries and everything is sold until **you** clear it (it is deliberately not in the app: tell the assistant).
* **Kill switch** (Paper tab, two taps): nothing opens and everything held is sold, until you resume.
* **15:20 IST:** anything expiring today is sold at the bid and not bought; **15:31:** what could not be sold is cash-settled at the index price.
* There is **no cap on the number of trades**: only the loss limits.

## If something is red

* **Paper tab says the runner has not reported:** Actions, *Paper runner*: is a run in progress? If the last one is red, open it: the log says why (the relay did not answer, a saved account did not verify, or two histories disagree). Orders wait two minutes and then expire, nothing is filled meanwhile. The scheduler starts it again within ten minutes up to three times a day; or Run workflow by hand.
* **11:50, 17:40 and 23:30 (a few minutes each):** the runner changes hands (a new job starts). An order sent then expires; send it again.
* **What trades when:** the runner is up from 06:00 to midnight, but the risk gate decides what can trade: NSE F&O from 09:15 to 15:30. MCX and currency are refused until their costs and holiday calendars are verified in the config; until then the evening is watched, not traded.
* The ledger backup on the `paper-ledger` branch is **off** (this repository is public: it would show every thesis and position). To turn it on, set the repository variable `PAPER_LEDGER_BACKUP` to `yes`.

More: docs/RECORDING.md ("The paper runner", "Running the paper runner"), docs/LIVE.md (the relay's routes).

## Special sessions (Muhurat trading)

On a day the exchange opens for a special window (Diwali Muhurat trading, 8 Nov 2026, 14:20 to 15:30 IST, NSE circular NSE/CMTR/76941), `config/quantdesk.yaml` `calendar.special_sessions` names it. That one entry opens the **paper gate** for NSE/BSE F&O inside the window and makes the **relay's Kotak poller** run inside it (`deploy/cloudflare/kotak.js` `SPECIAL_SESSIONS`; a test fails if the two disagree). Recorders, health reports, the scheduler and the watchdog do not know about it, so on such a day start what you need **by hand** (Actions, Run workflow):

1. **Kotak universe** (the option chains for the Build tab), any time before the window.
2. **Kite tick recorder**: `first_until` 15:35, `second_until` 15:36. It logs in to Kite by itself.
3. **Paper runner**: `handover` 14:05, `handover2` 15:35, `handover3` and `until` 15:36, leave `new_account` off.

Nothing else changes: the same risk gate, the same limits, paper money only.

## AUTO v2: the paper desk writing, testing and choosing its own strategies (paper money only)

Since 13 Nov 2026 AUTO runs **v2** (`quantdesk/paper/auto2.py`). Your words: "a system which is sophisticated, advanced ... can take any strategy in its place, create its own strategy, permutation, combination, can trade."

* **It writes the strategies.** Every combination of the following, 1,836 strategies in all, each with a short id that says exactly what it is (for example `IC1.fran.1/0.5.d`: an iron condor one strike wide, flat view, rich volatility, any day, the near expiry, take profit at 1R, stop at 0.5R, out by the close):
  * a market context: direction up, down or flat; volatility rich, cheap or either; any day or the expiry eve;
  * a structure that suits it: long call or put, debit or credit spreads, iron condor or butterfly, long straddle or strangle;
  * a width, an expiry (the near one or the next), a take-profit, a stop, and out-by-the-close or up to three sessions.
* **It tests them.** Whenever a strategy's context holds for an underlying (the four indices and the 20 stocks), it is traded **in shadow**: no money, but at the real bid and offer of every leg, with the desk's real fees, closed by its own exits. Each result is scored in R (profit over the most it could have lost). The record is kept on the private relay, so it grows across sessions.
* **It chooses.** A strategy trades with paper money only after **8 shadow trades**, and then by **Thompson sampling**: a short record is shrunk towards zero, the best plausible draw wins, and a draw at or below zero does not trade. Capital flows to what has worked and away from what has not.
* **It trades** through the runner and the risk gate like your orders: one lot, a multi-leg structure as one package, sold options only inside a bounded structure. Its own exits close it, with sold legs bought back first. Your hand-placed orders work beside it.
* **What it sees:** direction from the same four readings as v1, and the volatility state: the options' at-the-money implied volatility against the volatility the price has shown over the last hour. Your own research found direction hard to forecast and volatility easier; the catalogue lets the record decide which contexts pay.
* **Where to watch it:** Positions → Strategy lab (the record's leaders, what is live, what it sees now), and the 15:50 push.
* **Bounds:** the risk gate's loss caps only (2.5% of the account a trade with fees, 5% a day, a 10% drawdown halt). No cap on trades, strategies or positions.
* **Switches:** off with the repository variable `PAPER_AUTO` = `no`; back to v1 with `PAPER_AUTO_ENGINE` = `v1`.
* **Not proven to make money.** The shadow record is the evidence it builds; the first days are mostly shadow trades.

## AUTO v1: the paper desk deciding for itself (paper money only)

You said go on 8 Nov 2026: the desk may take trades by itself beside yours. Since 13 Nov 2026 it is **ON for every run** ("enable the self-trading ... a system which trades itself"): it trades the four index families and the 20 watchlist stocks. To switch it off, set the repository variable `PAPER_AUTO` to `no`. Your hand-placed orders are unchanged and work at the same time.

It looks for **high reward for little risk**, and it is **not an intraday-only system**.

* **Entry** (`quantdesk/paper/auto.py`, pure rules; every order's thesis spells out why): one lot, the first strike out of the money (more convexity for the same stop), of an expiry at least three days away. Only when at least two of four readings agree and none points the other way: resting bid/offer pressure around the money (calls against puts), the forward the options imply against the futures price (put-call parity), the index's own move over five minutes, and the **tone of the recent news** (the relay's digest: last two hours, medium or high impact, not recaps).
* **Risk and reward:** the most it can lose is the premium, and a stop caps that at **40% of the premium**. There is **no cap on the gain**: a trailing stop arms at +80% (twice the risk) and follows 30% below the peak, so a trade that works can run for several times what it risked. Most trades will lose their small stop; the winners pay for them. The peak is written into the ledger, so a restart or the night cannot loosen the trail.
* **Overnight:** ten minutes before the close each position gets a decision. It is **held** if its expiry is still at least two days away, it is under three calendar days old (a holiday counts as a day, so the carry over Tuesday 10 Nov is short), it is not well under its entry, the readings do not point the other way and the news is not against it; otherwise it is sold. In the morning it keeps its stop and trailing stop. It also leaves early when the readings turn the other way or strong news turns against it.
* **No cap on trades (owner, 8 Nov 2026: "do not keep any cap on the trades ... keep a cap on your losses").** There is no limit on the number of trades or open positions and no stop of AUTO's own: the bound is the risk gate's loss caps (2.5% a trade with fees, 5% a day, a 10% drawdown halt, and the loss budget that limits what can be open at once). The only guards left are against double-handling: it never adds to a contract already held, and it does not re-buy the same contract within five minutes of its last fill in it. The gate still applies to every one of its orders: the kill switch, the daily loss cap, the drawdown halt, quote freshness and size. It only ever sells **the lots it bought itself** (strategy name starts `AUTO v1`, quantity from its own ledger fills); yours are never touched, even if you buy the same contract. **Because it has no cap, AUTO may use up the whole loss budget, and then your own buys are refused with the gate's "loss budget" reason**; its open premium shares that budget with yours, a position carried overnight can limit the next day's buys, and the gate's flatten/trim act on all positions by size, not by who opened them. A fault in the autopilot cannot stop the runner or the brakes. **Before switching AUTO off, check the Paper tab for open `AUTO v1` positions**: with the autopilot off nothing manages their stops. After any entry order for an index and direction (filled or refused) it waits 60 seconds before another for that index and direction. **Ceiling to plan for:** the relay can hold an account of about 960 ledger rows (about 1.2 MB, 1.24 KB a row). An AUTO that trades freely can write 200 or more rows a day, so the ceiling can arrive in **3 to 4 days**. Past it the relay refuses every save of the account: the app's equity and positions go stale, order results are not posted back, and after 30 seconds new entries (yours too) wait, while exits, stops, the gate and the kill switch keep working on the runner. To keep that from happening AUTO **stops opening new positions once the ledger reaches 800 rows** (a storage guard, not a trade cap; it still manages and exits what it holds, and says so in its status line). To go on, the limit is raised (`MAX_CHUNKS` in `deploy/cloudflare/paper.js`) or the ledger is archived, both a deliberate change. AUTO also proposes nothing while the account is already stopped for the day or halted by the drawdown limit.
* **It is not proven.** Its readings are the ones the app's Flow panel logs and grades; until they have a record they are a hypothesis, and a high-reward/low-hit-rate style needs many trades to judge. Its trades, with the price it saw and what it paid (slippage), are the evidence. Judge it on the Paper tab by the `AUTO v1` strategy name.
