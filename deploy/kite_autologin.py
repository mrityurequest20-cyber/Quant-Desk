#!/usr/bin/env python3
"""Log in to Kite by itself and get the day's single-use request_token, for market data only.

The owner asked for this on 6 Nov 2026: "I want the complete automated stuffs", then "Completely automate, don't worry
about any risk or limit." Kite's access token dies every morning, and the old routine needed the owner to log in by
hand and paste the request_token into the `Kite token` workflow; on 3 and 4 Nov nobody did, and no ticks were recorded.

What it does, with the owner's Zerodha user ID, password and TOTP key from GitHub secrets (never from chat, never in
the repository, never printed):
  1. opens Kite Connect's login page for the API key (the session Zerodha ties the login to);
  2. posts the user ID and password to Zerodha's login API;
  3. posts a TOTP code it computes itself (RFC 6238: SHA-1, 30 s, 6 digits; one retry with the next window);
  4. follows Zerodha's redirects until the one that points away from Zerodha carries `request_token=`, and stops there:
     the app's redirect URL is never contacted.
The request_token goes to a 0600 file. `quantdesk data kite-token` then exchanges it (API key and secret only) and the
token is used for market data only: no order, position, holding, margin or profile method is called anywhere.

Standard library only, on purpose: the process that holds the password imports no third-party code (a test checks).
Run it with the system `python3 -I -S` (no site-packages). Exit codes: 0 done or not configured (no secrets: the desk carries on without Kite),
1 the login failed (the workflow surfaces it, so the watchdog can alert).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.cookiejar
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

LOGIN_BASE = "https://kite.zerodha.com"
ZERODHA_HOSTS = {"kite.zerodha.com", "kite.trade"}      # redirects are followed only while they stay on these hosts
TIMEOUT = 20
MAX_HOPS = 10
UA = "Mozilla/5.0 (X11; Linux x86_64) quant-desk-kite-data-login"


class LoginError(Exception):
    """A failed step. Its message never carries a secret or a token."""


def totp(secret_b32: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    """RFC 6238 TOTP (HMAC-SHA1), as Zerodha's authenticator setup issues it."""
    key = base64.b32decode(_norm_b32(secret_b32), casefold=True)
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def _norm_b32(s: str) -> str:
    s = "".join(s.split()).upper()
    return s + "=" * (-len(s) % 8)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):   # we follow redirects ourselves, host by host
        return None


def _opener(jar):
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())


def _open(op, url, data=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data is not None else None,
                                 headers={"User-Agent": UA, "X-Kite-Version": "3"})
    try:
        resp = op.open(req, timeout=TIMEOUT)
        return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:                      # 3xx (not followed) and 4xx/5xx both land here
        return e.code, e.headers, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LoginError(f"could not reach {urllib.parse.urlsplit(url).hostname} ({type(e).__name__})") from None


def _follow(op, url, hosts, schemes=("https",)):
    """GET url and follow redirects while they stay on `hosts` over `schemes`. Returns (final_url, location_off_host or None)."""
    for _ in range(MAX_HOPS):
        code, headers, _ = _open(op, url)
        if code not in (301, 302, 303, 307, 308):
            return url, None
        nxt = urllib.parse.urljoin(url, headers.get("Location", ""))
        parts = urllib.parse.urlsplit(nxt)
        if parts.hostname not in hosts:
            return url, nxt                                   # the app's redirect URL: read it, never open it
        if parts.scheme not in schemes:                       # never send Zerodha's session cookie over plain HTTP
            raise LoginError("Zerodha redirected to a non-HTTPS address; refusing to follow it")
        url = nxt
    raise LoginError("too many redirects from Zerodha")


def _post_json(op, url, data, what):
    code, _, body = _open(op, url, data)
    try:
        js = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        raise LoginError(f"{what}: Zerodha answered {code} with no JSON") from None
    if js.get("status") != "success":
        msg = str(js.get("message") or js.get("error_type") or code)
        raise LoginError(f"{what}: {msg[:120].encode('ascii', 'replace').decode()}")
    return js.get("data") or {}


def request_token(api_key: str, user_id: str, password: str, totp_secret: str, *, base: str = LOGIN_BASE,
                  hosts=ZERODHA_HOSTS, schemes=("https",), clock=time.time) -> str:
    jar = http.cookiejar.CookieJar()
    op = _opener(jar)
    connect = (base + "/connect/login?v=3&api_key={key}").format(key=urllib.parse.quote(api_key))
    page, early = _follow(op, connect, hosts, schemes)
    if early and "request_token=" in early:                  # already logged in (a reused session)
        return _token_from(early)
    d = _post_json(op, base + "/api/login", {"user_id": user_id, "password": password}, "login")
    rid = d.get("request_id")
    if not rid:
        raise LoginError("login: Zerodha returned no request_id")
    if d.get("twofa_type") not in (None, "totp") and "totp" not in (d.get("twofa_types") or []):
        raise LoginError(f"login: the account's second factor is {d.get('twofa_type')!r}, not TOTP")
    last = None
    for shift in (0, 30):                                     # one retry in the next window, for a code that just expired
        try:
            _post_json(op, base + "/api/twofa", {"user_id": user_id, "request_id": rid, "twofa_value":
                       totp(totp_secret, clock() + shift), "twofa_type": "totp", "skip_totp": "true"}, "two-factor")
            break
        except LoginError as e:
            last = e
            if shift == 0:
                time.sleep(1)
    else:
        raise last
    _, loc = _follow(op, page, hosts, schemes)
    if not loc:
        raise LoginError("no redirect to the app after the login (is the Kite Connect app authorised for this "
                         "user? Log in once by hand through the app's login URL to authorise it)")
    return _token_from(loc)


def _token_from(loc: str) -> str:
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query)
    tok = (q.get("request_token") or [""])[0]
    if not tok.isalnum() or not 8 <= len(tok) <= 64:
        raise LoginError("the redirect carried no request_token of the expected shape")
    return tok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="file to write the request_token to (0600)")
    a = ap.parse_args(argv)
    env = {k: os.environ.get(k, "").strip() for k in ("KITE_DATA_KEY", "KITE_USER_ID", "KITE_PASSWORD", "KITE_TOTP_SECRET")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        print(f"kite login: not configured ({', '.join(missing)} not set); the desk carries on without Kite")
        return 0
    try:
        base64.b32decode(_norm_b32(env["KITE_TOTP_SECRET"]), casefold=True)
    except ValueError:
        print("::error::kite login: KITE_TOTP_SECRET is not a base32 key (it is the key Zerodha shows when TOTP is set up)")
        return 1
    try:
        tok = request_token(env["KITE_DATA_KEY"], env["KITE_USER_ID"], env["KITE_PASSWORD"], env["KITE_TOTP_SECRET"])
    except LoginError as e:
        print(f"::error::kite login failed: {e}")
        return 1
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{tok}")
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(tok)
    print("kite login: request token obtained (not shown)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
