# The desk as an organization

The goal is a digital organization that runs, checks and improves itself, rebuilding parts of itself when the evidence
says so. **The owner should never be the one who finds the defect.** If an outside reviewer (the owner, ChatGPT, anyone)
finds a problem before the desk did, that is the organization's failure, and it is scored as one.

This file is the charter. [AUTONOMY.md](AUTONOMY.md) is how the engineer works a shift. `quantdesk/ops/org.py` is the
part that runs without any language model: the audit rota, the scorecard and the trust levels.

## Departments

Each department has a mandate, standing duties that run on a schedule, and the right to say no inside its mandate.
Today one engineer session runs every department, delegating to department agents (`.claude/agents/*.md`). The
structure doesn't change when there are more sessions: each department becomes its own session reporting to the
chief of staff.

| Department | Mandate | Standing duties (automatic) | Says no to |
|---|---|---|---|
| **Chief of staff** (the board) | the plan: what to build next and why; resources; the weekly report | Saturday: the weekly plan (`docs/org/plan.md`) from every department's report, the scorecard and the research proposals | work that serves no goal in the plan |
| **Engineering** | code, tests, pipelines, workflows | fix `desk:bug` / `desk:ops` issues; keep CI green | — |
| **Architecture** | module boundaries, tech debt, speed, structure | Friday audit: slow and flaky tests, dead code, error logs, duplication, the tech-debt register | structural changes without a reason on record |
| **Data** | the warehouse, feeds, coverage, provenance | Monday audit: `warehouse-audit` on fresh data, gaps, schema changes, manifest status | studies on data it hasn't vouched for |
| **Research** | specs, studies, the principles ledger | Wednesday audit: re-attack the top caveat on a relied-on principle; spec/result integrity; provenance | any claim without a registered result |
| **Orders** (execution) | sleeves, paper fills, settlement, the paper account | Tuesday audit: every fill against its quote, the settlement gap, the skip rate, ledger integrity | a sleeve rule change outside a new spec |
| **Risk & compliance** | the hard limits, secrets, pre-registration discipline, statutory rates | Thursday audit: every order path, every secret's handling, risk config against last week, workflow permissions | anything that crosses a hard limit; it has a veto |
| **Internal audit** | adversarial review of all of the above | Saturday: audit the organization itself (escaped defects, the scorecard, the plan); Sunday: the heavy deterministic audits | it reports; it never fixes what it audits |

**Independence:** whoever built something never audits it. The internal-audit agent has no write tools. A finding goes
to the owning department as a `desk-request` issue; the fix is that department's job.

## The audit rota: critical evaluation without being asked

Every day `python -m quantdesk org rota --issues` (workflow `Org`) opens that day's audit as an issue labelled
`desk:audit`, assigned to a department by the table above. The engineer's shift does it **before** routine queue
work, and the next day's rota escalates anything left undone. Each audit issue states:
- the questions to attack, written as hypotheses that the desk is wrong;
- the commands to run;
- what a closing comment needs: every finding with its evidence and severity, each filed as its own `desk-request`
  issue, or "no finding" with the evidence that it was looked for.

On Sundays the same workflow also starts the deterministic audits on GitHub's runners: `warehouse-audit`, `entry-check`,
and an informational re-run of the latest law audit on fresh data. Their reports land in the `Study` runs, and the
Monday audit reads them.

A good audit asks what would make the desk's own claims false. The L1 evidence audit of 4 Oct 2026
(docs/reports/2026-10-04_l1_evidence_audit.md) is the model: it found that fills were bhavcopy closes, that five
held-out instruments were effectively two, and that the sleeves settled differently from the history. The owner had to
ask for it. The rota exists so that never has to happen again.

## Accountability: rewards, penalties and earned autonomy

Language models don't learn from points the way people do. What changes their behaviour is what they are allowed to do
and what they read before they start. So rewards and penalties here are **autonomy** and **lessons**, recorded in
`docs/org/scorecard.jsonl` (append-only, in git):

| Event | Points | Also |
|---|---:|---|
| `self_found`: a defect found by the desk's own audit or check | +3 | the finding's issue |
| `fixed`: a fix shipped with a regression test, CI green | +2 | the commit |
| `owner_found`: a defect an outside reviewer found first (an escape) | −5 | a lesson, and a new standing check so that class is caught next time |
| `regression`: a change that broke something, or a red main | −3 | a lesson |
| `asked_owner`: a decision handed to the owner that the desk should have made | −2 | a lesson |
| `reverted`: a change that had to be undone | −2 | a lesson |

Each department's trust is its trailing 8-week score:
- **probation** (below 0): every change from it gets an independent internal-audit pass before it ships, and its audit
  runs twice a week;
- **standard** (0–9): the normal evidence trail (AUTONOMY.md, "How a change ships");
- **trusted** (10 or more): small, tested changes may ship in batches, and its audit can drop to fortnightly.

Every penalty writes a lesson into `docs/org/lessons.md`. The engineer reads the lessons at the start of every shift.
That is how a mistake made once changes the next shift's behaviour.

**The north-star metric is the self-found share:** self-found defects ÷ (self-found + owner-found). It starts at 0%: on
4 Oct 2026 every defect in the record was found because the owner asked. It goes on the weekly progress report next to
the evidence level.

## What the owner still holds

The owner holds the hard limits (AUTONOMY.md): real money, looser risk, rewriting the record, secrets. Everything else
belongs to the organization. When the owner points out something the desk should have found, it is logged as
`owner_found`, with its lesson and its new check. That way the next one gets found without anyone asking.
