"""HAR volatility in shadow: record it beside the desk's own estimate at the opening read, then grade both later.

Record (VolShadow, called by the engine). Once per index per session, at the first minute from 09:30 on that the HAR
forecast can be computed (retried until 10:00), one INFO `quant` journal event carries both forecasts of the realised
variance over the next 30m / 60m / 120m / to the close (`data.vol_shadow`). "HAR" is vol_forecast_v1's locked C_har
(harvol.py: coefficients fitted offline with the spec's own training window, no refit here). "Desk" is the desk's
VolForecaster realised estimate at that minute (the per-minute variance it feeds the EV Monte Carlo, before the implied
blend; horizon variance = per-minute variance x minutes). This is the desk's live estimate and NOT the study's candidate
A: the live forecaster works on close-to-close returns and leaves out each day's opening return, the study's A includes
it, so at 09:30 the desk figure is expected to run roughly 20% below A. What this shadow compares is therefore HAR against
what the desk actually uses, not a replication of the locked comparison. The protocol it is judged by (one decision
point, the pooled statistic, N sessions, the failure rule) is fixed in docs/VOL_SHADOW_PROTOCOL.md.

Shadow means no decision reads it: nothing here writes anything the engine uses, every failure is caught and journaled
as a WARN, the inputs are bars the desk already holds, and there is no network call. There is no apply mode.

Grade (compare / render, `intraday vol-shadow`). Reads those events and the recorded 1-minute bars once the horizon has
completed, and scores them the way vol_forecast_v1 did: QLIKE of the realised variance (the sum of squared 1-minute log
returns over the horizon) against each forecast, and the move ratio, the realised mean |move| over the forecast's
expected |move| sqrt(2/pi) x sigma (1.00 is calibrated; above 1 the forecast was too small, below 1 too big). The running
comparison is recomputed from the journal each time, so it only grows as sessions are added. It is a forward test,
reported and not acted on: it scores the realised-volatility forecasts only, not whether either improves option plans.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from ..autolearn import volstudy as V
from ..autolearn.prereg import nw_t

CANDS = ("desk", "har")
MIN_DAYS_FOR_T = 10
INDICES = ("NIFTY", "BANKNIFTY")           # the protocol's session counts only when both have a gradable record
TARGET_SESSIONS = 60                       # docs/VOL_SHADOW_PROTOCOL.md: no read before this many sessions (20 has about 50% power on NIFTY)
HORIZONS = ("30m", "60m", "120m", "close")  # a session counts only with all four graded, for both indices
COEF_PIN = "de59c4ab9496e9ae2bc828741686949bf5608a2c4af548ce064afa25b3bef56a"   # sha256 of vol_har_v1.json, as the protocol pins it
BACKSTOP = dt.date(2027, 3, 31)            # docs/VOL_SHADOW_PROTOCOL.md: fewer than 60 by then is "not confirmed (underpowered)"
STATE_KEY = "vol_shadow:primary_read"      # the one stored read (journal state): later runs show it, they do not recompute
MODES = ("off", "shadow")                  # no apply mode: a forecast that decides nothing is the whole feature
OPEN_READ = 15                             # minutes after 09:15: 09:30, the first decision point the study covered
OPEN_READ_UNTIL = 45                       # ...retried until 10:00, then given up on (once, with a WARN)
MIN_PER_YEAR = 375 * 252                   # as quant.py


class VolShadow:
    """The engine's hook: record HAR beside the desk's estimate at the opening read. Writes only to the journal."""

    def __init__(self, cfg, journal):
        raw = cfg.get("intraday.vol_forecast", {})
        vf = raw if isinstance(raw, dict) else {}
        mode = vf.get("mode", "off")
        mode = "off" if mode is False else str(mode).strip().lower()      # YAML 1.1 reads a bare `off` as False
        self.bad_mode = None if mode in MODES else str(vf.get("mode"))
        if raw is not None and not isinstance(raw, dict):                  # a malformed block: off, with the same WARN
            self.bad_mode = str(raw)
        self.mode = mode if self.bad_mode is None else "off"
        try:
            from .harvol import DEFAULT_PATH
        except Exception as exc:                                  # an import failure must not stop the engine being built
            DEFAULT_PATH = Path(__file__).with_name("vol_har_v1.json")
            self.bad_mode, self.mode = f"harvol could not be imported ({exc!r:.80})", "off"
        self.path = Path(str(vf.get("path") or DEFAULT_PATH))     # the committed coefficients unless the config points elsewhere
        self.journal = journal
        self.har: dict = {}
        self.done: set = set()
        self.tried: set = set()
        self.why: dict = {}
        self.day = None
        self.pin: dict | None = None

    @property
    def on(self) -> bool:
        return self.mode == "shadow"

    def start_session(self, day: dt.date, t0, underlyings) -> None:
        """Load the coefficients for today. Anything missing is a WARN naming why; the desk goes on without the shadow."""
        self.har, self.done, self.tried, self.why, self.day = {}, set(), set(), {}, day
        if self.bad_mode is not None:
            self.journal.event(t0, "WARN", "quant", f"intraday.vol_forecast.mode {self.bad_mode!r} is not off or shadow: "
                                                    "treated as off (there is no apply mode)")
        if not self.on:
            return
        why, bad = "", []
        try:
            from .harvol import HarVol, load_coefs
            coefs, why = load_coefs(self.path)
            for u in underlyings if coefs else ():
                h, w = HarVol.for_session(coefs, u, day)
                if h is None:
                    bad.append(f"{u}: {w}")
                else:
                    self.har[u] = h
        except Exception as exc:                                  # nothing here may stop the desk
            self.har, why = {}, f"HAR could not load ({exc!r:.120})"
        self.pin = pins(self.path) if self.har else None
        if self.har:
            self.journal.event(t0, "INFO", "quant", f"vol shadow: HAR (vol_forecast_v1) will be recorded beside the desk's "
                               f"estimate at the opening read for {', '.join(self.har)}; it changes no decision")
            if bad:
                self.journal.event(t0, "WARN", "quant", f"vol shadow unavailable for {'; '.join(bad)}")
        else:
            self.journal.event(t0, "WARN", "quant", f"vol shadow unavailable ({why or '; '.join(bad)}): nothing is recorded today")

    def step(self, u: str, now, bars: pd.DataFrame, desk_rv_ann, atm_iv=None, used_sigma_30m_pct=None) -> None:
        """Called each minute per index; does work once per session (at the opening read), otherwise returns at once.
        `desk_rv_ann`: the desk forecaster's realised vol in % annualised at this minute (None when it has none)."""
        if not self.on or u in self.done or u not in self.har:
            return
        m = int((now.hour * 60 + now.minute) - (9 * 60 + 15))
        if m < OPEN_READ:
            return
        if m > OPEN_READ_UNTIL:                                  # the opening read is over (a runner that starts later records nothing)
            self.done.add(u)
            if u in self.tried:
                self.journal.event(now, "WARN", "quant", f"{u} vol shadow: no HAR forecast at the opening read "
                                                         f"({self.why.get(u, 'not available')}); nothing is recorded for today")
            else:                                                # the engine reached this index only after the window
                self.journal.event(now, "WARN", "quant", f"{u} vol shadow: the engine first reached the opening read at "
                                                         f"{now:%H:%M}, after 10:00 (a late start); nothing is recorded for today")
            return
        self.tried.add(u)
        try:
            res, why = self.har[u].forecast(bars, now)
        except Exception as exc:
            res, why = None, f"error {exc!r:.120}"
        if res is None:
            self.why[u] = why                                    # tried again next minute, until the window closes
            return
        self.done.add(u)
        r6 = lambda x: float(f"{x:.6g}")                          # noqa: E731
        mins = res["minutes"]
        ok = desk_rv_ann is not None and desk_rv_ann == desk_rv_ann and desk_rv_ann > 0
        a = (float(desk_rv_ann) / 100) ** 2 / MIN_PER_YEAR if ok else None
        desk = {h: r6(a * n) for h, n in mins.items()} if a else {}
        if not desk:
            self.journal.event(now, "WARN", "quant", f"{u} vol shadow: the desk has no realised-vol estimate at the opening read; "
                                                     "HAR is recorded alone and cannot be graded against it")
        h30 = next(h for h in ("30m", "60m", "120m", "close") if h in res["var"])
        self.journal.event(now, "INFO", "quant",
                           f"vol shadow {u} {now:%H:%M}: {h30} sigma HAR {math.sqrt(res['var'][h30]) * 100:.3f}%"
                           + (f" vs desk {math.sqrt(desk[h30]) * 100:.3f}%" if h30 in desk else ""),
                           {"vol_shadow": {"symbol": u, "m": res["m"], "model": "C_har", "atm_iv": atm_iv, "minutes": mins,
                                           "desk": desk, "har": {h: r6(v) for h, v in res["var"].items()},
                                           "used_sigma_30m_pct": used_sigma_30m_pct, "pin": self.pin}})


