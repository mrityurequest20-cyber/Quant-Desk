"""Reconciling fills the relay never received (quantdesk/paperlink/reconcile.py, audit K-01): priced by the paper broker's own rules from recorded quotes,
appended (never rewriting a row), all or nothing, once only; and its workflow (.github/workflows/paper-reconcile.yml). PAPER MONEY ONLY."""
from __future__ import annotations

import datetime as dt
import io
import json
import re
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from quantdesk.config import Config
from quantdesk.paper import slippage as SL
from quantdesk.paper.account import Account
from quantdesk.paper.risk import Quote
from quantdesk.paper.runner import Runner, account_json, choose_state, load_account, parse_contract
from quantdesk.paperlink import reconcile as RC

ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc
T0 = dt.datetime(2026, 11, 20, 4, 0, tzinfo=UTC)
LONG, SHORTED, NEW = "NIFTY24NOV2626000PE", "NIFTY24NOV2626100CE", "NIFTY24NOV2626200CE"


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


def inst(cfg, sym):
    a = Account(1.0)
    rn = Runner(cfg, a)
    i, why = parse_contract(sym, rn.und, rn.lots, frozenset(rn.seg_of))
    assert i is not None, why
    return i


def account(cfg):
    """An account holding one long put (two rows: the buy, then a buy of another contract that is then sold), so the ledger has a known end."""
    a = Account(500000.0)
    a.apply_fill("buy", inst(cfg, LONG), "nse_fo", 65, 100.0, 24.0, T0.isoformat(), "test", "a long put held for the reconciliation test", None)
    a.apply_fill("buy", inst(cfg, NEW), "nse_fo", 65, 50.0, 24.0, (T0 + dt.timedelta(minutes=1)).isoformat(), "test", "bought and then sold, for the ledger's end", None)
    a.apply_fill("sell", inst(cfg, NEW), "nse_fo", 65, 55.0, 24.0, (T0 + dt.timedelta(minutes=2)).isoformat(), "test", "sold: the ledger's last row", None)
    return a


def row(sym, at, bid, ask, bq=1000.0, aq=1000.0, source="kotak"):
    strike, right = float(sym[-7:-2]), sym[-2:]
    c = right.lower()
    return {"ts": at, "underlying": "NIFTY", "expiry": "2026-11-24", "strike": strike, "source": source,
            f"{c}_bid": bid, f"{c}_ask": ask, f"{c}_bidq": bq, f"{c}_askq": aq}


def plan(a, events, age=300):
    return {"id": "test", "expect": {"ledger_len": len(a.ledger), "last_ts": a.ledger[-1]["ts"]}, "max_quote_age_s": age, "events": events}


def check(p, tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(p), encoding="utf-8")
    return RC.load_plan(f)


AT = T0 + dt.timedelta(minutes=10)


def test_a_sale_is_priced_and_charged_exactly_as_the_paper_broker_would(cfg):
    """The same quote through the real broker (on a copy of the account) and through the reconciler: the same price, the same fees."""
    a, b = account(cfg), account(cfg)
    q = Quote(80.0, 80.5, AT, 65.0, 500.0)                                                  # 65 units against 65 shown: the gate allows it, at the most impact
    _, real = Runner(cfg, b).broker.sell(LONG, 65, q, AT, "exit")
    book = RC.QuoteBook([row(LONG, AT - dt.timedelta(seconds=5), 80.0, 80.5, bq=65.0, aq=500.0)])
    booked = RC.reconcile(cfg, a, plan(a, [{"at": AT.isoformat(), "side": "sell", "symbol": LONG}]), book, "2026-11-21")
    assert real is not None and booked[0]["price"] == pytest.approx(real["price"]) and booked[0]["fees"] == pytest.approx(real["fees"])
    assert a.ledger[-1]["price"] == pytest.approx(real["price"]) and a.cash == pytest.approx(b.cash)


