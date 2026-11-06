"""What is left of the self-learning paper loop (the loop itself was retired with the paper desk on 6 Nov 2026).

    cli.py         `autolearn vol-har-fit`: the command named in the committed HAR coefficients' provenance
                   (quantdesk/intraday/vol_har_v1.json), kept so that fit can be reproduced
    features.py    versioned causal features, bar validation, data fingerprints
    evaluate.py    cost simulation, metrics and confidence intervals
    prereg.py      the pre-registered intraday direction tests (docs/prereg/intraday_direction_v1.json)
    volstudy.py    the pre-registered move-size study (vol_forecast_v1): the HAR fit comes from it

Paper only. Nothing here places orders, and no language model touches signals, sizing, limits or promotion.
"""