def pins(coef_path: Path) -> dict:
    """The inputs the protocol pins, as sha256 hex, recorded with every forecast: the coefficient file, and the code whose
    change voids the count: harvol.py, the desk's own forecaster quant.py, and volstudy.py (which builds the grid and the QLIKE).
    The grading code (this file's _pooled, prereg.nw_t) is outside the pin: a change to it is a protocol amendment, not a restart.
    A value is None when it cannot be read."""
    def sha(*paths):
        try:
            h = hashlib.sha256()
            for q in paths:
                h.update(Path(q).read_bytes())
            return h.hexdigest()
        except OSError:
            return None
    here = Path(__file__).parent
    return {"coef": sha(coef_path), "code": sha(here / "harvol.py", here / "quant.py", here.parent / "autolearn" / "volstudy.py")}


def shadow_rows(events: pd.DataFrame) -> pd.DataFrame:
    """The journaled shadow forecasts, one row per (event, symbol)."""
    out = []
    if events is not None and len(events):
        for e in events[events["category"] == "quant"].itertuples():
            try:
                d = json.loads(e.data) if isinstance(e.data, str) else e.data
                d = d.get("vol_shadow") if isinstance(d, dict) else None
            except ValueError:
                continue
            if d and d.get("symbol") and "m" in d and isinstance(d.get("minutes"), dict):
                pin = d.get("pin") if isinstance(d.get("pin"), dict) else {}
                out.append({"ts": pd.Timestamp(e.ts), "symbol": d["symbol"], "m": int(d["m"]), "minutes": d["minutes"],
                            "desk": d.get("desk") or {}, "har": d.get("har") or {},
                            "pin": f"{pin['coef']}:{pin['code']}" if isinstance(pin.get("coef"), str) and isinstance(pin.get("code"), str) else None})
    df = pd.DataFrame(out, columns=["ts", "symbol", "m", "minutes", "desk", "har", "pin"])
    if df.empty:
        return df
    df["day"] = [t.date() for t in df["ts"]]
    # a runner restarted inside the opening read records twice: the first forecast of the session counts, once
    return df.sort_values("ts", kind="stable").drop_duplicates(["symbol", "day"]).drop(columns="day").reset_index(drop=True)


