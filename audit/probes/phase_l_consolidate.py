"""Phase L: build the PROPOSED consolidated findings register A–L as JSON (read-only; nothing here edits a report).

Sources, parsed as they stand (each record keeps its `source`):
  A–G  audit/QUANTDESK_POST_G_CONSOLIDATION.md §3 matrix (severity/status copied from the canonical register)
  H    audit/QUANTDESK_PHASE_H_REGISTER_PROPOSAL.md table + acceptance from QUANTDESK_PHASE_H_RELIABILITY.md
  I-K  the finding sections of QUANTDESK_PHASE_{I,J,K}_*.md
  L    defined below (Phase L), plus owner decisions carried forward from the Phase J/K reviews and Phase L updates

    python audit/probes/phase_l_consolidate.py audit/data/phase_l_consolidated_findings.json
"""
import hashlib
import json
import re
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[1]
REG = A / "QUANTDESK_FINDINGS_REGISTER.md"
ID = re.compile(r"\b([A-L]-\d\d|Q-\d\d|V-[A-Z]?\d+)\b")
EVID = {"PO": "production persisted data", "AR": "replay (archived)", "ST": "synthetic fixture", "CI": "code-only",
        "INF": "inference", "EXT": "external source"}
TAGS = [("prod-render", "production persisted data (rendered)"), ("replay-exact", "exact replay"), ("replay-subst", "substituted replay"),
        ("prod-replay", "replay (archived)"), ("synth", "synthetic fixture"), ("prod", "production persisted data"),
        ("infer", "inference"), ("code", "code-only")]

# ---- stages and readiness gates (the blueprint, §6 of the Phase L report) --------------------------------------------
STAGES = {
    "S0": ("Owner decisions and guardrails", "G1"), "S1": ("Evidence integrity and provenance", "G1"),
    "S2": ("Data-validity layer and contaminated-record rebuild", "G1"), "S3": ("Crash, restart and order-state correctness", "G1"),
    "S4": ("Decision-state propagation and UI truthfulness", "G1"), "S5": ("Observability, alerting and scheduling", "G1"),
    "S6": ("Deterministic end-to-end trade test, then the gate-architecture decision", "G1"),
    "S7": ("Statistical hygiene and learning claims", "G2"), "S8": ("Execution realism and economics", "G3"),
    "S9": ("Live-readiness controls (never authorised by this audit)", "G4")}
GATES = {"G1": "Paper-system correctness and recovery", "G2": "Statistical strategy evidence",
         "G3": "Executable trade economics and fill realism", "G4": "Authorization for any live trading"}
STAGE_OVERRIDE_AG = {  # Phase L judgement where the post-G roadmap gives no item or the auto-mapping misplaces it
    "A-02": "S3", "A-13": "S1", "A-15": "S1", "B-08": "S6", "B-09": "S6", "B-11": "S1", "C-08": "S1", "D-03": "S2",
    "D-07": "S5", "F-03": "S8", "F-07": "S5", "G-03": "S2", "G-04": "S1", "G-05": "S5", "G-06": "S1"}
R_TO_S = {"R0": "S0", "R1": "S1", "R2a": "S2", "R2b": "S2", "R3": "S8", "R4": "S6", "R5": "S6", "R6": "S8", "R7": "S7",
          "R8": "S9", "R9": "S8", "R10": "S4"}
RC = {  # root-cause families: RC1–RC5 from the post-G consolidation; RC5 split and RC6/RC7 added in Phase L
    "RC1": "Authorization chain closed by design mismatch (gate needs a model that cannot exist for the plans built)",
    "RC2": "No data-validity layer: failures become valid-looking data",
    "RC3": "Adoption without nulls: signals and gates adopted on point estimates",
    "RC4": "Unenforced governance and record integrity",
    "RC5a": "Decision outcomes are not propagated to the state the UI reads (fire result discarded; rejections decision-only; decisions never served)",
    "RC5b": "The operator surface's own health is not monitored (publish, deploy, freshness, schedule)",
    "RC6": "Cron-delivered scheduling: GitHub delivers schedule events hours late; backup crons still run the full pipeline",
    "RC7": "Crash/restart state machine incomplete (orders, legs, halts not idempotent or not persisted)"}
