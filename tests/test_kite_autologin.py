"""The automatic Kite login (deploy/kite_autologin.py), against a local stand-in for Zerodha's login flow: the connect page, the
password and TOTP posts, the cookie, and the redirect chain that ends at the app's redirect URL with a request_token."""
import ast
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
import kite_autologin as KA  # noqa: E402

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"          # base32 of the RFC 6238 SHA-1 seed "12345678901234567890"
USER, PASSWORD, SECRET, KEY = "AB1234", "s3cret-pass!", "JBSWY3DPEHPK3PXP", "apikey123"
REQUEST_TOKEN = "RT0123456789abcdefXYZ"


def test_totp_matches_the_rfc_6238_vectors():
    # RFC 6238 appendix B (SHA-1), last 6 of the 8 digits
    for t, code in ((59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037")):
        assert KA.totp(RFC_SECRET, t) == code
    assert KA.totp("gezd gnbv gy3t qojq gezd gnbv gy3t qojq", 59) == "287082"        # spaces and lower case, as some apps show it


class Fake(http.server.BaseHTTPRequestHandler):
    authorised = True
    spa = False             # True: a logged-in login page answers 200 (the browser's JavaScript hands over), unless skip_session=true
    has_finish = True       # False: /connect/finish does not exist
    log: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj, headers=()):
        self._send(code, json.dumps(obj).encode(), [("Content-Type", "application/json"), *headers])

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        Fake.log.append(("GET", u.path))
        logged_in = "enctoken=E1" in (self.headers.get("Cookie") or "")
        if u.path == "/connect/login":
            if "sess_id" not in q:
                return self._send(302, headers=[("Location", f"/connect/login?api_key={q['api_key'][0]}&sess_id=S1"), ("Set-Cookie", "kf_session=K1; Path=/")])
            if logged_in and Fake.spa and q.get("skip_session") != ["true"]:
                return self._send(200, b"<html>one moment ... (javascript hands over)</html>")
            if logged_in and q.get("skip_session") == ["true"] and Fake.authorised:      # the server-side hand-over: straight to the app
                return self._send(302, headers=[("Location", f"https://myapp.example/cb?action=login&status=success&request_token={REQUEST_TOKEN}")])
            if logged_in:
                return self._send(302, headers=[("Location", "/connect/finish?sess_id=S1")])
            return self._send(200, b"<html>login</html>")
        if u.path == "/connect/finish":
            if not Fake.has_finish:
                return self._send(404)
            if not Fake.authorised:
                return self._send(302, headers=[("Location", "/connect/authorize?sess_id=S1")])
            return self._send(302, headers=[("Location", f"https://myapp.example/cb?action=login&status=success&request_token={REQUEST_TOKEN}")])
        if u.path == "/connect/authorize":
            return self._send(200, b"<html>authorise this app</html>")
        return self._send(404)

    def do_POST(self):
        form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        f = {k: v[0] for k, v in form.items()}
        Fake.log.append(("POST", self.path))
        if "kf_session=K1" not in (self.headers.get("Cookie") or ""):
            return self._json(400, {"status": "error", "message": "no session"})
        if self.path == "/api/login":
            if f.get("user_id") == USER and f.get("password") == PASSWORD:
                return self._json(200, {"status": "success", "data": {"user_id": USER, "request_id": "R1", "twofa_type": "totp", "twofa_types": ["totp"]}})
            return self._json(403, {"status": "error", "message": "Invalid `user_id` or `password`.", "error_type": "InputException"})
        if self.path == "/api/twofa":
            now = time.time()
            ok = {KA.totp(SECRET, now), KA.totp(SECRET, now - 30)}
            if f.get("request_id") == "R1" and f.get("twofa_type") == "totp" and f.get("twofa_value") in ok:
                return self._json(200, {"status": "success", "data": {}}, [("Set-Cookie", "enctoken=E1; Path=/")])
            return self._json(403, {"status": "error", "message": "Invalid TOTP", "error_type": "TwoFAException"})
        return self._send(404)


@pytest.fixture()
def zerodha():
    Fake.authorised, Fake.spa, Fake.has_finish, Fake.log = True, False, True, []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _login(base, **kw):
    args = dict(api_key=KEY, user_id=USER, password=PASSWORD, totp_secret=SECRET)
    args.update({k: v for k, v in kw.items() if k != "schemes"})
    return KA.request_token(args["api_key"], args["user_id"], args["password"], args["totp_secret"], base=base, hosts={"127.0.0.1"},
                            schemes=kw.get("schemes", ("http",)))


def test_the_login_returns_the_request_token_and_never_opens_the_apps_redirect_url(zerodha, monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False), monkeypatch.delenv("HTTP_PROXY", raising=False), monkeypatch.delenv("https_proxy", raising=False), monkeypatch.delenv("http_proxy", raising=False)
    assert _login(zerodha) == REQUEST_TOKEN
    assert ("POST", "/api/login") in Fake.log and ("POST", "/api/twofa") in Fake.log
    assert Fake.log[-1] == ("GET", "/connect/finish")                        # it stopped at the redirect to myapp.example


def test_a_wrong_password_fails_and_the_message_carries_no_secret(zerodha, monkeypatch):
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(KA.LoginError) as e:
        _login(zerodha, password="wrong-pass")
    assert "Invalid" in str(e.value) and "wrong-pass" not in str(e.value) and PASSWORD not in str(e.value)


def test_a_wrong_totp_key_fails_after_one_retry(zerodha, monkeypatch):
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(KA.LoginError, match="two-factor"):
        _login(zerodha, totp_secret="KRSXG5CTMVRXEZLU")
    assert Fake.log.count(("POST", "/api/twofa")) == 2


def test_an_app_the_user_never_authorised_says_so_instead_of_hanging(zerodha, monkeypatch):
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(k, raising=False)
    Fake.authorised = False
    with pytest.raises(KA.LoginError, match="authorise"):
        _login(zerodha)


def test_without_the_secrets_it_does_nothing_and_succeeds(tmp_path, monkeypatch, capsys):
    for k in ("KITE_DATA_KEY", "KITE_USER_ID", "KITE_PASSWORD", "KITE_TOTP_SECRET"):
        monkeypatch.delenv(k, raising=False)
    out = tmp_path / "req"
    assert KA.main(["--out", str(out)]) == 0 and not out.exists() and "not configured" in capsys.readouterr().out


def test_a_totp_key_that_is_not_base32_is_named_not_tried(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KITE_DATA_KEY", KEY), monkeypatch.setenv("KITE_USER_ID", USER), monkeypatch.setenv("KITE_PASSWORD", PASSWORD)
    monkeypatch.setenv("KITE_TOTP_SECRET", "123456")                       # a 6-digit code pasted instead of the key
    assert KA.main(["--out", str(tmp_path / "req")]) == 1 and "not a base32 key" in capsys.readouterr().out


def test_the_process_that_holds_the_password_imports_only_the_standard_library():
    tree = ast.parse((ROOT / "deploy" / "kite_autologin.py").read_text())
    mods = {(a.name if isinstance(n, ast.Import) else n.module).split(".")[0]
            for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [n])}
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}, mods - set(sys.stdlib_module_names)
    sh = (ROOT / "deploy" / "kite-autologin.sh").read_text()
    assert '"$py" -I -S "$here/kite_autologin.py"' in sh and "py=/usr/bin/python3" in sh   # the system Python; -I: no PYTHONPATH, user site or
                                                                            # cwd; -S: no site-packages, so no installed package's .pth runs


