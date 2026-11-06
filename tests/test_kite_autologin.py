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
            if logged_in:
                return self._send(302, headers=[("Location", "/connect/finish?sess_id=S1")])
            return self._send(200, b"<html>login</html>")
        if u.path == "/connect/finish":
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
    Fake.authorised, Fake.log = True, []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _login(base, **kw):
    args = dict(api_key=KEY, user_id=USER, password=PASSWORD, totp_secret=SECRET)
    args.update(kw)
    return KA.request_token(args["api_key"], args["user_id"], args["password"], args["totp_secret"], base=base, hosts={"127.0.0.1"})


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
    assert 'python3 -I "$here/kite_autologin.py"' in sh                    # isolated mode: no PYTHONPATH, no user site, no cwd on the path


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
