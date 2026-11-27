"""MarketLens: a read-only market analysis app for Indian index and stock derivatives.

It turns the public NSE/BSE end-of-day record (F&O bhavcopy, official index closes, participant-wise open interest,
FII/DII cash flows, the corporate event calendar) into analysis a derivatives trader reads before deciding: volatility
(implied, realised, the premium between them, term structure, skew), the move the options market prices and how often
that was right, positioning (strike open interest, futures build-up, rollover, participant books), flows and events.

It never tells anyone to buy or sell. Every number is shown against its own history, with the date its history starts,
and with a plain-language reading next to the analyst's one.

    python -m marketlens build --warehouse DIR --out DIR      build the site's data from a warehouse folder
    python -m marketlens fetch --dest DIR                     download the public warehouse tables
"""

__version__ = "0.1.0"
