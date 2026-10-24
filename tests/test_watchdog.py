"""The watchdog (deploy/cloudflare/watchdog.js): what it checks, when, and how it alerts.

The JavaScript runs under Node with a fake `fetch`, so every scenario is a real run of the shipped code against canned GitHub,
site and ntfy answers. The checks that need no Node (the holiday copy, the cron schedule, the alert workflow) run anywhere."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_cloudflare import _config, stage_worker

ROOT = Path(__file__).resolve().parents[1]
NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
TOPIC = "desk-alerts-7f3a9c2e41"
TOKEN = "github_pat_" + "q" * 82


def _node(tmp_path, script: str):
    stage_worker(tmp_path)
    (tmp_path / "run.mjs").write_text(script, encoding="utf-8")
    run = subprocess.run(["node", "run.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


HEAD = r"""
import worker, { dispatchWorkflow } from "./worker.mjs";
import * as W from "./watchdog.js";
const R = "https://api.github.com/repos/mrityurequest20-cyber/Quant-Desk";
const IST = (s) => Date.parse(s + "+05:30");
let calls = [], state = {}, logs = [];
console.log = (m) => logs.push(String(m));
const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json" } });
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  calls.push({ url, method: init.method || "GET", headers: init.headers || {}, body: init.body || null });
  if (url.endsWith("/dispatches")) return new Response(null, { status: 204 });
  if (url.startsWith("https://ntfy.sh/")) return new Response("{}", { status: 200 });
  if (url.endsWith("/data.json")) {
    if (state.hbStatus) return new Response("no", { status: state.hbStatus });
    return json({ state: { heartbeat: state.hb }, setups: state.setups });
  }
  const wf = url.match(/\/actions\/workflows\/([a-z-]+)\.yml\/runs/);
  if (wf) { if (state.ghFail) return new Response("x", { status: 500 }); return json({ workflow_runs: (state.runs || {})[wf[1]] || [] }); }
  if (url.includes("/actions/runs")) {
    const st = new URL(url).searchParams.get("status");
    return json({ workflow_runs: (state.failed || {})[st] || [] });
  }
  return new Response("?", { status: 404 });
};
const env = (extra = {}) => ({ GH_DISPATCH_TOKEN: "%TOKEN%", NTFY_TOPIC: "%TOPIC%", ORIGIN: "https://pages.example/Quant-Desk", ...extra });
async function at(when, e = env(), s = {}) {
  calls = []; logs = []; state = s;
  const results = await W.runWatchdog({ scheduledTime: IST(when) }, e, { dispatchWorkflow });
  return { results, calls, logs };
}
const alerts = (r) => r.results.flatMap((x) => x.alerts.map((a) => `${a.sev} ${a.check} ${a.title}`));
const pushes = (r) => r.calls.filter((c) => c.url.startsWith("https://ntfy.sh/"));
const emails = (r) => r.calls.filter((c) => c.url.endsWith("/watchdog-alert.yml/dispatches"));
const run = (created, conclusion = "success", status = "completed", extra = {}) =>
  ({ created_at: new Date(IST(created)).toISOString(), updated_at: new Date(IST(created) + 600000).toISOString(), conclusion, status, html_url: "https://github.com/x/y/actions/runs/1", name: "Live paper desk", head_branch: "main", ...extra });
const out = {};
""".replace("%TOKEN%", TOKEN).replace("%TOPIC%", TOPIC)


@NODE
def test_the_desk_not_started_is_a_p1_by_push_and_by_email_and_a_started_desk_is_silent(tmp_path):
    out = _node(tmp_path, HEAD + r"""
let r = await at("2026-10-23T09:10:00", env(), { runs: { live: [] } });
out.none = { alerts: alerts(r), push: pushes(r).map((c) => ({ url: c.url, h: c.headers, b: c.body })),
             email: emails(r).map((c) => JSON.parse(c.body)) };
