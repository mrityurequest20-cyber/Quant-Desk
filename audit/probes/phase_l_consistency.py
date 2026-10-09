"""Phase L: decision-to-UI consistency attack — every stepped minute of a recorded session (read-only).

Replays a recorded session from copies of persisted evidence (as phase_k_timeline: journal-branch bars + memory,
chains-2026 snapshots, the repo's replay wiring, the 12:20 hand-over emulated) and, at every minute, compares:

  - each armed-trigger hit and its real outcome (instrumented by wrapping the engine instance's own methods in this
    harness: `_fire_armed`, `_blocked`, `playbook.fire`, `ev.evaluate`; production code is not modified);
  - the decision rows and thoughts written that minute;
  - the engine's `last_action`, the heartbeat (`intraday_live`) action and armed list;
  - what the app's Live screen would say: a Python port of app.js `readAction` / `stance` / `renderNow`
    (validated against Phase K's Chromium renders by test_phase_l_probes.py).

Two trigger modes:
  bar   — the repo's replay: no live price, each new 1-minute bar's range fires armed setups (engine.step).
  tick  — SYNTHETIC SUBSTITUTION of production's live-price path (Kotak LTP every 5 s, engine.tick): between minute
          steps the next bar's open → (low, high | high, low) → close are fed as four LTP ticks at +10/+25/+40/+55 s.
          Production's rejections carry second-resolution timestamps (e.g. 13:59:22), i.e. they came from tick().

    python audit/probes/phase_l_consistency.py JOURNAL_DIR CHAINS_DIR 2026-10-05 bar OUT.json [--drop-zero-prior-vix]
"""
import datetime as dt
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from phase_i_replay import snapshots  # noqa: E402
from quantdesk.config import Config, DEFAULT_CONFIG  # noqa: E402
from quantdesk.intraday.chains import RecordedChains  # noqa: E402
from quantdesk.intraday.engine import IntradayEngine  # noqa: E402
from quantdesk.intraday.feeds import ReplayFeed  # noqa: E402
from quantdesk.intraday.learning import Memory  # noqa: E402
from quantdesk.intraday.recorder import SessionRecorder  # noqa: E402
from quantdesk.intraday.sim import IntradayBroker  # noqa: E402
from quantdesk.journal.journal import Journal  # noqa: E402

IST = "Asia/Kolkata"
SETUP = {"orb": "Opening-range breakout", "vwap_trend": "VWAP trend", "trend_break": "Trend break", "fade": "Fade",
         "reversal": "Reversal", "range": "Range"}


# ---- app.js port (quantdesk/web/static/app/app.js:134-150, 463-485) ------------------------------------------------
def cap(s):
    return (str(s)[:1].upper() + str(s)[1:]) if s else ""


def read_action(a):
    a = str(a or "").strip()
    if re.match(r"^ENTER", a):
        return {"kind": "enter", "label": "Entered a trade", "reason": a[6:]}
    if re.match(r"^EXIT", a):
        return {"kind": "exit", "label": "Closed a trade", "reason": a[5:]}
    m = re.match(r"^standing aside[^:]*:\s*(.*)$", a, re.I | re.S)
    if m:
        return {"kind": "aside", "label": "Standing aside", "reason": cap(m.group(1))}
    m = re.match(r"^watching[^:]*:\s*(.*)$", a, re.I | re.S)
    if m:
        return {"kind": "watch", "label": "Watching", "reason": cap(m.group(1))}
    m = re.match(r"^armed:\s*(.*)$", a, re.I | re.S)
    if m:
        return {"kind": "armed", "label": "Waiting at the level", "reason": cap(m.group(1))}
    if re.search(r"sized to 0 lots|not worth it|\bEV\b", a):
        return {"kind": "pass", "label": "Passed on a setup", "reason": cap(a)}
    return {"kind": "other" if a else "none", "label": cap(a) if a else "No read yet", "reason": ""}


def stance(v):
    a = read_action((v or {}).get("action"))
    if a["kind"] == "none" and v and (v.get("vetoes") or []):
        return {"kind": "aside", "label": "Standing aside", "reason": cap(v["vetoes"][0])}
    return a


def render_now(hb: dict, paused: bool = False) -> dict:
    vs, pos, armed = hb.get("views") or {}, hb.get("positions") or [], hb.get("armed") or []
    if not vs:
        return {"head": "The desk's read appears here from 09:15 IST, updated every minute.", "lines": {}}
    reads = {s: stance(v) for s, v in vs.items()}
    if paused:
        head = "Paused from the app · open positions are still managed"
    elif hb.get("halted"):
        head = "Done for the day · the daily loss limit is hit"
    elif pos:
        head = (f"In a {pos[0]['symbol']} trade" if len(pos) == 1 else f"In {len(pos)} trades") + \
               (f" · armed on {', '.join(dict.fromkeys(a['symbol'] for a in armed))}" if armed else "")
    elif armed:
        a = armed[0]
        head = f"Armed · {SETUP.get(a['setup'], a['setup'])} {'call' if a['direction'] > 0 else 'put'} on {a['symbol']} at {a['level']:,.2f}"
    elif any(r["kind"] == "enter" for r in reads.values()):
        head = "Just entered a trade"
    elif all(r["kind"] == "aside" for r in reads.values()):
        head = "Standing aside · a no-trade flag is up"
    elif any(r["kind"] == "watch" for r in reads.values()):
        head = "Watching · no setup has triggered"
    else:
        head = "Reading the market every minute"
    return {"head": head, "lines": {s: r["label"] + (": " + r["reason"] if r["reason"] else "") for s, r in reads.items()
                                    if r["kind"] != "none"}, "kinds": {s: r["kind"] for s, r in reads.items()}}


