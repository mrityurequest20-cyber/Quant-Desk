"""The organization's deterministic core (ops/org.py): the rota files each department's audit on its day and the
probation departments' second audit on Saturday; the scorecard's points set trust; the ledger in the repository is
well-formed and every penalty on it has a lesson."""
import datetime as dt

from quantdesk.ops import org as O

MON = dt.date(2026, 10, 5)


def ev(dept, kind, day="2026-10-04"):
    return {"date": day, "dept": dept, "kind": kind, "what": "x", "ref": "y"}


def test_every_department_is_audited_on_its_own_day():
    days = {MON + dt.timedelta(days=i): O.due(MON + dt.timedelta(days=i), []) for i in range(7)}
    assert [d for x in days.values() for d in x] == ["data", "orders", "research", "risk_compliance", "architecture",
                                                     "internal_audit"]
    assert days[MON + dt.timedelta(days=6)] == []                      # Sunday: the Study runs instead
    assert O.deterministic(dt.date(2026, 10, 4)) == [("warehouse-audit", ""), ("entry-check", ""),
                                                     ("law-audit", "docs/prereg/expiry_eve_law_v2_audit.json")]
    assert O.deterministic(dt.date(2026, 10, 11)) == [("warehouse-audit", ""), ("entry-check", "")]
    assert O.deterministic(MON) == []


def test_points_set_trust_and_probation_means_a_second_audit():
    events = [ev("research", "owner_found"), ev("research", "fixed"), ev("data", "self_found")] + \
             [ev("orders", "self_found")] * 4
    sc = O.scores(events, MON)
    assert sc["research"]["points"] == -3 and sc["research"]["trust"] == "probation"
    assert sc["data"]["trust"] == "standard" and sc["orders"]["points"] == 12 and sc["orders"]["trust"] == "trusted"
    assert O.due(dt.date(2026, 10, 10), events) == ["internal_audit", "research"]
    old = O.scores([ev("research", "owner_found", "2026-07-01")], MON)          # outside the 8-week window
    assert old["research"]["points"] == 0 and old["research"]["trust"] == "standard"
    assert O.self_found_share(events) == round(5 / 6, 4) and O.self_found_share([]) is None


def test_the_audit_issue_is_filed_once_and_flagged_when_overdue():
    class GH:
        def __init__(self):
            self.made, self.comments, self.labels, self.today = {}, [], [], MON

        def ensure_label(self, *a):
            pass

        def create(self, title, body, labels):
            self.made[title] = {"number": len(self.made) + 1, "title": title, "body": body, "labels": labels,
                                "created_at": f"{self.today}T11:50:00Z"}
            return self.made[title]

        def issues(self, label, state="open", since=None):
            return [i for i in self.made.values() if state == "all" or i.get("state", "open") == state]

        def comment(self, n, b):
            self.comments.append(n)

        def add_label(self, n, name):
            self.labels.append((n, name))
            next(i for i in self.made.values() if i["number"] == n)["labels"].append(name)

    gh = GH()
    first = O.sync(gh, MON, [], say=lambda *a: None)
    again = O.sync(gh, MON, [], say=lambda *a: None)
    assert first["created"] == [1] and again["created"] == []
    gh.made[O.title("data", MON)]["state"] = "closed"                  # the shift closed it; a re-run doesn't refile
    assert O.sync(gh, MON, [], say=lambda *a: None)["created"] == []
    gh.made[O.title("data", MON)]["state"] = "open"
    body = gh.made[O.title("data", MON)]["body"]
    assert "data-steward" in body and "warehouse-audit" in body and "no finding" in body
    gh.today = MON + dt.timedelta(days=2)
    late = O.sync(gh, gh.today, [], say=lambda *a: None)
    assert late["overdue"] == [1] and gh.labels == [(1, "overdue")]
    gh.today = MON + dt.timedelta(days=3)
    assert O.sync(gh, gh.today, [], say=lambda *a: None)["overdue"] == []                   # flagged once


def test_the_ledger_is_honest_and_every_penalty_has_a_lesson():
    events = O.load()
    assert events, "docs/org/scorecard.jsonl is the organization's memory; it can't be empty"
    assert O.problems(events, O.LESSONS.read_text()) == []
    assert O.problems([ev("research", "owner_found", "2026-11-01")], "## 2026-10-04: x") == [
        "line 1: a owner_found on 2026-11-01 has no lesson dated on or after it in lessons.md"]
    assert O.problems([ev("sales", "bonus")], "")[:2] == ["line 1: unknown department 'sales'", "line 1: unknown kind 'bonus'"]
    agents = {p.stem for p in (O.ROOT / ".claude" / "agents").glob("*.md")}
    assert {d["agent"] for d in O.DEPTS.values()} | {"chief-of-staff"} <= agents
