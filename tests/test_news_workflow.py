"""The news digest workflow (.github/workflows/news.yml): public feeds in, the relay's ingest key in one step, nothing written to the repository, no broker."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = (ROOT / ".github" / "workflows" / "news.yml").read_text(encoding="utf-8")
WF = yaml.safe_load(RAW)


def test_it_can_only_read_the_repository_and_holds_one_secret_in_one_step():
    assert WF["permissions"] == {"contents": "read"} and "permissions" not in WF["jobs"]["digest"]
    holders = [s for s in WF["jobs"]["digest"]["steps"] if "secrets." in yaml.safe_dump(s)]
    assert len(holders) == 1 and set(holders[0]["env"]) == {"LIVE_URL", "LIVE_INGEST_TOKEN"} and holders[0]["run"] == "python -m quantdesk news --push"
    assert RAW.count("secrets.") == 1 and "secrets.LIVE_INGEST_TOKEN" in RAW and "LIVE_READ_TOKEN" not in RAW                  # the ingest key only: it cannot read the board or the paper account
    assert not any("secrets." in str(v) for v in WF["env"].values())
    for s in WF["jobs"]["digest"]["steps"]:
        if str(s.get("uses", "")).startswith("actions/checkout"):
            assert s["with"]["persist-credentials"] is False


def test_no_broker_no_order_no_push_and_no_cron_of_its_own():
    assert not re.search(r"KITE_|KOTAK_|ZERODHA|API_SECRET|TOTP|PASSWORD|place_order|git push|--force|contents: write", RAW, re.I)
    assert "schedule" not in WF[True] and list(WF[True]) == ["workflow_dispatch"]                                                # started by deploy/scheduler.py or by hand
    assert WF["concurrency"] == {"group": "news-digest", "cancel-in-progress": False} and WF["jobs"]["digest"]["timeout-minutes"] <= 10
