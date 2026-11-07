"""The paper runner's line to the relay (docs/LIVE.md): read the live board, drain the owner's order queue, post what happened, keep the account.

https only; a redirect is refused (urllib would send the Authorization header to the new host); an answer is capped at 4 MB; a failure carries the HTTP status or the
exception class and never the URL or a token. Two keys, as everywhere: the READ key reads the board, the INGEST key reads the queue and writes results and state.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TIMEOUT_S = 15.0
MAX_ANSWER = 4_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RelayError(RuntimeError):
    """A relay call that failed. The message is safe to log: a status or an exception class, nothing else."""


def base_of(live_url: str) -> str:
    u = str(live_url or "").strip().rstrip("/")
    if not u.startswith("https://"):
        raise ValueError("LIVE_URL must be an https URL")
    for tail in ("/live/ingest", "/live"):
        if u.endswith(tail):
            u = u[: -len(tail)]
    return u


class Relay:
    def __init__(self, live_url: str, read_token: str, ingest_token: str, opener=None, timeout: float = TIMEOUT_S):
        if not (read_token and ingest_token):
            raise ValueError("the runner needs both the READ and the INGEST token")
        self.base, self._read, self._ingest, self.timeout = base_of(live_url), read_token, ingest_token, timeout
        self._open = opener or urllib.request.build_opener(_NoRedirect).open

    @classmethod
    def from_env(cls) -> "Relay":
        e = lambda k: (os.environ.get(k) or "").strip()                    # noqa: E731
        if not (e("LIVE_URL") and e("LIVE_READ_TOKEN") and e("LIVE_INGEST_TOKEN")):
            raise ValueError("LIVE_URL, LIVE_READ_TOKEN and LIVE_INGEST_TOKEN must all be set")
        return cls(e("LIVE_URL"), e("LIVE_READ_TOKEN"), e("LIVE_INGEST_TOKEN"))

    def _call(self, method: str, path: str, token: str, body=None) -> dict:
        try:
            data = json.dumps(body, allow_nan=False).encode() if body is not None else None
        except (ValueError, TypeError, OverflowError):
            raise RelayError(f"{method} {path}: the body cannot be encoded") from None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": "quantdesk-paper"})
        try:
            with self._open(req, timeout=self.timeout) as r:
                if not 200 <= getattr(r, "status", 200) < 300:
                    raise RelayError(f"{method} {path}: HTTP {r.status}")
                raw = r.read(MAX_ANSWER + 1)
        except RelayError:
            raise
        except urllib.error.HTTPError as e:
            raise RelayError(f"{method} {path}: HTTP {e.code}") from None
        except Exception as e:                                             # noqa: BLE001
            raise RelayError(f"{method} {path}: {type(e).__name__}") from None
        if len(raw) > MAX_ANSWER:
            raise RelayError(f"{method} {path}: answer too large")
        try:
            out = json.loads(raw or b"{}")
        except (ValueError, RecursionError):
            raise RelayError(f"{method} {path}: not JSON") from None
        if not isinstance(out, dict):
            raise RelayError(f"{method} {path}: unexpected answer")
        return out

    def snapshot(self) -> dict:
        return self._call("GET", "/live/snapshot", self._read)

    def queue(self) -> dict:
        return self._call("GET", "/paper/queue", self._ingest)

    def post_result(self, result: dict) -> dict:
        return self._call("POST", "/paper/result", self._ingest, result)

    def put_state(self, summary: dict, account_text: str | None) -> dict:
        body = {"summary": summary}
        if account_text is not None:
            body["account"] = account_text
        return self._call("POST", "/paper/state", self._ingest, body)

    def get_state(self) -> dict:
        return self._call("GET", "/paper/state?full=1", self._ingest)
