"""Phase K: a synthetic session in which the engine takes and closes a trade by its own path (setup → gates → open →
manage → close), for the trade-detail screen. Production has 0 trades, and the approved-plan-model gate blocks every
directional entry (B-02), so the scratch config sets autolearn.require_approved_model = false (documented
substitution; the production config is not touched). Everything else is the engine's own behaviour.

    python audit/probes/phase_k_trade_fixture.py OUT_SITE_DIR > out.json
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import phase_h_det_tests as H  # noqa: E402
from quantdesk.config import Config, DEFAULT_CONFIG  # noqa: E402
from quantdesk.intraday.engine import IntradayEngine, run_replay  # noqa: E402
from quantdesk.intraday.feeds import ReplayFeed  # noqa: E402
from quantdesk.intraday.sim import IntradayBroker  # noqa: E402
from quantdesk.journal.journal import Journal  # noqa: E402
from quantdesk.web.export_site import publish_site  # noqa: E402


def main(out: Path):
    bars, days = H.world()
    tmp = Path(tempfile.mkdtemp(prefix="k-trade-"))
    over = {"runtime": {"dir": str(tmp / "rt")}, "autolearn": {"require_approved_model": False}}
    cfg = Config.load(DEFAULT_CONFIG, overrides=over)
    acct = tmp / "rt" / "intraday"
    acct.mkdir(parents=True)
    j = Journal(acct / "journal.db", autocommit_every=1)
    j.set_state("intraday_account", {"capital": float(cfg.get("intraday.capital")), "since": str(days[0])})
    broker = IntradayBroker(cfg, starting_cash=float(cfg.get("intraday.capital")), state_path=acct / "broker.json")
    taken = []
    for d in days[-12:]:
        eng = IntradayEngine(cfg, ReplayFeed(bars, d), "model", j, broker, None, None, None, acct / "reviews")
        run_replay(eng)
        taken += [(str(d), t.id, t.strategy, t.exit_reason, round(t.pnl, 0)) for t in eng.closed]
        if taken:
            break
    j.commit()
    publish_site(cfg, "live", out)
    tr = j.df("SELECT id, strategy, symbol, opened_at, closed_at, pnl, r_multiple, grade, exit_reason, rationale, meta, context "
              "FROM trades").to_dict("records")
    dec = j.df("SELECT ts, strategy, symbol, action, detail FROM decisions").to_dict("records")
    fills = j.df("SELECT ts, trade_id, symbol, qty, price, fees FROM fills").to_dict("records")
    print(json.dumps({"journal": str(acct / "journal.db"), "trades_taken": taken, "trades": tr, "decision_rows": dec[-6:],
                      "fills": fills}, indent=1, default=str))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