def test_a_buy_and_a_sale_to_open_follow_the_broker_rules_with_impact(cfg):
    a = account(cfg)
    book = RC.QuoteBook([row(NEW, AT, 50.0, 50.5, bq=65.0, aq=650.0), row(SHORTED, AT, 40.0, 40.4, bq=65.0, aq=1000.0)])
    ev = [{"at": AT.isoformat(), "side": "sto", "symbol": SHORTED, "lots": 1, "strategy": "AUTO v2 test", "thesis": "a sold leg for the reconciliation test"},
          {"at": AT.isoformat(), "side": "buy", "symbol": NEW, "lots": 2, "strategy": "AUTO v2 test", "thesis": "bought legs for the reconciliation test"}]
    booked = RC.reconcile(cfg, a, plan(a, ev), book, "2026-11-21")
    assert booked[0]["price"] == pytest.approx(40.0 - SL.impact_ticks(65, 65.0) * SL.TICK)          # a sale: the bid less the impact
    assert booked[1]["price"] == pytest.approx(50.5 + SL.impact_ticks(130, 650.0) * SL.TICK)        # a buy: the offer plus it
    assert a.positions[SHORTED].qty == -65 and a.positions[NEW].qty == 130
    assert all("[reconstructed 2026-11-21" in r["thesis"] and AT.isoformat() in r["thesis"] for r in a.ledger[-2:])     # an opening is tagged too


def test_rows_are_appended_tagged_and_the_ledger_still_verifies_and_continues_the_old_one(cfg):
    a = account(cfg)
    old = load_account(account_json(a))
    book = RC.QuoteBook([row(LONG, AT, 90.0, 90.5)])
    RC.reconcile(cfg, a, plan(a, [{"at": AT.isoformat(), "side": "sell", "symbol": LONG, "why": "AUTO v2 exit: trailed"}]), book, "2026-11-21")
    assert a.verify_ledger() and len(a.ledger) == len(old.ledger) + 1
    assert a.ledger[:len(old.ledger)] == old.ledger                                          # no existing row changed
    chosen, _ = choose_state(load_account(account_json(a)), old)
    assert chosen is not None and len(chosen.ledger) == len(a.ledger)                        # the relay's own rule accepts it as a continuation
    t = a.ledger[-1]["thesis"]
    assert "[reconstructed 2026-11-21" in t and "audit K-01" in t and AT.isoformat() in t and "kotak quote" in t


def test_it_runs_once_only_a_second_run_is_refused_and_changes_nothing(cfg):
    a = account(cfg)
    p = plan(a, [{"at": AT.isoformat(), "side": "sell", "symbol": LONG}])
    book = RC.QuoteBook([row(LONG, AT, 90.0, 90.5)])
    RC.reconcile(cfg, a, p, book, "2026-11-21")
    n = len(a.ledger)
    with pytest.raises(RC.PlanError, match="not the one this plan continues"):
        RC.reconcile(cfg, a, p, book, "2026-11-21")
    assert len(a.ledger) == n


def test_the_ledger_length_must_match_even_when_the_last_row_time_does(cfg):
    a = account(cfg)
    p = plan(a, [{"at": AT.isoformat(), "side": "sell", "symbol": LONG}])
    p["expect"]["ledger_len"] += 1                                                         # same last time, another length: a different ledger
    with pytest.raises(RC.PlanError, match="not the one this plan continues"):
        RC.reconcile(cfg, a, p, RC.QuoteBook([row(LONG, AT, 90.0, 90.5)]), "2026-11-21")


@pytest.mark.parametrize("quote, why", [
    (None, "no recorded quote"),
    ((dt.timedelta(seconds=400), 90.0, 90.5), "s old"),
    ((dt.timedelta(seconds=1), 91.0, 90.5), "crossed"),
    ((dt.timedelta(seconds=1), None, 90.5), "crossed"),
])
def test_a_missing_stale_crossed_or_empty_quote_is_refused_and_nothing_is_booked(cfg, quote, why):
    a = account(cfg)
    n, cash = len(a.ledger), a.cash
    rows = [] if quote is None else [row(LONG, AT - quote[0], quote[1], quote[2])]
    ev = [{"at": AT.isoformat(), "side": "sell", "symbol": LONG}]
    with pytest.raises(RC.PlanError, match=why):
        RC.reconcile(cfg, a, plan(a, ev), RC.QuoteBook(rows), "2026-11-21")
    assert len(a.ledger) == n and a.cash == cash