FAMILY = {  # Phase L assignment for H–L (A–G keep their post-G family where one is given)
    **{k: "RC7" for k in ("H-01", "H-02", "H-03", "H-06", "H-07", "H-10", "H-12", "H-14")},
    "H-04": "RC5b", "H-05": "RC6", "H-08": "RC2", "H-09": "RC4", "H-11": "RC4", "H-13": "RC2",
    "I-01": "RC2", "I-02": "RC4", "I-03": "RC4", "I-04": "RC4", "I-05": "RC4", "I-06": "RC7", "I-07": "RC5a", "I-08": "RC4",
    "I-09": "RC2", "I-10": "RC6",
    "J-01": "RC2", "J-02": "RC7", "J-03": "RC5a", "J-04": "RC4", "J-05": "RC3", "J-06": "RC3", "J-07": "RC5a", "J-08": "RC5a",
    "J-09": "RC5a", "J-10": "RC2", "J-11": "RC5b",
    "K-01": "RC5a", "K-02": "RC5a", "K-03": "RC5b", "K-04": "RC5b", "K-05": "RC2", "K-06": "RC5b",
    "L-01": "RC5a", "L-02": "RC5a", "L-03": "RC5b", "L-04": "RC5b", "L-05": "RC6", "L-06": "RC3"}
