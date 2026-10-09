"""Phase I: recompute every thought's score/conviction/bias from its persisted evidence; counterfactual without the VIX vote.

    python audit/probes/phase_i_thought_recompute.py JOURNAL_DB > out.json
"""
import sqlite3, json, sys, numpy as np
db = sys.argv[1]
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
rows = c.execute("select id, ts, symbol, bias, score, conviction, action, evidence from thoughts order by id").fetchall()
def agg(ev):
    if not ev: return 0.0, 0.0, "neutral"
    tot_w = sum(e["weight"] for e in ev if e["direction"] != 0) or 1.0
    score = sum(e["weight"] * e["direction"] for e in ev) / sum(e["weight"] for e in ev)
    agree = sum(e["weight"] for e in ev if np.sign(e["direction"]) == np.sign(score) and e["direction"] != 0) / tot_w
    bias = "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"
    return score, abs(score) * agree, bias
n = ok_s = ok_b = ok_c = 0; vix_rows = vix_plus = flips = 0; dscore = []; flip_eg = []
for i, ts, sym, bias, score, conv, action, ev in rows:
    ev = json.loads(ev); n += 1
    s, cv, b = agg(ev)
    ok_s += abs(s - score) < 1e-9; ok_c += abs(cv - conv) < 1e-9; ok_b += (b == bias)
    vx = [e for e in ev if e["factor"] == "vix"]
    if vx:
        vix_rows += 1; vix_plus += vx[0]["direction"] == 1.0 and "0.00 (-100.0%" in vx[0]["observation"]
        s2, cv2, b2 = agg([e for e in ev if e["factor"] != "vix"])
        dscore.append(score - s2)
        if b2 != bias:
            flips += 1
            if len(flip_eg) < 5: flip_eg.append((ts[:16], sym, bias, round(score, 3), "->", b2, round(s2, 3), action[:40]))
print(json.dumps({"thoughts": n, "score_recomputed_exactly": ok_s, "conviction_recomputed_exactly": ok_c,
                  "bias_recomputed_exactly": ok_b, "rows_with_vix_factor": vix_rows,
                  "vix_is_zero_minus100pct_plus1": vix_plus,
                  "mean_score_shift_from_vix": round(float(np.mean(dscore)), 4) if dscore else None,
                  "max_score_shift_from_vix": round(float(np.max(dscore)), 4) if dscore else None,
                  "bias_label_flips_without_vix": flips, "examples": flip_eg}, indent=1))
