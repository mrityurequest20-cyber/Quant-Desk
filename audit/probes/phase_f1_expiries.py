"""Phase F1: the desk's expiry calendar and lot sizes vs the exchanges' own files (warehouse bhavcopies)."""
import sys, glob, datetime as dt
from pathlib import Path
import pandas as pd
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from quantdesk.config import Config, DEFAULT_CONFIG
from quantdesk.core.calendar import TradingCalendar
wh = Path(sys.argv[1])
cfg = Config.load(DEFAULT_CONFIG)
nse = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{wh}/fo_bhav_2026*.parquet"))])
bse = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{wh}/bse_fo_bhav_2026*.parquet"))])
hol = pd.read_parquet(f"{wh}/nse_holidays_2026.parquet")
print("holiday table:", hol.columns.tolist(), len(hol))
cal = TradingCalendar(cfg.holidays())                     # the desk's own holidays (config), as the engine uses
nse_wd = {d for d in pd.to_datetime(hol.date).dt.date if d.weekday() < 5}
print("desk holidays:", len(cal.holidays), "| NSE weekday holidays missing from the desk:", sorted(nse_wd - cal.holidays),
      "| desk holidays NSE doesn't list:", sorted(cal.holidays - nse_wd))
for sym, df in (("NIFTY", nse), ("BANKNIFTY", nse), ("FINNIFTY", nse), ("MIDCPNIFTY", nse), ("NIFTYNXT50", nse), ("SENSEX", bse), ("BANKEX", bse)):
    o = df[(df.symbol == sym) & df.kind.isin(["CE", "PE"])]
    if o.empty:
        print(sym, "no rows"); continue
    spec = cfg.instrument_spec(sym) if sym in ("NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY","SENSEX","BANKEX") else None
    real = sorted({pd.Timestamp(e).date() for e in o.expiry if dt.date(2026, 10, 9) <= pd.Timestamp(e).date() <= dt.date(2026, 12, 31)})
    lots = o[o.date == o.date.max()].lot.dropna().unique() if "lot" in o else []
    if spec:
        mine = [e for e in cal.expiries(dt.date(2026, 10, 9), 83, spec["expiry_weekday"], spec["weekly_expiry"])]
        missing = sorted(set(real) - set(mine))                        # listed by the exchange, absent from the desk
        horizon = max(real) if real else dt.date(2026, 10, 9)
        unlisted = sorted(e for e in mine if e <= horizon and e not in real)   # desk dates inside the listed range
        later = sum(e > horizon for e in mine)
        print(f"{sym:10s} lot cfg {spec['lot_size']:>4} exch {[int(x) for x in lots]} | listed {len(real)}, all on the desk "
              f"calendar: {not missing} {missing or ''} | desk dates inside the listed range but not listed: {unlisted} "
              f"| desk weeklies beyond the listing: {later}")
    else:
        print(f"{sym:10s} not configured; exch lot {list(lots)} expiries {real[:4]}")
