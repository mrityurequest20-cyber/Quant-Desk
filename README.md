# QuantDesk journal (machine-written)

State the live paper desk carries from one trading day to the next: `intraday/journal.db` (every
thought, decision, fill, trade and review), `intraday/broker.json` (paper cash and positions),
`intraday/reviews/*.md` (one written review per session) and `intraday/data/<date>/*_1m.csv` (the
bars it saw). Rewritten by the workflow after every run. Don't edit by hand.

Read it locally: `git fetch origin journal && git archive FETCH_HEAD | tar -x -C runtime`, then
`python -m quantdesk intraday trades` / `stats` / `review`, or `python -m quantdesk serve`.