def realised(bars: pd.DataFrame) -> dict:
    """{day: (r, missing)} for one symbol's 1-minute bars, on volstudy's grid."""
    days, r, miss, _ = V.grid(bars[["open", "close"]])
    return {d: (r[i], miss[i]) for i, d in enumerate(days)}


_SKIP_REASONS = (("no HAR forecast at the opening read", "no HAR forecast by 10:00 (too little history or a gap)"),
                 ("after 10:00 (a late start)", "late start (the engine first reached the read after 10:00)"),
                 ("no realised-vol estimate", "the desk had no estimate (HAR recorded, not graded)"),
                 ("could not start", "could not start"), ("unavailable", "coefficients missing or unusable"),
                 ("is not off or shadow", "bad vol_forecast config (treated as off)"), ("failed", "error while recording"))


def skips(events: pd.DataFrame) -> dict:
    """Why index-sessions have no gradable record: the shadow's own WARNs, counted by reason (it is journaled, never silent)."""
    out: dict[str, int] = {}
    if events is None or not len(events) or "message" not in events:
        return out
    msg = events["message"].astype(str)
    w = events[(events["category"] == "quant") & (msg.str.contains("vol shadow", regex=False) | msg.str.contains("vol_forecast", regex=False))]
    if "level" in w:
        w = w[w["level"].isin(["WARN", "ERROR", "CRITICAL"])]
    for msg in w["message"].astype(str):
        why = next((label for key, label in _SKIP_REASONS if key in msg), "other")
        out[why] = out.get(why, 0) + 1
    return out


