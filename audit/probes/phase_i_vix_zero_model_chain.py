"""Phase I: the model chain and the VIX vote when today's India VIX bars are 0 (the recorded production condition).
Synthetic session (phase_h_det_tests.world); prior days keep their synthetic VIX, as production read them from Yahoo.

    python audit/probes/phase_i_vix_zero_model_chain.py > out.json
"""
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import phase_h_det_tests as H
from quantdesk.intraday.chains import chain_analytics
bars, days = H.world()
day = days[-1]
out = {}
for label, vixmod in (("vix_normal", None), ("vix_zero", 0.0)):
    b = {k: v.copy() for k, v in bars.items()}
    if vixmod is not None:
        v = b["INDIAVIX"]; today = v.index.date == day          # production: prior days from Yahoo, today from Kotak = 0
        for c in ("open", "high", "low", "close"):
            v.loc[today, c] = vixmod
    eng = H.make(Path(tempfile.mkdtemp(prefix="i-vix-")), b, day)
    eng.start_session(day)
    H.advance(eng, "10:30")
    S, iv = eng.model_state("NIFTY", eng.feed.now())
    ch = eng.model_chain.chain("NIFTY", eng.expiry["NIFTY"], ts=eng.feed.now())
    k = ch.index[abs(ch.index - S).argmin()]
    an = eng.chain_an.get("NIFTY", {})
    vs = eng._vix_state()
    out[label] = {"model_state_iv": iv, "atm_strike": float(k), "atm_ce_ltp": float(ch.loc[k, "ce_ltp"]),
                  "atm_ce_bid_ask": [float(ch.loc[k, "ce_bid"]), float(ch.loc[k, "ce_ask"])],
                  "atm_ce_iv_col": float(ch.loc[k, "ce_iv"]), "engine_chain_an_atm_iv": an.get("atm_iv"),
                  "engine_chain_source": eng.chain_df["NIFTY"].attrs.get("source"),
                  "vix_state": vs}
print(json.dumps(out, indent=1, default=str))
