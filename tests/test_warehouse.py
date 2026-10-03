"""The NSE data warehouse: parsers on the real formats (lines copied from NSE's files on 2 Oct 2026, via
deploy/probe_nse.py), the gap-filling update, provenance, and the GitHub-release store."""
import datetime as dt
import io
import json
import zipfile

import pandas as pd
import pytest

from quantdesk.data import nse as N
from quantdesk.data.warehouse import ReleaseStore, Warehouse, holiday_diff, needed_assets, update

UDIFF = """TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4
2026-10-01,2026-10-01,FO,NSE,STO,67131,,ABCAPITAL,,2026-10-27,2026-10-27,435.00,PE,ABCAPITAL26OCT435PE,0.00,0.00,0.00,39.30,39.30,39.30,375.05,59.85,3100,0,0,0.00,0,F1,3100,,,,,
2026-10-01,2026-10-01,FO,NSE,IDO,51245,,NIFTY,,2026-10-27,2026-10-27,20750.00,PE,NIFTY26OCT20750PE,17.40,41.40,17.40,26.40,27.40,19.30,22421.95,26.40,12480,4290,752,1015745532.75,393,F1,65,,,,,
2026-10-01,2026-10-01,FO,NSE,IDO,47166,,NIFTY,,2026-10-19,2026-10-19,23050.00,PE,NIFTY26O1923050PE,509.25,751.45,495.45,604.10,608.20,473.40,22421.95,604.10,3185,-650,47,72135258.00,45,F1,65,,,,,
2026-10-01,2026-10-01,FO,NSE,IDF,35001,,NIFTY,,2026-10-27,2026-10-27,,,NIFTY26OCTFUT,22500.00,22600.00,22400.00,22480.50,22481.00,22650.00,22421.95,22480.50,15000000,120000,250000,1.0E11,90000,F1,65,,,,,
"""
OLD = """INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,
FUTIDX,BANKNIFTY,31-Jul-2024,0,XX,52998.6,52998.6,52300,52724.1,52724.1,177911,1403441.12,2607810,-185025,05-JUL-2024,
FUTIDX,NIFTY,25-Jul-2024,0,XX,24306.9,24419.2,24240,24379.4,24379.4,230381,1400814.91,14171325,-371200,05-JUL-2024,
OPTIDX,NIFTY,11-Jul-2024,24300,CE,180,210.5,150.2,190.35,190.35,812345,4934567.1,5432100,123450,05-JUL-2024,
OPTSTK,RELIANCE,25-Jul-2024,3100,CE,50,60,45,55,55,1000,100,20000,100,05-JUL-2024,
"""
PART = '''""Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Oct 01, 2026"",,,,,,,,,,,,,,
Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short       ,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short,Option Stock Call Long,Option Stock Put Long,Option Stock Call Short,Option Stock Put Short,Total Long Contracts      ,Total Short Contracts
Client,306566,56754,3422680,155072,3743798,2363022,3448314,3206170,1566739,571650,883971,875714,11974455,8625995
DII,48119,14862,264333,4574585,8533,40402,3557,876,9411,43501,204308,22745,414299,4820933
FII,29605,339779,3393649,2858568,670483,1114773,1101948,448195,112470,227850,206962,90579,5548830,5046031
Pro,51101,23996,817937,310374,1337674,958371,1206669,821327,669169,831768,1062548,685731,4666020,4110645
TOTAL,435391,435391,7898599,7898599,5760488,4476568,5760488,4476568,2357789,1674769,2357789,1674769,22603604,22603604
'''
STATUS = {"marketState": [{"market": "Capital Market", "index": "NIFTY 50", "last": 22421.95}],
          "indicativenifty50": {"finalClosingValue": 22421.95, "closingValue": 22421.95},
          "giftnifty": {"CONTRACTSTRADED": 83278, "DAYCHANGE": 133.5, "EXPIRYDATE": "27-Oct-2026", "INSTRUMENTTYPE": "FUTIDX",
                        "LASTPRICE": 22624.5, "PERCHANGE": 0.59, "SYMBOL": "NIFTY", "TIMESTMP": "02-Oct-2026 02:42"}}
FIIDII = [{"buyValue": "25420.04", "category": "DII", "date": "01-Oct-2026", "netValue": "10041.84", "sellValue": "15378.2"},
          {"buyValue": "12260.26", "category": "FII/FPI", "date": "01-Oct-2026", "netValue": "-9484.22", "sellValue": "21744.48"}]


