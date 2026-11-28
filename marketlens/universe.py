"""What MarketLens covers: the instruments the owner trades. No currencies."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    kind: str            # "index" | "stock" | "vix"
    exchange: str        # "NSE" | "BSE"
    index_name: str | None = None   # the name in NSE's official index-close file
    sector: str | None = None


INDICES = [
    Instrument("NIFTY", "Nifty 50", "index", "NSE", "Nifty 50", "Broad market"),
    Instrument("BANKNIFTY", "Nifty Bank", "index", "NSE", "Nifty Bank", "Banks"),
    Instrument("FINNIFTY", "Nifty Financial Services", "index", "NSE", "Nifty Financial Services", "Financials"),
    Instrument("MIDCPNIFTY", "Nifty Midcap Select", "index", "NSE", "Nifty Midcap Select", "Midcaps"),
    Instrument("NIFTYNXT50", "Nifty Next 50", "index", "NSE", "Nifty Next 50", "Large caps (next 50)"),
    Instrument("SENSEX", "BSE Sensex", "index", "BSE", None, "Broad market"),
    Instrument("BANKEX", "BSE Bankex", "index", "BSE", None, "Banks"),
]

VIX = Instrument("INDIAVIX", "India VIX", "vix", "NSE", "India VIX", "Volatility")

STOCKS = [
    Instrument("RELIANCE", "Reliance Industries", "stock", "NSE", sector="Energy & conglomerate"),
    Instrument("HDFCBANK", "HDFC Bank", "stock", "NSE", sector="Banks"),
    Instrument("SBIN", "State Bank of India", "stock", "NSE", sector="Banks"),
    Instrument("ICICIBANK", "ICICI Bank", "stock", "NSE", sector="Banks"),
    Instrument("TCS", "Tata Consultancy Services", "stock", "NSE", sector="IT"),
    Instrument("BHARTIARTL", "Bharti Airtel", "stock", "NSE", sector="Telecom"),
    Instrument("BSE", "BSE Ltd", "stock", "NSE", sector="Capital markets"),
    Instrument("INFY", "Infosys", "stock", "NSE", sector="IT"),
    Instrument("AXISBANK", "Axis Bank", "stock", "NSE", sector="Banks"),
    Instrument("MARUTI", "Maruti Suzuki", "stock", "NSE", sector="Autos"),
    Instrument("DIXON", "Dixon Technologies", "stock", "NSE", sector="Electronics manufacturing"),
    Instrument("PAYTM", "One 97 Communications (Paytm)", "stock", "NSE", sector="Fintech"),
    Instrument("BAJAJ-AUTO", "Bajaj Auto", "stock", "NSE", sector="Autos"),
    Instrument("KOTAKBANK", "Kotak Mahindra Bank", "stock", "NSE", sector="Banks"),
    Instrument("BHEL", "Bharat Heavy Electricals", "stock", "NSE", sector="Capital goods"),
    Instrument("LAURUSLABS", "Laurus Labs", "stock", "NSE", sector="Pharma"),
    Instrument("DIVISLAB", "Divi's Laboratories", "stock", "NSE", sector="Pharma"),
    Instrument("ITC", "ITC", "stock", "NSE", sector="FMCG"),
    Instrument("BAJFINANCE", "Bajaj Finance", "stock", "NSE", sector="NBFC"),
    Instrument("M&M", "Mahindra & Mahindra", "stock", "NSE", sector="Autos"),
]

ALL = INDICES + STOCKS
BY_SYMBOL = {i.symbol: i for i in ALL + [VIX]}


def slug(symbol: str) -> str:
    """A file-safe name: M&M -> M_M, BAJAJ-AUTO -> BAJAJ-AUTO."""
    return symbol.replace("&", "_")
