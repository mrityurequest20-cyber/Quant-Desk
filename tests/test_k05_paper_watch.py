"""Audit K-05 (FH-04, B-08; HIGH): no alert reached the owner when the paper runner went red or its state went stale. The paper run is one run from about 06:00 to
midnight, so W6 and W14 only ever saw it "in progress"; and nothing read the relay's paper state. Now W21 reads the run's parts (jobs) every half hour and W22
reads the relay's state while the run is in progress. Real runs of the shipped watchdog under Node, against canned GitHub and relay answers. PAPER MONEY ONLY."""
from __future__ import annotations

import pytest

from tests.test_watchdog import HEAD, NODE, _node

D = "2026-11-23"                     # a Monday (24 Nov is an NSE holiday)

PAPER_HEAD = HEAD + r"""
const D = "%D%";
const base = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
  const u = String(url);
  const m = u.match(/\/actions\/runs\/(\d+)\/jobs/);
  if (m) { calls.push({ url: u, method: "GET", headers: init.headers || {} }); return json({ jobs: (state.jobs || {})[m[1]] || [] }); }
  return base(url, init);
};
const secrets = { LIVE_INGEST_TOKEN: "i".repeat(30), LIVE_READ_TOKEN: "r".repeat(30) };
const relay = (summary) => ({ idFromName: () => "b", get: () => ({ fetch: async (u) => { calls.push({ url: String(u), method: "GET", headers: {} }); return json({ summary }); } }) });
const paper = (created, status = "in_progress", conclusion = null, id = 77) => ({ id, created_at: new Date(IST(created)).toISOString(), run_started_at: new Date(IST(created)).toISOString(),
  updated_at: new Date(IST(created)).toISOString(), status, conclusion, html_url: "https://github.com/x/y/actions/runs/77", name: "Paper runner", head_branch: "main" });
const job = (name, conclusion, ended, status = "completed") => ({ name, status, conclusion, completed_at: ended ? new Date(IST(ended)).toISOString() : null, html_url: "https://github.com/x/y/actions/runs/77/job/1" });
const of = (r, check) => r.results.filter((x) => x.check === check).flatMap((x) => x.alerts);
const fmt = (r, check) => of(r, check).map((a) => `${a.sev} ${a.title}`);
""".replace("%D%", D)


