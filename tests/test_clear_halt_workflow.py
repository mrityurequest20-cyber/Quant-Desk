"""The 'Clear a desk halt' dispatch workflow: modelled on restate.yml (same permissions, the journal-admin group, never
live-desk), no `${{ inputs.* }}` inside a script, refuses inside the session window, maps each halt to its CLI command,
and saves nothing when there is nothing to clear. The steps' bash is run for real against a faked `date` / `python`."""
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "clear-halt.yml").read_text(encoding="utf-8"))
RESTATE = yaml.safe_load((ROOT / ".github" / "workflows" / "restate.yml").read_text(encoding="utf-8"))
STEPS = WF["jobs"]["clear"]["steps"]


def _steps(prefix):
    return [s for s in STEPS if s.get("name", "").startswith(prefix)]


def _run(step, tmp_path, env=None, bins=None):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, body in (bins or {}).items():
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    e = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", **(env or {})}
    return subprocess.run(["bash", "-eo", "pipefail", "-c", step["run"]], cwd=tmp_path, env=e, capture_output=True, text=True)


def test_permissions_equal_restates_and_no_broader():
    assert WF["permissions"] == RESTATE["permissions"] == {"contents": "write", "actions": "read"}
    assert "permissions" not in WF["jobs"]["clear"]


def test_it_shares_the_journal_admin_group_and_never_the_live_desks():
    assert WF["concurrency"] == RESTATE["concurrency"] == {"group": "journal-admin", "cancel-in-progress": False}
    assert "concurrency" not in WF["jobs"]["clear"]
    assert "live-desk" not in json.dumps({k: v for k, v in WF.items() if k != "name"})


def test_dispatch_inputs():
    # PyYAML reads the bare key `on` as True
    inputs = (WF.get("on") or WF[True])["workflow_dispatch"]["inputs"]
    assert inputs["halt"]["type"] == "choice" and inputs["halt"]["options"] == ["inherited-position", "drawdown"]
    assert inputs["reason"]["required"] is True
    assert inputs["force"]["type"] == "boolean" and inputs["force"]["default"] is False


def test_no_input_is_interpolated_into_a_script():
    for s in STEPS:
        assert "${{ inputs." not in s.get("run", ""), s["name"]
        assert "${{ github.event.inputs" not in s.get("run", ""), s["name"]
    env = WF["jobs"]["clear"]["env"]                       # inputs reach scripts only as env vars
    assert env["HALT"] == "${{ inputs.halt }}" and env["REASON"] == "${{ inputs.reason }}" and env["FORCE"] == "${{ inputs.force }}"


FAKE_GH = """#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
wf = a[a.index("--workflow") + 1]
if wf in os.environ.get("GH_FAIL", "").split(","):
    sys.exit(1)
print(1 if wf in os.environ.get("GH_BUSY", "").split(",") else 0)
"""


@pytest.mark.parametrize("busy,fail,waits", [
    ("", "", False), ("live.yml", "", True), ("autolearn.yml", "", True), ("learn.yml", "", True),
    ("", "autolearn.yml", True),       # can't read a writer's runs: wait rather than guess
])
def test_it_waits_for_every_journal_writer(tmp_path, busy, fail, waits):
    """Risk review, 17 Oct: the wait looked only at live.yml; autolearn.yml (16:10 IST, up to 75 min, now pruning) and
    learn.yml save the journal too, and a clear that saved over them would make their save fail its lease."""
    step = dict(_steps("Wait for a running desk")[0])
    step["run"] = step["run"].replace("seq 320", "seq 1").replace("sleep 60", "true")   # one look, no sleeping
    r = _run(step, tmp_path, env={"GH_BUSY": busy, "GH_FAIL": fail, "GITHUB_REPOSITORY": "o/r"}, bins={"gh": FAKE_GH})
    assert (r.returncode != 0) is waits, r.stdout + r.stderr


def test_only_the_repository_owner_can_run_it():
    assert WF["jobs"]["clear"]["if"].replace(" ", "") == "github.actor==github.repository_owner"


def test_it_reuses_the_leased_save():
    save = _steps("Save the journal")[0]["run"]
    assert "deploy/journal.sh save" in save and "JOURNAL_ALLOW_SHRINK" not in json.dumps(WF)
    names = [s.get("name", "") for s in STEPS]
    assert names.index("Restore the journal") < names.index("Clear the halt") < names.index("Save the journal")


# ---- the time window -----------------------------------------------------------------------------------------------
FAKE_DATE = """#!/usr/bin/env python3
import datetime, os, sys
print(datetime.datetime.fromisoformat(os.environ["FAKE_NOW"]).strftime(sys.argv[1].lstrip("+")))
"""


@pytest.mark.parametrize("now,refused", [
    ("2026-10-19T07:59", False),     # Monday, a minute before the window (the scheduler wakes the desk from 08:25)
    ("2026-10-19T08:00", True),
    ("2026-10-19T08:30", True),
    ("2026-10-19T12:00", True),
    ("2026-10-23T16:15", True),      # Friday, the last minute
    ("2026-10-23T16:16", False),
    ("2026-10-19T20:00", False),
    ("2026-10-17T12:00", False),     # Saturday, mid-day
    ("2026-10-18T09:30", False),     # Sunday
])
def test_it_refuses_inside_the_session_window_and_changes_nothing(tmp_path, now, refused):
    for step in _steps("Refuse inside the session window"):                 # before the wait and again after it
        r = _run(step, tmp_path, env={"FAKE_NOW": now}, bins={"date": FAKE_DATE})
        assert (r.returncode != 0) is refused, r.stdout + r.stderr
        if refused:
            assert "between sessions" in r.stdout and "nothing changed" in r.stdout
    assert len(_steps("Refuse inside the session window")) == 2
    names = [s.get("name", "") for s in STEPS]
    assert names.index("Refuse inside the session window") < names.index("Wait for a running desk to finish") \
        < names.index("Refuse inside the session window (after the wait)") < names.index("Restore the journal")