def _pooled(d: pd.DataFrame) -> dict:
    """The protocol's ONE primary statistic (docs/VOL_SHADOW_PROTOCOL.md). Per session, the mean over both indices and the four
    horizons of QLIKE(desk) - QLIKE(HAR) (positive: HAR better); the session is the unit; one-sided Newey-West t (5 lags) read
    against Student's t with n - 1 degrees of freedom. What counts, enforced here:
    - a session needs all four horizons graded, for both indices;
    - every forecast carries the pins it was made under; only the trailing run of sessions under ONE pin counts, and the coefficient
      pin must equal COEF_PIN (a refit or a change to harvol.py / quant.py restarts the count on that date; a session recorded
      without a pin never counts);
    - the statistic uses the FIRST `TARGET_SESSIONS` of that run, so a session 61 cannot move it.
    `sessions_both` is the number that count; `sessions_excluded` the graded sessions that do not (shown, never hidden)."""
    d = d.assign(diff=V.qlike(d["rv"].to_numpy(float), d["F_desk"].to_numpy(float))
                 - V.qlike(d["rv"].to_numpy(float), d["F_har"].to_numpy(float)),
                 desk_q=V.qlike(d["rv"].to_numpy(float), d["F_desk"].to_numpy(float)))
    if "pin" not in d:
        d["pin"] = None
    whole = d.groupby(["day", "symbol"])["horizon"].agg(lambda s: set(HORIZONS) <= set(s))
    d = d[[bool(whole.get((a, b), False)) for a, b in zip(d["day"], d["symbol"])]]
    have = d.groupby("day")["symbol"].agg(lambda s: set(INDICES) <= set(s))
    both = d[d["day"].isin(have[have].index)]
    per_all = both.groupby("day")["diff"].mean().sort_index()
    pin_of = both.groupby("day")["pin"].agg(lambda s: s.iloc[0] if s.nunique(dropna=False) == 1 else None).reindex(per_all.index)
    # Runs of consecutive sessions under one valid pin. A session with a bad or missing pin ends the run and starts an empty one.
    runs: list[list] = []
    cur: list = []
    prev = None
    for day, pin in pin_of.items():
        if not (isinstance(pin, str) and pin.split(":")[0] == COEF_PIN):
            if cur:
                runs.append(cur)
            cur, prev = [], None
            runs.append([])
            continue
        if cur and pin != prev:
            runs.append(cur)
            cur = []
        cur.append(day)
        prev = pin
    if cur:
        runs.append(cur)
    # The FIRST run that reaches the target is the one that counts: a change after an earned 60 cannot void it (the read may not
    # have been taken yet). Until a run reaches it, the latest run counts, so a change restarts an unfinished count from zero.
    run = next((r for r in runs if len(r) >= TARGET_SESSIONS), runs[-1] if runs else [])
    per = per_all.loc[run] if run else per_all.iloc[:0]
    out = {"sessions_both": int(len(per)), "sessions_excluded": int(len(per_all) - len(per)), "pooled": None}
    if len(per):
        first = per.iloc[:TARGET_SESSIONS]
        n = len(first)
        t = nw_t(first.to_numpy()) if n >= MIN_DAYS_FOR_T else float("nan")
        p = float(student_t.sf(t, df=n - 1)) if t == t else float("nan")
        use = both[both["day"].isin(first.index)]
        desk_q = float(use.groupby("day")["desk_q"].mean().mean())
        out["pooled"] = {"sessions": int(n), "mean_diff": float(first.mean()),
                         "gain_pct": float(100 * first.mean() / desk_q) if desk_q > 0 else None, "nw_t": t, "p_one_sided": p}
    return out


