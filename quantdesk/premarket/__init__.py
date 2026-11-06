"""The pre-market brief: what today holds for every F&O instrument, read before the market opens.

`premarket.yml` runs it every 15 minutes from 07:15 to 09:15 IST, and on demand. Each run reads:

* **the universe**: every F&O underlying in the latest NSE bhavcopy (indices and stocks, no cap), with its price,
  lot, strike step and how liquid its options were (`universe.py`);
* **the calendar**: macro events (config `calendar.events`), index expiries, and every F&O company's results board
  meeting from NSE's event calendar;
* **history**: for each company, its own past results reactions (how far the stock moved, what the options had
  priced, what a straddle across the result returned), from the calendar where NSE has it and inferred from the
  data's fingerprint (implied volatility collapses as the price jumps) where it doesn't (`history.py`);
* **global cues and headlines**: overnight moves abroad (Yahoo) and public RSS headlines that name an instrument.

It writes `brief.json` and `brief.md`: today's events with their historical analogues, every reporting company with
its implied move against its own history, and a ranked watch-list in which every name carries its reasons.

Public data only: NSE's warehouse tables, Yahoo, RSS. Never the Kite feed (licensed to the subscriber). It places
nothing, sizes nothing, and changes no desk path. The labels it prints are context, not tested trading rules.
"""
