"""The allocator (docs/prereg/allocator_v1.json), PHASE 1: SHADOW ONLY.

Each evening, would the registered allocator have carried an ELIGIBLE, DEFINED-RISK expiry-seller condor in the paper account
overnight, one night, to its sleeve's own expiry, how many lots (max loss, fees included, at most 2.5% of equity), and what would
it have made? It journals exactly that and nothing else: it holds only read-only views of the journal and the broker
(`_ReadOnlyJournal`, `_ReadOnlyBroker`), so it cannot write to the paper account, place an order or register a carry. `apply`
is not implemented: it runs as shadow, and says so. The registry, the square-off exemption and the halt recognition that a real
carry needs are a later phase.

Nothing here picks a strike, a delta, an expiry or a fill. The expiry-seller sleeves (sleeves.py) decide and record each eve's
condor on real quotes; the allocator takes that recorded trade, re-verifies the structure, prices all four legs from recorded
real quotes as the paper broker would fill them (all-or-nothing), sizes whole lots, and checks every desk limit and halt.

Read it in this order: `limits` (min of the desk's configured value and the spec's ceiling) -> `gates` (the paper account's
state that must be clear) -> `price_legs`, `structure_problems`, `carry_problems` -> `size` -> `Allocator.decide` (every rule, no
side effects) -> `mark_shadows`, `settle_shadows` (real quotes, then the sleeve's own settlement) -> `report`.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from ..core.calendar import TradingCalendar
from ..core.types import Instrument
from .chains import load_chain
from .engine import DD_KEY, DD_PEAK_KEY
from .feeds import IST
from .halt import HALT_KEY, book_diff
from .risk import IntradayRisk
from .sleeves import PREREG, REAL_SOURCES, intrinsic

SPEC_PATH = PREREG / "allocator_v1.json"
MODES = ("off", "shadow", "apply")
SHADOW_SESSIONS_REQUIRED = 5                  # distinct sessions with a recorded shadow would-place before apply takes effect
HALT_FLAGS = ("kill_switch", "journal", "daily_loss", "safe_mode", "reconcile", "inherited")   # intraday_live["halts"]
BAD_FLAGS = ("locked", "late")                # a leg or snapshot flagged this refuses the allocation
ENTRY_AFTER = dt.time(15, 26)                 # the sleeves open from here; settlement is recorded from 15:31


def load_spec(path: Path = SPEC_PATH) -> dict:
    raw = Path(path).read_bytes()
    spec = json.loads(raw)
    spec["_hash"] = hashlib.sha256(raw).hexdigest()[:12]
    return spec


def settings(cfg) -> dict:
    """`intraday.allocator.mode`: off | shadow | apply. Anything else is shadow (as the earn-in gate)."""
    mode = str((cfg.get("intraday.allocator", {}) or {}).get("mode", "shadow")).lower()
    return {"mode": mode if mode in MODES else "shadow"}


# ---- read-only views: what shadow mode is given ----------------------------------------------------------------------
class _ReadOnlyJournal:
    def __init__(self, journal):
        self._j = journal

    def get_state(self, key, default=None):
        return self._j.get_state(key, default)

    def df(self, sql: str, params=()):
        if not sql.lstrip().upper().startswith("SELECT"):
            raise PermissionError("shadow mode reads the journal, it does not write it")
        return self._j.df(sql, params)


class _ReadOnlyBroker:
    live = False

    def __init__(self, broker):
        self._b = broker
        self.name, self.costs = broker.name, broker.costs

    def positions(self):
        return {k: dict(v) for k, v in self._b.positions().items()}

    def cash(self):
        return self._b.cash()


# ---- limits ---------------------------------------------------------------------------------------------------------
def _cap(configured, ceiling):
    return ceiling if configured is None else min(configured, ceiling)


def limits(cfg, spec: dict) -> dict:
    """Every number the allocation is held to: the smaller of the desk's configured value and the spec's ceiling."""
    r, c = IntradayRisk(cfg), spec["limits"]
    dd = cfg.get("intraday.risk.cross_day_drawdown_halt", 0) or 0
    return {"risk_per_trade": _cap(r.risk_per_trade, c["max_loss_per_position"]["ceiling"]),
            "max_trades": int(_cap(r.max_trades, c["max_trades_per_day"]["ceiling"])),
            "max_open": int(_cap(r.max_open, c["max_open"]["ceiling"])),
            "daily_loss": _cap(r.daily_loss, c["daily_loss"]["ceiling"]),
            "max_exposure": _cap(r.max_exposure, c["max_total_outlay"]["ceiling"]),
            "max_margin": _cap(r.max_margin, c["max_total_outlay"]["ceiling"]),
            "dd_halt": _cap(dd or None, c["cross_day_drawdown_halt"]["ceiling"]),
            "max_lots": int(_cap(r.max_lots, c["max_lots"]["ceiling"])),
            "credit_margin": float(r.credit_margin or 0.0),
            "short_from": cfg.get("intraday.short_legs_from_equity", 300000)}


# ---- the paper account, as the gates see it -------------------------------------------------------------------------
def _open_rows(journal) -> list[dict]:
    rows = journal.df("SELECT id, strategy, symbol, units, initial_risk, legs FROM trades WHERE status='open'")
    out = []
    for r in rows.itertuples():
        legs = [l for l in json.loads(r.legs or "[]") if l.get("exit_price") is None]
        out.append({"id": r.id, "strategy": r.strategy, "initial_risk": float(r.initial_risk or 0.0), "legs": legs,
                    "cost": sum(float(l["qty"]) * float(l["entry_price"]) for l in legs)})
    return out


def _as_trades(rows: list[dict]):
    return [SimpleNamespace(id=r["id"], legs=[SimpleNamespace(instrument=SimpleNamespace(symbol=l["instrument"]["symbol"]),
                                                              qty=int(l["qty"])) for l in r["legs"]]) for r in rows]


def gates(cfg, journal, broker, day: dt.date, lim: dict, virtual: list[dict]) -> tuple[list[str], dict]:
    """(every reason the allocation must be refused on the real state, the numbers used). Fail-closed: whatever cannot
    be read refuses. `virtual`: earlier would-place allocations of the same evening (shadow mode counts them)."""
    why: list[str] = []
    if cfg.get("account.mode") != "paper":
        why.append(f"account.mode is {cfg.get('account.mode')!r}, not paper")
    if getattr(broker, "live", True) or getattr(broker, "name", "") != "paper":
        why.append("the broker is not the simulated paper broker")
    kill = Path(cfg.runtime_dir) / str(cfg.get("intraday.kill_switch_file", "KILL"))
    if kill.exists():
        why.append(f"the kill switch file {kill.name} is present")
    live = journal.get_state("intraday_live") or {}
    facts: dict = {}
    if live.get("day") != str(day):
        why.append("no session record for the day: the allocator cannot tell what the day's loss was")
    else:
        if live.get("paused"):
            why.append("new entries are paused from the app")
        on = [k for k in HALT_FLAGS if (live.get("halts") or {}).get(k)]
        if on:
            why.append("the session recorded a halt: " + ", ".join(on))
    if journal.get_state("intraday_paused"):
        why.append("new entries are paused from the app")
    gov = journal.get_state("risk_governor") or {}
    until = str(gov.get("standdown_until") or "")
    if until[:10] == str(day):
        why.append(f"the risk governor stood the desk down ({gov.get('standdown_why')})")
    if journal.get_state(HALT_KEY):
        why.append("an inherited-position halt is active (the owner clears it)")
    if journal.get_state(DD_KEY):
        why.append("the cross-day drawdown halt is active (the owner clears it)")

    rows = _open_rows(journal)
    positions = broker.positions() or {}
    want, have = book_diff(_as_trades(rows), positions)
    if want != have:
        why.append("the broker's positions do not equal the journal's open trades")
    if rows:                                                    # phase 1 registers no carry: anything open is not one
        why.append("an open position is not a registered overnight carry: " + ", ".join(r["id"] for r in rows))

    equity = float(broker.cash()) + sum(r["cost"] for r in rows)
    facts.update(equity=equity, cash=float(broker.cash()), open_positions=len(rows) + len(virtual))
    if not math.isfinite(equity) or equity <= 0:
        why.append("equity unknown")
        return why, facts
    start = live.get("day_start_equity") if live.get("day") == str(day) else None
    open_risk = sum(r["initial_risk"] for r in rows) + sum(v["max_loss"] for v in virtual)
    if start and float(start) > 0:
        dd_day = equity / float(start) - 1
        facts.update(day_start_equity=float(start), day_return=dd_day)
        if not dd_day > -lim["daily_loss"]:
            why.append(f"the day is at its loss limit ({dd_day:.2%} <= -{lim['daily_loss']:.1%})")
        facts["daily_room"] = equity - float(start) * (1 - lim["daily_loss"]) - open_risk
    else:
        facts["daily_room"] = 0.0
    peak = float((journal.get_state(DD_PEAK_KEY) or {}).get("peak") or 0.0)
    if peak > 0:
        facts.update(peak=peak, drawdown=equity / peak - 1)
        if equity / peak - 1 <= -lim["dd_halt"]:
            why.append(f"equity is {equity / peak - 1:.1%} from its peak (halt at {lim['dd_halt']:.0%})")
    else:
        why.append("no equity peak on record: the drawdown cannot be measured")
    today = int(journal.df("SELECT COUNT(*) AS n FROM trades WHERE substr(opened_at,1,10)=?", (str(day),))["n"].iloc[0])
    facts["trades_today"] = today + len(virtual)
    if facts["trades_today"] + 1 > lim["max_trades"]:
        why.append(f"{lim['max_trades']} trades already today")
    if facts["open_positions"] + 1 > lim["max_open"]:
        why.append(f"{lim['max_open']} positions already open")
    blocked = sum(v["margin"] for v in virtual)
    facts["blocked_margin"] = blocked
    facts["open_risk"] = open_risk
    sf = lim["short_from"]
    if sf is None:
        why.append("selling is off (intraday.short_legs_from_equity is null)")
    elif equity < float(sf):
        why.append(f"equity ₹{equity:,.0f} is below ₹{float(sf):,.0f}, the desk's floor for sold legs")
    return why, facts


# ---- the trade as the paper broker would fill it --------------------------------------------------------------------
def paper_fill(broker, inst: Instrument, qty: int, ref: float) -> float:
    """The price IntradayBroker.execute returns for `qty` of `inst` around the reference quote `ref`: one adverse tick,
    then the cost model's own slippage (nil for the intraday broker). Computed before any order is sent."""
    ticks = float(getattr(broker.costs, "opt_half_ticks", 0.0))
    ref = max(ref + (1 if qty > 0 else -1) * ticks * broker.costs.tick, broker.costs.tick)
    return float(broker.costs.fill_price(inst, qty, ref))