def _stored_row(journal):
    with journal.lock:
        return journal.db.execute("SELECT value FROM state WHERE key=?", (STATE_KEY,)).fetchone()


def _insert_once(journal, rec: dict) -> bool:
    """Write the read only if no row exists under the key, whatever it holds. True when this call wrote it."""
    with journal.lock:
        cur = journal.db.execute("INSERT OR IGNORE INTO state (key, value) VALUES (?, ?)", (STATE_KEY, json.dumps(rec)))
        wrote = cur.rowcount == 1
    journal.commit()
    return wrote


def read_once(journal, rep: dict, today: dt.date) -> dict:
    """The protocol's single read, kept: at the 60th counted session (or, if fewer than 60 by BACKSTOP, after it) the verdict is
    computed once, stored in the journal's state, and every later run shows that record without recomputing. `--since`, a new
    session or a second run cannot change it. The record carries the pin it was made under.

    The seal fails closed: ANY existing row under the key means the read has been taken, whatever it holds (a damaged or emptied
    record is reported as unreadable and is never overwritten). The write is INSERT OR IGNORE, so an earlier verdict can never be
    replaced, and the verdict is also appended to the events table, which is append-only, as a history."""
    row = _stored_row(journal)
    if row is None:
        pl, n = rep.get("pooled"), rep.get("sessions_both", 0)
        if n >= TARGET_SESSIONS and pl:
            ok = pl["mean_diff"] > 0 and pl["p_one_sided"] == pl["p_one_sided"] and pl["p_one_sided"] < 0.05
            rec = {"read_on": str(today), "sessions": pl["sessions"], "mean_diff": pl["mean_diff"], "gain_pct": pl["gain_pct"],
                   "nw_t": pl["nw_t"], "p_one_sided": pl["p_one_sided"], "verdict": "PASS" if ok else "NOT CONFIRMED",
                   "coef_pin": COEF_PIN}
        elif today > BACKSTOP:
            rec = {"read_on": str(today), "sessions": int(n), "verdict": "NOT CONFIRMED (underpowered)", "coef_pin": COEF_PIN}
        else:
            return rep
        if _insert_once(journal, rec):
            journal.event(pd.Timestamp.now(tz="Asia/Kolkata"), "INFO", "quant", f"vol shadow primary read taken: {rec['verdict']}",
                          {"vol_shadow_read": rec})
            journal.commit()
            rep["first_read"] = True
        row = _stored_row(journal)                      # whoever won a race, the stored record is the one that counts
    try:
        got = json.loads(row[0]) if row else None
    except ValueError:
        got = None
    if isinstance(got, dict) and got.get("verdict"):
        rep["stored"] = got
    else:
        rep["stored_unreadable"] = True
    return rep