def test_all_or_nothing_a_failure_part_way_undoes_every_row_already_booked(cfg):
    a = account(cfg)
    n, cash = len(a.ledger), a.cash
    ev = [{"at": AT.isoformat(), "side": "sell", "symbol": LONG},
          {"at": AT.isoformat(), "side": "sell", "symbol": NEW}]                                   # not held
    with pytest.raises(RC.PlanError, match="no long position"):
        RC.reconcile(cfg, a, plan(a, ev), RC.QuoteBook([row(LONG, AT, 90.0, 90.5), row(NEW, AT, 1.0, 1.1)]), "2026-11-21")
    assert len(a.ledger) == n and a.cash == cash and LONG in a.positions


def test_a_close_must_match_the_side_held(cfg):
    a = account(cfg)
    with pytest.raises(RC.PlanError, match="no short"):
        RC.reconcile(cfg, a, plan(a, [{"at": AT.isoformat(), "side": "btc", "symbol": LONG}]), RC.QuoteBook([row(LONG, AT, 90.0, 90.5)]), "2026-11-21")


@pytest.mark.parametrize("mutate, why", [
    (lambda p: p.pop("expect"), "expect"),
    (lambda p: p.update(max_quote_age_s=10_000), "max_quote_age_s"),
    (lambda p: p["events"][0].update(book_at="2020-01-01T00:00:00Z"), "before the ledger"),
    (lambda p: p["events"][0].update(side="short"), "needs side"),
    (lambda p: p["events"].append({"at": AT.isoformat(), "side": "buy", "symbol": NEW, "lots": 1, "strategy": "s", "thesis": "short"}), "thesis"),
    (lambda p: p["events"].append({"at": AT.isoformat(), "side": "sell", "symbol": LONG, "lots": 1}), "whole position"),
    (lambda p: p["events"].append({"at": AT.isoformat(), "side": "buy", "symbol": NEW, "lots": 3, "strategy": "s", "thesis": "bigger than AUTO v2 ever opens"}), "1 to 2"),
])
def test_a_malformed_plan_is_refused_before_anything_runs(cfg, tmp_path, mutate, why):
    a = account(cfg)
    p = plan(a, [{"at": AT.isoformat(), "side": "sell", "symbol": LONG}])
    mutate(p)
    with pytest.raises(RC.PlanError, match=why):
        check(p, tmp_path)