r = await at("2026-10-23T09:10:00", env(), { runs: { live: [run("2026-10-23T08:52:00", "success", "in_progress")] } });
out.started = { alerts: alerts(r), n: r.calls.length };
r = await at("2026-10-20T09:10:00", env(), { runs: { live: [] } });          // Dussehra: a holiday
out.holiday = { alerts: alerts(r), n: r.calls.length };
r = await at("2026-10-24T09:10:00", env(), { runs: { live: [] } });          // Saturday
out.saturday = { alerts: alerts(r), n: r.calls.length };
r = await at("2026-10-23T09:11:00", env(), { runs: { live: [] } });          // not a slot
out.offslot = { alerts: alerts(r), n: r.calls.length };
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["none"]["alerts"] == ["P1 W1 Desk not started"]
    (push,) = out["none"]["push"]
    assert push["url"] == f"https://ntfy.sh/{TOPIC}" and push["h"]["Priority"] == "high" and "rotating_light" in push["h"]["Tags"]
    assert push["h"]["Title"].startswith("P1 W1: Desk not started") and "2026-10-23" in push["b"]
    (mail,) = out["none"]["email"]
    assert mail["ref"] == "main" and mail["inputs"]["severity"] == "P1" and mail["inputs"]["check"] == "W1"
    assert mail["inputs"]["day"] == "2026-10-23" and set(mail["inputs"]) == {"severity", "check", "title", "body", "link", "day"}
    assert out["started"]["alerts"] == [] and out["holiday"] == {"alerts": [], "n": 0} and out["saturday"] == {"alerts": [], "n": 0}
    assert out["offslot"] == {"alerts": [], "n": 0}


