# Quant-Desk Remediation Log

The running record of post-audit remediation. One item at a time; each item waits for owner approval before work starts.
It sits alongside the forensic audit (PR #9, `audit/`); it does not modify the audit register.

**Live-trading authorization: NOT GRANTED.** Nothing in this file authorizes live trading.

| Field | Value |
|---|---|
| Programme stage | **S0: readiness and containment** |
| S0 status | **NO-GO**: critical blockers open (see §3); engineer routine paused (interim) |
| Last updated | 2026-10-09 (S0 readiness assessment, session 1) |
| Repo revision assessed | `main@c96909f1f0f4e77ad30817ca53f2df7b28bb9098` (2026-10-04 13:09 UTC) |
| Audit revision assessed | `claude/exciting-galileo-criwur@813849453aa4` (PR #9, draft, open) |
| Runtime state assessed | `journal@9cdfbeb` (2026-10-09 22:48 IST), `gh-pages@e80b0ed` (2026-10-09 16:14 IST) |
| Next item awaiting approval | §6: owner actions O-2, O-3, O-5, then the first remediation PR (A-19) |

## Evidence labels

- **VERIFIED NOW**: collected directly in this session (command, API response or file named).
- **PREVIOUSLY REPORTED**: in an earlier audit report but not reproduced in this session.
- **UNKNOWN / OWNER**: cannot be established from the evidence available to this session.

One label never silently becomes another.

---

## 1. Item log

| # | Date | Item | Stage | Status | Approval |
|---|---|---|---|---|---|
| 1 | 2026-10-09 | S0 readiness assessment (read-only) | S0 | **done**: this file | requested by owner |
| 2 | 2026-10-09 | O-1: pause the engineer routine | S0 | **done**: `enabled: false` at 22:36:11 UTC (S0-05) | owner approved in session |
| 3 | 2026-10-09 | O-4a: ask the audit session to commit and push the H–L artifacts | S0 | **declined by that session (correctly)**: it needs the owner's approval typed in that session, not a relayed request. **Owner action** (S0-02) | owner approved in session |
| 4 | — | Owner actions O-2, O-3, O-4b, O-5 (§6.1) | S0 | **awaiting owner** | owner only |
| 5 | — | First remediation PR: A-19 test clock seam (§6.2) | S0 | **proposed, not started** | needs owner approval |

---

## 2. S0 readiness report

### S0-01: Repository state and baseline

| | |
|---|---|
| **Status** | VERIFIED |
| **Evidence** | `git status` (clean); `git rev-parse HEAD origin/main` → both `c96909f`; `git rev-parse --is-shallow-repository` → `true` (local clone has 50 commits) |
| **Conclusion** | Working branch `claude/quant-desk-s0-readiness-0vkxm8` = `main@c96909f`; tree clean. `main` has had no commits since 2026-10-04 13:09 UTC. |
| **Uncertainty** | The local clone is shallow: full history was not inspected locally. |
| **Required action** | None. |
| **Pass condition** | Met. |

### S0-02: Audit artifacts: location, completeness, integrity

| | |
|---|---|
| **Status** | **BLOCKED: H–L evidence missing** (A–G VERIFIED) |
| **Evidence** | GitHub: PR #9 is open and draft and has not been merged. Its branch `claude/exciting-galileo-criwur@8138494` holds 45 files under `audit/` (10,194 lines). `audit/QUANTDESK_FORENSIC_AUDIT.md` phase tracker: A–G "done", **H, I, J, K, L "not started"**. The register lists **68 findings** (A:19 B:11 C:8 D:8 E:9 F:7 G:6) plus controls V-01…V-38 and questions Q-01…Q-13. A search of `main`, `journal`, `research`, `gh-pages` and the audit branch found no Phase H–L findings. |
| **Conclusion** | The A–G evidence is preserved on a remote branch, and its git blob hashes are pinned in Appendix A. The handoff reports **115 findings across A–L**. That leaves **≈47 findings (H–L) that exist in no repository location this session can see**. Among them: India VIX zero readings, the Pages 404, kill-switch reachability, journal mutation, replay failures, crash/orphan exposure, and the lost/unrecoverable evidence. They are PREVIOUSLY REPORTED only. |
| **Located (VERIFIED NOW, 2026-10-09 ~22:30 UTC)** | The audit session `session_01W3ozoc7W4HkbhbWrrxBk83` ("QuantDesk forensic audit") is idle. Its status reads "Phase L audit artifacts written under audit/, left uncommitted". Its final turn (2026-10-09 18:49:50 UTC) says the H–L artifacts are **untracked files under `audit/`**, kept local on the owner's instruction, and that it will commit and push them to `claude/exciting-galileo-criwur` when the owner says so. Its container was reachable at 22:26–22:28 UTC: file reads were served from it. |
| **Uncertainty** | The H–L files exist **only** in that session's container, which can be reclaimed when idle. They are not hashed anywhere. Also, PR #9 is unmerged, so its branch could be deleted. |
| **Relay attempt** | 2026-10-09 ~22:36 UTC: this session asked the audit session (on owner approval) to push. It **declined**, citing the owner's standing instruction in that session to keep artifacts local, and said only the owner, typing in that session, can lift it. That is the correct control. It reported (**not verified here**): tracked changes 0; register hash `e49341c0…` unchanged; Phase K probes (10) and Phase L probes (21) pass. It also correctly flagged a timestamp error in this session's message ("about 22:40 UTC" vs a 22:36:11 send); the owner's answer came before 22:36:11. |
| **Required action** | **Owner, urgent:** tell the audit session to commit and push the H–L artifacts to `claude/exciting-galileo-criwur` (as it offered). Then this log records their hashes. Do not delete that branch. Decide whether to merge PR #9 (audit-only) or tag it (e.g. `audit-a-l-2026-10-09`) so the evidence is pinned. |
| **Pass condition** | All 115 findings are committed with hashes, or the owner records which are lost and they are re-derived. The A–G branch is tagged or merged. |

### S0-03: Test baseline (independent re-run)

| | |
|---|---|
| **Status** | **VERIFIED NOW**: baseline reproduced; CI red only by A-19 |
| **Evidence** | `git archive c96909f` exported to a scratch dir. Fresh venv: CPython 3.11.17 (the CI version), `pip install -r requirements.txt` → pandas 3.0.6, numpy 2.4.6, scipy 1.17.1, pyarrow 26.0.0, yfinance 1.7.0, anthropic 1.13.0. Command: `python -m pytest -o addopts="" -q -rfEs`, with `GH_TOKEN`/`GITHUB_TOKEN`/`GITHUB_REPOSITORY` unset and a fail-closed `gh` shim first on `PATH`, so no test could dispatch a workflow or push. |
| **Result** | Run 2026-10-09 22:14:51 → 22:43:42 UTC (28m49s): **441 passed, 3 failed, 9 skipped (453)**. Failures: `test_kotak.py::test_chain_from_the_live_book[live]` and `[docs]`. Every IV is NaN at `test_kotak.py:202` (A-19 reproduced). Also `test_provenance.py::test_the_stamp_names_a_commit`, an **artifact of this run**: the `git archive` export has no `.git`. Re-run in the real checkout: `tests/test_provenance.py` → 2 passed. 3 of the 9 skips are "node not installed" (`test_cloudflare.py:54,101`, `test_web.py:128`); CI has node. The other 6 are sample-dependent (`test_handover.py:45` ×3, `test_kotak.py:348,363,380`). **Reconciled: 441 + 1 + 3 = 445 passed, 2 failed (A-19), 6 skipped, the same as previously reported.** The 3 node tests were not run in this session. |
| **Coverage gap** | The suite passes on pandas 3.0.6, yet production logs A-02 (`grading failed: Cannot losslessly convert units`) at every session (S0-11). **No test exercises catch-up grading on real-shaped data.** A green suite does not mean that path is healthy. |
| **Previously reported** | 445 passed / 2 failed / 6 skipped. The 2 failures are `test_kotak.py::test_chain_from_the_live_book[live,docs]` (A-19, wall-clock date bomb since 2026-10-06 15:30 IST). |
| **Uncertainty** | Dependencies are unpinned (A-03). This session's resolution already differs from the audit's recorded environment (numpy 2.5.3 → 2.4.6, scipy 1.18.1 → 1.17.1, pyarrow 25.0.1 → 26.0.0). So "the baseline" is not reproducible across days. |
| **Required action** | Fix A-19 (§6.2). Pin dependencies with a lockfile (separate later item, A-03). |
| **Pass condition** | The suite is green on a pinned environment, twice, on different days, including the 3 node tests. |

### S0-04: Branch protection, rulesets, required CI

| | |
|---|---|
| **Status** | **VERIFIED: FAIL** |
| **Evidence** | GitHub API `GET /repos/…/branches/main` → `protected: false`, `protection.enabled: false`, `required_status_checks.enforcement_level: "off"`, contexts `[]`. `GET /repos/…/branches/main/protection` → 404 "Branch not protected". `GET /repos/…/rulesets` → `[]`. `GET /repos/…/rules/branches/main` → `[]`. All 5 branches (`main`, `gh-pages`, `journal`, `research`, audit branch) report `protected: false`. Repo: public, `allow_auto_merge: false`. |
| **Conclusion** | Anyone or anything with write access can push straight to `main` with no review and no green CI. G-01 is confirmed as a current fact, not just a historical one. |
| **Uncertainty** | Collaborator list, deploy keys, Actions "allow GitHub Actions to approve PRs" setting, and org-level rules were not visible through this session's proxy. |
| **Required action** | Owner: protect `main` with a PR requirement, ≥1 approving review that is not the author, required status check `tests` (from `ci.yml`), no force-push, no deletion, and "include administrators". Only enable the required check **after** A-19 is fixed, or `main` is permanently blocked. |
| **Pass condition** | The API shows `protected: true` with the required review and the `tests` check. A test push straight to `main` is rejected. |

### S0-05: Autonomous engineer (G-01) containment

| | |
|---|---|
| **Status** | **CONTAINED (interim)**: routine paused 2026-10-09 22:36:11 UTC; the durable control (S0-04) is still open |
| **Evidence** | Claude Code routine `trig_01HMifSht7GsShdv8wm789cn` "Quant-Desk engineer shift": `enabled: true`, cron `CRON_TZ=Asia/Kolkata 40 17 * * 1-6`, last fired 2026-10-09 12:11 UTC, **next fire 2026-10-10 12:10 UTC (17:40 IST Sat)**. It wakes persistent session `session_0195MhBsgNBjQrBNf6ic15ja`. Its prompt: *"Every judgement call is yours … nothing waits for the owner. Ship through an engineer/ branch."* `docs/AUTONOMY.md:75` says "The owner is not in the loop". `docs/AUTONOMY.md:115` says "**Ship:** merge the branch into main … and push". |
| **Conclusion** | An agent that can change engine, risk, specs and its own instructions is scheduled to run tomorrow. Its standing instruction is to self-merge into an unprotected `main`. That directly contradicts the handoff's change-control rule ("no self-approval of safety-critical changes"). The "No real money / No looser risk" limits (`AUTONOMY.md:133-141`) are prose only. |
| **Uncertainty** | What that persistent session will actually do next. It has shipped nothing to `main` since 10-04 (G-02, consistent with `git log`). |
| **Required action** | Owner: **pause the routine** before 2026-10-10 12:10 UTC (`enabled=false`, keeping its history). This session can do that with a single API call, but only on explicit owner approval. Then branch protection (S0-04) becomes the durable control. |
| **Pass condition** | The routine shows `enabled: false` (or is re-scoped to open PRs only, with `main` protected), and the change is recorded here. |
| **Action taken** | 2026-10-09 22:36:11 UTC: `update_trigger(trig_01HMifSht7GsShdv8wm789cn, enabled=false)`, done by this session on the owner's explicit approval. The API returned `enabled: false`. Prompt, schedule, history and persistent session are unchanged. Re-enabling is one call (`enabled=true`). Keep it paused until `main` is protected and `AUTONOMY.md`'s self-merge rule is replaced by PR + independent review. |

### S0-06: Live-trading entry points, flags, credentials (repository-visible)

| | |
|---|---|
| **Status** | VERIFIED (repository only); see S0-07 for the operating state |
| **Evidence** | The only order-placing adapter is `quantdesk/execution/kite.py` (`KiteBroker`; `place_order` at :95, `cancel_order` at :114). It is constructed only at `quantdesk/cli.py:133-137` when the global `--live` flag is passed. Its constructor refuses unless **all** of these hold: `account.mode == "live"` (config is `paper`: `config/quantdesk.yaml:9`), `confirm_live=True` (`--live`), `kiteconnect` importable (not in `requirements.txt`, commented out at its end), and `KITE_API_KEY` + `KITE_ACCESS_TOKEN` set. `grep` finds **no** `--live`, `KITE_*`, or `kiteconnect` in any of the 22 workflows, the Dockerfile, `docker-compose.yml` or the systemd units. The intraday desk (the one that runs daily) uses `IntradayBroker(PaperBroker)` (`intraday/sim.py:77`). `serve` hard-wires `PaperBroker` (`cli.py:240`). Kotak is used with a consumer key only, for data endpoints (`broker-check.yml`, `kotak.py`). Kite data feed code (`intraday/feeds.py:167-178`) reads Kite credentials but places no orders. The web `/api/order` route is "paper account only" (`web/server.py:16`) and the public site is GET/HEAD only (`deploy/cloudflare/worker.js`). |
| **Conclusion** | From repository evidence, no path in the repository's scheduled automation can reach real orders. This matches audit control V-38. |
| **Uncertainty** | The repository cannot show: repository/organization **secret names** (the proxy denies the API), any self-hosted machine running a modified config or `--live`, any broker-side API apps, algos, GTTs, or open positions created outside this code. The live adapter's known defects (F-06: partial fills dropped, naive timestamps) are latent, not proven absent. |
| **Required action** | See S0-07. |
| **Pass condition** | Repository side: met. |

### S0-07: Operational live-trading state

| | |
|---|---|
| **Status** | **BLOCKED: OWNER ACTION REQUIRED: LIVE-TRADING STATE UNVERIFIED.** |
| **Evidence** | Paper journal `journal@9cdfbeb`: `trades 0`, `fills 0`, capital ₹5,00,000 since 2026-10-05, `halted: false`. That is evidence about the **paper** account only. |
| **Conclusion** | Per the handoff's evidence policy, missing credentials in the repository and zero recorded orders do **not** establish that live trading is disabled. |
| **Uncertainty** | Broker accounts (Zerodha Kite, Kotak Neo): whether API apps or trading-enabled sessions exist, whether there are any open positions or pending orders, and whether any self-hosted desk is running. |
| **Required action** | Owner, in the broker consoles and nowhere else: (a) confirm no Kite Connect app has an active access token; revoke or disable it if not needed. (b) Confirm the Kotak Neo key is data-only, with no trading session. (c) Confirm zero open positions and zero pending orders, GTTs or algos in each broker account. (d) Confirm no self-hosted QuantDesk (docker, systemd, cron) is running anywhere. (e) List the GitHub repository secret **names** (not values) under Settings → Secrets and variables → Actions. Record the date and time and the answers here. |
| **Pass condition** | Owner-signed entry in this log answering (a)–(e), with screenshots kept privately by the owner. |

### S0-08: Public site / GitHub Pages outage

| | |
|---|---|
| **Status** | **VERIFIED: DOWN; proximate cause identified; why it happened: UNKNOWN / OWNER** |
| **Evidence** | `curl https://mrityurequest20-cyber.github.io/Quant-Desk/` and `/data.json` → **HTTP 404 "Site not found · GitHub Pages"** (2026-10-09 ~22:00 UTC). Repo API → **`"has_pages": false`**. The `gh-pages` branch is fresh: `e80b0ed` "site 2026-10-09 16:14 IST", `data.json` 3,076,190 bytes. The dynamic `pages-build-deployment` workflow's **last run is #389, 2026-10-08 10:46 UTC (16:16 IST), success**. There have been **zero Pages builds since**, although `gh-pages` was pushed repeatedly on 10-09. |
| **Conclusion** | Pages was **disabled or unpublished** on the repository between 2026-10-08 10:46 UTC and 2026-10-09 (morning). The desk publishes correctly; GitHub no longer serves it. That is a settings change, not a code defect. The Cloudflare Worker proxies to that origin, so it also serves 404s for the app and `data.json`. |
| **Uncertainty** | Who or what disabled Pages. Possibilities include a manual toggle, the repository's settings being changed by an agent with admin token scope, or GitHub action on the account. Cloudflare Worker logs were not accessible. |
| **Required action** | Owner: check the account security log (github.com/settings/security-log, filter `repo.pages_*` / `pages`) for 2026-10-08 10:46Z → 2026-10-09. Then re-enable Settings → Pages → Deploy from branch `gh-pages` / root. Add a publication-freshness check later (S5). |
| **Pass condition** | `has_pages: true`, both URLs return 200, and the served `data.json` heartbeat matches the latest `gh-pages` commit. The cause is recorded here. |

### S0-09: Scheduled workflows and job inventory

| | |
|---|---|
| **Status** | VERIFIED (partial); corroborates reported issues |
| **Evidence** | 22 repository workflows plus 2 dynamic ones (Pages, Dependabot). **Scheduled:** `live.yml` (cron `22 3 * * 1-5`), `scheduler.yml` (`*/10 * * * 0-5`), `data.yml`, `org.yml`, `progress.yml`, `research.yml`, plus `selfreview.yml` (`workflow_run`), `ci.yml`, `site.yml`, Cloudflare Worker crons (`wrangler.jsonc`), and the engineer routine (S0-05). **Observed 10-05…10-09:** the real sessions are the `workflow_dispatch` runs of `live.yml` at 03:00 UTC (08:30 IST), started by the scheduler, ending ≈10:14 UTC. `live.yml`'s **own cron arrives ≈10:23-10:43 UTC (16:00-16:13 IST), after the close, every day**, and re-runs **both jobs end-to-end**. On 10-09 (run 37919282668) that meant: restore the journal, a session attempt (15 s), **sleeves again**, progress, **save the journal again**, archive, then a 14-minute Kotak backfill. The 30 most recent `scheduler.yml` runs span 10-09 05:30–18:52 UTC. Only 3 of them are `schedule` events (06:16, 13:21, 18:52 UTC); the rest are `workflow_dispatch` runs every 10 minutes, sent by the Cloudflare Worker as the owner's token (actor `mrityurequest20-cyber`). Earlier runs were not inspected. |
| **Conclusion** | The reported "post-close routine reruns the full pipeline" is **corroborated now**: it is `live.yml`'s own late schedule, not a separate backup job. The second sleeves pass and second journal save happen post-close every trading day. Their idempotency is unverified. |
| **Uncertainty** | Whether the post-close re-run changes sleeves ledgers or overwrites journal state (needs a diff of the two saves; the `journal` branch keeps no history, A-10). Worker logs. The `GH_DISPATCH_TOKEN` scope (the Worker logs its kind; Cloudflare access needed). |
| **Required action** | S5 item: remove the `schedule:` trigger from `live.yml` or make it a no-op after the close (owner-approved workflow change). Not part of S0's first PR. |
| **Pass condition** | One completed session run per trading day; no post-close re-run; the inventory table is kept in this log. |

### S0-10: Evidence preservation of runtime state

| | |
|---|---|
| **Status** | **VERIFIED: AT RISK** |
| **Evidence** | `deploy/push-dir.sh` publishes `journal` and `gh-pages` as **one orphan commit, force-pushed** each time. `journal` now = single commit `9cdfbeb`. The audit's evidence snapshot `journal@ecd03156` (2026-10-09 12:20 IST) is **no longer on any branch**. This session's copy of `intraday/journal.db` (sha256 `7c86ac40…6361d943`, 12,292,096 bytes): trades 0, fills 0, decisions 73, events 78, thoughts 743, news 4,071, equity 375. |
| **Conclusion** | Every journal save destroys the previous state on the remote (A-10 confirmed). The audit's own evidence base is already unreachable by branch. Session raw data goes to artifacts (90-day expiry) and `chains-YYYY` releases. |
| **Uncertainty** | Whether GitHub still serves `ecd03156` by SHA (unreferenced objects can be garbage-collected). |
| **Required action** | Owner-approved, low-risk, no-code step: snapshot the current `journal` and `gh-pages` heads to dated tags (e.g. `evidence/journal-2026-10-09`). Tags survive force-pushes. Durable fix is S1. |
| **Pass condition** | Dated evidence tags exist, with hashes recorded here. |

### S0-11: Known production defect A-02 (catch-up grading)

| | |
|---|---|
| **Status** | VERIFIED NOW (still occurring) |
| **Evidence** | Journal events: `WARN learning "grading failed: Cannot losslessly convert units"` at **09:15 and 12:22 every session 2026-10-06 → 10-09** (8 occurrences). Production pandas resolves to 3.x from the unpinned `requirements.txt`. |
| **Conclusion** | Matches A-02/A-03. It is logged at WARN, which self-review does not file (D-07). |
| **Required action** | Later item (after dependency pinning); not S0's first PR. |
| **Pass condition** | Zero occurrences across 3 sessions on a pinned environment. |

### S0-12: Development permissions and secrets hygiene (repository-visible)

| | |
|---|---|
| **Status** | PARTIAL: UNKNOWN / OWNER for settings |
| **Evidence** | Workflow `permissions:` blocks: `contents: write` in `live.yml`, `autolearn.yml`, `learn.yml`, `restate.yml`, `site.yml`, `data.yml`, `chain-archive.yml`, `external-data.yml`, `kotak-backfill.yml`. `actions: write` in `scheduler.yml`, `wake.yml`, `org.yml`. `issues: write` in `org.yml`, `progress.yml`, `selfreview.yml`. Actions are pinned by SHA. `live.yml` fans each LLM key across 8–15 alternative secret names. `ci.yml`'s `pip-audit` is `continue-on-error`. |
| **Conclusion** | Workflow scopes are declared per file (good) but broad. The secret-name fan-out widens what any edit to `live.yml` can read. |
| **Uncertainty** | Default `GITHUB_TOKEN` permission setting; who holds admin; the `GH_DISPATCH_TOKEN` scope. |
| **Required action** | Owner: confirm repository Settings → Actions → General → Workflow permissions = "Read repository contents" by default, and "Allow GitHub Actions to create and approve pull requests" = off. |
| **Pass condition** | Owner-recorded settings in this log. |

---

## 3. S0 go / no-go

**Recommendation: NO-GO.** S0 cannot exit, and no S1 work should start yet.

**Critical blockers**

1. **S0-07: live-trading state unverified.** BLOCKED: OWNER ACTION REQUIRED: LIVE-TRADING STATE UNVERIFIED.
2. **S0-05: the autonomous engineer** has self-merge authority over an unprotected `main`. *Interim containment: paused 2026-10-09 22:36 UTC.* The durable fix is S0-04.
3. **S0-04: `main` is unprotected**: no review, no required CI, no rulesets.
4. **S0-02: H–L audit evidence (≈47 findings) is not preserved** anywhere visible.
5. **S0-10: the runtime evidence base is overwritten** on every save. The audit's snapshot is already gone from the branch.

**Serious, but not blocking containment**

- S0-08: the public site is down (Pages disabled; settings change).
- S0-03: CI is red by date bomb (A-19), so required CI cannot be switched on yet.
- S0-09: a post-close full-pipeline re-run every day.

---

## 4. What was NOT verified in this session

- Broker accounts, tokens, positions, orders (no access). See S0-07.
- GitHub repository secret names, environments, collaborators, deploy keys, Actions settings, security/audit log (proxy-denied or settings-only).
- Cloudflare Worker logs, its secrets, the `GH_DISPATCH_TOKEN` scope; the Workers Builds failure on PR #9.
- Any self-hosted QuantDesk deployment.
- Contents of Phase H–L reports (not found).
- Kill-switch behaviour in the hosted runtime (not tested: out of scope for a read-only pass).
- Whether the post-close `live.yml` re-run mutates sleeves or journal state.
- Exact reproduction of the audit's 54 probes (not re-run here).

---

## 5. Owner access needed (summary)

| Needs | Item |
|---|---|
| Broker consoles (Kite, Kotak Neo) | S0-07 |
| GitHub Settings: Branches/Rules, Pages, Actions, Secrets, security log | S0-04, S0-08, S0-12, S0-07(e) |
| claude.ai routines (or approve this session to pause it) | S0-05 |
| Previous session's container or files | S0-02 |
| Cloudflare dashboard (Worker logs, secrets) | S0-08, S0-09 |

---

## 6. Proposed next steps (awaiting approval; nothing below has been started)

### 6.1 Owner containment actions (settings, no code)

| ID | Action | Who |
|---|---|---|
| O-1 | Pause routine "Quant-Desk engineer shift" before 2026-10-10 12:10 UTC | **done** 2026-10-09 22:36 UTC |
| O-2 | Answer S0-07 (a)–(e) from the broker consoles | owner only |
| O-3 | Re-enable Pages from `gh-pages`, after checking the security log | owner only |
| O-4a | Get the H–L artifacts committed by the audit session | **owner only**: type the approval in `session_01W3ozoc7W4HkbhbWrrxBk83`; a relayed request was declined |
| O-4b | Tag evidence: `claude/exciting-galileo-criwur` (after H–L lands), the `journal` head and the `gh-pages` head | owner, or this session on approval |
| O-5 | Protect `main` (PR + 1 non-author review + no force-push), adding required check `tests` **after** §6.2 merges | owner only |

### 6.2 Smallest first remediation PR: A-19 (test date bomb), zero production behaviour change

- **Finding:** A-19 (P4), plus it is the prerequisite for O-5's required CI.
- **Root cause (re-verified in code):** `tests/test_kotak.py:24` fixes `EXP = 2026-10-06`. `KotakOptionChain.chain` stamps `attrs["ts"] = pd.Timestamp.now(tz=IST)` (`quantdesk/intraday/kotak.py:288`). After expiry, T clamps to 0, so every IV is NaN and the assertion at `test_kotak.py:202` fails.
- **Why not the audit's proposed patch:** PR #9 suggests honouring `chain(..., ts=…)`. But `intraday/engine.py:349` and `intraday/tape.py:85` already pass `ts=now`. That patch would change the timestamp on every **production** chain snapshot, which flows into sleeves, recorder, sim fills and IV time-to-expiry (`sleeves.py:451`, `recorder.py:39`, `sim.py:28`, `plans.py:450`). That is a behaviour change, entangled with A-11, and does not belong in a test fix.
- **Proposed change:** add a module-level clock seam in `quantdesk/intraday/kotak.py`, `def _now(): return pd.Timestamp.now(tz=IST)`, used at :288. In the test, `monkeypatch.setattr(kotak, "_now", lambda: pd.Timestamp("2026-10-05 10:00", tz=IST))`. Production calls the same function with the same result.
- **Invariants preserved:** no change to any snapshot timestamp in production, any risk or entry gate, config, or workflow. No assertion is weakened (the IV>0 assertion stays).
- **Tests:** the full suite before and after, on the pinned 3.11 venv. Expected: the two A-19 failures pass, nothing else changes. A regression check: the same test with the clock seam set to 2026-10-07 must still fail. That proves the seam drives the result, after which the extra check is removed.
- **Rollback:** revert the single commit. There is no data or state migration.
- **Acceptance:** CI `tests` green on the PR; diff limited to `kotak.py` (≤3 lines) and `test_kotak.py` (≤3 lines).
- **Independent reviewer:** the owner (human). Not the engineer routine and not this session.

---

## Appendix A: Audit artifact hashes (PR #9 head `8138494`)

`sha256` prefix of the file content, then the git blob id, then the path.

```
8391758f0ed1583a  4754d53d6b5b  audit/QUANTDESK_AI_AUDIT.md
5ff6c87befaa5921  f68b8fea10a8  audit/QUANTDESK_ARCHITECTURE_MAP.md
dffe5654fc3b2ac0  34cdc300963e  audit/QUANTDESK_DATA_LINEAGE.md
e49341c0817354b1  94781c4dc908  audit/QUANTDESK_FINDINGS_REGISTER.md
b2cc4b26c09c773b  2c2c434d1aa8  audit/QUANTDESK_FORENSIC_AUDIT.md
d648803d0e5517b6  795475cebf1e  audit/QUANTDESK_LEARNING_AUDIT.md
628f53e722d1f8c4  5e5ce54f18c9  audit/QUANTDESK_OPTIONS_EXECUTION.md
7c545d0aa12b4076  de923d2cb935  audit/QUANTDESK_RESEARCH_VALIDITY.md
0d17894273666a6a  90eb7eeefe55  audit/QUANTDESK_TRADING_STATE_MACHINE.md
65da3607b92ff89f  bd41e661263e  audit/data/phase_b_funnel.json
91d5bc7a4c14b365  f2b68d1e97e1  audit/data/phase_d_learning_ab.json
999b9f2bda498a49  cd51ed5364e3  audit/data/phase_e_d1_official.txt
dc354e8399b2875f  d60fb043f05e  audit/data/phase_e_eve_spreads.txt
8a59d575ae8e02a4  994c7e435982  audit/data/phase_e_frozen_minutes.txt
cd5eff48d0c561c3  7c23fbe5a016  audit/data/phase_e_l1_robust.txt
8a91f9355dbfbdae  21bea1570fb9  audit/data/phase_e_repro_v2.json
40e5d93ef75a37ca  540b5dfacecf  audit/data/phase_e_stats_check.txt
fbbfcc08f24d053d  4dee1a1ad640  audit/data/phase_e_v2_post.txt
2485836af90a95f8  d2c30b16e357  audit/data/phase_f1_expiries.txt
af472c537cb06bd6  b990d8605066  audit/data/phase_f3_pricing.txt
a0c899c3b4dbb4e2  abfd23844bec  audit/data/phase_f4_depth.txt
23bb343cec20c744  19e1fd6ec9e7  audit/data/phase_f6_bar_label.txt
08ee9015cfff97bc  8a8bd6fb1a14  audit/probes/phase_b_replay_funnel.py
ffb01b15d1ae9070  ac46892cb53d  audit/probes/phase_c_null_cycle.py
4975f07c1e4ef47a  da0a23330dfe  audit/probes/phase_c_null_dm.py
b8372bf2b20d5f37  6380598fcab4  audit/probes/phase_d_factor_placebo.py
f0fa3228dcddcc27  7d6d04520004  audit/probes/phase_d_replay_learning_ab.py
17b43fd8a4967a99  5f83b2880212  audit/probes/phase_e_d1_official.py
7043159cef4acdd0  0b5ccafa833e  audit/probes/phase_e_eve_spreads.py
88293b95cdb0e37e  61a38f82b5e0  audit/probes/phase_e_frozen_minutes.py
2f5354129c5d1569  f040a7509cdf  audit/probes/phase_e_l1_robust.py
1ffe1327d0d29e11  b7670174cbc7  audit/probes/phase_e_repro_v2.py
fa561d65e20ae610  9c805c6ac559  audit/probes/phase_e_stats_check.py
a13567e0fb741b0e  4e6f1e1df8aa  audit/probes/phase_e_v2_post.py
64a96f12f2e91bc9  df56b20e1cd3  audit/probes/phase_f1_expiries.py
a3a559f0c0e05d9d  229055ba5328  audit/probes/phase_f3_pricing.py
79e2a17cd88c3abe  9a8c9b5c7d0e  audit/probes/phase_f4_depth.py
afdbe0e1ec130d16  0baa3a67ea20  audit/probes/phase_f6_bar_label.py
24cefe501936ffe2  de0e320bea00  audit/probes/test_phase_a_probes.py
499fbb3b4faab42d  1fbf335e85af  audit/probes/test_phase_b_probes.py
e9c7f068a78786fe  91e43a7c21d8  audit/probes/test_phase_c_probes.py
80f2efc82e8f3b29  f3e01b3c07c5  audit/probes/test_phase_d_probes.py
360190ca32851556  c432685ad34c  audit/probes/test_phase_e_probes.py
16910aa3ce887312  2682a703d08c  audit/probes/test_phase_f_probes.py
d4c2254c5670bcf1  41933f4e0496  audit/probes/test_phase_g_probes.py
```

## Appendix B: Change report template (per approved remediation)

Finding ID(s) · Root cause evidence · Files changed · Revision / PR · Behaviour changed · Safety invariants preserved ·
Tests run · Passed / failed / skipped / not run · Security and risk review · Rollback plan · Acceptance criteria status ·
Independent reviewer · Remaining risks · Next recommended item · Owner approval required
