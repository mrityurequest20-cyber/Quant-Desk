"""The daily Kite-vs-Kotak agreement record (quantdesk/data/agreement.py, agreement.yml, the Data-health check): counts only, a partial day marked, the workflow's isolation."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import yaml

from quantdesk.data import agreement as AG
from quantdesk.data import health as H

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/agreement.yml"
MS = lambda s: int(dt.datetime.fromisoformat(s).replace(tzinfo=AG.IST).timestamp() * 1000)    # noqa: E731


def _day(day="2026-11-09", cycles=4400, both=176000, dis=1760, ob=40000, od=800, worst=3.2):
    return {"day": day, "cycles": cycles, "both": both, "disagree": dis, "opt_both": ob, "opt_disagree": od, "worst_cycle_pct": worst, "first_at": MS(f"{day} 09:00:05"), "last_at": MS(f"{day} 15:35:00"),
            "peak": {"z": {"eq": 180, "opt": 2900, "mcx": 40}, "k": {"eq": 190, "opt": 300}}}


def test_a_relay_day_becomes_one_record_of_counts_and_percentages(tmp_path):
    health = {"agreement": {"today": _day("2026-11-10"), "days": {"2026-11-09": _day("2026-11-09", dis=3520), "2026-11-06": {"day": "bad"}}}, "kotak": {"x": 1}}
    made = AG.build(health, tmp_path)
    assert [m["day"] for m in made] == ["2026-11-09", "2026-11-10"]
    m = json.loads((tmp_path / "2026-11-09" / "agreement.json").read_text())
    assert m["agree_pct"] == 98.0 and m["pairs"] == 176000 and m["opt_agree_pct"] == 98.0 and m["partial"] is False and m["first"] == "09:00:05" and m["last"] == "15:35:00"
    assert not re.search(r"RELIANCE|NIFTY|ltp", json.dumps({k: v for k, v in m.items() if k != "note"}), re.I) and set(m) <= {
        "day", "source", "cycles", "pairs", "disagree", "agree_pct", "opt_pairs", "opt_disagree", "opt_agree_pct", "worst_cycle_pct", "first", "last", "partial", "note", "peak_fresh"}
    assert AG.build({}, tmp_path / "e") == [] and AG.build({"agreement": {"today": None, "days": {}}}, tmp_path / "e") == []
    assert AG.day_manifest(_day(cycles=0)) is None and AG.day_manifest(_day(cycles=50))["partial"] is True and AG.day_manifest(_day(both=0, dis=0, ob=0, od=0))["agree_pct"] is None


class Store:
    def __init__(self, m=None):
        self.m = m

    def tags(self, t): return ["agreement-2026"] if self.m else []
    def assets(self, t): return [f"{self.m['day']}_agreement.json"] if self.m else []
    def read(self, t, n): return json.dumps(self.m).encode()


def test_the_health_check_reports_the_share_and_warns_on_low_agreement_a_partial_day_or_a_missing_record():
    day = dt.date(2026, 11, 9)
    ok = H.check_agreement(Store(AG.day_manifest(_day())), day)
    assert ok.status == H.OK and "99.0%" in ok.detail and "Kite 3,120 names, Kotak 490" in ok.detail
    blind = AG.day_manifest({**_day(), "peak": {"z": {}, "k": {"eq": 190}}})
    assert H.check_agreement(Store(blind), day).status == H.WARN and "blind" in H.check_agreement(Store(blind), day).detail
    assert H.check_agreement(Store(AG.day_manifest(_day(dis=8000))), day).status == H.WARN                       # 95.5%
    assert H.check_agreement(Store(AG.day_manifest(_day(dis=40000))), day).status == H.BAD                       # 77%
    p = H.check_agreement(Store(AG.day_manifest(_day(cycles=40))), day)
    assert p.status == H.WARN and "only 40 cycles" in p.detail
    assert H.check_agreement(Store(AG.day_manifest(_day(both=0, dis=0, ob=0, od=0))), day).status == H.WARN
    assert H.check_agreement(Store(), day).status == H.MISSING
    assert "check_agreement(store, day), \"Kite vs Kotak agreement\"" in (ROOT / "quantdesk/data/health.py").read_text(encoding="utf-8")


def test_the_workflow_reads_with_the_read_key_only_and_publishes_with_no_secret():
    import sys
    sys.path.insert(0, str(ROOT / "deploy"))
    import check_workflows
    text = WF.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    assert check_workflows.check(WF) == [] and wf["permissions"] == {"contents": "read"}
    on = wf.get("on", wf.get(True))
    assert set(on) == {"schedule", "workflow_dispatch"} and on["schedule"] == [{"cron": "50 10 * * 1-5"}]
    assert sorted(set(re.findall(r"secrets\.(\w+)", text))) == ["LIVE_READ_TOKEN"]                                # the read-only relay key, nothing from a broker
    assert not re.search(r"secrets\.(KITE|KOTAK|INGEST)|TOTP|PASSWORD|API_SECRET", text)
    pub = yaml.safe_dump(wf["jobs"]["publish"])
    assert wf["jobs"]["publish"]["permissions"] == {"contents": "write"} and "secrets." not in pub and "LIVE_" not in pub
    assert "permissions" not in wf["jobs"]["read"] and "-L" not in text.split("curl", 1)[1].split("\n", 1)[0] and "--location" not in text         # no redirect followed
    assert "^https://" in text
