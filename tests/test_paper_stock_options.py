"""Stock options on the paper desk (owner's order, 13 Nov 2026) and the session review.

Stock options go through the same real gate, broker and account as index options, with two rules of their own: the lot is the contract's (NSE revises a stock's lot from a
given expiry), and a stock option is sold from 15:20 IST on the trading day BEFORE its expiry, because NSE settles it by delivery of the shares. The session review is worked
out from the account's own ledger and travels in the state the runner keeps on the private relay (never to the public repository)."""
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.markets import sessions as MK
from quantdesk.paper import review as RV
from quantdesk.paper import runner as R
from quantdesk.paper.account import Account
from quantdesk.paper.risk import KillSwitch, RiskGate

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
MON = dt.datetime(2026, 11, 9, 10, 0, tzinfo=IST)            # a trading Monday
EVE = dt.date(2026, 11, 20)                                  # Friday: the last trading day before the 23 Nov 2026 stock expiry
REL = "RELIANCE23NOV261340CE"
NIFTY = "NIFTY24NOV2626000CE"                                # a cash-settled index option expiring after it
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


@pytest.fixture()
def rn(cfg, tmp_path):
    return R.Runner(cfg, Account(500_000), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL")), kill_file=tmp_path / "KILL")


def book(bid, ask):
    return dict(bid=bid, ask=ask, bid_qty=5000, ask_qty=5000, ltp=(bid + ask) / 2, age_s=2.0)


def snap(now, **q):
    quotes = {REL: book(20.0, 20.5), NIFTY: book(60.0, 61.0), "RELIANCE": dict(ltp=1338.0, age_s=2.0), "NIFTY": dict(ltp=25900.0, age_s=2.0)}
    quotes.update(q)
    return {"now": int(now.timestamp() * 1000), "quotes": quotes}


def order(now, oid="ord-0001", **kw):
    o = dict(id=oid, side="buy", symbol=REL, lots=1, strategy="results run-up", thesis="results next week; implied volatility still below its usual pre-results level",
             queued_at=int(now.timestamp() * 1000) - 3000)
    o.update(kw)
    return o


def step(rn, now, orders=(), **q):
    return rn.step(snap(now, **q), list(orders), False, now.astimezone(dt.timezone.utc))


# ---- the contract ---------------------------------------------------------------------------------------------------------------------
def test_the_config_lists_the_twenty_stocks_with_a_lot_for_every_listed_expiry(cfg):
    lots = R.stock_lots(cfg)
    watch = [s.upper() for s in cfg.get("desk.watchlist")["stocks"]]
    assert sorted(lots) == sorted(watch) and len(lots) == 20                                         # the paper desk trades exactly the watchlist's stocks
    assert set(watch) <= set(cfg.get("paper.underlyings")["nse_fo"])                                 # and the gate's mislabel guard knows them
    for u, by in lots.items():
        assert len(by) == 3 and all(isinstance(v, int) and v > 0 for v in by.values()), u
    assert lots["HDFCBANK"][dt.date(2026, 11, 23)] == 650 and lots["HDFCBANK"][dt.date(2027, 1, 25)] == 750     # NSE revised it from January: the lot is the contract's


def test_a_stock_contract_takes_its_own_expirys_lot_and_an_unlisted_expiry_is_refused(cfg):
    und, lots = set(cfg.get("paper.underlyings")["nse_fo"]), {"NIFTY": 65, **R.stock_lots(cfg)}
    assert R.parse_contract("HDFCBANK23NOV26820CE", und, lots)[0].lot_size == 650
    assert R.parse_contract("HDFCBANK25JAN27820CE", und, lots)[0].lot_size == 750
    assert R.parse_contract("M&M23NOV263400PE", und, lots)[0].underlying == "M&M"
    assert R.parse_contract("BAJAJ-AUTO23NOV2611000CE", und, lots)[0].lot_size == 75
    inst, why = R.parse_contract("HDFCBANK30MAR27820CE", und, lots)
    assert inst is None and "no verified lot size for the 30 Mar 2027 expiry" in why                   # refused, never guessed
    assert R.parse_contract("IDEA23NOV2610CE", und, lots)[0] is None                                    # a stock not on the list


def test_a_bad_lot_table_entry_is_left_out_not_trusted(cfg):
    bad = {"paper.stock_options.lots": {"AAA": {"2026-11-23": 0}, "BBB": {"2026-02-30": 10}, "CCC": {"2026-11-23": True}, "DDD": "x", "EEE": {"2026-11-23": 10.5}}}
    real = cfg.get
    cfg.get = lambda k, d=None: bad[k] if k in bad else real(k, d)
    assert R.stock_lots(cfg) == {}


# ---- buying and the day before expiry ---------------------------------------------------------------------------------------------------
def test_a_stock_option_buys_one_lot_of_its_contract_through_the_real_gate(rn):
    res = step(rn, MON, [order(MON)])["results"][0]
    assert res["status"] == "filled" and res["fill"]["qty"] == 500 and res["fill"]["price"] == 20.5 and res["fill"]["fees"] > 0


def test_on_the_day_before_expiry_a_stock_option_is_bought_until_1520_and_not_after(rn):
    before, after = dt.datetime.combine(EVE, dt.time(15, 0), IST), dt.datetime.combine(EVE, dt.time(15, 21), IST)
    assert step(rn, before, [order(before)])["results"][0]["status"] == "filled"
    res = step(rn, after, [order(after, oid="ord-0002")])["results"][0]
    assert res["status"] == "refused" and "delivery of the shares" in res["reasons"][0]
    res = step(rn, after, [order(after, oid="ord-0003", symbol=NIFTY)])["results"][0]               # a cash-settled index option is not touched by the stock rule
    assert res["status"] == "filled"


def test_a_held_stock_option_is_sold_at_1520_the_day_before_expiry_and_an_index_option_is_kept(rn):
    step(rn, MON, [order(MON), order(MON, oid="ord-0002", symbol=NIFTY)])
    assert set(rn.account.positions) == {REL, NIFTY}
    rep = step(rn, dt.datetime.combine(EVE, dt.time(15, 10), IST))
    assert set(rn.account.positions) == {REL, NIFTY} and not rep["forced"]                          # not before 15:20
    rep = step(rn, dt.datetime.combine(EVE, dt.time(15, 21), IST))
    assert set(rn.account.positions) == {NIFTY}                                                      # the stock option went at the bid; the index option stays to its own expiry
    assert any(f["action"] == "sell expiring" for f in rep["forced"])
    assert rn.account.ledger[-1]["kind"] == "sell" and rn.account.ledger[-1]["symbol"] == REL and rn.account.ledger[-1]["price"] == 20.0


def test_an_expired_position_is_not_retried_every_cycle(rn):
    step(rn, MON, [order(MON)])
    later = dt.datetime(2026, 11, 25, 10, 0, tzinfo=IST)                                              # past its expiry with nothing done: it is "stuck", reported, not re-sold each cycle
    assert not step(rn, later)["forced"]


# ---- the session review ---------------------------------------------------------------------------------------------------------------
def test_the_review_counts_what_the_ledger_says_and_today_carries_the_whole_days_result(rn):
    t0, t1 = MON, MON + dt.timedelta(minutes=30)
    step(rn, t0, [order(t0)])
    step(rn, t1, [order(t1, oid="ord-0002", side="sell", lots="all", strategy=None, thesis=None)], **{REL: book(24.0, 24.5)})
    rv = rn.summary(snap(t1, **{REL: book(24.0, 24.5)}), t1.astimezone(dt.timezone.utc))["reviews"]
    today = rv[0]
    buy, sell = rn.account.ledger[0], rn.account.ledger[1]
    assert today["today"] is True and today["day"] == "2026-11-09" and today["closes"] == 1 and today["wins"] == 1 and today["losses"] == 0
    assert today["realized"] == pytest.approx((24.0 - 20.5) * 500) and today["fees"] == pytest.approx(buy["fees"] + sell["fees"], abs=0.01)
    assert today["net"] == pytest.approx(today["realized"] - today["fees"]) and today["opened"] == [REL] and today["still_open"] == []
    assert today["equity_change"] == pytest.approx(today["net"], abs=0.01)                            # nothing held: the whole day is the closed trade after fees
    assert [f["t"] for f in today["fills"]] == ["10:00", "10:30"]                                      # IST clock times, not the ledger's UTC
    assert [f["kind"] for f in today["fills"]] == ["buy", "sell"] and today["fills"][0]["thesis"].startswith("results next week") and "\x1f" not in json.dumps(today)


def test_an_earlier_day_shows_closed_trades_after_fees_only_and_today_is_always_there(rn):
    step(rn, MON, [order(MON)])
    t1 = MON + dt.timedelta(minutes=5)
    step(rn, t1, [order(t1, oid="ord-0002", side="sell", lots="all", strategy=None, thesis=None)])
    wed = dt.datetime(2026, 11, 11, 11, 0, tzinfo=IST)
    rv = RV.session_reviews(rn.account, wed, 499_000.0, R.visible)
    assert [r["day"] for r in rv] == ["2026-11-11", "2026-11-09"] and rv[0]["fills"] == [] and rv[0]["today"] is True
    assert "equity_change" not in rv[1] and rv[1]["closes"] == 1 and rv[1]["losses"] == 1                # sold at the bid it was bought above: a loss, shown as such


def test_the_review_stays_inside_the_relays_cap_however_busy_the_account(rn):
    t = MON
    for i in range(160):                                                                              # 320 fills in a day
        t = t + dt.timedelta(seconds=30)
        step(rn, t, [order(t, oid=f"ord-{2 * i:04d}")])
        step(rn, t, [order(t, oid=f"ord-{2 * i + 1:04d}", side="sell", lots="all", strategy=None, thesis=None)])
    s = rn.summary(snap(t), t.astimezone(dt.timezone.utc))
    n = len([r for r in rn.account.ledger if r["kind"] in ("buy", "sell")])                         # the gate stops a losing day partway: count what it let through
    assert n > RV.MAX_FILLS and s["reviews"][0]["n_fills"] == n and len(s["reviews"][0]["fills"]) == RV.MAX_FILLS and len(json.dumps(s["reviews"])) <= RV.MAX_CHARS
    assert len(json.dumps(s)) < 60000                                                                  # the relay's MAX_SUMMARY (deploy/cloudflare/paper.js)


# ---- the app and the watchdog -----------------------------------------------------------------------------------------------------------
def test_the_published_page_prices_a_stock_option_with_its_own_expirys_lot(cfg):
    from quantdesk.web.export_site import trade_config
    inst = trade_config(cfg)["inst"]
    assert inst["RELIANCE"]["lots"] == {"23NOV26": 500, "29DEC26": 500, "25JAN27": 500} and inst["RELIANCE"]["physical"] is True and inst["RELIANCE"]["step"] == 10.0
    assert inst["HDFCBANK"]["lots"]["25JAN27"] == 750 and inst["ITC"]["step"] == 2.5
    assert inst["NIFTY"] == {"lot": 65, "step": 50.0}                                                    # the indices are unchanged
    app = (ROOT / "quantdesk/web/static/app/app.js").read_text()
    assert "inst.lots[spec.exp]" in app and "exp: o.e" in app and "exp: B.exp" in app                    # every pricing call says which expiry it is pricing


def test_the_positions_tab_shows_the_review_and_the_watchdog_pushes_it_by_push_only():
    app = (ROOT / "quantdesk/web/static/app/app.js").read_text()
    assert "function ppReview(reviews)" in app and "ppReview(sm.reviews)" in app and "innerHTML" not in app
    wd = (ROOT / "deploy/cloudflare/watchdog.js").read_text()
    w18 = wd[wd.index("async function w18Review"):wd.index("export const SLOTS")]
    assert w18.count("pushOnly: true") == 2 and '"https://live/paper/state"' in w18                       # never the email path: that opens an issue on a PUBLIC repository
    assert '{ at: "15:50", days: "trading", run: w18Review, check: "W18" }' in wd


@needs_node
def test_the_push_line_says_the_day_in_one_line(tmp_path):
    for f in ("watchdog.js", "live.js", "kotak.js", "series.js", "paper.js", "news.js", "candles.js", "routes.js"):
        shutil.copyfile(ROOT / "deploy/cloudflare" / f, tmp_path / f)
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "t.mjs").write_text("""import { reviewLine } from './watchdog.js';
console.log(JSON.stringify([
  reviewLine({ equity_change: 4240.4, net: 3900, closes: 3, wins: 2, losses: 1, best: 2500, worst: -800, fees: 212, opened: ["A", "B"], still_open: ["B"], events: [] }),
  reviewLine({ net: -1200, closes: 0, fees: 40, opened: [], events: ["15:02 The daily loss limit was hit"] }),
  reviewLine(null)]));""")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    a, b, c = json.loads(r.stdout)
    assert a.startswith("+Rs 4,240 on the day (all in). 3 closed (2 won, 1 lost), best +Rs 2,500, worst -Rs 800; 2 opened, 1 still held; fees Rs 212.")
    assert b.startswith("-Rs 1,200 from closed trades after fees. nothing closed;") and "1 brake event(s)" in b and c is None