def test_nothing_in_the_login_path_can_trade():
    for f in ("deploy/kite_autologin.py", "deploy/kite-autologin.sh"):
        src = (ROOT / f).read_text()
        for call in ("place_order", "modify_order", "cancel_order", "exit_order", "positions(", "holdings(", "margins(", "/orders", "/portfolio"):
            assert call not in src, (f, call)
    sh = (ROOT / "deploy" / "kite-autologin.sh").read_text()
    assert "KITE_DATA_TOKEN=" in sh and "KITE_ACCESS_TOKEN" not in sh and "KITE_API_KEY" not in sh    # the data path's names, never the broker adapter's


def test_exchange_without_a_login_is_a_quiet_no_op(tmp_path):
    env = {**os.environ, "RUNNER_TEMP": str(tmp_path)}
    r = subprocess.run(["bash", str(ROOT / "deploy" / "kite-autologin.sh"), "exchange"], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "nothing to exchange" in r.stdout


def test_a_redirect_to_plain_http_is_refused_so_the_session_cookie_never_travels_unencrypted(zerodha, monkeypatch):
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(KA.LoginError, match="non-HTTPS"):
        _login(zerodha, schemes=("https",))                               # the stand-in redirects over http: refused at the first hop
    assert ("POST", "/api/login") not in Fake.log                          # the password was never sent


# ---- the login gate: only the first run of the day, first attempt ----------------------------------------------------------------
import datetime as _dt  # noqa: E402
import kite_login_gate as G  # noqa: E402

DAY = _dt.date(2026, 11, 9)


def _r(i, ist):
    return {"databaseId": i, "createdAt": _dt.datetime.fromisoformat(ist).replace(tzinfo=G.IST).astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_only_the_first_run_of_the_day_on_its_first_attempt_may_log_in():
    yday = _r(90, "2026-11-06 08:30")
    assert G.may_log_in([_r(100, "2026-11-09 08:30"), yday], 100, 1, DAY)[0] is True
    assert G.may_log_in([_r(101, "2026-11-09 08:55"), _r(100, "2026-11-09 08:30")], 101, 1, DAY)[0] is False     # a late cron / second starter
    assert G.may_log_in([_r(101, "2026-11-09 08:30"), _r(100, "2026-11-09 08:30")], 100, 1, DAY)[0] is True      # a race: the earlier id wins
    assert G.may_log_in([_r(101, "2026-11-09 08:30"), _r(100, "2026-11-09 08:30")], 101, 1, DAY)[0] is False     # ... and the later one skips
    assert G.may_log_in([_r(100, "2026-11-09 08:30")], 100, 2, DAY)[0] is False                                    # "Re-run failed jobs"
    assert G.may_log_in([_r(100, "2026-11-09 00:10")], 100, 1, DAY)[0] is True                                     # IST day, not UTC
    assert G.may_log_in([], 100, 1, DAY)[0] is False                                                               # can't see itself: no login
    assert G.may_log_in([_r(100, "2026-11-08 23:50")], 100, 1, DAY)[0] is False                                    # created yesterday, gated today


def test_the_gate_says_no_when_it_cannot_read_the_runs(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_RUN_ID", "100"), monkeypatch.setenv("GITHUB_REPOSITORY", "o/r"), monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("PATH", str(tmp_path))                                 # no gh on the path
    assert G.main() == 0 and out.read_text() == "first=false\n"
    src = (ROOT / "deploy" / "kite_login_gate.py").read_text()
    tree = ast.parse(src)
    mods = {(a.name if isinstance(n, ast.Import) else n.module).split(".")[0]
            for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [n])}
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}


# ---- the hand-over after the second factor (the real run on 6 Nov 2026 stopped here: HTTP 200 instead of a redirect) -----------
def _no_proxy(monkeypatch):
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(k, raising=False)


def test_when_the_login_page_answers_200_the_finish_route_hands_over(zerodha, monkeypatch):
    _no_proxy(monkeypatch)
    Fake.spa = True
    assert _login(zerodha) == REQUEST_TOKEN
    assert ("GET", "/connect/finish") in Fake.log


def test_without_a_finish_route_skip_session_still_hands_over(zerodha, monkeypatch):
    _no_proxy(monkeypatch)
    Fake.spa, Fake.has_finish = True, False
    assert _login(zerodha) == REQUEST_TOKEN


def test_when_no_route_hands_over_the_error_says_where_it_stopped_and_carries_no_secret(zerodha, monkeypatch):
    _no_proxy(monkeypatch)
    Fake.spa, Fake.has_finish = True, False
    Fake.authorised = False                                  # skip_session leads to the authorise page (200, no redirect to the app)
    with pytest.raises(KA.LoginError) as e:
        _login(zerodha)
    msg = str(e.value)
    assert "tried 3 routes" in msg and "HTTP 200" in msg and "authorise" in msg
    for secret in (PASSWORD, SECRET, REQUEST_TOKEN, "S1"):
        assert secret not in msg, secret                     # a status and a path only: no password, key, token or session id
