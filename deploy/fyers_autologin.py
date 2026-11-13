#!/usr/bin/env python3
"""Log in to Fyers by itself and get the day's access token, for market data only.

The owner's order of 13 Nov 2026 (docs/AUTONOMY.md, "More market-data brokers"): "I need to also enable them in the
auto login standpoint so that they can get the data easily", then "I have added fyers". The desk reads MCX and
currency prices from Fyers (docs/FEEDS.md) and nothing else.

Two ways in, cheapest first:
  1. **The refresh token** (`--refresh-in`, kept encrypted on the `fyers-token` branch by deploy/fyers-token.sh):
     POST /api/v3/validate-refresh-token with the app hash, the refresh token and the PIN. Fyers gives a refresh token
     with every full login; it lasts about 15 days. One call, no TOTP.
  2. **The TOTP login**, only when there is no refresh token or it was refused: the four calls Fyers' own web login
     makes (send the login OTP request for the client id, verify the TOTP code, verify the PIN, ask for an auth code
     for the app), then POST /api/v3/validate-authcode for the access and refresh tokens. Fyers does not document
     steps 1 to 4 for API users; community scripts have used them since 2023 and report that they change. When they
     do, this step fails, the run goes red and the watchdog says so: nothing else breaks.

The app hash is SHA-256 of "APP_ID:SECRET", as Fyers' own SDK computes it (fyers_apiv3 SessionModel.get_hash).

Writes {"access", "refresh", "how"} to `--out` (mode 0600). Never prints, logs or puts in an error any secret or token.
Lockout guard: the workflow lets only the first run of the IST day, on its first attempt, call this
(deploy/kite_login_gate.py with GATE_WORKFLOW=fyers-feed.yml), so a wrong PIN costs at most one refresh and one login a day.

Standard library only, on purpose: the process that holds the PIN and the TOTP key imports no third-party code (a test
checks). Run it with the system `python3 -I -S`. Exit codes: 0 done, or not configured (no secrets: the desk carries on
without Fyers); 1 the login failed.

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

API = "https://api-t1.fyers.in/api/v3"
VAGATOR = "https://api-t2.fyers.in/vagator/v2"
TOKEN_URLS = ("https://api-t1.fyers.in/api/v3/token", "https://api.fyers.in/api/v2/token")     # the auth-code step: v3 first, the older host that community scripts still use second
HOSTS = {"api-t1.fyers.in", "api-t2.fyers.in", "api.fyers.in"}                                  # the only hosts this file will send anything to
TIMEOUT = 20
UA = "Mozilla/5.0 (X11; Linux x86_64) quant-desk-fyers-data-login"
TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9._-]{20,4096}$")                                         # a JWT: only a token of this shape is ever written
AUTHORITY_ENDS = dt.date(2027, 12, 31)                                                          # docs/AUTONOMY.md: the owner's Fyers data exception ends on this date
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NEEDS = ("FYERS_APP_ID", "FYERS_SECRET_ID", "FYERS_REDIRECT_URI", "FYERS_CLIENT_ID", "FYERS_PIN", "FYERS_TOTP_SECRET")


class LoginError(Exception):
    """A failed step. Its message never carries a secret or a token."""


def totp(secret_b32: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    """RFC 6238 TOTP (HMAC-SHA1, 30 s, 6 digits), as Fyers' authenticator setup issues it."""
    s = "".join(secret_b32.split()).upper()
    s += "=" * (-len(s) % 8)
    key = base64.b32decode(s, casefold=True)
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def app_hash(app_id: str, secret: str) -> str:
    return hashlib.sha256(f"{app_id}:{secret}".encode()).hexdigest()


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the auth-code step answers 308 with the code in its body, and nothing here may be sent to another host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def post(url: str, body: dict, bearer: str | None = None) -> tuple[int, dict]:
    """POST JSON to a Fyers host; (HTTP status, JSON body or {}). A 3xx or 4xx answer is returned, not raised: Fyers puts its reason in the body."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname not in HOSTS:
        raise LoginError(f"refusing to send to {u.scheme}://{u.hostname}: not a Fyers API host")
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
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


_HIDE: set[str] = set()          # the secrets this run holds (filled by main): never repeated in a message, even if Fyers echoes one back


def _why(status: int, obj: dict) -> str:
    """Fyers' own code and message, cleaned: no secret this run holds, only plain words, no run of four or more digits (a PIN) and no long run of characters (a token)."""
    msg = str(obj.get("message") or "")
    for secret in sorted(_HIDE, key=len, reverse=True):
        if len(secret) >= 3:
            msg = msg.replace(secret, " ")
    msg = re.sub(r"[^A-Za-z0-9 ,.:'()-]", "", msg)
    msg = re.sub(r"\d{4,}", "", msg)
    msg = " ".join(w for w in msg.split() if len(w) <= 24)[:120]
    return f"HTTP {status}, code {obj.get('code', '?')}" + (f": {msg}" if msg else "")


def _ok(status: int, obj: dict) -> bool:
    return 200 <= status < 300 and obj.get("s") in ("ok", None) and obj.get("code", 200) in (200, 1)


def refresh(app_id: str, secret: str, refresh_token: str, pin: str, send=post) -> str:
    """Today's access token from a stored refresh token and the PIN."""
    status, obj = send(f"{API}/validate-refresh-token", {"grant_type": "refresh_token", "appIdHash": app_hash(app_id, secret),
                                                        "refresh_token": refresh_token, "pin": pin})
    tok = obj.get("access_token")
    if not (_ok(status, obj) and isinstance(tok, str) and TOKEN_SHAPE.match(tok)):
        raise LoginError("refresh token refused (" + _why(status, obj) + ")")
    return tok