def price_legs(ev: dict, broker) -> tuple[list[dict] | None, str]:
    """The sleeve's four recorded legs priced for the paper broker from their recorded real quotes, or (None, why not):
    all-or-nothing, nothing is ever priced from a model."""
    u, exp, lot = ev["underlying"], dt.date.fromisoformat(ev["expiry"]), int(ev["lot"])
    out = []
    for l in ev.get("legs") or []:
        try:
            qty, bid, ask = int(l["qty"]), float(l["bid"]), float(l["ask"])
            strike = float(l["strike"])
        except (KeyError, TypeError, ValueError):
            return None, "a leg has no recorded quote"
        if abs(qty) != 1:
            return None, f"{l.get('right')} {l.get('strike')}: a leg is not one lot"
        if not (math.isfinite(bid) and math.isfinite(ask) and bid > 0 and ask >= bid):
            return None, f"{l['right']} {strike:.0f}: no two-sided real quote"
        inst = Instrument.option(u, exp, strike, l["right"], lot)
        ref = ask if qty > 0 else bid
        out.append({"inst": inst, "symbol": inst.symbol, "qty": qty, "right": l["right"], "strike": strike, "bid": bid,
                    "ask": ask, "ref": ref, "fill": paper_fill(broker, inst, qty, ref), "sleeve_fill": l.get("fill"),
                    "touch_qty": l.get("touch_qty"), "flags": list(l.get("flags") or [])})
    return (out, "") if len(out) == 4 else (None, f"{len(out)} legs recorded, not four")


