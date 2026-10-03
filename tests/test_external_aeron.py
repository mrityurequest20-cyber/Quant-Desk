"""The external index-minute importer (quantdesk/data/external_aeron.py): parsing, IST bar-start timestamps, validation,
one file per session, immutable partitions, provenance, the independent check, 5m / horizon datasets, and the use
restrictions (never option, bid/ask, IV or execution data; never evidence for qualification)."""
import json

import numpy as np
import pandas as pd
import pytest

from quantdesk.data import external_aeron as X


def minutes(day, start=25000.0, seed=0, label_end=True, n=375, extra=True):
    rng = np.random.default_rng(seed)
    c = start * np.exp(np.cumsum(rng.normal(0, 3e-4, n)))
    o = np.r_[start, c[:-1]]
    base = pd.Timestamp(f"{day} 09:15") + (pd.Timedelta(minutes=1) if label_end else pd.Timedelta(0))
    rows = []
    if extra:
        rows.append((pd.Timestamp(f"{day} 09:08"), start, start, start, start))
    for i in range(n):
        rows.append((base + pd.Timedelta(minutes=i), o[i], max(o[i], c[i]) + 1, min(o[i], c[i]) - 1, c[i]))
    if extra:
        rows.append((pd.Timestamp(f"{day} 15:31"), c[-1], c[-1], c[-1], c[-1]))
    return rows


def write(path, sym, rows, fields=9):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for t, o, h, l, c in rows:
            base = f"{sym},{t:%Y%m%d},{t:%H:%M},{o:.2f},{h:.2f},{l:.2f},{c:.2f}"
            f.write(base + (",0,0" if fields == 9 else ",0" if fields == 8 else "") + "\n")


@pytest.fixture
def source(tmp_path):
    src = tmp_path / "src"
    days = ["2021-02-01", "2021-02-02", "2021-02-03", "2021-02-04"]
    for i, d in enumerate(days):
        dd = pd.Timestamp(d)
        write(src / "2021" / "FEB" / f"{dd:%d%b}".upper() / f"{dd:%d%b}".upper() / "NIFTY.txt", "NIFTY", minutes(d, seed=i))
        write(src / "2021" / "FEB" / f"{dd:%d%b}".upper() / f"{dd:%d%b}".upper() / "BANKNIFTY.txt", "BANKNIFTY",
              minutes(d, start=35000, seed=10 + i))
    # an old-style monthly 7-field file repeating 1 Feb (the same minutes) and a short day
    write(src / "2021" / "FEB" / "NIFTY.txt", "NIFTY", minutes("2021-02-01", seed=0, extra=False) + minutes("2021-02-05", n=200, seed=5), fields=7)
    # a messy day: duplicates (identical + conflicting), a bad price, negative volume, a wrong symbol, junk, a jump
    rows = minutes("2021-02-08", seed=8)
    messy = src / "2021" / "FEB" / "08FEB" / "08FEB" / "NIFTY.txt"
    write(messy, "NIFTY", rows)
    with open(messy, "a") as f:
        t = rows[10][0]
        f.write(f"NIFTY,{t:%Y%m%d},{t:%H:%M},{rows[10][1]:.2f},{rows[10][2]:.2f},{rows[10][3]:.2f},{rows[10][4]:.2f},0,0\n")
        t = rows[20][0]
        f.write(f"NIFTY,{t:%Y%m%d},{t:%H:%M},1.00,2.00,0.50,1.50,0,0\n")
        f.write("NIFTY,20210208,10:30,100,90,95,96,0,0\n")             # high < low
        f.write("NIFTY,20210208,10:31,25000,25001,24999,25000,-5,0\n")  # negative volume
        f.write("ACC,20210208,10:32,1600,1601,1599,1600,10,0\n")        # another symbol
        f.write("garbage line\n")
    jump = minutes("2021-02-09", seed=9)
    jump[200] = (jump[200][0], jump[200][1] * 1.08, jump[200][2] * 1.08, jump[200][3] * 1.08, jump[200][4] * 1.08)
    write(src / "2021" / "FEB" / "09FEB" / "09FEB" / "NIFTY.txt", "NIFTY", jump)
    write(src / "2021" / "FEB" / "06FEB" / "06FEB" / "NIFTY.txt", "NIFTY", minutes("2021-02-06", seed=6))   # a Saturday
    write(src / "2021" / "FEB" / "NIFTY_F1.txt", "NIFTY_F1", minutes("2021-02-01", seed=1))               # futures: ignored
    return src


