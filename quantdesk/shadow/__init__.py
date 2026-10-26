"""Shadow setup replay: offline, additive, read-only. Finds the desk's own setups on every instrument and labels what
would have happened, for later ML (the M4 entry filter). It never trades, sizes, or changes a ceiling; it imports the
desk's detectors (quantdesk/intraday/analyst.py, features.py, playbook.py) and calls them unmodified."""
