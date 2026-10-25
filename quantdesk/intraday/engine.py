"""The intraday engine — one loop for live paper trading and for replays.

Every completed minute:
  1. pull new 1m bars (and ticks, if the feed has them) and record them;
  2. refresh the option chain every few minutes; recalibrate option marks from it;
  3. compute the session state and let the analyst form a view (evidence, bias, day type,
     vol view, vetoes, narrative);
  4. manage open positions: invalidation level, premium stop/target, underlying target,
     breakeven trail, time stop, 15:15 square-off;
  5. scan the playbook; size through intraday risk; execute on the sim broker at bid/ask;
  6. journal the thought (every few minutes, on a bias change, and on every trade event).
At the close: square off, write the session review.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import time
import traceback
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from ..core.calendar import TradingCalendar
from ..core.types import OPTIONS, Instrument, Order, Trade, TradeLeg, new_trade_id
from ..journal.journal import Journal, trade_from_dict, trade_to_dict
from . import governor
from .analyst import Analyst, MarketView
from .chainflow import ChainFlow, chain_step
from .chains import ChainSource, IntradayPricer, ModelOptionChain, chain_analytics, fill_iv, liquidity, time_to_expiry
from .features import session_state
from .feeds import IST, IntradayFeed, ReplayFeed, frozen_minutes, refresh_due, session_bounds
from .halt import CLEAR_CMD, HALT_KEY, book_diff, inherited, leg_key, prune_accepted, summary
from .halt import accepted as accepted_halt
from .ivhist import iv_percentile
from .orderflow import FootprintBuilder
from .playbook import Playbook, TradePlan
from .quant import DirectionModel, EVEngine, VolForecaster, features_5m, load_research, session_sigma, to_5m
from .risk import IntradayRisk
from .sim import IntradayBroker, QuoteMarker
from .volshadow import VolShadow

log = logging.getLogger(__name__)
_claude_budget_warned = False                       # the budget display fails quietly: one log line per process, not one a minute



DD_KEY, DD_PEAK_KEY = "intraday_drawdown_halt", "intraday_peak_equity"      # P2-9: the cross-day drawdown halt

def _provenance() -> dict:
    """C-11: which code made this record (the commit and workflow run on Actions; empty off it). The afternoon job runs
    the branch tip, so a merge during the day changes behaviour; this puts that on the trade and the session start."""
    return {k: v for k, v in (("commit", os.environ.get("GITHUB_SHA", "")[:12]), ("run", os.environ.get("GITHUB_RUN_ID", "")))
            if v}

class IntradayEngine:
    def __init__(self, cfg, feed: IntradayFeed, chains: ChainSource | str | None, journal: Journal,
                 broker: IntradayBroker, recorder=None, say=print, underlyings: list[str] | None = None,
                 review_dir: Path | None = None, news=None, brain=None, memory=None):
        ic = cfg.get("intraday", {}) or {}
        self.cfg, self.feed, self.journal, self.broker, self.recorder = cfg, feed, journal, broker, recorder
        self.say = say or (lambda *_: None)
        self.underlyings = underlyings or ic.get("underlyings", ["NIFTY", "BANKNIFTY"])
        self.vix = cfg.get("universe.volatility_index", "INDIAVIX")
        self.cal = TradingCalendar(cfg.holidays())
        self.pricer = IntradayPricer(cfg.get("backtest.risk_free", 0.065), cfg.get("backtest.dividend_yield", 0.012))
        self.model_chain = ModelOptionChain(cfg, self.cal, self.model_state, self.pricer)
        self.chains = self.model_chain if chains in (None, "model") else chains
        self.analyst, self.playbook, self.risk = Analyst(cfg), Playbook(cfg, self.pricer), IntradayRisk(cfg)
        # the risk governor (governor.py): shadow by default (journals what it would do); tighten (paper only) hands the
        # risk engine tighter limits. State: journal key risk_governor. Any failure → identity limits, never an exception.
        self._gov_cfg, self._gov_base, self._gov_acct = governor.settings(cfg.get("intraday.governor")), dict(self.risk.base_limits), cfg.get("account.mode")
        self._gov, self._gov_obs, self._gov_saved = None, {}, None
        self.marker = QuoteMarker(self.pricer)
        self.refresh_min = getattr(self.chains, "refresh_min", None) or ic.get("chain_refresh_min", 3)
        self.max_entry_slip = float(ic.get("max_entry_slip", 0.15))
        # buyer only below this equity: no short option legs (margin). None: never sell; 0: always allowed
        sl = ic.get("short_legs_from_equity", 300000)
        self.short_from = None if sl is None else float(sl)
        # anticipation: setups the read already favours wait at their trigger level (playbook.Armed) and fire the
        # moment price gets there, from a live price polled every few seconds (feeds with `realtime`) or, without
        # one, from each new 1-minute bar's range. Stops and targets are checked on the same fast loop.
        ac = ic.get("anticipate", {}) or {}
        self.anticipate = bool(ac.get("enabled", True))
        self.ant = {"setups": tuple(ac.get("setups", ("orb", "trend_break", "vwap_trend"))), "ttl_min": float(ac.get("ttl_min", 2)),
                    "buffer_atr5": float(ac.get("buffer_atr5", 0.10)), "reach_atr5": float(ac.get("reach_atr5", 1.5)),
                    # the 5m-close confirmation stays as a fallback: a breakout the read only backs once it happens
                    # (conviction often arrives with the break) is still taken, later, rather than missed
                    "confirm_fallback": bool(ac.get("confirm_fallback", True))}
        self.tick_sec = float(ac.get("tick_sec", 5))
        self.armed: dict[str, list] = {}
        self.last_px: dict[str, tuple] = {}
        self._last_s: dict[str, dict] = {}
        self._tick_fails = 0
        self._tick_retry = None
        self.live_fails = 0
        self.think_every = ic.get("thought_every_min", 5)
        self.stale_min = ic.get("chain_stale_min", 12)
        self.history_days = ic.get("history_days", 6)
        self.expiry_min_days = ic.get("expiry_min_days", 1)
        self.review_dir = review_dir
        self.news = news                                  # NewsDesk (live headlines) or None
        self.brain = brain                                # Brain (global markets ↔ news ↔ India ↔ decision) or None
        self.brain_state: dict = {}
        self.last_action: dict[str, str] = {}
        qc = cfg.get("intraday.quant", {}) or {}
        self.qc = qc
        self.quant_on = bool(qc.get("enabled", True))
        # a directional trade needs a plan model approved on real point-in-time evidence (autolearn/research.py)
        self.require_model = bool(cfg.get("autolearn.require_approved_model", True))
        # paper-only exploration (ships off): while no plan model is approved, a directional plan that passes every other
        # gate may trade at `lots`, capped, labelled unvalidated and kept out of the paper gate (_explore_off)
        xc = ic.get("exploration", {}) or {}
        try:
            until = pd.Timestamp(str(xc["until"])).date() if xc.get("until") else None
        except (TypeError, ValueError):
            until = dt.date.min                                  # an unreadable end date is an expired one
        self.explore = {"enabled": bool(xc.get("enabled", False)), "max_per_day": int(xc.get("max_per_day", 2)),
                        "lots": max(1, int(xc.get("lots", 1))), "max_total": int(xc.get("max_total", 40)), "until": until}
        self._explore_said = False
        self.volf = VolForecaster()
        # intraday.vol_forecast.mode (off | shadow): vol_forecast_v1's HAR forecast is recorded beside the desk's own at the
        # opening read, to be graded later (`intraday vol-shadow`). Nothing reads it: it is not an input to any decision.
        self.volshadow = VolShadow(cfg, journal)
        self.ev = EVEngine(cfg, self.pricer, broker.costs, n_paths=int(qc.get("n_paths", 2000)))
        self.models: dict[str, DirectionModel] = {}
        self.hist5: dict[str, pd.DataFrame] = {}
        self.qstate: dict[str, dict] = {}
        self._pcache: dict[str, tuple] = {}
        self._qc_cache: dict[str, dict] = {}
        self._qerrors: set = set()
        self.research = load_research(Path(cfg.runtime_dir) / "research" / "edges.json") if self.quant_on else {}
        self.bars: dict[str, pd.DataFrame] = {}
        self.last_ts: dict[str, pd.Timestamp] = {}
        self.chain_df: dict[str, pd.DataFrame] = {}
        self.chain_an: dict[str, dict] = {}
        self.chainflow = ChainFlow()                      # how each chain moved since the first read (chainflow.py)
        self.breadth = None                               # breadth.Breadth (the index's own stocks; live with Kotak) or None
        self.breadth_state: dict[str, dict | None] = {}
        self.rel: dict | None = None                      # BANKNIFTY vs NIFTY (relstrength.py)
        self.hist_edge: dict[str, dict] = {}              # the warehouse research's buyer's edge for today, per underlying
        # the self-learning loop (quantdesk/autolearn): LiveLearner or None (replays, tests). It records every model's
        # prediction per 5-minute bar before the outcome is known; a promoted champion's signal gates entries.
        self.learner = None
        self.learn_sig: dict[str, dict | None] = {}
        # fail-closed halts: a kill-switch file, a stale feed, an unverifiable model, a journal that fails its check
        self.kill_file = Path(cfg.runtime_dir) / str(ic.get("kill_switch_file", "KILL"))
        self.killed = False
        self.stale_feed_min = float(ic.get("stale_feed_min", 3))
        self.journal_fault: str | None = None
        self.halt: dict | None = None                     # an inherited position awaits the owner (halt.py; H-02/H-03)
        # engine health: failures, slow steps, the reconciliation of broker vs journal, safe mode (all in the heartbeat)
        self.max_step_failures = int(ic.get("max_step_failures", 3))
        self.slow_step_sec = float(ic.get("slow_step_sec", 40))
        self.health: dict = {"step_errors": 0, "consecutive_failures": 0, "last_error": None, "slow_steps": 0,
                             "last_step_sec": None, "safe_mode": None, "reconcile": None}
        self.chain_at: dict[str, pd.Timestamp] = {}               # when a chain refresh last succeeded (throttle) ...
        self.chain_ok_at: dict[str, pd.Timestamp] = {}            # ... and the age `_blocked` vetoes on (P1-4)
        self.chain_fail: dict[str, int] = {}
        self.chain_tried: dict[str, pd.Timestamp] = {}
        self.chain_failed_at: dict[str, pd.Timestamp] = {}        # a refresh that raised: retried after `refresh_min`, not every minute
        self._exit_tried: dict[str, pd.Timestamp] = {}            # trade id -> its last exit attempt (`_close`, `_retry_exit`)
        self.fallback_since: dict[str, pd.Timestamp] = {}         # index -> when its real chain went down (said once per outage)
        self.lot_mismatch: dict[str, tuple[int, int]] = {}        # P2-6: underlying -> (configured lot, exchange mktLot) while they differ
        self._lot_said: dict[str, tuple[int, int]] = {}           # the pair last reported (one event per pair per session)
        # P2-9 (owner decision 16 Oct: 10%): a drawdown from the account's high-water mark that halts new entries across
        # days until the owner clears it (`quantdesk intraday clear-drawdown-halt`); exits are never held by it.
        self.dd_halt_frac = float(cfg.get("intraday.risk.cross_day_drawdown_halt", 0) or 0)
        self.dd_halt: dict | None = None
        self.peak_equity: float | None = None
        self.expiry: dict[str, dt.date] = {}
        self.open_trades: list[Trade] = []
        self.closed: list[Trade] = []
        self.views: dict[str, MarketView] = {}
        self.late_start: set[str] = set()                         # indices whose data began after the open (B-10)
        self.last_thought: dict[str, pd.Timestamp] = {}
        self.last_bias: dict[str, str] = {}
        self.flow = {u: FootprintBuilder(float(cfg.instrument_spec(u).get("tick", 0.05))) for u in self.underlyings}
        self.feature_cache: dict[str, dict] = {u: {} for u in self.underlyings}
        self.day: dt.date | None = None
        self.day_start_equity = broker.cash()
        self.paused = bool(journal.get_state("intraday_paused", False))
        self.events_today: list[str] = []
        from .events import EventBook, from_config
        self.eventbook = EventBook(from_config(cfg))
        self.warehouse_dir = Path(cfg.runtime_dir) / "warehouse"
        self.iv_hist: dict[str, pd.DataFrame] = {}        # past year's ATM IV per underlying (ivhist.py)
        self.fut_hist: dict[str, list] = {}               # today's futures snapshots per underlying: (ts, ltp, oi)
        self._fut_fails = 0
        self.gift_source = None                           # callable → parse_gift frame (live only); None = skip
        # learning (learning.py): every call is graded against what the market did next; the record moves factor
        # weights, news trust and setup conviction within bounds. None: the desk doesn't learn (tests, one-offs).
        self.memory = memory
        self.learned_today: dict = {}
        self._record_said: dict = {}
        self._apply_memory()
        self.gift: dict | None = None
        self._gift_at = None
        self._gift_fails = 0

    # ---- helpers ----------------------------------------------------------------------------------
    def lot(self, u: str) -> int:
        return int(self.cfg.instrument_spec(u).get("lot_size", 1))

    def model_state(self, u: str, ts) -> tuple[float, float]:
        """Spot and ATM IV for the model chain: last 1m close, India VIX × iv_beta."""
        df = self.bars[u]
        S = float(df.loc[:ts]["close"].iloc[-1])
        v = self.bars.get(self.vix)
        c = v.loc[:ts]["close"] if v is not None else pd.Series(dtype=float)
        c = c[c > 0]                                            # I-01: a 0 / NaN VIX print would price at zero vol
        vix = float(c.iloc[-1]) if len(c) else 14.0
        return S, vix / 100 * float(self.cfg.instrument_spec(u).get("iv_beta", 1.0))

    def pick_expiry(self, u: str, today: dt.date) -> dt.date:
        try:
            exps = self.chains.expiries(u, today) if isinstance(self.chains, ModelOptionChain) else self.chains.expiries(u)
        except Exception as exc:
            spec = self.cfg.instrument_spec(u)
            exps = self.cal.expiries(today, 70, int(spec.get("expiry_weekday", 1)), bool(spec.get("weekly_expiry", True)))
            self.journal.event(pd.Timestamp.now(tz=IST), "WARN", "chain", f"{u} expiries from calendar ({exc})")
        exps = [e for e in exps if (e - today).days >= self.expiry_min_days]
        return exps[0]

    def equity(self, now) -> float:
        val = 0.0
        for t in self.open_trades:
            S = self.spot(t.symbol)
            val += sum(l.qty * self.marker.mid(l.instrument, S, now) for l in t.legs if l.exit_price is None)
        return self.broker.cash() + val

    def spot(self, u: str) -> float:
        return float(self.bars[u]["close"].iloc[-1])

    # ---- session lifecycle ------------------------------------------------------------------------------
    def start_session(self, day: dt.date) -> None:
        self.day = day
        self._lot_said.clear()                                # a lot mismatch is reported once per session
        for sym in self.underlyings + [self.vix]:
            h = self.feed.history(sym, self.history_days)
            self.bars[sym] = h.tail(375 * self.history_days) if h is not None else \
                pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            self.last_ts[sym] = h.index[-1] if h is not None and len(h) else None
            self._backfill_recorder(sym, h, day)
        self.expiry = {u: self.pick_expiry(u, day) for u in self.underlyings}
        self._learn(day, catch_up=True)
        self._load_heavyweights()
        self._load_iv_history(day)
        if self.brain is not None:                        # FII positioning and cash flows: context for the narrative
            from .brain import load_flows
            try:
                self.brain.flows = load_flows(self.warehouse_dir, day, Path(self.cfg.runtime_dir) / "research")
            except Exception:
                self.brain.flows = None
        self._load_hist_edge(day)
        self._check_journal(day)
        if self.learner is not None:
            try:
                self.learner.start(day)
            except Exception as exc:                          # unreadable registry: no model steers, no entries
                self.learner.fault = f"learning registry unreadable: {exc!s:.160}"
            if self.learner.fault:
                self.journal.event(session_bounds(day)[0], "ERROR", "autolearn", f"entries halted: {self.learner.fault}")
            elif self.learner.active:
                self.journal.event(session_bounds(day)[0], "INFO", "autolearn",
                                   f"champion {self.learner.champion_id} steers entries"
                                   + (f" (drift {self.learner.drift.get('state')})" if self.learner.drift else ""))
        self._explore_off(session_bounds(day)[0])                   # live + exploration on: the CRITICAL goes on the record now
        self.events_today = self.eventbook.describe(day, self.cal.prev_trading_day(day))
        saved = self._restore(day)
        self._reconcile(day)
        self._check_inherited(day)
        if saved.get("day_start_equity"):
            self.day_start_equity = float(saved["day_start_equity"])
            self.risk.reset(day, self.day_start_equity)
            r = saved.get("risk") or {}
            self.risk.trades_today = int(r.get("trades_today", len(self.closed) + len(self.open_trades)))
            self.risk.consec_losses, self.risk.halted = int(r.get("consec_losses", 0)), bool(r.get("halted", False))
            self.risk.cool_until = pd.Timestamp(r["cool_until"]) if r.get("cool_until") else None
        else:
            self.day_start_equity = self.broker.cash() + sum(t.entry_cost for t in self.open_trades)
            self.risk.reset(day, self.day_start_equity)
            self.risk.trades_today = len([t for t in self.closed if t.opened_at.date() == day]) + len(self.open_trades)
        self._drawdown_check(session_bounds(day)[0], self.day_start_equity)
        self._gov_safe(self._gov_start, day)
        if self.quant_on:
            self._train_models(day)
        try:
            self.volshadow.start_session(day, session_bounds(day)[0], self.underlyings)
        except Exception as exc:                                   # the shadow may never stop a session from starting
            log.warning("vol shadow could not start: %r", exc)
            try:                                                   # ...and on the record, so the report can count it
                self.journal.event(self.feed.now(), "WARN", "quant", f"vol shadow could not start: {exc!r:.160}")
            except Exception:
                pass
        exp = ", ".join(f"{u} {e:%d-%b}" for u, e in self.expiry.items())
        self.say(f"── session {day} · capital ₹{self.day_start_equity:,.0f} · expiries {exp} · chain {self.chains.name} "
                 f"· feed {self.feed.name}{' · events: ' + ', '.join(self.events_today) if self.events_today else ''}")
        self.journal.event(session_bounds(day)[0], "INFO", "session", f"session start; expiries {exp}; chain {self.chains.name}",
                           {**_provenance(), "started_at": str(pd.Timestamp.now(tz="Asia/Kolkata"))})
        if getattr(self.memory, "corrupt", None):              # C-10: said every session until the owner restores the file
            self.journal.event(session_bounds(day)[0], "ERROR", "learning",
                               f"learning memory unreadable ({self.memory.corrupt}): the desk trades on neutral tilts and "
                               f"saves nothing over the file; restore memory.json from the journal branch's evidence")

    def _backfill_recorder(self, sym: str, hist, day: dt.date) -> None:
        """P2-10: a runner that starts mid-day (the afternoon one, a restart) gets the minutes it missed in its history,
        so the recorder (which keeps only what poll() returns) had a hole there; fill today's missing minutes. Data only."""
        if self.recorder is None or hist is None or not len(hist):
            return
        try:
            n = self.recorder.fill_bars(sym, hist[hist.index.date == day])
            if n:
                self.journal.event(pd.Timestamp.now(tz=IST), "INFO", "session", f"{sym}: {n} bar(s) from history added to today's record")
        except Exception as exc:                                  # a recorder fault must never stop the session starting
            log.warning("recorder backfill %s: %s", sym, exc)

    def step(self) -> bool:
        now = self.feed.now()
        self._commands(now)
        self._kill_switch(now)
        got = False
        for sym in self.underlyings + [self.vix]:
            new = self.feed.poll(sym, self.last_ts.get(sym))
            if new is None or new.empty:
                continue
            self.bars[sym] = pd.concat([self.bars.get(sym), new]) if sym in self.bars and len(self.bars[sym]) else new
            self.last_ts[sym] = new.index[-1]
            if self.anticipate and not self.live_px and sym in self.underlyings:
                for ts, b in new.iterrows():                   # no live price: each new bar's range decides the armed orders
                    self._fire_armed(sym, now, bar=(float(b["open"]), float(b["high"]), float(b["low"])))
            if self.recorder:
                rec_new = new
                if hasattr(type(self.feed), "unrecorded"):      # minutes served from Kite stay out of the recorder: its licence is the subscriber's, and the recording reaches public artifacts
                    rec_new = new[~new.index.isin(list(self.feed.unrecorded(sym)))]
                self.recorder.record_bars(sym, rec_new)
                fb = getattr(self.feed, "fut_bars", {}).get(sym)
                if fb is not None and len(fb):                  # the futures' own bars, for the chart and replays
                    self.recorder.record_bars(f"{sym}-FUT", fb[fb.index.date == fb.index[-1].date()])
            got = got or sym in self.underlyings
        if self.feed.has_ticks:
            for u in self.underlyings:
                for t in self.feed.trades(u):
                    self.flow[u].add(t)
        self._gov_safe(self._gov_step, now)
        if not got:
            self._wallclock_exits(now)                    # no new bar is no reason to hold a position past the square-off
            return False
        early, tried, fails = self._manage_first(now)          # exits before the optional network refreshes (P2-2)
        try:
            self._refresh_optional(now)
            for u in self.underlyings:                             # one index's failure must not starve the other (P2-2)
                try:
                    self._step_underlying(u, now, early, tried)
                except Exception as exc:
                    self._step_failed(u, now, exc, fails)
        finally:                                               # the square-off happens whatever failed above (P2-2)
            self._wallclock_exits(now)
        self._snapshot(now)
        self._persist()
        self._heartbeat(now)
        self.journal.commit()
        if fails:                                              # the step finished for everyone else; run_step still counts it
            raise fails[0]
        return True

    def _refresh_optional(self, now) -> None:
        self._refresh_news(now)
        self._short_legs(now)
        if self.brain is not None and self.brain.gfeed is not None:
            self._guarded("global", now, "global refresh", self.brain.gfeed.refresh, now)
        if self.brain is not None and getattr(self.brain, "hfeed", None) is not None:
            self._guarded("global", now, "heavyweights refresh", self.brain.hfeed.refresh, now)
        if self.breadth is not None:
            self._guarded("breadth", now, "breadth refresh", self.breadth.refresh, now)
        from .relstrength import PAIR, rel_strength
        if all(x in self.underlyings for x in PAIR):
            self.rel = self._guarded("pair", now, "relative strength", rel_strength, self.bars.get(PAIR[0]),
                                     self.bars.get(PAIR[1]), self.day, now)

    def _manage_first(self, now) -> tuple[dict, set, list]:
        """Exits for open trades come first: refresh the chain they are marked on and run `_manage`, before the news,
        global, heavyweights and breadth refreshes (steps of 51 s and 65 s were logged; exits waited behind that I/O).
        -> (exits by index, indices whose chain was just refreshed, failures)."""
        early, tried, fails = {}, set(), []
        for u in self.underlyings:
            if not any(t.symbol == u for t in self.open_trades) or u not in self.bars or self.bars[u].empty \
                    or self.bars[u].index[-1].date() != self.day:
                continue
            try:
                self._refresh_chain(u, now)
                tried.add(u)
                early[u] = self._manage(u, SimpleNamespace(spot=self.spot(u)), now)
            except Exception as exc:
                self._step_failed(u, now, exc, fails)
        return early, tried, fails

    def _step_failed(self, u: str, now, exc: Exception, fails: list) -> None:
        """One index's work failed: journal it, keep going, and hand the failure to `step` to re-raise at the end so
        `run_step` counts it (a persistent failure still ends in safe mode)."""
        log.exception("%s step failed", u)
        self.journal.event(now, "WARN", "engine", f"{u}: this minute's work failed, carrying on with the rest: {exc!r:.200}",
                           {"where": _where(exc)})
        fails.append(exc)

    def _step_underlying(self, u: str, now, early: dict, tried: set) -> None:
        if u not in self.bars or self.bars[u].empty or self.bars[u].index[-1].date() != self.day:
            return
        if u not in tried:
            self._refresh_chain(u, now)
        s = session_state(self.bars[u], now, cache=self.feature_cache[u])
        if s is None:
            return
        if not s.get("from_open", True) and u not in self.late_start:
            self.late_start.add(u)                           # once a session: self-review files it (D-07)
            first = self.bars[u][self.bars[u].index.date == self.day].index[0]
            self.journal.event(now, "WARN", "data", f"{u}: the opening bars failed to arrive (today's data starts "
                               f"{first:%H:%M}), so the analyst stands aside while they are missing")
        if self.learner is not None:                         # every model's prediction, before the outcome exists
            self.learn_sig[u] = self._guarded(u, now, "learning record", self._learn_step, u, now)
        q = self._guarded(u, now, "quant state", self._quant_state, u, now) if self.quant_on else None
        if q is not None and self.volshadow.on:
            self._vol_shadow(u, now, q)
        b = self._guarded(u, now, "brain", self._think_globally, u, now) if self.brain is not None else None
        blk = self.eventbook.blocking(now)                   # only an announcement inside the session blocks
        br = self.breadth_state[u] = self.breadth.state(u, s.get("chg"), now) if self.breadth is not None else None
        view = self.analyst.assess(u, s, self.chain_an.get(u), self._vix_state(), self.expiry[u] == self.day,
                                   blk.label() if blk else None, self._flow_state(u, now),
                                   self.news.state(u, now) if self.news is not None else None, q,
                                   {"evidence": b.evidence, "narrative": b.narrative} if b is not None else None,
                                   breadth=br, rel=self.rel, hist_edge=self.hist_edge.get(u))
        self.views[u] = view
        self._last_s[u] = s
        exits = early[u] if u in early else self._manage(u, view, now)    # an open trade was managed first
        action = self._maybe_enter(u, view, s, now)
        if self.anticipate:
            action = self._arm(u, view, s, now, action)
        self._think(u, view, now, "; ".join(exits + [action]) if exits else action, force=bool(exits))

    def _wallclock_exits(self, now) -> None:
        """What must happen by the clock, bar or no bar: a stuck exit is retried, and past the square-off time every
        open position is closed (P1-2: with polls returning nothing from 14:50 the trade sat open to the end of the day)."""
        for t in list(self.open_trades):
            if t.meta.get("exit_pending"):
                self._retry_exit(t, now)
            elif now.time() >= self.risk.square_off:
                self._close(t, now, "square_off", f"intraday square-off at {self.risk.square_off:%H:%M}")

    def _open_risk(self) -> float:
        """What the open trades can still lose to their stops, in rupees (their initial risk: the conservative figure)."""
        return float(sum(max(float(getattr(t, "initial_risk", 0.0) or 0.0), 0.0) for t in self.open_trades))

    def _retry_exit(self, t, now) -> str:
        """Finish an exit already under way, once per moment: `_manage`, the wall clock and `tick` all reach for it, and a
        stuck 2-leg spread would otherwise be sent to the broker twice (each retry is already guarded by the broker-held
        quantity, so this saves traffic, not safety). `_close` stamps every attempt, so a fresh exit that `_manage` or the
        wall clock just sent and left stuck is not sent again in the same moment. Cadence is unchanged: every step, every tick."""
        last = self._exit_tried.get(t.id)
        if last is not None and abs((now - last).total_seconds()) < 2:
            return ""
        self._exit_tried[t.id] = now
        return self._close(t, now, *t.meta["exit_pending"])

    def end_session(self, reason: str = "square_off", note: str = "end of session") -> str:
        now = self.feed.now()
        for u in {t.symbol for t in self.open_trades} - set(self.chain_df):
            self._refresh_chain(u, now)                 # exits priced off a calibrated chain, never a default IV
        for t in list(self.open_trades):
            self._close(t, now, reason, note)
        if self.learner is not None:
            self.learner.resolve({u: self.bars.get(u) for u in self.underlyings}, now)
        try:
            self._say_frozen(now)
        except Exception as e:                            # a note about the feed must never cost the close
            self.journal.event(now, "WARN", "data", f"frozen-bar check failed: {type(e).__name__}: {e}")
        self._check_cash(now)
        self._learn(self.day)
        review = self.session_review()
        review += self._reflect(review, now)
        self.journal.event(now, "INFO", "session_review", review[:2000])
        self._persist(ended=True)
        self.journal.commit()
        if self.review_dir:
            self.review_dir.mkdir(parents=True, exist_ok=True)
            (self.review_dir / f"{self.day}.md").write_text(review, encoding="utf-8")
        return review

    # ---- data -------------------------------------------------------------------------------------------
    def _refresh_chain(self, u: str, now) -> None:
        at, failed = self.chain_at.get(u), self.chain_failed_at.get(u)
        if not refresh_due(now, at, self.refresh_min):
            return
        if not refresh_due(now, failed, self.refresh_min):
            return                                            # the last refresh raised: a retry throttle, not a freshness claim
        try:
            ch = None
            fails = self.chain_fail.get(u, 0)
            tried = self.chain_tried.get(u)
            # after 3 straight failures, only retry the real chain every 15 minutes (each try can block ~20s)
            if self.chains is not self.model_chain and (fails < 3 or refresh_due(now, tried, 15)):
                self.chain_tried[u] = now
                try:
                    ch = self.chains.chain(u, self.expiry[u], spot=self.spot(u), ts=now)
                    if fails >= 3:
                        self.journal.event(now, "INFO", "chain", f"{u} {self.chains.name} chain is back")
                    self.chain_fail[u] = 0
                except Exception as exc:
                    # NSE blocks many cloud IPs, throttles, or is down: the desk must not stop because of it.
                    # Price off the model chain (India VIX + skew) and say so in the journal.
                    n = self.chain_fail[u] = fails + 1
                    if n == 1 or n % 10 == 0:
                        self.journal.event(now, "WARN", "chain", f"{u} {self.chains.name} chain unavailable ({exc!s:.160}); "
                                                               f"pricing off the model chain (India VIX)"
                                                               f"{f' — {n} failures in a row' if n > 1 else ''}")
            if ch is None:
                ch = self.model_chain.chain(u, self.expiry[u], spot=self.spot(u), ts=now)
            if not ch.attrs.get("spot") or ch.attrs["spot"] != ch.attrs["spot"]:
                ch.attrs["spot"] = self.spot(u)
            ch = fill_iv(ch, self.pricer)
            self.chain_df[u] = ch
            self._check_lot(u, ch, now)
            if self.chains is self.model_chain or ch.attrs.get("source") != "model":
                # P2-4: a model chain standing in for a failed real one (VIX x beta IV, not this market's) must not
                # recalibrate the marks of open positions; the replay's own model chain is the market and still does.
                # Before the optional analytics (P1-4): an error there must not leave the marks on a stale IV.
                self.marker.calibrate(ch, self.lot(u))
            an = chain_analytics(ch, self.pricer, self.lot(u))
            if ch.attrs.get("source") != "model":             # the model chain's IV is India VIX's, not this market's
                an.update(iv_percentile(self.iv_hist.get(u), an.get("atm_iv"), (self.expiry[u] - now.date()).days, now.date()))
            an.update(self._futures(u, now, an.get("spot")))
            an.update(self.chainflow.update(u, an, now, chain_step(ch)))
            self.chain_an[u] = an
            self.chain_at[u] = self.chain_ok_at[u] = now          # only a refresh that worked counts (P1-4)
            self.chain_failed_at.pop(u, None)
            self._say_fallback(u, ch, now)
            if self.recorder and ch.attrs.get("source") != "model":
                self.recorder.record_chain(ch)
        except Exception as exc:                              # chain_at/chain_ok_at stay: the data is as old as its last success
            self.chain_failed_at[u] = now
            self.journal.event(now, "WARN", "chain", f"{u} chain refresh failed: {exc}")

    def _say_fallback(self, u: str, ch: pd.DataFrame, now) -> None:
        """F-01 on the record: while a configured real chain (Kotak) is down and the data is the fallback's (NSE or the
        model), entries are skipped on purpose. Said once per outage, not every minute; the next outage says it again."""
        down = self._real_book() and ch.attrs.get("source") != self.chains.name
        if not down:
            self.fallback_since.pop(u, None)
            return
        if u not in self.fallback_since:
            self.fallback_since[u] = now
            self.journal.event(now, "WARN", "execution", f"{u}: no new entries while the {self.chains.name} chain is down; "
                               f"entries are skipped on purpose and the data is from the {ch.attrs.get('source')} fallback "
                               f"(exits and marks carry on)", {"source": ch.attrs.get("source")})

    def _check_lot(self, u: str, ch: pd.DataFrame, now) -> None:
        """P2-6: the configured lot against the exchange's (Kotak's `mktLot`). Orders are sized in the configured multiple, so
        a lot NSE has revised would put every order in the wrong size: no new entry on `u` until the owner updates the config
        (never adopted silently; exits are untouched). An unknown lot (no `mktLot`, a model or NSE chain) vetoes nothing."""
        raw = ch.attrs.get("lot") if ch.attrs.get("source") != "model" else None
        try:
            real = int(raw) if raw is not None and float(raw) > 0 else 0
        except (TypeError, ValueError):
            real = 0
        cfg_lot = self.lot(u)
        if not real or real == cfg_lot:
            self.lot_mismatch.pop(u, None)
            return
        pair = self.lot_mismatch[u] = (cfg_lot, real)
        if self._lot_said.get(u) != pair:
            self._lot_said[u] = pair
            self.journal.event(now, "ERROR", "data", f"{u} lot size mismatch: config says {cfg_lot} but the exchange (Kotak mktLot) "
                               f"says {real}; no new entries on {u} until instruments.{u}.lot_size is corrected", {"config": cfg_lot, "exchange": real})

    def _refresh_news(self, now) -> None:
        if self.news is None:
            return
        try:
            fresh = self.news.refresh(now)
        except Exception as exc:                          # the desk trades without news rather than not at all
            self.journal.event(now, "WARN", "news", f"news refresh failed: {exc!s:.160}")
            return
        if fresh:
            self.journal.news_add(fresh, now)
            hot = [x for x in fresh if x.impact == "high" and max(x.about.values() or [0]) >= self.news.min_relevance]
            for x in hot:
                self.say(f"  {now:%H:%M} NEWS ({x.source}) {x.title} [tone {x.sentiment:+.2f}]")
        for x in self.news.collect():                     # language models' reads that arrived since (llm.py)
            self.journal.news_set_nlp(x.id, x.nlp)

    def _think_globally(self, u: str, now):
        df = self.bars[u]
        today = df[df.index.date == self.day]
        prior = df[df.index.date < self.day]
        gap = float(np.log(today["open"].iloc[0] / prior["close"].iloc[-1])) if len(today) and len(prior) else None
        items = list(self.news.items.values()) if self.news is not None else None
        tone = (lambda x: self.news.item_tone(x, u, now)) if self.news is not None else None
        r30 = None
        if len(today) > 30:
            r30 = float(np.log(today["close"].iloc[-1] / today["close"].iloc[-31]))
        st = self.brain.think(u, now, items, gap, tone=tone, index_r30=r30)
        self.brain_state[u] = st
        return st

    def _vix_state(self) -> dict | None:
        v = self.bars.get(self.vix)
        if v is None or v.empty:
            return None
        today = v[v.index.date == self.day]
        prev = v[v.index.date < self.day]
        # I-01: a 0 VIX is a bad print, not a -100% move: no valid reading today, or a prior day of only bad prints, is
        # no state (and no ZeroDivisionError)
        today, pc = today[today["close"] > 0], prev["close"][prev["close"] > 0]
        if today.empty or (len(prev) and pc.empty):
            return None
        base = float(pc.iloc[-1]) if len(pc) else float(today["open"].iloc[0])
        if not base > 0:
            return None
        return {"last": float(today["close"].iloc[-1]), "chg": float(today["close"].iloc[-1]) / base - 1}

    def _flow_state(self, u: str, now) -> dict | None:
        fb = self.flow.get(u)
        if not self.feed.has_ticks or fb is None or not fb.bars:
            return None
        recent = [b for b in fb.bars if b.start >= now - pd.Timedelta(minutes=30)]
        if not recent:
            return None
        st = recent[-1].stacked
        return {"source": "ticks", "delta_30": sum(b.delta for b in recent), "volume_30": sum(b.volume for b in recent),
                "stacked_buy": st["buy"], "stacked_sell": st["sell"]}

    # ---- trading ------------------------------------------------------------------------------------------
    # ---- anticipation: arm at the level, fire in real time -----------------------------------------------------
    @property
    def live_px(self) -> bool:
        """A live price between minutes (Kotak's quotes) that is working; otherwise (replays, bar-only feeds, or the
        quotes failing) each new bar's range decides the armed orders."""
        return bool(getattr(self.feed, "has_ltp", False)) and self._tick_fails < 3

    def _arm(self, u: str, view: MarketView, s: dict, now, action: str) -> str:
        """Re-arm this underlying's anticipated setups from the minute's read; say what's waiting in the thought."""
        self.armed[u] = []
        if self._blocked(u, view, now) or not action.startswith("watching"):
            return action
        q = self.qstate.get(u) or {}
        why = (f"{view.bias} read (score {view.score:+.2f}, conviction {view.conviction:.2f}"
               + (f", model P(up) {q['p_model']:.2f}" if q.get("valid") and q.get("p_model") is not None else "") + ")")
        self.armed[u] = self.playbook.arm(view, s, now, ttl_min=self.ant["ttl_min"], buffer_atr5=self.ant["buffer_atr5"],
                                          reach_atr5=self.ant["reach_atr5"], setups=self.ant["setups"], why=why)
        if not self.armed[u]:
            return action
        return "armed: " + "; ".join(a.describe() for a in self.armed[u])

    def _fire_armed(self, u: str, now, price: float | None = None, bar: tuple | None = None) -> str | None:
        """Fire the first armed setup the price (or the new bar's range) reached, through the same gates as any entry."""
        live = [a for a in self.armed.get(u, []) if now <= a.expires]
        view, s = self.views.get(u), self._last_s.get(u)
        if not live or view is None or s is None:
            return None
        for a in live:
            S = (price if a.hit(price) else None) if price is not None else a.bar_fill(*bar)
            if S is None:
                continue
            self.armed[u] = []                                  # one shot per read: re-armed on the next minute
            why = self._blocked(u, view, now)
            if why:
                return None
            chain = self._chain_at(u, float(S), now)            # priced where the trade fills, not a minute ago
            plan = self.playbook.fire(a, view, chain, now, S)
            if plan is None:
                return None
            kept, stop = self._by_record(u, [plan], view, now)
            if not kept:
                self._think(u, view, now, f"{a.setup} reached its level {a.level:,.2f} but {stop}", force=True)
                return None
            kept, stop = self._model_gates(u, kept, now)        # the same model gates as any other entry
            if not kept:
                msg = f"{a.setup} reached its level {a.level:,.2f} but {stop}"
                # on the decision record only: this minute's read isn't formed yet, so no thought on last minute's
                self.journal.decision(now, a.setup, u, "rejected", msg, 0, {"armed": a.to_record(), "plan": plan.describe()})
                return msg
            plan = kept[0]
            at_s = replace(view, spot=float(S))
            eq = self.equity(now)
            appr = self._approved(u, kept, eq, now)
            if appr is not None:
                if isinstance(appr, str):
                    self._think(u, view, now, appr, force=True)
                    return appr
                plan, lots, notes = appr
                msg = self._open(plan, lots, notes, at_s, s, now)
                self._think(u, at_s, now, msg, force=True)
                return msg
            if self.quant_on:
                pick = self._guarded(u, now, "EV selection", self._select_by_ev, u, [plan], at_s, eq, now, chain)
                if pick is None or isinstance(pick, str):
                    msg = f"{a.setup} reached its level {a.level:,.2f} but " + (pick or "the quant layer failed")
                    self.journal.decision(now, a.setup, u, "rejected", msg, 0,
                                          {"armed": a.to_record(), "target": plan.target_underlying, "regime": view.day_type})
                    self._think(u, view, now, msg, force=True)
                    return msg
                plan, lots, notes = pick
            else:
                lots, notes = self.risk.size(plan, eq, self.broker.cash(), self._open_risk())
                if lots < 1:
                    self.journal.decision(now, plan.setup, u, "rejected", " | ".join(notes), 0, {"plan": plan.describe()})
                    return None
            msg = self._open(plan, lots, notes, at_s, s, now)
            self._think(u, at_s, now, msg, force=True)
            return msg
        return None

    def _chain_at(self, u: str, S: float, now) -> pd.DataFrame:
        """The last chain repriced to underlying price S: each strike's bid/ask/LTP moves by its Black-Scholes value
        change at its own IV (the live book, when there is one, still sets the actual fill)."""
        from ..options.pricing import bs_price
        ch = self.chain_df[u]
        S0 = float(ch.attrs.get("spot") or S)
        if abs(S - S0) < 1e-9:
            return ch
        out = ch.copy()
        out.attrs = {**ch.attrs, "spot": float(S)}
        T = max(time_to_expiry(now, ch.attrs["expiry"]), 1 / 365 / 24)
        K = ch.index.to_numpy(dtype=float)
        for side, right in (("ce", "CE"), ("pe", "PE")):
            iv = ch[f"{side}_iv"].to_numpy(dtype=float) / 100
            ok = iv > 0
            shift = np.zeros(len(K))
            shift[ok] = (bs_price(S, K[ok], T, self.pricer.r, self.pricer.q, iv[ok], right)
                         - bs_price(S0, K[ok], T, self.pricer.r, self.pricer.q, iv[ok], right))
            for f in ("bid", "ask", "ltp"):
                col = out[f"{side}_{f}"]
                out[f"{side}_{f}"] = np.where(col > 0, np.maximum(col + shift, 0.05), col)
        return out

    def tick(self) -> bool:
        """Between minute steps: the live index price fires armed entries the moment price gets there and checks open
        positions' stops and targets in real time. A no-op without a realtime feed or anything to watch."""
        if not (getattr(self.feed, "has_ltp", False) and self.day):
            return False
        if self.open_trades and self.feed.now().time() >= self.risk.square_off:
            n = len(self.open_trades)
            self._wallclock_exits(self.feed.now())        # the square-off is the clock's, not the next bar's
            if len(self.open_trades) < n:
                self._persist()
                self.journal.commit()
                return True
        want = [u for u in self.underlyings if self.armed.get(u) or any(t.symbol == u for t in self.open_trades)]
        if not want:
            return False
        now = self.feed.now()
        if self._tick_fails >= 3 and self._tick_retry and now < self._tick_retry:
            return False                                         # failing: the minute bars decide; retry once a minute
        try:
            px = self.feed.ltp(want) or {}
            if self._tick_fails >= 3:
                self.journal.event(now, "INFO", "quotes", "live index price is back: armed orders fire in real time again")
            self._tick_fails = 0
        except Exception as exc:
            self._tick_fails += 1
            self._tick_retry = now + pd.Timedelta(minutes=1)
            if self._tick_fails == 3:
                self.journal.event(now, "WARN", "quotes", f"live index price unavailable ({exc!s:.160}); armed orders "
                                                          f"fire on the minute bars until it's back")
            return False
        did = False
        for u, p in px.items():
            if not (p and p == p):
                continue
            self.last_px[u] = (now, float(p))
            fired = self._fire_armed(u, now, price=float(p)) if self.anticipate else None
            view = self.views.get(u)
            exits = self._manage(u, replace(view, spot=float(p)), now) if view is not None else []
            if exits:
                self._think(u, replace(view, spot=float(p)), now, "; ".join(exits), force=True)
            did = did or bool(fired or exits)
        if did:
            self._persist()
            self._heartbeat(now)
            self.journal.commit()
        return did

    def _short_legs(self, now) -> None:
        """Buyer only until the account can carry the margin a sold leg needs; say so when it changes."""
        ok = self.short_from is not None and self.equity(now) >= self.short_from
        if ok != self.playbook.allow_short or not hasattr(self, "_short_said"):
            self._short_said = True
            if not ok:
                self.journal.event(now, "INFO", "mode", "buyer only: long calls and puts, no sold legs (spreads, flies) "
                                   + (f"until equity reaches ₹{self.short_from:,.0f}" if self.short_from is not None else "(selling off)"))
            elif self.playbook.allow_short is False:
                self.journal.event(now, "INFO", "mode", f"equity ₹{self.equity(now):,.0f} ≥ ₹{self.short_from:,.0f}: spreads and "
                                                         f"defined-risk selling are back on")
        self.playbook.allow_short = ok

    # ---- learning ---------------------------------------------------------------------------------------------
    def _apply_memory(self) -> None:
        """Hand what the record says to the parts that use it. The factor record (weights, graduation) goes to the
        analyst and the brain to show; they apply it only under intraday.learning.apply_factor_weights (D-01)."""
        if self.memory is None:
            return
        from .analyst import PROBATION, PROMOTE_N, PROMOTE_REL
        from .earn_in import Gate
        from .learning import apply_factor_weights
        try:
            self.earn_gate = Gate(self.memory, self.cfg)
        except Exception as exc:                          # the gate failing must not stop the desk: nothing is earned
            log.exception("earn-in gate failed")
            self.earn_gate = None
            try:
                self.journal.event(self.feed.now(), "WARN", "learning", f"earn-in gate failed, nothing learned is "
                                   f"applied through it this session: {exc!r:.160}")
            except Exception:
                pass
        gate = self.earn_gate
        if gate is not None and gate.mode == "apply":
            # Only what earned its place reaches trading; every other learned tilt is 1.0x (earn_in.py).
            self.analyst.learned = gate.factor_weights()
            self.analyst.apply_learned = True
            self.analyst.graduated = {f for f in PROBATION if gate.earned("factor", f)
                                      and (self.memory.stat("factor", f) or {"n": 0})["n"] >= PROMOTE_N
                                      and self.memory.reliability("factor", f) >= PROMOTE_REL}
            if self.brain is not None:
                self.brain.apply_learned = True
                self.brain.learned = {k: (self.memory.reliability("factor", k), float(r["n"]))
                                      for k, r in (self.memory.d["tables"].get("factor") or {}).items()
                                      if k.startswith(("global_", "heavy_")) and gate.earned("factor", k)}
            if self.news is not None:
                self.news.trust = gate.news_trust
                self.news.reader_trust = lambda name: gate.reliability("news_reader", name)
        else:
            # As before the gate, and with the config's own switch: an apply-mode gate that failed after an earlier
            # success must not leave apply_learned on, or the raw, unearned record would reach trading.
            self.analyst.apply_learned = apply_factor_weights(self.cfg)
            if self.brain is not None:
                self.brain.apply_learned = apply_factor_weights(self.cfg)
            self.analyst.learned = self.memory.factor_weights()
            self.analyst.graduated = {f for f in PROBATION if (self.memory.stat("factor", f) or {"n": 0})["n"] >= PROMOTE_N
                                      and self.memory.reliability("factor", f) >= PROMOTE_REL}
            if self.brain is not None:                    # probation drivers earn a vote on their live record
                self.brain.learned = {k: (self.memory.reliability("factor", k), float(r["n"]))
                                      for k, r in (self.memory.d["tables"].get("factor") or {}).items()
                                      if k.startswith(("global_", "heavy_"))}
            if self.news is not None:
                self.news.trust = self.memory.news_trust
                self.news.reader_trust = lambda name: self.memory.reliability("news_reader", name)
        if gate is not None and gate.mode != "off":
            try:                                          # a note about the gate must never cost the engine's start
                self.journal.event(self.feed.now(), "INFO", "learning", gate.summary(),
                                   {"mode": gate.mode, "earned": gate.earned_items()})
            except Exception:
                log.exception("earn-in summary not journaled")

    def _say_frozen(self, now) -> None:
        """F-02: one WARN per index whose bars froze today (Kotak's index series sits flat 15:15-15:28 while the future
        trades); grading masks those minutes. A vendor's freeze, not the desk's fault, so not worded as a failure."""
        for u in self.underlyings:
            b = self.bars.get(u)
            f = frozen_minutes(b[b.index >= session_bounds(self.day)[0]]) if b is not None and len(b) else []
            if not len(f):
                continue
            new = np.r_[True, (f[1:] - f[:-1]) != pd.Timedelta(minutes=1)]   # a new span wherever a minute is skipped
            spans = list(zip(f[new], f[np.r_[new[1:], True]]))
            self.journal.event(now, "WARN", "data", f"{u}: index bars frozen " + ", ".join(
                f"{a:%H:%M}-{z:%H:%M}" for a, z in spans) + f" ({len(f)} minutes), kept out of grading",
                {"symbol": u, "spans": [[str(a), str(z)] for a, z in spans]})

    def _learn(self, day, catch_up: bool = False) -> None:
        """Grade the day's calls (news, each read's factors, trades, refused pre-break entries) against the bars that
        followed, save the memory and re-weight. At the start of a session it catches up on anything a crashed close
        left ungraded."""
        if self.memory is None:
            return
        from . import learning
        try:
            if not catch_up:                              # the buyer's edge: realised vs the open's implied vol
                for u in self.underlyings:
                    learning.record_move(self.memory, day, u, self.bars.get(u), self.chainflow.opening(u))
            got = learning.grade_session(self.memory, self.journal, {u: self.bars.get(u) for u in self.underlyings}, day)
            self.memory.save()
        except Exception as exc:                          # learning must never cost a session
            self.journal.event(pd.Timestamp.now(tz=IST), "WARN", "learning", f"grading failed: {exc!s:.200}")
            return
        self._apply_memory()
        if not catch_up:
            self.learned_today = got
        if any(got.values()):
            self.journal.event(pd.Timestamp.now(tz=IST), "INFO", "learning",
                               ("caught up: " if catch_up else "graded: ") + ", ".join(f"{v} {k}" for k, v in got.items()),
                               got)

    def _reflect(self, review: str, now) -> str:
        """After the close: Claude reads the review and the record and writes the lessons (for the human and the
        memory; nothing here touches orders or risk). Also what the language models cost today."""
        desk = getattr(self.news, "llm", None) if self.news is not None else None
        if desk is None or not desk.active:
            return ""
        out = []
        claude = next((r for r in desk.readers if r.name == "claude"), None)
        try:
            hold = (desk.budget.deny("reflect") if claude is not None and desk.budget is not None else None)   # '' = used up
        except Exception as exc:                      # can't check the credit: Claude skipped (fail closed), the close goes on
            hold = ""
            log.warning("claude budget check failed, reflection skipped: %s", exc)
        if claude is not None and self.cfg.get("intraday.llm.claude.reflect", True) and hold is None:
            from .learning import summary
            try:
                from .teacher import advisory_lines          # yesterday's teaching, labelled advisory: context, never a rule
                got = claude.reflect(review, (summary(self.memory, factor_weights_applied=self.analyst.apply_learned)
                                              if self.memory is not None else []) + advisory_lines(self.journal))
            except Exception as exc:
                got = None
                self.journal.event(now, "WARN", "llm", f"reflection failed: {exc!s:.200}")
            if getattr(claude, "charge_error", None):
                desk.errors["claude"] = claude.charge_error
            if got and (got["lessons"] or got["watch_tomorrow"]):
                out += ["", "## Reflection (Claude, after the close)", ""] + [f"- {x}" for x in got["lessons"]]
                if got["watch_tomorrow"]:
                    out += ["", "Watch at tomorrow's open:"] + [f"- {x}" for x in got["watch_tomorrow"]]
                if self.memory is not None:
                    self.memory.d["lessons"].append({"day": str(self.day), **got})
                    self.memory.save()
        from .llm import BUDGET_NOTE, cost_line
        lc = self.cfg.get("intraday.llm", {}) or {}
        prices = {k: {"in": (lc.get(k) or {}).get("price_in", 0), "out": (lc.get(k) or {}).get("price_out", 0),
                      "cr": (lc.get(k) or {}).get("price_cache_read", 0), "cw": (lc.get(k) or {}).get("price_cache_write", 0)}
                  for k in ("claude", "gemini", "ollama") if (lc.get(k) or {}).get("price_in") is not None}
        cost = cost_line(desk.usage(), prices)
        try:
            bl = desk.budget.line() if desk.budget is not None else ""
        except Exception as exc:                      # a display: never abort the session close
            bl = ""
            log.warning("claude budget line failed: %s", exc)
        if cost or desk.errors or bl:
            line = "Language models today: " + (cost or "no calls") + (
                "; problems: " + "; ".join(f"{k}: {v}" for k, v in desk.errors.items()) if desk.errors else "") + (
                f". {bl}" if bl else "")
            out += ["", line]
            self.journal.event(now, "INFO", "llm", line, {"usage": desk.usage(), "errors": desk.errors})
            failed = {k: v for k, v in desk.errors.items() if not str(v).startswith(("daily cap",) + BUDGET_NOTE)}
            if failed:                                    # G-05: at WARN too, so self-review files it (D-07)
                self.journal.event(now, "WARN", "llm", "language model reads failed: " + "; ".join(
                    f"{k}: {v}" for k, v in failed.items())[:200], {"errors": failed})
        return "\n".join(out)

    def _by_record(self, u: str, plans: list, view: MarketView, now) -> tuple[list, str | None]:
        """Each setup's own record of R (by day type when it has one) scales its conviction, and a clearly losing
        record stands it aside, but only under intraday.learning.apply_factor_weights (D-01): a stood-aside setup takes
        no more trades, so its record could never recover. A fresh desk changes nothing."""
        if self.memory is None:
            return plans, None
        kept, stop = [], None
        for p in plans:
            gate = getattr(self, "earn_gate", None)
            m, why = (gate.setup_mult(p.setup, view.day_type) if gate is not None and gate.mode == "apply"
                      else self.memory.setup_mult(p.setup, view.day_type, self.analyst.apply_learned))
            if why:
                stop = stop or f"its record says no: {why}"
                said = self._record_said.get((u, p.setup))
                if said is None or now - said >= pd.Timedelta(minutes=15):    # once per setup per 15 minutes
                    self._record_said[(u, p.setup)] = now
                    self.journal.decision(now, p.setup, u, "rejected", f"track record: {why}", 0, {"plan": p.describe()})
                continue
            if m != 1.0:
                p.notes["track_record"] = f"conviction ×{m:.2f} from its past trades"
                p.conviction = float(min(1.0, max(0.0, p.conviction * m)))
            kept.append(p)
        return kept, stop

    def _by_relative_strength(self, u: str, plans: list) -> list:
        """Which index: once the record shows the leader of the last 30 minutes keeps leading (relstrength.py), a plan
        long the laggard or short the leader has its conviction cut, and one with the leader gets a small lift. Until
        then nothing changes."""
        if self.memory is None or self.rel is None:
            return plans
        from .relstrength import preference, record
        rec = record(self.memory)
        for p in plans:
            got = preference(u, p.direction, self.rel, rec)
            if got:
                m, note = got
                p.notes["relative_strength"] = note
                p.conviction = float(min(1.0, max(0.0, p.conviction * m)))
        return plans

    def _blocked(self, u: str, view: MarketView, now) -> str | None:
        """Why no new entry can be taken right now (None: one can)."""
        if self.killed:
            return f"halted: kill switch ({self.kill_file.name}) is set"
        if gap := self.cfg.holiday_gap(now):
            return f"halted: {gap}"
        if self.health.get("safe_mode"):
            return f"halted: safe mode ({self.health['safe_mode']})"
        if (self.health.get("reconcile") or {}).get("ok") is False:
            return f"halted: broker and journal disagree ({self.health['reconcile']['detail']})"
        if self.halt:
            return f"halted: inherited position awaits the owner ({summary(self.halt)}); clear with `{CLEAR_CMD}`"
        if self.journal_fault:
            return f"halted: {self.journal_fault}"
        if self.dd_halt:
            return (f"halted: equity ₹{self.dd_halt['equity']:,.0f} is {self.dd_halt['drawdown']:.1%} below its peak "
                    f"₹{self.dd_halt['peak']:,.0f} (limit {self.dd_halt_frac:.0%}); the owner clears it with "
                    f"`quantdesk intraday clear-drawdown-halt --reason \"…\"`")
        if self.learner is not None and self.learner.fault:
            return f"halted: {self.learner.fault}"
        if self.paused:
            return "standing aside: new entries paused from the app"
        last = self.last_ts.get(u)
        if last is not None and self.feed.realtime_age(now, last) > self.stale_feed_min:
            return f"halted: {u} feed stale (last bar {last:%H:%M}, {self.feed.realtime_age(now, last):.0f} min ago)"
        if view.vetoes:
            return f"standing aside: {view.vetoes[0]}"
        if u not in self.chain_df:
            return "standing aside: no option chain"
        if self.chains is not self.model_chain and self.chain_df[u].attrs.get("source") == "model":
            # F-01: the real chain failed and the model stands in; its quotes and OI are invented, not tradable
            return f"standing aside: {u} {self.chains.name} option chain unavailable (model prices are not tradable)"
        if u in self.lot_mismatch:
            cfg_lot, real = self.lot_mismatch[u]
            return f"halted: {u} lot size mismatch (config {cfg_lot}, exchange {real}); the owner corrects instruments.{u}.lot_size"
        age = now - (self.chain_ok_at.get(u) or self.chain_df[u].attrs.get("ts", now))   # the data's age, not the last try's
        if self.chain_df[u].attrs.get("source") != "model" and age > pd.Timedelta(minutes=self.stale_min):
            return f"standing aside: option chain {age.seconds // 60} min old"
        gate = self.risk.gate(now, self.equity(now), self.open_trades, u)
        return f"standing aside: {gate[0]}" if gate else None

    def _maybe_enter(self, u: str, view: MarketView, s: dict, now) -> str:
        why = self._blocked(u, view, now)
        if why:
            return why
        eq = self.equity(now)
        skip = self.ant["setups"] if self.anticipate and not self.ant["confirm_fallback"] else ()
        plans = self.playbook.scan(view, s, self.chain_df[u], now, skip=skip)
        if not plans:
            return "watching: no setup has triggered"
        plans, stop = self._by_record(u, plans, view, now)
        if not plans:
            return f"standing aside: {stop}"
        plans = self._by_relative_strength(u, plans)
        plans, why = self._model_gates(u, plans, now)
        if not plans:
            return why
        approved = self._approved(u, plans, eq, now)
        if approved is not None:
            if isinstance(approved, str):
                return approved
            plan, lots, notes = approved
            return self._open(plan, lots, notes, view, s, now)
        if self.quant_on:
            pick = self._guarded(u, now, "EV selection", self._select_by_ev, u, plans, view, eq, now)
            if pick is None:
                return "standing aside: the quant layer failed on this minute (see events)"
            if isinstance(pick, str):
                return pick
            plan, lots, notes = pick
            return self._open(plan, lots, notes, view, s, now)
        plan = max(plans, key=lambda p: p.conviction)
        lots, notes = self.risk.size(plan, eq, self.broker.cash(), self._open_risk())
        if lots < 1:
            self.journal.decision(now, plan.setup, u, "rejected", " | ".join(notes), 0, {"plan": plan.describe()})
            return f"setup {plan.setup} found but sized to 0 lots ({notes[-1]})"
        return self._open(plan, lots, notes, view, s, now)

    def _model_gates(self, u: str, plans: list, now) -> tuple[list, str | None]:
        """Every entry path's model gates. A directional plan needs the approved plan model
        (autolearn.require_approved_model); an active direction champion may then only narrow what's left."""
        why = None
        if self.require_model:                                # no directional trade without an approved plan model
            if self.learner is None:
                plans, why = [p for p in plans if p.direction == 0], ("standing aside: no approved plan model (the learning "
                                                                    "loop is off); directional reads stay advisory")
            else:
                gated, why = self.learner.plan_gate(u, plans, now)
                if self.learner.plan is None and any(p.direction for p in plans):     # dropped for want of ANY approved model
                    gated, why = self._explore(u, plans, gated, why, now)
                plans = gated
            if not plans:
                return [], why
        if self.learner is not None:                          # an active champion: only setups its signal agrees with
            plans, why2 = self.learner.entry_filter(u, plans)
            if why2:
                return [], why2
        return plans, why

    def _explore_off(self, now) -> str | None:
        """Why an exploration entry may not be taken now (None: it may). Paper only, ahead of an approved plan model,
        inside its caps; the counts come from the journal's trades, so a restart can't reset them (unreadable: off)."""
        x = self.explore
        if not x["enabled"]:
            return "exploration is off"
        if self.cfg.get("account.mode") != "paper" or not isinstance(self.broker, IntradayBroker):
            if not self._explore_said:
                self._explore_said = True
                self.journal.event(now, "CRITICAL", "exploration", "exploration is enabled but this is not the paper account "
                                   "(account.mode / broker): it never enters outside paper trading")
            return "exploration is paper only"
        if self.learner is None or self.learner.plan is not None:
            return "an approved plan model is steering (or the learning loop is off)"
        if not self.quant_on:
            return "the quant layer (the EV floor) is off"
        if x["until"] is not None and now.date() > x["until"]:
            return f"exploration ended {x['until']}"
        try:
            at = self.journal.df("SELECT opened_at FROM trades WHERE json_extract(meta, '$.mode') = 'exploration'")["opened_at"]
        except Exception as exc:
            return f"exploration trades unreadable ({exc!s:.60})"
        if len(at) >= x["max_total"]:
            return f"exploration spent its {x['max_total']} trades"
        if int((at.astype(str).str[:10] == str(now.date())).sum()) >= x["max_per_day"]:
            return f"exploration took its {x['max_per_day']} for today"
        return None

    def _explore(self, u: str, plans: list, kept: list, why: str | None, now) -> tuple[list, str | None]:
        """plan_gate dropped the directional plans because no plan model is approved: when exploration is on and allowed,
        they go on (tagged, unvalidated) to the champion filter, risk sizing, the EV floor and the live-book checks."""
        off = self._explore_off(now)
        if off:
            return kept, (why if not self.explore["enabled"] else f"{why} [{off}]")
        for p in (p for p in plans if p.direction):
            p.notes["mode"] = "exploration"
        return [p for p in plans if p.direction == 0 or p.notes.get("mode") == "exploration"], None

    def _approved(self, u: str, plans: list, eq: float, now):
        """The approved plan model's best plan, sized by the risk engine: (plan, lots, notes), a reason it can't be sized,
        or None when no plan carries an approval. Its expected value is the validated one, so there's no Monte Carlo on an
        unvalidated P(up) and no alternative structure it didn't approve."""
        approved = [p for p in plans if p.notes.get("plan_model")]
        if not approved:
            return None
        plan = max(approved, key=lambda p: p.notes["plan_model"]["ev_R"])
        pm = plan.notes["plan_model"]
        lots, notes = self.risk.size(plan, eq, self.broker.cash(), self._open_risk())
        if lots < 1:
            self.journal.decision(now, plan.setup, u, "rejected", " | ".join(notes), 0, {"plan": plan.describe()})
            return f"setup {plan.setup} approved by the plan model but sized to 0 lots ({notes[-1]})"
        plan.notes["quant_text"] = (f"plan model {pm['model_id']} ({pm['horizon']}, DTE {pm['bucket']}): expected "
                                    f"{pm['ev_R']:+.2f}R, P(net>0) {pm['p_win']:.0%}")
        return plan, lots, notes + [plan.notes["quant_text"]]

    # ---- quant layer --------------------------------------------------------------------------------------------
    def preopen(self, now) -> None:
        """Before the open, every few minutes: GIFT Nifty (NSE IX's NIFTY future, trading since 06:30 IST), the
        overnight cue in one number. Recorded with the session; context for the read, not evidence (untested)."""
        if self.gift_source is None or not refresh_due(now, self._gift_at, 4):
            return
        self._gift_at = now
        from ..data.nse import gift_implied_gap
        try:
            g = self.gift_source()
        except Exception as exc:
            self._gift_fails += 1
            if self._gift_fails == 1:
                self.journal.event(now, "WARN", "gift", f"GIFT Nifty unavailable ({exc!s:.160})")
            return
        if g is None or g.empty:
            return
        r = g.iloc[0]
        gap = gift_implied_gap(float(r["last"]), float(r["nifty_close"]), r["expiry"], now.date(),
                               self.cfg.get("backtest.risk_free", 0.065), self.cfg.get("backtest.dividend_yield", 0.012))
        first = self.gift is None
        self.gift = {"ts": str(r["ts"]), "last": float(r["last"]), "pct": float(r["pct"]),
                     "nifty_close": float(r["nifty_close"]), "implied_gap": gap, "taken": str(now)}
        self.journal.set_state("intraday_gift", self.gift)
        if self.recorder is not None:
            path = self.recorder.day_dir(now.date()) / "gift.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame([self.gift]).to_csv(path, mode="a", header=not path.exists(), index=False)
        if first:
            self.journal.event(now, "INFO", "gift", f"GIFT Nifty {r['last']:,.1f} ({pd.Timestamp(r['ts']):%H:%M}): "
                                                   f"implies a {gap:+.2%} open for NIFTY after carry")

    def _load_heavyweights(self) -> None:
        """Results dates for the index heavyweights from the warehouse's copy of NSE's event calendar (live.yml pulls
        it); context only. Silently nothing when the file isn't there."""
        from .events import EventBook, from_config, heavyweight_results, load_corp_events
        try:
            corp = load_corp_events(self.warehouse_dir)
        except Exception:
            corp = None
        heavy = sorted({s for u in self.underlyings for s in (self.cfg.get(f"intraday.heavyweights.{u}") or [])})
        self.eventbook = EventBook(from_config(self.cfg) + heavyweight_results(corp, heavy))

    def _futures(self, u: str, now, spot) -> dict:
        """The near-month future right now (Kotak): basis, carry and the 30-minute OI build-up (futures.py)."""
        fut = getattr(self.feed, "fut", None)
        if fut is None or not getattr(self.feed, "has_futures", False) or u == self.vix:
            return {}
        try:
            snap = fut.snapshot(u, self.day)
            self._fut_fails = 0
        except Exception as exc:
            self._fut_fails += 1
            if self._fut_fails in (1, 30):
                self.journal.event(now, "WARN", "futures", f"{u} futures snapshot failed ({exc!s:.160})")
            return {}
        h = self.fut_hist.setdefault(u, [])
        if snap["ltp"] > 0 and snap["oi"] > 0 and spot and spot == spot and (not h or h[-1][0] < now):
            h.append((now, snap["ltp"], snap["oi"], float(spot)))
        from .futures import read
        out = read(h, float(spot) if spot else float("nan"), now, snap["expiry"], snap["symbol"])
        if snap.get("oi_prev") and snap["oi_prev"] > 0:
            out["fut_oi_vs_prev"] = float(snap["oi"] / snap["oi_prev"] - 1)
        nxt = snap.get("next")
        if nxt and nxt.get("ltp", 0) > 0:
            out["fut_calendar"] = float(nxt["ltp"] - snap["ltp"])
        return out

    def _load_iv_history(self, day: dt.date) -> None:
        """Each underlying's past year of ATM IV from the warehouse's bhavcopy (live.yml pulls 13 months), for the
        IV percentile in the read. Context only: without the files the read simply has no percentile."""
        from .ivhist import load
        try:
            self.iv_hist = load(self.warehouse_dir, self.underlyings, self.pricer.r, self.pricer.q, self.expiry_min_days, day)
        except Exception as exc:
            self.iv_hist = {}
            self.journal.event(session_bounds(day)[0], "WARN", "quant", f"ATM IV history unavailable ({exc!s:.160})")
        if self.iv_hist:
            self.journal.event(session_bounds(day)[0], "INFO", "quant", "ATM IV history for the IV percentile: " +
                               ", ".join(f"{u} {len(h)} sessions to {h['date'].iloc[-1]}" for u, h in self.iv_hist.items()))

    def _learn_step(self, u: str, now) -> dict | None:
        """The learning loop's record for `u`'s last completed 5-minute bar (and the champion's decision on it)."""
        df = self.bars[u]
        c = self._qc_cache.get(u)
        if c is None or c["day"] != self.day:
            prior = df[df.index.date < self.day]
            h5 = self.hist5.get(u)
            last5 = h5[h5.index.date == h5.index.date[-1]] if h5 is not None and len(h5) else None
            prev_close = float(prior["close"].iloc[-1]) if len(prior) else float("nan")
            prev_sig = session_sigma(last5["close"].to_numpy(dtype=float)) if last5 is not None and len(last5) else float("nan")
        else:
            prev_close, prev_sig = c["prev_close"], c["prev_sig"]
        return self.learner.on_bar(u, now, df, self.day, prev_close, prev_sig)

    def _reconcile(self, day) -> None:
        """Broker positions must equal the legs of the journal's open trades. Anything else (a crash between a fill and
        its journal entry, a hand-edited file) halts new entries until it's explained: fail closed, say exactly what."""
        want, have = book_diff(self.open_trades, self.broker.positions() or {})
        diff = {k: (want.get(k, 0), have.get(k, 0)) for k in set(want) | set(have) if want.get(k, 0) != have.get(k, 0)}
        self._check_cash(session_bounds(day)[0])
        acc = accepted_halt(self.journal) if diff else {}
        if ok := {k: v for k, v in diff.items() if leg_key(k, *v) in acc}:   # the owner's forced clear took these as is
            rec = next(iter(acc.values()))                # one record: the last clear accepted them all
            self.journal.event(session_bounds(day)[0], "WARN", "risk",
                               f"reconciliation: {len(ok)} leg(s) left as the owner accepted them ({rec.get('by')}, "
                               f"{str(rec.get('at'))[:16]}: {str(rec.get('reason'))[:120]}): "
                               + "; ".join(f"{k}: journal {w:+d} vs broker {h:+d}" for k, (w, h) in sorted(ok.items())),
                               {"accepted": sorted(ok)})
            diff = {k: v for k, v in diff.items() if k not in ok}
        if not diff:
            self.health["reconcile"] = {"ok": True, "positions": len(have)}
            return
        detail = "; ".join(f"{k}: journal {w:+d} vs broker {h:+d}" for k, (w, h) in sorted(diff.items()))[:300]
        self.health["reconcile"] = {"ok": False, "detail": detail}
        self.journal.event(session_bounds(day)[0], "CRITICAL", "risk", f"reconciliation failed, entries halted: {detail}",
                           {"journal": want, "broker": have})
        self.say(f"  RECONCILIATION FAILED: {detail}")

    def _check_cash(self, at) -> None:
        """C-09: paper cash must equal the account's capital less every fill's value and fees. A gap means P&L or cash
        was booked without a fill (an unjournaled unwind, a leg marked closed with no order): an ERROR on the record
        (it counts against the paper gate), never a halt."""
        try:
            cap = float((self.journal.get_state("intraday_account") or {}).get("capital") or 0)
            if cap <= 0:
                return
            row = self.journal.df("SELECT COALESCE(SUM(qty * price), 0) AS q, COALESCE(SUM(fees), 0) AS f FROM fills")
            expect = cap - float(row["q"].iloc[0]) - float(row["f"].iloc[0])
            cash = float(self.broker.cash())
        except Exception as exc:                          # a check must never cost the session
            log.warning("cash reconciliation skipped: %r", exc)
            return
        gap = cash - expect
        self.health["cash_reconcile"] = {"ok": abs(gap) <= 1.0, "gap": round(gap, 2)}
        if abs(gap) > 1.0:
            self.journal.event(at, "ERROR", "reconcile", f"paper cash ₹{cash:,.2f} differs from capital less fills "
                               f"₹{expect:,.2f} by ₹{gap:+,.2f}: P&L or cash was booked without a fill",
                               {"cash": cash, "expected": expect, "gap": gap})

    def _check_inherited(self, day) -> None:
        """H-02/H-03, owner decision "flag + manual": an orphan broker leg, a trade carried over from another day (a
        stuck exit included) or an expired leg nobody settled is named in a CRITICAL event and halts new entries until
        the owner clears it (`quantdesk intraday clear-halt`). The halt is kept in the journal's state, so a restart,
        the hand-over or the next day doesn't forget it. Nothing is closed, adopted or settled here; exits of the
        trades the journal holds for today run as before. A clean start (books agree, nothing carried) does nothing."""
        t0 = session_bounds(day)[0]
        items = inherited(self.journal, self.broker.positions() or {}, day, self.open_trades, first_seen=t0)
        if acc := accepted_halt(self.journal):
            prune_accepted(self.journal, {i["key"] for i in items})
            items = [i for i in items if i["key"] not in acc]
        prev = self.journal.get_state(HALT_KEY)
        if not items and not prev:
            self.halt = None
            return
        prev = prev or {"raised_at": str(t0), "items": []}
        cur = {i["key"]: i for i in items}
        known = [cur.get(i["key"], i) for i in prev["items"]]          # as it stands today, or as it was last seen
        fresh = [i for i in items if i["key"] not in {k["key"] for k in known}]
        again = known if prev.get("announced") != str(day) else []    # once a day while the halt stands
        for i in again:
            gone = "" if i["key"] in cur else " (no longer present: the owner can clear the halt)"
            self.journal.event(t0, "CRITICAL", "risk", f"entries still halted since {str(prev['raised_at'])[:16]}, "
                               f"awaiting `{CLEAR_CMD}`: {i['detail']}{gone}", i)
        for i in fresh:
            self.journal.event(t0, "CRITICAL", "risk", f"inherited position, entries halted until the owner clears it "
                               f"(`{CLEAR_CMD}`): {i['detail']}", i)
        self.halt = {**prev, "items": known + fresh, "announced": str(day)}
        self.journal.set_state(HALT_KEY, self.halt)
        for i in again + fresh:
            self.say(f"  ENTRIES HALTED: {i['detail']}")

    def enter_safe_mode(self, now, reason: str) -> None:
        """The engine keeps failing: stop new entries for the session and square off what's open (each exit on its
        own, so one bad leg can't block the rest)."""
        if self.health.get("safe_mode"):
            return
        self.health["safe_mode"] = reason[:200]
        flat = 0
        for t in list(self.open_trades):
            try:
                self._close(t, now, "safe_mode", f"safe mode: {reason[:120]}")
                flat += t not in self.open_trades         # an exit a leg of which didn't fill is still open (H-01)
            except Exception as exc:                      # recorded; the next one is still tried
                self.journal.event(now, "CRITICAL", "risk", f"safe mode could not close {t.id}: {exc!r:.160}")
        try:
            self._persist()
        except Exception:
            pass
        still = len(self.open_trades)
        self.journal.event(now, "CRITICAL", "risk", f"safe mode: {reason[:200]}; {flat} position(s) squared off"
                           + (f", {still} still open (exit retried)" if still else "") + ", entries halted")
        self.journal.commit()
        self.say(f"  {now:%H:%M} SAFE MODE: {reason[:120]}")

    def _kill_switch(self, now) -> None:
        """The file-based kill switch: present → flatten every paper position once and take no new entries."""
        on = self.kill_file.exists()
        if on and not self.killed:
            for t in list(self.open_trades):
                self._close(t, now, "kill_switch", f"kill switch {self.kill_file.name} set: flattened")
            self.journal.event(now, "CRITICAL", "risk", f"kill switch {self.kill_file} set: positions flattened, entries halted")
            self.say(f"  {now:%H:%M} KILL SWITCH: flattened, no new entries")
        elif self.killed and not on:
            self.journal.event(now, "WARN", "risk", "kill switch cleared: entries allowed again")
        self.killed = on

    def _check_journal(self, day) -> None:
        """Fail closed on a journal that doesn't pass SQLite's own check."""
        try:
            res = self.journal.integrity()
        except Exception as exc:
            res = f"unreadable ({exc!s:.80})"
        self.journal_fault = None if res == "ok" else f"journal integrity check failed: {res}"
        if self.journal_fault:
            self.journal.event(session_bounds(day)[0], "CRITICAL", "risk", self.journal_fault)

    def _load_hist_edge(self, day: dt.date) -> None:
        """The warehouse research's buyer's edge (research.sh fetches buyer_edge.json) for today's weekday and the days
        to the expiry each underlying trades: what five years say about buying the ATM straddle at this point."""
        from ..research.warehouse_research import edge_for
        self.hist_edge = {}
        try:
            table = json.loads((Path(self.cfg.runtime_dir) / "research" / "buyer_edge.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for u in self.underlyings:
            e = self.expiry.get(u)
            if e is not None:
                got = edge_for(table, u, day, self.cal.trading_days_between(day, e))
                if got:
                    self.hist_edge[u] = got

    def _live(self, insts, now) -> dict[str, tuple[float, float]]:
        """Bid/ask right now from the broker's book when the chain source has one; {} otherwise (or on an error),
        and the plan's chain prices / the marks stand in."""
        try:
            out = self.chains.live_quotes(insts) if hasattr(self.chains, "live_quotes") else {}
            self.live_fails = 0
            return out or {}
        except Exception as exc:
            self.live_fails += 1
            if self.live_fails == 1 or self.live_fails % 10 == 0:
                self.journal.event(now, "WARN", "quotes", f"live quotes unavailable ({exc!s:.160}); "
                                                          f"using the last chain{f' — {self.live_fails} in a row' if self.live_fails > 1 else ''}")
            return {}

    def _real_book(self) -> bool:
        """The chain source is a broker's book (Kotak), as opposed to the model chain: there, no live quote means no entry."""
        return self.chains is not self.model_chain and (self.chains.name == "kotak" or bool(getattr(self.chains, "book", False)))

    def _leg_liquidity(self, u: str, insts, legs, live: dict) -> list[str]:
        """Each leg's book at entry, from the live quotes or else the last chain: e.g. '25000CE ok 0.4%'."""
        ch = self.chain_df.get(u)
        out = []
        for inst, leg in zip(insts, legs):
            if inst.symbol in live:
                b, a = live[inst.symbol]
            elif ch is not None and leg.strike in ch.index:
                b, a = ch.at[leg.strike, f"{leg.right.lower()}_bid"], ch.at[leg.strike, f"{leg.right.lower()}_ask"]
            else:
                b = a = float("nan")
            flag = liquidity(b, a)
            out.append(f"{leg.strike:g}{leg.right} {flag}" + (f" {(a - b) / ((a + b) / 2):.1%}" if flag != "no quote" else ""))
        return out

    def _guarded(self, u: str, now, what: str, fn, *args):
        """Run a quant step; on an error, journal it (once per session per kind) and return None so the desk keeps
        thinking and simply doesn't trade on numbers it couldn't compute."""
        try:
            return fn(*args)
        except Exception as exc:
            key = (self.day, u, what)
            if key not in self._qerrors:
                self._qerrors.add(key)
                log.exception("%s failed", what)
                self.journal.event(now, "ERROR", "quant", f"{u} {what} failed: {exc!r:.200}", {"where": _where(exc)})
            return None

    def _vol_shadow(self, u: str, now, q: dict) -> None:
        """Record the HAR forecast beside the desk's (volshadow.py). Read-only on everything the engine decides with."""
        try:
            self.volshadow.step(u, now, self.bars[u], q.get("rv_ann"), (self.chain_an.get(u) or {}).get("atm_iv"),
                                q.get("sigma_30m_pct"))
        except Exception as exc:
            key = (self.day, u, "vol shadow")
            if key not in self._qerrors:
                self._qerrors.add(key)
                try:
                    self.journal.event(now, "WARN", "quant", f"{u} vol shadow failed (no decision is affected): {exc!r:.200}")
                except Exception:                      # the shadow's own report of a failure must not itself stop the step
                    log.exception("vol shadow failed and could not be journaled")

    def _train_models(self, day) -> None:
        """Fit each underlying's direction model on sessions before `day` only, and say how it tested."""
        for u in self.underlyings:
            try:
                h = self.feed.history_bars(u, int(self.qc.get("train_days", 55)))
                h = h[h.index.date < day] if h is not None and len(h) else pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            except Exception as exc:
                h = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
                self.journal.event(session_bounds(day)[0], "WARN", "quant", f"{u}: no 5m history for the model ({exc!s:.120})")
            self.hist5[u] = h
            m = DirectionModel(min_auc=float(self.qc.get("min_auc", 0.53)))
            diag = m.fit(features_5m(h)) if len(h) else m.diag
            self.models[u] = m
            msg = (f"{u} direction model: {diag.get('status')}"
                   + (f" (walk-forward AUC {diag['auc_oos']:.3f}, log-loss skill {diag['logloss_skill_oos']:+.2%}, "
                      f"{diag['samples']:,} samples over {diag['days']} days)" if "auc_oos" in diag else
                      f" ({diag.get('samples', 0)} samples, {diag.get('days', 0)} days)"))
            self.journal.event(session_bounds(day)[0], "INFO", "quant", msg)
            self.say("  " + msg)

    def _quant_state(self, u: str, now) -> dict:
        df = self.bars[u]
        c = self._qc_cache.get(u)
        if c is None or c["day"] != self.day:                      # locate today's rows once per session
            prior = df[df.index.date < self.day]
            h5 = self.hist5.get(u)
            last5 = h5[h5.index.date == h5.index.date[-1]] if h5 is not None and len(h5) else None
            c = self._qc_cache[u] = {"day": self.day, "start": len(prior),
                                     "prev_close": float(prior["close"].iloc[-1]) if len(prior) else float("nan"),
                                     "prev_sig": session_sigma(last5["close"].to_numpy(dtype=float)) if last5 is not None else float("nan"),
                                     "volf": VolForecaster()}
        today = df.iloc[c["start"]:]
        m = self.models.get(u)
        p_model = None
        n5 = len(today) // 5                                        # completed 5m bars (features change only then)
        if m is not None and m.w is not None and n5 > 0:
            cached = self._pcache.get(u)
            if cached and cached[0] == (self.day, n5):
                p_model = cached[1]
            else:
                five = to_5m(today.iloc[:n5 * 5])
                f = features_5m(five, c["prev_close"], c["prev_sig"])
                p_model = m.predict(f.iloc[-1])
                self._pcache[u] = ((self.day, n5), p_model)
        an = self.chain_an.get(u) or {}
        vol = c["volf"].forecast(df, self.day, an.get("atm_iv"), today_close=today["close"].to_numpy(dtype=float))
        d = (m.diag if m is not None else {}) or {}
        ls = self.learn_sig.get(u) if self.learner is not None and self.learner.active else None
        if ls is not None:                                    # a promoted, verified champion replaces the session fit
            p_model = ls["p"] if ls["signal"] else 0.5
            card = self.learner.reg.card(self.learner.champion_id) or {}
            vm = ((card.get("validation") or {}).get("metrics") or {}).get("classification") or {}
            d = {"auc_oos": vm.get("auc"), "samples": (card.get("training_window") or {}).get("rows"),
                 "status": f"champion {self.learner.champion_id}" + (" (abstaining)" if not ls["signal"] else "")}
            m = _Valid()
        rd = (self.research.get(u) or {}).get("drift")
        q = {"sigma_min": vol["sigma_min"], "sigma_30m_pct": vol["sigma_30m"] * 100, "vol_ann": vol["vol_ann"], "research_drift": rd,
             "rv_ann": vol["rv_ann"], "vol_source": vol["source"], "p_model": p_model, "valid": bool(m is not None and m.valid),
             "auc": d.get("auc_oos"), "samples": d.get("samples"), "model_status": d.get("status")}
        self.qstate[u] = q
        return q

    def _p_up(self, u: str, view) -> tuple[float, str]:
        q = self.qstate.get(u) or {}
        if q.get("valid") and q.get("p_model") is not None:
            return float(np.clip(q["p_model"], 0.35, 0.65)), f"direction model (AUC {q['auc']:.3f})"
        tilt = float(self.qc.get("prior_tilt", 0.10))
        return float(0.5 + np.clip(tilt * view.score, -tilt, tilt)), "prior tilt from the analyst's score (unvalidated)"

    def _select_by_ev(self, u: str, plans: list, view, eq: float, now, chain: pd.DataFrame | None = None):
        """Price every plan and its alternative structures by Monte Carlo; trade the best EV per rupee of risk
        that the account can hold and that clears the EV floor. Otherwise say why not."""
        q = self.qstate.get(u) or {}
        if not q.get("sigma_min"):
            return "standing aside: no volatility forecast yet"
        p_up, p_src = self._p_up(u, view)
        close = pd.Timestamp(dt.datetime.combine(self.day, self.risk.square_off), tz=IST)
        minutes_left = (close - now).total_seconds() / 60
        floor_inr, floor_r = float(self.qc.get("min_ev_inr", 40)), float(self.qc.get("min_ev_r", 0.05))
        cands = []
        for plan in plans:
            variants = [plan] + self.playbook.alternatives(plan, self.chain_df[u] if chain is None else chain, now, self.qc.get("long_deltas", (0.30, 0.40)),
                                                            [tuple(x) for x in self.qc.get("spreads", ((0.45, 0.30), (0.50, 0.20)))])
            for v in variants:
                drift = ((self.research.get(u) or {}).get("drift") or {}).get("per_min", 0.0)
                e = self.ev.evaluate(v, view.spot, now, q["sigma_min"], p_up if v.direction != 0 else 0.5, minutes_left, drift)
                lots, notes = self.risk.size(v, eq, self.broker.cash(), self._open_risk())
                cands.append((v, e, lots, notes))
        fits = [c for c in cands if c[2] >= 1]
        ok = [c for c in fits if c[1]["ev"] >= max(floor_inr, floor_r * c[0].planned_risk_per_lot())]
        if not ok:
            best = max(fits or cands, key=lambda c: c[1]["ev_r"])
            v, e = best[0], best[1]
            why = (f"best of {len(cands)} structures is {v.structure} with EV ₹{e['ev']:+,.0f}/lot ({e['ev_r']:+.2f}R, "
                   f"P(profit) {e['p_profit']:.0%}) at P(up) {p_up:.2f} [{p_src}]"
                   + ("" if fits else "; none fits the account"))
            self.journal.decision(now, v.setup, u, "rejected", f"EV below the floor: {why}", 0,
                                  {"plan": v.describe(), "ev": {k: round(x, 3) if isinstance(x, float) else x for k, x in e.items()}})
            return f"setup {v.setup} found but not worth it after costs: {why}"
        plan, e, lots, notes = max(ok, key=lambda c: c[1]["ev_r"])
        bst = self.brain_state.get(u)
        if bst is not None and bst.size_mult < 1:
            # global stress: volatility targeting. With one-lot sizes this can mean no trade at all, by design.
            scaled = int(math.floor(lots * bst.size_mult + 0.49))   # 1 lot survives mild stress; ×0.5 (≈4σ) means aside
            notes = notes + [f"global stress {bst.stress:.1f}σ: size ×{bst.size_mult:.2f} → {scaled} lot(s)"]
            if scaled < 1:
                self.journal.decision(now, plan.setup, u, "rejected", notes[-1], 0, {"plan": plan.describe()})
                return f"setup {plan.setup} passed the EV gate but global stress is {bst.stress:.1f}σ: standing aside"
            lots = scaled
        others = sorted([c for c in cands if c[0] is not plan], key=lambda c: -c[1]["ev_r"])[:3]
        text = (f"EV ₹{e['ev']:+,.0f}/lot ({e['ev_r']:+.2f}R), P(profit) {e['p_profit']:.0%}, CVaR5 ₹{e['cvar5']:,.0f}, costs "
                f"₹{e['fees'] + e['exit_cost']:,.0f}/lot, σ over {e['horizon_min']}m {e['sigma_h_pct']:.2f}%, P(up) {p_up:.2f} [{p_src}]; "
                f"picked over " + ", ".join(f"{c[0].structure} {c[1]['ev_r']:+.2f}R" for c in others))
        plan.notes["quant"] = {k: (round(x, 4) if isinstance(x, float) else x) for k, x in e.items()}
        plan.notes["quant"]["p_source"] = p_src
        plan.notes["quant_text"] = text
        return plan, lots, notes + [f"quant: {text}"]

    def _open(self, plan: TradePlan, lots: int, notes: list[str], view: MarketView, s: dict, now) -> str:
        u = plan.symbol
        expl = plan.notes.get("mode") == "exploration"
        if expl:                                                  # the last word: caps, paper only, and exactly `lots`
            off = self._explore_off(now)
            if off or lots < self.explore["lots"]:
                msg = f"skipped {plan.setup}: exploration " + (off or f"needs {self.explore['lots']} lot(s); risk and cash allow {lots}")
                self.journal.decision(now, plan.setup, u, "rejected", msg, 0, {"plan": plan.describe()})
                return msg
            lots = self.explore["lots"]
        t = Trade(id=new_trade_id("I"), strategy=plan.setup, family="intraday", symbol=u, direction=plan.direction,
                  kind=OPTIONS, legs=[], units=lots, opened_at=now, entry_underlying=view.spot,
                  initial_risk=plan.planned_risk_per_lot() * lots, stop=plan.invalidation, target=plan.target_underlying,
                  exit_rules={"premium_stop": plan.premium_stop, "premium_target": plan.premium_target,
                              "time_stop_min": plan.time_stop_min, "credit": plan.is_credit},
                  rationale=(("EXPLORATION (unvalidated prior): " if expl else "") + f"[{plan.setup}] Trigger: {plan.trigger}. Thesis: {plan.thesis} "
                             f"Structure: {plan.describe()} (vol view {view.vol_view}). "
                             + (f"Quant: {plan.notes['quant_text']}. " if plan.notes.get("quant_text") else "")
                             + f"Market read: {view.narrative}"),
                  context={"regime": view.day_type, "bias": view.bias, "score": round(view.score, 3),
                           "conviction": round(view.conviction, 3), "vol_view": view.vol_view,
                           "evidence": [(e.factor, round(e.direction, 2), e.observation) for e in view.evidence],
                           "levels": {k: round(float(v), 2) for k, v in view.levels.items() if v == v and v is not None},
                           "chain": {k: v for k, v in view.chain.items() if isinstance(v, (int, float, str))}},
                  meta={"structure": plan.structure, "expiry": str(plan.expiry), "quote_source": plan.quote_source,
                        "code": _provenance(),
                        "entry_net_premium_per_lot": plan.net_premium, "max_loss": plan.max_loss_per_lot(),
                        "legs_plan": [(l.strike, l.right, l.ratio, round(l.price, 2), round(l.iv, 2), round(l.delta, 3))
                                      for l in plan.legs], **plan.notes})
        insts = [Instrument.option(u, plan.expiry, l.strike, l.right, plan.lot_size) for l in plan.legs]
        live = self._live(insts, now)
        t.meta["leg_liquidity"] = self._leg_liquidity(u, insts, plan.legs, live)
        if (live or self._real_book()) and any(i.symbol not in live for i in insts):
            # the book answered, but not two-sided for every leg (or did not answer at all): a real order there may not fill
            missing = ", ".join(f"{l.strike:g}{l.right}" for i, l in zip(insts, plan.legs) if i.symbol not in live)
            msg = f"skipped {plan.setup}: no two-sided quote on {missing} in the live book"
            self.journal.decision(now, plan.setup, u, "rejected", msg, 0,
                                  {"plan": plan.describe(), "legs": t.meta["leg_liquidity"]})
            return msg
        px = {i.symbol: (live[i.symbol][1] if l.ratio > 0 else live[i.symbol][0]) if i.symbol in live else l.price
              for i, l in zip(insts, plan.legs)}
        if live:
            # a real limit order at the planned prices wouldn't fill if the book has moved away: skip, don't chase
            planned = sum(l.ratio * l.price for l in plan.legs)
            now_net = sum(l.ratio * px[i.symbol] for i, l in zip(insts, plan.legs))
            worse = now_net - planned                       # + = paying more (debit) or collecting less (credit)
            if abs(planned) > 0 and worse > self.max_entry_slip * abs(planned):
                msg = (f"skipped {plan.setup}: the live book moved away (planned ₹{planned * plan.lot_size:,.0f}/lot, "
                       f"now ₹{now_net * plan.lot_size:,.0f}/lot)")
                self.journal.decision(now, plan.setup, u, "rejected", msg, 0, {"plan": plan.describe()})
                return msg
        t.meta["fill_quotes"] = f"live {self.chains.name} book" if len(live) == len(insts) else "option chain"
        for inst, leg in zip(insts, plan.legs):
            qty = leg.ratio * lots * plan.lot_size
            fill = self.broker.execute(Order(inst, qty, t.id, "open"), px[inst.symbol], now)
            if fill is None:
                return self._abort_entry(t, plan, inst.symbol, notes, now)
            self.journal.fill(now, t.id, inst.symbol, qty, fill.price, fill.fees, fill.fee_breakdown)
            t.legs.append(TradeLeg(inst, qty, fill.price))
            t.fees += fill.fees
        t.pnl = -t.fees
        t.last_mark = {l.instrument.symbol: l.entry_price for l in t.legs}
        self.open_trades.append(t)
        self.risk.trades_today += 1
        self._gov_safe(self._gov_open, t, now)
        self.journal.open_trade(t, notes)
        if expl:
            self.journal.decision(now, plan.setup, u, "exploration", f"EXPLORATION (unvalidated prior): {lots} lot(s), no approved "
                                  "plan model; outside the paper gate", lots, {"plan": plan.describe(), "trade": t.id})
        self._persist()                                   # the position is on record before anything else can fail
        msg = (f"ENTER {plan.setup} {lots}×{plan.describe()} | stop {plan.invalidation or '—'} | {plan.trigger}"
               + (" | EXPLORATION (unvalidated prior)" if expl else ""))
        self.say(f"  {now:%H:%M} {u:<9} ▲ {msg}")
        return msg

    def _abort_entry(self, t: Trade, plan: TradePlan, rejected: str, notes: list[str], now) -> str:
        """A leg of a multi-leg entry was rejected after earlier legs had filled: unwind them. Every unwind fill is
        journalled and its cost booked into the trade, so the broker's cash equals the sum of trade P&L. The trade is
        recorded as closed ("entry_aborted"); a leg whose unwind is rejected too keeps the trade open and pending exit
        (retried each minute by `_close`), so the broker and the journal still agree. No leg filled: nothing to book."""
        if not t.legs:
            return f"order for {rejected} rejected; nothing opened"
        stuck = []
        for leg in t.legs:
            fill = self.broker.execute(Order(leg.instrument, -leg.qty, t.id, "unwind"), leg.entry_price, now)
            if fill is None:
                stuck.append(leg.instrument.symbol)
                continue
            self.journal.fill(now, t.id, leg.instrument.symbol, -leg.qty, fill.price, fill.fees, fill.fee_breakdown)
            leg.exit_price = fill.price
            t.fees += fill.fees
        t.pnl = sum(l.qty * ((l.exit_price if l.exit_price is not None else l.entry_price) - l.entry_price)
                    for l in t.legs) - t.fees
        t.last_mark = {l.instrument.symbol: l.entry_price for l in t.legs}
        t.meta["aborted_entry"] = f"order for {rejected} rejected after {len(t.legs)} leg(s) had filled"
        self.risk.trades_today += 1
        self.journal.open_trade(t, notes)
        if stuck:
            t.meta["exit_pending"] = ["entry_aborted", t.meta["aborted_entry"]]
            self.open_trades.append(t)
            self.journal.event(now, "CRITICAL", "execution",
                               f"{t.meta['aborted_entry']}; unwind of {', '.join(stuck)} also rejected: {t.id} stays open, "
                               f"retried each minute", {"trade": t.id})
            self._persist()
            return f"order for {rejected} rejected; unwind of {', '.join(stuck)} incomplete, retrying"
        t.mae, t.mfe = min(t.mae, t.pnl), max(t.mfe, t.pnl)
        t.status, t.closed_at, t.exit_reason, t.exit_note = "closed", now, "entry_aborted", t.meta["aborted_entry"]
        t.exit_underlying = t.entry_underlying
        self.closed.append(t)
        self.journal.close_trade(t, None)
        self.risk.on_close(t.pnl, now)
        self.journal.event(now, "WARN", "execution", f"{t.meta['aborted_entry']}; unwound, cost ₹{-t.pnl:,.2f} booked to {t.id}",
                           {"trade": t.id, "pnl": t.pnl})
        self._persist()
        return f"order for {rejected} rejected; unwound {len(t.legs)} leg(s), ₹{t.pnl:,.2f}"

    def _manage(self, u: str, view: MarketView, now) -> list[str]:
        out = []
        S = view.spot
        for t in [x for x in self.open_trades if x.symbol == u]:
            if t.meta.get("exit_pending"):                # an exit already under way is finished, whatever the market does
                out.append(self._retry_exit(t, now))
                continue
            marks = {l.instrument.symbol: self.marker.mid(l.instrument, S, now) for l in t.legs}
            t.update_excursions(marks)
            t.bars_held = int((now - t.opened_at).total_seconds() // 60)
            gross = t.value(marks) - t.entry_cost
            prem = abs(t.entry_cost)
            r = t.exit_rules
            credit = r.get("credit", t.entry_cost < 0)
            reason = note = None
            if t.stop is not None and ((t.direction > 0 and S <= t.stop) or (t.direction < 0 and S >= t.stop)):
                reason, note = "invalidation", f"underlying {S:,.2f} through {t.stop:,.2f}"
            elif t.meta.get("range") and not (t.meta["range"][0] <= S <= t.meta["range"][1]):
                reason, note = "range_break", f"underlying {S:,.2f} left the value area {t.meta['range']}"
            elif gross <= -prem * r["premium_stop"]:
                reason, note = "premium_stop", f"P&L ₹{gross:,.0f} hit the {'credit ×' if credit else ''}{r['premium_stop']} stop"
            elif gross >= prem * r["premium_target"]:
                reason, note = "premium_target", f"P&L ₹{gross:,.0f} reached the {r['premium_target']:.0%} target"
            elif t.target is not None and ((t.direction > 0 and S >= t.target) or (t.direction < 0 and S <= t.target)):
                reason, note = "underlying_target", f"underlying reached {t.target:,.2f}"
            elif t.mfe > 0.5 * prem * r["premium_target"] and gross <= 0:
                reason, note = "breakeven_stop", "gave back a half-target open profit: out at breakeven"
            elif t.bars_held >= r["time_stop_min"] and gross < 0.1 * prem:
                reason, note = "time_exit", f"no progress in {t.bars_held} min"
            if reason:
                out.append(self._close(t, now, reason, note))
        return [m for m in out if m]                      # a silent retry of a stuck exit says nothing

    def _close(self, t: Trade, now, reason: str, note: str) -> str:
        self._exit_tried[t.id] = now                      # every attempt counts for `_retry_exit`'s once-per-moment rule
        S = self.spot(t.symbol)
        live = self._live([l.instrument for l in t.legs], now)
        t.meta["exit_quotes"] = f"live {self.chains.name} book" if len(live) == len(t.legs) else "marked"
        problems = []
        for l in t.legs:
            if l.exit_price is not None:                  # closed on an earlier attempt
                continue
            q = live.get(l.instrument.symbol)
            px = (q[0] if l.qty > 0 else q[1]) if q else self.marker.exit_price(l.instrument, l.qty, S, now)
            # never close more than the broker holds: a leg already closed there (by hand, or before a restart)
            # would otherwise be sold again into a naked position
            held = int(((self.broker.positions() or {}).get(l.instrument.symbol) or {}).get("qty", 0))
            sign = 1 if l.qty > 0 else -1
            qty = sign * min(abs(l.qty), max(0, sign * held))
            if not qty:
                l.exit_price = px                         # no order: marked at the estimated exit price
                problems.append(f"exit of {l.instrument.symbol} skipped: the broker holds {held}")
                continue
            fill = self.broker.execute(Order(l.instrument, -qty, t.id, "close"), px, now)
            if fill is None:
                continue
            if qty != l.qty:
                problems.append(f"exit of {l.instrument.symbol}: the broker held {held} of {l.qty}; closed {qty}")
            self.journal.fill(now, t.id, l.instrument.symbol, -qty, fill.price, fill.fees, fill.fee_breakdown)
            l.exit_price = fill.price
            t.fees += fill.fees
        stuck = [l.instrument.symbol for l in t.legs if l.exit_price is None]
        first = bool(stuck) and "exit_pending" not in t.meta
        if problems or first:                             # once per trade for a stuck exit, not on every retry
            msg = "; ".join(problems + ([f"exit of {', '.join(stuck)} not filled: {t.id} stays open, retried each minute"]
                                        if first else []))
            self.journal.event(now, "CRITICAL", "execution", msg, {"trade": t.id, "reason": reason})
        if stuck:
            t.meta["exit_pending"] = [reason, note]
            self._persist()
            if not first:
                return ""
            msg = f"EXIT {t.strategy} {reason} incomplete: {', '.join(stuck)} still open, retrying"
            self.say(f"  {now:%H:%M} {t.symbol:<9} ▼ {msg}")
            return msg
        t.meta.pop("exit_pending", None)
        t.pnl = sum(l.qty * ((l.exit_price or l.entry_price) - l.entry_price) for l in t.legs) - t.fees
        t.mae, t.mfe = min(t.mae, t.pnl), max(t.mfe, t.pnl)
        t.status, t.closed_at, t.exit_reason, t.exit_note, t.exit_underlying = "closed", now, reason, note, S
        t.bars_held = int((now - t.opened_at).total_seconds() // 60)
        self.open_trades.remove(t)
        self.closed.append(t)
        v = self.views.get(t.symbol)
        rv = self.journal.close_trade(t, v.day_type if v else None)
        self.risk.on_close(t.pnl, now)
        self._gov_safe(self._gov_close, t, now)
        self._persist()                                   # the exit is on record before anything else can fail
        msg = f"EXIT {t.strategy} {reason}: ₹{t.pnl:,.0f} ({t.r_multiple:+.2f}R, grade {rv['grade']}) — {note}"
        self.say(f"  {now:%H:%M} {t.symbol:<9} ▼ {msg}")
        return msg

    # ---- remote control (the app writes commands; the engine executes them) ----------------------------------
    def _commands(self, now) -> None:
        if self.halt and not self.journal.get_state(HALT_KEY):   # the owner cleared it (clear-halt) mid-session
            self.halt = None
            self.say(f"  {now:%H:%M} entry halt cleared by the owner")
        cmds = self.journal.get_state("intraday_cmds") or []
        done = set(self.journal.get_state("intraday_cmds_done") or [])
        todo = [c for c in cmds if c.get("id") not in done]
        for c in todo:
            cmd, arg = c.get("cmd"), c.get("arg")
            if cmd == "pause":
                self.paused = True
            elif cmd == "resume":
                self.paused = False
            elif cmd in ("flatten", "close"):
                for t in list(self.open_trades):
                    if cmd == "flatten" or t.id == arg:
                        self._close(t, now, "manual", f"{'flattened' if cmd == 'flatten' else 'closed'} from the app")
                if cmd == "flatten":
                    self.paused = True
            done.add(c.get("id"))
            self.journal.event(now, "WARN", "remote", f"{cmd}{' ' + str(arg) if arg else ''} from the app")
            self.say(f"  {now:%H:%M} remote command: {cmd} {arg or ''}")
        if todo:
            self.journal.set_state("intraday_cmds_done", sorted(done))
            self.journal.set_state("intraday_paused", self.paused)

    def _heartbeat(self, now) -> None:
        """Everything the app's Live screen needs, in one small state row updated every minute."""
        eq = self.equity(now)
        views = {}
        for u, v in self.views.items():
            ns = self.news.state(u, now) if self.news is not None else None
            views[u] = {"spot": v.spot, "bias": v.bias, "score": v.score, "conviction": v.conviction, "day_type": v.day_type,
                        "vol_view": v.vol_view, "iv": v.iv, "rv": v.rv, "narrative": v.narrative, "vetoes": v.vetoes,
                        "levels": {k: float(x) for k, x in v.levels.items() if x is not None and x == x},
                        "chg": v.state.get("chg"), "vwap": v.state.get("vwap"), "phase": v.state.get("phase"),
                        "expiry": str(self.expiry.get(u)), "news": ns,
                        "quant": {k: x for k, x in (self.qstate.get(u) or {}).items() if k != "sigma_min"} or None,
                        "action": self.last_action.get(u),
                        "brain": _brain_view(self.brain_state.get(u)),
                        "chain": _chain_view(self.chain_an.get(u)),
                        "breadth": self.breadth_state.get(u), "rel": self.rel, "hist_edge": self.hist_edge.get(u),
                        "learned_applied": self.analyst.apply_learned,    # D-01: "learned" is the record, not the weight
                        "evidence": [{"factor": e.factor, "category": e.category, "direction": e.direction,
                                      "weight": e.weight, "observation": e.observation,
                                      "learned": (getattr(self.analyst, "learned", None) or {}).get(e.factor)} for e in v.evidence]}
        positions = []
        for t in self.open_trades:
            S = self.spot(t.symbol)
            marks = {l.instrument.symbol: self.marker.mid(l.instrument, S, now) for l in t.legs}
            positions.append({"id": t.id, "setup": t.strategy, "symbol": t.symbol, "structure": t.meta.get("structure"),
                              "lots": t.units, "opened": str(t.opened_at), "pnl": t.value(marks) - t.entry_cost - t.fees,
                              "stop": t.stop, "target": t.target, "entry_underlying": t.entry_underlying, "spot": S,
                              "direction": t.direction, "premium": abs(t.entry_cost),
                              "premium_stop": t.exit_rules.get("premium_stop"), "premium_target": t.exit_rules.get("premium_target"),
                              "time_stop": (str(t.opened_at + pd.Timedelta(minutes=t.exit_rules["time_stop_min"]))
                                            if t.exit_rules.get("time_stop_min") else None),
                              "legs": [{"symbol": l.instrument.symbol, "qty": l.qty, "entry": l.entry_price,
                                        "mark": marks[l.instrument.symbol]} for l in t.legs],
                              "rationale": t.rationale[:600]})
        data = self._data_status(now)
        if now.minute % 5 == 0 and isinstance(data, dict) and isinstance(data.get("kite"), dict):
            try:                                                    # the Kite feed's counters outlive this process (the morning and the afternoon runner each start from zero): docs/ml/KITE_TRIAL.md reads them from here
                self.journal.event(now, "INFO", "feed", "kite feed counters " + json.dumps({k: v for k, v in data["kite"].items() if k != "symbols"}, sort_keys=True))
            except Exception:
                pass
        self.journal.set_state("intraday_live", {
            "ts": str(now), "day": str(self.day), "equity": eq, "day_start_equity": self.day_start_equity,
            "day_pnl": eq - self.day_start_equity, "paused": self.paused, "halted": self.risk.halted,
            "trades_today": self.risk.trades_today, "feed": self.feed.name, "chain": self.chain_name(), "data": data,
            "views": views, "positions": positions,
            "armed": [a.to_record() for u in self.underlyings for a in self.armed.get(u, []) if now <= a.expires],
            "news_health": dict(self.news.health) if self.news is not None else None,
            "claude_budget": self._claude_line(),
            "global": _global_view(self.brain, now), "gift": self.gift, "events": self.events_today,
            "learning": self._learning_view(),
            "autolearn": self.learner.status() if self.learner is not None else None,
            "halts": {"kill_switch": self.killed, "journal": self.journal_fault, "daily_loss": self.risk.halted,
                      "safe_mode": self.health.get("safe_mode"),
                      "reconcile": (self.health.get("reconcile") or {}).get("ok") is False,
                      **({"inherited": summary(self.halt)} if self.halt else {})},
            "health": dict(self.health)})

    def _data_status(self, now) -> dict | None:
        """Where the desk's market data comes from and how fresh it is, for the app's Data panel: the feed's name, its Kite status if the websocket is attached, and each
        index's last bar and its age. A display: whatever is wrong with it must never cost the desk a heartbeat."""
        try:
            bars = {}
            for u in self.underlyings + [self.vix]:
                ts = self.last_ts.get(u)
                bars[u] = {"last_bar": str(ts), "age_s": round((now - ts).total_seconds(), 1)} if ts is not None else None
            st = getattr(self.feed, "status", None)
            return {"feed": self.feed.name, "kite": st() if callable(st) else None, "bars": bars}
        except Exception:
            return None

    def _claude_line(self) -> str | None:
        """'Claude: $X today, $Y of $20.00 used, ~N sessions left at this pace' (None without a credit)."""
        global _claude_budget_warned
        try:                                          # a display: whatever is wrong with the ledger must never cost the desk a step
            b = getattr(getattr(self.news, "llm", None), "budget", None) if self.news is not None else None
            return (b.line() or None) if b is not None else None
        except Exception as exc:
            if not _claude_budget_warned:
                _claude_budget_warned = True
                log.warning("claude budget line unavailable (shown once): %s", exc)
            return None

    def _learning_view(self) -> dict | None:
        """What the record says, for the app: factor IC by horizon, the buyer's edge, the probation factors."""
        if self.memory is None:
            return None
        from . import learning
        from .analyst import PROBATION
        try:
            from .relstrength import earned, record
            rs = record(self.memory)
            return {"ic": learning.ic_table(self.memory)[:12], "edge": learning.buyer_edge(self.memory),
                    "rs": {**rs, "used": earned(rs)} if rs else None,
                    "sessions": len(self.memory.d.get("days") or []),
                    "probation": {f: {"n": round((self.memory.stat("factor", f) or {"n": 0})["n"], 1),
                                      "rel": round(self.memory.reliability("factor", f), 3),
                                      "earned": f in self.analyst.graduated,
                                      "voting": self.analyst.apply_learned and f in self.analyst.graduated}
                                  for f in PROBATION},
                    "factor_weights_applied": self.analyst.apply_learned}
        except Exception:                                 # the app's extra must never cost a heartbeat
            return None

    # ---- journaling ------------------------------------------------------------------------------------------
    def _think(self, u: str, view: MarketView, now, action: str, force: bool = False) -> None:
        self.last_action[u] = action
        last = self.last_thought.get(u)
        changed = self.last_bias.get(u) != view.bias
        trade_event = action.startswith(("ENTER", "EXIT")) or force
        if last is None or trade_event or changed or now - last >= pd.Timedelta(minutes=self.think_every):
            self.journal.thought(view, action)
            self.last_thought[u], self.last_bias[u] = now, view.bias
            if not trade_event:
                self.say(f"  {now:%H:%M} {u:<9} · {view.bias:<8} {view.score:+.2f} c{view.conviction:.2f} "
                         f"{view.day_type:<12} IV/RV {view.vol_view:<7} | {action}")

    def _snapshot(self, now) -> None:
        if now.minute % 5:
            return
        eq = self.equity(now)
        self.journal.snapshot(now, equity=eq, cash=self.broker.cash(), drawdown=min(0.0, eq / self.day_start_equity - 1),
                              open_trades=len(self.open_trades), gross=0.0, net_delta=0.0, vega=0.0,
                              open_risk=sum(t.initial_risk for t in self.open_trades),
                              regime=",".join(f"{u}:{v.day_type}" for u, v in self.views.items()))
        self._drawdown_check(now, eq)

    def _drawdown_check(self, now, equity: float) -> None:
        """Track the account's high-water mark (journal state, so it spans days and runners) and halt new entries once
        equity is `cross_day_drawdown_halt` below it. The mark moves only on realised equity (no position open), so a
        spurious mark on an open option can't lift it for good; the drawdown is measured on marked equity (the
        conservative side). Re-reads the halt while set, so an owner's clear applies at once."""
        if not self.dd_halt_frac or not math.isfinite(equity) or equity <= 0:
            return
        try:
            if self.peak_equity is None or self.dd_halt:
                st = self.journal.get_state(DD_PEAK_KEY) or {}
                peak = float(st.get("peak") or 0)
                if st.get("restart"):                           # the owner cleared a halt: the mark restarts here
                    peak = equity
                    self.journal.set_state(DD_PEAK_KEY, {"peak": peak, "at": str(now), "restarted": st.get("at")})
                elif not peak:                                  # first run: the account's own record sets the mark
                    row = self.journal.df("SELECT MAX(equity) AS m FROM equity WHERE COALESCE(open_trades, 0) = 0")
                    m = row["m"].iloc[0] if len(row) else None
                    cap = float((self.journal.get_state("intraday_account") or {}).get("capital") or 0)
                    peak = max(float(m) if m is not None and m == m else 0.0, cap,
                               equity if not self.open_trades else 0.0)
                    self.journal.set_state(DD_PEAK_KEY, {"peak": peak, "at": str(now)})
                self.peak_equity = peak
                if not (self.dd_halt or {}).get("fault"):       # a fault halt holds for the session, whatever the state says
                    self.dd_halt = self.journal.get_state(DD_KEY)
            if equity > self.peak_equity and not self.open_trades:
                self.peak_equity = equity
                self.journal.set_state(DD_PEAK_KEY, {"peak": equity, "at": str(now)})
            dd = equity / self.peak_equity - 1
            if not self.dd_halt and dd <= -self.dd_halt_frac:
                self.dd_halt = {"since": str(now), "peak": self.peak_equity, "equity": equity, "drawdown": dd}
                self.journal.set_state(DD_KEY, self.dd_halt)
                self.journal.event(now, "CRITICAL", "risk", f"drawdown halt: equity ₹{equity:,.0f} is {dd:.1%} below its "
                                   f"peak ₹{self.peak_equity:,.0f} (limit {self.dd_halt_frac:.0%}); new entries halted "
                                   f"until the owner clears it", self.dd_halt)
                self.say(f"  {now:%H:%M} DRAWDOWN HALT: {dd:.1%} from the peak")
        except Exception as exc:                          # a tracking fault must not cost the step; it fails closed
            log.exception("drawdown check failed")
            if not self.dd_halt:
                self.dd_halt = {"since": str(now), "peak": self.peak_equity or 0.0, "equity": equity, "drawdown": float("nan"),
                                "fault": f"{exc!r:.120}"}

    def _persist(self, ended: bool = False) -> None:
        r = self.risk
        self.journal.set_state("intraday_open", {
            "day": str(self.day), "ended": ended, "trades": [trade_to_dict(t) for t in self.open_trades],
            "closed": [trade_to_dict(t) for t in self.closed if t.opened_at.date() == self.day],
            "day_start_equity": self.day_start_equity,
            "risk": {"trades_today": r.trades_today, "consec_losses": r.consec_losses, "halted": r.halted,
                     "cool_until": str(r.cool_until) if r.cool_until is not None else None}})
        self._gov_safe(self._gov_save)

    # ---- risk governor hooks (governor.py): the only places the engine touches it ------------------------------------
    def _gov_safe(self, fn, *a) -> None:
        """Run a governor hook. Any failure means identity limits (no change to trading) and one log line per process."""
        try:
            fn(*a)
        except Exception as exc:
            governor.log_fault(exc)
            try:
                self.risk.apply_limits(None)
            except Exception:
                pass

    def _gov_start(self, day: dt.date) -> None:
        """Load (or begin) the governor's state for today and apply it: a restart or the 12:20 hand-over carries on from it."""
        self._gov, self._gov_obs = None, {}
        if self._gov_cfg["mode"] == "off":
            return
        st = self.journal.get_state("risk_governor")
        if not (isinstance(st, dict) and st.get("v") == governor.VERSION):
            rs = self.journal.df("SELECT r_multiple FROM trades WHERE status='closed' AND family='intraday' AND r_multiple IS NOT NULL "
                                 "ORDER BY closed_at DESC LIMIT 20")["r_multiple"].tolist()[::-1]
            pk = [x for x in (self.day_start_equity, self.journal.df("SELECT MAX(equity) AS m FROM equity")["m"].iloc[0]) if x is not None and x == x]
            st = governor.new_state(day, self._gov_cfg, self._gov_base, rs, max(pk))
        v = self.bars.get(self.vix)
        prior = v[(v.index.date < day) & (v["close"] > 0)] if v is not None and len(v) else None
        closes = {str(d): float(c) for d, c in prior["close"].groupby(prior.index.date).last().items()} if prior is not None else {}
        self._gov = governor.note_vix(st, closes, day)
        self._gov_refresh(session_bounds(day)[0])

    def _gov_step(self, now) -> None:
        """Each step: what the governor would do now (cheap), journaled when it changes, used only in tighten mode."""
        if self._gov is None:
            return
        worst = None                                       # the underlying whose realised 30-minute range is biggest vs its forecast
        for u in self.underlyings:
            b = self.bars.get(u)
            w = b.iloc[-30:] if b is not None and len(b) >= 30 else None
            if w is None or w.index[0].date() != self.day:
                continue
            sg = (self.qstate.get(u) or {}).get("sigma_30m_pct")
            rp = governor.realised_range_pct(w["high"].tolist(), w["low"].tolist(), float(w["close"].iloc[-1]))
            if rp is not None and sg and (worst is None or rp / sg > worst[0] / worst[1]):
                worst = (rp, sg)
        vs = self._vix_state()
        stale = any(self.feed.realtime_age(now, self.last_ts[u]) > self.stale_feed_min for u in self.underlyings if self.last_ts.get(u) is not None)
        self._gov_refresh(now, {"equity": self.equity(now), "range_pct": worst and worst[0], "fc_sigma30_pct": worst and worst[1],
                                "vix": vs and vs["last"], "feed_events": self.journal.count_events(self.day), "stale": stale})

    def _gov_refresh(self, now, obs: dict | None = None) -> None:
        if self._gov is None:
            return
        if obs is not None:
            self._gov_obs = obs
        mode = self._gov_cfg["mode"]
        self._gov, dec = governor.tick(self._gov, self._gov_obs, self._gov_base, self._gov_cfg, now)
        lim, until, why = governor.effective(dec, mode, self._gov_acct, now)
        self.risk.apply_limits(lim, pd.Timestamp(until) if until is not None else None, why)
        how = "applied" if lim is not None else ("proposal, not applied (not a paper account)" if mode == "tighten" else "shadow")
        for c in dec["changes"]:                           # changes only
            self.journal.event(now, "INFO", "governor", f"{how}: {c['rule']}: {c['field']} {c['old']} → {c['new']} | {c['reason']}",
                               {**c, "mode": mode, "applied": lim is not None})

    def _gov_open(self, t: Trade, now) -> None:
        if self._gov is not None:
            slip = governor.entry_slippage(t.meta.get("legs_plan"), [l.entry_price for l in t.legs])
            self._gov = governor.on_open(self._gov, slip, now, self._gov_cfg)
            self._gov_refresh(now)

    def _gov_close(self, t: Trade, now) -> None:
        if self._gov is not None:
            self._gov = governor.on_close(self._gov, t.pnl, t.r_multiple, now, self._gov_cfg)
            self._gov_refresh(now)

    def _gov_save(self) -> None:
        if self._gov is not None:
            js = json.dumps(self._gov, sort_keys=True, default=str)
            if js != self._gov_saved:
                self.journal.set_state("risk_governor", self._gov)
                self._gov_saved = js

    def _restore(self, day: dt.date) -> dict:
        """Pick up today's session after a restart: open positions, the trades already closed, the day's
        starting equity and the risk state (trade count, loss streak, cooldown, halt)."""
        st = self.journal.get_state("intraday_open") or {}
        if st.get("day") != str(day):
            if st.get("trades"):
                self.journal.event(pd.Timestamp.now(tz=IST), "WARN", "session",
                                   f"{len(st['trades'])} position(s) from {st.get('day')} were never squared off; not "
                                   f"restored, entries halted for the owner")
            return {}
        self.open_trades = [trade_from_dict(d) for d in st.get("trades") or []]
        self.closed = [trade_from_dict(d) for d in st.get("closed") or []]
        if self.open_trades or self.closed or st.get("day_start_equity"):
            self.say(f"  resumed today's session: {len(self.open_trades)} open, {len(self.closed)} closed")
        return st

    def chain_name(self) -> str:
        """The chain actually in use: the configured source, or what is standing in for it."""
        srcs = {str(ch.attrs.get("source")) for ch in self.chain_df.values()}
        name = self.chains.name
        if self.chains is self.model_chain or not srcs or srcs == {name}:
            return name
        if name not in srcs:
            return f"{'+'.join(sorted(srcs))} (no {name})"
        return "+".join([name] + sorted(srcs - {name}))

    # ---- review ------------------------------------------------------------------------------------------------
    def session_review(self) -> str:
        day = self.day
        trades = [t for t in self.closed if t.opened_at.date() == day]
        nx = sum(t.meta.get("mode") == "exploration" for t in trades)
        th = self.journal.thoughts(str(day))
        end_eq = self.broker.cash()
        L = [f"# Intraday session review — {day}", "",
             f"Capital ₹{self.day_start_equity:,.0f} → ₹{end_eq:,.0f} (**{end_eq / self.day_start_equity - 1:+.2%}**, "
             f"₹{end_eq - self.day_start_equity:+,.0f}); {len(trades)} trade(s)"
             + (f" ({nx} exploration: unvalidated prior, outside the paper gate)" if nx else "") + f"; chain source {self.chain_name()}; "
             f"feed {self.feed.name}.", ""]
        if self.events_today:
            L += [f"Events: {'; '.join(self.events_today)}.", ""]
        if self.gift and "NIFTY" in self.bars:
            b = self.bars["NIFTY"]
            today, prior = b[b.index.date == day], b[b.index.date < day]
            if len(today) and len(prior):
                gap = today["open"].iloc[0] / prior["close"].iloc[-1] - 1
                L += [f"GIFT Nifty before the open implied **{self.gift['implied_gap']:+.2%}** for NIFTY (after carry); "
                      f"it opened **{gap:+.2%}**.", ""]
        for u in self.underlyings:
            tu = th[th["symbol"] == u] if not th.empty else th
            if tu.empty:
                continue
            first, lastr = tu.iloc[0], tu.iloc[-1]
            L += [f"## {u}", f"- Opened read ({str(first.ts)[11:16]}): {first.narrative}",
                  f"- Closing read ({str(lastr.ts)[11:16]}): {lastr.narrative}"]
            flips = tu[tu["bias"] != tu["bias"].shift()]
            if len(flips) > 1:
                L.append("- Bias path: " + " → ".join(f"{str(r.ts)[11:16]} {r.bias}" for r in flips.itertuples()))
            types = tu["day_type"].value_counts()
            L.append(f"- Day type (share of reads): " + ", ".join(f"{k} {v / len(tu):.0%}" for k, v in types.items()))
            L.append("")
        if trades:
            L += ["## Trades", "", "| Time | Setup | Structure | Lots | P&L ₹ | R | Exit | Grade |", "|---|---|---|---:|---:|---:|---|---|"]
            for t in trades:
                L.append(f"| {t.opened_at:%H:%M}–{t.closed_at:%H:%M} | {t.strategy} {t.symbol}{' (exploration)' if t.meta.get('mode') == 'exploration' else ''} | {t.meta.get('structure')} | "
                         f"{t.units} | {t.pnl:,.0f} | {t.r_multiple:+.2f} | {t.exit_reason} | "
                         f"{self._grade(t.id)} |")
            L.append("")
            for t in trades:
                L += [f"**{t.id} · {t.strategy} {t.symbol}** — {t.rationale}", f"Exit: {t.exit_reason} — {t.exit_note}.", ""]
            wins = sum(t.pnl > 0 for t in trades)
            L.append(f"Win rate {wins}/{len(trades)}, net ₹{sum(t.pnl for t in trades):,.0f}, costs ₹{sum(t.fees for t in trades):,.0f}.")
            if nx:
                ex = [t for t in trades if t.meta.get("mode") == "exploration"]
                L.append(f"Exploration: {len(ex)} trade(s), {sum(t.pnl > 0 for t in ex)} win(s), net ₹{sum(t.pnl for t in ex):,.0f}; "
                         f"the rest: {len(trades) - nx} trade(s), net ₹{sum(t.pnl for t in trades) - sum(t.pnl for t in ex):,.0f}.")
        else:
            reasons = th["action"].str.extract(r"^(standing aside|watching)[^:]*: (.*)$")[1].dropna().value_counts().head(4) \
                if not th.empty else pd.Series(dtype=int)
            L.append("No trades. Most common reasons: " + "; ".join(f"{k} (x{v})" for k, v in reasons.items()))
        if self.memory is not None:
            from .learning import summary
            got = self.learned_today
            lines = summary(self.memory, factor_weights_applied=self.analyst.apply_learned)
            L += ["", "## What the desk learned", "",
                  (f"Graded today: {got.get('news', 0)} news calls, {got.get('factors', 0)} factor reads, "
                   f"{got.get('trades', 0)} trades, {got.get('armed', 0)} refused pre-break entries. "
                   if got else "")
                  + f"Record over {len(self.memory.d['days'])} session(s); every weight is shrunk toward 1× until the "
                    f"record is long enough to mean something."
                  + ("" if self.analyst.apply_learned else
                     " Factor weights are recorded, not applied: every factor reads at its unlearned weight until a "
                     "significance test says its record isn't noise.")]
            L += [f"- {x}" for x in lines] if lines else ["- Nothing graded yet."]
        return "\n".join(L)

    def _grade(self, tid: str) -> str:
        r = self.journal.df("SELECT grade FROM trades WHERE id=?", (tid,))
        return r["grade"].iloc[0] if not r.empty else "?"


CHAIN_VIEW = ("source", "atm_iv", "atm_ivp", "implied_move", "straddle", "dte_days", "pcr_oi", "pcr_doi", "max_pain",
              "call_wall", "put_wall", "top_call_adds", "top_put_adds", "skew_25d", "gex_state", "gamma_flip",
              "fut_basis", "fut_carry", "fut_buildup")


def _chain_view(an: dict | None) -> dict | None:
    """The option chain's read for the app (chains.chain_analytics, futures, and chainflow's cf_* changes)."""
    if not an:
        return None

    def ok(x):
        return x is not None and not (isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))))
    out = {k: an[k] for k in CHAIN_VIEW if k in an and ok(an[k])}
    out.update({k: x for k, x in an.items() if k.startswith("cf_") and ok(x)})
    return out


class _Valid:
    """Marks a promoted champion as validated for `_quant_state` (it passed every gate to get there)."""
    valid = True


def _brain_view(st) -> dict | None:
    if st is None:
        return None
    return {"regime": st.regime, "regime_score": st.regime_score, "stress": st.stress, "size_mult": st.size_mult,
            "narrative": st.narrative, "gap": st.gap, "evidence": st.evidence, "pulse": st.pulse, "flows": st.flows,
            "drivers": [{k: d.get(k) for k in ("id", "name", "sign", "live", "prior_z", "z30", "pressure", "gap_beta", "gap_corr",
                                                "co_corr", "lead_t", "validated", "lead_sign", "news_tone", "news_n", "news_latest")}
                        | {"move": d.get("lead")} for d in st.drivers]}


def _global_view(brain, now) -> dict | None:
    if brain is None or brain.gfeed is None:
        return None
    mk = brain.gfeed.snapshot(now)
    return {"markets": {k: {x: m.get(x) for x in ("name", "region", "india", "last", "prior_ret", "prior_z", "since_open", "r30",
                                                   "z30", "live", "last_ts", "prior_date")} for k, m in mk.items()},
            "health": dict(brain.gfeed.health)}


def _where(exc: BaseException, frames: int = 6) -> list[str]:
    """The last few frames of a failure, so a journaled error can be traced from the journal alone
    (29 Sep 2026: a one-off TypeError on the live desk was journaled as a bare repr, untraceable)."""
    tb = traceback.extract_tb(exc.__traceback__)[-frames:]
    return [f"{Path(f.filename).name}:{f.lineno} {f.name}: {(f.line or '').strip()[:120]}" for f in tb]


# ---- drivers ------------------------------------------------------------------------------------------
def run_replay(engine: IntradayEngine) -> str:
    feed = engine.feed
    assert isinstance(feed, ReplayFeed)
    engine.start_session(feed.day)
    while feed.advance():
        engine.step()
    return engine.end_session()


def run_live(engine: IntradayEngine, stop_at: dt.time | None = None, handover: bool = False) -> str:
    """Wall-clock loop: waits for the open, steps a few seconds after each minute closes.

    stop_at + handover: stop at that time *without* squaring off; the next run (same journal and
    broker state) resumes the session where this one left off. That is how two back-to-back
    runners cover a full 6¼-hour session when each is capped at 6 hours."""
    now = engine.feed.now()
    day = now.date()
    if not engine.cal.is_trading_day(day):
        return f"{day} is not an NSE trading day"
    open_ts, close_ts = session_bounds(day)
    end = pd.Timestamp(dt.datetime.combine(day, stop_at), tz=IST) if stop_at else close_ts
    if now >= close_ts:
        st = engine.journal.get_state("intraday_open") or {}
        if st.get("day") == str(day) and not st.get("ended") and (st.get("trades") or st.get("closed")):
            engine.start_session(day)                   # a handed-over session nobody closed: close it now
            return engine.end_session()
        return f"the {day} session is over"
    if handover and now >= end:
        return f"past the hand-over time {stop_at:%H:%M}; nothing to do"
    if now < open_ts:
        engine.say(f"waiting for the open ({open_ts:%H:%M})…")
        # read the news while waiting, so the opening read (and the site's News tab) already know the overnight stories
        while engine.feed.now() < open_ts:
            n = engine.feed.now()
            if engine.news is not None:
                engine._refresh_news(n)
            engine.preopen(n)
            engine.journal.commit()
            time.sleep(max(1.0, min(240.0, (open_ts - n).total_seconds() + 5)))
    engine.start_session(day)
    import signal

    def _stop(signum, frame):                             # a cancelled run: save state first, then stop
        raise SystemExit(f"signal {signum}")
    try:
        prev = signal.signal(signal.SIGTERM, _stop)
    except ValueError:                                    # not the main thread (tests): no handler
        prev = None
    try:
        while engine.feed.now() < end + pd.Timedelta(seconds=30):
            run_step(engine)
            n = engine.feed.now()
            nxt = n.floor("min") + pd.Timedelta(seconds=64)            # the next minute's step, 4 s after it closes
            if handover and end < close_ts and nxt >= end + pd.Timedelta(seconds=30):
                break                                         # P2-10: that step is outside the window; don't idle a minute to find out
            while (left := (nxt - engine.feed.now()).total_seconds()) > 0:
                ticking = getattr(engine.feed, "has_ltp", False)
                time.sleep(max(0.5, min(engine.tick_sec, left)) if ticking else left)
                if ticking and engine.feed.now() < nxt:
                    try:
                        engine.tick()
                    except Exception as exc:                    # the minute step still runs; journal the failure
                        log.exception("tick failed")
                        engine.journal.event(engine.feed.now(), "ERROR", "engine", f"tick: {exc!r}", {"where": _where(exc)})
    except (SystemExit, KeyboardInterrupt):
        try:                                              # whatever happens next, the account is on disk
            engine._persist()
            engine.journal.event(engine.feed.now(), "WARN", "session", "runner stopped: state saved")
            engine.journal.commit()
        finally:
            raise
    finally:
        if prev is not None:
            signal.signal(signal.SIGTERM, prev)
    if handover and end < close_ts:
        engine._persist()
        engine.journal.event(engine.feed.now(), "INFO", "session", f"handed over at {stop_at:%H:%M} with "
                             f"{len(engine.open_trades)} open position(s)")
        engine.journal.commit()
        eq = engine.equity(engine.feed.now())
        return (f"handed over at {stop_at:%H:%M}: {len(engine.open_trades)} open, {len(engine.closed)} closed, "
                f"day P&L ₹{eq - engine.day_start_equity:+,.0f}")
    return engine.end_session()


def run_step(engine: IntradayEngine) -> bool:
    """One minute of the desk, contained: a failure is journaled and counted, a run of them puts the engine in safe
    mode (no entries, positions squared off), and a step slower than `slow_step_sec` is reported."""
    h = engine.health
    t0 = time.monotonic()
    try:
        ok = engine.step()
        h["consecutive_failures"] = 0
    except Exception as exc:                              # keep the loop alive; journal the failure
        ok = False
        log.exception("step failed")
        now = engine.feed.now()
        h["step_errors"] += 1
        h["consecutive_failures"] += 1
        h["last_error"] = f"{now:%H:%M} {exc!r:.160}"
        engine.journal.event(now, "ERROR", "engine", repr(exc), {"where": _where(exc)})
        if h["consecutive_failures"] >= engine.max_step_failures:
            engine.enter_safe_mode(now, f"{h['consecutive_failures']} steps failed in a row, last: {exc!r:.120}")
        try:
            engine._wallclock_exits(now)                  # a failing step must not cost the 15:15 square-off
        except Exception:
            log.exception("wall-clock exits failed")
        try:
            engine.journal.commit()
        except Exception:
            pass
    dt_ = time.monotonic() - t0
    h["last_step_sec"] = round(dt_, 2)
    if dt_ > engine.slow_step_sec:
        h["slow_steps"] += 1
        engine.journal.event(engine.feed.now(), "WARN", "engine", f"slow step: {dt_:.0f}s (the loop is falling behind)")
    return ok


def close_out(engine: IntradayEngine, note: str = "stopped by the operator") -> str:
    """Square off today's open positions now, at current prices, and close the session: what
    cancelling the day's run (the kill switch) does, so no paper position is left dangling."""
    day = engine.feed.now().date()
    st = engine.journal.get_state("intraday_open") or {}
    if st.get("day") != str(day) or st.get("ended") or not st.get("trades"):
        return "nothing open to close"
    engine.start_session(day)
    return engine.end_session("manual", note)