# ---- the command mapping -------------------------------------------------------------------------------------------
FAKE_PY = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$ARGS_OUT"
"""


def _clear_args(tmp_path, halt, force, reason="all squared off"):
    out = tmp_path / "args"
    r = _run(_steps("Clear the halt")[0], tmp_path, bins={"python": FAKE_PY},
             env={"HALT": halt, "FORCE": force, "REASON": reason, "GITHUB_ACTOR": "owner", "ARGS_OUT": str(out)})
    assert r.returncode == 0, r.stdout + r.stderr
    return out.read_text().splitlines(), r.stdout


def test_inherited_position_maps_to_clear_halt_and_force_only_when_asked(tmp_path):
    args, _ = _clear_args(tmp_path, "inherited-position", "false")
    assert args == ["-m", "quantdesk", "intraday", "clear-halt", "--reason", "all squared off", "--by", "owner"]
    args, _ = _clear_args(tmp_path, "inherited-position", "true")
    assert args[3:] == ["clear-halt", "--reason", "all squared off", "--by", "owner", "--force"]


def test_drawdown_maps_to_clear_drawdown_halt_and_never_gets_force(tmp_path):
    args, _ = _clear_args(tmp_path, "drawdown", "false")
    assert args == ["-m", "quantdesk", "intraday", "clear-drawdown-halt", "--reason", "all squared off", "--by", "owner"]
    args, out = _clear_args(tmp_path, "drawdown", "true")
    assert "--force" not in args and "ignored" in out


def test_a_reason_with_shell_characters_stays_one_argument(tmp_path):
    reason = 'x"; touch pwned; echo $(id) `id` \'y'
    args, _ = _clear_args(tmp_path, "drawdown", "false", reason=reason)
    assert args[args.index("--reason") + 1] == reason and not (tmp_path / "pwned").exists()


def test_an_unknown_halt_is_refused(tmp_path):
    r = _run(_steps("Clear the halt")[0], tmp_path, bins={"python": FAKE_PY},
             env={"HALT": "other", "FORCE": "false", "REASON": "r", "GITHUB_ACTOR": "o", "ARGS_OUT": str(tmp_path / "a")})
    assert r.returncode != 0


# ---- nothing to clear / halt state ---------------------------------------------------------------------------------
def _journal_with(tmp_path, state):
    db = tmp_path / "runtime" / "intraday" / "journal.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT)")
        for k, v in state.items():
            c.execute("INSERT INTO state VALUES (?,?)", (k, json.dumps(v)))


def _before(tmp_path, halt):
    out = tmp_path / "gh_out"
    out.write_text("")
    r = _run(_steps("Halt state before")[0], tmp_path, env={"HALT": halt, "GITHUB_OUTPUT": str(out), "PATH": os.environ["PATH"]})
    assert r.returncode == 0, r.stderr
    return out.read_text().strip(), r.stdout


def test_no_halt_means_nothing_to_clear_and_no_save(tmp_path):
    _journal_with(tmp_path, {"intraday_halt": None})
    present, out = _before(tmp_path, "inherited-position")
    assert present == "present=false" and "nothing to clear" in out
    # every later journal-touching step is conditional on the halt being present; the summary is not
    for name in ("Clear the halt", "Halt state after", "Save the journal"):
        assert _steps(name)[0]["if"] == "steps.before.outputs.present == 'true'"
    assert "if" not in _steps("Summary")[0]


def test_a_missing_journal_is_nothing_to_clear(tmp_path):
    assert _before(tmp_path, "drawdown")[0] == "present=false"


def test_each_halt_reads_its_own_state_key(tmp_path):
    _journal_with(tmp_path, {"intraday_halt": {"raised_at": "2026-10-16 09:20", "items": [{"detail": "orphan leg X"}]},
                             "intraday_drawdown_halt": None})
    present, out = _before(tmp_path, "inherited-position")
    assert present == "present=true" and "orphan leg X" in out
    assert _before(tmp_path, "drawdown")[0].endswith("present=false")


def test_a_drawdown_halt_is_seen(tmp_path):
    _journal_with(tmp_path, {"intraday_drawdown_halt": {"equity": 90000, "peak": 100000, "drawdown": 0.1}})
    present, out = _before(tmp_path, "drawdown")
    assert present == "present=true" and "90000" in out


def test_the_state_keys_match_the_engine_and_halt_module():
    from quantdesk.intraday.engine import DD_KEY
    from quantdesk.intraday.halt import HALT_KEY
    src = " ".join(s.get("run", "") for s in STEPS)
    assert f'"{HALT_KEY}"' in src and f'"{DD_KEY}"' in src
    assert len(re.findall(r"intraday_halt|intraday_drawdown_halt", src)) >= 4
