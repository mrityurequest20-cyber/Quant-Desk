# QuantDesk: AI / LLM Audit (Phase G)

Read-only forensic audit, Phase G of the master protocol. Findings use the register's format and IDs
(`QUANTDESK_FINDINGS_REGISTER.md`).

**Status: Phase G complete, awaiting review.**
- No model was called.
- The autonomous engineer's session was **read only** (`get_session`, `list_events`), never messaged or steered.
- No production code, configuration, routine or state was changed.

---

## G0. Objective, scope, baseline

**Objective (master protocol):**
- For every AI component, trace INPUT → PROMPT → CONTEXT → OUTPUT → PARSER → DECISION → PERSISTENCE → FUTURE USE.
- Classify what it does: explains / summarizes / proposes / filters / votes / learns / changes parameters / promotes
  strategies / changes risk / changes execution.
- Audit hallucination handling, timeouts, provider fallback, stale responses, malformed outputs, prompt/version
  tracking, reproducibility, cost, latency, failure behaviour and authority boundaries.
- The bar: "AI must not silently become uncontrolled trading authority."

### Baseline

| Item | Value |
|---|---|
| Start commit | `df2e6f1`, clean tree |
| Evidence | journal snapshot `ecd03156` (news table, events, `memory.json`); GitHub (branches, PRs, issues); the account's routine list; the engineer session's metadata and last events (read-only) |

**Evidence tags:** [prod] production record · [synth] synthetic · [code] code reading · [infer] inference.

### AI components found

| # | Component | Where | Runs in production? |
|---|---|---|---|
| A | **LLM news readers** (Claude, Gemini, Ollama) | `intraday/llm.py`, `intraday/news.py`, `intraday/learning.py` | **Gemini and Ollama: yes** (759 reads, 10-05 … 10-08). **Claude: no** (no key) |
| B | **After-close reflection** (Claude) | `llm.ClaudeReader.reflect`, `engine._reflect` | **No** (Claude absent; 0 lessons) |
| C | **Autonomous desk engineer**: a claude.ai routine plus a persistent Claude Code session (Opus 5.5, high effort, permission mode `auto`) | `docs/AUTONOMY.md`, `.claude/settings.json`, routine "Quant-Desk engineer shift" | **Yes** (fires Mon–Sat 17:40 IST) |
| D | **Department agents** (architect, chief-of-staff, data-steward, internal-auditor, orders-desk, research-reviewer, risk-compliance) | `.claude/agents/*.md` | As sub-agents of C |
| E | Rule-based NLP (`nlp.py`) | — | Yes. **Not AI**: deterministic rules (the "rules" reader); included as the baseline the LLMs are weighed against |
| — | `ai-check.yml` | lists which keys exist and models respond | Manual; not a decision path |

No workflow runs Claude Code. `selfreview.yml` and `org.yml` only file GitHub issues, which component C works through.

---

## G1. LLM news readers: the full trace

| Stage | What happens | Evidence |
|---|---|---|
| **INPUT** | Headlines from the news desk, new and within the 120-minute window, about NIFTY/BANKNIFTY with relevance ≥ 2, recaps excluded. Batches of 12, at most 40 calls per provider per day. | `news.py:369-370`, `llm.py LLMDesk.submit` |
| **PROMPT** | `READ_SYSTEM`: −1…+1 effect on each index over 30–60 minutes, with a confidence, an event class and a ≤ 20-word reason. Claude: JSON schema, effort "low". Gemini: JSON mime, temperature 0.2. Ollama: schema format, temperature 0.2. | `llm.py:40-79` |
| **CONTEXT** | Only "id \| published IST \| source \| title — summary". No prices, positions or account. | `_payload` |
| **OUTPUT → PARSER** | `_parse_reads`: JSON, else a `{…}` slice, else **regex over prose** (`_parse_text_reads`). Unknown ids are dropped, numbers clipped to ±1 and [0, 1], an unknown event becomes "general". | `llm.py:113-160` |
| **DECISION** | `NewsDesk.item_tone`: the rules' sentiment plus each non-advisory reader's value, weighted by `reader_trust × max(0.2, confidence)`. **Only once the read has arrived (`at ≤ now`).** Ollama is advisory-only (never weighed). Tone feeds `NewsDesk.state` → the analyst's **"news" evidence (weight 0.5)** → the score. | `news.py:386-401, 418-453`; `analyst.py:210` |
| **PERSISTENCE** | `journal.news_set_nlp`: `{NIFTY, BANKNIFTY, confidence, event, why, at}` per reader in `news.nlp`. **No model id, no prompt version, no raw response** (`last_raw` lives in memory only). Usage and errors: one INFO event per day. | `engine.py:394-395, 662` |
| **FUTURE USE** | `learning.grade_news` grades each reader against the next 30 minutes. `news_reader` statistics set `reader_trust` (same 0.5–1.5× rule as factors). | `learning.py:140-175` |