@NODE
def test_a_red_part_is_a_p1_by_push_and_email_at_the_next_half_hour_and_only_then(tmp_path):
    out = _node(tmp_path, PAPER_HEAD + r"""
const runs = { "paper-desk": [paper(D + "T05:55:00")] };
const jobs = { 77: [job("morning", "failure", D + "T11:20:00"), job("afternoon", null, null, "in_progress")] };
let r = await at(D + "T11:30:00", env(), { runs, jobs });
out.first = fmt(r, "W21");
out.pushed = pushes(r).length; out.emailed = emails(r).length;
out.body = of(r, "W21").map((a) => a.body).join(" ");
r = await at(D + "T12:00:00", env(), { runs, jobs });
out.again = fmt(r, "W21");
r = await at(D + "T11:00:00", env(), { runs, jobs: { 77: [job("morning", null, null, "in_progress")] } });
out.running = fmt(r, "W21");
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["first"] == ["P1 Paper runner: the morning part ended failure"]          # was: nothing until the Saturday digest's count (FH-04)
    assert out["pushed"] >= 1 and out["emailed"] == 1                                    # P1: push, and the email issue (the GitHub email went to the bot)
    assert "11:20 IST" in out["body"]
    assert out["again"] == [] and out["running"] == []                                   # reported once, by the first slot after it ended


@NODE
def test_a_part_killed_by_its_time_limit_ends_cancelled_and_is_reported_and_green_or_skipped_parts_are_not(tmp_path):
    out = _node(tmp_path, PAPER_HEAD + r"""
const runs = { "paper-desk": [paper(D + "T05:55:00")] };
let r = await at(D + "T15:00:00", env(), { runs, jobs: { 77: [job("morning", "success", D + "T11:45:00"), job("afternoon", "cancelled", D + "T14:56:00")] } });
out.killed = fmt(r, "W21");
r = await at(D + "T12:00:00", env(), { runs, jobs: { 77: [job("morning", "success", D + "T11:45:00"), job("afternoon", "skipped", D + "T11:46:00")] } });
out.fine = fmt(r, "W21");
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["killed"] == ["P1 Paper runner: the afternoon part ended cancelled"] and out["fine"] == []


@NODE
def test_the_night_part_is_watched_after_midnight_and_on_any_day(tmp_path):
    out = _node(tmp_path, PAPER_HEAD + r"""
const runs = { "paper-desk": [paper("2026-11-27T05:55:00", "completed", "failure")] };                     // a Friday's run, read on Saturday at 00:10
let r = await at("2026-11-28T00:10:00", env(), { runs, jobs: { 77: [job("night", "failure", "2026-11-27T23:59:30")] } });
out.night = fmt(r, "W21");
r = await at("2026-11-24T19:00:00", env(), { runs: { "paper-desk": [paper("2026-11-24T16:50:00")] }, jobs: { 77: [job("morning", "failure", "2026-11-24T18:40:00")] } });
out.holiday = fmt(r, "W21");                                                                                  // an NSE holiday's MCX evening (K-37)
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["night"] == ["P1 Paper runner: the night part ended failure"] and out["holiday"] == ["P1 Paper runner: the morning part ended failure"]


@NODE
def test_a_stale_state_or_brakes_down_while_the_run_is_in_progress_is_a_p1_by_push_only(tmp_path):
    out = _node(tmp_path, PAPER_HEAD + r"""
const runs = { "paper-desk": [paper(D + "T05:55:00")] };
const S = (o) => env({ ...secrets, LIVE: relay(o) });
const fresh = IST(D + "T13:30:00") - 5000, old = IST(D + "T13:30:00") - 20 * 60000;
let r = await at(D + "T13:30:00", S({ received_at: old, equity: 523456.78, positions: [{ symbol: "NIFTYX" }] }), { runs });
out.stale = fmt(r, "W22"); out.staleEmail = emails(r).length; out.staleBody = of(r, "W22").map((a) => a.body).join(" ");
r = await at(D + "T13:30:00", S({ received_at: fresh }), { runs });
out.fresh = fmt(r, "W22");
r = await at(D + "T13:30:00", S({ received_at: fresh, brakes_down: true }), { runs });
out.brakes = fmt(r, "W22"); out.brakesEmail = emails(r).length;
r = await at(D + "T13:30:00", S({ received_at: fresh, degraded: "summary failed (KeyError)" }), { runs });
out.degraded = fmt(r, "W22");
r = await at(D + "T13:30:00", S(null), { runs });
out.none = fmt(r, "W22");
r = await at(D + "T14:00:00", S({ received_at: old }), { runs });
out.repeats = fmt(r, "W22");
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["stale"] == ["P1 Paper runner: its state on the relay is stale"] and "20 minutes ago" in out["staleBody"]     # was: silent for 94 minutes (B-08). (13:30 and 14:00: no W10 at those times)
    assert out["staleEmail"] == 0 and out["brakesEmail"] == 0                            # push only: it reads the relay's private state; an email is a public issue
    assert "523" not in out["staleBody"] and "NIFTYX" not in out["staleBody"]            # no account figure or position ever reaches an alert
    assert out["fresh"] == [] and out["brakes"] == ["P1 Paper runner: the brakes are down"]
    assert out["degraded"] == ["P2 Paper runner: the app's view is degraded"]
    assert out["none"] == ["P1 Paper runner: its state on the relay is stale"] and out["repeats"] == ["P1 Paper runner: its state on the relay is stale"]


@NODE
def test_the_state_check_is_silent_with_no_run_in_progress_a_just_started_run_or_the_live_view_off(tmp_path):
    out = _node(tmp_path, PAPER_HEAD + r"""
const S = (o) => env({ ...secrets, LIVE: relay(o) });
const old = IST(D + "T13:30:00") - 60 * 60000;
out.done = fmt(await at(D + "T13:30:00", S({ received_at: old }), { runs: { "paper-desk": [paper(D + "T05:55:00", "completed", "success")] } }), "W22");
out.young = fmt(await at(D + "T13:30:00", S({ received_at: old }), { runs: { "paper-desk": [paper(D + "T13:20:00")] } }), "W22");
out.off = fmt(await at(D + "T13:30:00", env(), { runs: { "paper-desk": [paper(D + "T05:55:00")] } }), "W22");
out.weekend = fmt(await at("2026-11-29T13:30:00", S({ received_at: old }), { runs: { "paper-desk": [] } }), "W22");
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out == {"done": [], "young": [], "off": [], "weekend": []}


@NODE
def test_a_relay_that_never_answers_is_reported_and_never_holds_the_firing(tmp_path):
    out = _node(tmp_path, PAPER_HEAD + r"""
const hang = { idFromName: () => "b", get: () => ({ fetch: () => new Promise(() => {}) }) };
const t0 = Date.now();
const r = await at(D + "T13:30:00", env({ ...secrets, LIVE: hang }), { runs: { "paper-desk": [paper(D + "T05:55:00")] } });
out.ms = Date.now() - t0;
out.w22 = fmt(r, "W22");
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["w22"] == ["P2 Watchdog could not run a check"] and out["ms"] < 15000


def test_the_slots_cover_every_half_hour_of_the_desks_day_and_the_night_parts_end():
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "deploy" / "cloudflare" / "watchdog.js").read_text(encoding="utf-8")
    assert 'export const PAPER_SLOTS = ["00:10", ...Array.from({ length: 36 }' in src and "PAPER_STALE_MIN = 10" in src
    assert re.search(r'PAPER_SLOTS\.map\(\(at\) => \(\{ at, days: "all", run: w21PaperParts, check: "W21" \}\)\)', src)
    assert re.search(r'run: w22PaperState, check: "W22"', src)


@NODE
@pytest.mark.parametrize("hhmm, prev", [("06:00", "2026-11-23T00:10"), ("00:10", "2026-11-22T23:30"), ("13:30", "2026-11-23T13:00"), ("23:30", "2026-11-23T23:00")])
def test_each_slot_looks_back_to_the_previous_one(tmp_path, hhmm, prev):
    out = _node(tmp_path, PAPER_HEAD + f"""
out.prev = W.prevPaperSlotMs(IST("2026-11-23T{hhmm}:00")) === IST("{prev}:00");
out.n = W.PAPER_SLOTS.length;
console.log = () => {{}}; process.stdout.write(JSON.stringify(out) + "\\n");
""")
    assert out == {"prev": True, "n": 37}
