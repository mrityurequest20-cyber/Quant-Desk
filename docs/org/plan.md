# Weekly plan: week of 5 Oct 2026

Written by the chief of staff. The next one is due Saturday 10 Oct (AUTONOMY.md, shift step 5).

## Where we are
- **Evidence level 2/4.** L1 is replicated and robust on v2 (10 of 10). L2 passed its registered test but is fragile.
- **Self-found share: 0%.** All nine defects on record (docs/org/scorecard.jsonl) were found because the owner asked.
  This week the organization starts finding its own.

## This week's three outcomes
1. **The rota runs every day and every audit is closed with evidence.** Six departments, six audits, each finding
   filed as its own issue. Target: at least 3 `self_found`, 0 `owner_found`.
2. **The forward links start measuring.** The first eves of expiry_eve_entry_v1: NIFTY on Mon 5 Oct, SENSEX on Wed
   7 Oct. The first `official` settlement events. A skip rate under 10%.
3. **Issue #3 closed:** dated fee rates and lots for new studies, and the BSE 1–2 Jan 2024 exclusion, each cited to
   its official source.

## Departments
| Department | Priority this week | Trust | Audit |
|---|---|---|---|
| Research | issue #3; Wednesday: re-attack L1's narrow-instrument caveat with data already on hand | probation | Wed + Sat |
| Orders | the first eves' fills, settlement checks and skips, each verified by hand | probation | Tue + Sat |
| Data | the Monday warehouse audit on the fresh week; the stock-options backfill | probation | Mon + Sat |
| Risk & compliance | Thursday: full sweep of order paths, secrets and permissions | standard | Thu |
| Architecture | Friday: the slowest tests (test_handover 11 min, test_plan_research 7 min); duplicate implementations of costs and settlement | standard | Fri |
| Chief of staff | this plan; next Saturday's plan from real department reports | standard | Sat |

## Stop doing
- Waiting for the owner to ask "is this robust?". Every relied-on claim gets attacked on the rota.

## Levers only the owner holds
- None this week.
