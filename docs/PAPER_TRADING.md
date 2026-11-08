# Paper trading by hand: the owner's runbook

**Paper money only.** Nothing here can reach a broker. Real money needs the owner's separate, explicit yes, and is not built.

## The picture

```
Build tab (you)  ->  relay queue  ->  paper runner (GitHub Actions)  ->  risk gate  ->  paper broker  ->  ledger
                                              ^ the gate decides; the app and the runner only carry the order
```

* You choose and size a trade in the **Build** tab (the market read, the news and the ideas are above the builder), write **why**, review it, and send it.
* The **paper runner** (started by the scheduler on trading days, from about 08:30 IST) takes it through the risk gate within seconds, fills it at the **offer** (a buy) or the **bid** (a sell) with the real costs, and writes it into a hash-chained ledger.
* The **Paper** tab shows the account, the positions with your thesis, the orders and why any was refused, and the **kill switch**.

## The very first time (once, before the first trade)

The runner refuses to start without a saved account (a lost state must never silently begin the history again). Start it once by hand:
GitHub, Actions, **Paper runner**, Run workflow: tick **new_account**, set **handover** to about 5 minutes from now (IST, HH:MM), leave **until** as it is. When it is green, the account is on the relay and every later start finds it. Check the Paper tab shows an equity of 5,00,000.

## Placing a trade

1. Build tab: pick the index, the expiry and a structure (or use *Ideas for your view*). Only structures the paper desk can open show **Send as a paper order**: today that means long options on NIFTY, BANKNIFTY, FINNIFTY or MIDCPNIFTY (a spread has a short leg: it stays a what-if until a margin model exists).
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
| expired (waited N s) | the runner was not running for 2 minutes after you sent it (for example the 12:20 hand-over): nothing was bought; send it again |
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
* **12:20-12:25:** the runner changes hands (a new job starts). An order sent then expires; send it again.
* The ledger backup on the `paper-ledger` branch is **off** (this repository is public: it would show every thesis and position). To turn it on, set the repository variable `PAPER_LEDGER_BACKUP` to `yes`.

More: docs/RECORDING.md ("The paper runner", "Running the paper runner"), docs/LIVE.md (the relay's routes).

## AUTO v1: the paper desk deciding for itself (paper money only)

You said go on 8 Nov 2026: the desk may take trades by itself beside yours. It is **off unless switched on**: tick `auto` when you run the **Paper runner** by hand, or set the repository variable `PAPER_AUTO` to `yes` so every scheduled run has it. Your hand-placed orders are unchanged and work at the same time.

* **How it decides** (`quantdesk/paper/auto.py`, pure rules, every order's thesis spells out why): it buys the at-the-money call (or put) of the nearest expiry, **one lot**, only when at least two of three readings agree and none points the other way: resting bid/offer pressure around the money (calls against puts), the forward the options imply against the futures price (put-call parity), and the index's own move over five minutes.
* **How it leaves:** +30% on the premium, -25%, 25 minutes, the signals turning the other way, or ten minutes before the close. It never holds overnight and it **only ever sells its own positions** (strategy name starts `AUTO v1`); yours are never touched.
* **Its own limits, on top of the risk gate:** at most 2 positions open, 6 entries a day, 20 minutes between entries on an index, and it stops for the day (and sells) once its own day is down 1% of the capital. The gate still applies to every one of its orders: the kill switch, the daily loss cap, the drawdown halt, quote freshness and size. A fault in the autopilot cannot stop the runner or the brakes.
* **It is not proven.** These are the readings the app's Flow panel logs and grades; until they have a record they are a hypothesis. Its trades, with the price it saw and what it paid (slippage), are the evidence. Judge it on the Paper tab by the `AUTO v1` strategy name.
