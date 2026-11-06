"""`quantdesk intraday …` commands: what is left of the intraday desk after the owner stopped paper trading
(6 Nov 2026). The engine, the brain, the learning loop and the sleeves were removed; the recorders stay.

  tape         record real option chains every minute for several expiries (record.yml runs it beside the recorder)
  doctor       can this machine record the session (Yahoo, NSE, Kotak, the calendar)
  kotak-check  what the Kotak Neo consumer key can see (quotes, expiries, option chain, candles)
  vol-shadow   the desk's recorded A-vs-HAR volatility forecasts against what the index did
  export-site  the web app as a read-only static site
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import pandas as pd

from ..core.calendar import TradingCalendar
from ..journal.journal import Journal
from .recorder import SessionRecorder


def paths(cfg, account: str) -> dict:
    base = cfg.runtime_dir / "intraday"
    acct = base if account == "live" else base / account
    acct.mkdir(parents=True, exist_ok=True)
    return {"journal": acct / "journal.db", "data": base / "data"}


def _kotak_client():
    """A Kotak Neo client when KOTAK_CONSUMER_KEY is set, else None."""
    from .kotak import KotakClient, KotakError
    try:
        return KotakClient.from_env()
    except KotakError:
        return None


def cmd_tape(cfg, a):
    """Record real option chains every minute for several expiries, beside the engine (intraday/tape.py)."""
    from .feeds import IST
    from .kotak import KotakOptionChain
    from .tape import ChainTape, completeness, render
    data = paths(cfg, "live")["data"]
    if a.report:
        day = a.report if a.report != "today" else str(pd.Timestamp.now(tz=IST).date())
        print(render(completeness(data / day)), flush=True)
        return
    client = _kotak_client()
    if client is None:
        print("chain tape: no KOTAK_CONSUMER_KEY; nothing to record (NSE's public chain is the engine's fallback only)",
              flush=True)
        return
    now = pd.Timestamp.now(tz=IST)
    if not TradingCalendar(cfg.holidays()).is_trading_day(now.date()):
        print(f"chain tape: {now.date()} is not an NSE trading day", flush=True)
        return
    tc = cfg.get("intraday.tape", {}) or {}
    want = dict(tc.get("expiries") or {})
    if a.symbols:
        want = {s.strip().upper(): want.get(s.strip().upper(), 2) for s in a.symbols.split(",") if s.strip()}
    kc = cfg.get("intraday.kotak", {}) or {}
    tape = ChainTape(KotakOptionChain(client, strikes=kc.get("strikes", 20)), data, want or None,
                     every_min=tc.get("every_min", 1), say=lambda m: print(m, flush=True))
    tape.run(dt.time.fromisoformat(a.until) if a.until else None)


def cmd_vol_shadow(cfg, a):
    """Live A (the desk's vol forecaster) vs HAR: the journaled shadow forecasts scored against the recorded bars. The protocol's
    single read (60 counted sessions, or the 31 Mar 2027 backstop) is taken here once on the live journal and stored; after
    that this command shows the stored record. `--since` narrows only the per-cell tables, never the primary statistic."""
    import pandas as pd

    from . import volshadow
    p = paths(cfg, a.account or "live")
    j = Journal(p["journal"])
    rec = SessionRecorder(p["data"])
    bars = rec.load_bars(cfg.get("intraday.underlyings")) if rec.days() else {}
    rep = volshadow.compare(j.events(), bars)
    if a.since:
        part = volshadow.compare(j.events(since=a.since), bars)
        rep = {**part, **{k: rep[k] for k in ("pooled", "sessions_both", "sessions_excluded") if k in rep}}
    if (a.account or "live") == "live":
        rep = volshadow.read_once(j, rep, pd.Timestamp.now(tz="Asia/Kolkata").date())
    else:
        print(f"(account {a.account}: the protocol's single read applies to the live journal only and is not taken here)")
    print(volshadow.render(rep))


def cmd_export_site(cfg, a):
    from ..web.export_site import export_site, publish_site
    if a.dir:
        out = publish_site(cfg, a.account or "live", Path(a.dir), a.sessions, a.label, a.note)
        print(f"published {out}/ (data.json {(out / 'data.json').stat().st_size / 1e6:.2f} MB): serve the folder from "
              f"any static host; the page re-reads data.json every minute", flush=True)
        return
    out = export_site(cfg, a.account or "live", Path(a.out), a.sessions, a.label, a.note)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB): open it in any browser, or host it anywhere static")


def cmd_kotak_check(cfg, a):
    """Walk the Kotak Neo endpoints the desk uses with KOTAK_CONSUMER_KEY; exit 1 if quotes or the chain fail."""
    from .kotak import check
    kotak = _kotak_client()
    if kotak is None:
        sys.exit("no KOTAK_CONSUMER_KEY: add it as a repository secret (Settings → Secrets and variables → Actions)")
    print(f"Kotak Neo · consumer key set ({len(os.environ['KOTAK_CONSUMER_KEY'].strip())} chars) · data endpoints only, "
          f"no login, no orders", flush=True)
    taped = list((cfg.get("intraday.tape", {}) or {}).get("expiries") or {})
    if not check(kotak, list(dict.fromkeys(cfg.get("intraday.underlyings") + taped))):
        sys.exit(1)
    print("verdict: Kotak data is usable; the recorder and the chain tape read it")


def cmd_doctor(cfg, a):
    """Can this machine record the session? Market-data reachability (Yahoo, NSE, Kotak), the calendar, expiries."""
    import time
    from .chains import NSEOptionChain
    from .feeds import IST, YahooIntradayFeed
    cal = TradingCalendar(cfg.holidays())
    now = pd.Timestamp.now(tz=IST)
    print(f"now {now:%a %Y-%m-%d %H:%M} IST · {'NSE trading day' if cal.is_trading_day(now.date()) else 'not an NSE trading day'}"
          f" · next session {cal.next_trading_day(now.date()):%a %d-%b}")
    syms = cfg.get("intraday.underlyings") + [cfg.get("universe.volatility_index")]
    feed, yahoo_ok = YahooIntradayFeed(cfg), True
    for sym in syms:
        t0 = time.time()
        try:
            df = feed.history(sym, 2)
            if df.empty:
                raise RuntimeError("no bars returned")
            lag = (now - df.index[-1]).total_seconds() / 60
            print(f"  yahoo  {sym:<10} ok   {len(df):>4} 1m bars · last {df.index[-1]:%d-%b %H:%M} "
                  f"({lag:,.0f} min ago) · {time.time() - t0:.1f}s")
        except Exception as exc:
            yahoo_ok = False
            print(f"  yahoo  {sym:<10} FAIL {exc!s:.160}")
    for u in cfg.get("intraday.underlyings"):
        spec = cfg.instrument_spec(u)
        exps = cal.expiries(now.date(), 40, int(spec.get("expiry_weekday", 1)), bool(spec.get("weekly_expiry", True)))
        print(f"  calendar {u:<8} next expiries {', '.join(f'{e:%a %d-%b}' for e in exps[:3])}")
    nse = NSEOptionChain()
    try:
        t0 = time.time()
        exps = nse.expiries("NIFTY")
        ch = nse.chain("NIFTY", exps[0])
        print(f"  nse    NIFTY      ok   expiries {', '.join(f'{e:%d-%b}' for e in exps[:3])} · {len(ch)} strikes "
              f"· spot {ch.attrs.get('spot')} · {time.time() - t0:.1f}s")
        nse_ok = True
    except Exception as exc:
        nse_ok = False
        print(f"  nse    NIFTY      FAIL {exc!s:.160}")
    kotak = _kotak_client()
    if kotak is not None:
        from .kotak import check
        print("  kotak  (KOTAK_CONSUMER_KEY set)")
        check(kotak, cfg.get("intraday.underlyings"), say=lambda m: print("  " + m))
    print("verdict:", "ready" if yahoo_ok and nse_ok else
          "ready, but NSE's public chain is unreachable from here (Kotak's, when its key is set, is the recorder's source)" if yahoo_ok else
          "NOT ready: no bars from Yahoo")
    if not yahoo_ok:
        sys.exit(1)


def register(sub):
    s = sub.add_parser("intraday", help="the intraday recorders' tools (the paper desk itself was retired on 6 Nov 2026)")
    ss = s.add_subparsers(dest="icmd", required=True)
    x = ss.add_parser("tape", help="record real option chains every minute for the nearest expiries")
    x.add_argument("--until", help="HH:MM to stop early")
    x.add_argument("--symbols", help="e.g. NIFTY,BANKNIFTY (default: intraday.tape.expiries)")
    x.add_argument("--report", nargs="?", const="today", help="completeness of a recorded day (YYYY-MM-DD) instead")
    x.set_defaults(fn=cmd_tape)
    x = ss.add_parser("doctor", help="check this machine can record the session (Yahoo, NSE, Kotak, calendar)")
    x.set_defaults(fn=cmd_doctor)
    x = ss.add_parser("kotak-check", help="what the Kotak Neo consumer key can see (no login, no orders)")
    x.set_defaults(fn=cmd_kotak_check)
    x = ss.add_parser("vol-shadow", help="the recorded A-vs-HAR volatility forecasts against what the index did (QLIKE, move ratio)")
    x.add_argument("--account", help="live (default), replay, synthetic")
    x.add_argument("--since", help="only forecasts from this date (YYYY-MM-DD)")
    x.set_defaults(fn=cmd_vol_shadow)
    x = ss.add_parser("export-site", help="the web app + an account's data as a read-only static site")
    x.add_argument("--account", help="live (default), replay, synthetic")
    x.add_argument("--out", default="quantdesk-snapshot.html")
    x.add_argument("--dir", help="write a live-updating static site into this folder instead (index.html + data.json)")
    x.add_argument("--sessions", type=int, default=3, help="sessions of thoughts to include")
    x.add_argument("--label")
    x.add_argument("--note")
    x.set_defaults(fn=cmd_export_site)
    return s
