# D-01 follow-up: do the other record-driven tilts beat a placebo?

Data: `origin/journal` at `9cdfbeb` (learning cycle 2026-10-09). `intraday/memory.json`, `intraday/journal.db` (4,071
headlines, 743 thoughts, **0 trades**), the recorded 1-minute sessions (29 Sep, 5-9 Oct) and the 5-minute research bars
(58 sessions, 20 Jul - 9 Oct). Scripts: `docs/reports/d01_followup/`. No trading behaviour was changed.

| tilt | live? | data it has | beats noise? | recommendation |
|---|---|---|---|---|
| `news_trust` (event x source), and `reader_trust` | yes, every news read | 181 half-hour windows (rules), 16 session x index blocks | **No.** | Move behind the flag |
| `Memory.setup_mult` + stand-aside | yes, but **nothing to apply yet** (0 trades graded) | none | **Cannot be tested on the journal.** Simulated: unsafe | Move behind the flag (costs nothing today) |
| relstrength `preference` | gated by `earned()`; **currently off** | 58 sessions, 3,595 points | **No** (IC -0.034, t -0.83) | Leave live: its gate is already a significance test |

## 1. `news_trust` (and `reader_trust`)

Rebuilt row by row with the repo's own `learning.forward()` and `grade_news` rules (tone threshold 0.15, headlines
sharing a 30-minute window count once between them). The rules reader comes to **181 windows at 55.5% right**;
`memory.json` says 263 at 55.1%, the difference being the bootstrap replay, which graded older headlines on other bars.
Placebo: flip the sign of the forward return by **session x index** (16 blocks), re-learn the whole event x source
table each time, 20,000 flips. Also an exact 256-flip test by session (the two indices share the day's move).

| statistic | observed | placebo median / 95th | p |
|---|---|---|---|
| hit rate, session x index | 55.5% | 49.8% / 55.2% | 0.040 |
| hit rate, session only (exact) | 55.5% | | 0.102 |
| mean log tilt (level) | +0.109 | -0.007 / +0.096 | 0.102 |
| dispersion of the tilt across headlines | 0.096 | 0.078 / 0.139 | **0.284** |
| walk-forward lift (trust learned on earlier sessions, scored on the next) | +7.6 bps | -0.3 / +11.7 | **0.116** (session only: 0.266) |

- **Effective n.** The per-window call has lag-1/2/3 autocorrelation of +0.18/+0.07/+0.12 and NIFTY and BANKNIFTY agree in the
  same window at +0.71. Bartlett-style: **n_eff = 77** of 181 windows (memory's 263 is not independent either).
  z = +0.97 at n_eff; +1.65 even at 263.
- **What noise does.** In 53% of sign-flipped worlds the record moves some headline's trust beyond 0.8x-1.25x. The
  live record's spread (43% of graded headlines outside 0.9-1.1x, top pair Times of India x general = 1.43x) is what noise
  produces: dispersion p = 0.28.
- The hit-rate p = 0.04 is the single nominal pass; it goes to 0.10 once the two indices are treated as one market, and
  it is one of five looks. The tilt that actually moves conviction (the dispersion, and what a walk-forward user would have
  earned) is not distinguishable from noise.
- `reader_trust`: rules 55.5% (x1.10), gemini 56.5% (x1.10) on 84 windows, ollama 51.9% (x1.03) on 103. Same wiring
  (`engine._apply_memory`), same weakness; these are 0.98x-1.12x so the effect is small.

**Verdict: not distinguishable from noise. Move `news_trust` and `reader_trust` behind the flag.**

## 2. `setup_mult` and the stand-aside rule

`memory.json` has no `setup` table and `journal.db` has no trades: the journal has never closed one, so `setup_mult` returns
(1.0, None) for everything today. There is nothing to measure, so this is a **simulation of what the rule does to a setup
whose true edge is known**, using `learning.Memory` itself. Stand-aside is absorbing here (a stood-aside setup takes no
more trades, so its record cannot recover).

P(stood aside for good) by true edge, with R as the desk's own recorded plan outcomes (net R, zero-meaned; sd 0.67) vs a
1:2 bracket (-1R / +2R, like the playbook's rr 1.5-2.0 targets):

| true edge | plan-R, 20 / 50 / 100 trades | bracket, 20 / 50 / 100 trades |
|---|---|---|
| -0.3R | 32% / 55% / 70% | 56% / 73% / 81% |
| 0.0R | 0.3% / 0.7% / 0.6% | **27% / 33% / 34%** |
| +0.1R | 0.1% | 20% / 23% / 24% |
| +0.3R | 0% | 10% / 11% / 11% |

- With bracket-shaped R, a **break-even setup is permanently stood aside a third of the time, and a +0.3R setup 1 time in 9.**
  The shrink prior (8 pseudo-trades at 0R) is tiny against -1R losses. The tilt itself, for a break-even setup after 20
  trades: x0.91-x1.23 (90% band), outside +-10% in 29% of draws.
- Across the 25 setup x day-type cells the rule checks separately, a break-even bracket desk stands aside at least one in
  100% of draws (11% even with plan-shaped R).
- Caveat: this is a model, not a measurement. Real trade R has stop, target, time and EOD exits, so the truth sits
  between the two columns. The point is that the rule's false-positive rate depends on R's shape and is nowhere tested.

**Verdict: untested, and unsafe when R is bracket-shaped. Move behind the flag now; it costs nothing (no record) and stops a
permanent, unrecoverable stand-aside being triggered by noise on the first live trades.**

## 3. relstrength `preference`

Persistence of the BANKNIFTY/NIFTY ratio's last-30-minute move into the next 30, every 5-minute mark of all 58 sessions
(the live record holds only 9, W = 94.5, IC +0.011, t +0.10, so `earned()` is False and the preference is off).

- IC **-0.034**, t -0.83 on the record's formula (W = 599). Autocorrelation of x is +0.82/+0.65/+0.48/+0.31 at lags 1-4, so
  Bartlett n_eff = 788 vs the record's n/6 = 599: the record's overlap discount is about right, if anything cautious.
  Session-level: positive in 38% of 58 sessions, t -0.95.
- Placebo, sign-flip by session: p(one-sided) = 0.825. Block permutation of sessions at the same clock times: 0.848.
- Where the preference would act (|z30| >= 1, 889 points): going with the leader returns -0.51 bps, right 45.8%; p = 0.83.
- Does noise switch it on? Checking the running record after every session, **3%** of placebo paths cross `earned()`
  somewhere in 58 sessions (a single look is 2.3%). The gate is a real one-sided t >= 2 test with n >= 30, and the data
  does not pass it (the running t over 56 session closes ranged -1.61 to +0.17).

**Verdict: does not beat noise, but the gate already keeps it off and is close to its nominal false-positive rate. Leave it
live, no flag.** If the owner wants symmetry anyway, it is a one-line gate, but it would change nothing today.
Data note: 29 Sep and 5-9 Oct use the recorded 1-minute bars, every other day the 5-minute research bars (both read on the same 5-minute marks).

## Recommendation

1. Move `news_trust` and `reader_trust` behind the flag (what the record does is displayed, not applied). This is the only
   one of the three changing live conviction today.
2. Move `setup_mult`'s multiplier and stand-aside behind the flag too, or at least the stand-aside. Zero effect on
   today's behaviour; protects against the first handful of live trades.
3. Leave the relstrength preference as it is.

All three need the owner's sign-off; this PR changes docs and the config comment only.
