"""Session recorder: every live session writes its 1m bars and option-chain snapshots to
disk, so the desk builds its own intraday history (Yahoo keeps 1m bars for ~7 days only)
and any past day can be replayed through the engine exactly as it was seen live.

  runtime/intraday/data/2026-09-28/NIFTY_1m.csv
  runtime/intraday/data/2026-09-28/chains/NIFTY_2026-09-29_1030.csv
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from .chains import load_chain, save_chain
from .feeds import IST, normalise_bars


class SessionRecorder:
    def __init__(self, root: Path):
        self.root = Path(root)

    def day_dir(self, day: dt.date) -> Path:
        return self.root / str(day)

    def record_bars(self, symbol: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        for day, part in df.groupby(df.index.date):
            path = self.day_dir(day) / f"{symbol}_1m.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                old = pd.read_csv(path, index_col=0, parse_dates=True)   # raw evidence: NaN/zero rows already on disk stay
                idx = pd.DatetimeIndex(old.index)                        # (the readers normalise); only the index is aligned
                old.index = (idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)).as_unit("ns")
                part = pd.concat([old, part])
            part = part[~part.index.duplicated(keep="last")].sort_index()
            part.to_csv(path, index_label="ts")

    def fill_bars(self, symbol: str, df: pd.DataFrame) -> int:
        """Add only the minutes the day's file lacks (a runner that started mid-day finds the bars it missed in its
        history, which poll() never returns again); every bar already recorded stays as it was. Returns how many."""
        if df is None or df.empty:
            return 0
        added = 0
        for day, part in df.groupby(df.index.date):
            path = self.day_dir(day) / f"{symbol}_1m.csv"
            if path.exists():
                old = normalise_bars(pd.read_csv(path, index_col=0, parse_dates=True))
                part = part[~part.index.isin(old.index)]
                if part.empty:
                    continue
                merged = pd.concat([old, part]).sort_index()
            else:
                merged = part.sort_index()
            path.parent.mkdir(parents=True, exist_ok=True)
            merged.to_csv(path, index_label="ts")
            added += len(part)
        return added

    def record_chain(self, chain: pd.DataFrame) -> None:
        ts = pd.Timestamp(chain.attrs["ts"])
        path = (self.day_dir(ts.date()) / "chains" /
                f"{chain.attrs['underlying']}_{chain.attrs['expiry']}_{ts:%H%M}.csv")
        tmp = path.with_name(f".{path.name}.tmp")        # the chain tape (tape.py) may write the same minute's file
        save_chain(chain, tmp)
        tmp.replace(path)

    def days(self) -> list[dt.date]:
        if not self.root.exists():
            return []
        out = []
        for p in self.root.iterdir():
            try:
                out.append(dt.date.fromisoformat(p.name))
            except ValueError:
                continue
        return sorted(out)

    def load_bars(self, symbols: list[str], upto: dt.date | None = None) -> dict[str, pd.DataFrame]:
        out: dict[str, list] = {s: [] for s in symbols}
        for d in self.days():
            if upto and d > upto:
                continue
            for s in symbols:
                p = self.day_dir(d) / f"{s}_1m.csv"
                if p.exists():
                    out[s].append(normalise_bars(pd.read_csv(p, index_col=0, parse_dates=True)))
        return {s: pd.concat(v).sort_index() for s, v in out.items() if v}

    def load_chains(self, day: dt.date) -> dict[str, list[pd.DataFrame]]:
        out: dict[str, list] = {}
        d = self.day_dir(day) / "chains"
        if d.exists():
            for p in sorted(d.glob("*.csv")):
                ch = load_chain(p)
                out.setdefault(ch.attrs["underlying"], []).append(ch)
        return out
