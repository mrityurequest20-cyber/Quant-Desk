import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantdesk.config import DEFAULT_CONFIG, Config  # noqa: E402
from quantdesk.data.synthetic import SyntheticProvider  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    # the shipped default is require_approved_model: false (owner decision, #36); these tests were written for the gated
    # desk, so they pin it. tests of the open path set it false themselves.
    return Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp_path / "runtime")},
                                                  "autolearn": {"require_approved_model": True}})


@pytest.fixture(scope="session")
def market():
    """A seeded synthetic universe (~6 years), simulated once per test session."""
    c = Config.load(DEFAULT_CONFIG)
    prov = SyntheticProvider(c, start="2019-01-01", end="2024-12-31", seed=1)
    return prov, prov.universe(c.all_symbols(), "2019-01-01")


@pytest.fixture(scope="session")
def aux(market):
    from quantdesk.engine.engine import Engine
    return Engine.build_aux(Config.load(DEFAULT_CONFIG), market[1])
