"""The wide Kite universe (quantdesk/data/kite_universe.py) and how the recorder, the live push and the relay carry it: every F&O underlying, MCX, currency,
the F&O stocks' cash prices and index options near the money, instead of five symbols. Built on synthetic instrument lists shaped like Kite's own."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from quantdesk.data import kite_record as K
from quantdesk.data import kite_universe as U
from quantdesk.data import live_push as LP

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 9)
CORE = {"NIFTY": 256265, "BANKNIFTY": 260105, "INDIAVIX": 264969, "NIFTY-FUT": 1000, "BANKNIFTY-FUT": 2000}


def _inst(tok, name, typ, expiry, seg="NFO-FUT", strike=0.0, sym=None, exch="NFO"):
    return {"instrument_token": tok, "name": name, "instrument_type": typ, "expiry": expiry, "strike": strike, "tradingsymbol": sym or f"{name}{typ}{tok}", "segment": seg, "exchange": exch}


def make_lists():
    nfo, tok = [], 10_000
    for name in ("NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY"):
        for exp in ("2026-11-03", "2026-11-24", "2026-12-29"):                   # the 3 Nov contract is expired
            tok += 1
            nfo.append(_inst(tok, name, "FUT", exp))
    for fam, centre, step in (("NIFTY", 24500, 50), ("BANKNIFTY", 52000, 100), ("FINNIFTY", 24000, 50), ("MIDCPNIFTY", 12000, 25)):
        for exp in ("2026-11-12", "2026-11-19", "2026-11-26"):
            for k in range(-30, 31):
                for typ in ("CE", "PE"):
                    tok += 1
                    nfo.append(_inst(tok, fam, typ, exp, strike=float(centre + k * step), sym=f"{fam}{exp}{centre + k * step}{typ}"))
    nse = [{"instrument_token": 500 + i, "name": n, "instrument_type": "EQ", "tradingsymbol": n, "expiry": None, "strike": 0.0, "segment": "NSE", "exchange": "NSE"}
           for i, n in enumerate(("RELIANCE", "TCS", "INFY", "WIPRO"))]               # WIPRO has no F&O here: not wanted
    mcx = [_inst(700 + i, n, "FUT", "2026-11-28", exch="MCX") for i, n in enumerate(("CRUDEOIL", "GOLD", "SILVER"))] + [_inst(710, "GOLD", "FUT", "2026-12-31", exch="MCX")]
    cds = [_inst(800, "USDINR", "FUT", "2026-11-27", exch="CDS"), _inst(801, "EURINR", "FUT", "2026-11-27", exch="CDS")]
    bfo = [_inst(900, "SENSEX", "FUT", "2026-11-26", exch="BFO")]
    return {"NFO": nfo, "NSE": nse, "MCX": mcx, "CDS": cds, "BFO": bfo}


class FakeKite:
    def __init__(self, lists=None, broken=(), ltp_ok=True):
        self.lists, self.broken, self.ltp_ok = (make_lists() if lists is None else lists), set(broken), ltp_ok

    def ltp(self, keys):
        if not self.ltp_ok:
            raise ConnectionError("no price")
        ids = {"NSE:NIFTY 50": (256265, 24510.0), "NSE:NIFTY BANK": (260105, 52040.0), "NSE:NIFTY FIN SERVICE": (257801, 24020.0), "NSE:NIFTY MID SELECT": (288009, 12010.0),
               "NSE:NIFTY NEXT 50": (270857, 70000.0), "BSE:SENSEX": (265, 80000.0)}
        return {k: {"instrument_token": ids[k][0], "last_price": ids[k][1]} for k in keys if k in ids}

    def instruments(self, ex):
        if ex in self.broken:
            raise ConnectionError(ex)
        return self.lists.get(ex, [])


def build(**kw):
    return U.build_wide(kw.pop("kite", FakeKite()), TODAY, kw.pop("core", CORE), **kw)


def test_every_underlying_gets_its_near_month_future_not_an_expired_one():
    toks, meta, errs = build()
    for name in ("RELIANCE", "TCS", "INFY"):
        assert meta[f"{name}-FUT"]["expiry"] == "2026-11-24" and meta[f"{name}-FUT"]["s"] == "fut"
    assert "NIFTY-FUT" not in toks                                        # a core symbol is not repeated
    assert meta["CRUDEOIL-MCX"]["s"] == "mcx" and meta["GOLD-MCX"]["expiry"] == "2026-11-28"       # the nearer GOLD contract
    assert meta["USDINR-CDS"]["s"] == "cds" and meta["EURINR-CDS"]["s"] == "cds" and meta["SENSEX-BFO"]["s"] == "bfo"


def test_f_and_o_stocks_get_their_cash_price_and_indices_do_not_pose_as_stocks():
    toks, meta, _ = build()
    assert {k for k, v in meta.items() if v["s"] == "eq"} == {"RELIANCE", "TCS", "INFY"}               # WIPRO has no F&O; NIFTY and BANKNIFTY are not stocks
    assert meta["FINNIFTY"]["s"] == "idx" and meta["SENSEX"]["s"] == "idx" and meta["NIFTYNXT50"]["s"] == "idx"


def test_index_options_are_a_window_around_the_money_for_the_nearest_two_expiries():
    toks, meta, _ = build()
    nifty = {k: v for k, v in meta.items() if v["s"] == "opt" and v["name"] == "NIFTY"}
    assert len(nifty) == 2 * 21 * 2                                      # two expiries, 21 strikes (ATM +- 10), calls and puts
    assert {v["expiry"] for v in nifty.values()} == {"2026-11-12", "2026-11-19"}                      # not the third
    strikes = sorted({v["strike"] for v in nifty.values()})
    assert strikes[0] == 24500 - 10 * 50 and strikes[-1] == 24500 + 10 * 50 and 24500.0 in strikes       # spot 24510 -> ATM 24500 (nearest listed strike), 10 steps each side
    assert {v["kind"] for v in nifty.values()} == {"CE", "PE"}
    assert {v["name"] for v in meta.values() if v["s"] == "opt"} == set(U.OPT_FAMILIES)


def test_tokens_are_unique_and_never_collide_with_the_core():
    toks, _, _ = build()
    assert len(set(toks.values())) == len(toks) and not set(toks.values()) & set(CORE.values()) and not set(toks) & set(CORE)


def test_the_cut_drops_options_first_and_never_a_future_or_a_spot_price():
    full, meta, _ = build()
    nonopt = len([1 for v in meta.values() if v["s"] != "opt"])
    toks, m2, errs = build(limit=len(CORE) + nonopt + 10)
    assert len(toks) == nonopt + 10 and sum(1 for v in m2.values() if v["s"] == "opt") == 10
    assert all(any(k == f"{n}-FUT" for k in toks) for n in ("RELIANCE", "TCS", "INFY")) and "RELIANCE" in toks
    assert any("cut to the" in e for e in errs)


def test_one_missing_exchange_or_price_skips_only_its_part():
    toks, meta, errs = build(kite=FakeKite(broken=("MCX",)))
    assert not any(v["s"] == "mcx" for v in meta.values()) and any(v["s"] == "fut" for v in meta.values()) and any("MCX" in e for e in errs)
    toks, meta, errs = build(kite=FakeKite(ltp_ok=False))
    assert not any(v["s"] == "opt" for v in meta.values()) and "RELIANCE-FUT" in toks and any("index prices" in e for e in errs)
    toks, meta, errs = build(kite=FakeKite(lists={}))
    assert set(toks) == {"FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX"} and len(errs) >= 4        # no instrument lists at all: only the index spots (they need no list), and every gap explained, never an exception


def test_the_module_can_place_no_order():
    src = (ROOT / "quantdesk/data/kite_universe.py").read_text()
    assert not re.search(r"place_order|modify_order|cancel_order|\.orders\(|\.positions\(|\.holdings\(|\.margins\(|\.profile\(", src)
    assert not re.search(r"quantdesk\.(paper|engine|journal|risk|broker)|from \.\.(paper|engine|journal)", src)


# ---- the recorder ----------------------------------------------------------------------------------------------------------------------
class Ws:
    MODE_FULL, MODE_QUOTE = "full", "quote"

    def __init__(self):
        self.subs, self.modes = [], {}

    def subscribe(self, toks): self.subs.append(list(toks))
    def set_mode(self, mode, toks): self.modes.setdefault(mode, []).extend(toks)
    def connect(self, threaded=True): self.on_connect(self, {})
    def close(self): pass


def test_the_core_is_recorded_with_depth_and_the_rest_in_quote_mode_subscribed_in_chunks(tmp_path):
    toks = {**CORE, **{f"S{i}": 10_000 + i for i in range(1200)}}
    ws = Ws()
    rec = K.Recorder(tmp_path, toks, lambda: ws, core=set(CORE))
    rec.ws.connect()
    assert ws.modes["full"] == list(CORE.values()) and len(ws.modes["quote"]) == 1200
    assert all(len(c) <= 500 for c in ws.subs) and sum(len(c) for c in ws.subs) == 1205
    ev = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()] if (tmp_path / "events.jsonl").exists() else []
    rec.flush()
    ev = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert ev[0]["kind"] == "connect" and ev[0]["full"] == 5 and ev[0]["quote"] == 1200


def test_without_a_core_argument_everything_is_full_mode_as_before(tmp_path):
    ws = Ws()
    K.Recorder(tmp_path, {"NIFTY": 1, "BANKNIFTY": 2}, lambda: ws).ws.connect()
    assert ws.modes == {"full": [1, 2]}


def test_a_quote_mode_tick_without_depth_is_recorded_and_sent_with_its_segment(tmp_path):
    seen = []

    class Live:
        def update(self, sym, q): seen.append((sym, q))
    rec = K.Recorder(tmp_path, {"RELIANCE-FUT": 7}, Ws, core=set(), meta={"RELIANCE-FUT": {"s": "fut"}}, live=Live())
    rec._on_ticks(None, [{"instrument_token": 7, "last_price": 2900.5, "volume_traded": 10, "change": -0.4}])
    assert rec.ticks == 0 and rec.wide_ticks == 1 and len(rec.rows) == 0 and len(rec.wide_rows) == 1        # a wide tick never enters the trial's buffer
    assert seen == [("RELIANCE-FUT", {"ltp": 2900.5, "vol": 10.0, "chg": -0.4, "s": "fut"})]
    assert LP.quote_from_tick({"last_price": 1.0}, None, "nonsense") == {"ltp": 1.0}                   # an unknown segment is not sent


def test_the_last_recorded_part_is_flushed_before_the_display_stops(tmp_path):
    order = []

    class Live:
        def start(self): order.append("start")
        def stop(self): order.append("stop")
        def stats(self): return {}
    rec = K.Recorder(tmp_path, {"A": 1}, Ws, live=Live())
    real = rec.flush
    rec.flush = lambda: (order.append("flush"), real())[1]
    t0 = pd.Timestamp("2026-11-09 09:15", tz="Asia/Kolkata")
    clock = iter([t0, t0] + [t0 + pd.Timedelta(seconds=9999)] * 20)
    rec.now = lambda: next(clock)
    rec.run(t0 + pd.Timedelta(seconds=1), sleep=lambda s: None)
    assert order == ["start", "flush", "stop", "flush"]


def test_a_display_that_cannot_start_never_stops_the_recording(tmp_path):
    class Live:
        def start(self): raise RuntimeError("no threads")
    rec = K.Recorder(tmp_path, {"A": 1}, Ws, live=Live())
    t0 = pd.Timestamp("2026-11-09 09:15", tz="Asia/Kolkata")
    clock = iter([t0, t0] + [t0 + pd.Timedelta(seconds=9999)] * 20)
    rec.now = lambda: next(clock)
    assert rec.run(t0 + pd.Timedelta(seconds=1), sleep=lambda s: None)["parts"] == 0 and rec.live is None


def test_run_session_records_the_wide_universe_too_and_a_broken_one_costs_only_itself(tmp_path, monkeypatch):
    from tests.test_kite_trial import Clock, FakeKite as CoreKite, FakeTicker
    monkeypatch.setenv("KITE_DATA_KEY", "k")
    monkeypatch.setenv("KITE_DATA_TOKEN", "t")
    monkeypatch.delenv("LIVE_URL", raising=False)

    class Wide(CoreKite):
        def instruments(self, ex):
            if ex == "NFO":
                return super().instruments(ex) + [_inst(3000, "RELIANCE", "FUT", "2026-11-24", sym="RELIANCEFUT")]
            return []

    clock, ticker = Clock("2026-10-26 15:29:58"), FakeTicker()
    out = tmp_path / "a"
    res = K.run_session(out, "15:30", kite=Wide(), ticker_factory=lambda: ticker, now=clock, sleep=lambda s: clock.advance(1))
    uni = json.loads((out / "universe.json").read_text())
    assert "RELIANCE-FUT" not in res["tokens"] and res["wide_n"] >= 1                                  # tokens (and tokens.json) are the trial's five instruments only
    assert "RELIANCE-FUT" in uni["wide_tokens"] and uni["meta"]["RELIANCE-FUT"]["s"] == "fut" and set(uni["core"]) == set(CORE)
    assert set(json.loads((out / "tokens.json").read_text())) == set(CORE)
    assert uni["meta"]["NIFTY"]["s"] == "idx" and uni["meta"]["NIFTY-FUT"]["s"] == "fut"

    monkeypatch.setattr(K, "build_wide", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))        # the wide part blows up: the core five are still recorded
    clock2, ticker2 = Clock("2026-10-26 15:29:58"), FakeTicker()
    res2 = K.run_session(tmp_path / "b", "15:30", kite=CoreKite(), ticker_factory=lambda: ticker2, now=clock2, sleep=lambda s: clock2.advance(1))
    assert set(res2["tokens"]) == set(CORE) and res2["wide_n"] == 0 and res2["wide_errors"] == ["wide universe: RuntimeError"]
    monkeypatch.undo()
    monkeypatch.setenv("KITE_DATA_KEY", "k")
    monkeypatch.setenv("KITE_DATA_TOKEN", "t")
    monkeypatch.setenv("KITE_WIDE", "0")
    clock3, ticker3 = Clock("2026-10-26 15:29:58"), FakeTicker()
    assert set(K.run_session(tmp_path / "c", "15:30", kite=Wide(), ticker_factory=lambda: ticker3, now=clock3, sleep=lambda s: clock3.advance(1))["tokens"]) == set(CORE)       # KITE_WIDE=0 switches it off


# ---- the live push at scale ------------------------------------------------------------------------------------------------------------
class Resp:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_a_wide_push_goes_in_batches_and_a_failure_keeps_everything_unsent():
    sent = []
    p = LP.LivePusher("https://x.example/live/ingest", "T" * 30, opener=lambda req, timeout: (sent.append(json.loads(req.data)), Resp())[1])
    for i in range(2000):
        p.update(f"S{i}", {"ltp": float(i)})
    assert p.push_once() and [len(b["quotes"]) for b in sent] == [LP.BATCH, LP.BATCH, 2000 - 2 * LP.BATCH] and sum(len(b["quotes"]) for b in sent) == 2000
    calls = []

    def down(req, timeout):
        calls.append(1)
        raise OSError("down")
    q = LP.LivePusher("https://x.example/live/ingest", "T" * 30, opener=down)
    for i in range(2000):
        q.update(f"S{i}", {"ltp": float(i)})
    assert q.push_once() is False and len(calls) == 1 and len(q.dirty) == 2000     # one timeout per cycle, and nothing is lost


def test_the_pusher_will_not_follow_a_redirect_with_its_token():
    import http.server
    import threading
    import urllib.error
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_POST(self):
            hits.append((self.path, self.headers.get("Authorization")))
            if self.path == "/live/ingest":
                self.send_response(302); self.send_header("Location", "/elsewhere"); self.end_headers()
            else:
                self.send_response(200); self.end_headers()
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    p = LP.LivePusher("https://x.example/live/ingest", "T" * 30)
    p.url = f"http://127.0.0.1:{srv.server_port}/live/ingest"             # the https rule is checked at construction; the opener's redirect rule is what is under test
    p.update("A", {"ltp": 1.0})
    assert p.push_once() is False and p.last_error.startswith("HTTPError 302")
    srv.shutdown()
    assert [h[0] for h in hits] == ["/live/ingest"]                       # the redirect target was never contacted, so the token never went there


def test_the_live_tab_has_search_segments_sorting_and_show_more_and_skips_github_io():
    app = (ROOT / "quantdesk/web/static/app/app.js").read_text()
    for needle in ("Search every instrument", "LIVE_SEGS", "LIVE_SORTS", "Show ${", "github\\.io"):
        assert needle in app, needle
    assert "innerHTML" not in app


# ---- the Kite trial's measures must not move (independent review, B1) --------------------------------------------------------------------------
def test_wide_files_live_in_their_own_folder_and_the_trials_measures_do_not_move(tmp_path):
    from tests.test_kite_trial import DAY, KC, moving, reference_for, ticks_for, write_session
    mins = KC.session_minutes(DAY)
    write_session(tmp_path / "plain", ticks_for("NIFTY", mins, moving), reference_for("NIFTY", mins, moving))
    base = KC.session_report(tmp_path / "plain", DAY)
    write_session(tmp_path / "mixed", ticks_for("NIFTY", mins, moving), reference_for("NIFTY", mins, moving))
    mixed = tmp_path / "mixed"
    (mixed / "wide").mkdir()
    rows = [{"symbol": f"STK{i}", "token": 5000 + i, "ts_exchange": None, "ts_recv": pd.Timestamp("2026-11-09 09:15:01", tz="Asia/Kolkata"), "last_price": 100.0 + i,
             "last_qty": 1.0, "volume": 10.0, "oi": None, "buy_qty_total": 5.0, "sell_qty_total": 6.0, "change": 0.1, "open": 99.0, "high": 101.0, "low": 98.0, "close": 99.5}
            for i in range(50)]
    pd.DataFrame(rows, columns=K.WIDE_COLUMNS).to_parquet(mixed / "wide" / "wide_000000_0001.parquet", index=False)        # no exchange timestamp: the shape that crashed the measure
    (mixed / "universe.json").write_text(json.dumps({"meta": {}, "core": ["NIFTY"], "wide_tokens": {f"STK{i}": 5000 + i for i in range(50)}}))
    rep = KC.session_report(mixed, DAY)
    assert rep["passed"] == base["passed"] and rep["measures"] == base["measures"] and rep["ticks"] == base["ticks"]
    assert rep["D3_bytes"] == base["D3_bytes"]                                                         # the trial's storage measure counts its own files only
    assert [m["symbol"] for m in rep["measures"]] == ["NIFTY"]


def test_a_whole_wide_session_leaves_the_trials_report_computable(tmp_path, monkeypatch):
    from tests.test_kite_trial import Clock, FakeKite as CoreKite, FakeTicker, KC, kite_tick
    monkeypatch.setenv("KITE_DATA_KEY", "k")
    monkeypatch.setenv("KITE_DATA_TOKEN", "t")
    monkeypatch.delenv("LIVE_URL", raising=False)

    class Wide(CoreKite):
        def instruments(self, ex):
            return super().instruments(ex) + [_inst(3000, "RELIANCE", "FUT", "2026-11-24", sym="RELIANCEFUT")] if ex == "NFO" else []
    clock, ticker = Clock("2026-10-26 15:29:50"), FakeTicker()
    out = tmp_path / "rec"

    def sleep(s):
        clock.advance(1)
        ticker.on_ticks(ticker, [kite_tick(256265, 25000.0, clock().tz_localize(None)), {"instrument_token": 3000, "last_price": 2900.0, "volume_traded": 5, "change": 0.2}])
    res = K.run_session(out, "15:30", kite=Wide(), ticker_factory=lambda: ticker, now=clock, sleep=sleep)
    assert (out / "wide").is_dir() and list((out / "wide").glob("wide_*.parquet")) and not list(out.glob("wide_*"))
    assert all(p.name.startswith("ticks_") for p in out.glob("*.parquet"))                              # nothing but the trial's own parts at the top level
    rep = KC.session_report(out, pd.Timestamp("2026-10-26").date())                                    # used to raise on the NaT exchange timestamps
    assert sorted(m["symbol"] for m in rep["measures"]) == sorted(CORE) and res["wide_n"] == 1                # the trial measures its five instruments, no wide symbol
    ev = [json.loads(x) for x in (out / "events.jsonl").read_text().splitlines()]
    assert any(e["kind"] == "wide" and e["ticks"] > 0 for e in ev)


def test_a_failing_wide_write_never_fails_the_run_and_the_overflow_is_on_record(tmp_path, monkeypatch):
    rec = K.Recorder(tmp_path, {"NIFTY": 1, "RELIANCE-FUT": 2}, Ws, core={"NIFTY"})
    monkeypatch.setattr(K, "MAX_WIDE_BUFFER", 2)
    rec._on_ticks(None, [{"instrument_token": 2, "last_price": float(i)} for i in range(5)])
    assert rec.wide_ticks == 2 and rec.wide_overflow == 3
    real = pd.DataFrame.to_parquet
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda self, path, *a, **k: (_ for _ in ()).throw(OSError("disk full")) if "wide_" in Path(path).name else real(self, path, *a, **k))
    rec.flush()                                                                                        # does not raise
    assert len(rec.wide_rows) == 2 and rec.dropped == 0 and rec.wide_dropped == 3                       # kept for the next flush; the core's drop count is untouched