# ---- instrumentation (wraps the instance's bound methods; the class and repo files are untouched) -------------------
def instrument(eng, log: dict):
    ctx = {"in_fire": False, "blocked": None, "plan_none": False}
    orig_fire, orig_blocked, orig_pfire, orig_eval = eng._fire_armed, eng._blocked, eng.playbook.fire, eng.ev.evaluate

    def blocked(u, view, now):
        r = orig_blocked(u, view, now)
        if ctx["in_fire"]:
            ctx["blocked"] = r
        return r

    def pfire(*a, **k):
        r = orig_pfire(*a, **k)
        if ctx["in_fire"]:
            ctx["plan_none"] = r is None
        return r

    def evaluate(plan, S, now, sigma_min, p_up, *a, **k):
        e = orig_eval(plan, S, now, sigma_min, p_up, *a, **k)
        log["ev_calls"].append({"ts": str(now), "symbol": plan.symbol, "setup": plan.setup, "structure": plan.structure,
                                "direction": plan.direction, "p_up_arg": round(float(p_up), 6), "ev": round(float(e["ev"]), 2)})
        return e

    def fire(u, now, price=None, bar=None):
        live = [a for a in eng.armed.get(u, []) if now <= a.expires]
        expired = [a for a in eng.armed.get(u, []) if now > a.expires]
        hits = [a for a in live if ((price is not None and a.hit(price)) or (price is None and a.bar_fill(*bar) is not None))]
        nd = eng.journal.df("SELECT COUNT(*) n FROM decisions")["n"].iloc[0]
        nt = eng.journal.df("SELECT COUNT(*) n FROM thoughts")["n"].iloc[0]
        ctx.update(in_fire=True, blocked=None, plan_none=False)
        try:
            r = orig_fire(u, now, price=price, bar=bar)
        finally:
            ctx["in_fire"] = False
        if expired:
            log["expired_at_fire"].append({"ts": str(now), "symbol": u, "n": len(expired)})
        if not hits:
            return r
        a = hits[0]                                          # _fire_armed acts on the first hit only
        dd = eng.journal.df("SELECT COUNT(*) n FROM decisions")["n"].iloc[0] - nd
        dt_ = eng.journal.df("SELECT COUNT(*) n FROM thoughts")["n"].iloc[0] - nt
        if r and r.startswith("ENTER"):
            cls = "approved_enter"
        elif ctx["blocked"]:
            cls = "blocked_silent"
        elif ctx["plan_none"]:
            cls = "plan_none_silent"
        elif r and "no approved plan model" in r or (r and dd and not dt_):
            cls = "rejected_model_gate"
        elif r and "not worth it" in r or (r and "EV" in r):
            cls = "rejected_ev"
        elif r is None and dt_:
            cls = "rejected_by_record"
        elif r is None and dd:
            cls = "rejected_size"
        elif r:
            cls = "rejected_other"
        else:
            cls = "unexplained_none"
        log["fires"].append({"ts": str(now), "minute": f"{now:%H:%M}", "symbol": u, "mode": "tick" if price is not None else "bar",
                             "setup": a.setup, "level": a.level, "n_live": len(live), "n_hits": len(hits), "outcome": cls,
                             "blocked_reason": ctx["blocked"], "returned": r, "decision_rows": int(dd), "thought_rows": int(dt_)})
        return r

    eng._fire_armed, eng._blocked, eng.playbook.fire, eng.ev.evaluate = fire, blocked, pfire, evaluate


class TickFeed(ReplayFeed):
    """ReplayFeed plus an emulated live price (has_ltp): the harness sets `px` before each tick()."""
    has_ltp = True
    px: dict = {}

    def ltp(self, want):
        return {u: self.px[u] for u in want if u in self.px}