def structure_problems(legs: list[dict]) -> list[str]:
    """Defined risk, verified from the legs themselves: one short and one long of each right, the long further out of the
    money. Anything else is not a condor and is never allocated, whatever the sleeve called it."""
    bad = []
    for right, sign in (("CE", 1), ("PE", -1)):
        side = [l for l in legs if l["right"] == right]
        shorts, longs = [l for l in side if l["qty"] < 0], [l for l in side if l["qty"] > 0]
        if len(side) != 2 or len(shorts) != 1 or len(longs) != 1:
            bad.append(f"{right}: not exactly one short and one long wing")
        elif not (longs[0]["strike"] - shorts[0]["strike"]) * sign > 0:
            bad.append(f"{right}: the long wing is not further out of the money than the short")
    return bad


def carry_problems(cfg, cal: TradingCalendar, eve: dt.date, expiry: dt.date, now: pd.Timestamp) -> list[str]:
    """One night only: the expiry is the next trading day AND the next calendar day, on a calendar the desk has a holiday
    list for, and the allocation is made in the eve's own post-close step."""
    bad = []
    for d in (eve, expiry):
        if gap := cfg.holiday_gap(d):
            bad.append(f"the exchange calendar cannot be trusted for {d}: {gap}")
    if not cal.is_trading_day(eve):
        bad.append(f"{eve} is not a trading day")
    elif cal.next_trading_day(eve) != expiry:
        bad.append(f"the expiry {expiry} is not the next trading day after {eve}")
    if (expiry - eve).days != 1:
        bad.append(f"{(expiry - eve).days} calendar days between {eve} and {expiry}: a weekend or a holiday sits between")
    if now.date() != eve:
        bad.append(f"not made in the eve's own post-close step (run on {now.date()}, eve {eve})")
    elif now.time() < ENTRY_AFTER:
        bad.append(f"run at {now:%H:%M}, before the sleeves' entry window closes")
    return bad