### Authority: what it can and cannot do

| | Readers (A) |
|---|---|
| Explains | Yes ("why", shown in the app) |
| Summarizes | No |
| Proposes | No |
| Filters | No (the breaking-news veto uses the rules' impact, not an LLM) |
| **Votes** | **Yes**: into the news tone → the analyst score (Gemini and Claude; not Ollama) |
| **Learns** | **Yes**: per-reader trust from grading |
| Changes parameters | No |
| Promotes strategies | No |
| Changes risk | No (no path into `risk`, `playbook`, `quant`, `sim` or `sleeves`: probe) |
| Changes execution | No |

**The score itself reaches a trade only through the iron fly's |score| ≤ 0.3 test and the EV P(up) prior (B-01).
Today that path is closed (B-02, C-05).** So the LLM's effect on a trade is currently nil, and structurally small.

### Production record [prod]

| | Gemini | Ollama (advisory) | Claude |
|---|---|---|---|
| Reads 10-05 … 10-08 | 382 | 377 | 0 (no key) |
| Read lag after publish: median / 90th pct / max | 25 / 93 / 120 min | 29 / 98 / 121 min | — |
| Reads at ±1 or with an empty "why" (the prose-parse signature) | 0 | 0 | — |
| Graded record (`memory.json`) | n 90, hits 53.6 → shrunk 0.578 → **trust ×1.16** | n 95, hits 50.1 | — |
| Daily calls | 8–32 | 9–28 | — |
| Timeouts | 10-05, 10-08 (45 s) | 10-07, 10-08 (90 s) | — |

The rules reader stands at 118.0 / 215 → trust ×1.09.

### Failure behaviour [code + prod]

| Failure | Behaviour | Verdict |
|---|---|---|
| Timeout or HTTP error | Caught per reader; recorded in `errors`; the batch is lost for that reader; trading continues. Claude: 60 s, 2 retries. Gemini: 45 s, up to 7 models × 2 tries. Ollama: 90 s. | Fails safe. **But reported only at INFO** inside the daily cost line, so self-review (ERROR-only, D-07) never sees it (G-05). |
| Provider down | That reader is absent; tone falls back to the rules | Safe |
| Model retired or busy (Gemini) | **Silently walks a 7-model fallback chain.** Claude uses server-side fallback. **The model that answered is not recorded.** | G-04 |
| Malformed output | **Prose fallback:** "The NIFTY 50 may slip" → NIFTY **+1.0**; "NIFTY at 22,500 … mildly bearish" → **+1.0 / +1.0**, confidence 0.5 invented. **Out-of-range JSON** (7, −3, confidence 2) is clipped and **accepted**, not rejected. | G-03 (latent: 0 occurrences in production; JSON modes on) |
| Hallucination | No grounding check. Mitigations: values bounded to ±1; the tone is a weighted mean with the rules; trust learned from outcomes. No check that "why" matches the headline. | Partial |
| Stale response | Reads count only from arrival (`at`); a story leaves the tone after its window. No maximum read age, but the window bounds it. | Safe (V-34) |
| Daily cap reached | That reader stops for the day; recorded in `errors` | Safe |
| Keys | From the environment only; `key_for` reports the variable's name, never the value | Safe (V-37) |

### Reproducibility and versioning

- Not reproducible: no stored model id, prompt hash, raw text, seed or deterministic decoding (temperature 0.2).
- The reader name ("gemini") spans alias drift (`gemini-flash-latest` "tracks Google's current Flash") and the
  fallback chain.
- The learned trust therefore mixes models (G-04).

### Cost

- Tokens are counted per reader. Prices are configured only for Claude, so Gemini and Ollama costs are never priced.
- Volumes are small: ≤ 32 calls a day, ≤ 23k input tokens.

---

## G2. After-close reflection [code + prod]

| Stage | Detail |
|---|---|
| Input | The session review (≤ 24k characters) plus the learning summary |
| Prompt | `REFLECT_SYSTEM` |
| Output | `REFLECT_SCHEMA` JSON: ≤ 5 lessons, ≤ 3 things to watch |
| Parser | Strict JSON. Anything else gives no reflection. |
| Persistence | Appended to the review and to `memory.d["lessons"]` |
| Future use | **None in code.** `memory.d["lessons"]` is written once and never read (probe). The docstring is accurate: "They never touch orders, sizing or risk." |
| Production | **Never ran** (no Claude key; `lessons: []`) |

**Classification:** explains / summarizes only. Display-only, and the code agrees with its claim.

---

## G3. The autonomous desk engineer (component C), the real AI authority

### What it is [prod]

- A claude.ai routine, **"Quant-Desk engineer shift"**: enabled, `CRON_TZ=Asia/Kolkata 40 17 * * 1-6`, created
  2026-10-04, persistent session `session_0195MhBsgNBjQrBNf6ic15ja`.
- Opus 5.5, `permission_mode: auto`.
- Its tools include `Bash`, `Write`, `Edit`, `Agent`, `WebFetch`, and **`create_trigger` / `update_trigger` /
  `delete_trigger` / `fire_trigger`**: it can create and change its own schedule.
- The prompt: "Every judgement call is yours: decide … nothing waits for the owner."

### What AUTONOMY.md authorises it to do [code]

- Fix bugs; data plumbing; new fetchers.
- **Write new pre-registered specs, run studies, record results, move principles on the evidence ladder, add forward
  paper sleeves.**
- **Apply paper sizing** from a registered allocator spec.
- **Merge its own branches into `main` and push.** "The owner is not in the loop."

### What restrains it

| Limit | Enforced by | Verdict |
|---|---|---|
| No real money | **Technically:** no workflow carries trading credentials. Kotak is a **consumer key only** ("no login, no orders, no static IP"; SEBI's static-IP rule covers order APIs). Kite needs secrets that exist nowhere, plus `account.mode: live` plus `--live`. | **Enforced** (V-38) |
| No looser risk | Prose only. Risk tests read the limits from config (`cfg.get("intraday.risk.daily_loss_limit")`), so loosening the config passes them. | **Not enforced** |
| No rewriting the record | Partly. `test_every_recorded_result_matches_its_spec_as_registered` fails if a spec **with a result** changes. Specs **without** results (`expiry_seller_v1`, `v3`, `expiry_eve_entry_v1`) are unguarded, and deleting a result with its spec edit would pass. | **Partial** |
| No red pushes | Prose. `main` is **unprotected**, with no required checks. | **Not enforced** |
| Review gates (CLEAR from `risk-compliance`; `internal-auditor` for probation departments) | Other Claude agents of the same model, invoked by the engineer itself. No human or independent reviewer. **No CLEAR or VETO record exists** in the repo or on issues. | **Not independent** |
| Human review | None by design: **0 pull requests** in the repo's history apart from this audit's; **112 of 114 commits on `main` authored by Claude** (1 owner, 1 Codex), pushed directly. No CODEOWNERS. | **Absent** |

### What it actually does [prod]

- **No commit to `main` since 2026-10-04.** The scorecard's 20 events are all from 10-04; there are no `engineer/*`
  branches on the remote.
- **The department audits are not being worked:** issues #6 (Orders, labelled overdue), #7 (Research) and #8 (Risk)
  are open with no answer.
- The session's current state (10-09 12:39 UTC) is **blocked, "need_input"**. The owner rejected a tool call at
  12:21 UTC, so the engineer stopped and asked "resume or discard?" about an uncommitted fix for the A-19 date bomb
  on `engineer/11-frozen-clock-kotak-test`.
- So the documented "it decides; it does not ask" loop is, in practice, **owner-gated and dormant** (G-02).
- The scorecard also shows the owner finding most defects: **8 `owner_found` vs 2 `self_found`**.
- Cost of that session so far: ≈ $7.80 (session metadata). Not tracked in the repository.

### Authority classification of the engineer (C)

| Capability | Has it? | Controlled by |
|---|---|---|
| Explains, summarizes | yes | — |
| Proposes | yes | — |
| **Changes parameters** (config, thresholds, gates) | **yes** | nothing technical |
| **Promotes strategies** (principles ladder, new sleeves) | **yes** | specs it writes itself; tests check hash consistency only |
| **Changes risk** (paper sizing via allocator spec; config limits) | **yes** (paper) | prose |
| **Changes execution** (engine, playbook, fills) | **yes** (paper) | prose |
| Places real orders | **no** | credentials absent (V-38) |
| Reschedules itself | **yes** | nothing |

**Against the protocol's bar.** The engineer is not *silent*: every change is a visible commit. It is, however, an
**uncontrolled authority** over the paper desk, its risk configuration and its research record. Today the only
reviewer is the same model, and the only effective brake has been the owner interrupting it (G-01).

---

## Findings (proposed for the register)

| ID | Title | Sev | Status |
|---|---|---|---|
| G-01 | The autonomous Claude engineer has unreviewed write authority over `main`: engine, risk config, specs, principles, sleeves, its own schedule. The hard limits (except real money) are prose; the reviewers are the same model; `main` is unprotected. | P1 | VERIFIED |
| G-02 | The documented autonomy is not what runs: nothing shipped since 10-04, audit issues unanswered (#6 overdue), the engineer blocked on owner input; the owner finds most defects (8 vs 2) | P2 | CONTRADICTED |
| G-03 | Malformed LLM output becomes a confident read: the prose fallback reads "NIFTY 50" as +1.0; out-of-range JSON is clipped and accepted | P3 | VERIFIED (latent) |
| G-04 | No model or prompt provenance: reads carry no model id or prompt version; Gemini's 7-model fallback and alias, and Claude's server-side fallback, all accrue to one reader's trust; not reproducible | P3 | VERIFIED |
| G-05 | LLM failures are reported only at INFO (invisible to self-review), and Gemini is up-weighted ×1.16 on a statistically untested record | P3 | VERIFIED |
| G-06 | Claude reader and reflection never ran in production (no key); Gemini and Ollama costs unpriced; the engineer's spend untracked in the repo | P4 | VERIFIED |

**Controls:**
- V-34: reads count from arrival.
- V-35: advisory-only enforced.
- V-36: no LLM path to orders, sizing, risk or execution; reflection is write-only.
- V-37: keys never printed.
- V-38: real money technically out of reach.

**New question:** Q-13, whether the owner intends the engineer to merge unreviewed. The autonomy design says yes; the
owner's 10-09 interruption suggests otherwise.

## Proven / suggestive / untested

**Proven:**
- The full reader trace.
- The parser behaviour (synthetic).
- The advisory-only and arrival gating (synthetic, on the production `NewsDesk`).
- The production read volumes, lags, errors and trust (journal).
- The engineer's authority and its gaps (docs, GitHub state, routine and session metadata).
- The dormancy (no commits since 10-04, open issues, the blocked session).

**Suggestive:**
- That the owner's 10-09 rejection was a deliberate brake rather than an incidental one. The transcript records the
  rejection, not the intent.

**Untested:**
- Live model behaviour on adversarial headlines (no model was called; the audit is read-only).
- Claude's reader and reflection (never ran).
- What the department agents would actually rule (none produced a record).

## Coverage matrix

| Protocol item | Covered in | Status |
|---|---|---|
| Trace INPUT → … → FUTURE USE for every AI component | G1 (readers), G2 (reflection), G3 (engineer, agents) | Covered |
| Explains / summarizes / proposes / filters / votes / learns / changes parameters / promotes / changes risk / changes execution | the authority tables in G1 and G3 | Covered |
| Hallucination handling | G1 failure table | Covered: bounded, no grounding (G-03) |
| Timeout behaviour | G1 | Covered (G-05) |
| Provider fallback | G1 | Covered (G-04) |
| Stale responses | G1 | Covered (V-34) |
| Malformed outputs | G1 | Covered (G-03) |
| Prompt / version tracking | G1 | Covered (G-04) |
| Reproducibility | G1 | Covered (G-04) |
| Cost | G1, G3 | Covered (G-06) |
| Latency | G1 production record (read lag) | Covered |
| Failure behaviour | G1 | Covered |
| Authority boundaries | G1, G2, G3 | Covered (G-01, V-36, V-38) |
| "AI must not silently become uncontrolled trading authority" | G3 | Not silent; **uncontrolled over the paper desk and the research record** (G-01) |

## Remediation (not implemented: awaiting review)

| Priority | Fix | Addresses |
|---|---|---|
| 1 | Protect `main`: require a pull request, green CI and a **human** approval (or CODEOWNERS on `quantdesk/intraday/{engine,risk,playbook,sim}.py`, `config/`, `docs/prereg/`, `docs/principles.json`, `.github/workflows/`). Keep the engineer's autonomy on branches and PRs. | G-01 |
| 2 | Turn the prose limits into tests: pin risk-limit ceilings (a test that fails if `intraday.risk.*` loosens); guard every registered spec file (hash list committed at registration), with or without a result; forbid result deletion | G-01 |
| 3 | Reconcile AUTONOMY.md with how the owner actually wants to run it (Q-13): either an approval step, or let the engineer finish without asking. Make the routine report each shift's outcome as an issue comment. | G-02 |
| 4 | Drop the prose fallback (or require both numbers within [−1, 1] and an explicit label); reject, don't clip, out-of-range JSON | G-03 |
| 5 | Persist the model that answered, a prompt hash and the raw response per read; key the learned trust by (reader, model) | G-04 |
| 6 | Log LLM timeouts and errors at WARN, and teach self-review to count them; give reader trust the same placebo or confidence-interval treatment D-01 calls for | G-05 |
| 7 | Price every provider in config; record the engineer's spend per shift | G-06 |