def main(jdir: Path, cdir: Path, day: dt.date, mode: str, out: Path, drop_vix: bool):
    tmp = Path(tempfile.mkdtemp(prefix=f"l-cons-{day}-"))
    acct = tmp / "rt" / "intraday"
    shutil.copytree(jdir / "intraday" / "data", acct / "data", ignore=lambda d, n: [x for x in n if x == "chains"])
    shutil.copy(jdir / "intraday" / "memory.json", acct / "memory.json")
    dropped = []
    if drop_vix:
        for f in sorted((acct / "data").glob("*/INDIAVIX_1m.csv")):
            if f.parent.name < str(day) and (pd.read_csv(f)["close"] <= 0).mean() > 0.5:
                f.unlink()
                dropped.append(f.parent.name)
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}})
    unders = cfg.get("intraday.underlyings")
    bars = SessionRecorder(acct / "data").load_bars(unders + [cfg.get("universe.volatility_index")], upto=day)
    chains = RecordedChains(snapshots(cdir, day, unders))
    jpath, bpath = acct / "journal.db", acct / "broker.json"
    j0 = Journal(jpath)
    j0.set_state("intraday_account", {"capital": float(cfg.get("intraday.capital")), "since": "2026-10-05"})
    j0.close()
    Feed = TickFeed if mode == "tick" else ReplayFeed
    log = {"fires": [], "ev_calls": [], "expired_at_fire": [], "minutes": [], "tick_heartbeats": []}

    def engine(at):
        feed = Feed(bars, day)
        if at:
            feed.clock = pd.Timestamp(f"{day} {at}", tz=IST)
        e = IntradayEngine(cfg, feed, chains, Journal(jpath, autocommit_every=1),
                           IntradayBroker(cfg, starting_cash=float(cfg.get("intraday.capital")), state_path=bpath),
                           None, None, None, acct / "reviews", memory=Memory(acct / "memory.json"))
        instrument(e, log)
        return e

    def minute_record(eng, now, kind="step"):
        hb = eng.journal.get_state("intraday_live") or {}
        last = f"{now:%Y-%m-%d %H:%M}"
        dec = eng.journal.df("SELECT ts, strategy, symbol, detail, context FROM decisions WHERE substr(ts,1,16)=?", (last,))
        th = eng.journal.df("SELECT ts, symbol, action FROM thoughts WHERE substr(ts,1,16)=?", (last,))
        ui = render_now(hb, eng.paused)
        return {"ts": str(now), "minute": f"{now:%H:%M}", "kind": kind, "hb_ts": hb.get("ts"),
                "engine_armed": {u: [(a.setup, a.level, str(a.expires)) for a in v] for u, v in eng.armed.items() if v},
                "hb_armed": [(a["symbol"], a["setup"], a["level"], a["expires"]) for a in hb.get("armed") or []],
                "hb_actions": {u: v.get("action") for u, v in (hb.get("views") or {}).items()},
                "hb_quant": {u: {k: (v.get("quant") or {}).get(k) for k in ("valid", "p_model")} for u, v in (hb.get("views") or {}).items()},
                "hb_score": {u: v.get("score") for u, v in (hb.get("views") or {}).items()},
                "decisions": dec[["ts", "strategy", "symbol", "detail"]].to_dict("records"),
                "decision_ctx_armed": [("armed" in json.loads(c)) for c in dec["context"]],
                "thoughts": th.to_dict("records"), "ui": ui}

    eng = engine(None)
    eng.start_session(day)
    morning = True
    while eng.feed.advance():
        eng.step()
        now = eng.feed.now()
        log["minutes"].append(minute_record(eng, now))
        if mode == "tick" and now < eng.feed.close_ts:      # the next minute's bar, as live prices inside the minute
            nxt = {}
            for u in unders:
                b = bars.get(u)
                if b is None:
                    continue
                r = b[b.index == now]
                if len(r):
                    o, h, l, c = (float(r[k].iloc[0]) for k in ("open", "high", "low", "close"))
                    nxt[u] = [o, l, h, c] if c >= o else [o, h, l, c]
            base = eng.feed.clock
            for i, sec in enumerate((10, 25, 40, 55)):
                eng.feed.clock = base + pd.Timedelta(seconds=sec)
                TickFeed.px = {u: v[i] for u, v in nxt.items()}
                hbts = (eng.journal.get_state("intraday_live") or {}).get("ts")
                did = eng.tick()
                if did:
                    rec = minute_record(eng, eng.feed.clock, kind="tick")
                    rec["hb_changed"] = rec["hb_ts"] != hbts
                    log["tick_heartbeats"].append(rec)
            eng.feed.clock = base
        if morning and f"{now:%H:%M}" >= "12:20":
            eng._persist()
            eng.journal.close()
            morning = False
            eng = engine("12:21")
            eng.start_session(day)
            eng.journal.commit()
    eng.end_session()
    eng.journal.commit()
    res = {"day": str(day), "mode": mode, "evidence_class": ("replay-exact" if not dropped else "replay-subst")
           + ("+synth-tick" if mode == "tick" else ""), "substitution": {"dropped_zero_prior_vix_days": dropped},
           **log, "outcomes": dict(Counter(f["outcome"] for f in log["fires"]))}
    out.write_text(json.dumps(res, indent=0, default=str))
    print(json.dumps({"day": str(day), "mode": mode, "minutes": len(log["minutes"]), "fires": len(log["fires"]),
                      "outcomes": res["outcomes"], "tick_heartbeats": len(log["tick_heartbeats"])}))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), dt.date.fromisoformat(sys.argv[3]), sys.argv[4], Path(sys.argv[5]),
         "--drop-zero-prior-vix" in sys.argv)
