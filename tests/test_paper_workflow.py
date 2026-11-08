"""The paper runner's workflow (.github/workflows/paper-desk.yml): who holds which key, who can write, and what it can never do. PAPER MONEY ONLY: no broker credential anywhere in it."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = (ROOT / ".github" / "workflows" / "paper-desk.yml").read_text(encoding="utf-8")
WF = yaml.safe_load(RAW)
JOBS = WF["jobs"]


def steps(job):
    return JOBS[job]["steps"]


def test_only_the_publish_job_can_write_and_it_holds_no_secret():
    assert WF["permissions"] == {"contents": "read"}                                                  # everything else is read-only
    assert JOBS["publish"]["permissions"] == {"contents": "write"} and "permissions" not in JOBS["morning"] and "permissions" not in JOBS["afternoon"]
    pub = yaml.safe_dump(JOBS["publish"])
    assert "secrets.LIVE" not in pub and "secrets." not in pub.replace("secrets.GITHUB_TOKEN", "") and "github.token" in pub    # the repository token for the branch, nothing else


def test_the_relay_keys_live_in_the_one_step_that_runs_the_runner_in_each_half_and_nowhere_else():
    for job in ("morning", "afternoon"):
        holders = [s for s in steps(job) if "secrets." in yaml.safe_dump(s)]
        assert len(holders) == 1 and holders[0]["run"].find("quantdesk paper run") >= 0, job
        assert set(holders[0]["env"]) == {"LIVE_URL", "LIVE_READ_TOKEN", "LIVE_INGEST_TOKEN"}
    assert RAW.count("secrets.LIVE_READ_TOKEN") == 2 and RAW.count("secrets.LIVE_INGEST_TOKEN") == 2     # a half each; the workflow-level env holds none
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
    assert "paper verify --file \"$f\"" in pick and "--extends \"$m\"" in pick and "the runner saved no account to publish" in pick and "exit 1" in pick      # each file verifies; the longer wins; nothing saved is an error
    check = next(x["run"] for x in steps_ if x.get("name", "").startswith("Check it continues"))
    assert "--extends \"$LEDGER_WORK/account.json\"" in check
    order = [x.get("name", "") for x in steps_]
    assert order.index("Fetch the paper-ledger branch (into its own directory)") < order.index("Check it continues the branch's account") < order.index("Add it to the branch (a new commit; never a force-push)")
    assert next(x for x in steps_ if x.get("name", "").startswith("Fetch the"))["run"] == "deploy/paper_ledger.sh fetch" and next(x for x in steps_ if x.get("name", "").startswith("Add it"))["run"] == "deploy/paper_ledger.sh push"


def test_the_backup_is_off_unless_the_owner_turns_it_on_because_the_repository_is_public():
    gate = "vars.PAPER_LEDGER_BACKUP == 'yes'"
    assert gate in JOBS["publish"]["if"]
    for job in ("morning", "afternoon"):
        up = [x for x in steps(job) if str(x.get("uses", "")).startswith("actions/upload-artifact")]
        assert len(up) == 1 and gate in up[0]["if"], job                                               # nothing is uploaded to a public place by default
    assert "PUBLIC" in RAW and "paper-ledger" in RAW


def test_one_run_at_a_time_two_halves_inside_a_job_limit_and_the_first_account_is_a_declared_act():
    assert WF["concurrency"] == {"group": "paper-desk", "cancel-in-progress": False}                      # two runners on one account would be dangerous
    assert JOBS["afternoon"]["needs"] == "morning" and JOBS["publish"]["needs"] == "afternoon"
    for job in JOBS:
        assert JOBS[job]["timeout-minutes"] <= 359, job                                                   # under GitHub's six hours
    assert JOBS["morning"]["timeout-minutes"] == 355 and JOBS["afternoon"]["timeout-minutes"] == 355     # the afternoon half must be able to run from an early morning crash to the close
    inp = WF[True]["workflow_dispatch"]["inputs"]                                                         # (YAML reads the key `on` as True)
    assert inp["new_account"]["default"] is False and inp["new_account"]["type"] == "boolean"
    assert "--new-account" in "\n".join(s.get("run", "") for s in steps("morning")) and "--new-account" not in "\n".join(s.get("run", "") for s in steps("afternoon"))
    assert "schedule" not in WF[True]                                                                     # started by deploy/scheduler.py or by hand, never by GitHub's own cron


def test_the_ledger_branch_is_restored_read_only_and_a_missing_branch_is_not_an_error():
    cks = [s for s in steps("morning") if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(cks) == 2 and cks[1]["with"]["ref"] == "paper-ledger" and cks[1]["continue-on-error"] is True
