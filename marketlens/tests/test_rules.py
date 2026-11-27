"""The ban list and MWPL parsers on the layouts NSE has used, and on files they must refuse."""
import io
import zipfile

import pandas as pd
import pytest

from marketlens.engine import rules as R

BAN = b"Securities in Ban For Trade Date 27-NOV-2026:\r\n1,SAIL\r\n2,RBLBANK\r\n3,M&M\r\n"
BAN_NIL = b"Securities in Ban For Trade Date 28-NOV-2026: NIL\n"
MWPL_OLD = (b"Date,ISIN,Scrip Name,NSE Symbol,MWPL,Open Interest,Limit for Next Day\n"
            b"27-Nov-2026,INE114A01011,STEEL AUTHORITY OF INDIA,SAIL,\"1,000,000\",\"960,000\",No Fresh Positions\n"
            b"27-Nov-2026,INE002A01018,RELIANCE INDUSTRIES LTD,RELIANCE,5000000,1500000,3250000\n")
MWPL_NEW = (b"Date,ISIN,Scrip Name,NSE Symbol,MWPL,Open Interest,Future Equivalent Open Interest,Limit for Next Day\n"
            b"27-Nov-2026,INE002A01018,RELIANCE INDUSTRIES LTD,RELIANCE,5000000,9999999,2000000,2750000\n")


def test_ban_list_and_nil():
    assert R.parse_ban(BAN) == ["SAIL", "RBLBANK", "M&M"]
    assert R.parse_ban(BAN_NIL) == []


def test_ban_refuses_html_or_garbage():
    with pytest.raises(R.FormatError):
        R.parse_ban(b"<html><body>Not found</body></html>")
    with pytest.raises(R.FormatError):
        R.parse_ban(b"Securities in Ban For Trade Date 27-NOV-2026:\nsomething else entirely\n")


def test_mwpl_old_layout_and_thousands_separators():
    m = R.parse_mwpl(MWPL_OLD).set_index("symbol")
    assert m.loc["SAIL", "util"] == pytest.approx(0.96)
    assert m.loc["SAIL", "limit_text"] == "No Fresh Positions"
    assert m.loc["RELIANCE", "util"] == pytest.approx(0.30)


def test_mwpl_new_layout_uses_futures_equivalent_oi():
    m = R.parse_mwpl(MWPL_NEW).set_index("symbol")
    assert m.loc["RELIANCE", "util"] == pytest.approx(0.40)     # 2,000,000 / 5,000,000, not the plain OI


def test_mwpl_from_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("combineoi_27112026.csv", MWPL_OLD)
    assert len(R.parse_mwpl(buf.getvalue())) == 2


def test_mwpl_refuses_wrong_file():
    with pytest.raises(R.FormatError):
        R.parse_mwpl(b"a,b,c\n1,2,3\n")


def test_stock_block_and_sentences():
    d1, d2 = pd.Timestamp("2026-11-26"), pd.Timestamp("2026-11-27")
    ban = pd.DataFrame({"date": [d1, d2, d2], "symbol": ["", "", "SAIL"]})
    mw = pd.DataFrame({"date": [d1, d2, d2], "symbol": ["SAIL", "SAIL", "RELIANCE"], "mwpl": [1e6, 1e6, 5e6],
                       "oi": [9e5, 9.6e5, 4.1e6], "util": [0.9, 0.96, 0.82], "limit_text": ["", "No Fresh Positions", ""]})
    s = R.stock_block("SAIL", ban, mw)
    assert s["in_ban"] and s["ban_date"] == "2026-11-27" and s["ban_days"] == 1 and s["util"] == pytest.approx(0.96)
    assert "in the F&O ban for the 2026-11-27 session" in R.sentence(s)
    r = R.stock_block("RELIANCE", ban, mw)
    assert r["in_ban"] is False and "82%" in R.sentence(r) and "close" in R.sentence(r)


def test_fetch_skips_unpublished_days_and_merges(tmp_path):
    from quantdesk.data.nse import NotPublished

    class Fake:
        def archive(self, path):
            if "fo_secban_27112026" in path:
                return BAN, "https://x/content/fo/" + path
            if "combineoi_27112026.csv" in path:
                return MWPL_OLD, "https://x/archives/nsccl/mwpl/" + path
            raise NotPublished(path)

    rep = R.fetch(tmp_path, [pd.Timestamp("2026-11-27").date(), pd.Timestamp("2026-11-28").date()], nse=Fake(), say=lambda *_: None)
    assert rep["ban_days"] == 1 and rep["mwpl_days"] == 1 and not rep["errors"]
    ban, mw = R.load(tmp_path)
    assert sorted(ban["symbol"]) == ["", "M&M", "RBLBANK", "SAIL"] and len(mw) == 2