STAGE = {**{k: "S3" for k in ("H-01", "H-02", "H-03", "H-06", "H-07", "H-09", "H-10", "H-12", "H-14", "I-06")},
         "H-04": "S5", "H-05": "S5", "H-08": "S2", "H-11": "S1", "H-13": "S2",
         **{k: "S1" for k in ("I-02", "I-03", "I-04", "I-05", "I-07", "I-08", "I-10")}, "I-01": "S2", "I-09": "S2",
         **{k: "S4" for k in ("J-01", "J-02", "J-03", "J-04", "J-06", "J-07", "J-08", "J-09", "J-10", "J-11",
                              "K-01", "K-02", "K-03", "K-04", "K-06", "L-01", "L-02", "L-03")},
         "J-05": "S7", "K-05": "S8", "L-04": "S0", "L-05": "S5", "L-06": "S7"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tag_classes(text):
    out = []
    for t, name in TAGS:
        if f"[{t}" in text or f"{t}]" in text or f"+ {t}" in text:
            if name not in out:
                out.append(name)
    for pat, name in ((r"\bproduction\b|deployed gh-pages|\bprod_", "production persisted data"),
                      (r"exact replay", "exact replay"), (r"substituted replay|vix_substituted", "substituted replay"),
                      (r"\breplay\b", "replay (archived)"), (r"synthetic|fixture|engine-written", "synthetic fixture"),
                      (r"\brendered\b|Rendered", "rendered (Chromium)"), (r"`[\w/]+\.py:\d", "code-only")):
        if re.search(pat, text) and name not in out and not (name == "replay (archived)" and any("replay" in o for o in out)):
            out.append(name)
    return out or ["see source"]


def strip(s):
    return re.sub(r"\*\*|`", "", s or "").strip()


def a_to_g():
    t = (A / "QUANTDESK_POST_G_CONSOLIDATION.md").read_text()
    rmap = {}
    for line in t.splitlines():
        m = re.match(r"^\| (R\d+[ab]?) \|", line)
        if m:
            cells = line.split("|")
            for x in ID.findall(cells[3]):
                rmap.setdefault(x, m.group(1))
    rc_of = {}
    for line in t.splitlines():
        m = re.match(r"^\| \*\*(RC\d)\*\* \|", line)
        if m:
            for x in ID.findall(line.split("|")[3]):
                rc_of.setdefault(x, m.group(1))
    out = []
    for line in t.splitlines():
        m = re.match(r"^\| ([A-G]-\d\d) \|", line)
        if not m:
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        fid, sev, status, comp, evid, repro, cls, blocks, overlaps, acc = c[:10]
        fam = (re.search(r"RC\d", overlaps) or [None])[0] if re.search(r"RC\d", overlaps) else rc_of.get(fid)
        fam = "RC5a" if fam == "RC5" else fam
        r = rmap.get(fid)
        stage = R_TO_S.get(r) if r else {"RC1": "S6", "RC2": "S2", "RC3": "S7", "RC4": "S1", "RC5a": "S4"}.get(fam) or \
            ("S2" if "P" in blocks else "S7" if "R" in blocks else "S9" if "L" in blocks else "S1")
        stage = STAGE_OVERRIDE_AG.get(fid, stage)
        rep = strip(repro)
        out.append({"id": fid, "phase": fid[0], "title": strip(comp), "severity": strip(sev), "status": strip(status),
                    "evidence_class": [EVID.get(e, e) for e in strip(evid).split()],
                    "evidence_class_method": "post-G matrix codes (PO/AR/ST/CI/INF/EXT); AR does not distinguish exact from substituted replay",
                    "confidence": "high" if rep.startswith("Y") else "medium-high" if rep.startswith("P") else "medium",
                    "uncertainty": {"D": "confirmed defect", "L": "latent: reachable, not yet triggered", "H": "unverified hypothesis",
                                    "G": "evidence/coverage gap"}.get(cls, cls),
                    "root_cause": {"family": fam, "demonstrated": bool(fam), "note": "family per post-G §4" if fam else "not demonstrated"},
                    "related": sorted(set(ID.findall(overlaps)) - {fid}), "blocks": strip(blocks),
                    "risk_if_unresolved": "; ".join({"P": "wrong or unsafe paper trading", "R": "untrustworthy research",
                                                    "A": "unreviewed autonomous change", "L": "blocks live"}[b] for b in strip(blocks).split() if b in "PRAL") or "low",
                    "acceptance": strip(acc), "acceptance_by_evidence_class": None,
                    "regression_test": "flip the finding's existing probe (register / phase reports)",
                    "dependencies": sorted(set(ID.findall(overlaps)) - {fid}), "roadmap_item": r,
                    "earliest_stage": stage, "gate": STAGES[stage][1], "source": "QUANTDESK_POST_G_CONSOLIDATION.md §3"})
    return out


def h():
    t = (A / "QUANTDESK_PHASE_H_REGISTER_PROPOSAL.md").read_text()
    rel = (A / "QUANTDESK_PHASE_H_RELIABILITY.md").read_text()
    out = []
    for line in t.splitlines():
        m = re.match(r"^\| (H-\d\d) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$", line)
        if not m:
            continue
        fid = m.group(1)
        sec = re.search(rf"^### {fid}:.*?(?=^### |\Z)", rel, re.M | re.S)
        acc = re.search(r"^\| Acceptance \| (.*?) \|$", sec.group(0), re.M) if sec else None
        ev = re.search(r"^\| Evidence(?: type)? \| (.*?) \|$", sec.group(0), re.M) if sec else None
        out.append(_rec(fid, strip(m.group(2)), strip(m.group(3)), strip(m.group(4)), sec.group(0) if sec else m.group(4),
                        strip(acc.group(1)) if acc else None, "QUANTDESK_PHASE_H_REGISTER_PROPOSAL.md + H_RELIABILITY.md"))
    return out


def section_findings(p):
    f = next(A.glob(f"QUANTDESK_PHASE_{p}_*.md"))
    t = f.read_text()
    out = []
    for m in re.finditer(rf"^### ({p}-\d\d): (.*)$", t, re.M):
        sec = t[m.end():].split("\n### ")[0].split("\n## ")[0]
        g = lambda k: (re.search(rf"^\| {k} \| (.*?) \|$", sec, re.M) or [None, None])[1]  # noqa: E731
        ev = g("Evidence type") or g("Evidence") or ""
        rc = g("Root cause")
        r = _rec(m.group(1), strip(m.group(2)), strip(g("Severity")), strip(g("Status")), sec,
                 strip(g("Acceptance")), f.name)
        if rc:
            r["root_cause"]["note"] = strip(rc)[:400]
            r["root_cause"]["demonstrated"] = not re.search(r"UNVERIFIED|UNRESOLVED|unknown", rc, re.I)
        out.append(r)
    return out


def _rec(fid, title, sev, status, evtext, acc, src):
    st = STAGE.get(fid, "S4")
    return {"id": fid, "phase": fid[0], "title": title, "severity": sev, "status": status, "evidence_class": tag_classes(evtext),
            "evidence_class_method": "keyword-derived from the finding's section text: review before adoption",
            "confidence": "high" if re.search(r"prod|replay-exact|reproduced", evtext + status, re.I) else "medium",
            "uncertainty": "latent" if "latent" in status.lower() else "observed",
            "root_cause": {"family": FAMILY.get(fid), "demonstrated": FAMILY.get(fid) is not None, "note": "family assigned in Phase L"},
            "related": [], "risk_if_unresolved": None, "acceptance": acc, "acceptance_by_evidence_class": None,
            "regression_test": "flip the finding's existing probe (phase report)", "dependencies": [], "roadmap_item": None,
            "earliest_stage": st, "gate": STAGES[st][1], "source": src}


# ---- Phase L: new proposals ------------------------------------------------------------------------------------------
L_NEW = [
    {"id": "L-01", "title": "An armed trigger's outcome never reaches the screen: `step()` discards `_fire_armed`'s result, model-gate rejections are written to `decisions` only, and the live-tick path rewrites the heartbeat with the stale 'armed:' action and an emptied armed list",
     "severity": "P3", "status": "VERIFIED (exact + substituted replay, every minute; production by path and code)",
     "evidence_class": ["exact replay", "substituted replay", "synthetic fixture (tick emulation)", "production persisted data", "code-only"],
     "confidence": "high (replay, full coverage); production screens not recountable (heartbeat overwritten)",
     "root_cause": {"family": "RC5a", "demonstrated": True, "note": "engine.py:257-258 ignores the return value; :477-482 decision-only by design; tick() :565-574 heartbeat without updating last_action; :1347 per-minute _think overwrites. Demonstrated by instrumented replay"},
     "related": ["K-01", "K-02", "J-07", "J-08", "B-03", "B-06"], "dependencies": [],
     "risk_if_unresolved": "The operator cannot see what the desk did at a trigger; a future approved-but-blocked or sized-to-zero hit is equally invisible",
     "acceptance": "Every armed-trigger hit produces exactly one record of its outcome that the UI shows for >= 1 minute; no heartbeat after a rejection says 'armed' for the rejected level or 'no setup has triggered'",
     "acceptance_by_evidence_class": {"synthetic": "tick-emulated fixture: 0 heartbeats with an 'armed:' action and no armed entry for that symbol",
                                      "replay": "phase_l_consistency over 5 sessions x 2 modes: 0 of N hits unshown (today 60/60 unshown in each mode)",
                                      "production": "5 consecutive sessions: every decision row with context.armed has a matching thought/heartbeat outcome within 60 s"},
     "regression_test": "test_phase_l_probes::test_every_replayed_trigger_rejection_is_hidden_from_the_screen (flips after the fix)",
     "earliest_stage": "S4", "source": "Phase L L1"},
    {"id": "L-02", "title": "A trigger hit while a halt is up leaves no record that the level was reached (`_fire_armed` clears the armed list and returns None at `_blocked`)",
     "severity": "P4", "status": "VERIFIED (synthetic fixture on the exact 10-05 replay); 0 production occurrences observable",
     "evidence_class": ["synthetic fixture", "code-only"], "confidence": "high (deterministic)",
     "root_cause": {"family": "RC5a", "demonstrated": True, "note": "engine.py:465-468"},
     "related": ["L-01", "H-07", "J-03"], "dependencies": ["L-01"],
     "risk_if_unresolved": "Post-incident review can't tell whether a halt cost an entry",
     "acceptance": "A blocked hit writes a decision row with the halt reason",
     "acceptance_by_evidence_class": {"synthetic": "phase_l_blocked_silent: 1 decision row at 10:56 with the halt reason", "replay": "n/a (no halts in replays)", "production": "n/a until a halt coincides with a hit"},
     "regression_test": "test_phase_l_probes::test_halted_trigger_hit_leaves_no_record", "earliest_stage": "S4", "source": "Phase L L1"},
    {"id": "L-03", "title": "The published site shows armed setups after they expire: TTL 2 min, publish cadence 6 min, and the app never checks `expires`",
     "severity": "P3", "status": "VERIFIED (code + config + substituted replay counts; 1 production published snapshot)",
     "evidence_class": ["code-only", "substituted replay", "production persisted data"], "confidence": "high for the mechanism; viewer exposure inferred",
     "root_cause": {"family": "RC5b", "demonstrated": True, "note": "config anticipate.ttl_min 2; run-session.sh PUBLISH_EVERY_MIN 6; app.js renderNow/armedRow ignore expires"},
     "related": ["K-03", "K-04", "J-07", "L-04"], "dependencies": [],
     "risk_if_unresolved": "For about 4 of every 6 minutes after a publish that carries one, a viewer sees an 'Armed · … until HH:MM' already in the past",
     "acceptance": "The app hides or greys armed entries whose expires < now; the publish cadence is >= TTL or the card says 'as of'",
     "acceptance_by_evidence_class": {"synthetic": "render at expires+1 min: no 'Armed ·' headline", "replay": "0 published snapshots with an expired card shown as live",
                                      "production": "gh-pages snapshots over 5 sessions: 0 expired cards rendered as live"},
     "regression_test": "test_phase_l_probes::test_published_armed_card_outlives_its_expiry", "earliest_stage": "S4", "source": "Phase L L1"},
    {"id": "L-04", "title": "The published site returned HTTP 404 at 2026-10-09 18:35Z; GitHub Pages has no deployment after 2026-10-08 10:46Z although gh-pages was pushed on 10-09 and the live run concluded success; nothing alerted",
     "severity": "P2", "status": "OBSERVED (production, GitHub API + HTTP); cause and start time UNRESOLVED",
     "evidence_class": ["production persisted data", "external source"], "confidence": "high for the observation; cause unknown",
     "root_cause": {"family": "RC5b", "demonstrated": False, "note": "Pages settings/deploy state not readable read-only; the Worker proxies the Pages origin and passes the 404 through"},
     "related": ["H-04", "K-03", "K-04", "K-06", "J-11"], "dependencies": [],
     "risk_if_unresolved": "The operator's only window is down with no signal; Phase J/K 'production render' findings describe gh-pages branch content, not necessarily what was served on 10-09",
     "acceptance": "A post-publish check fetches the served data.json, compares its heartbeat ts with the pushed one and alerts on mismatch or non-200",
     "acceptance_by_evidence_class": {"synthetic": "the check fed a 404 / stale body raises an alert", "replay": "n/a",
                                      "production": "5 sessions: every in-session publish verified served within 5 min; 0 unalerted mismatches"},
     "regression_test": "phase_l_pages_latency (deployments per session-day) + an HTTP check (owner-side)", "earliest_stage": "S0", "source": "Phase L L4"},
    {"id": "L-05", "title": "The backup cron for live.yml is still delivered after the close every day and runs the full pipeline: duplicate, mislabelled archive assets ('morning' = full-day bars) and an extra post-close journal save",
     "severity": "P4", "status": "VERIFIED (production, Actions run/job metadata and release assets)",
     "evidence_class": ["production persisted data"], "confidence": "high",
     "root_cause": {"family": "RC6", "demonstrated": True, "note": "live.yml cron '22 3 * * 1-5' kept as backup (3e2b99a); runs created 10:23-10:43Z on 10-05..10-09; journal content unchanged on 10-09 (last event 15:31:04)"},
     "related": ["H-05", "I-10", "H-10", "A-10"], "dependencies": [],
     "risk_if_unresolved": "Archive consumers can double-count bars; a post-close force-push races any later journal writer",
     "acceptance": "A live.yml run that starts after 15:30 IST exits before restoring or saving the journal and uploads nothing",
     "acceptance_by_evidence_class": {"synthetic": "dry-run of live.yml logic at 16:00 IST: no save/upload steps", "replay": "n/a",
                                      "production": "5 sessions: 0 release assets from runs created after 10:00Z"},
     "regression_test": "release asset listing per day (phase_l report §4)", "earliest_stage": "S5", "source": "Phase L L3"},
    {"id": "L-06", "title": "The learning IC table ranks a near-constant regressor: 'vix' is #2 of the app's top 12 (|t| 1.85 at 5 min) on direction variance 0.0002 (mean 0.999), i.e. on the fabricated +1 vote",
     "severity": "P3", "status": "VERIFIED (production memory; repo's ic_table)",
     "evidence_class": ["production persisted data", "code-only"], "confidence": "high",
     "root_cause": {"family": "RC3", "demonstrated": True, "note": "learning.ic_table guards only vx <= 1e-12; no minimum direction variance or effective-n rule"},
     "related": ["J-05", "I-01", "D-01", "J-01"], "dependencies": ["I-01"],
     "risk_if_unresolved": "The UI presents an artefact of invalid data as one of the strongest learned signals",
     "acceptance": "ic_table excludes factors whose direction variance or distinct-value count is below a stated floor, and says so",
     "acceptance_by_evidence_class": {"synthetic": "a constant-direction factor is excluded", "replay": "n/a", "production": "the CLOSE memory's table no longer lists 'vix' until rebuilt"},
     "regression_test": "test_phase_l_probes::test_vix_ic_is_ranked_on_a_near_constant_regressor", "earliest_stage": "S7", "source": "Phase L L2"},
]

# ---- decisions carried forward (owner) and Phase L updates: proposals, never applied to the canonical register -------
DECISIONS = {
    "J-01": {"severity_proposed": "P1", "basis": "owner decision on the Phase J review"},
    "J-02": {"severity_proposed": "P2 (P0 if any live-trading mode is enabled)", "basis": "owner decision on the Phase J review"},
    "J-03": {"severity_proposed": "P2", "basis": "owner decision on the Phase J review"},
    "K-01": {"severity_proposed": "P3", "basis": "owner: reproduced in exact replay"},
    "K-02": {"severity_proposed": "P3", "basis": "owner: substituted replay plus consistent production evidence"},
    "K-03": {"severity_proposed": "P3", "basis": "owner: partially reproduced; Pages latency unmeasured (Phase L: deploy time now measured, CDN still not)"},
    "K-04": {"severity_proposed": "P4", "basis": "owner"}, "K-05": {"severity_proposed": "P3", "basis": "owner: synthetic only"},
    "K-06": {"severity_proposed": "P4", "basis": "owner"},
}
UPDATES = {
    "I-01": "Root cause still UNVERIFIED (no payload). Indicated: zero OHLC only on Kotak-served minutes; the 1 nonzero bar/day carries Yahoo-style float32 artefacts; 10-08: 1 Yahoo poll <-> 1 nonzero bar. The candle path has no >0 guard (ltp() has one). validation.py:40's INDIAVIX exemption is not on the intraday path (ops/checks only): not causal. Learning effect reconciled exactly (L2). Escalation to P1 not triggered: autolearn/research VIX is Yahoo with a >0 guard (plans.py:324).",
    "I-07": "Full coverage: replay 14/41 and production 33/51 EV rows print a P(up) the evaluator did not use; all 51 production EV rows priced an iron fly (direction 0, P(up) 0.5). The app's 'P(up) used' says 'coin flip + prior' in 41/41 replay minutes.",
    "I-10": "Owner correction accepted. Scheduler attribution VERIFIED against run metadata: live.yml cron '22 3 * * 1-5' (08:52 IST); 09-30 run event=schedule created 09:49:30Z (15:19 IST), 10-01 created 10:16:38Z (15:46 IST, 80 s); no dispatch either day; scheduler.yml added 3e2b99a 2026-10-02 09:37Z. Why GitHub delivered late: external, unknowable. Retitle: 'No live session on 10-01 and 10 minutes on 09-30 (late cron); the record has holes'.",
    "J-05": "Clarified per owner: 6 of the 11 'graded sessions' are bootstrap Yahoo replays (09-24 .. 10-01, incl. 10-01). Phase L adds L-06 (IC on a near-constant regressor).",
    "K-01": "Extended: bar replay over 5 sessions: 8 of 60 rejections re-armed at the same level in the same minute; 60/60 outcomes shown nowhere. Shares root cause L-01.",
    "K-02": "Extended: 41 of 60 bar-replay rejections are followed by 'no setup has triggered'; production lower bound 6 of 22 within 5 min (sampled thoughts). Shares root cause L-01.",
    "K-03": "Pages deploy timing measured (382 runs): build+deploy median 27 s, p90 56 s, max 147 s; first in-session deployment 09:19:34-09:19:40 IST on 10-05..10-08. CDN caching and 10-09 (no deployments) unresolved.",
    "Q-05": "Correction proposed: the 10-05 08:31 auto-reset found 0 trades, so the Rs 20k account's trades/thoughts/events were already gone; news rows from 09-29 survive, no DELETE exists in code, the 10-05 run skipped its reset step, and the journal branch is one force-pushed commit. How they disappeared is UNRESOLVED; attributing it to force-push (A-10) is inference.",
    "A-02": "Wording: 9 of 10 catch-up gradings since the reset failed (10-05 09:15 succeeded); still recurring on 10-09.",
    "D-03": "Nuance: post-reset factor increments reconstruct exactly from persisted thoughts + recorded bars (vix: 5/5 session multipliers to 4 dp; PREV memory within 3e-4); only the bootstrap/pre-reset portion is not replayable.",
    "H-05": "Related mechanism confirmed for live.yml (L-05, I-10): cron delivery 6-7 h late is routine on this repo.",
}
DUPLICATES = [
    {"group": "Trigger outcome not shown", "parent": "L-01", "members": ["K-01", "K-02", "J-07", "J-08", "L-02", "B-03"], "relation": "shared root cause RC5a; keep members as UI acceptance tests"},
    {"group": "India VIX zero", "parent": "I-01", "members": ["J-01", "H-08", "I-09", "L-06"], "relation": "same input defect: data (I-01), display (J-01), model chain (H-08/I-09), learning statistic (L-06)"},
    {"group": "EV P(up) text", "parent": "I-07", "members": ["K report 'I-07 in the UI'"], "relation": "same defect, two surfaces"},
    {"group": "Operator surface health", "parent": "H-04", "members": ["L-04", "K-03", "K-04", "K-06", "J-11", "L-03"], "relation": "RC5b; one post-publish verification + status model closes most"},
    {"group": "Cron lateness", "parent": "H-05", "members": ["I-10", "L-05"], "relation": "RC6"},
    {"group": "Restart state", "parent": "H-01", "members": ["H-02", "H-03", "H-07", "I-06", "J-02", "B-04"], "relation": "RC7"},
]


def main(out: Path):
    recs = a_to_g() + h() + section_findings("I") + section_findings("J") + section_findings("K")
    have = {r["id"] for r in recs}
    for r in L_NEW:
        r = dict(r)
        r.setdefault("phase", "L")
        r["evidence_class_method"] = "hand-assigned in Phase L"
        r["gate"] = STAGES[r["earliest_stage"]][1]
        r["uncertainty"] = "observed"
        r["roadmap_item"] = None
        recs.append(r)
    for r in recs:
        if r["id"] in DECISIONS:
            r["owner_decision"] = DECISIONS[r["id"]]
        if r["id"] in UPDATES:
            r["phase_l_update"] = UPDATES[r["id"]]
        r["duplicate_group"] = next((g["group"] for g in DUPLICATES if r["id"] == g["parent"] or r["id"] in g["members"]), None)
        r.setdefault("phase", r["id"][0])
    for r in recs:
        if not r.get("acceptance_by_evidence_class"):
            ev = " ".join(r["evidence_class"]).lower()
            latent = "latent" in (r.get("status") or "").lower() or "latent" in str(r.get("uncertainty"))
            r["acceptance_by_evidence_class"] = {
                "template": True,
                "synthetic": "a deterministic fixture/probe asserting the acceptance above flips from fail to pass",
                "replay": ("re-running the recorded-session replays shows 0 occurrences" if "replay" in ev else
                           "n/a unless the defect is observable in recorded sessions"),
                "production": ("n/a: latent path; must not be provoked in production" if latent else
                               "monitored over >= 5 consecutive production sessions with 0 occurrences, from persisted records")}
    counts = {}
    for r in recs:
        s = re.match(r"P\d", r.get("owner_decision", {}).get("severity_proposed", "") or r["severity"] or "")
        counts[s.group(0) if s else "?"] = counts.get(s.group(0) if s else "?", 0) + 1
    res = {"status": "PROPOSED. Not applied to the canonical register.",
           "canonical_register_sha256": sha(REG),
           "stages": {k: {"name": v[0], "gate": v[1]} for k, v in STAGES.items()}, "gates": GATES, "root_cause_families": RC,
           "duplicate_groups": DUPLICATES, "updates_not_applied": UPDATES, "owner_decisions_carried": DECISIONS,
           "counts": {"findings": len(recs), "by_phase": {p: sum(r["phase"] == p for r in recs) for p in "ABCDEFGHIJKL"},
                      "by_effective_severity": dict(sorted(counts.items())),
                      "with_acceptance_split_hand_written": sum(bool(r.get("acceptance_by_evidence_class")) and not r["acceptance_by_evidence_class"].get("template") for r in recs),
                      "with_acceptance_split_template": sum(bool((r.get("acceptance_by_evidence_class") or {}).get("template")) for r in recs)},
           "acceptance_naming_two_or_more_evidence_classes_before_phase_l": sum(
               sum(bool(re.search(p, r.get("acceptance") or "", re.I)) for p in
                   (r"production|recorded session|\bprod\b", r"replay", r"synthetic|fixture|fault.injection|test|probe")) >= 2
               for r in recs if r["phase"] != "L"),
           "findings": recs}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res["counts"], indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