def zipped(text: str, name: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


def test_udiff_bhavcopy_keeps_index_contracts_only():
    df = N.parse_fo_bhav(zipped(UDIFF, "BhavCopy.csv"), dt.date(2026, 10, 1))
    assert list(df.columns) == N.BHAV_COLS and len(df) == 3                    # the stock option is dropped
    put = df[(df.kind == "PE") & (df.strike == 20750)].iloc[0]
    assert put.expiry == dt.date(2026, 10, 27) and put.close == 26.40 and put.underlying == 22421.95
    assert put.oi == 12480 and put.contracts == 752 and put.lot == 65 and put.src == "udiff"
    fut = df[df.kind == "FUT"].iloc[0]
    assert fut.strike != fut.strike and fut.close == 22480.5                   # futures carry no strike
    with pytest.raises(ValueError, match="trade dates"):
        N.parse_fo_bhav(zipped(UDIFF, "x.csv"), dt.date(2026, 10, 2))           # a file for another day is refused


def test_old_bhavcopy_format():
    df = N.parse_fo_bhav(zipped(OLD, "fo05JUL2024bhav.csv"), dt.date(2024, 7, 5))
    assert len(df) == 3 and set(df.kind) == {"FUT", "CE"} and (df.src == "old").all()
    ce = df[df.kind == "CE"].iloc[0]
    assert (ce.symbol, ce.expiry, ce.strike, ce.close, ce.contracts) == ("NIFTY", dt.date(2024, 7, 11), 24300, 190.35, 812345)
    assert ce.underlying != ce.underlying and ce.lot != ce.lot                 # the old format has neither


def test_participant_file_with_its_title_line_and_ragged_headers():
    df = N.parse_participant(PART.encode(), dt.date(2026, 10, 1))
    assert list(df.participant) == ["Client", "DII", "FII", "Pro", "TOTAL"]
    fii = df.set_index("participant").loc["FII"]
    assert fii.fut_idx_long == 29605 and fii.fut_idx_short == 339779 and fii.fut_stk_short == 2858568
    assert fii.total_long == 5548830 and fii.opt_idx_put_short == 448195
    assert (df.drop(columns=["date", "participant"]).iloc[:4].sum() == df.drop(columns=["date", "participant"]).iloc[4]).all()


def test_api_parsers():
    g = N.parse_gift(STATUS).iloc[0]
    assert g["last"] == 22624.5 and g["expiry"] == dt.date(2026, 10, 27) and g["nifty_close"] == 22421.95
    assert g["ts"] == pd.Timestamp("2026-10-02 02:42", tz="Asia/Kolkata")
    gap = N.gift_implied_gap(g["last"], g["nifty_close"], g["expiry"], dt.date(2026, 10, 2))
    assert 0.004 < gap < 0.006                                                 # +0.90% premium, ~0.36% of it is carry
    f = N.parse_fii_dii(FIIDII).set_index("category")
    assert f.loc["FII", "net"] == -9484.22 and f.loc["DII", "buy"] == 25420.04
    h = N.parse_holidays({"FO": [{"tradingDate": "02-Oct-2026", "description": "Mahatma Gandhi Jayanti"}]})
    assert h == [(dt.date(2026, 10, 2), "Mahatma Gandhi Jayanti")]


class Resp:
    def __init__(self, status, content=b"", js=None):
        self.status_code, self.content, self._js = status, content, js

    def json(self):
        if self._js is None:
            raise ValueError
        return self._js


class FakeNSE:
    """NSE's archives for 30 Sep – 1 Oct 2026: 1 Oct has every file, 30 Sep's bhavcopy is missing."""

    def __init__(self):
        self.headers, self.got = {}, []

    def get(self, url, timeout=None):
        self.got.append(url)
        if url.endswith(("/", "/option-chain")):
            return Resp(200, b"<html>")
        if "20261001_F_0000.csv.zip" in url:
            return Resp(200, zipped(UDIFF, "BhavCopy.csv"))
        if "fao_participant_oi_01102026" in url or "fao_participant_vol_01102026" in url:
            return Resp(200, PART.encode())
        if "fao_participant_oi_30092026" in url:
            return Resp(200, PART.replace("Oct 01", "Sep 30").encode())
        if url.endswith("/api/marketStatus"):
            return Resp(200, json.dumps(STATUS).encode(), STATUS)
        if url.endswith("/api/fiidiiTradeReact"):
            return Resp(200, json.dumps(FIIDII).encode(), FIIDII)
        if "/api/" in url:
            return Resp(200, b"[]", [])
        return Resp(404, b"<!DOCTYPE html>")


def test_update_fills_gaps_and_records_provenance(tmp_path):
    wh = Warehouse(tmp_path)
    fake = FakeNSE()
    nse = N.NSE(session=fake, gap=0)
    say = []
    c = update(wh, nse, dt.date(2026, 9, 30), dt.date(2026, 10, 1), only={"fo_bhav", "participant_oi", "gift_nifty",
                                                                        "fii_dii"},
               say=say.append, today=dt.date(2026, 10, 2))
    assert c["fo_bhav"] == 3 and c["participant_oi"] == 10 and c["gift_nifty"] == 1 and c["fii_dii"] == 2
    bhav = wh.read("fo_bhav")
    assert len(bhav) == 3 and sorted(p.name for p in wh.files("fo_bhav")) == ["fo_bhav_2026-10.parquet"]
    man = wh.read("manifest").set_index(["table", "date"])
    ok = man.loc[("fo_bhav", pd.Timestamp("2026-10-01"))]
    assert ok.status == "ok" and len(ok.sha256) == 64 and ok.rows == 3 and "BhavCopy_NSE_FO" in ok.url
    assert man.loc[("fo_bhav", pd.Timestamp("2026-09-30"))].status == "none"   # NSE had nothing
    # run again the same day: the missing day is retried (it might still come), everything else is settled
    fake.got.clear()
    update(wh, nse, dt.date(2026, 9, 30), dt.date(2026, 10, 1), only={"fo_bhav", "participant_oi"}, say=say.append,
           today=dt.date(2026, 10, 2))
    assert [u for u in fake.got if "nsearchives" in u] == [
        "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_20260930_F_0000.csv.zip"]
    # a week later: one last try, and then it's taken as never coming
    for expect in (1, 0):
        fake.got.clear()
        update(wh, nse, dt.date(2026, 9, 30), dt.date(2026, 10, 1), only={"fo_bhav"}, say=say.append,
               today=dt.date(2026, 10, 9))
        assert len([u for u in fake.got if "nsearchives" in u]) == expect
    assert len(wh.read("fo_bhav")) == 3                                          # no duplicates from re-runs


def test_holidays_are_skipped_and_checked(tmp_path):
    wh = Warehouse(tmp_path)
    fake = FakeNSE()
    update(wh, N.NSE(session=fake, gap=0), dt.date(2026, 10, 1), dt.date(2026, 10, 2), only={"participant_oi"},
           holidays={dt.date(2026, 10, 2)}, say=lambda m: None, today=dt.date(2026, 10, 9))
    assert not any("02102026" in u for u in fake.got)
    wh.upsert("nse_holidays", pd.DataFrame({"date": [dt.date(2026, 10, 2), dt.date(2026, 11, 9)],
                                            "description": ["Gandhi Jayanti", "Diwali Laxmi Pujan"]}))
    missing, extra = holiday_diff(wh, {dt.date(2026, 10, 2), dt.date(2026, 10, 20)}, 2026)
    assert missing == [(dt.date(2026, 11, 9), "Diwali Laxmi Pujan")] and extra == [dt.date(2026, 10, 20)]


def test_release_store_pulls_only_whats_there_and_pushes_changes(tmp_path):
    calls = []

    class R:
        def __init__(self, rc=0, out=""):
            self.returncode, self.stdout = rc, out

    def run(cmd, check=True, capture_output=True, text=True):
        calls.append(cmd)
        if cmd[1:3] == ["release", "view"] and "--json" in cmd:
            return R(0, json.dumps({"assets": [{"name": "fo_bhav_2026-10.parquet"}, {"name": "manifest_2026.parquet"}]}))
        return R(0, "")
    st = ReleaseStore("warehouse", run=run)
    got = st.pull(tmp_path, ["fo_bhav_2026-09.parquet", "fo_bhav_2026-10.parquet", "manifest_2026.parquet"])
    assert got == ["fo_bhav_2026-10.parquet", "manifest_2026.parquet"]
    assert sum(c[1:3] == ["release", "download"] for c in calls) == 2
    st.push(tmp_path, ["fo_bhav_2026-10.parquet"])
    up = [c for c in calls if c[1:3] == ["release", "upload"]][0]
    assert up[-1] == "--clobber" and up[3] == "warehouse" and up[4].endswith("fo_bhav_2026-10.parquet")
    names = needed_assets(dt.date(2026, 9, 25), dt.date(2026, 10, 2))
    assert "fo_bhav_2026-09.parquet" in names and "fo_bhav_2026-10.parquet" in names and "participant_oi_2026.parquet" in names


# ---- the session archive -----------------------------------------------------------------------------------------
def test_session_archive_compacts_chains_and_bars(tmp_path):
    import numpy as np
    from quantdesk.data.archive import archive, compact_day, load_archive
    from quantdesk.intraday.chains import COLUMNS
    from quantdesk.intraday.recorder import SessionRecorder
    rec = SessionRecorder(tmp_path / "data")
    day = dt.date(2026, 10, 5)
    for minute, spot in ((30, 22450.0), (31, 22455.5)):
        ch = pd.DataFrame(np.arange(len(COLUMNS) * 3, dtype=float).reshape(3, -1), columns=COLUMNS,
                          index=pd.Index([22400.0, 22450.0, 22500.0], name="strike"))
        ch.attrs.update({"underlying": "NIFTY", "spot": spot, "expiry": dt.date(2026, 10, 6),
                         "ts": pd.Timestamp(f"{day} 09:{minute}", tz="Asia/Kolkata"), "source": "kotak"})
        rec.record_chain(ch)
    bars = pd.DataFrame({"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "close": [1.0, 2.0], "volume": [0.0, 0.0]},
                        index=pd.DatetimeIndex([f"{day} 09:15", f"{day} 09:16"]).tz_localize("Asia/Kolkata"))
    rec.record_bars("NIFTY", bars)
    f = compact_day(tmp_path / "data" / str(day))
    assert len(f["chains"]) == 6 and set(f["chains"]["spot"]) == {22450.0, 22455.5} and len(f["bars"]) == 2
    assert {"ts", "underlying", "expiry", "spot", "source", "strike", "ce_bid", "pe_ask"} <= set(f["chains"].columns)
    pushed = []

    class Store:
        def __init__(self, year):
            self.year = year

        def push(self, src, names):
            pushed.append((self.year, sorted(names)))
    names = archive(tmp_path / "data", "morning-7", tmp_path / "out", store_for=Store, say=lambda m: None)
    assert sorted(names) == ["2026-10-05_morning-7_bars.parquet", "2026-10-05_morning-7_chains.parquet"]
    assert pushed == [(2026, sorted(names))]
    back = load_archive(tmp_path / "out", "chains")
    assert len(back) == 6 and back["source"].eq("kotak").all()


STOCKS = UDIFF.splitlines()[0] + "\n" + "\n".join(
    [f"2026-10-01,2026-10-01,FO,NSE,STO,1,,RELIANCE,,2026-10-27,2026-10-27,{k}.00,{r},X,0,0,0,{c},0,0,1402.50,0,"
     f"{oi},0,{n},0,0,F1,500,,,,," for k, r, c, oi, n in
     [(1390, "CE", 25.0, 500000, 3000), (1400, "CE", 19.5, 900000, 9000), (1410, "CE", 14.0, 700000, 6000),
      (1390, "PE", 12.0, 400000, 2500), (1400, "PE", 16.5, 800000, 7000), (1410, "PE", 22.0, 300000, 90)]]
    + ["2026-10-01,2026-10-01,FO,NSE,STO,1,,RELIANCE,,2026-11-24,2026-11-24,1400.00,CE,X,0,0,0,40.0,0,0,1402.50,0,"
       "100000,0,999,0,0,F1,500,,,,,",
       "2026-10-01,2026-10-01,FO,NSE,STF,1,,RELIANCE,,2026-10-27,2026-10-27,,,X,0,0,0,1408.0,0,0,1402.50,0,"
       "50000000,0,40000,0,0,F1,500,,,,,"]) + "\n" + "\n".join(UDIFF.splitlines()[1:]) + "\n"


def test_stock_liquidity_from_the_same_bhavcopy():
    df = N.parse_fo_stocks(zipped(STOCKS, "b.csv"), dt.date(2026, 10, 1))
    assert list(df.columns) == N.STOCK_COLS and set(df["symbol"]) == {"RELIANCE", "ABCAPITAL"}   # no index rows
    r = df.set_index("symbol").loc["RELIANCE"]
    assert r.expiry == dt.date(2026, 10, 27) and r.lot == 500 and r.underlying == 1402.5
    assert r.opt_contracts == 27590 and r.active_strikes == 3                          # 1410 PE's 90 contracts don't count
    assert r.opt_premium == pytest.approx(500 * (25 * 3000 + 19.5 * 9000 + 14 * 6000 + 12 * 2500 + 16.5 * 7000 + 22 * 90))
    assert r.opt_oi == pytest.approx(3_600_000 / 500) and r.fut_oi == 100_000 and r.fut_contracts == 40000
    assert r.strike_step == 10 and r.atm_straddle == pytest.approx(36 / 1402.5)        # the November row is ignored
    assert (r.atm_call, r.atm_put) == (19.5, 16.5) and r.otm2_call != r.otm2_call     # no strike two above 1400 here


def test_buying_one_lot_of_a_stock_option():
    from quantdesk.intraday import stocks
    rel = pd.Series({"lot": 500, "atm_call": 18.6, "atm_put": 17.0, "otm2_call": 7.4, "otm2_put": 6.9})
    ok, why = stocks.fits_long(rel, 20000, 0.08)                        # ATM ₹9,300: over the ₹7,000 outlay cap
    assert ok and why.startswith("call 2 strikes out ₹7.40 × 500 = ₹3,700") and "risks ₹1,110" in why
    assert stocks.fits_long(rel, 50000, 0.08)[1].startswith("ATM call")  # a bigger account buys at the money
    pricey = pd.Series({"lot": 50, "atm_call": 420.0, "atm_put": 400.0, "otm2_call": 260.0, "otm2_put": 240.0})
    no, why = stocks.fits_long(pricey, 20000, 0.08)
    assert not no and "≈₹12,000" in why


def test_ranking_and_what_the_account_can_hold():
    from quantdesk.intraday import stocks
    rows = []
    for i, d in enumerate(pd.bdate_range("2026-09-01", periods=25)):
        rows += [{"date": d.date(), "symbol": "RELIANCE", "lot": 500, "underlying": 1400.0, "expiry": None, "opt_contracts": 2e5,
                  "opt_premium": 4e8 + i, "opt_oi": 1e5, "active_strikes": 30, "strike_step": 10.0, "atm_straddle": 0.03,
                  "fut_contracts": 4e4, "fut_oi": 1e5, "fut_close": 1405.0},
                 {"date": d.date(), "symbol": "IDEA", "lot": 70000, "underlying": 8.0, "expiry": None, "opt_contracts": 5e4,
                  "opt_premium": 6e7, "opt_oi": 1e5, "active_strikes": 12, "strike_step": 0.05 * 0 + 1.0, "atm_straddle": 0.08,
                  "fut_contracts": 2e4, "fut_oi": 1e5, "fut_close": 8.0},
                 {"date": d.date(), "symbol": "THIN", "lot": 1000, "underlying": 300.0, "expiry": None, "opt_contracts": 900,
                  "opt_premium": 9e8, "opt_oi": 1e3, "active_strikes": 4, "strike_step": 5.0, "atm_straddle": 0.05,
                  "fut_contracts": 100, "fut_oi": 1e3, "fut_close": 300.0}]
    r = stocks.rank(pd.DataFrame(rows), days=20)
    assert list(r.index) == ["RELIANCE", "IDEA", "THIN"] and r.loc["RELIANCE", "sessions"] == 20
    assert not r.loc["THIN", "liquid"] and r.loc["RELIANCE", "min_spread_risk"] == 2500
    assert stocks.fits(r.loc["RELIANCE"], 20000, 0.08) == (False, "one lot of a 1-strike spread risks ≈₹2,500 (12.5%), over the ₹1,600 budget")
    assert stocks.fits(r.loc["RELIANCE"], 100000, 0.08)[0]
    lines = stocks.table(r, 20000, 0.08)
    assert lines[1].startswith("RELIANCE") and "below the liquidity bar" in lines[-1]