def compare(events: pd.DataFrame, bars: dict[str, pd.DataFrame]) -> dict:
    """Score every journaled shadow forecast whose horizon has completed in `bars` ({symbol: 1m bars})."""
    rows = shadow_rows(events)
    real = {s: realised(b) for s, b in bars.items() if b is not None and len(b)}
    recs = []
    for e in rows.itertuples():
        day = e.ts.date()
        if e.symbol not in real or day not in real[e.symbol]:
            continue
        r, miss = real[e.symbol][day]
        for h, n in e.minutes.items():
            end = e.m + int(n)
            if end > V.N_MIN or miss[e.m:end].mean() > 0.2 or not (~miss[e.m:end]).any() or miss[end - 1]:
                continue                                           # not finished yet, or the bars are not there
            if not all(h in getattr(e, c) and getattr(e, c)[h] > 0 for c in CANDS):
                continue
            recs.append({"symbol": e.symbol, "day": day, "m": e.m, "horizon": h, "rv": float((r[e.m:end] ** 2).sum()),
                         "ret": float(r[e.m:end].sum()), "F_desk": float(e.desk[h]), "F_har": float(e.har[h]), "pin": e.pin})
    d = pd.DataFrame(recs)
    rep = {"forecasts": int(len(rows)), "scored": int(len(d)), "sessions": int(d["day"].nunique()) if len(d) else 0, "by": {},
           "skips": skips(events)}
    if d.empty:
        return rep
    rep.update(_pooled(d))
    for (sym, hz), g in d.groupby(["symbol", "horizon"]):
        cell = {"n": int(len(g)), "days": int(g["day"].nunique())}
        for c in CANDS:
            f = g[f"F_{c}"].to_numpy(float)
            loss = pd.Series(V.qlike(g["rv"].to_numpy(float), f)).groupby(g["day"].to_numpy()).mean()
            ratio = {}
            for lo, hi, name in V.BUCKETS:
                i = ((g["m"] >= lo) & (g["m"] < hi)).to_numpy()
                ratio[name] = (float(np.mean(np.abs(g["ret"].to_numpy(float)[i])) / np.mean(np.sqrt(2 / np.pi) * np.sqrt(f[i])))
                               if i.any() else None)
            cell[c] = {"qlike": float(loss.mean()), "move_ratio": float(np.mean(np.abs(g["ret"].to_numpy(float)))
                                                                         / np.mean(np.sqrt(2 / np.pi) * np.sqrt(f))),
                       "move_ratio_by_time": ratio}
        diff = (pd.Series(V.qlike(g["rv"].to_numpy(float), g["F_desk"].to_numpy(float))).groupby(g["day"].to_numpy()).mean()
                - pd.Series(V.qlike(g["rv"].to_numpy(float), g["F_har"].to_numpy(float))).groupby(g["day"].to_numpy()).mean())
        cell["qlike_gain_pct"] = float(100 * diff.mean() / cell["desk"]["qlike"]) if cell["desk"]["qlike"] > 0 else None
        cell["dm_t"] = nw_t(diff.to_numpy()) if len(diff) >= MIN_DAYS_FOR_T else None
        rep["by"][f"{sym} {hz}"] = cell
    return rep


