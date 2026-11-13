#!/usr/bin/env python3
"""Log in to Angel One SmartAPI by itself and get the day's session token, for market data only.

The owner's order of 13 Nov 2026 (docs/AUTONOMY.md, "More market-data brokers"): the third broker carries currency,
with an automatic daily login; then "Added angel one api too". Angel One's documented login is the supported way to do
this, not a workaround: POST /rest/auth/angelbroking/user/v1/loginByPassword with the client code, the MPIN and a TOTP
code (smartapi-python 1.5.5, SmartConnect.generateSession). One call; the answer's `data.jwtToken` is the session.

Writes {"jwt"} to `--out` (mode 0600). The feed token and the refresh token in the same answer are not kept: the desk
polls the quote API and needs neither. Never prints, logs or puts in an error any secret or token (even one Angel One
echoes back). Lockout guard: the workflow lets only the first run of the IST day, on its first attempt, call this
(deploy/kite_login_gate.py with GATE_WORKFLOW=angel-feed.yml); its second job logs in only after the first job's login
worked. A wrong MPIN costs at most one failed login a day.

Standard library only, on purpose: the process that holds the MPIN and the TOTP key imports no third-party code (a test
checks). Run it with the system `python3 -I -S`. Exit codes: 0 done, or not configured (no secrets: the desk carries on
without Angel One); 1 the login failed.

Market data only: no order, position, holding, funds or profile endpoint is named anywhere in this file (a test checks).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = "https://apiconnect.angelone.in"
LOGIN = ROOT + "/rest/auth/angelbroking/user/v1/loginByPassword"
HOSTS = {"apiconnect.angelone.in"}
TIMEOUT = 20
TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9._-]{20,4096}$")
AUTHORITY_ENDS = dt.date(2027, 12, 31)                                       # docs/AUTONOMY.md: the owner's data exception for this broker ends on this date
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NEEDS = ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_MPIN", "ANGEL_TOTP_SECRET")
_HIDE: set[str] = set()


class LoginError(Exception):
    """A failed step. Its message never carries a secret or a token."""


def headers(api_key: str) -> dict:
    """The headers SmartAPI asks for on every call (SmartConnect.requestHeaders). Its own SDK sends fixed placeholder addresses; so does this."""
    return {"Content-Type": "application/json", "Accept": "application/json", "X-UserType": "USER", "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1", "X-MACAddress": "00:00:00:00:00:00", "X-PrivateKey": api_key}


def totp(secret_b32: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    """RFC 6238 TOTP (HMAC-SHA1, 30 s, 6 digits), as Angel One's authenticator setup issues it."""
    s = "".join(secret_b32.split()).upper()
    s += "=" * (-len(s) % 8)
    key = base64.b32decode(s, casefold=True)
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def post(url: str, body: dict, hdrs: dict) -> tuple[int, dict]:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname not in HOSTS:
        raise LoginError(f"refusing to send to {u.scheme}://{u.hostname}: not Angel One's API host")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=hdrs)
    try:
        with _opener.open(req, timeout=TIMEOUT) as r:
            status, raw = r.status, r.read(1 << 20)
    except urllib.error.HTTPError as e:
        status, raw = e.code, (e.read(1 << 20) if e.fp else b"")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LoginError(f"{u.hostname}{u.path}: no answer ({type(e).__name__})") from None
    try:
        obj = json.loads(raw or b"{}")
    except ValueError:
        obj = {}
    return status, obj if isinstance(obj, dict) else {}


def _why(status: int, obj: dict) -> str:
    """Angel One's own error code and message, cleaned of every secret this run holds, of digit runs and of anything token-long."""
    msg = str(obj.get("message") or "")
    for secret in sorted(_HIDE, key=len, reverse=True):
        if len(secret) >= 3:
            msg = msg.replace(secret, " ")
    msg = re.sub(r"[^A-Za-z0-9 ,.:'()-]", "", msg)
    msg = re.sub(r"\d{4,}", "", msg)
    msg = " ".join(w for w in msg.split() if len(w) <= 24)[:120]
    code = re.sub(r"[^A-Za-z0-9]", "", str(obj.get("errorcode") or ""))[:12]
    return f"HTTP {status}" + (f", {code}" if code else "") + (f": {msg}" if msg else "")


def login(api_key: str, client_code: str, mpin: str, totp_secret: str, send=post, now=None, sleep=None) -> str:
    """The session token (the JWT, without "Bearer ")."""
    now, sleep = now or time.time, sleep or time.sleep
    left = 30 - now() % 30
    if left < 5:                                                     # a code about to expire would be refused: wait for the next window instead of spending the day's attempt
        sleep(left + 0.5)
    status, obj = send(LOGIN, {"clientcode": client_code, "password": mpin, "totp": totp(totp_secret, now())}, headers(api_key))
    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    jwt = str(data.get("jwtToken") or "")
    jwt = jwt[7:] if jwt.startswith("Bearer ") else jwt
    if not (200 <= status < 300 and obj.get("status") is True and TOKEN_SHAPE.match(jwt)):
        raise LoginError(f"login refused ({_why(status, obj)}); Angel One's message above says which of ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_MPIN, ANGEL_TOTP_SECRET to check")
    return jwt


def main(argv=None, env=None, send=post, today=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", required=True, help="where the session token goes (mode 0600)")
    a = p.parse_args(argv)
    env = os.environ if env is None else env
    if (today or dt.datetime.now(IST).date()) >= AUTHORITY_ENDS:
        print("angel login: the owner's data authority for Angel One has ended (docs/AUTONOMY.md); not logging in")
        return 0
    missing = [k for k in NEEDS if not (env.get(k) or "").strip()]
    if missing:
        print(f"angel login: not configured (missing {', '.join(missing)}); the desk carries on without Angel One")
        return 0
    _HIDE.update(env[k].strip() for k in NEEDS)
    try:
        totp(env["ANGEL_TOTP_SECRET"], 0)
    except (ValueError, TypeError):
        print("::error::angel login: ANGEL_TOTP_SECRET is not a base32 key (use the text under the QR code, not the API secret)")
        return 1
    try:
        jwt = login(env["ANGEL_API_KEY"].strip(), env["ANGEL_CLIENT_CODE"].strip(), env["ANGEL_MPIN"].strip(), env["ANGEL_TOTP_SECRET"], send=send)
    except LoginError as e:
        print(f"::error::angel login: {e}")
        return 1
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"jwt": jwt}, fh)
    print("angel login: logged in; today's session token is ready (not shown)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
