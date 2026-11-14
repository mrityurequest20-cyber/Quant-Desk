"""Probation release (B): checked at the end of every session after demotion. Rule: at least TR trades over at least SS distinct sessions since demotion, and the
mean of the SESSION means above zero. Reports the share released within 20 calendar sessions of a strategy that is truly at mu (it closes trades on half of them), for
three R shapes and several (trades a session, within-session correlation)."""
import numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simB5 as B
def release(out, mask, TR, SS):
    tot = np.where(mask, out, 0).sum(2); cnt = mask.sum(2)
    act = cnt > 0
    smean = np.where(act, tot / np.maximum(cnt, 1), 0.0)
    n_tr, n_s, s_sum = np.cumsum(cnt, 1), np.cumsum(act, 1), np.cumsum(smean, 1)
    ok = (n_tr >= TR) & (n_s >= SS) & (s_sum > 0)
    return np.where(ok.any(1), ok.argmax(1), -1)
REGISTERED = (8, 8)
if __name__ == "__main__":
    N = 3000
    print("released within 20 calendar sessions (a strategy closing trades on half of them); min-max over the three R shapes")
    for TR, SS in ((8, 1), (8, 3), (8, 5), (16, 5), REGISTERED):
        for m, rho in ((1, 0.0), (2, 0.3), (5, 0.6)):
            row = []
            for mu in (-0.3, -0.1, 0.15, 0.3):
                res = []
                for kind in ("normal", "credit", "2/-1"):
                    o, mk = B.series(N, 60, [((0, 60), mu)], kind, m, rho)
                    f = release(o, mk, TR, SS)
                    res.append(((f >= 0) & (f < 20)).mean())
                row.append(f"mu {mu:+.2f}: {min(res):.2f}-{max(res):.2f}")
            tag = "  <- registered" if (TR, SS) == REGISTERED else ""
            print(f">= {TR} trades over >= {SS} sessions, m={m} rho={rho}: " + "; ".join(row) + tag)
