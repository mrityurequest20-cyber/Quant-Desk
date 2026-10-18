"""Decision step of the shadow replay: the desk's own detectors, called unmodified, on bars that had closed by `now`.

  features.session_state  -> the market state     analyst.Analyst.assess -> the view (underlying evidence only)
  playbook.Playbook.scan  -> confirmed setups     playbook.Playbook.arm   -> anticipated setups (level known, fill later)

`decide` filters its input to bars whose minute has closed at `now` (index + 1 minute <= now), exactly as ReplayFeed.poll
does, so passing it the whole day or only the past gives the same answer (tests/test_shadow_replay.py enforces it).
What the live decision also uses and this one cannot: the option chain's own analytics, order flow, news, the brain, the
direction model, the setup record, the EV floor and the model gates. A setup found here is a candidate, not a trade."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..intraday.analyst import Analyst, MarketView
from ..intraday.chains import IntradayPricer, ModelOptionChain, fill_iv
from ..intraday.features import session_state
from ..intraday.playbook import Armed, Playbook, TradePlan

BAR = pd.Timedelta(minutes=1)


@dataclass
class Decision:
    now: pd.Timestamp
    view: MarketView
    state: dict
    chain: pd.DataFrame
    plans: list[TradePlan]          # confirmed setups (scan)
    armed: list[Armed]              # anticipated setups (arm)
    iv: float
    iv_source: str


class Detector:
    def __init__(self, cfg, symbol: str, calendar, vix: pd.DataFrame | None = None, default_iv: float = 0.15):
        self.cfg, self.symbol, self.cal = cfg, symbol, calendar
        self.vix = vix
        self.default_iv = default_iv
        self.analyst = Analyst(cfg)
        pricer = IntradayPricer(cfg.get("backtest.risk_free", 0.065), cfg.get("backtest.dividend_yield", 0.012))
        self.pricer = pricer
        self.playbook = Playbook(cfg, pricer)
        cap = float(cfg.get("intraday.capital", 20000))
        short_from = cfg.get("intraday.short_legs_from_equity", 300000)
        self.playbook.allow_short = short_from is not None and cap >= float(short_from)   # as the engine's _short_legs
        ant = cfg.get("intraday.anticipate", {}) or {}
        self.ant = {"enabled": bool(ant.get("enabled", True)), "ttl_min": float(ant.get("ttl_min", 2)),
                    "buffer_atr5": float(ant.get("buffer_atr5", 0.10)), "reach_atr5": float(ant.get("reach_atr5", 1.5)),
                    "setups": tuple(ant.get("setups", ("orb", "trend_break", "vwap_trend")))}
        self.expiry_min_days = int(cfg.get("intraday.expiry_min_days", 1))
        self.cache: dict = {}
        self._iv = (self.default_iv, "default")
        self.model = ModelOptionChain(cfg, calendar, lambda u, ts: (self._spot, self._iv[0]), pricer)
        self._spot = 0.0

    def atm_iv(self, now: pd.Timestamp, s: dict) -> tuple[float, str]:
        """ATM IV for the model chain, as the engine's model_state: India VIX x iv_beta (the last closed print)."""
        beta = float(self.cfg.instrument_spec(self.symbol).get("iv_beta", 1.0))
        if self.vix is not None and len(self.vix):
            c = self.vix[self.vix.index + BAR <= now]["close"]
            c = c[c > 0]
            if len(c):
                return float(np.clip(c.iloc[-1] / 100 * beta, 0.05, 1.5)), "vix*beta"
        rv = s.get("rv_5d")
        if rv is not None and rv == rv and rv > 0:
            return float(np.clip(rv / 100, 0.05, 1.5)), "rv_5d"
        return self.default_iv, "default"

    def expiry_for(self, day: dt.date, book_expiries: list[dt.date]) -> tuple[dt.date, str]:
        """The expiry the desk would trade (pick_expiry): nearest at least expiry_min_days away. Real option-minute expiries
        when there are any, the calendar's otherwise."""
        pool = [e for e in book_expiries if (e - day).days >= self.expiry_min_days]
        if pool:
            return pool[0], "option-minutes"
        spec = self.cfg.instrument_spec(self.symbol)
        exps = self.cal.expiries(day, 70, int(spec.get("expiry_weekday", 1)), bool(spec.get("weekly_expiry", True)))
        exps = [e for e in exps if (e - day).days >= self.expiry_min_days]
        return exps[0], "calendar"

    def is_expiry_day(self, day: dt.date) -> bool:
        spec = self.cfg.instrument_spec(self.symbol)
        exps = self.cal.expiries(day, 10, int(spec.get("expiry_weekday", 1)), bool(spec.get("weekly_expiry", True)))
        return bool(exps) and exps[0] == day

    def decide(self, bars: pd.DataFrame, now: pd.Timestamp, expiry: dt.date, expiry_day: bool = False) -> Decision | None:
        visible = bars[bars.index + BAR <= now]
        s = session_state(visible, now, tick=0.05, cache=self.cache)
        if s is None:
            return None
        iv, src = self.atm_iv(now, s)
        self._spot, self._iv = float(s["last"]), (iv, src)
        view = self.analyst.assess(self.symbol, s, None, None, expiry_day, None, None)
        ch = self.model.chain(self.symbol, expiry, spot=self._spot, ts=now)
        ch = fill_iv(ch, self.pricer)
        plans = self.playbook.scan(view, s, ch, now)
        armed = (self.playbook.arm(view, s, now, ttl_min=self.ant["ttl_min"], buffer_atr5=self.ant["buffer_atr5"],
                                   reach_atr5=self.ant["reach_atr5"], setups=self.ant["setups"],
                                   why=f"{view.bias} read, score {view.score:+.2f}, conviction {view.conviction:.2f}")
                 if self.ant["enabled"] else [])
        return Decision(now, view, s, ch, plans, armed, iv, src)

    def fire(self, a: Armed, d: Decision, S: float) -> TradePlan | None:
        """The trade an armed setup becomes when price reaches its level (playbook.fire), priced off the decision's chain."""
        return self.playbook.fire(a, d.view, d.chain, d.now, S)
