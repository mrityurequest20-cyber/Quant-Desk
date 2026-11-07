"""The app after the clean-up of 7 Nov 2026: four tabs (Live, Today, History, Data), nothing left of the retired desk's Desk, Chart, Brain and Feed screens, a header pill that speaks
for the live feeds, and a published data.json that no longer carries the desk's thoughts, news and charts. The pure parts run under Node; the page itself was driven in Chromium."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "quantdesk/web/static/app/app.js").read_text()
HTML = (ROOT / "quantdesk/web/static/app/index.html").read_text()
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def test_the_app_has_exactly_five_tabs_and_a_section_for_each():
    tabs = re.search(r"const TABS = (\[.*?\]\]);", APP).group(1)
    assert re.findall(r'\["(\w+)", "(\w+)"\]', tabs) == [("live", "Live"), ("build", "Build"), ("today", "Today"), ("trades", "History"), ("data", "Data")]
    assert re.findall(r'<section data-view="(\w+)"', HTML) == ["trades", "live", "build", "today", "data"]
    assert "repeat(5,1fr)" in HTML and "repeat(7" not in HTML
    assert 'SUBS = { trades: [["history", "History"], ["performance", "Performance"], ["reviews", "Reviews"]] }' in APP     # no open-positions screen: nothing trades


def test_nothing_of_the_retired_screens_is_left_and_every_element_the_code_asks_for_exists():
    for gone in ("renderDesk", "renderChart", "renderBrain", "renderFeed", "renderLog", "renderPositionsTab", "drawChart", "createLW", "loadChart", "loadNews", "installCard", "deskStatus", "loadState"):
        assert gone not in APP, gone
    for gone in ('data-view="desk"', 'data-view="chart"', 'data-view="brain"', 'data-view="feed"', 'id="d-now"', 'id="c-box"', 'id="b-body"', 'id="f-body"', 'data-go='):
        assert gone not in HTML, gone
    wanted = set(re.findall(r'\$\("#([\w-]+)"\)', APP))
    have = set(re.findall(r'id="([\w-]+)"', HTML)) | set(re.findall(r'id: "([\w-]+)"', APP))
    assert wanted <= have, sorted(wanted - have)
    assert "innerHTML" not in APP                                                  # server text goes in with textContent only


def test_an_old_bookmark_or_saved_tab_lands_on_live_and_the_history_tab_says_it_is_a_record():
    assert 'tab = "live"' in APP and 'store("qd.tab") || "live"' in APP and 'show(t || "live", s)' in APP
    assert 'tab: "live"' in APP and 'trades: "history"' in APP
    assert "stopped trading on 6 Nov 2026" in HTML and "read-only" in HTML


def status_part() -> str:
    return APP[APP.index("function liveStatus()"):APP.index("function setStatus()")]


def run_status(tmp_path, cases: list[dict]) -> list[dict]:
    script = r"""
