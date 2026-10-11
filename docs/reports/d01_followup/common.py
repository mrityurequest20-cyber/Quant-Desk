"""Shared loaders for the D-01 follow-up placebo study.

Setup: `git fetch origin journal && mkdir -p j && git archive origin/journal | tar -x -C j` next to these scripts (or
point QD_JOURNAL at the extracted `intraday/` folder), `pip install pyarrow`, then run from this folder:
`python news_study.py`, `python rs_study.py`, `python setup_study.py`. news_study reads news_rows.pkl, which
`python -c "from common import *; news_rows().to_pickle('news_rows.pkl')"` writes."""
import glob
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from quantdesk.intraday import learning as L  # noqa: E402

J = os.environ.get("QD_JOURNAL") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "j", "intraday")
IST = "Asia/Kolkata"


def bars(sym: str) -> pd.DataFrame:
    """1-minute recorded bars where the journal has them, the 5-minute research bars for the other days."""
    b5 = pd.read_parquet(f"{J}/autolearn/bars5/{sym}.parquet")
    b5.index = b5.index.tz_convert(IST)
    ones = []
    for f in sorted(glob.glob(f"{J}/data/*/{sym}_1m.csv")):
        d = pd.read_csv(f, index_col=0)
        d.index = pd.to_datetime(d.index, format="ISO8601").tz_convert(IST)
        if len(d) >= 300:                                    # a whole session only (2026-09-30 has 10 bars)
            ones.append(d[["open", "high", "low", "close", "volume"]])
    one = pd.concat(ones).sort_index() if ones else b5.iloc[:0]
    one = one[~one.index.duplicated()]
    have = set(one.index.date)
    rest = b5[~pd.Index(b5.index.date).isin(have)]
    return pd.concat([rest, one]).sort_index()


def news_rows() -> pd.DataFrame:
    """Row-level replica of learning.grade_news: one row per (headline, reader, index) graded, with its share weight."""
    c = sqlite3.connect(f"{J}/journal.db")
    news = pd.read_sql("SELECT * FROM news ORDER BY ts", c)
    B = {s: bars(s) for s in ("NIFTY", "BANKNIFTY")}
    rows = []
    for r in news.itertuples():
        about = json.loads(r.about) if isinstance(r.about, str) and r.about else {}
        nlp_ = json.loads(r.nlp) if isinstance(r.nlp, str) and r.nlp else {}
        for sym in ("NIFTY", "BANKNIFTY"):
            if (about.get(sym) or 0) < 2.0:
                continue
            got = L.forward(B[sym], r.ts, from_open=True, with_start=True)
            if got is None:
                continue
            fr, t0 = got
            llm_ = ((nlp_.get("llm") or {}).get("readers") or {})
            for reader, tone in [("rules", r.sentiment)] + [(k, (v or {}).get(sym)) for k, v in llm_.items()]:
                if tone is None or not tone == tone or abs(tone) < 0.15:
                    continue
                rows.append(dict(id=r.id, reader=reader, sym=sym, win=t0.floor("30min"), t0=t0, tone=float(tone), fr=fr,
                                 event=nlp_.get("event", "general"), source=r.source))
    df = pd.DataFrame(rows)
    df["w"] = 1.0 / df.groupby(["reader", "sym", "win"])["id"].transform("count")
    df["s"] = np.sign(df["tone"])
    df["day"] = df["t0"].dt.date
    return df