@NODE
def test_the_heartbeat_check_reads_age_halt_and_feed_and_survives_a_bad_site(tmp_path):
    out = _node(tmp_path, HEAD + r"""
const hb = (minAgo, extra = {}) => ({ ts: new Date(IST("2026-10-23T09:30:00") - minAgo * 60000 + 19800000 - 19800000).toISOString().replace("T", " ").replace("Z", "+00:00"), halted: false, feed: "kotak", ...extra });
const cases = { fresh: hb(3), warm: hb(15), stale: hb(25), halted: hb(2, { halted: true }), yahoo: hb(2, { feed: "yahoo" }), mixedOk: hb(2, { feed: "kotak+yahoo (190 of 570 polls from Yahoo)" }),
  mixedBad: hb(2, { feed: "kotak+yahoo (400 of 570 polls from Yahoo)" }), missing: undefined, noTs: {} };
out.cases = {};
for (const [k, v] of Object.entries(cases)) {
  const r = await at("2026-10-23T09:30:00", env(), { hb: v });
  out.cases[k] = { alerts: alerts(r), push: pushes(r).length, email: emails(r).length };
}
let r = await at("2026-10-23T09:30:00", env(), { hbStatus: 502 });
out.down = { alerts: alerts(r), email: emails(r).length };
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    c = out["cases"]
    assert c["fresh"] == {"alerts": [], "push": 0, "email": 0}
    assert c["warm"] == {"alerts": [], "push": 0, "email": 0}                      # 15 minutes is publish cadence + Pages lag, not a fault
    assert c["stale"]["alerts"] == ["P1 W2 Stale heartbeat"] and c["stale"]["push"] == 1 and c["stale"]["email"] == 1
    assert c["halted"]["alerts"] == ["P1 W2 Desk halted"]
    assert c["yahoo"] == {"alerts": ["P2 W2 Feed fell back"], "push": 1, "email": 0}          # P2: push only
    assert c["mixedOk"]["alerts"] == []                                            # the real label on 23 Oct: a third from Yahoo is normal
    assert c["mixedBad"]["alerts"] == ["P2 W2 Feed mostly Yahoo"]
    assert c["missing"]["alerts"] == ["P2 W2 Heartbeat unreadable"] and c["noTs"]["alerts"] == ["P2 W2 Heartbeat unreadable"]
    assert out["down"]["alerts"] == ["P2 W2 Watchdog could not run a check"] and out["down"]["email"] == 0   # blind is reported, not silent


@NODE
def test_after_close_checks_flag_missing_and_failed_runs_and_ignore_other_branches(tmp_path):
    out = _node(tmp_path, HEAD + r"""
const D = "2026-10-23";
let r = await at(D + "T16:00:00", env(), { runs: { live: [], "collect-wide": [] }, failed: {} });
out.missing = alerts(r);
r = await at(D + "T16:00:00", env(), { runs: { live: [run(D + "T08:52:00", "failure")], "collect-wide": [run(D + "T15:25:00")] }, failed: {} });
out.livefailed = alerts(r);
r = await at(D + "T16:00:00", env(), { runs: { live: [run(D + "T08:52:00", null, "in_progress")], "collect-wide": [run(D + "T15:25:00")] }, failed: {} });
out.running = alerts(r);
const f = (name, when, extra = {}) => run(when, "failure", "completed", { name, ...extra });
r = await at(D + "T16:00:00", env(), { runs: { live: [run(D + "T08:52:00")], "collect-wide": [run(D + "T15:25:00")] }, failed: {
  failure: [f("Collect wide data", D + "T15:30:00"), f("CI", D + "T11:00:00", { head_branch: "some-pr" }), f("Old", D + "T07:00:00")],
  cancelled: [f("Desk scheduler", D + "T12:00:00"), f("Live paper desk", D + "T13:00:00")] } });
out.failures = r.results.filter((x) => x.check === "W6").flatMap((x) => x.alerts.map((a) => [a.title, a.body]));
r = await at(D + "T18:00:00", env(), { runs: { selfreview: [] }, failed: {} });
out.eve = alerts(r);
r = await at(D + "T21:00:00", env(), { runs: { data: [run(D + "T20:15:00")] }, failed: {} });
out.late = alerts(r);
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["missing"] == ["P1 W3 Live paper desk did not run", "P2 W3 Collect wide data did not run"]
    assert out["livefailed"] == ["P1 W3 Live paper desk failed"] and out["running"] == []
    (title, body), = out["failures"]
    assert title == "2 workflow run(s) failed or cancelled"          # main only, since 08:00, Desk scheduler cancels ignored
    assert "Collect wide data" in body and "Live paper desk" in body and "CI" not in body and "Old" not in body
    assert out["eve"] == ["P2 W5 Self-review did not run"] and out["late"] == []


@NODE
def test_credential_expiry_alerts_as_each_threshold_is_crossed_and_once(tmp_path):
    out = _node(tmp_path, HEAD + r"""
const reg = (d) => env({ CRED_EXPIRY: JSON.stringify({ GH_DISPATCH_TOKEN: d }) });
const t = async (when, d) => alerts(await at(when, reg(d), {})).filter((a) => a.includes("W7"));
out.d14 = await t("2026-10-23T07:30:00", "2026-11-06");
out.d13 = await t("2026-10-23T07:30:00", "2026-11-05");
out.d7 = await t("2026-10-23T07:30:00", "2026-10-30");
out.d2 = await t("2026-10-23T07:30:00", "2026-10-25");
out.d1 = await t("2026-10-23T07:30:00", "2026-10-24");
out.mon = await t("2026-10-26T07:30:00", "2026-10-27");            // Monday: Friday saw 4 days, Monday sees 1: crossed the 2-day mark
out.expired = await t("2026-10-23T07:30:00", "2026-10-20");
out.bad = alerts(await at("2026-10-23T07:30:00", env({ CRED_EXPIRY: "{nope" }), {})).filter((a) => a.includes("W7"));
const r = await at("2026-10-23T07:30:00", reg("2026-10-30"), {});
out.p1email = emails(r).length; out.p1push = pushes(r).length;
out.leak = JSON.stringify(r.calls.map((c) => [c.body])).includes("github_pat_");
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["d14"] == ["P2 W7 GH_DISPATCH_TOKEN expires in 14 day(s)"] and out["d13"] == [] and out["d1"] == []
    assert out["d7"] == ["P1 W7 GH_DISPATCH_TOKEN expires in 7 day(s)"] and out["d2"] == ["P1 W7 GH_DISPATCH_TOKEN expires in 2 day(s)"]
    assert out["mon"] == ["P1 W7 GH_DISPATCH_TOKEN expires in 1 day(s)"] and out["expired"] == ["P1 W7 GH_DISPATCH_TOKEN has expired"]
    assert out["bad"] == ["P2 W7 Credential expiry register unreadable"] and out["leak"] is False
    # credential names and dates go by push only: the repository is public, so an issue would publish them
    assert out["p1push"] == 1 and out["p1email"] == 0


@NODE
def test_the_saturday_digest_carries_the_labelled_setup_line_and_is_never_held_back_by_it(tmp_path):
    out = _node(tmp_path, HEAD + r"""
const D = ["2026-10-19", "2026-10-21", "2026-10-22", "2026-10-23"];
const base = { runs: { live: D.map((d) => run(d + "T08:52:00")) }, failed: { failure: [] } };
const LINE = "Labelled setups: 4 this week (paper 2, replay 2, shadow 0); 4 in total from 2 sessions, 1% of the 300 the entry filter needs at least (300 to 500).";
const digest = async (extra, e = env()) => {
  const r = await at("2026-10-24T17:30:00", e, { ...base, ...extra });
  return { body: r.results.flatMap((x) => x.alerts.map((a) => a.body))[0], pushes: pushes(r).length, emails: emails(r).length };
};
out.ok = await digest({ setups: { line: LINE, total: 4 } });
out.missing = await digest({});
out.errored = await digest({ setups: { line: null, error: "AttributeError: no _dir" } });
out.down = await digest({ hbStatus: 503 });
out.noorigin = await digest({}, env({ ORIGIN: "" }));
out.blank = await digest({ setups: { line: "   " } });
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert "Sessions run 4 of 4 expected" in out["ok"]["body"] and "Labelled setups: 4 this week (paper 2, replay 2, shadow 0); 4 in total from 2 sessions" in out["ok"]["body"]
    assert out["ok"]["body"].index("Labelled setups") < out["ok"]["body"].index("Details:")
    assert "Labelled setups: not published in data.json." in out["missing"]["body"]
    assert "Labelled setups: not available (AttributeError: no _dir)." in out["errored"]["body"]
    assert "Labelled setups: not available (data.json answered 503)." in out["down"]["body"]
    assert "Labelled setups: not available (ORIGIN is not set)." in out["noorigin"]["body"]
    assert "Labelled setups: not published in data.json." in out["blank"]["body"]
    for k in out:                                                                       # whatever the line says, the digest itself goes out once by push and once by email
        assert out[k]["pushes"] == 1 and out[k]["emails"] == 1 and out[k]["body"].startswith("Sessions run 4 of 4 expected")


@NODE
def test_saturday_digest_and_the_december_calendar_check(tmp_path):
    out = _node(tmp_path, HEAD + r"""
const D = ["2026-10-19", "2026-10-21", "2026-10-22", "2026-10-23"];       // 20 Oct was a holiday
let r = await at("2026-10-24T17:30:00", env(), { runs: { live: D.map((d) => run(d + "T08:52:00")) }, failed: { failure: [run("2026-10-21T12:00:00", "failure")] } });
out.digest = r.results.flatMap((x) => x.alerts.map((a) => [a.sev, a.body]));
out.digestPush = pushes(r).map((c) => c.headers.Priority);
out.digestEmail = emails(r).length;
r = await at("2026-12-15T07:30:00", env(), {});
out.dec15 = alerts(r);
out.dec16 = alerts(await at("2026-12-16T07:30:00", env(), {}));
out.dec14 = alerts(await at("2026-12-14T07:30:00", env(), {}));
out.jun = alerts(await at("2026-06-15T07:30:00", env(), {}));
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    (sev, body), = out["digest"]
    assert sev == "INFO" and body.startswith("Sessions run 4 of 4 expected") and "failed on main: 1" in body
    assert out["digestPush"] == ["low"] and out["digestEmail"] == 1
    assert out["dec15"] == ["P2 W9 NSE 2027 holiday list not entered"] and out["dec16"] == [] and out["dec14"] == [] and out["jun"] == []


@NODE
def test_alerts_never_carry_secrets_and_degrade_without_a_topic_or_token(tmp_path):
    out = _node(tmp_path, HEAD + r"""
let r = await at("2026-10-23T09:10:00", env({ NTFY_TOPIC: "" }), { runs: { live: [] } });
out.notopic = { pushes: pushes(r).length, emails: emails(r).length, log: r.logs.join(" | ") };
r = await at("2026-10-23T09:10:00", env({ GH_DISPATCH_TOKEN: "" }), { runs: { live: [] } });
out.notoken = { pushes: pushes(r).length, emails: emails(r).length, log: r.logs.join(" | ") };
r = await at("2026-10-23T09:10:00", env({ NTFY_TOPIC: "a b/c" }), { runs: { live: [] } });
out.badtopic = pushes(r).length;
r = await at("2026-10-23T09:10:00", env(), { runs: { live: [] } });
out.logs = r.logs.join(" | ");
out.allBodies = JSON.stringify(r.calls.map((c) => [c.url.startsWith("https://ntfy.sh/") ? "ntfy" : c.url, c.body,
  c.url.startsWith("https://ntfy.sh/") ? c.headers : null]));
out.ascii = W.ascii("Désk — halted\n\t  now", 40);
out.test = (await at("2026-10-23T12:34:00", env({ WATCHDOG_TEST: "1" }), {})).results.map((x) => [x.check, x.alerts[0].sev]);
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["notopic"]["pushes"] == 0 and out["notopic"]["emails"] == 1 and "NTFY_TOPIC is not set" in out["notopic"]["log"]
    assert out["notoken"]["pushes"] == 1 and out["notoken"]["emails"] == 0 and "GH_DISPATCH_TOKEN is not set" in out["notoken"]["log"]
    assert out["badtopic"] == 0
    assert TOPIC not in out["logs"] and TOKEN not in out["logs"]                    # logs name outcomes, never the topic or the token
    assert TOKEN not in out["allBodies"] and TOPIC not in out["allBodies"]       # no body, URL or ntfy header carries either
    assert out["ascii"] == "D sk halted now"
    assert out["test"] == [["TEST", "INFO"]]                                        # the drill sends one INFO alert at any time


@NODE
def test_the_worker_starts_the_desk_before_the_watchdog_and_the_watchdog_trigger_never_starts_it(tmp_path):
    out = _node(tmp_path, HEAD + r"""
calls = []; state = { runs: { live: [] } };
await worker.scheduled({ cron: "*/10 2-9 * * MON-FRI", scheduledTime: IST("2026-10-23T09:10:00") }, env(), {});
out.alarm = calls.map((c) => c.url.split("/").slice(-2).join("/"));
calls = []; state = { runs: { live: [] } };
await worker.scheduled({ cron: "*/10 2-9 * * mon-fri", scheduledTime: IST("2026-10-23T09:10:00") }, env(), {});
out.odd = calls.map((c) => c.url.split("/").slice(-2).join("/"))[0];
calls = []; state = {};
await worker.scheduled({ cron: "0,30 10-16 * * *", scheduledTime: IST("2026-10-23T16:00:00") }, env(), {});
out.watch = calls.some((c) => c.url.includes("scheduler.yml"));
globalThis.fetch = async (url) => { if (String(url).includes("scheduler.yml")) return new Response(null, { status: 204 }); throw new Error("network down"); };
logs = [];
await worker.scheduled({ cron: "*/10 2-9 * * MON-FRI", scheduledTime: IST("2026-10-23T09:10:00") }, env(), {});
out.survived = true; out.logs = logs.join(" | ");
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["alarm"][0] == "scheduler.yml/dispatches"                  # the alarm clock goes first
    assert out["odd"] == "scheduler.yml/dispatches"                        # a cron string reported differently still starts the desk
    assert any(x == "watchdog-alert.yml/dispatches" for x in out["alarm"])
    assert out["watch"] is False                                           # the fifth trigger does not start the desk
    # the network is down for everything except the scheduler dispatch: the desk is still started, the failed check is reported
    # as an alert of its own, the unreachable ntfy and email are logged, and nothing is thrown out of the handler
    assert out["survived"] and "desk scheduler dispatched" in out["logs"] and "watchdog W1" in out["logs"]
    assert "ntfy was unreachable" in out["logs"]


# ---- no Node needed ------------------------------------------------------------------------------------------------------

def _js_holidays():
    text = (ROOT / "deploy" / "cloudflare" / "watchdog.js").read_text(encoding="utf-8")
    block = re.search(r"export const HOLIDAYS = \[(.*?)\];", text, flags=re.S).group(1)
    years = re.search(r"export const HOLIDAY_YEARS = \[(.*?)\];", text).group(1)
    return re.findall(r"\d{4}-\d{2}-\d{2}", block), [int(y) for y in years.split(",")]


def test_the_workers_holiday_copy_matches_the_desks_calendar():
    cfg = yaml.safe_load((ROOT / "config" / "quantdesk.yaml").read_text(encoding="utf-8"))["calendar"]
    days, years = _js_holidays()
    assert sorted(days) == sorted(str(d) for d in cfg["holidays"])
    assert years == cfg["holiday_years"]


def _cron_matches(expr, minute, hour, dow):
    """Cloudflare cron semantics for the patterns used here (UTC; day names)."""
    m, h, _dom, _mon, d = expr.split()
    names = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}

    def field(spec, lo, hi, conv=int):
        out = set()
        for part in spec.split(","):
            step = 1
            if "/" in part:
                part, s = part.split("/")
                step = int(s)
            if part == "*":
                a, b = lo, hi
            elif "-" in part:
                a, b = (conv(x) for x in part.split("-"))
            else:
                a = b = conv(part)
            out |= set(range(a, b + 1, step))
        return out
    return (minute in field(m, 0, 59) and hour in field(h, 0, 23) and
            dow in field(d, 0, 6, conv=lambda x: names[x] if x in names else int(x)))


def test_every_watchdog_slot_coincides_with_a_cron_firing():
    """A check scheduled at a time the Worker is never woken would silently never run (the audit found this in the first design)."""
    crons = _config()["triggers"]["crons"]
    text = (ROOT / "deploy" / "cloudflare" / "watchdog.js").read_text(encoding="utf-8")
    slots = re.findall(r'\{ at: "(\d\d):(\d\d)", days: "(\w+)"', text)
    assert len(slots) >= 14
    # one IST date per kind of day: a Friday, and a Saturday for the digest
    days = {"trading": [5], "weekdays": [1, 2, 3, 4, 5], "saturday": [6]}
    for hh, mm, kind in slots:
        utc_min = (int(hh) * 60 + int(mm) - 330) % 1440
        for dow in days[kind]:
            assert any(_cron_matches(c, utc_min % 60, utc_min // 60, dow) for c in crons), (hh, mm, kind, dow)


def test_the_alert_workflow_is_least_privilege_and_never_expands_inputs_into_a_script():
    path = ROOT / ".github" / "workflows" / "watchdog-alert.yml"
    wf = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert set(wf["on"]) == {"workflow_dispatch"}                                  # only the Worker (or the owner) can start it
    assert wf["permissions"] == {"contents": "read", "issues": "write"}
    steps = wf["jobs"]["alert"]["steps"]
    assert all("uses" not in s for s in steps)                                    # no third-party action, nothing to pin or trust
    for s in steps:
        assert "${{" not in s["run"], "inputs reach the script only through env"
    env = steps[0]["env"]
    assert env["GH_TOKEN"] == "${{ github.token }}" and not any("secrets." in str(v) for v in env.values())
    script = steps[0]["run"]
    assert "--assignee" in script and "watchdog-key" in script and "gh issue comment" in script   # notifies the owner; one issue per check per day
    assert "exit 1" in script                                                      # bad severity/day/check is refused


@NODE
def test_the_real_heartbeat_timestamp_format_parses(tmp_path):
    """Copied from the published data.json on 23 Oct 2026: pandas writes microseconds and an IST offset with a space, not a T."""
    out = _node(tmp_path, HEAD + r"""
out.real = W.parseTs("2026-10-23 15:30:04.402768+05:30");
out.expect = Date.parse("2026-10-23T15:30:04.402+05:30");
out.bad = [W.parseTs(null), W.parseTs("nonsense"), W.parseTs(12345)].map((x) => Number.isNaN(x));
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["real"] == out["expect"] and out["bad"] == [True, True, True]
