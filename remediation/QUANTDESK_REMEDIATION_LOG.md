# Quant-Desk Remediation Log

The running record of post-audit remediation. One item at a time; each item waits for owner approval before work starts.
It sits alongside the forensic audit (PR #9, `audit/`); it does not modify the audit register.

**Live-trading authorization: NOT GRANTED.** Nothing in this file authorizes live trading.

| Field | Value |
|---|---|
| Programme stage | **S0: readiness and containment** |
| S0 status | **NO-GO**: critical blockers open (see §3); engineer routine paused (interim) |
| Last updated | 2026-10-10 04:37 UTC (S0 assessment + remediation PRs #14–#23, session 1; CI green on all PR heads) |
| Repo revision assessed | `main@c96909f1f0f4e77ad30817ca53f2df7b28bb9098` (2026-10-04 13:09 UTC) |
| Audit revision assessed | `claude/exciting-galileo-criwur@813849453aa4` (PR #9, draft, open) |
| Runtime state assessed | `journal@9cdfbeb` (2026-10-09 22:48 IST), `gh-pages@e80b0ed` (2026-10-09 16:14 IST) |
| Next item awaiting approval | **Owner review of PRs #14–#23 (§7)**, and owner actions O-2, O-3, O-4b, O-5 |

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
| 3 | 2026-10-09 | O-4a: H–L artifacts committed | S0 | **done**: the owner approved in the audit session; commit `de344bd` (22:47 UTC), independently verified here (S0-02) | owner, in the audit session |
| 4 | — | Owner actions O-2, O-3, O-4b, O-5 (§6.1) | S0 | **awaiting owner** (O-4b: this session's tag push was refused, 403) | owner only |
| 5 | 2026-10-09 | A-19 fix | S0 | **PR #14** (draft, not merged) | owner approved the scope |
| 6 | 2026-10-09 | Further fixes under the owner's "fix everything" instruction | S0/S2/S5 | **PRs #15–#23** (drafts, none merged); see §7 | owner: "do whatever you want"; merging stays with the owner |

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
| **Status** | **VERIFIED: all A–L evidence now committed** (preservation done; pinning by tag still open, O-4b) |
| **Evidence** | GitHub: PR #9 is open and draft and has not been merged. Its branch `claude/exciting-galileo-criwur@8138494` holds 45 files under `audit/` (10,194 lines). `audit/QUANTDESK_FORENSIC_AUDIT.md` phase tracker: A–G "done", **H, I, J, K, L "not started"**. The register lists **68 findings** (A:19 B:11 C:8 D:8 E:9 F:7 G:6) plus controls V-01…V-38 and questions Q-01…Q-13. A search of `main`, `journal`, `research`, `gh-pages` and the audit branch found no Phase H–L findings. |
| **Conclusion** | The A–G evidence is preserved on a remote branch, and its git blob hashes are pinned in Appendix A. The handoff reports **115 findings across A–L**. That leaves **≈47 findings (H–L) that exist in no repository location this session can see**. Among them: India VIX zero readings, the Pages 404, kill-switch reachability, journal mutation, replay failures, crash/orphan exposure, and the lost/unrecoverable evidence. They are PREVIOUSLY REPORTED only. |
| **Located (VERIFIED NOW, 2026-10-09 ~22:30 UTC)** | The audit session `session_01W3ozoc7W4HkbhbWrrxBk83` ("QuantDesk forensic audit") is idle. Its status reads "Phase L audit artifacts written under audit/, left uncommitted". Its final turn (2026-10-09 18:49:50 UTC) says the H–L artifacts are **untracked files under `audit/`**, kept local on the owner's instruction, and that it will commit and push them to `claude/exciting-galileo-criwur` when the owner says so. Its container was reachable at 22:26–22:28 UTC: file reads were served from it. |
| **Uncertainty** | The H–L files exist **only** in that session's container, which can be reclaimed when idle. They are not hashed anywhere. Also, PR #9 is unmerged, so its branch could be deleted. |
| **Relay attempt** | 2026-10-09 ~22:36 UTC: this session asked the audit session (on owner approval) to push. It **declined**, citing the owner's standing instruction in that session to keep artifacts local, and said only the owner, typing in that session, can lift it. That is the correct control. It reported (**not verified here**): tracked changes 0; register hash `e49341c0…` unchanged; Phase K probes (10) and Phase L probes (21) pass. It also correctly flagged a timestamp error in this session's message ("about 22:40 UTC" vs a 22:36:11 send); the owner's answer came before 22:36:11. |
| **Preserved (VERIFIED NOW, 2026-10-09 ~22:50 UTC)** | Commit `de344bd255f3766b02fb8ce301d9d89740e6fe45` on `claude/exciting-galileo-criwur` (parent `8138494`), "Audit Phases H-L: reports, probes and raw evidence". Checked here independently: **176 files, all added, all under `audit/`, 0 outside**. Per-file manifest sha256 = `feb36b9803a8bd1daa41ed4b615e8320c109c5f5d2ae79b781ac4912c6978f42`, regenerated here and matching the audit session's figure. The canonical register sha256 prefix is still `e49341c0817354b1` (unchanged). `audit/data/phase_l_consolidated_findings.json`: status *"PROPOSED. Not applied to the canonical register."*; **115 findings** = A19 B11 C8 D8 E9 F7 G6 **H14 I10 J11 K6 L6**; by effective severity P1 7, P2 36, P3 55, P4 17. One P2 is marked **"P0 if any live mode is enabled"** (rule shared with H-01), so S0-07 decides its severity. The handoff's "115 findings" is now VERIFIED as a count. The individual H–L findings remain PREVIOUSLY REPORTED until each is re-verified when it is worked. |
| **Key pins (sha256)** | `f76c57c99d4a8d5f1b42c3e6fe0d1c56eaee8a2e8d3bf2e6858d7dd5a64d52e3` audit/QUANTDESK_PHASE_H_RELIABILITY.md · `5202619aa66dcdca83039a46af4cc632ca537c67d7eac7e91b84c69b6a437894` audit/QUANTDESK_PHASE_I_AUDITABILITY.md · `4b50ba726942f711087054e19d9b3998bf4bf32f6dace3c7369dd572a95aa56c` audit/QUANTDESK_PHASE_J_UI_TRUTHFULNESS.md · `c8465ddb080c4668ece170e34e1dbf41122adce7866a4056259c3e56c6bcd379` audit/QUANTDESK_PHASE_K_SESSION_FORENSICS.md · `c94c5b3421962b9d2c1383ea07d35343c1e0fa178fce630f438a7fc27c4cbca2` audit/QUANTDESK_PHASE_L_FINAL_AUDIT.md · `3409c8ace916c162ab4d74f02a09ff8cfb18c94dddcf6b160d6519cff19741b9` audit/QUANTDESK_POST_G_CONSOLIDATION.md · `81b3812dcaf4b8786d6bfbcd8b1f6a80da085dccd93ab40be18cd04de6b4fb23` audit/data/phase_l_consolidated_findings.json · `2fa26b17d047b7e15c3c2f3304f751537f1964fff6047888e6f866cdfc513c60` audit/probes/test_phase_l_probes.py (generated from the manifest; full list in Appendix A2) |
| **Superseded** | ~~Owner, urgent:~~ tell the audit session to commit and push the H–L artifacts to `claude/exciting-galileo-criwur` (as it offered). Then this log records their hashes. Do not delete that branch. Decide whether to merge PR #9 (audit-only) or tag it (e.g. `audit-a-l-2026-10-09`) so the evidence is pinned. |
| **Pass condition** | All 115 findings are committed with hashes, or the owner records which are lost and they are re-derived. The A–G branch is tagged or merged. |

### S0-03: Test baseline (independent re-run)

| | |
|---|---|
| **Status** | **VERIFIED NOW**: baseline reproduced; CI red only by A-19, **fixed in PR #14** (CI on #13 confirmed: 445 passed / 2 failed / 6 skipped) |
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
4. ~~S0-02: H–L audit evidence not preserved~~. **Resolved 2026-10-09 22:47 UTC** (`de344bd`, 115 findings, verified). Only tagging remains (O-4b); PR #9 is still an unmerged draft.
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
- The individual Phase H–L findings: committed and hashed, but not re-verified (PREVIOUSLY REPORTED).
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
| O-4a | Get the H–L artifacts committed by the audit session | **done** 2026-10-09 22:47 UTC (`de344bd`) |
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

## 7. Remediation PRs (2026-10-09/10; all drafts, none merged)

Every PR changes the fewest lines that fix the finding. Each adds a regression test that **fails on `main` and passes
with the fix** (reproduced here before the change), and each carries the identical A-19 commit from #14 so its CI can
go green by itself. Merging is the owner's decision. Engine and risk-gate changes (#22) need an independent
risk-compliance review first.

| PR | Finding | Sev. | What it fixes | Evidence it works | Production behaviour change |
|---|---|---|---|---|---|
| #14 | A-19 | P4 | Test date bomb: `test_chain_from_the_live_book` red on every branch since 10-06 | 2 failures reproduced → pass; negative control (clock after expiry) fails again; `test_kotak.py` 18 passed / 3 skipped | **None**: `KotakOptionChain.now()` returns the same wall clock; a guard test pins that |
| #15 | A-03 | P2 | Unpinned dependencies (root cause of A-02) | All 44 packages pinned to CI's 2026-10-09 install; a fresh install's freeze is **identical** to CI's; `uv pip check` OK | **None** today (same versions); stops silent drift |
| #16 | A-02 | P2 | Catch-up grading crash (`Cannot losslessly convert units`), twice every session since 10-06 | Production error reproduced exactly; `normalise_bars` → `ns` index (lossless, pandas-2 behaviour); regression test | Catch-up grading **runs again**; bar index unit `s` → `ns` (values unchanged) |
| #17 | D-07 | P2 | Self-review filed only ERROR events, so A-02 was never seen | New test fails → passes; `test_selfreview.py` 8 passed; calibrated on the real journal (only the A-02 WARNs qualify) | Self-review files a transient issue for WARN events that say "failed" |
| #18 | G-03 | P3 | LLM prose fallback read "NIFTY 50" as +1.0; out-of-range JSON clipped to max | 2 tests fail → pass; LLM/news/NLP 54 passed | Out-of-range LLM reads are **dropped**, not clipped. **Reverses a deliberate design and changes an existing test: review** |
| #19 | A-07 | P3 | `LockBox.verify` passed when the locked row count changed | Reproduced (`assert []`); `test_autolearn.py` 21 passed; **production lock verified intact** (1,200 rows, `96591d96…`), so the cycle is not halted | Integrity check fails on a real change to the final-test data |
| #20 | G-05 | P3 | LLM read timeouts hidden inside the INFO cost line | Test fails → passes; LLM + self-review 18 passed | Adds a WARN `llm` event on reader failure (daily cap excluded); the cost line is unchanged |
| #21 | A-18 | P4 | A forming 5-minute bar counted as complete after 1 minute | Test fails → passes; intraday + Kotak 37 passed / 3 skipped; merges cleanly with #16 | `history_bars` drops the forming 5-minute bar |
| #22 | F-01 | P2 | When the real chain fails, the desk could open trades on the **model** chain (invented quotes and OI) | Gate allowed entry before the fix (only the time window stopped it) → blocked after; explicit model-chain replays unaffected | **Tightens** entry gating: no *new* entries while a configured real chain is down (exits still managed). **Needs risk-compliance review** |
| #23 | B-10 | P3 | Opening range / IB / session minutes came from the first bar present, not 09:15 | Reproduced (a 10:00 start gave `minutes == 60`); broad run 121 passed / 7 skipped (1 Node skip locally; CI runs it) | Unchanged on a complete day; after a late start, OR/IB are marked unknown, so ORB stands aside. **Strategy-feature change: review** |

**Merge order note.** #21, #22 and #23 each append a test at the end of `tests/test_intraday.py`, so they conflict
pairwise in that one test file (production code merges cleanly). Resolution: keep both tests. Whichever merges first, the
others get `main` merged in. #20 and #22 both touch `engine.py` but merge cleanly; #16 and #21 both touch `feeds.py`
but merge cleanly.

**Verification across the set (VERIFIED NOW).** A local integration branch merging #14 + #15 + #16 (`28d5dcf`, never
pushed) ran the full suite in the real git checkout, CPython 3.11.17, Node available, GitHub tokens stripped:
**449 passed, 0 failed, 6 skipped** (2026-10-09 23:41 → 2026-10-10 00:08 UTC). This is the first fully green run since
2026-10-06. It reconciles with the old baseline: 445 previously passing + the 2 A-19 tests now passing + 1 new A-19
guard + 1 new A-02 test = 449. All 3 Node tests ran and passed. The 6 skips are the sample-dependent ones also skipped
on `main` (`test_handover.py:45` ×3, `test_kotak.py:356/371/388`). Each PR also runs the full suite in CI.

**CI on every PR head (VERIFIED NOW, 2026-10-10 04:37 UTC).** `tests` and `doctor` are **green** on all eleven heads:
#13 `08342da`, #14 `a0f46b4`, #15 `4ad2396`, #16 `2fd7dbe`, #17 `a71fac1`, #18 `dacef65`, #19 `df7ba0e`,
#20 `7dc8efb`, #21 `b91f241`, #22 `b8e6d5e`, #23 `dc2a41e`. The only red check is the Cloudflare `Workers Builds`
preview, which fails at setup on every non-`main` branch (a Cloudflare project setting, not the code; explained on
each PR). The earlier red `tests` on #13 (`7a2dab1`, `150af60`) was the A-19 date bomb; #13 now carries the same
A-19 commit as #14 and is green. None of these PRs is merged.

**Checks done without a PR (VERIFIED NOW).**
- **Data integrity:** `autolearn verify` on a scratch copy of `journal@9cdfbeb` reports "learning ledger, registry and
  journal: intact" (hash chains + SQLite `integrity_check`). The sleeves ledgers (`expiry_seller_v1`, `_v3`): 6 rows
  each, no duplicate (event, id), no open position without a settlement, so the daily post-close re-run (S0-09)
  has not double-written them.
- **Archive duplication (S0-09):** the post-close re-run re-archives the day's bars under a new part name, but
  `data/archive.load_archive` de-duplicates on read by design. That costs storage and runner minutes; the data is
  not corrupted. Removing the re-run (`live.yml` schedule) stays an owner-approved workflow change.
- **Secrets:** a regex scan of the working tree and all fetched history for GitHub, Anthropic, Google, AWS and Slack
  tokens and private keys found **none**; no `.env` or key files are tracked. Caveat: the clone is shallow (50 commits
  plus the fetched branches).
- **Evidence tags (O-4b):** created locally, but the push was **refused by this session's git policy (HTTP 403)**;
  only branch pushes are allowed. The owner must run:
  `git tag -a evidence/audit-a-l-2026-10-09 de344bd -m "audit A-L" && git tag -a evidence/journal-2026-10-09 9cdfbeb -m "journal" && git tag -a evidence/gh-pages-2026-10-09 e80b0ed -m "site" && git push origin --tags`

**Not fixed, and why.**
- D-08 (graded-id truncation, P4 latent): the right fix changes `memory.json`'s schema; the handoff forbids touching
  learning memory without owner sign-off. ~2,100 graded per week against a 5,000 cap: not urgent.
- E-01 (sleeves settle on a frozen index, P1), C-01/B-02 (zero trades is structural), D-01 (factor learning ≈ noise):
  strategy and research decisions, not bugs to patch; they need owner-reviewed studies (S6/S7).
- A-13 (back-dated events), A-10 (force-pushed journal), F-04/F-06 (fills and the live adapter): S1/S3 design work,
  not one-line fixes.

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

## Appendix A2: Phase H–L artifact manifest (commit `de344bd`)

Generated here by `git diff-tree --no-commit-id --name-only -r de344bd | sort | xargs sha256sum` over a `git archive` of that commit. The sha256 of this list is `feb36b9803a8bd1daa41ed4b615e8320c109c5f5d2ae79b781ac4912c6978f42`.

```
85c55e7755499c98a375a609e37a25d8ce1e5704f5fac64a11180462c25c71f7  audit/QUANTDESK_PHASE_H_CLOSEOUT.md
7d036cb441d836ad025233375348857c429a05c8886ebe299b01bd9933ea4104  audit/QUANTDESK_PHASE_H_REGISTER_PROPOSAL.md
f76c57c99d4a8d5f1b42c3e6fe0d1c56eaee8a2e8d3bf2e6858d7dd5a64d52e3  audit/QUANTDESK_PHASE_H_RELIABILITY.md
5202619aa66dcdca83039a46af4cc632ca537c67d7eac7e91b84c69b6a437894  audit/QUANTDESK_PHASE_I_AUDITABILITY.md
4b50ba726942f711087054e19d9b3998bf4bf32f6dace3c7369dd572a95aa56c  audit/QUANTDESK_PHASE_J_UI_TRUTHFULNESS.md
c8465ddb080c4668ece170e34e1dbf41122adce7866a4056259c3e56c6bcd379  audit/QUANTDESK_PHASE_K_SESSION_FORENSICS.md
c94c5b3421962b9d2c1383ea07d35343c1e0fa178fce630f438a7fc27c4cbca2  audit/QUANTDESK_PHASE_L_FINAL_AUDIT.md
3409c8ace916c162ab4d74f02a09ff8cfb18c94dddcf6b160d6519cff19741b9  audit/QUANTDESK_POST_G_CONSOLIDATION.md
21533cc0f2e4b3fb967c884076539c37a3cdc07b0c48a3387bbbe3c89627f87e  audit/data/phase_h_det_tests.json
269d33c5e116e2c890c7d85b3797093428cf588bd86a2b66a14c6e379223e0de  audit/data/phase_i_counterfactual.json
e6c9efe0027a6812f7f77371b3b04ced14773a32310c116760a2895908e7929b  audit/data/phase_i_evidence.json
d3ba73d398731d2695122e9e33749a896cd8427b9f45f536cdca341df099daa3  audit/data/phase_i_news_mutation.json
76bfcc48b07ea037aee9d6450106b60c3d8d693be4ace7b80cf601051a425975  audit/data/phase_i_probe_run.txt
9f46a35b2f260d46f8495fdcd35c5a4d4be2f52bbd85e0bafd9a653816b1fb80  audit/data/phase_i_replay_2026-10-05.json
2df2f3e8c192b1b6316b92d4b3357e37314659e881f38e92d2ca7eef5dee0903  audit/data/phase_i_replay_2026-10-08_vix_substituted.json
2421cb86e48669ff060058a49274ba7a717013fa4e34f37c7a6fe0c39b407977  audit/data/phase_i_snapshot_diff.json
2a55008632573e19415567b8ce79208a7d2dcce61076355ff448f8604d578b49  audit/data/phase_i_snapshot_ident.json
514b340969c0bdf22d57de1d064d73fbb561b62f4badcc67b98f1e61947432b7  audit/data/phase_i_thought_recompute.json
4d15853a2f9d871fc9c94feb0f1f9655ad2577fe3b82b566c80dbb06032239c5  audit/data/phase_i_vix_zero_model_chain.json
0258b604ae079ab10dd0458087b154e4944d4839a1cae1af7e2785a0acb1783d  audit/data/phase_j_probe_run.txt
3c70a6ddfd9d266c8bf43a11c8e4f45d0b5bbc9dc0518dd8c5fd842e79989b36  audit/data/phase_j_screens/deployed_1246_brain.png
765f7c3a42f4706a174992b6bda047233f6480a9c3ab697e68d2c4587d7f965e  audit/data/phase_j_screens/deployed_1246_desk.png
069cef966da8292e02a826b29fca08775b087ae2996c0aeca4a743b8b068f281  audit/data/phase_j_screens/deployed_1246_text.json
86e7c2c8ec3caa2b2556d0cc3a99114ca10354792f3df9a5fb676eff6e2ef805  audit/data/phase_j_screens/focus_deployed_vix_evidence.png
12c3ebeac06c35ce1c238c675bc314f5d369ba79ced9288b2538107d2461e9a1  audit/data/phase_j_screens/focus_fx_8a_account.png
6d910d9125136b04428a2e658bef65c70aaa4140fce71192200da40e38b053ff  audit/data/phase_j_screens/focus_fx_8a_lifecycle.png
30b40423f13adf24f7383fdd0ab12d8c4160bda7b02124d7ab490875b99fceb1  audit/data/phase_j_screens/focus_fx_8a_now.png
2200d10ef5b15d2dd669226d55126231a181272e8c98c5306dab2191d6a6a8e8  audit/data/phase_j_screens/focus_fx_8b_account.png
6d910d9125136b04428a2e658bef65c70aaa4140fce71192200da40e38b053ff  audit/data/phase_j_screens/focus_fx_8b_lifecycle.png
6265d93272d06b3df830e6d0b194fddd905561a555771cfffdef8630d15c644d  audit/data/phase_j_screens/focus_fx_8b_now.png
e09529f60bc3a960fbb92f7e6dc7b6276f9ccbe0882c327e43ad0c8c01a4ae73  audit/data/phase_j_screens/focus_fx_kill_account.png
a85972dd37570ff33419672effcb45d48d8dbd5ce43b88161d0bd39883afe487  audit/data/phase_j_screens/focus_fx_kill_lifecycle.png
6aaec1a2788869503e613319104b9d1d3a4fe94cf6fdd6670760776bb14a79a4  audit/data/phase_j_screens/focus_fx_kill_now.png
d1c7c05842367c17a7975def706ed9bd25d4253f3c43d93e459ddc4ab421d9e8  audit/data/phase_j_screens/focus_fx_safe_account.png
6d910d9125136b04428a2e658bef65c70aaa4140fce71192200da40e38b053ff  audit/data/phase_j_screens/focus_fx_safe_lifecycle.png
381fbdced44008fafa740e4b1c8178056ea9b207ee0466fdd420af7898a08d21  audit/data/phase_j_screens/focus_fx_safe_now.png
3138501db89f365bfa2445831f9a668a164af5e75b35563dfb27fbfd3d707370  audit/data/phase_j_screens/focus_prod_learned.png
a513234e2a053a866a7b4e64584404dbb72774e7c17a575b0c4c46b7d657b2b2  audit/data/phase_j_screens/focus_prod_lifecycle.png
5d0abf93ec4f0911c221e20171bdb428adc9798071b68488aaf769c9e8e1f5c8  audit/data/phase_j_screens/focus_prod_quant.png
95c28f676e518566d05bde89e0a122658e5b9c905ff82040200787331f74c412  audit/data/phase_j_screens/focus_prod_stale_banner.png
6c651963f90d05670ff4bf645c30039a58dba73185b86eb274570acfcd510410  audit/data/phase_j_screens/focus_prod_vix_evidence.png
6daefd234365e833faeb4aae6f94e79ef090f351ac827adc3af2e6d83f788652  audit/data/phase_j_screens/fx_8a_brain.png
17d66242b2f43753941c5a567e5a61f82b3d3463db680b48b052e672d725b360  audit/data/phase_j_screens/fx_8a_chart_chart.png
859d0529c57aa0c832f7f96d24a257598f8d316ecc3c144c98a8c0dc513de794  audit/data/phase_j_screens/fx_8a_chart_text.json
1727cb978adec81a97109ef6fc484d6ae3c65f7f7fdf9bd67f2a316062d68f0d  audit/data/phase_j_screens/fx_8a_desk.png
34c77620ccd60a1e46f6055e1bfe2ad938571026bf9066c65b05b61e92a93b05  audit/data/phase_j_screens/fx_8a_text.json
c0efe966dd5d67460673c42ccc1c16167e852c1629b73360b73fb71154013cbb  audit/data/phase_j_screens/fx_8a_trades.png
6daefd234365e833faeb4aae6f94e79ef090f351ac827adc3af2e6d83f788652  audit/data/phase_j_screens/fx_8b_brain.png
c7e387b5e821f5ca57236b05d702418d847e292496fa17d4762c1863960479db  audit/data/phase_j_screens/fx_8b_desk.png
bdc7a99b8a4d0aa03cad4874f7ed9a7d7caea657f17235e530e4372e845d8bfa  audit/data/phase_j_screens/fx_8b_text.json
db5d63e1bd465db8a332b8d42a1fe17d5b781e8c3428ad2eee85cbd54f145c6c  audit/data/phase_j_screens/fx_8b_trades.png
8c98ef64d919a0287b79e0467494911c7fa2688739ceeb49a639ec296c6adef2  audit/data/phase_j_screens/fx_kill_brain.png
a98230edf789027ee3eb17810c1c26104aafc291b05ce7a3abf8bfc985867eef  audit/data/phase_j_screens/fx_kill_desk.png
5087ef739db4756e420120faacc05dfb8ac2a40d99978e1afab391fe99780b26  audit/data/phase_j_screens/fx_kill_text.json
887575ad6c0e4d116c2507421339eff348f713e5ae39bea52f663c9c826ad6d3  audit/data/phase_j_screens/fx_kill_trades.png
b941c5e2636dabf63725def9a41050a5f5b0bd2883989e398858e607775e0031  audit/data/phase_j_screens/fx_safe_brain.png
26acd7a7ed2cd39c9eecd2eeadd4c4d37af3c4f56e506d6eeaa22c9008c5c434  audit/data/phase_j_screens/fx_safe_desk.png
358055b653689ab27322e8f34f0482229bc648f26c535cc6618af647e81581df  audit/data/phase_j_screens/fx_safe_text.json
4288df0b8b2d5116db4138c4ccf54996fd8581c0919955bda9928db7827490e9  audit/data/phase_j_screens/fx_safe_trades.png
2ddb8d25e37e17be48adf36ef7a9b649f2c58083fae6201cbcdf630e84ce68ac  audit/data/phase_j_screens/prod_1529_brain.png
18a74497be49310b04baf0c0945fff6880d05b5c78330cecaa5c43331ccefdd7  audit/data/phase_j_screens/prod_1529_chart.png
f21ea23f2e8eda2b35ba07456e83a9ebfa65a3c59464498c8dd90005cef3e122  audit/data/phase_j_screens/prod_1529_desk.png
21060e158372fae82adc3188e330cd671f585ff1540a3e44433f103e8692bcd3  audit/data/phase_j_screens/prod_1529_feed-log.png
de18066fc78db1b98003c34b4e52ec4cd1919e6fc0f5a41fb1fc240eea9bb7ef  audit/data/phase_j_screens/prod_1529_feed.png
93e66741ffca22d6a1f6d98c5d6a6cfb1614ed9ea5501b625e89fc6baa54004d  audit/data/phase_j_screens/prod_1529_text.json
bb5331cbb10edac52580687d4bd3e1a193bf4792d83da3e8c999081453c69888  audit/data/phase_j_screens/prod_1529_trades.png
7ecf36fc6fcd80f4bed77dc9ac7e1d9c36b9c9e18fd34615099f5a5886d788fc  audit/data/phase_j_screens/prod_stale_mon1000_desk.png
a87f86bebd29d98f8b9dfc04c5291ce790c1845843d9ef8220bfc8489cead7dd  audit/data/phase_j_screens/prod_stale_mon1000_text.json
0df7f216d5b9d41e74fa6f84fd04a9d554a734d352c46ea60f9007cbb8c80bc9  audit/data/phase_k_probe_run.txt
47bbedf037024c4206a8b1a452154cce9d8d8a265f5f3abe76396d48e1be0ef5  audit/data/phase_k_prod_points.json
3eb217aa536f8028e309990ba54195a78529d3b635d8b7e25bcdf371f15c7a6d  audit/data/phase_k_screens/focus_k1005_03_armed_rejected_now.png
949e35f9e51f1612d26d97994c6ed55fad1608d6420ef5e564252cb64134183c  audit/data/phase_k_screens/focus_k1008_03_armed_trigger_rejected_094430_now.png
8a4fa541898a0be212cf37369eef3646a53e1a5a7dea662afa5502d893fcc570  audit/data/phase_k_screens/focus_k1008_04_ev_rejection_110330_now.png
060c459944bd9e58d5956ac943fe9930a74db094445488444775e02a04a713c1  audit/data/phase_k_screens/focus_prod_close_1544_status.png
95c28f676e518566d05bde89e0a122658e5b9c905ff82040200787331f74c412  audit/data/phase_k_screens/focus_prod_open_1012_0917.png
6cc56ff55f6edcf265430c54eb565bb0490e88efddf036dad68b828b22c92da1  audit/data/phase_k_screens/k1005_01_first_heartbeat_091630_desk.png
263bc6e3f07c02f751b6a566ced95d49eda6485902bc867c23ed03c9d49f92a1  audit/data/phase_k_screens/k1005_01_first_heartbeat_091630_text.json
54e185a6d8699586336ca9c88fc085e883ea49fbf06bd631cf9064ef232faf3e  audit/data/phase_k_screens/k1005_02_first_armed_093030_desk.png
0a238acf0e2cd7f7c2d0f298dd3e4d71fda098a2a6b1f8c4cab6669a1a0d72b4  audit/data/phase_k_screens/k1005_02_first_armed_093030_text.json
c0e8de75aea81bbc6bc88844cbea64385f6df043ac87e6ba002bfdcae48c5b77  audit/data/phase_k_screens/k1005_03_armed_trigger_rejected_105630_desk.png
34e34184faab27bdc37e70fa691188a44932d1f66a9725e0ad44d6e61d5fadff  audit/data/phase_k_screens/k1005_03_armed_trigger_rejected_105630_text.json
e1aa4975506b2ac3e4d75aa4121e4de11207aa3153567cb8d846d4b3022461df  audit/data/phase_k_screens/k1005_05_handover_morning_last_122030_desk.png
b1f59393a76ba3d529e411eb2274cf451a80362c11d3fa4ee2c604c41372f157  audit/data/phase_k_screens/k1005_05_handover_morning_last_122030_text.json
e1aa4975506b2ac3e4d75aa4121e4de11207aa3153567cb8d846d4b3022461df  audit/data/phase_k_screens/k1005_06_handover_afternoon_restored_122120_desk.png
b1f59393a76ba3d529e411eb2274cf451a80362c11d3fa4ee2c604c41372f157  audit/data/phase_k_screens/k1005_06_handover_afternoon_restored_122120_text.json
327bca94c574ab052018ac50259bcfe1bdc19f812ed816efc54826c59f5eec98  audit/data/phase_k_screens/k1005_07_handover_afternoon_first_step_122140_desk.png
1798528570798eff56773c0c52ba9d5955b6a38b35f976eca1b975b39a3bf030  audit/data/phase_k_screens/k1005_07_handover_afternoon_first_step_122140_text.json
de0ca8916415cf78abd9a918f919ad8f8a3422dca8c5dbb3320b62eb151037d7  audit/data/phase_k_screens/k1005_09_after_end_session_153130_desk.png
d93a7a0a33b488dfb86959df9a9f4a3ff0d06e604d763f8eccc20a5d60e703df  audit/data/phase_k_screens/k1005_09_after_end_session_153130_text.json
01309f82fb2d328f7269e034ebce351aca87b7e245081e3b8aa48b998dcf8576  audit/data/phase_k_screens/k1005_09_after_end_session_200000_desk.png
90940462d5ffd5d604ab5408bd09756cc75d01408415d9d52235f23423f7507d  audit/data/phase_k_screens/k1005_09_after_end_session_200000_text.json
e3ce3a5c8bf3d6364479ec993869399dd23eaaa7b1de740f70403bbd264832b8  audit/data/phase_k_screens/k1008_03_armed_trigger_rejected_094430_desk.png
3a1c844efdda485d791359337b20b61c0521218efc8d91814b937f86e3bd4ee5  audit/data/phase_k_screens/k1008_03_armed_trigger_rejected_094430_text.json
ebdceae9c4f24f2d4d19d0ae3b14dba2687772195a0dc6d7a4e116b24fe6d62c  audit/data/phase_k_screens/k1008_04_ev_rejection_110330_desk.png
160d6ef75e4c1d1f68727c348b8e77f631ea6efcebfedabb47592f5c7f3ae2df  audit/data/phase_k_screens/k1008_04_ev_rejection_110330_text.json
94eb47a0ac8cfeb31de575eba94741970bf62ceea1f1543fd6d11a61ff3783c3  audit/data/phase_k_screens/outage_k1005_log.json
9eb7eff5e468c90240d1deee6c02ed838f4383bcfa896ecbdef112daf02f5c8d  audit/data/phase_k_screens/outage_k1005_outage_1_loaded.png
a326d20edd1642f52744729e689b7d05778b159dc3edc7d712d53bde70eb85af  audit/data/phase_k_screens/outage_k1005_outage_2_failing_70s.png
a326d20edd1642f52744729e689b7d05778b159dc3edc7d712d53bde70eb85af  audit/data/phase_k_screens/outage_k1005_outage_3_failing_130s.png
02036d33c1cca9903edc49d13cd6d5364f481d8d977016e6467371c178d48f4b  audit/data/phase_k_screens/outage_k1005_outage_4_recovered.png
9eb7eff5e468c90240d1deee6c02ed838f4383bcfa896ecbdef112daf02f5c8d  audit/data/phase_k_screens/outage_k1005_stuck_1_loaded.png
979130f7de0f1a70dd10a6f2a9f6900c8775bf3d77b59da40ff3486266c953bd  audit/data/phase_k_screens/outage_k1005_stuck_2_16min.png
b171dc5a9ed1c99b605362585aeb3dec6f350afbd6313cac1c10c6a909a2fc9d  audit/data/phase_k_screens/prod_close_1544_desk.png
c604f2bff995897a21c00ed13e30217ffa54bb31c3d0b9f7d4fbb129a364a42d  audit/data/phase_k_screens/prod_close_1544_text.json
c8ee825201c6cf087a1136087677063a4160a1e94dbd9a819aa690b20839c6ef  audit/data/phase_k_screens/prod_open_1012_090500_desk.png
59bce0d7e1594b61a09b0c68bf7553f0b2ca8a7ff91410af9ba37408ee26d223  audit/data/phase_k_screens/prod_open_1012_090500_text.json
0ded9a1de383b2c6a28c0499a633b96a2d7814e5f1ffcb57bad7e815608261ca  audit/data/phase_k_screens/prod_open_1012_091700_desk.png
f9b88c9081dea0c178fc427fb8e288c76d5856c469c9a6fe749385f19a2459e4  audit/data/phase_k_screens/prod_open_1012_091700_text.json
9687b241655e5ca6c6b52310dfd50c813726a254676ef178eedf8c3bad2e068b  audit/data/phase_k_screens/trade_orb_history.png
eb50d5541a592fe11d70c0f412cff6403fa3d50f5a6d7475691bbc5c91205072  audit/data/phase_k_screens/trade_orb_sheet.png
2d6032570cc5dae525a553e698dff451e29a739a85a13c0a072776279759633e  audit/data/phase_k_screens/trade_orb_text.json
c570232d02084dec0dc2ab9d38fafe85e66a6becfe249f3470c150d49a0c11b4  audit/data/phase_k_sessions.json
597ecd16ce807d833410927c94ae9c322bc7f0ef866c667eff502c9a31f45492  audit/data/phase_k_timeline_2026-10-05.json
b1fc7669486e520a9275b70cee7ef94a84939a289cdf4932e703456577ac92c5  audit/data/phase_k_timeline_2026-10-08_vix_substituted.json
01a857503cc562a8f4cd231d6ef298e59e68422f28ebf61c893ad71f8a718ab4  audit/data/phase_k_trade_fixture.json
719a34b660c817cf1a009bd109b998183f09337f3c2fe45d3629b0819d0c5d79  audit/data/phase_l_blocked_silent.json
abbc7f082c81cfedca98952f70e8a2ae64cdf7a9782f4dca83e099ce49ea10e4  audit/data/phase_l_consistency_raw/cons_1005_bar.json.gz
0805470e3f5339611b4d4a658f34e570d3830cb77f7e06eef41229088702c43c  audit/data/phase_l_consistency_raw/cons_1005_tick.json.gz
9280eedbe472ac0d4f91b2e45b8422eab924a090326f7b0f264d654e3bdbbef4  audit/data/phase_l_consistency_raw/cons_1006_bar.json.gz
e9c4707fb91e33fc220900d93d55f00d7053a5ce9025d92f28641128fce741a7  audit/data/phase_l_consistency_raw/cons_1006_tick.json.gz
4e426da9a1b83deb9427baad2dea4b2e78efed7f3b1584f3085872f7a782cb47  audit/data/phase_l_consistency_raw/cons_1007_bar.json.gz
b3ae3026dcfdf9cfbd530d2df11afd8d74cf82a416cc29f95eff12974a279d9f  audit/data/phase_l_consistency_raw/cons_1007_tick.json.gz
1bff3e53176d3b9a320ee5170956c862169f38f7446cd45d00b056bc9f537553  audit/data/phase_l_consistency_raw/cons_1008_bar.json.gz
2f07c99c6225efb81ae4aadf6684b8a89b1341b259083e72afcf313a2c90c980  audit/data/phase_l_consistency_raw/cons_1008_tick.json.gz
da411f24dde92b28889512087905b1d7d33bdc30ca5350b2d0f8f063753beed6  audit/data/phase_l_consistency_raw/cons_1009_bar.json.gz
c76c386d2bcc5b046842b7fd49817b65221f8984fd2e0678e2c709b6fb8c2925  audit/data/phase_l_consistency_raw/cons_1009_tick.json.gz
578a270cd761c1fd0550108a661ab17a0badd734e41d44f5ca9a4b8096ba6d2e  audit/data/phase_l_consistency_summary.json
81b3812dcaf4b8786d6bfbcd8b1f6a80da085dccd93ab40be18cd04de6b4fb23  audit/data/phase_l_consolidated_findings.json
6667e0eb24f44f1b2308f7db5ec7ba4e2ff8e2b0bbff203bafbc9a6f991c69da  audit/data/phase_l_pages_get_20261009T1835Z.txt
dc481e009ca9b945422a2fa0e04f18f2c561d8f1ef44d19f4d4b85fee12a3e15  audit/data/phase_l_pages_latency.json
c84d6b8a283abe33f7fe9d40e7f6552b87cb6db85dddd195a3107b91d8eb36e3  audit/data/phase_l_probe_run.txt
6577e1ce4e65071cdfc99808a14e0f6a25300aea02f60955cdd964626de473aa  audit/data/phase_l_prod_consistency.json
8a5692e70ce7a1b4b0740bb9ec25a6b29d665219006fab28a94947f05f97626c  audit/data/phase_l_published_armed.json
afb25cb9d6fd8560b56212c8546db29ca0336a9149c896c2a099b1521ea0243d  audit/data/phase_l_release_assets.json
6f6dab4c6fd84fdfd658f06ea65d9813092e7cccfc8ddf5f45124a70de37c35f  audit/data/phase_l_scheduler_runs.json
663c8099a057a6de176727f396f6e088db2d49c9de8a57349b7a30cdc652f955  audit/data/phase_l_screens/l1005_tick_rejected_105540_desk.png
684442406eddbdd98b206f3cc653d3a3a0c08069103ddaf6a9b413bbbced99ae  audit/data/phase_l_screens/l1005_tick_rejected_105540_text.json
8be48703c3fbbf89d3c47bfb08d5624a4c0b0d905f1cfc8475de9792000f3346  audit/data/phase_l_series_scan.json
01d16c4cb1a22aeac379c3d511d02f53659c65d1f4d0c15e7b9fbc09149c1856  audit/data/phase_l_ui_port_check.json
6c58884d483d7b7f8a2b6869e63727a27b98c62c642b08866531077088a24cce  audit/data/phase_l_vix_counterfactual_2026-10-05.json
1445ce132c3b3b1fb9bf4fae5c057ef5b8cd4f844b8b93c1c4d3a3e2555620c8  audit/data/phase_l_vix_counterfactual_2026-10-08_subst.json
f04f3591a23a156181762e9d983717c9f73e3cf3a1b83913626421fc41370a56  audit/data/phase_l_vix_ic.json
bd3e00f5f41ac202369a63e3456ef3be87883e98408cd4b9a22bcf6df7766ca4  audit/data/phase_l_vix_learning.json
c9b900456b9e95240e0f63124e1ddd3a7b33cee16b03935e9c973e3f9135abc3  audit/probes/phase_h_det_tests.py
63c091df9f2eaa056714b48c780fbc1bdd55a0f3eb31bd8efb0604c18f545eb1  audit/probes/phase_i_counterfactual.py
1003c32b4f09d3cce46b4a427966bf74bb0401bb4d970d84411b54e2b09e600c  audit/probes/phase_i_evidence.py
c60a1a63849bd21db95bdeedc054e9433413a5771f7b38a7c5639c5e7511ccef  audit/probes/phase_i_news_mutation.py
fd6b295ee63ee7f212809b6200801b1048912db1393e2843a621ae040cbc34c6  audit/probes/phase_i_replay.py
31f533b9caa062ce0abd6a352ddf9f8a65ec4bf22907fa9cfe526f5135229a23  audit/probes/phase_i_snapshot_diff.py
3991c157cba69c0afdfbe5b50fc665b583dd308e9cb44137551e7b2ff47677ab  audit/probes/phase_i_snapshot_ident.py
f6a9bdebce841d4be1bd1cd8a7392e4fec90b6362eae60ed366baf7827f2c6cb  audit/probes/phase_i_thought_recompute.py
e6be8642eab3027fa7b165ed1523c1bc10d8fde9dfbb48ac0d67f93e18081fe1  audit/probes/phase_i_vix_zero_model_chain.py
fae3dcbba3e4d9177357edb636f3ef35de6a4d49c12d80c01902468933f419df  audit/probes/phase_j_focus.py
10203ecc8fc00288039c021ec38ae380050b9d4e136e321ace8f59646682cbf7  audit/probes/phase_j_shoot.py
b5688ad83d6ae61c15c58024478e2f201ec00296c9be028ebdd5b8966c790d26  audit/probes/phase_j_site.py
4f95efe861491414b80925b320a28bad4ca72d811df27edfb1643b895dfc18f6  audit/probes/phase_k_outage.py
f3861ae6fed4bfd08bf767b9bb3aeb967de03947023d511eaf8aae8a9bf539d8  audit/probes/phase_k_prod_points.py
f3b9ee0d8754f1e6025f3c27c293a62277918b891645fe6bddcb7a4baa9f2260  audit/probes/phase_k_sessions.py
3e3889ef25d1a72e6b94b8a2de391257545856f66f193d96c0b8fed94203d152  audit/probes/phase_k_timeline.py
247668e3d62d19eebcdc4a6abba0b05519b85389444f1949810c00b61503310f  audit/probes/phase_k_trade_fixture.py
75e2b849101a0f078d1a242c09c7845d75d690da1d0d94a0f71d78219c0e2774  audit/probes/phase_k_trade_sheet.py
a39b46b1cf32c21ccb97909e5000a999dd1ccd12749b2c401d369879e30432dd  audit/probes/phase_l_blocked_silent.py
741d2a3a25d87e38ac7430d1af8c9b0e525fee678b3d5ab98022b8bb0d8b695f  audit/probes/phase_l_consistency.py
ebd4d21821c146f8a12782a989e65925a70e7e409e50901c654837b6f52e0d27  audit/probes/phase_l_consistency_analyze.py
78899d6b1d3fcdd280fa5432066669e5d328db234c11d28602a58436a6fb10ca  audit/probes/phase_l_consolidate.py
830cbbf2e51c302635559054fd0ab507e6f5214c63639c5ee17cf0306b58af1a  audit/probes/phase_l_pages_latency.py
ac7f83ff6be1951538e88af7180244dccd9d6ac3751a2d1adb9e278a15399a62  audit/probes/phase_l_prod_consistency.py
10ea6f69f3e2afde941cae16b7ab7815a562af6ba98de3ba25dff8c8be6874e9  audit/probes/phase_l_series_scan.py
7844718f7bfd8efe3536e9068fd9b8f9b6c2477c46229984e8dc4d09d69db992  audit/probes/phase_l_ui_port_check.py
b1d91e595714731e4e19c1e3ec2516502f51ab1050c5787b08d5c32ce258618c  audit/probes/phase_l_vix_counterfactual.py
ad623917ac4fc527701899ea77dacb02a3bcd4fe15ed53d96d6f2fc5079381d9  audit/probes/phase_l_vix_learning.py
c87e89fd5fd2ab6d947511fb0eef4713a81ca4e7fd30e73e14c21203f58525cb  audit/probes/test_phase_h_probes.py
e998e9d756400f2c7def45f63c10a05e3b5be793604c5e156ce9fb8b15c7b77c  audit/probes/test_phase_i_probes.py
4218123a80c682a7de6cdbe6a6a1a9397a80e2d52a5a72ed7af1fcbcdc6994eb  audit/probes/test_phase_j_probes.py
fda193a2a89aec0d2493cedebef5c8611565aaa9373afdc9746c128811fcb65d  audit/probes/test_phase_k_probes.py
2fa26b17d047b7e15c3c2f3304f751537f1964fff6047888e6f866cdfc513c60  audit/probes/test_phase_l_probes.py
```

## Appendix B: Change report template (per approved remediation)

Finding ID(s) · Root cause evidence · Files changed · Revision / PR · Behaviour changed · Safety invariants preserved ·
Tests run · Passed / failed / skipped / not run · Security and risk review · Rollback plan · Acceptance criteria status ·
Independent reviewer · Remaining risks · Next recommended item · Owner approval required
