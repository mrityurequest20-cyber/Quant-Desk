"""The History tab starts clean (owner, 7 Nov 2026): `app.history_since` limits what the published app shows, and nothing in the journal is edited or deleted.
With nothing in the window the app shows the account at its capital (₹5,00,000), no profit or loss and no trades."""
from __future__ import annotations

import json

from quantdesk.journal.journal import Journal
from quantdesk.web.intraday_api import IntradayAPI

DAYS = ["2026-10-12", "2026-11-05", "2026-11-06", "2026-11-09"]


def seeded(cfg):
    base = cfg.runtime_dir / "intraday"
    base.mkdir(parents=True, exist_ok=True)
    j = Journal(base / "journal.db")
    j.set_state("intraday_account", {"capital": 500000.0, "since": "2026-10-04"})
    for i, day in enumerate(DAYS):
        j._exec("INSERT INTO trades (id, symbol, direction, strategy, status, pnl, fees, r_multiple, grade, exit_reason, opened_at, closed_at, meta, context) "
                "VALUES (?, 'NIFTY', 1, 'orb', 'closed', ?, 10.0, 0.5, 'B', 'target', ?, ?, '{}', '{}')",
                (f"t{i}", 1000.0 * (i + 1), day + " 10:00:00+05:30", day + " 11:00:00+05:30"))
    j.commit()
    reviews = base / "reviews"
    reviews.mkdir(exist_ok=True)
    for day in DAYS:
        (reviews / f"{day}.md").write_text("# review " + day)
    return j


def test_the_window_limits_trades_reviews_and_every_figure_but_the_journal_keeps_everything(cfg):
    j = seeded(cfg)
    api = IntradayAPI(cfg)
    assert len(api.trades(None, 100)) == 4 and len(api.reviews(None)) == 4 and api.stats(None)["trades"] == 4              # no window: as before
    assert [t["opened_at"][:10] for t in api.trades(None, 100, "2026-11-06")] == ["2026-11-09", "2026-11-06"]
    assert api.reviews(None, "2026-11-06") == ["2026-11-09", "2026-11-06"]
    s = api.stats(None, "2026-11-06")
    assert s["trades"] == 2 and s["net"] == 3000.0 + 4000.0 and [e["day"] for e in s["equity"]] == ["2026-11-06", "2026-11-09"]
    assert s["equity"][0]["equity"] == 500000.0 + 3000.0                                                                     # the equity line starts from the capital, not from the hidden trades
    assert int(j.df("SELECT COUNT(*) AS n FROM trades")["n"].iloc[0]) == 4                                                  # nothing was deleted


def test_a_window_with_no_trades_in_it_shows_the_capital_and_nothing_else(cfg):
    seeded(cfg)
    api = IntradayAPI(cfg)
    assert api.trades(None, 100, "2026-11-10") == [] and api.reviews(None, "2026-11-10") == []
    assert api.stats(None, "2026-11-10") == {"trades": 0, "capital": 500000.0}


def test_the_shipped_config_starts_the_history_clean_at_five_lakh_and_the_site_publishes_nothing_older(cfg, tmp_path):
    from quantdesk.web.export_site import site_data
    assert cfg.get("app.history_since") == "2026-11-07" and cfg.get("intraday.capital") == 500000
    seeded(cfg)
    data = site_data(cfg, "live", live=True)
    assert data["history_since"] == "2026-11-07"
    assert [t["opened_at"][:10] for t in data["trades"]] == ["2026-11-09"]                  # only what is after the cut: the seeded 9 Nov trade stands in for a trade after the restart
    assert set(data["reviews"]) == {"2026-11-09"} and data["stats"]["trades"] == 1
    assert all(k in ("t3",) for k in data["trade"]) and "t0" not in data["trade"] and "t2" not in data["trade"]
    cfg.data["app"]["history_since"] = "2026-12-01"
    empty = site_data(cfg, "live", live=True)
    assert empty["trades"] == [] and empty["trade"] == {} and empty["reviews"] == {} and empty["stats"] == {"trades": 0, "capital": 500000.0}


def test_the_app_shows_the_account_flat_when_the_window_is_empty():
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "quantdesk/web/static/app/app.js").read_text()
    assert "function flatAccount(capital)" in app and 'kpi("Account", inr(capital))' in app and 'kpi("Net P&L", inr(0))' in app and 'kpi("Trades", "0")' in app
    assert app.count("flatAccount(") == 3                                                    # defined once, used by History and by Performance
