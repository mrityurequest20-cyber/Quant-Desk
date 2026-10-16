"""The README's intraday risk numbers and its account of the plan-model gate must say what the config does (P1-7:
they still said 1% / 6 trades / -2.5% and "no directional trade without a plan model" after both had changed)."""
import re
from pathlib import Path

from quantdesk.config import DEFAULT_CONFIG, Config

README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")


def _line(prefix: str) -> str:
    hits = [l for l in README.splitlines() if l.strip().startswith(prefix)]
    assert len(hits) == 1, f"expected one README line starting {prefix!r}, found {len(hits)}"
    return hits[0]


def test_readme_risk_numbers_equal_the_config():
    r = Config.load(DEFAULT_CONFIG).get("intraday.risk")
    sizing, limits = _line("- **Sizing:**"), _line("- **Daily limits:**")
    assert re.search(r"(\d+(?:\.\d+)?)% of capital at risk", sizing).group(1) == f"{r['risk_per_trade'] * 100:g}"
    assert re.search(r"(\d+) trades a day", limits).group(1) == str(r["max_trades_per_day"])
    assert re.search(r"(\d+) open", limits).group(1) == str(r["max_open"])
    assert re.search(r"−(\d+(?:\.\d+)?)% daily stop", limits).group(1) == f"{r['daily_loss_limit'] * 100:g}"
    assert re.search(r"cooldown after (\d+) losses", limits).group(1) == str(r["cooldown_after_losses"])
    assert re.search(r"at most (\d+)% of equity", limits).group(1) == f"{r['max_total_outlay'] * 100:g}"


def test_readme_states_the_plan_model_gate_as_configured():
    on = bool(Config.load(DEFAULT_CONFIG).get("autolearn.require_approved_model", True))
    claims_off = "not gated on an approved plan model right now" in README
    assert claims_off != on, "README's plan-model gate sentence disagrees with autolearn.require_approved_model"
