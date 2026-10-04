"""Read-mostly API over the intraday desk's journal(s), for the web/mobile app.

The intraday engine runs as its own process (`quantdesk intraday live`) and writes to its
journal every minute; this side only reads, except for remote-control commands, which it
appends to a queue the engine executes on its next step (pause / resume / close / flatten)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from ..intraday.feeds import normalise_bars
from ..journal.journal import Journal

COMMANDS = {"pause", "resume", "flatten", "close"}


class IntradayAPI:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg.runtime_dir / "intraday"
        self._j: dict[str, Journal] = {}

    # ---- accounts / plumbing -------------------------------------------------------------------------
    def _dir(self, account: str) -> Path:
        if account in (None, "", "live"):
            return self.base
        if not account.replace("_", "").replace("-", "").isalnum():
            raise KeyError("bad account name")
        return self.base / account

    def accounts(self) -> list[dict]:
        out = []
        if (self.base / "journal.db").exists():
            out.append({"id": "live", "label": "Live paper"})
        if self.base.exists():
            for p in sorted(self.base.iterdir()):
                if p.is_dir() and (p / "journal.db").exists():
                    out.append({"id": p.name, "label": p.name.capitalize()})
        return out

    def j(self, account: str | None) -> Journal:
        a = account or "live"
        path = self._dir(a) / "journal.db"
        if not path.exists():
            raise KeyError(f"no intraday account {a!r} yet")
        if a not in self._j:
            self._j[a] = Journal(path)
        return self._j[a]

    def _data_dir(self, account: str | None) -> Path:
        d = self._dir(account) / "data"
        return d if d.exists() else self.base / "data"

    def _cash(self, account) -> float | None:
        p = self._dir(account) / "broker.json"
        return json.loads(p.read_text())["cash"] if p.exists() else None

    def pending_capital(self, account) -> float | None:
        """The configured capital, when the account is about to take it.

        The engine's own rule (intraday/account.ensure_account): an account with no trades takes the configured capital
        at its next session. Until that session, the stored figure is stale (on 4 Oct 2026 the app showed ₹20,000 two
        days after the account was set to ₹5,00,000), so the app shows what the account is about to be."""
        j = self.j(account)
        acct = j.get_state("intraday_account") or {}
        cfg_cap = float(self.cfg.get("intraday.capital", 20000))
        n = int(j.df("SELECT COUNT(*) AS n FROM trades")["n"].iloc[0])
        return cfg_cap if n == 0 and float(acct.get("capital") or 0) != cfg_cap else None

    def capital(self, account) -> float:
        """The account's own starting capital (not whatever the config says today), unless it has yet to trade."""
        pending = self.pending_capital(account)
        if pending is not None:
            return pending
        acct = self.j(account).get_state("intraday_account") or {}
        return float(acct.get("capital") or self.cfg.get("intraday.capital", 20000))

    def limits(self) -> dict:
        """The risk limits the desk trades under (the app shows how much of each is used today)."""
        r = self.cfg.get("intraday.risk", {}) or {}
        sl = self.cfg.get("intraday.short_legs_from_equity", 300000)       # buyer only below this equity (engine)
        return {**{k: r.get(k) for k in ("risk_per_trade", "max_trades_per_day", "max_open", "daily_loss_limit")},
                "short_legs_from_equity": None if sl is None else float(sl)}

    # ---- screens -----------------------------------------------------------------------------------------
    def state(self, account=None) -> dict:
        j = self.j(account)
        hb = j.get_state("intraday_live") or {}
        cash = self._cash(account)
        cap = self.capital(account)
        pending = self.pending_capital(account) is not None
        if pending:                                         # nothing traded yet: the account starts at the new capital
            cash, hb = cap, {**hb, "equity": cap}
        day = hb.get("day")
        closed = j.df("SELECT id, strategy, symbol, pnl, r_multiple, grade, exit_reason, opened_at, closed_at "
                      "FROM trades WHERE status='closed' AND opened_at >= ? ORDER BY closed_at DESC", (day or "9999",))
        tot = j.df("SELECT COALESCE(SUM(pnl),0) AS pnl, COUNT(*) AS n FROM trades WHERE status='closed'").iloc[0]
        age = None
        if hb.get("ts"):
            age = (pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timestamp(hb["ts"])).total_seconds()
        return {"heartbeat": hb, "age_sec": age, "cash": cash, "capital": cap,
                "equity": hb.get("equity", cash if cash is not None else cap), "total_pnl": float(tot["pnl"]), "total_trades": int(tot["n"]),
                "paused": bool(j.get_state("intraday_paused", False)), "closed_today": closed.to_dict("records"),
                "limits": self.limits(), "capital_pending": pending,
                "pending_commands": len([c for c in (j.get_state("intraday_cmds") or [])
                                         if c["id"] not in set(j.get_state("intraday_cmds_done") or [])])}

    def thoughts(self, account=None, symbol=None, n=40, before=None) -> list[dict]:
        j = self.j(account)
        q, p = "SELECT * FROM thoughts WHERE 1=1", []
        if symbol:
            q += " AND symbol = ?"
            p.append(symbol)
        if before:
            q += " AND id < ?"
            p.append(int(before))
        rows = j.df(q + " ORDER BY id DESC LIMIT ?", (*p, int(n)))
        out = []
        for r in rows.to_dict("records"):
            for k in ("evidence", "vetoes", "levels", "chain"):
                r[k] = json.loads(r[k]) if r.get(k) else None
            out.append(r)
        return out

    def news(self, account=None, n=120) -> list[dict]:
        rows = self.j(account).news(n=int(n))
        out = []
        for r in rows.to_dict("records"):
            for k in ("sources", "about", "nlp"):
                r[k] = json.loads(r[k]) if r.get(k) else None
            out.append(r)
        return out

    def trades(self, account=None, n=100) -> list[dict]:
        t = self.j(account).df("SELECT id, strategy, symbol, direction, units, opened_at, closed_at, pnl, fees, r_multiple, "
                               "grade, exit_reason, status, meta FROM trades ORDER BY opened_at DESC LIMIT ?", (int(n),))
        recs = t.to_dict("records")
        for r in recs:
            m = json.loads(r.pop("meta") or "{}")
            r["structure"], r["expiry"] = m.get("structure"), m.get("expiry")
        return recs

    def trade(self, account=None, tid=None) -> dict:
        t = self.j(account).df("SELECT * FROM trades WHERE id=?", (tid,))
        if t.empty:
            raise KeyError(f"no trade {tid}")
        r = t.iloc[0].to_dict()
        for k in ("legs", "context", "meta", "sizing", "lessons"):
            r[k] = json.loads(r[k]) if r.get(k) else None
        r["fills"] = self.j(account).df("SELECT ts, symbol, qty, price, fees FROM fills WHERE trade_id=? ORDER BY id",
                                        (tid,)).to_dict("records")
        return r

    def reviews(self, account=None) -> list[str]:
        d = self._dir(account) / "reviews"
        return sorted((p.stem for p in d.glob("*.md")), reverse=True) if d.exists() else []

    def review(self, account=None, date=None) -> dict:
        p = self._dir(account) / "reviews" / f"{date}.md"
        if not p.exists() or not date or "/" in date:
            raise KeyError("no such review")
        return {"date": date, "markdown": p.read_text(encoding="utf-8")}

    def stats(self, account=None) -> dict:
        t = self.j(account).trades("closed")
        cap = self.capital(account)
        if t.empty:
            return {"trades": 0, "capital": cap}
        t["day"] = t["opened_at"].str[:10]
        t["structure"] = t["meta"].map(lambda m: json.loads(m).get("structure"))
        t["day_type"] = t["context"].map(lambda c: json.loads(c).get("regime"))
        t["hour"] = t["opened_at"].str[11:13] + ":00"
        daily = t.groupby("day")["pnl"].sum()
        eq = cap + daily.cumsum()
        wins, losses = t[t["pnl"] > 0]["pnl"], t[t["pnl"] <= 0]["pnl"]

        def by(col):
            g = t.groupby(col)
            return [{"key": str(k), "trades": int(len(x)), "win": float((x["pnl"] > 0).mean()), "avg_r": float(x["r_multiple"].mean()),
                     "pnl": float(x["pnl"].sum())} for k, x in g]

        return {"capital": cap, "trades": int(len(t)), "sessions": int(len(daily)), "net": float(t["pnl"].sum()),
                "win_rate": float((t["pnl"] > 0).mean()), "avg_r": float(t["r_multiple"].mean()),
                "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else None,
                "fees": float(t["fees"].sum()), "green_days": float((daily > 0).mean()), "worst_day": float(daily.min()),
                "best_day": float(daily.max()), "max_dd": float((eq / eq.cummax() - 1).min()),
                "equity": [{"day": d, "equity": float(v)} for d, v in eq.items()],
                "by_setup": by("strategy"), "by_structure": by("structure"), "by_day_type": by("day_type"),
                "by_exit": by("exit_reason"), "by_hour": by("hour"), "by_symbol": by("symbol"),
                "grades": {str(k): int(v) for k, v in t["grade"].value_counts().sort_index().items()},
                "calibration": self._calibration(t)}

    @staticmethod
    def _profile(day: pd.DataFrame) -> dict | None:
        """The session's profile for the chart: price bins with their volume (or, for an index, time) at price, and
        the POC and value area the desk itself reads."""
        from ..intraday.orderflow import profile_from_bars
        prof = profile_from_bars(day, bins=48) if len(day) >= 5 else None
        if prof is None:
            return None
        top = float(prof.volume.max()) or 1.0
        return {"kind": prof.kind, "poc": round(prof.poc, 2), "vah": round(prof.vah, 2), "val": round(prof.val, 2),
                "step": round(float(prof.prices[1] - prof.prices[0]), 4) if len(prof.prices) > 1 else 1.0,
                "prices": [round(float(x), 2) for x in prof.prices], "size": [round(float(v) / top, 3) for v in prof.volume]}

    @staticmethod
    def _calibration(t: pd.DataFrame) -> list[dict]:
        """Was the probability the desk traded on any good? For trades priced by the quant layer: the P(right
        direction) it assumed vs how often the underlying actually moved its way by the exit."""
        rows = []
        for r in t.itertuples():
            q = (json.loads(r.meta or "{}").get("quant") or {})
            if "p_up" not in q or not r.direction or pd.isna(r.exit_underlying) or pd.isna(r.entry_underlying):
                continue
            p_right = q["p_up"] if r.direction > 0 else 1 - q["p_up"]
            right = (r.exit_underlying - r.entry_underlying) * r.direction > 0
            rows.append((p_right, right, str(q.get("p_source", "?")).split(" (")[0], r.pnl))
        if not rows:
            return []
        df = pd.DataFrame(rows, columns=["p", "right", "source", "pnl"])
        df["bucket"] = pd.cut(df["p"], [0, 0.5, 0.53, 0.56, 0.6, 1.0], labels=["≤50%", "50–53%", "53–56%", "56–60%", ">60%"])
        out = []
        for (src, b), g in df.groupby(["source", "bucket"], observed=True):
            out.append({"source": src, "bucket": str(b), "trades": int(len(g)), "assumed": float(g["p"].mean()),
                        "realised": float(g["right"].mean()), "pnl": float(g["pnl"].sum())})
        return out

    # ---- chart data --------------------------------------------------------------------------------------
    def _bars(self, account, symbol: str, days: int = 1, date: str | None = None) -> pd.DataFrame:
        d = self._data_dir(account)
        if not d.exists():
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        dates = sorted(p.name for p in d.iterdir() if (p / f"{symbol}_1m.csv").exists())
        if date:
            dates = [x for x in dates if x <= date]
        frames = [normalise_bars(pd.read_csv(d / x / f"{symbol}_1m.csv", index_col=0, parse_dates=True)) for x in dates[-days:]]
        return pd.concat(frames) if frames else pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    SESSIONS = {"1m": 2, "3m": 3, "5m": 3, "15m": 5}       # sessions on the chart: today plus context

    def chart(self, account=None, symbol="NIFTY", date=None, interval="1m") -> dict:
        """Candles for the last few sessions (the latest one is never shown alone: a late start or a holiday-eve
        stub of a few bars is unreadable), VWAP that restarts each session, the session profile, and the levels:
        computed from the bars themselves (prior day, opening range, CPR, value area, day range), plus what only the
        desk's last read knows (OI walls)."""
        symbol = symbol.upper()
        df = self._bars(account, symbol, self.SESSIONS.get(interval, 2), date)
        if df.empty:
            return {"symbol": symbol, "bars": None}
        dates = sorted(set(df.index.date))
        last = dates[-1]
        day = str(last)
        today = df[df.index.date == last]
        prior = df[df.index.date == dates[-2]] if len(dates) > 1 else df.iloc[:0]
        prof_src = today if len(today) >= 30 or prior.empty else prior      # a stub day: profile the full one before it
        profile = self._profile(prof_src)
        if profile is not None:
            profile["day"] = str(prof_src.index[-1].date())
        levels = self._bar_levels(today, prior, profile)
        if interval in ("3m", "5m", "15m"):
            df = df.resample(interval.replace("m", "min"), label="left", closed="left", origin="start_day",
                             offset="15min").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                                  "volume": "sum"}).dropna(subset=["close"])
        vwap = np.empty(len(df))
        d_of = np.array(df.index.date)
        for d in dates:                                     # VWAP restarts every session (TWAP when there's no volume)
            m = d_of == d
            if not m.any():
                continue
            part = df[m]
            vol = part["volume"].to_numpy(dtype=float)
            vol = vol if vol.sum() > 0 else np.ones(len(part))
            tp = ((part["high"] + part["low"] + part["close"]) / 3).to_numpy()
            vwap[m] = np.cumsum(tp * vol) / np.cumsum(vol)
        j = self.j(account)
        first = str(dates[0])
        tr = j.df("SELECT id, strategy, direction, opened_at, closed_at, entry_underlying, exit_underlying, pnl, "
                  "exit_reason, stop, target, meta FROM trades WHERE symbol=? AND opened_at >= ? AND opened_at < ?",
                  (symbol.replace("-FUT", ""), first, day + " 99"))
        markers = []
        for r in tr.itertuples():
            m = json.loads(r.meta or "{}")
            markers.append({"t": int(pd.Timestamp(r.opened_at).timestamp()), "kind": "entry", "price": r.entry_underlying,
                            "dir": r.direction, "text": f"{r.strategy} · {m.get('structure')}"})
            if r.closed_at:
                markers.append({"t": int(pd.Timestamp(r.closed_at).timestamp()), "kind": "exit", "price": r.exit_underlying,
                                "dir": r.direction, "text": f"{r.exit_reason} ₹{r.pnl:,.0f}"})
        th = j.df("SELECT levels FROM thoughts WHERE symbol=? AND ts >= ? AND ts < ? ORDER BY id DESC LIMIT 1",
                  (symbol.replace("-FUT", ""), day, day + " 99"))
        if not th.empty and th.iloc[0]["levels"]:            # the read adds what bars can't say (OI walls); the bars stay
            for k, v in json.loads(th.iloc[0]["levels"]).items():   # current for the rest (a read can be minutes old)
                if v is not None:
                    levels.setdefault(k, v)
        return {"symbol": symbol, "day": day, "interval": interval, "profile": profile,
                "sessions": [str(d) for d in dates], "today_bars": int(len(today)),
                "session_starts": [int(df[d_of == d].index[0].timestamp()) for d in dates if (d_of == d).any()],
                "bars": {"t": [int(x.timestamp()) for x in df.index], "o": df["open"].round(2).tolist(),
                         "h": df["high"].round(2).tolist(), "l": df["low"].round(2).tolist(), "c": df["close"].round(2).tolist(),
                         "v": df["volume"].round(0).tolist()},
                "vwap": [round(float(x), 2) for x in vwap], "markers": markers,
                "levels": {k: round(float(v), 2) for k, v in levels.items() if v is not None and v == v}}

    @staticmethod
    def _bar_levels(today: pd.DataFrame, prior: pd.DataFrame, profile: dict | None) -> dict:
        """The levels a trader marks before the open and during the first hour, from the bars alone."""
        out: dict = {}
        if len(prior):
            H, L, C = float(prior["high"].max()), float(prior["low"].min()), float(prior["close"].iloc[-1])
            out.update({"pdh": H, "pdl": L})
            pivot, bc = (H + L + C) / 3, (H + L) / 2
            tc = 2 * pivot - bc
            out.update({"cpr_tc": max(tc, bc), "cpr_bc": min(tc, bc)})
        if len(today):
            t0 = today.index[0].normalize() + pd.Timedelta(hours=9, minutes=15)
            orng = today[(today.index >= t0) & (today.index < t0 + pd.Timedelta(minutes=15))]
            if len(orng) >= 10:                              # only a real opening range, not the first bars of a late start
                out.update({"or_high": float(orng["high"].max()), "or_low": float(orng["low"].min())})
            ib = today[(today.index >= t0) & (today.index < t0 + pd.Timedelta(minutes=60))]
            if len(ib) >= 45:
                out.update({"ib_high": float(ib["high"].max()), "ib_low": float(ib["low"].min())})
            out.update({"day_high": float(today["high"].max()), "day_low": float(today["low"].min())})
        if profile:
            out.update({"poc": profile["poc"], "vah": profile["vah"], "val": profile["val"]})
        return out

    def udf(self, account=None, symbol="NIFTY", interval="1m", frm=None, to=None, countback=None) -> dict:
        """UDF bars for the GoCharting datafeed (intraday resolutions)."""
        df = self._bars(account, symbol.split(":")[-1].upper(), 30)
        if interval in ("3m", "5m", "15m", "30m", "1h"):
            rule = interval.replace("m", "min") if interval.endswith("m") else "60min"
            df = df.resample(rule, label="left", closed="left", origin="start_day", offset="15min").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
        t = np.array([int(x.timestamp()) for x in df.index], dtype=np.int64)
        m = np.ones(len(t), dtype=bool)
        if to is not None:
            m &= t <= int(float(to))
        if frm is not None:
            idx = np.where(m & (t >= int(float(frm))))[0]
            if countback and len(idx) < int(countback):
                idx = np.where(m)[0][-int(countback):]
        else:
            idx = np.where(m)[0][-int(countback):] if countback else np.where(m)[0]
        if not len(idx):
            return {"s": "no_data", "nextTime": None}
        d = df.iloc[idx]
        return {"s": "ok", "t": t[idx].tolist(), "o": d["open"].tolist(), "h": d["high"].tolist(), "l": d["low"].tolist(),
                "c": d["close"].tolist(), "v": d["volume"].tolist()}

    # ---- remote control ---------------------------------------------------------------------------------
    def command(self, account, body: dict) -> dict:
        cmd = str(body.get("cmd", ""))
        if cmd not in COMMANDS:
            raise ValueError(f"unknown command {cmd!r}; use one of {sorted(COMMANDS)}")
        arg = body.get("arg")
        if cmd == "close" and not arg:
            raise ValueError("close needs the trade id")
        j = self.j(account)
        cmds = j.get_state("intraday_cmds") or []
        c = {"id": uuid.uuid4().hex[:10], "cmd": cmd, "arg": arg, "ts": str(pd.Timestamp.now(tz="Asia/Kolkata"))}
        cmds.append(c)
        j.set_state("intraday_cmds", cmds[-200:])
        if cmd in ("pause", "resume"):                 # reflect immediately even before the engine's next minute
            j.set_state("intraday_paused", cmd == "pause")
        return {"queued": c, "note": "the engine applies it on its next minute"}