const LIVE_FRESH = 15, LIVE_DELAYED = 120;
const fin = (v) => v != null && isFinite(v);
const liveAge = (s) => Math.round(s) + "s";
const nextOpen = () => "Mon 09:15";
const cases = JSON.parse(process.argv[2]);
const out = [];
for (const c of cases) {
	const S = { lv: { health: c.health || null, hstate: c.hstate == null ? 200 : c.hstate } };
	const location = { hostname: c.host || "quant-desk.example.workers.dev" };
	const navigator = { onLine: c.online !== false };
	const store = () => (c.key === false ? null : "k".repeat(40));
	const inSession = () => !!c.session;
	""" + status_part() + r"""
	out.push(liveStatus());
}
console.log(JSON.stringify(out));
"""
    (tmp_path / "s.mjs").write_text(script.replace("\tconst S =", "\tconst S =").replace("function liveStatus() {\n\tconst L = S.lv", "function liveStatus() {\n\tconst L = S.lv"), encoding="utf-8")
    r = subprocess.run(["node", "s.mjs", json.dumps(cases)], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
def test_the_header_pill_says_what_the_live_feeds_are_doing(tmp_path):
    fresh = {"kite": {"n": 900, "newest_age_s": 2.0}, "kotak": {"n": 400, "newest_age_s": 4.0}}
    out = run_status(tmp_path, [
        {"host": "mrityurequest20-cyber.github.io"},                                   # 0 the public copy: no live feed at all
        {"online": False},                                                             # 1
        {"key": False},                                                                # 2 no key typed yet
        {"hstate": 503},                                                               # 3 the relay is not switched on
        {"hstate": 401},                                                               # 4 the relay refused the key
        {"hstate": "err"},                                                             # 5 the request failed
        {},                                                                            # 6 nothing back yet
        {"health": fresh, "session": True},                                            # 7 both sources fresh
        {"health": {"kite": {"n": 9, "newest_age_s": 3.0}, "kotak": {"n": 0, "newest_age_s": None}}, "session": True},          # 8 only Kite
        {"health": {"kite": {"n": 9, "newest_age_s": 60.0}, "kotak": {"n": 0, "newest_age_s": None}}, "session": True},         # 9 a minute old, in the session
        {"health": {"kite": {"n": 9, "newest_age_s": 900.0}, "kotak": {"n": 0, "newest_age_s": None}}, "session": True},        # 10 long silent, in the session
        {"health": {"kite": {"n": 9, "newest_age_s": 900.0}, "kotak": {"n": 0, "newest_age_s": None}}, "session": False},       # 11 silent after the close: closed, not broken
        {"health": {"kite": {"n": 0, "newest_age_s": None}, "kotak": {"n": 0, "newest_age_s": None}}, "session": True},         # 12 empty board in the session
        {"health": {"kite": {"n": 0, "newest_age_s": None}, "kotak": {"n": 0, "newest_age_s": None}}, "session": False},        # 13 empty board overnight
    ])
    t = [(o["t"], o["k"]) for o in out]
    assert t[0] == ("Public copy", "off") and t[1] == ("Offline", "off net") and t[2] == ("Live off", "off")
    assert t[3] == ("Relay off", "off") and t[4] == ("Key?", "off") and t[5] == ("No answer", "off") and t[6] == ("Connecting", "off")
    assert t[7] == ("Live", "live") and out[7]["s"] == "Kite + Kotak"
    assert t[8] == ("Live", "live") and out[8]["s"] == "Kite"
    assert t[9] == ("Delayed", "stale") and out[9]["s"] == "60s"
    assert t[10] == ("No feed", "stale")
    assert t[11] == ("Closed", "off") and "opens" in out[11]["s"]
    assert t[12] == ("No prices", "stale") and t[13] == ("Closed", "off")


def test_the_pill_is_polled_on_every_tab_without_the_live_tab_and_the_key_only_goes_to_the_relay():
    poll = APP[APP.index("async function pollHealth()"):APP.index("// ---- ", APP.index("async function pollHealth()"))]
    assert '"/live/health"' in poll and 'Authorization: "Bearer " + key' in poll and 'cache: "no-store"' in poll
    assert "github" in poll.split("fetch(")[0]                                         # the public address never sends a request
    assert "setInterval(pollHealth, 10000)" in APP


def test_the_published_data_no_longer_carries_the_retired_desks_thoughts_news_and_charts(cfg, tmp_path):
    from quantdesk.web.export_site import ROUTES, publish_site
    out = publish_site(cfg, "live", tmp_path / "site")
    data = json.loads((out / "data.json").read_text())
    for gone in ("thoughts", "news", "chart", "export_errors"):
        assert gone not in data, gone
    for kept in ("state", "trades", "trade", "reviews", "stats", "setups", "premarket_url"):                      # History, the Today brief and the Saturday digest still read these
        assert kept in data, kept
    for gone in ("/api/i/thoughts", "/api/i/news", "/api/i/chart"):
        assert gone not in ROUTES, gone


def test_the_data_tab_says_what_is_recorded_and_what_is_not():
    part = APP[APP.index("const DATA_RECORDED"):APP.index("async function renderDataTab")]
    for needle in ("record.yml", "kite-record.yml", "collect-wide.yml", "data.yml", "premarket.yml", "15:32", "MCX and currency", "encrypted"):
        assert needle in part, needle
    body = APP[APP.index("async function renderDataTab"):APP.index("function openSettings")]
    assert "/live/health" not in body and "liveStatus()" in body                      # it reads the one poller's answer, it does not poll a second time
    assert "Data health workflow" in body


def test_the_pill_follows_the_key_at_once_and_a_closed_market_says_so():
    save = APP[APP.index("function liveKeyForm"):APP.index("function liveRows")]
    assert "renderLive(); pollHealth(); }" in save                                  # saving a key refreshes the pill now, not at the next 10 s poll
    forget = APP[APP.index('"Forget this key"') - 330:APP.index('"Forget this key"')]
    assert "L.health = null" in forget and "setStatus()" in forget                  # forgetting it clears the old health and the pill
    assert 'setStatus(); return void put(body, liveKeyForm(note))' in APP          # a refused key or a down relay updates the pill too
    assert '"Market closed, opens " + nextOpen()' in APP and 'inSession() ? "No prices yet"' in APP
