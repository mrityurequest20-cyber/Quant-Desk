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
import time
import traceback
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.calendar import TradingCalendar
from ..core.types import OPTIONS, Instrument, Order, Trade, TradeLeg, new_trade_id
from ..journal.journal import Journal, trade_from_dict, trade_to_dict
from .analyst import Analyst, MarketView
from .chainflow import ChainFlow, chain_step
from .chains import ChainSource, IntradayPricer, ModelOptionChain, chain_analytics, fill_iv, liquidity, time_to_expiry
from .features import session_state
from .feeds import IST, IntradayFeed, ReplayFeed, session_bounds
from .ivhist import iv_percentile
from .orderflow import FootprintBuilder
from .playbook import Playbook, TradePlan
from .quant import DirectionModel, EVEngine, VolForecaster, features_5m, load_research, session_sigma, to_5m
from .risk import IntradayRisk
from .sim import IntradayBroker, QuoteMarker

log = logging.getLogger(__name__)


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
        self.volf = VolForecaster()
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
        self.chain_at: dict[str, pd.Timestamp] = {}
        self.chain_fail: dict[str, int] = {}
        self.chain_tried: dict[str, pd.Timestamp] = {}
        self.expiry: dict[str, dt.date] = {}
        self.open_trades: list[Trade] = []
        self.closed: list[Trade] = []
        self.views: dict[str, MarketView] = {}
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
        vix = float(v.loc[:ts]["close"].iloc[-1]) if v is not None and len(v.loc[:ts]) else 14.0
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
            val += sum(l.qty * self.marker.mid(l.instrument, S, now) for l in t.legs)
        return self.broker.cash() + val

    def spot(self, u: str) -> float:
        return float(self.bars[u]["close"].iloc[-1])

    # ---- session lifecycle ------------------------------------------------------------------------------
    def start_session(self, day: dt.date) -> None:
        self.day = day
        for sym in self.underlyings + [self.vix]:
            h = self.feed.history(sym, self.history_days)
            self.bars[sym] = h.tail(375 * self.history_days) if h is not None else \
                pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            self.last_ts[sym] = h.index[-1] if h is not None and len(h) else None
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
        self.events_today = self.eventbook.describe(day, self.cal.prev_trading_day(day))
        saved = self._restore(day)
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
        if self.quant_on:
            self._train_models(day)
        exp = ", ".join(f"{u} {e:%d-%b}" for u, e in self.expiry.items())
        self.say(f"── session {day} · capital ₹{self.day_start_equity:,.0f} · expiries {exp} · chain {self.chains.name} "
                 f"· feed {self.feed.name}{' · events: ' + ', '.join(self.events_today) if self.events_today else ''}")
        self.journal.event(session_bounds(day)[0], "INFO", "session", f"session start; expiries {exp}; chain {self.chains.name}")

    def step(self) -> bool:
        now = self.feed.now()
        self._commands(now)
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
                self.recorder.record_bars(sym, new)
                fb = getattr(self.feed, "fut_bars", {}).get(sym)
                if fb is not None and len(fb):                  # the futures' own bars, for the chart and replays
                    self.recorder.record_bars(f"{sym}-FUT", fb[fb.index.date == fb.index[-1].date()])
            got = got or sym in self.underlyings
        if self.feed.has_ticks:
            for u in self.underlyings:
                for t in self.feed.trades(u):
                    self.flow[u].add(t)
        if not got:
            return False
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
        for u in self.underlyings:
            if u not in self.bars or self.bars[u].empty or self.bars[u].index[-1].date() != self.day:
                continue
            self._refresh_chain(u, now)
            s = session_state(self.bars[u], now, cache=self.feature_cache[u])
            if s is None:
                continue
            q = self._guarded(u, now, "quant state", self._quant_state, u, now) if self.quant_on else None
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
            exits = self._manage(u, view, now)
            action = self._maybe_enter(u, view, s, now)
            if self.anticipate:
                action = self._arm(u, view, s, now, action)
            self._think(u, view, now, "; ".join(exits + [action]) if exits else action, force=bool(exits))
        if now.time() >= self.risk.square_off:
            for t in list(self.open_trades):
                self._close(t, now, "square_off", f"intraday square-off at {self.risk.square_off:%H:%M}")
        self._snapshot(now)
        self._persist()
        self._heartbeat(now)
        self.journal.commit()
        return True

    def end_session(self, reason: str = "square_off", note: str = "end of session") -> str:
        now = self.feed.now()
        for u in {t.symbol for t in self.open_trades} - set(self.chain_df):
            self._refresh_chain(u, now)                 # exits priced off a calibrated chain, never a default IV
        for t in list(self.open_trades):
            self._close(t, now, reason, note)
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
        at = self.chain_at.get(u)
        if at is not None and (now - at) < pd.Timedelta(minutes=self.refresh_min):
            return
        try:
            ch = None
            fails = self.chain_fail.get(u, 0)
            tried = self.chain_tried.get(u)
            # after 3 straight failures, only retry the real chain every 15 minutes (each try can block ~20s)
            if self.chains is not self.model_chain and (fails < 3 or tried is None or now - tried >= pd.Timedelta(minutes=15)):
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
            an = chain_analytics(ch, self.pricer, self.lot(u))
            if ch.attrs.get("source") != "model":             # the model chain's IV is India VIX's, not this market's
                an.update(iv_percentile(self.iv_hist.get(u), an.get("atm_iv"), (self.expiry[u] - now.date()).days, now.date()))
            an.update(self._futures(u, now, an.get("spot")))
            an.update(self.chainflow.update(u, an, now, chain_step(ch)))
            self.chain_an[u] = an
            self.chain_at[u] = now
            self.marker.calibrate(ch, self.lot(u))
            if self.recorder and ch.attrs.get("source") != "model":
                self.recorder.record_chain(ch)
        except Exception as exc:
            self.chain_at[u] = now
            self.journal.event(now, "WARN", "chain", f"{u} chain refresh failed: {exc}")

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
        if today.empty:
            return None
        base = float(prev["close"].iloc[-1]) if len(prev) else float(today["open"].iloc[0])
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
            at_s = replace(view, spot=float(S))
            eq = self.equity(now)
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
                lots, notes = self.risk.size(plan, eq, self.broker.cash())
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
        """Hand what the record says to the parts that use it."""
        if self.memory is None:
            return
        self.analyst.learned = self.memory.factor_weights()
        from .analyst import PROBATION, PROMOTE_N, PROMOTE_REL
        self.analyst.graduated = {f for f in PROBATION if (self.memory.stat("factor", f) or {"n": 0})["n"] >= PROMOTE_N
                                  and self.memory.reliability("factor", f) >= PROMOTE_REL}
        if self.brain is not None:                        # probation drivers earn a vote on their live record
            self.brain.learned = {k: (self.memory.reliability("factor", k), float(r["n"]))
                                  for k, r in (self.memory.d["tables"].get("factor") or {}).items()
                                  if k.startswith(("global_", "heavy_"))}
        if self.news is not None:
            self.news.trust = self.memory.news_trust
            self.news.reader_trust = lambda name: self.memory.reliability("news_reader", name)

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
        if claude is not None and self.cfg.get("intraday.llm.claude.reflect", True):
            from .learning import summary
            try:
                got = claude.reflect(review, summary(self.memory) if self.memory is not None else [])
            except Exception as exc:
                got = None
                self.journal.event(now, "WARN", "llm", f"reflection failed: {exc!s:.200}")
            if got and (got["lessons"] or got["watch_tomorrow"]):
                out += ["", "## Reflection (Claude, after the close)", ""] + [f"- {x}" for x in got["lessons"]]
                if got["watch_tomorrow"]:
                    out += ["", "Watch at tomorrow's open:"] + [f"- {x}" for x in got["watch_tomorrow"]]
                if self.memory is not None:
                    self.memory.d["lessons"].append({"day": str(self.day), **got})
                    self.memory.save()
        from .llm import cost_line
        lc = self.cfg.get("intraday.llm", {}) or {}
        prices = {k: {"in": (lc.get(k) or {}).get("price_in", 0), "out": (lc.get(k) or {}).get("price_out", 0)}
                  for k in ("claude", "gemini", "ollama") if (lc.get(k) or {}).get("price_in") is not None}
        cost = cost_line(desk.usage(), prices)
        if cost or desk.errors:
            line = "Language models today: " + (cost or "no calls") + (
                "; problems: " + "; ".join(f"{k}: {v}" for k, v in desk.errors.items()) if desk.errors else "")
            out += ["", line]
            self.journal.event(now, "INFO", "llm", line, {"usage": desk.usage(), "errors": desk.errors})
        return "\n".join(out)

    def _by_record(self, u: str, plans: list, view: MarketView, now) -> tuple[list, str | None]:
        """Each setup's own record of R (by day type when it has one) scales its conviction, and a clearly losing
        record stands it aside. A fresh desk changes nothing."""
        if self.memory is None:
            return plans, None
        kept, stop = [], None
        for p in plans:
            m, why = self.memory.setup_mult(p.setup, view.day_type)
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
        if self.paused:
            return "standing aside: new entries paused from the app"
        if view.vetoes:
            return f"standing aside: {view.vetoes[0]}"
        if u not in self.chain_df:
            return "standing aside: no option chain"
        age = now - self.chain_at.get(u, now)
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
        if self.quant_on:
            pick = self._guarded(u, now, "EV selection", self._select_by_ev, u, plans, view, eq, now)
            if pick is None:
                return "standing aside: the quant layer failed on this minute (see events)"
            if isinstance(pick, str):
                return pick
            plan, lots, notes = pick
            return self._open(plan, lots, notes, view, s, now)
        plan = max(plans, key=lambda p: p.conviction)
        lots, notes = self.risk.size(plan, eq, self.broker.cash())
        if lots < 1:
            self.journal.decision(now, plan.setup, u, "rejected", " | ".join(notes), 0, {"plan": plan.describe()})
            return f"setup {plan.setup} found but sized to 0 lots ({notes[-1]})"
        return self._open(plan, lots, notes, view, s, now)

    # ---- quant layer --------------------------------------------------------------------------------------------
    def preopen(self, now) -> None:
        """Before the open, every few minutes: GIFT Nifty (NSE IX's NIFTY future, trading since 06:30 IST), the
        overnight cue in one number. Recorded with the session; context for the read, not evidence (untested)."""
        if self.gift_source is None or (self._gift_at is not None and now - self._gift_at < pd.Timedelta(minutes=4)):
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
                lots, notes = self.risk.size(v, eq, self.broker.cash())
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
        t = Trade(id=new_trade_id("I"), strategy=plan.setup, family="intraday", symbol=u, direction=plan.direction,
                  kind=OPTIONS, legs=[], units=lots, opened_at=now, entry_underlying=view.spot,
                  initial_risk=plan.planned_risk_per_lot() * lots, stop=plan.invalidation, target=plan.target_underlying,
                  exit_rules={"premium_stop": plan.premium_stop, "premium_target": plan.premium_target,
                              "time_stop_min": plan.time_stop_min, "credit": plan.is_credit},
                  rationale=(f"[{plan.setup}] Trigger: {plan.trigger}. Thesis: {plan.thesis} "
                             f"Structure: {plan.describe()} (vol view {view.vol_view}). "
                             + (f"Quant: {plan.notes['quant_text']}. " if plan.notes.get("quant_text") else "")
                             + f"Market read: {view.narrative}"),
                  context={"regime": view.day_type, "bias": view.bias, "score": round(view.score, 3),
                           "conviction": round(view.conviction, 3), "vol_view": view.vol_view,
                           "evidence": [(e.factor, round(e.direction, 2), e.observation) for e in view.evidence],
                           "levels": {k: round(float(v), 2) for k, v in view.levels.items() if v == v and v is not None},
                           "chain": {k: v for k, v in view.chain.items() if isinstance(v, (int, float, str))}},
                  meta={"structure": plan.structure, "expiry": str(plan.expiry), "quote_source": plan.quote_source,
                        "entry_net_premium_per_lot": plan.net_premium, "max_loss": plan.max_loss_per_lot(),
                        "legs_plan": [(l.strike, l.right, l.ratio, round(l.price, 2), round(l.iv, 2), round(l.delta, 3))
                                      for l in plan.legs], **plan.notes})
        insts = [Instrument.option(u, plan.expiry, l.strike, l.right, plan.lot_size) for l in plan.legs]
        live = self._live(insts, now)
        t.meta["leg_liquidity"] = self._leg_liquidity(u, insts, plan.legs, live)
        if live and any(i.symbol not in live for i in insts):
            # the book answered, but not two-sided for every leg: a real order there may not fill at all
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
                for done in t.legs:
                    self.broker.execute(Order(done.instrument, -done.qty, t.id, "unwind"), done.entry_price, now)
                return f"order for {inst.symbol} rejected; nothing opened"
            self.journal.fill(now, t.id, inst.symbol, qty, fill.price, fill.fees, fill.fee_breakdown)
            t.legs.append(TradeLeg(inst, qty, fill.price))
            t.fees += fill.fees
        t.pnl = -t.fees
        t.last_mark = {l.instrument.symbol: l.entry_price for l in t.legs}
        self.open_trades.append(t)
        self.risk.trades_today += 1
        self.journal.open_trade(t, notes)
        msg = f"ENTER {plan.setup} {lots}×{plan.describe()} | stop {plan.invalidation or '—'} | {plan.trigger}"
        self.say(f"  {now:%H:%M} {u:<9} ▲ {msg}")
        return msg

    def _manage(self, u: str, view: MarketView, now) -> list[str]:
        out = []
        S = view.spot
        for t in [x for x in self.open_trades if x.symbol == u]:
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
        return out

    def _close(self, t: Trade, now, reason: str, note: str) -> str:
        S = self.spot(t.symbol)
        live = self._live([l.instrument for l in t.legs], now)
        t.meta["exit_quotes"] = f"live {self.chains.name} book" if len(live) == len(t.legs) else "marked"
        for l in t.legs:
            q = live.get(l.instrument.symbol)
            px = (q[0] if l.qty > 0 else q[1]) if q else self.marker.exit_price(l.instrument, l.qty, S, now)
            fill = self.broker.execute(Order(l.instrument, -l.qty, t.id, "close"), px, now)
            if fill is None:
                self.journal.event(now, "ERROR", "execution", f"exit {l.instrument.symbol} rejected for {t.id}")
                continue
            self.journal.fill(now, t.id, l.instrument.symbol, -l.qty, fill.price, fill.fees, fill.fee_breakdown)
            l.exit_price = fill.price
            t.fees += fill.fees
        t.pnl = sum(l.qty * ((l.exit_price or l.entry_price) - l.entry_price) for l in t.legs) - t.fees
        t.mae, t.mfe = min(t.mae, t.pnl), max(t.mfe, t.pnl)
        t.status, t.closed_at, t.exit_reason, t.exit_note, t.exit_underlying = "closed", now, reason, note, S
        t.bars_held = int((now - t.opened_at).total_seconds() // 60)
        self.open_trades.remove(t)
        self.closed.append(t)
        v = self.views.get(t.symbol)
        rv = self.journal.close_trade(t, v.day_type if v else None)
        self.risk.on_close(t.pnl, now)
        msg = f"EXIT {t.strategy} {reason}: ₹{t.pnl:,.0f} ({t.r_multiple:+.2f}R, grade {rv['grade']}) — {note}"
        self.say(f"  {now:%H:%M} {t.symbol:<9} ▼ {msg}")
        return msg

    # ---- remote control (the app writes commands; the engine executes them) ----------------------------------
    def _commands(self, now) -> None:
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
        self.journal.set_state("intraday_live", {
            "ts": str(now), "day": str(self.day), "equity": eq, "day_start_equity": self.day_start_equity,
            "day_pnl": eq - self.day_start_equity, "paused": self.paused, "halted": self.risk.halted,
            "trades_today": self.risk.trades_today, "feed": self.feed.name, "chain": self.chain_name(),
            "views": views, "positions": positions,
            "armed": [a.to_record() for u in self.underlyings for a in self.armed.get(u, []) if now <= a.expires],
            "news_health": dict(self.news.health) if self.news is not None else None,
            "global": _global_view(self.brain, now), "gift": self.gift, "events": self.events_today,
            "learning": self._learning_view()})

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
                                      "voting": f in self.analyst.graduated} for f in PROBATION}}
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

    def _persist(self, ended: bool = False) -> None:
        r = self.risk
        self.journal.set_state("intraday_open", {
            "day": str(self.day), "ended": ended, "trades": [trade_to_dict(t) for t in self.open_trades],
            "closed": [trade_to_dict(t) for t in self.closed if t.opened_at.date() == self.day],
            "day_start_equity": self.day_start_equity,
            "risk": {"trades_today": r.trades_today, "consec_losses": r.consec_losses, "halted": r.halted,
                     "cool_until": str(r.cool_until) if r.cool_until is not None else None}})

    def _restore(self, day: dt.date) -> dict:
        """Pick up today's session after a restart: open positions, the trades already closed, the day's
        starting equity and the risk state (trade count, loss streak, cooldown, halt)."""
        st = self.journal.get_state("intraday_open") or {}
        if st.get("day") != str(day):
            if st.get("trades"):
                self.journal.event(pd.Timestamp.now(tz=IST), "WARN", "session",
                                   f"{len(st['trades'])} position(s) from {st.get('day')} were never squared off; ignored")
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
        th = self.journal.thoughts(str(day))
        end_eq = self.broker.cash()
        L = [f"# Intraday session review — {day}", "",
             f"Capital ₹{self.day_start_equity:,.0f} → ₹{end_eq:,.0f} (**{end_eq / self.day_start_equity - 1:+.2%}**, "
             f"₹{end_eq - self.day_start_equity:+,.0f}); {len(trades)} trade(s); chain source {self.chain_name()}; "
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
                L.append(f"| {t.opened_at:%H:%M}–{t.closed_at:%H:%M} | {t.strategy} {t.symbol} | {t.meta.get('structure')} | "
                         f"{t.units} | {t.pnl:,.0f} | {t.r_multiple:+.2f} | {t.exit_reason} | "
                         f"{self._grade(t.id)} |")
            L.append("")
            for t in trades:
                L += [f"**{t.id} · {t.strategy} {t.symbol}** — {t.rationale}", f"Exit: {t.exit_reason} — {t.exit_note}.", ""]
            wins = sum(t.pnl > 0 for t in trades)
            L.append(f"Win rate {wins}/{len(trades)}, net ₹{sum(t.pnl for t in trades):,.0f}, costs ₹{sum(t.fees for t in trades):,.0f}.")
        else:
            reasons = th["action"].str.extract(r"^(standing aside|watching)[^:]*: (.*)$")[1].dropna().value_counts().head(4) \
                if not th.empty else pd.Series(dtype=int)
            L.append("No trades. Most common reasons: " + "; ".join(f"{k} (x{v})" for k, v in reasons.items()))
        if self.memory is not None:
            from .learning import summary
            got = self.learned_today
            lines = summary(self.memory)
            L += ["", "## What the desk learned", "",
                  (f"Graded today: {got.get('news', 0)} news calls, {got.get('factors', 0)} factor reads, "
                   f"{got.get('trades', 0)} trades, {got.get('armed', 0)} refused pre-break entries. "
                   if got else "")
                  + f"Record over {len(self.memory.d['days'])} session(s); every weight is shrunk toward 1× until the "
                    f"record is long enough to mean something."]
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
    while engine.feed.now() < end + pd.Timedelta(seconds=30):
        try:
            engine.step()
        except Exception as exc:                        # keep the loop alive; journal the failure
            log.exception("step failed")
            engine.journal.event(engine.feed.now(), "ERROR", "engine", repr(exc), {"where": _where(exc)})
        n = engine.feed.now()
        nxt = n.floor("min") + pd.Timedelta(seconds=64)            # the next minute's step, 4 s after it closes
        while (left := (nxt - engine.feed.now()).total_seconds()) > 0:
            ticking = getattr(engine.feed, "has_ltp", False)
            time.sleep(max(0.5, min(engine.tick_sec, left)) if ticking else left)
            if ticking and engine.feed.now() < nxt:
                try:
                    engine.tick()
                except Exception as exc:                    # the minute step still runs; journal the failure
                    log.exception("tick failed")
                    engine.journal.event(engine.feed.now(), "ERROR", "engine", f"tick: {exc!r}", {"where": _where(exc)})
    if handover and end < close_ts:
        engine._persist()
        engine.journal.event(engine.feed.now(), "INFO", "session", f"handed over at {stop_at:%H:%M} with "
                             f"{len(engine.open_trades)} open position(s)")
        engine.journal.commit()
        eq = engine.equity(engine.feed.now())
        return (f"handed over at {stop_at:%H:%M}: {len(engine.open_trades)} open, {len(engine.closed)} closed, "
                f"day P&L ₹{eq - engine.day_start_equity:+,.0f}")
    return engine.end_session()


def close_out(engine: IntradayEngine, note: str = "stopped by the operator") -> str:
    """Square off today's open positions now, at current prices, and close the session: what
    cancelling the day's run (the kill switch) does, so no paper position is left dangling."""
    day = engine.feed.now().date()
    st = engine.journal.get_state("intraday_open") or {}
    if st.get("day") != str(day) or st.get("ended") or not st.get("trades"):
        return "nothing open to close"
    engine.start_session(day)
    return engine.end_session("manual", note)
