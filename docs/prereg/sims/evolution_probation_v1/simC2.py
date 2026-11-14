"""The calibration watch (C), revised: it scores what the model contributes, its VOTES (P >= 0.65 or <= 0.35), as calls: right or wrong on the next window's move (one
vote per scoring window). An exponentially weighted hit rate, ALPHA per vote, started from the plain mean of the first MIN_VOTES; the mute is decided once a session, at
its close, for the next session: muted below MUTE_BELOW, unmuted at UNMUTE_AT or above. Votes a session: Poisson(v); votes in one session share a session-level hit
probability (a + N(0, 0.15), clipped): a model's calls on one day are not independent."""
import numpy as np
rng = np.random.default_rng(37)
def muted_share(a, v, alpha=0.02, min_votes=50, mute=0.47, unmute=0.52, T=250, N=3000):
    k = rng.poisson(v, (N, T))
    ps = np.clip(a + rng.normal(0, 0.15, (N, T)), 0.02, 0.98)
    ew = np.full(N, np.nan); seen = np.zeros(N); first_sum = np.zeros(N); muted = np.zeros(N, bool); share = np.zeros(N); live = np.zeros(N)
    for t in range(T):
        live += (seen >= min_votes); share += muted
        M = k[:, t].max()
        for j in range(M):
            has = k[:, t] > j
            y = (rng.random(N) < ps[:, t]).astype(float)
            warm = has & (seen < min_votes)
            first_sum += np.where(warm, y, 0); seen += warm
            just = warm & (seen == min_votes)
            ew = np.where(just, first_sum / min_votes, ew)
            upd = has & ~warm & (seen >= min_votes)
            ew = np.where(upd, (1 - alpha) * ew + alpha * y, ew)
        ready = seen >= min_votes
        muted = np.where(ready, np.where(muted, ew < unmute, ew < mute), False)
    return (share / np.maximum(live, 1)).mean(), (live > 0).mean()
REGISTERED = (0.50, 0.53, 0.02)
if __name__ == "__main__":
    print("share of sessions muted once the model has 50 votes (250 sessions, Poisson(3) votes a session, N 2,000), by true hit rate")
    for mute, unmute, alpha in ((0.47, 0.52, 0.02), (0.50, 0.54, 0.02), (0.51, 0.54, 0.02), (0.50, 0.54, 0.03), REGISTERED):
        row = []
        for a in (0.60, 0.56, 0.53, 0.50, 0.45):
            m, _ = muted_share(a, 3, alpha=alpha, mute=mute, unmute=unmute, N=2000)
            row.append(f"{a:.2f}: {m:.2f}")
        tag = "  <- registered" if (mute, unmute, alpha) == REGISTERED else ""
        print(f"mute < {mute}, unmute >= {unmute}, alpha {alpha} | " + "  ".join(row) + tag)
