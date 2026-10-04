# How the desk runs without anyone in a chat

## Trading never waits for a person or a language model

| What | Where it runs | When |
|---|---|---|
| Wake-up | Cloudflare cron → `Desk scheduler` → `Desk waiter` | every 10 min 07:30–15:20 IST on weekdays; Sunday 17:30 IST |
| The paper desk + chain tape | `Live paper desk` (GitHub Actions) | every NSE trading day, 08:30–15:31 IST |
| Expiry sleeves (pre-registered) | `Live paper desk`, afternoon job | after the close |
| Option-minute backfill | `Live paper desk`, afternoon job | after the close |
| Learning cycle (autolearn) | `Learning cycle` | after every session |
| Self-review → GitHub issues | `Self-review` | after every session; 17:10 IST fallback |
| Edge research | `Edge research` | Saturdays 09:47 IST |
| Progress snapshot | `Live paper desk`, afternoon job | after every session |
| Progress report → "Desk progress" issue | `Progress` | Saturdays 10:40 IST |

The engine, risk limits, sleeves and research are deterministic Python. Language models (Claude, Gemini, Ollama) are
optional **readers** of the news and an after-close reflection, with no say over orders, sizing or risk. If every key
fails or a usage limit is hit, the desk runs on its rules, exactly as before (`intraday/llm.py`).

## Development requests queue up as GitHub issues

After each session `quantdesk intraday self-review --issues` (`ops/selfreview.py`) files what needs fixing or building
as issues labelled `desk-request`:
- `desk:bug`, `desk:ops`, `desk:data` and `desk:research` say what kind of request each one is;
- `auto-clears` marks a problem that closes itself when the check passes again.

The checks:
- a missed session;
- engine errors;
- a long run without a trade;
- drawdown;
- chain-tape gaps;
- expiry-sleeve skips, settlement problems, bugs, retirements and decision points;
- failed workflows;
- data milestones that make new research worth running.

The issues are the desk's to-do list. They persist whether or not anyone is around, and they show up in the GitHub app
on the owner's phone.

## The desk engineer: a scheduled Claude session

A Claude Code routine (claude.ai → Routines; it fires a fresh cloud session on a schedule) works the queue:

1. **Urgent first:** open `desk-request` issues labelled `desk:bug` or `desk:ops`, newest first.
2. **Then the rest of the queue:** the other open `desk-request` issues.
3. **When nothing is open:** the top unblocked item of [BACKLOG.md](BACKLOG.md).

Every session ends by commenting on each issue it touched, saying what it changed and the commit.

If Claude is unavailable (a usage limit, an outage), nothing breaks. The issues wait and the next session picks them
up.

### What the engineer may do on its own
- Fix bugs and failed workflows, with a test that reproduces the failure, after the full suite passes.
- Add data plumbing, checks, reports and docs.
- Write a **new** pre-registered spec (`docs/prereg/*.json`, committed alone before any code or result). Then:
  - run the study on the runner (`Study` workflow);
  - record the result;
  - add a forward paper sleeve with its own spec and ledger.
- Close the issues it resolved, each with the commit that resolved it.

### What it must never do (it comments on the issue for the owner instead)
- Place, enable or route any live order, or touch broker credentials.
- Loosen a risk limit (`intraday.risk`, the drawdown halts, the loss budget), or raise position size.
- Promote any strategy to the paper account's sizing or to real money. It reports eligibility; the owner decides.
- Edit a registered spec, a ledger, or a result after the fact; delete data; rewrite history.
- Print, commit or log a secret.
- Push with a failing test suite.

## Getting smarter, deliberately

- [principles.json](principles.json) is what the desk believes about markets. Each principle is stated without
  naming an instrument and placed on an evidence ladder: found → replicated → forward → proven, or rejected. It lists
  every piece of evidence for and against. Negative results stay, because they are knowledge too.
- A principle climbs only on a registered result. Replication means instruments the effect was never fitted to: an
  edge found on NIFTY and BANKNIFTY must also hold on FINNIFTY, SENSEX and the rest.
- The weekly progress report (`ops/progress.py`) compares this week with last week and with the first snapshot.
  - **Its headline is the evidence level:** the highest rung any principle has reached.
  - **Below it:** knowledge, research throughput, forward sleeves, the paper account and data.
  - Every line says improved, same or worse.

## How the owner steers
- Comment on any `desk-request` issue; the next engineer session reads the thread.
- Add an issue yourself with the `desk-request` label. Use `owner-decision` for things only you can decide.
- Re-rank [BACKLOG.md](BACKLOG.md).
- Pause or resume the routine at claude.ai → Routines.
