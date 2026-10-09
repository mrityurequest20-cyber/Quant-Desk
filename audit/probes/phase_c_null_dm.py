"""How often does the session DirectionModel 'validate' on a pure random walk? (read-only; synthetic data)"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import pandas as pd  # noqa: E402
from test_autolearn import market, sessions  # noqa: E402

from quantdesk.intraday.quant import DirectionModel, features_5m, to_5m  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
res = []
for seed in range(N):
    days = sessions(52, start="2026-07-20")
    f = features_5m(to_5m(market(days, phi=0.0, seed=seed)))
    m = DirectionModel()
    d = m.fit(f)
    res.append((m.valid, d.get("auc_oos"), d.get("logloss_skill_oos")))
r = pd.DataFrame(res, columns=["valid", "auc", "skill"])
p = r["valid"].mean()
print(f"fits {len(r)}  false-validation rate {p:.4f}  AUC>=0.53 {(r['auc'] >= 0.53).mean():.3f}  "
      f"sd(AUC) {r['auc'].std():.4f}  skill>0 {(r['skill'] > 0).mean():.3f}")
print(f"P(>=1 false validation in 40 independent fits) ~ {1 - (1 - p) ** 40:.3f}")