def economics(legs: list[dict], lot: int, lots: int, broker, expiry: dt.date) -> dict:
    """Per the spec: credit, wing width, entry fees, the exit allowance and the max loss for `lots`, in rupees."""
    credit = sum(-l["qty"] * l["fill"] for l in legs)
    wings = {r: abs(next(l["strike"] for l in legs if l["right"] == r and l["qty"] > 0)
                    - next(l["strike"] for l in legs if l["right"] == r and l["qty"] < 0)) for r in ("CE", "PE")}
    width = max(wings.values())
    fees = sum(broker.costs.fees(l["inst"], l["qty"] * lots * lot, l["fill"])[0] for l in legs)
    stt = broker.costs.exercise_stt(expiry) * 2 * width * lot * lots
    gross = max(width - credit, 0.0) * lot * lots
    return {"credit_pts": credit, "width_pts": width, "entry_fees": fees, "exit_allowance": stt, "gross_max_loss": gross,
            "max_loss": gross + fees + stt}


def size(legs: list[dict], lot: int, expiry: dt.date, broker, lim: dict, facts: dict) -> tuple[int, dict]:
    """The largest whole number of lots (1..max_lots) satisfying every sizing limit, with the numbers; 0 if none."""
    eq = facts["equity"]
    one = economics(legs, lot, 1, broker, expiry)
    notes = {"per_lot": one, "equity": eq, "caps": {}}
    if not 0 < one["credit_pts"] < one["width_pts"]:
        notes["why"] = f"credit {one['credit_pts']:.2f} pts is not between 0 and the wing width {one['width_pts']:.0f}"
        return 0, notes
    touch = [l["touch_qty"] for l in legs]
    depth = min(float(t) for t in touch) if all(t is not None and math.isfinite(float(t)) for t in touch) else None
    margin_room = min(lim["max_margin"], lim["max_exposure"], 0.5) * eq - facts.get("blocked_margin", 0.0)
    notes["caps"] = {"risk": lim["risk_per_trade"] * eq, "daily_room": facts.get("daily_room", 0.0), "margin_room": margin_room,
                     "touch_units": depth, "max_lots": lim["max_lots"]}
    best, binding = 0, None
    for n in range(lim["max_lots"], 0, -1):
        e = economics(legs, lot, n, broker, expiry)
        margin = max(e["max_loss"], lim["credit_margin"] * n)
        fits = {"risk": e["max_loss"] <= lim["risk_per_trade"] * eq,
                "daily_room": e["max_loss"] <= facts.get("daily_room", 0.0),
                "margin": margin <= margin_room,
                "touch": (n * lot <= depth) if depth is not None else n <= 1}
        if all(fits.values()):
            best = n
            notes.update(lots=n, max_loss=e["max_loss"], margin=margin, economics=e)
            break
        if n == 1:
            binding = [k for k, ok in fits.items() if not ok]
    if not best:
        notes["why"] = "1 lot does not fit: " + ", ".join(binding or ["max_lots"])
        notes["one_lot_max_loss"] = one["max_loss"]
    return best, notes