def test_files_parse_to_ist_bar_starts_and_sessions_validate(source, tmp_path):
    assert all(s in ("NIFTY", "BANKNIFTY") for _, s in X.discover(source))
    df, rep = X.read_file(source / "2021/FEB/01FEB/01FEB/NIFTY.txt", "NIFTY")
    assert rep["label"] == "end" and str(df["ts"].dt.tz) == X.IST
    clean, v = X.session_check(df[df["ts"].dt.date == pd.Timestamp("2021-02-01").date()])
    assert clean["ts"].iloc[0].strftime("%H:%M") == "09:15" and clean["ts"].iloc[-1].strftime("%H:%M") == "15:29"
    assert v["minutes"] == 375 and v["out_of_session"] == 2 and v["accepted"]
    old, rep7 = X.read_file(source / "2021/FEB/NIFTY.txt", "NIFTY")
    assert rep7["volume_absent"] == rep7["rows_in"] and rep7["invalid_volume"] == 0      # 7-field files: no volume column
    m, repm = X.read_file(source / "2021/FEB/08FEB/08FEB/NIFTY.txt", "NIFTY")
    assert repm["bad_price"] == 1 and repm["invalid_volume"] == 1 and repm["wrong_symbol"] == 1 and repm["unparsed"] == 1
    assert repm["out_of_order"] >= 1
    _, vm = X.session_check(m)
    assert vm["duplicates"] >= 1 and vm["conflicting_duplicates"] == 1 and vm["missing_minutes"] == 1


def test_import_writes_immutable_partitions_with_provenance(source, tmp_path):
    out = tmp_path / "out"
    man = X.import_dataset(source, out, say=None)
    ds = X.dataset_dir(out, man["source_commit"])
    assert man["status"] == X.UNVERIFIED and man["source_url"] == X.SOURCE_URL and man["importer_version"] == X.IMPORTER_VERSION
    f = {e["path"]: e for e in man["files"]}
    assert all(len(e["sha256"]) == 64 for e in f.values()) and not any("_F1" in p for p in f)
    s = {(r["symbol"], r["day"]): r for r in man["sessions"]}
    assert s[("NIFTY", "2021-02-01")]["files"] == 2 and s[("NIFTY", "2021-02-01")]["accepted"]       # one file chosen
    assert not s[("NIFTY", "2021-02-05")]["accepted"] and "short session" in s[("NIFTY", "2021-02-05")]["reasons"][0]
    assert not s[("NIFTY", "2021-02-09")]["accepted"] and "one-minute move" in s[("NIFTY", "2021-02-09")]["reasons"][0]
    assert not s[("NIFTY", "2021-02-06")]["accepted"] and "weekend" in s[("NIFTY", "2021-02-06")]["reasons"]
    m1 = X.load(ds, "1m", ["NIFTY"], use="underlying_features", allow_unverified=True)
    assert set(m1["ts"].dt.date.astype(str)) == {"2021-02-01", "2021-02-02", "2021-02-03", "2021-02-04", "2021-02-08"}
    assert m1["ts"].is_monotonic_increasing and not m1.duplicated("ts").any() and m1.attrs["status"] == X.UNVERIFIED
    q = json.loads((ds / "quality.json").read_text())
    assert q["by_year"]["NIFTY"]["2021"]["rejected"] == 3 and "missing_minute_rate" in q["by_year"]["NIFTY"]["2021"]
    assert "Rejected sessions" in (ds / "quality.md").read_text()
    # the same source again: identical partitions; a tampered partition is refused
    assert X.import_dataset(source, out, say=None)["partitions"] == man["partitions"]
    p = next((ds / "1m" / "symbol=NIFTY").glob("*.parquet"))
    pd.read_parquet(p).iloc[:-1].to_parquet(p)
    with pytest.raises(X.ImmutableViolation):
        X.import_dataset(source, out, say=None)