def totp_login(app_id: str, secret: str, client_id: str, pin: str, totp_secret: str, redirect_uri: str, send=post,
               now=None, sleep=None) -> tuple[str, str]:
    """(access token, refresh token) from a full login: client id, TOTP, PIN, auth code."""
    now, sleep = now or time.time, sleep or time.sleep
    status, obj = send(f"{VAGATOR}/send_login_otp_v2", {"fy_id": _b64(client_id), "app_id": "2"})
    key = obj.get("request_key")
    if not (_ok(status, obj) and isinstance(key, str) and key):
        raise LoginError("step 1 (start the login for the client id) failed (" + _why(status, obj) + ")")

    left = 30 - now() % 30
    if left < 5:                                                     # a code about to expire would be refused: wait for the next window instead of spending a failed attempt
        sleep(left + 0.5)
    status, obj = send(f"{VAGATOR}/verify_otp", {"request_key": key, "otp": totp(totp_secret, now())})
    key = obj.get("request_key")
    if not (_ok(status, obj) and isinstance(key, str) and key):
        raise LoginError("step 2 (TOTP code) refused (" + _why(status, obj) + "); check FYERS_TOTP_SECRET")

    status, obj = send(f"{VAGATOR}/verify_pin_v2", {"request_key": key, "identity_type": "pin", "identifier": _b64(pin)})
    sess = (obj.get("data") or {}).get("access_token") if isinstance(obj.get("data"), dict) else None
    if not (_ok(status, obj) and isinstance(sess, str) and TOKEN_SHAPE.match(sess)):
        raise LoginError("step 3 (PIN) refused (" + _why(status, obj) + "); check FYERS_PIN")

    app, _, kind = app_id.partition("-")
    body = {"fyers_id": client_id, "app_id": app, "redirect_uri": redirect_uri, "appType": kind or "100", "code_challenge": "",
            "state": "quantdesk", "scope": "", "nonce": "", "response_type": "code", "create_cookie": True}
    code, last = None, ""
    for url in TOKEN_URLS:
        status, obj = send(url, body, bearer=sess)
        data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
        link = obj.get("Url") or data.get("Url") or data.get("url")                                # the redirect it would have sent, with auth_code in its query
        if isinstance(link, str):
            got = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query).get("auth_code")
            if got and TOKEN_SHAPE.match(got[0]):
                code = got[0]
                break
        last = _why(status, obj)
    if not code:
        raise LoginError("step 4 (auth code for the app) failed (" + last + "); check FYERS_APP_ID and FYERS_REDIRECT_URI")

    status, obj = send(f"{API}/validate-authcode", {"grant_type": "authorization_code", "appIdHash": app_hash(app_id, secret), "code": code})
    acc, ref = obj.get("access_token"), obj.get("refresh_token")
    if not (_ok(status, obj) and isinstance(acc, str) and TOKEN_SHAPE.match(acc)):
        raise LoginError("step 5 (exchange the auth code) failed (" + _why(status, obj) + "); check FYERS_SECRET_ID")
    return acc, (ref if isinstance(ref, str) and TOKEN_SHAPE.match(ref) else "")


def _write(path: str, obj: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(obj, fh)


def main(argv=None, env=None, send=post, today=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--refresh-in", help="a file with the stored refresh token (may be missing)")
    p.add_argument("--out", required=True, help="where the tokens go (mode 0600)")
    a = p.parse_args(argv)
    env = os.environ if env is None else env
    if (today or dt.datetime.now(IST).date()) >= AUTHORITY_ENDS:
        print("fyers login: the owner's Fyers data authority has ended (docs/AUTONOMY.md); not logging in")
        return 0
    missing = [k for k in NEEDS if not (env.get(k) or "").strip()]
    if missing:
        print(f"fyers login: not configured (missing {', '.join(missing)}); the desk carries on without Fyers")
        return 0
    app_id, secret, pin = env["FYERS_APP_ID"].strip(), env["FYERS_SECRET_ID"].strip(), env["FYERS_PIN"].strip()
    _HIDE.update(v.strip() for k in NEEDS if (v := env.get(k)) and k != "FYERS_REDIRECT_URI")
    try:
        totp(env["FYERS_TOTP_SECRET"], 0)
    except (ValueError, TypeError):
        print("::error::fyers login: FYERS_TOTP_SECRET is not a base32 key (use the key shown when TOTP was enabled, not the QR image)")
        return 1

    stored = ""
    if a.refresh_in and os.path.isfile(a.refresh_in):
        with open(a.refresh_in) as fh:
            stored = fh.read().strip()
    if stored and TOKEN_SHAPE.match(stored):
        try:
            acc = refresh(app_id, secret, stored, pin, send=send)
        except LoginError as e:
            print(f"fyers login: {e}; trying the full TOTP login")
        else:
            _write(a.out, {"access": acc, "refresh": stored, "how": "refresh"})
            print("fyers login: today's access token from the refresh token (not shown)")
            return 0
    try:
        acc, ref = totp_login(app_id, secret, env["FYERS_CLIENT_ID"].strip(), pin, env["FYERS_TOTP_SECRET"],
                              env["FYERS_REDIRECT_URI"].strip(), send=send)
    except LoginError as e:
        print(f"::error::fyers login: {e}")
        return 1
    _write(a.out, {"access": acc, "refresh": ref or stored, "how": "totp"})
    print("fyers login: logged in with TOTP; today's access token" + (" and a new refresh token" if ref else "") + " (not shown)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