# ---- the ledger -----------------------------------------------------------------------------------------------------
class Allocator:
    def __init__(self, cfg, sellers: list, journal, broker, root: Path, spec: dict | None = None, say=print):
        self.cfg, self.sellers, self.say = cfg, list(sellers), say
        self.journal, self.broker = _ReadOnlyJournal(journal), _ReadOnlyBroker(broker)    # phase 1 cannot write to the account
        self.costs = broker.costs
        self.spec = spec or load_spec()
        self.ledger = Path(root) / f"{self.spec['name']}.jsonl"
        self.cal = TradingCalendar(cfg.holidays())
        self.lim = limits(cfg, self.spec)
        self.configured = settings(cfg)["mode"]

    # -- ledger
    def events(self) -> list[dict]:
        if not self.ledger.exists():
            return []
        return [json.loads(x) for x in self.ledger.read_text().splitlines() if x.strip()]

    def _append(self, ev: dict) -> dict:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        ev = {"allocator": self.spec["_hash"], "recorded_at": pd.Timestamp.now(tz=IST).isoformat(timespec="seconds"), **ev}
        with self.ledger.open("a") as f:
            f.write(json.dumps(ev, default=str) + "\n")
        return ev

    def shadow_sessions(self) -> int:
        return len({e["day"] for e in self.events()
                    if e.get("event") == "decision" and e.get("status") == "would_place" and e.get("mode") == "shadow"})

    def mode(self) -> tuple[str, str]:
        """(the mode in force, why not the configured one). PHASE 1: apply is not implemented; it is shadow, said so."""
        if self.configured == "apply":
            return "shadow", (f"apply is not implemented in this build (phase 1: shadow only); {self.shadow_sessions()} of "
                              f"{SHADOW_SESSIONS_REQUIRED} shadow sessions on record")
        return self.configured, ""

    # -- a day
    def run(self, day: dt.date, now: pd.Timestamp | None = None) -> list[str]:
        """Settle what is due, mark the shadow positions, then consider this evening's sleeve entries. Safe to re-run."""
        now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=IST)
        now = now.tz_localize(IST) if now.tzinfo is None else now.tz_convert(IST)
        mode, why = self.mode()
        if self.configured == "off":
            return []
        notes = [f"allocator: {why}; running as shadow"] if why else []
        notes += self.settle_shadows(day) + self.mark_shadows(day)
        notes += self.allocate(day, now, mode, why)
        return notes

    def _sleeve_events(self, day: dt.date) -> list[tuple]:
        """This evening's recorded sleeve entries, in the allowed list's order then by underlying."""
        allowed = [(a["spec"], a["sleeve"]) for a in self.spec["sleeves"]["allowed"]]
        out = []
        for sd in self.sellers:
            for e in sd.events():
                if e.get("event") == "open" and e.get("day") == str(day):
                    k = (sd.spec["name"], e["sleeve"])
                    out.append(((allowed.index(k) if k in allowed else len(allowed), e["underlying"]), sd, e))
        return [(sd, e) for _, sd, e in sorted(out, key=lambda x: x[0])]

    def allocate(self, day: dt.date, now: pd.Timestamp, mode: str, mode_why: str) -> list[str]:
        seen = {e["sleeve_trade"] for e in self.events() if e.get("event") == "decision"}
        virtual = [self._virtual(e) for e in self.events() if e.get("event") == "decision" and e.get("status") == "would_place"
                   and dt.date.fromisoformat(e["expiry"]) > day and e.get("mode") == "shadow"]
        journal, broker = self.journal, self.broker
        notes = []
        for sd, ev in self._sleeve_events(day):
            if ev["id"] in seen:
                continue
            rec, legs = self.decide(sd, ev, day, now, journal, broker, virtual)
            rec.update(mode=mode, configured_mode=self.configured, **({"apply_blocked": mode_why} if mode_why else {}))
            led = self._append({"event": "decision", **rec})
            if led["status"] == "would_place":
                virtual.append(self._virtual(led))
            notes.append(self._say(led))
        return notes

    @staticmethod
    def _virtual(e: dict) -> dict:
        return {"max_loss": float(e["sizing"]["max_loss"]), "margin": float(e["sizing"]["margin"])}

    def _say(self, e: dict) -> str:
        s = e["status"]
        if s == "would_place":
            return (f"allocator[{e['mode']}] {s} {e['sleeve_trade']}: {e['lots']} lot(s), max loss ₹{e['sizing']['max_loss']:,.0f}, "
                    f"margin ₹{e['sizing']['margin']:,.0f}")
        return f"allocator[{e['mode']}] {s} {e['sleeve_trade']}: " + "; ".join(e["reasons"])[:300]

    # -- the decision: every rule, no side effects
    def decide(self, sd, ev: dict, day: dt.date, now: pd.Timestamp, journal, broker, virtual: list[dict]):
        base = {"day": str(day), "eve": ev["day"], "sleeve_trade": ev["id"], "spec": sd.spec["name"],
                "sleeve_spec_hash": sd.spec["_hash"], "sleeve": ev["sleeve"], "strategy": ev["strategy"],
                "underlying": ev["underlying"], "expiry": ev["expiry"], "snapshot": ev.get("snapshot"),
                "limits": self.lim, "reasons": [], "lots": 0, "status": "refused"}
        why = base["reasons"]
        allowed = next((a for a in self.spec["sleeves"]["allowed"] if a["spec"] == sd.spec["name"] and a["sleeve"] == ev["sleeve"]), None)
        if allowed is None or sd.sleeves.get(ev["sleeve"], {}).get("naked", True):
            why.append("not an allocatable sleeve: only the allowed defined-risk condors are ever allocated (naked sleeves stay measurements)")
            return base, None
        if ev["underlying"] not in allowed["underlyings"]:
            why.append(f"{ev['underlying']} is not an allocatable underlying for this sleeve")
        cfg_lot = int(self.cfg.instrument_spec(ev["underlying"]).get("lot_size", 0))
        if int(ev["lot"]) != cfg_lot:
            why.append(f"the sleeve's lot {ev['lot']} is not the paper account's configured lot {cfg_lot} for {ev['underlying']}")
        if sd.spec["_hash"] != allowed["spec_sha256_12"] or ev["strategy"] != allowed["strategy"]:
            why.append("the sleeve spec is not the one this allocator was registered against (hash or strategy differs)")
        a = sd.assessment(ev["sleeve"], ev["underlying"])
        base["assessment"] = {k: a[k] for k in ("n", "cost", "consistency", "retired", "bugs", "eligible", "mean", "z")}
        if not a["eligible"]:
            why.append(f"the sleeve is not eligible under its own spec (n {a['n']}, cost {a['cost']}, consistency "
                       f"{a['consistency']}{', retired: ' + a['retired'] if a['retired'] else ''})")
        if str(ev.get("source")) not in REAL_SOURCES:
            why.append(f"quotes are not real exchange quotes ({ev.get('source')})")
        bad = [f for f in (ev.get("quote_flags") or []) if f in BAD_FLAGS] + sorted(
            {f for l in ev.get("legs") or [] for f in l.get("flags") or [] if f in BAD_FLAGS})
        if bad:
            why.append("quote quality: " + ", ".join(sorted(set(bad))))
        legs, problem = price_legs(ev, broker)
        if legs is None:
            why.append(problem)
        else:
            why += structure_problems(legs)
        eve, expiry = dt.date.fromisoformat(ev["day"]), dt.date.fromisoformat(ev["expiry"])
        why += carry_problems(self.cfg, self.cal, eve, expiry, now)
        g, facts = gates(self.cfg, journal, broker, day, self.lim, virtual)
        why += g
        base["facts"] = facts
        if why or legs is None:
            return base, None
        lots, notes = size(legs, int(ev["lot"]), expiry, broker, self.lim, facts)
        base["sizing"] = {"lot": int(ev["lot"]), **{k: v for k, v in notes.items() if k != "economics"}}
        if not lots:
            why.append(notes.get("why", "no lots fit"))
            return base, None
        base.update(status="would_place", lots=lots, sizing={**base["sizing"], **notes["economics"]},
                    legs=[{k: v for k, v in l.items() if k != "inst"} for l in legs])
        return base, legs

    # -- shadow marks and settlement (real quotes; the paper account is not touched)
    def _shadow_open(self) -> list[dict]:
        evs = self.events()
        done = {e["sleeve_trade"] for e in evs if e.get("event") == "settle" and e.get("kind") == "shadow"}
        return [e for e in evs if e.get("event") == "decision" and e.get("status") == "would_place" and e.get("mode") == "shadow"
                and e["sleeve_trade"] not in done]

    def mark_shadows(self, day: dt.date) -> list[str]:
        """Each open shadow position, once per later session: closed at the last recorded snapshot of its expiry that day
        (shorts bought at the ask, longs sold at the bid), after the paper fee model."""
        notes = []
        marked = {(e["sleeve_trade"], e["day"]) for e in self.events() if e.get("event") == "mark"}
        for rec in self._shadow_open():
            eve, exp = dt.date.fromisoformat(rec["eve"]), dt.date.fromisoformat(rec["expiry"])
            if not (eve < day <= exp) or (rec["sleeve_trade"], str(day)) in marked:
                continue
            files = sorted((self._data_dir() / str(day) / "chains").glob(f"{rec['underlying']}_{exp}_*.csv"),
                           key=lambda p: p.stem.rsplit("_", 1)[-1])
            if not files:
                continue
            try:
                ch = load_chain(files[-1])
            except Exception:
                continue
            value, fees, lot = 0.0, 0.0, self._lot(rec)
            try:
                for l in rec["legs"]:
                    side = l["right"].lower()
                    px = float(ch.at[l["strike"], f"{side}_ask" if l["qty"] < 0 else f"{side}_bid"])
                    if not (math.isfinite(px) and px > 0):
                        raise KeyError(l["symbol"])
                    q = l["qty"] * rec["lots"] * lot
                    value += q * (px - l["fill"])
                    fees += self.costs.fees(Instrument.option(rec["underlying"], exp, l["strike"], l["right"], lot), -q, px)[0]
            except KeyError:
                continue
            pnl = value - rec["sizing"]["entry_fees"] - fees
            self._append({"event": "mark", "kind": "shadow", "sleeve_trade": rec["sleeve_trade"], "day": str(day),
                          "snapshot": files[-1].name, "pnl_rs": round(pnl, 2)})
            notes.append(f"allocator[shadow] mark {rec['sleeve_trade']} {day}: ₹{pnl:+,.0f} if closed at the {files[-1].stem[-4:]} quotes")
        return notes

    def settle_shadows(self, day: dt.date) -> list[str]:
        notes = []
        for rec in self._shadow_open():
            s = self._sleeve_settlement(rec["sleeve_trade"])
            if s is None or dt.date.fromisoformat(rec["expiry"]) > day:
                continue
            lot, exp = self._lot(rec), dt.date.fromisoformat(rec["expiry"])
            pts, stt = 0.0, 0.0
            for l in rec["legs"]:
                intr = intrinsic(l["right"], l["strike"], float(s["settle"]))
                q = l["qty"] * rec["lots"] * lot
                pts += q * (intr - l["fill"])
                if q > 0 and intr > 0:
                    stt += self.costs.exercise_stt(exp) * intr * q
            pnl = pts - rec["sizing"]["entry_fees"] - stt
            self._append({"event": "settle", "kind": "shadow", "sleeve_trade": rec["sleeve_trade"], "day": str(day),
                          "settle": s["settle"], "settle_source": s.get("settle_source"), "pnl_rs": round(pnl, 2),
                          "lots": rec["lots"], "max_loss": rec["sizing"]["max_loss"]})
            notes.append(f"allocator[shadow] settled {rec['sleeve_trade']} at {s['settle']:,.2f}: ₹{pnl:+,.0f} for {rec['lots']} lot(s)")
        return notes

    def _data_dir(self) -> Path:
        return Path(self.sellers[0].data)

    @staticmethod
    def _lot(rec: dict) -> int:
        return int(rec["sizing"]["lot"])

    def _sleeve_settlement(self, sleeve_trade: str) -> dict | None:
        for sd in self.sellers:
            for e in sd.events():
                if e.get("event") == "settle" and e.get("id") == sleeve_trade:
                    return e
        return None

    # -- the report
    def report(self) -> dict:
        evs = self.events()
        dec = [e for e in evs if e.get("event") == "decision"]
        counts: dict[str, int] = {}
        for e in dec:
            counts[e["status"]] = counts.get(e["status"], 0) + 1
        mode, why = self.mode()
        return {"spec": self.spec["name"], "spec_hash": self.spec["_hash"], "configured": self.configured, "mode": mode, "why": why,
                "shadow_sessions": self.shadow_sessions(), "needed": SHADOW_SESSIONS_REQUIRED, "counts": counts,
                "recent": dec[-6:], "settled": [e for e in evs if e.get("event") == "settle"][-6:]}


def render(rep: dict) -> str:
    out = [f"## Allocator · {rep['spec']} · spec {rep['spec_hash']}", "",
           f"Mode **{rep['mode']}**" + (f" (configured {rep['configured']}; {rep['why']})" if rep["why"] else "")
           + f" · shadow sessions on record {rep['shadow_sessions']} of {rep['needed']} needed before apply takes effect"
           + (" · decisions: " + ", ".join(f"{k} {v}" for k, v in sorted(rep["counts"].items())) if rep["counts"] else ""), ""]
    for e in rep["recent"]:
        out.append(f"- {e['day']} {e['sleeve_trade']} [{e['mode']}] {e['status']}"
                   + (f": {e['lots']} lot(s), max loss ₹{e['sizing']['max_loss']:,.0f}" if e["status"] == "would_place" else
                      f": {'; '.join(e['reasons'])[:200]}"))
    for e in rep["settled"]:
        out.append(f"- settled {e['sleeve_trade']} ({e['kind']}): ₹{e['pnl_rs']:+,.0f} for {e['lots']} lot(s) at {e['settle']:,.2f}")
    out += ["", "Rules: docs/prereg/allocator_v1.json. Shadow journals what would be placed; the paper account is untouched."]
    return "\n".join(out)
