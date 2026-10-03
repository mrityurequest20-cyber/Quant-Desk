"""The self-learning paper loop around the DirectionModel (docs/ARCHITECTURE.md).

    ledger.py      every prediction recorded before its outcome is known (append-only, hash-chained), and its outcome
    features.py    versioned causal features, the 30-minute label, bar validation, data fingerprints
    validation.py  day-grouped walk-forward with purge and embargo, the locked final test, block bootstrap
    models.py      candidates (the DirectionModel baseline, regularised logits, boosted stumps), calibration, abstention
    evaluate.py    cost simulation, metrics by session / regime / symbol, confidence intervals, pass/fail gates
    registry.py    champion / challenger registry with an audited event log and rollback
    drift.py       feature, prediction, calibration and performance drift
    cycle.py       the paper-learning cycle: ingest → dataset → train → validate → register → paper → promote
    live.py        the live desk's side: shadow predictions for every registered model, the champion's signal

Paper only. Nothing here places orders, and no language model touches signals, sizing, limits or promotion.
"""
