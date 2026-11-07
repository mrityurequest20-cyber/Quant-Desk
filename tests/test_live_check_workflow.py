"""The 'Live relay check' workflow (.github/workflows/live-check.yml): run by hand, it calls the relay from GitHub with the owner's READ key and prints a status code and counts, never the key.
These tests pin what makes it safe to hold a secret and run the real script against a local mock relay."""
from __future__ import annotations

import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / ".github/workflows/live-check.yml"
WF = yaml.load(FILE.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
STEP = WF["jobs"]["check"]["steps"][0]
SCRIPT = STEP["run"]
KEY = "k" * 40


def test_it_holds_one_secret_reads_nothing_runs_no_third_party_code_and_follows_no_redirect():
    assert WF["on"] == {"workflow_dispatch": {}}                                            # by hand only: no schedule, no pull request
    assert WF["permissions"] == {}                                                          # no token scopes at all: it reads no repository content
    assert len(WF["jobs"]["check"]["steps"]) == 1 and "uses" not in STEP                    # no action: nothing to pin, no checkout
    assert set(STEP["env"]) == {"LIVE_URL", "LIVE_READ_TOKEN"} and "secrets.LIVE_READ_TOKEN" in STEP["env"]["LIVE_READ_TOKEN"]
    assert not any(re.search(r"secrets\.", str(v)) for k, v in STEP["env"].items() if k != "LIVE_READ_TOKEN")
    assert not re.search(r"curl[^\n]*(\s-[A-Za-z]*L[A-Za-z]*\b|\s--location)", SCRIPT)               # a redirect would forward the key (-L, -sSL, --location)
    assert not re.search(r"curl[^\n]*(\s-[A-Za-z]*v[A-Za-z]*\b|\s--verbose)", SCRIPT)               # no verbose output
    assert not re.search(r"set -x|curl[^\n]*( -v\b| --verbose)|echo[^\n]*\$\{?LIVE_READ_TOKEN", SCRIPT)      # nothing prints the key
    assert 'https://*/live/ingest' in SCRIPT and "exit 1" in SCRIPT                          # https only (loopback aside, for the test)
    assert re.search(r"-m 20", SCRIPT)                                                       # every call has a timeout


class Relay(BaseHTTPRequestHandler):
    mode = "ok"
    def log_message(self, *a): pass
    def _send(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        auth = self.headers.get("authorization")
        if Relay.mode == "off": return self._send(503, {"error": "the live view is not switched on"})
        if auth != "Bearer " + (KEY if Relay.mode == "ok" else "something-else"): return self._send(401, {"error": "no"})
        if self.path == "/live/snapshot": return self._send(200, {"count": 12, "newest_age_s": 3.5, "quotes": {}})
        if self.path == "/live/health": return self._send(200, {"kite": {"n": 7}, "kotak": {"status": "ok", "n": 5, "universe": {"asof": "2026-11-09"}}})
        return self._send(404, {"error": "x"})


def run_script(mode: str, tmp_path, token=KEY, url_tail="/live/ingest"):
    Relay.mode = mode
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Relay)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "LIVE_URL": f"http://127.0.0.1:{srv.server_port}{url_tail}", "LIVE_READ_TOKEN": token}
        r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", SCRIPT], capture_output=True, text=True, timeout=60, env=env, cwd=tmp_path)
        return r.returncode, r.stdout + r.stderr
    finally:
        srv.shutdown()


def test_the_right_key_opens_the_relay_and_the_summary_is_counts_only(tmp_path):
    code, out = run_script("ok", tmp_path)
    assert code == 0 and "Without a key: HTTP 401" in out and "With the READ key: HTTP 200" in out
    assert "Instruments on the board: 12" in out and "Kite instruments: 7" in out and "Kotak: ok" in out
    assert KEY not in out


def test_a_wrong_key_a_switched_off_relay_a_missing_secret_and_a_bad_address_each_say_so_and_fail(tmp_path):
    code, out = run_script("wrong", tmp_path)
    assert code == 1 and "HTTP 401" in out and "REJECTED" in out and KEY not in out
    code, out = run_script("off", tmp_path)
    assert code == 1 and "NOT SWITCHED ON" in out and KEY not in out
    code, out = run_script("ok", tmp_path, token="")
    assert code == 1 and "LIVE_READ_TOKEN is not set" in out
    code, out = run_script("ok", tmp_path, url_tail="/somewhere/else")
    assert code == 1 and "LIVE_URL must be https" in out and KEY not in out


def test_it_refuses_a_plain_http_address_that_is_not_loopback(tmp_path):
    r = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", SCRIPT], capture_output=True, text=True, timeout=30,
                       env={"PATH": "/usr/bin:/bin", "LIVE_URL": "http://example.com/live/ingest", "LIVE_READ_TOKEN": KEY}, cwd=tmp_path)
    assert r.returncode == 1 and "LIVE_URL must be https" in r.stdout and KEY not in r.stdout + r.stderr
