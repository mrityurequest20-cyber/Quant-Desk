"""Instrument registry: lot size, tick, segment, strike step, expiry rule, cost parameters and calendar per instrument.

Config-driven: the five indices come from the desk's own `instruments:` section; the stocks are `collect_wide.stocks`
(or `shadow.stock_names` until that section is merged), with their contract specs under `shadow.stocks`. Adding an
instrument is a config edit. A spec that was not verified against an exchange source carries `unverified: true`, and
every setup row of that instrument carries it too: P&L in rupees per lot is only as good as the lot size."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.calendar import TradingCalendar

BSE = {"SENSEX", "BANKEX"}


@dataclass(frozen=True)
class InstrumentSpec:
    name: str
    kind: str                      # index | stock
    lot_size: int | None           # None: not known, nothing is priced for it
    tick_size: float
    strike_step: float | None
    segment: str                   # derivatives segment: nse_fo | bse_fo
    cash_segment: str              # nse_cm | bse_cm
    expiry_weekday: int
    weekly_expiry: bool
    iv_beta: float
    cost_segment: str              # key of costs.segments (the desk's own statutory model)
    unverified: bool = False
    notes: tuple = field(default_factory=tuple)

    def as_instrument_spec(self) -> dict:
        """What cfg.instrument_spec(name) returns for the detectors (read-only use of the desk's own lookup)."""
        return {"kind": self.kind if self.kind == "index" else "equity", "lot_size": int(self.lot_size or 1),
                "strike_step": float(self.strike_step or 1), "weekly_expiry": self.weekly_expiry,
                "expiry_weekday": self.expiry_weekday, "iv_beta": self.iv_beta}


def _shadow(cfg) -> dict:
    return cfg.get("shadow", {}) or {}


def names(cfg) -> tuple[list[str], list[str]]:
    sh = _shadow(cfg)
    cw = cfg.get("collect_wide", {}) or {}
    idx = [str(x).upper() for x in (cw.get("indices") or sh.get("indices") or [])]
    stocks = [str(x).upper() for x in (cw.get("stocks") or sh.get("stock_names") or [])]
    return idx, stocks


def load(cfg) -> dict[str, InstrumentSpec]:
    sh = _shadow(cfg)
    idx, stocks = names(cfg)
    inst = cfg.get("instruments", {}) or {}
    extra = sh.get("overrides", {}) or {}
    tick = float(sh.get("tick_size", cfg.get("slippage.option_tick", 0.05)))
    out: dict[str, InstrumentSpec] = {}
    for n in idx:
        spec = {**inst.get(n, {}), **(extra.get(n) or {})}
        if not spec:
            out[n] = InstrumentSpec(n, "index", None, tick, None, "nse_fo", "nse_cm", 1, False, 1.0, "options", True,
                                    ("not in config instruments:",))
            continue
        bse = n in BSE
        out[n] = InstrumentSpec(
            n, "index", int(spec["lot_size"]), float(spec.get("tick_size", tick)), float(spec["strike_step"]),
            "bse_fo" if bse else "nse_fo", "bse_cm" if bse else "nse_cm", int(spec.get("expiry_weekday", 1)),
            bool(spec.get("weekly_expiry", False)), float(spec.get("iv_beta", 1.0)), "options",
            bool(spec.get("unverified", False)),
            ("NSE statutory rates applied to a BSE contract (no separate BSE schedule in costs:)",) if bse else ())
    stock_cfg = sh.get("stocks", {}) or {}
    for n in stocks:
        spec = stock_cfg.get(n) or {}
        lot = spec.get("lot_size")
        out[n] = InstrumentSpec(
            n, "stock", int(lot) if lot else None, float(spec.get("tick_size", tick)),
            float(spec["strike_step"]) if spec.get("strike_step") else None, "nse_fo", "nse_cm",
            int(spec.get("expiry_weekday", 1)), False, float(spec.get("iv_beta", 1.0)), "options",
            bool(spec.get("unverified", True)) or not lot, ("stock options are monthly",))
    return out


def calendar(cfg) -> TradingCalendar:
    """The trading calendar. BSE follows the NSE holiday list in this config (assumption: noted, not verified)."""
    return TradingCalendar(cfg.holidays())


def derived_config(cfg, reg: dict[str, InstrumentSpec]):
    """A copy of the config in which every registry instrument answers cfg.instrument_spec() with its registry values,
    so the unmodified detectors see the right lot size and strike step."""
    return cfg.with_overrides({"instruments": {n: {**cfg.instrument_spec(n), **s.as_instrument_spec()}
                                                for n, s in reg.items() if s.lot_size}})