def test_5m_bars_and_horizon_labels(source, tmp_path):
    out = tmp_path / "out"
    man = X.import_dataset(source, out, say=None, symbols=("NIFTY",))
    ds = X.dataset_dir(out, man["source_commit"])
    b5 = X.load(ds, "5m", ["NIFTY"], use="direction_research", allow_unverified=True)
    day = b5[b5.index.date == pd.Timestamp("2021-02-02").date()]
    assert len(day) == 75 and (day["n_1m"] == 5).all() and day.index[0].strftime("%H:%M") == "09:15"
    hz = X.load(ds, "horizons", ["NIFTY"], use="direction_research", allow_unverified=True)
    d = hz[hz["day"] == "2021-02-02"].reset_index(drop=True)
    close = day["close"].to_numpy()
    r = d.iloc[10]
    i = int((pd.Timestamp(r["ts"]) - day.index[0]) / pd.Timedelta(minutes=5)) - 1   # the decision bar (ts = its end)
    assert r["fwd_ret_30m"] == pytest.approx(np.log(close[i + 6] / close[i]))
    assert r["fwd_ret_120m"] == pytest.approx(np.log(close[i + 24] / close[i]))
    assert r["fwd_ret_close"] == pytest.approx(np.log(close[-1] / close[i]))
    assert (pd.to_datetime(d["label_end_60m"].dropna()) > pd.to_datetime(d.loc[d["label_end_60m"].notna(), "ts"])).all()
    assert d["fwd_ret_120m"].isna().sum() > d["fwd_ret_30m"].isna().sum()    # no label reaches past the session


def test_uses_are_restricted_and_status_needs_the_independent_check(source, tmp_path):
    out = tmp_path / "out"
    man = X.import_dataset(source, out, say=None)
    ds = X.dataset_dir(out, man["source_commit"])
    for bad in ("option_chain", "bid_ask", "iv", "option_execution", "qualification", "promotion", "paper_gate"):
        with pytest.raises(X.ForbiddenUse):
            X.load(ds, "1m", ["NIFTY"], use=bad, allow_unverified=True)
    with pytest.raises(X.ForbiddenUse, match="external_unverified"):
        X.load(ds, "1m", ["NIFTY"], use="direction_research")                 # unverified needs an explicit opt-in
    m1 = X.load(ds, "1m", ["NIFTY", "BANKNIFTY"], use="regime_research", allow_unverified=True)
    truth = {s: X.daily_from_minutes(g) for s, g in m1.groupby("symbol")}

    def honest(sym, start, end):
        return truth[sym][["high", "low", "close"]]

    def off(sym, start, end):
        return truth[sym][["high", "low", "close"]] * 1.01                     # 1% away: outside every tolerance
    r = X.verify(ds, reference=off, n=10, say=None, min_sampled=3)
    assert r["status"] == X.UNVERIFIED and json.loads((ds / "manifest.json").read_text())["status"] == X.UNVERIFIED
    r = X.verify(ds, reference=honest, n=10, say=None, min_sampled=3)
    assert r["status"] == X.VERIFIED and all(v["pass_rate"] == 1.0 for v in r["symbols"].values())
    assert X.load(ds, "1m", ["NIFTY"], use="direction_research").attrs["status"] == X.VERIFIED
    with pytest.raises(X.ForbiddenUse):                                         # verified still never means option data
        X.load(ds, "1m", ["NIFTY"], use="option_chain")
