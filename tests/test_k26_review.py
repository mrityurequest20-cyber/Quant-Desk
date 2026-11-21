"""Audit K-26 (AIJ-01, HIGH, latent): the session review replayed fills without their stop, the ledger refuses a futures entry with no stop, and the error was
swallowed into "no reviews". So from the first futures fill the review panel and W18's evening push were gone for good, and W18 said "did not run" every
evening. Now the replay passes the stop and target as the account's own replay does, and a review that cannot be worked out is said (review_error), not hidden.
PAPER MONEY ONLY."""
from __future__ import annotations

import datetime as dt

from quantdesk.core.types import Instrument
from quantdesk.markets import sessions as MK
from quantdesk.paper import review as RV
from quantdesk.paper import runner as R
from quantdesk.paper.account import Account
from tests.test_watchdog import HEAD, LIVE_HEAD, NODE, _node

IST = MK.IST


def booked():
    a = Account(500_000.0)
    nifty = Instrument.option("NIFTY", dt.date(2026, 11, 24), 24500, "CE", 65)
    a.apply_fill("buy", nifty, "nse_fo", 65, 100.0, 20.0, "2026-11-20T04:00:00+00:00", "s", "a held call bought on the day's plan")
    fut = Instrument.future("CRUDEOILM", 10)
    a.apply_fill("buy", fut, "mcx", 10, 5800.0, 30.0, "2026-11-20T06:00:00+00:00", "s", "crude holding above the overnight range", stop=5750.0, target=5900.0)
    return a


def test_a_ledger_with_a_futures_fill_still_gives_todays_review_with_that_fill():
    a = booked()
    now = dt.datetime(2026, 11, 20, 18, 0, tzinfo=IST)
    rv = RV.session_reviews(a, now, 500_000.0, R.visible)                       # was: ValueError "a futures entry needs a stop", swallowed into []
    today = [d for d in rv if d.get("day") == "2026-11-20"]
    assert today and {f["symbol"] for f in today[0]["fills"]} >= {"CRUDEOILM-FUT"}
    assert Account.from_dict(a.to_dict()).verify_ledger()                       # the account's own replay agreed all along


def test_a_review_that_cannot_be_worked_out_is_said_not_hidden(monkeypatch):
    class Rn(R.Runner):
        def __init__(self):
            self.account = booked()
    rn = Rn()
    monkeypatch.setattr(RV, "session_reviews", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    assert rn._reviews(dt.datetime(2026, 11, 20, 18, 0, tzinfo=IST), 500_000.0) == [] and rn._review_err == "ValueError"
    monkeypatch.setattr(RV, "session_reviews", lambda *a, **k: [{"day": "2026-11-20"}])
    assert rn._reviews(dt.datetime(2026, 11, 20, 18, 0, tzinfo=IST), 500_000.0) and rn._review_err is None
    src = (R.__file__ and open(R.__file__, encoding="utf-8").read())
    assert '"review_error": self._review_err' in src


@NODE
def test_w18_says_the_review_failed_instead_of_did_not_run(tmp_path):
    out = _node(tmp_path, HEAD + LIVE_HEAD + r"""
const D = "2026-11-23";
const paper = (summary) => ({ idFromName: () => "b", get: () => ({ fetch: async () => new Response(JSON.stringify({ summary })) }) });
const w18 = async (summary) => (await at(D + "T15:50:00", env({ ...secrets, LIVE: paper(summary) }), {})).results.filter((x) => x.check === "W18").flatMap((x) => x.alerts);
out.err = (await w18({ reviews: [], review_error: "ValueError" })).map((a) => [a.sev, a.title, a.pushOnly]);
out.none = (await w18({ reviews: [] })).map((a) => [a.sev, a.title]);
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["err"] == [["P2", "Session review 2026-11-23: could not be worked out", True]]
    assert out["none"] == [["INFO", "Session review 2026-11-23: none"]]