def render(rep: dict) -> str:
    L = ["# Live vol shadow: the desk's forecaster (A) vs HAR", "",
         f"{rep['forecasts']} journaled forecasts, {rep['scored']} (forecast, horizon) pairs with a completed horizon; "
         f"{rep.get('sessions', 0)} sessions graded, {rep.get('sessions_both', 0)} of {TARGET_SESSIONS} with both indices "
         f"(docs/VOL_SHADOW_PROTOCOL.md: only those count, with all four horizons and one pin; there is no read before {TARGET_SESSIONS}; "
         "nothing here is acted on).",
         "Shadow WARNs by reason (sessions or index-sessions with no gradable record): "
         + ("; ".join(f"{n} x {why}" for why, n in rep.get("skips", {}).items()) or "none") + ".", ""]
    st, n = rep.get("stored"), rep.get("sessions_both", 0)

    def num(x, spec):
        return format(x, spec) if isinstance(x, (int, float)) and x == x else "n/a"
    if rep.get("stored_unreadable"):
        L += ["**The single read was already taken, but its stored record is unreadable or incomplete.** It is NOT retaken. "
              f"Look at the journal's state row `{STATE_KEY}` and the `vol shadow primary read taken` event for the verdict.", ""]
    elif st:
        gp = num(st.get("gain_pct"), "+.1f") + ("%" if isinstance(st.get("gain_pct"), (int, float)) else "")
        body = (f"{st.get('sessions', '?')} sessions, mean QLIKE gain {num(st.get('mean_diff'), '+.4f')} ({gp}), NW t "
                f"{num(st.get('nw_t'), '+.2f')}, one-sided p {num(st.get('p_one_sided'), '.3f')} (Student t): "
                if "mean_diff" in st else f"{st.get('sessions', '?')} sessions counted: ")
        L += [f"**Primary statistic, READ ONCE on {st.get('read_on', '?')}** (stored in the journal; every later run shows this record "
              f"and does not recompute it): {body}**{st['verdict']}** (PASS needs a positive mean and p < 0.05).", ""]
    elif n >= TARGET_SESSIONS:
        L += [f"Primary statistic: {n} sessions are counted, so the single read is due; it is taken and stored by "
              "`intraday vol-shadow` on the live journal.", ""]
    else:
        L += [f"Primary statistic (the protocol's): withheld until {TARGET_SESSIONS} sessions with both indices are graded "
              f"({n} so far; backstop {BACKSTOP:%d %b %Y}). The per-cell DM t below is withheld too.", ""]
    if st:
        L += ["The per-cell tables below keep updating on every graded session and are descriptive only: they are not the test, "
              "and the verdict above does not change.", ""]
    if rep.get("sessions_excluded"):
        L += [f"{rep['sessions_excluded']} graded session(s) do not count: recorded under a different pin (a refit, or a change to "
              "harvol.py / quant.py / volstudy.py, restarts the count) or without one.", ""]
    ready = bool(st)
    if not rep["by"]:
        return "\n".join(L + ["Nothing to score yet."]) + "\n"
    L += ["| index · horizon | days | QLIKE A | QLIKE HAR | gain | DM t | move ratio A | move ratio HAR |",
          "|---|---|---|---|---|---|---|---|"]
    for k, c in rep["by"].items():
        g, t = c["qlike_gain_pct"], (c["dm_t"] if ready else None)
        L.append(f"| {k} | {c['days']} | {c['desk']['qlike']:.4f} | {c['har']['qlike']:.4f} | "
                 f"{'n/a' if g is None else f'{g:+.1f}%'} | {'n/a' if t is None or t != t else f'{t:+.2f}'} | "
                 f"{c['desk']['move_ratio']:.2f} | {c['har']['move_ratio']:.2f} |")
    L += ["", "Move ratio by time (09:30-10:00 · 10:00-11:30 · 11:30-13:30 · 13:30-15:00), A then HAR:", ""]
    for k, c in rep["by"].items():
        def fmt(x):
            return " · ".join("-" if v is None else f"{v:.2f}" for v in x["move_ratio_by_time"].values())
        L.append(f"- {k}: A {fmt(c['desk'])}  |  HAR {fmt(c['har'])}")
    L += ["", "QLIKE: lower is better; gain is HAR's improvement over A. Move ratio: realised mean |move| over the forecast's "
          "expected |move|; 1.00 is calibrated, above 1 too small, below 1 too big. DM t appears only once the protocol's "
          f"{TARGET_SESSIONS} sessions are in. Realised-volatility forecasts only: the implied blend is in neither number, and A is the desk's live estimate, "
          "not the study's candidate A (see docs/VOL_SHADOW_PROTOCOL.md)."]
    return "\n".join(L) + "\n"
