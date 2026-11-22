"""The paper runner's workflow (.github/workflows/paper-desk.yml): who holds which key, who can write, and what it can never do. PAPER MONEY ONLY: no broker credential anywhere in it."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = (ROOT / ".github" / "workflows" / "paper-desk.yml").read_text(encoding="utf-8")
WF = yaml.safe_load(RAW)
JOBS = WF["jobs"]
PARTS = ("morning", "afternoon", "evening", "night", "reserve")      # the reserve (audit K-07) takes over when one part ended at its start


def steps(job):
    return JOBS[job]["steps"]


def test_only_the_publish_job_can_write_and_it_holds_no_secret():
    assert WF["permissions"] == {"contents": "read"}                                                  # everything else is read-only
    assert JOBS["publish"]["permissions"] == {"contents": "write"} and all("permissions" not in JOBS[j] for j in PARTS[1:])
    assert JOBS["morning"]["permissions"] == {"contents": "read", "actions": "read"}                  # only to fetch the previous run's encrypted hand-over (audit K-01)
    pub = yaml.safe_dump(JOBS["publish"])
    assert "secrets.LIVE" not in pub and "secrets." not in pub.replace("secrets.GITHUB_TOKEN", "") and "github.token" in pub    # the repository token for the branch, nothing else


def test_the_relay_keys_live_in_the_one_step_that_runs_the_runner_in_each_half_and_nowhere_else():
    for job in PARTS:
        holders = [s for s in steps(job) if "secrets.LIVE" in yaml.safe_dump(s)]
        assert len(holders) == 1 and holders[0]["run"].find("quantdesk paper run") >= 0, job
        assert set(holders[0]["env"]) == {"LIVE_URL", "LIVE_READ_TOKEN", "LIVE_INGEST_TOKEN"}
        others = [s for s in steps(job) if "secrets." in yaml.safe_dump(s) and s is not holders[0]]
        assert len(others) == 2 and all(set(s["env"]) == {"HANDOVER_KEY"} for s in others), job      # the hand-over key (audit K-01), in two steps only
        for s in others:                                                                              # which run openssl alone: no repository code ever sees the key
            assert "openssl enc" in s["run"] and "python" not in s["run"] and "quantdesk" not in s["run"], job
    assert RAW.count("secrets.LIVE_READ_TOKEN") == 5 and RAW.count("secrets.LIVE_INGEST_TOKEN") == 5     # a part each; the workflow-level env holds none
    assert not any("secrets." in str(v) for v in WF["env"].values())


def test_there_is_no_broker_credential_no_order_call_and_no_force_push():
    script = (ROOT / "deploy" / "paper_ledger.sh").read_text(encoding="utf-8")
    assert not re.search(r"KITE_|KOTAK_|ZERODHA|API_SECRET|TOTP|PASSWORD|place_order|/orders", RAW + script, re.I)
    assert not re.search(r"--force|git push[^\n]*\s-f\b|\+refs|--delete|push[^\n]*:paper-ledger|push[^\n]*\+|\bg push\b[^\n]*\s(-f|--force)\b", RAW + script)       # the ledger branch only ever gains commits
    assert len(re.findall(r"\bg push\b", script)) == 1 and "::add-mask::" in script and "http.extraheader" in script        # one push, with a masked one-off header, not a persisted credential


def test_no_job_keeps_the_repository_credential_on_disk():
    for job in JOBS:
        for s in steps(job):
            if str(s.get("uses", "")).startswith("actions/checkout"):
                assert s["with"]["persist-credentials"] is False, job


def test_the_publish_job_verifies_picks_the_longest_and_only_the_two_git_steps_hold_the_token():
    steps_ = steps("publish")
    holders = [x["name"] for x in steps_ if "GH_TOKEN" in yaml.safe_dump(x)]
    assert holders == ["Fetch the paper-ledger branch (into its own directory)", "Add it to the branch (a new commit; never a force-push)"]      # the repository code (verify) never runs with the token
    pick = next(x["run"] for x in steps_ if x.get("name", "").startswith("Take the longest"))
    assert "paper verify --file \"$f\"" in pick and "--extends \"$pick\"" in pick and "the runner saved no account to publish" in pick and "exit 1" in pick      # each file verifies; the longer wins; nothing saved is an error
    assert "for part in morning afternoon evening night reserve" in pick                                       # every part's saved account is considered, in the order they ran
    check = next(x["run"] for x in steps_ if x.get("name", "").startswith("Check it continues"))
    assert "--extends \"$RUNNER_TEMP/ledger-branch/account.json\"" in check
    chk = next(x for x in steps_ if x.get("name", "").startswith("Check it continues"))
    assert "if" not in chk and "continue-on-error" not in chk                                          # the one step that stops a shorter account being pushed can be neither skipped nor ignored
    assert "two different histories" in pick
    order = [x.get("name", "") for x in steps_]
    assert order.index("Fetch the paper-ledger branch (into its own directory)") < order.index("Check it continues the branch's account") < order.index("Add it to the branch (a new commit; never a force-push)")
    assert next(x for x in steps_ if x.get("name", "").startswith("Fetch the"))["run"] == "deploy/paper_ledger.sh fetch" and next(x for x in steps_ if x.get("name", "").startswith("Add it"))["run"] == "deploy/paper_ledger.sh push"


def test_the_backup_is_off_unless_the_owner_turns_it_on_because_the_repository_is_public():
    gate = "vars.PAPER_LEDGER_BACKUP == 'yes'"
    assert gate in JOBS["publish"]["if"]
    for job in PARTS:
        up = [x for x in steps(job) if str(x.get("uses", "")).startswith("actions/upload-artifact")]
        plain = [x for x in up if x["with"]["path"] == "runtime/paper/ledger/account.json"]
        assert len(plain) == 1 and gate in plain[0]["if"], job                                         # nothing plain is uploaded to a public place by default
        enc = [x for x in up if x is not plain[0]]
        assert len(enc) == 1 and enc[0]["with"]["path"] == "handover-out/account.json.enc" and enc[0]["with"]["name"] == f"paper-handover-{job}", job   # the hand-over: ciphertext only
    assert "PUBLIC" in RAW and "paper-ledger" in RAW


def test_one_run_at_a_time_four_parts_inside_a_job_limit_and_the_first_account_is_a_declared_act():
    assert WF["concurrency"] == {"group": "paper-desk", "cancel-in-progress": False}                      # two runners on one account would be dangerous
    assert JOBS["afternoon"]["needs"] == "morning" and JOBS["evening"]["needs"] == "afternoon" and JOBS["night"]["needs"] == "evening" and JOBS["reserve"]["needs"] == "night" and JOBS["publish"]["needs"] == "reserve"
    env, inp = WF["env"], WF[True]["workflow_dispatch"]["inputs"]                                         # 06:00 to midnight (owner, 13 Nov 2026); the afternoon part holds the 15:20 sale and the 15:31 settlement
    assert [inp[k]["default"] for k in ("handover", "handover2", "handover3", "until")] == ["11:50", "17:40", "23:30", "23:59"]
    runner = lambda j: next(x["run"] for x in steps(j) if "quantdesk paper run" in x.get("run", ""))      # noqa: E731
    assert "--until \"$HANDOVER2\"" in runner("afternoon") and "--until \"$HANDOVER3\"" in runner("evening") and "--until \"$UNTIL\"" in runner("night") and "--until \"$UNTIL\"" in runner("reserve")
    assert all(k in env for k in ("HANDOVER", "HANDOVER2", "HANDOVER3", "UNTIL"))
    for job in JOBS:
        assert JOBS[job]["timeout-minutes"] <= 359, job                                                   # under GitHub's six hours
    assert all(JOBS[j]["timeout-minutes"] == 355 for j in PARTS)     # each part must be able to run from an early morning crash to the close
    inp = WF[True]["workflow_dispatch"]["inputs"]                                                         # (YAML reads the key `on` as True)
    assert inp["new_account"]["default"] is False and inp["new_account"]["type"] == "boolean"
    assert "--new-account" in "\n".join(s.get("run", "") for s in steps("morning")) and all("--new-account" not in "\n".join(s.get("run", "") for s in steps(j)) for j in PARTS[1:])
    assert "schedule" not in WF[True]                                                                     # started by deploy/scheduler.py or by hand, never by GitHub's own cron


def test_the_ledger_branch_is_restored_read_only_and_a_missing_branch_is_not_an_error():
    cks = [s for s in steps("morning") if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(cks) == 2 and cks[1]["with"]["ref"] == "paper-ledger" and cks[1]["continue-on-error"] is True


def test_no_workflow_uses_a_context_where_github_does_not_allow_it():
    """actionlint's finding on this workflow: `runner` (and `steps`, `job`) are not available in a workflow's or a job's `env`, `if` of a job, `concurrency` or `strategy`; GitHub rejects such a file at
    dispatch, which no other check here would notice. The step-level `env` is the place for them."""
    bad = []
    for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        wf = yaml.safe_load(f.read_text(encoding="utf-8"))
        scopes = [("workflow env", wf.get("env") or {}), ("concurrency", wf.get("concurrency") or {})]
        for name, job in (wf.get("jobs") or {}).items():
            scopes += [(f"{name} env", job.get("env") or {}), (f"{name} concurrency", job.get("concurrency") or {}), (f"{name} strategy", job.get("strategy") or {}), (f"{name} if", {"if": job.get("if", "")})]
        for where, d in scopes:
            for k, v in d.items():
                if re.search(r"\b(runner|steps|job)\.", str(v)):
                    bad.append((f.name, where, k))
    assert bad == []


# ---- audit K-01: each part's own account reaches the next part, encrypted -------------------------------------------------------------------------
def _named(job, start):
    return next(x for x in steps(job) if x.get("name", "").startswith(start))


def test_every_part_hands_its_own_account_on_encrypted_and_starts_from_the_longest_verified_copy():
    for i, job in enumerate(PARTS):
        names = [x.get("name", "") for x in steps(job)]
        run_i = next(k for k, x in enumerate(steps(job)) if "quantdesk paper run" in x.get("run", ""))
        dec, pick = _named(job, "Decrypt the hand-overs"), _named(job, "Start from the longest verified copy")
        enc, keep = _named(job, "Hand this part's own account"), _named(job, "Keep the encrypted hand-over")
        assert names.index(dec["name"]) < names.index(pick["name"]) < run_i < names.index(enc["name"]) < names.index(keep["name"]), job
        assert "paper pick --out runtime/paper/ledger/account.json $files" in pick["run"] and "ledger/account.json" in pick["run"] and "env" not in pick, job
        assert "openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt" in enc["run"] and "-in runtime/paper/ledger/account.json -out handover-out/account.json.enc" in enc["run"]
        assert "openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000" in dec["run"] and "for d in handover-prev handover" in dec["run"]
        assert enc["if"] == "${{ always() }}" and keep["if"] == "${{ always() }}", job                     # a part that fails or is cancelled still hands over what it holds
        assert keep["with"]["retention-days"] <= 3, job                                                    # long enough for the next morning, no longer
        for s_ in (enc, dec):
            assert s_["env"]["HANDOVER_KEY"] == "${{ secrets.PAPER_HANDOVER_KEY || secrets.MARKET_TAPE_KEY }}" and '-lt 32' in s_["run"], job
        if i == 0:
            prev = _named(job, "Fetch the previous run's hand-overs")
            assert prev["continue-on-error"] is True and set(prev["env"]) == {"GH_TOKEN"} and prev["env"]["GH_TOKEN"] == "${{ github.token }}"
            assert "gh run download" in prev["run"] and "--pattern 'paper-handover-*'" in prev["run"] and "python" not in prev["run"]
        else:
            got = next(x for x in steps(job) if str(x.get("uses", "")).startswith("actions/download-artifact"))
            assert got["with"]["pattern"] == "paper-handover-*" and got["continue-on-error"] is True, job
    assert "cp ledger/account.json runtime/paper/ledger/account.json" not in RAW                          # the branch's copy alone is never the only local candidate again
    assert not any("handover" in str(x.get("with", {}).get("path", "")) and x["with"]["path"].endswith(".json") for j in PARTS for x in steps(j)
                   if str(x.get("uses", "")).startswith("actions/upload-artifact"))                      # never a plain account in a hand-over