def test_the_committed_plan_for_20_nov_is_well_formed_and_holds_no_price(cfg):
    p = RC.load_plan(ROOT / "docs" / "reconcile" / "2026-11-20.json")
    assert p["expect"] == {"ledger_len": 15, "last_ts": "2026-11-20T06:25:06.625000+00:00"} and len(p["events"]) == 12
    text = (ROOT / "docs" / "reconcile" / "2026-11-20.json").read_text(encoding="utf-8")
    assert not re.search(r'"(price|fees|pnl|realized|cash|avg|equity)"', text)                # what happened, never what it cost: this repository is public
    rn = Runner(cfg, Account(1.0))
    for e in p["events"]:
        assert parse_contract(e["symbol"], rn.und, rn.lots, frozenset(rn.seg_of))[0] is not None, e["symbol"]
    assert all(re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+\.parquet", f) for f in p["chain_files"])
    left_open = {}
    for e in p["events"]:
        if e["side"] in ("buy", "sto"):
            left_open[e["symbol"]] = e
        else:
            left_open.pop(e["symbol"], None)
    assert sorted(left_open) == ["MIDCPNIFTY23NOV2614200PE"]
    for e in left_open.values():                     # an overnight AUTO v2 opening the plan leaves open carries its volatility stop (p<spot> d<sd>), as auto2 writes it, so vol_stop can act
        if e["strategy"].split()[2].endswith(".o"):
            assert re.search(r" p\d+(\.\d+)? d\d{1,6}$", e["strategy"]) and len(e["strategy"]) <= 60, e["strategy"]
    assert "owner's written decision" in p["why"]                                              # applying is the owner's act



def test_a_close_books_the_contract_held_priced_and_charged_as_the_broker_would(cfg):
    """A position held under an older lot size (as after an exchange's lot change): the close sells what is held, at the broker's own price and fees, and the row
    names the held contract, never a fresh parse of the symbol."""
    import dataclasses
    old_lot = dataclasses.replace(inst(cfg, LONG), lot_size=75)
    a, b = Account(500000.0), Account(500000.0)
    for x in (a, b):
        x.apply_fill("buy", old_lot, "nse_fo", 75, 100.0, 24.0, T0.isoformat(), "test", "a long put bought under the older lot size", None)
    q = Quote(80.0, 80.5, AT, 75.0, 500.0)
    _, real = Runner(cfg, b).broker.sell(LONG, 75, q, AT, "exit")
    book = RC.QuoteBook([row(LONG, AT - dt.timedelta(seconds=5), 80.0, 80.5, bq=75.0, aq=500.0)])
    booked = RC.reconcile(cfg, a, plan(a, [{"at": AT.isoformat(), "side": "sell", "symbol": LONG}]), book, "2026-11-21")
    assert real is not None and booked[0]["qty"] == 75 and booked[0]["price"] == pytest.approx(real["price"]) and booked[0]["fees"] == pytest.approx(real["fees"])
    assert a.ledger[-1]["instrument"] == old_lot.to_dict() == b.ledger[-1]["instrument"] and not a.positions and a.cash == pytest.approx(b.cash)
    assert a.verify_ledger()


def test_a_failed_send_says_how_to_tell_whether_it_went_through_and_prints_no_price(cfg, tmp_path, monkeypatch):
    from quantdesk.paperlink import cli
    from quantdesk.paperlink.relay import RelayError
    a = account(cfg)
    pf = tmp_path / "plan.json"
    pf.write_text(json.dumps(plan(a, [{"at": AT.isoformat(), "side": "sell", "symbol": LONG}])), encoding="utf-8")
    monkeypatch.setattr(RC.QuoteBook, "from_parquet", classmethod(lambda c, paths: c([row(LONG, AT, 90.0, 90.5)])))

    class Down:
        def get_state(self):
            return {"account": account_json(a)}

        def snapshot(self):
            return {"now": int(AT.timestamp() * 1000), "quotes": {}}

        def put_state(self, summary, text):
            raise RelayError("POST /paper/state: HTTP 503")
    monkeypatch.setattr("quantdesk.paperlink.relay.Relay.from_env", classmethod(lambda c: Down()))
    out = io.StringIO()
    with pytest.raises(SystemExit) as e, redirect_stdout(out):
        cli.cmd_reconcile(cfg, SimpleNamespace(plan=str(pf), chains=["x.parquet"], account=None, out=None, apply=True))
    msg = str(e.value)
    assert "HTTP 503" in msg and "If the send went through, a re-run is refused" in msg and "ledger length" in msg
    assert not re.search(r"\b(90|89\.\d+|cash|₹)\b", msg + out.getvalue())

def test_the_command_prints_counts_and_a_fingerprint_only_and_a_dry_run_sends_nothing(cfg, tmp_path, monkeypatch):
    from quantdesk.paperlink import cli
    a = account(cfg)
    (tmp_path / "acct.json").write_text(account_json(a), encoding="utf-8")
    pf = tmp_path / "plan.json"
    pf.write_text(json.dumps(plan(a, [{"at": AT.isoformat(), "side": "sell", "symbol": LONG}])), encoding="utf-8")
    monkeypatch.setattr(RC.QuoteBook, "from_parquet", classmethod(lambda c, paths: c([row(LONG, AT, 90.0, 90.5)])))
    called = []
    monkeypatch.setattr("quantdesk.paperlink.relay.Relay.from_env", classmethod(lambda c: called.append(1)))
    out = io.StringIO()
    with redirect_stdout(out):
        cli.cmd_reconcile(cfg, SimpleNamespace(plan=str(pf), chains=["x.parquet"], account=str(tmp_path / "acct.json"), out=str(tmp_path / "new.json"), apply=False))
    s = out.getvalue()
    assert "1 rows booked" in s and "dry run" in s and not called
    assert not re.search(r"\b(90|89\.\d+|cash|₹)\b", s)                                         # no price, no cash figure in a public log
    assert len(load_account((tmp_path / "new.json").read_text(encoding="utf-8")).ledger) == len(a.ledger) + 1


def test_apply_cannot_be_combined_with_an_offline_account(cfg, tmp_path, monkeypatch):
    from quantdesk.paperlink import cli
    a = account(cfg)
    (tmp_path / "acct.json").write_text(account_json(a), encoding="utf-8")
    pf = tmp_path / "plan.json"
    pf.write_text(json.dumps(plan(a, [{"at": AT.isoformat(), "side": "sell", "symbol": LONG}])), encoding="utf-8")
    monkeypatch.setattr(RC.QuoteBook, "from_parquet", classmethod(lambda c, paths: c([row(LONG, AT, 90.0, 90.5)])))
    with pytest.raises(SystemExit, match="cannot be combined"), redirect_stdout(io.StringIO()):
        cli.cmd_reconcile(cfg, SimpleNamespace(plan=str(pf), chains=["x"], account=str(tmp_path / "acct.json"), out=None, apply=True))


# ---- the workflow ---------------------------------------------------------------------------------------------------------------------------------
RAW = (ROOT / ".github" / "workflows" / "paper-reconcile.yml").read_text(encoding="utf-8")
WF = yaml.safe_load(RAW)


def test_the_workflow_is_manual_main_only_read_only_and_queued_with_the_runner():
    assert list(WF[True]) == ["workflow_dispatch"]                                            # yaml reads `on` as True
    assert WF["permissions"] == {"contents": "read"}
    assert WF["concurrency"]["group"] == "paper-desk" and WF["concurrency"]["cancel-in-progress"] is False      # the paper runner's group: never beside it
    job = WF["jobs"]["reconcile"]
    assert job["if"] == "${{ github.ref == 'refs/heads/main' }}"
    assert all(s.get("with", {}).get("persist-credentials") is False for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))


def test_the_relay_keys_are_in_the_one_step_that_reconciles_and_no_broker_credential_anywhere():
    steps = WF["jobs"]["reconcile"]["steps"]
    holders = [s for s in steps if "secrets." in yaml.safe_dump(s)]
    assert len(holders) == 1 and "quantdesk paper reconcile" in holders[0]["run"]
    assert set(holders[0]["env"]) == {"LIVE_URL", "LIVE_READ_TOKEN", "LIVE_INGEST_TOKEN", "APPLY"}
    assert not re.search(r"KITE_|KOTAK_|FYERS_|ANGEL_|ZERODHA|API_SECRET|TOTP|PASSWORD|place_order|/orders", RAW, re.I)
    assert "${{ inputs." not in "".join(s.get("run", "") for s in steps)                      # inputs reach shell only through env: no script injection


def test_apply_needs_the_plan_id_typed_again():
    gate = next(s for s in WF["jobs"]["reconcile"]["steps"] if s.get("name", "").startswith("Check the inputs"))
    assert '[ "$APPLY" = "true" ] && [ "$CONFIRM" != "$PLAN" ]' in gate["run"] and "exit 1" in gate["run"]
