"""Claude as a teacher (quantdesk/intraday/teacher.py): fakes only, no network, no key. After the close and never before;
the output is JSON with a schema and anything malformed is dropped with a WARN; lessons are advisory text that cannot
touch configuration, risk, sizing or gates; and they are stored where the journal save and retention keep them."""
import ast
import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace as NS

import pandas as pd
import pytest
import yaml

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.intraday import learning, llm, teacher
from quantdesk.journal import retention
from quantdesk.journal.journal import Journal

ROOT = Path(__file__).resolve().parents[1]
IST = "Asia/Kolkata"
DAY = "2026-10-16"
AFTER = pd.Timestamp(f"{DAY} 16:10", tz=IST)          # the post-close job
DURING = pd.Timestamp(f"{DAY} 11:00", tz=IST)         # the minute loop
CFG = Config.load(DEFAULT_CONFIG)


class FakeAnthropic:
    """The SDK's beta.messages.create, recorded; never touches the network."""
    def __init__(self, reply=None, stop="end_turn", usage=None):
        self.calls, self.reply, self.stop = [], reply, stop
        self.usage = usage or NS(input_tokens=6000, output_tokens=1500)
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        return NS(stop_reason=self.stop, usage=self.usage,
                  content=[NS(type="text", text=self.reply)] if self.stop != "refusal" and self.reply is not None else [])


def lesson(**kw):
    base = {"kind": "wrong", "claim": "The entry ignored the 10:40 reversal", "why": "the read stayed bullish after the break",
            "evidence": ["trade:T1", "thought:2"], "confidence": 0.4, "uncertainty": "one session, one regime",
            "suggests_change": False, "hypothesis": "", "confirm_if": "", "refute_if": ""}
    return {**base, **kw}


def reply(*lessons, summary="a thin day"):
    return json.dumps({"summary": summary, "lessons": list(lessons)})


@pytest.fixture
def journal():
    j = Journal()
    j._exec("INSERT INTO trades (id, strategy, family, symbol, direction, kind, units, opened_at, closed_at, pnl, r_multiple, "
            "exit_reason, exit_note, status, rationale, grade, review) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("T1", "orb", "intraday", "NIFTY", 1, "option", 2, f"{DAY} 10:05:00", f"{DAY} 11:30:00", -1200.0, -0.8, "stop",
             "premium stop", "closed", "opening-range break with flow", "C", "followed the read"))
    for i, (ts, bias) in enumerate([("09:30", "bullish"), ("10:05", "bullish"), ("10:40", "bearish")], 1):
        j._exec("INSERT INTO thoughts (ts, symbol, bias, score, conviction, day_type, action, narrative) VALUES (?,?,?,?,?,?,?,?)",
                (f"{DAY} {ts}:00", "NIFTY", bias, 0.4, 0.5, "trend", "watching: no setup", "narrative"))
    j.decision(f"{DAY} 10:06:00", "orb", "NIFTY", "rejected", "outlay above max_total_outlay")
    j.event(f"{DAY} 12:00:00", "WARN", "data", "stale chain")
    j.commit()
    return j


def ids_of(j):
    return sorted(teacher.build_packet(j, DAY)[1])


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for names in llm.KEY_NAMES.values():
        for n in names:
            monkeypatch.delenv(n, raising=False)


def reader_for(fake):
    return llm.ClaudeReader("k", client=fake)


def events(j, level=None):
    ev = j.events()
    ev = ev[ev["category"] == "teaching"]
    return ev if level is None else ev[ev["level"] == level]


# ---- the lessons -------------------------------------------------------------------------------------------------------
def test_a_taught_session_stores_labelled_advisory_lessons_citing_journal_rows(journal):
    ids = ids_of(journal)
    assert "trade:T1" in ids and any(i.startswith("decision:") for i in ids) and any(i.startswith("event:") for i in ids)
    dec = next(i for i in ids if i.startswith("decision:"))
    fake = FakeAnthropic(reply(lesson(evidence=["trade:T1", dec, "trade:nonsense"]),
                               lesson(claim="uncited", evidence=["trade:ghost"]), "not a lesson",
                               lesson(kind="right", claim="Stood aside on the stale chain", evidence=["event:1"], confidence=0.7,
                                      hypothesis="Standing aside on a stale chain saves R", confirm_if="stale-chain minutes lose on average",
                                      refute_if="they do not", suggests_change=True)))
    mem = learning.Memory()
    got = teacher.teach(CFG, journal, DAY, mem, reader=reader_for(fake), now=AFTER)
    assert got["status"] == "taught" and got["lessons"] == 2 and got["dropped"] == 2
    rec = journal.get_state("teacher:" + DAY)
    assert rec["advisory"] is True and rec["note"].startswith("ADVISORY ONLY") and rec["day"] == DAY
    first, second = rec["lessons"]
    assert first["evidence"] == ["trade:T1", dec] and first["status"] == "advisory" and first["uncertainty"]
    assert second["study_candidate"] is True and second["proposes_change"] is True       # a hypothesis, how to settle it
    assert [h["id"] for h in teacher.hypotheses(journal)] == [second["id"]]
    assert mem.d["teaching"][-1]["day"] == DAY                                             # mirrored in the learning memory
    assert any("partly malformed" in m for m in events(journal, "WARN")["message"])        # the dropped ones, said aloud
    # the request: JSON with a schema, a prompt that asks for citations and marks uncertainty, the teaching call only
    kw = fake.calls[0]
    assert kw["output_config"]["format"]["type"] == "json_schema" and kw["output_config"]["format"]["schema"] is teacher.LESSON_SCHEMA
    assert "cites the journal rows" in kw["system"] and "uncertainty" in kw["system"] and "trade:T1" in kw["messages"][0]["content"]
    st = journal.get_state(llm.BUDGET_KEY)
    assert st["teach_usd"] > 0 and st["by_day"] == {} and st["calls"] == 1                # teaching's half, not the reads'


def test_a_hypothesis_needs_a_way_to_settle_it_and_a_change_needs_a_hypothesis(journal):
    fake = FakeAnthropic(reply(lesson(suggests_change=True),                                         # a change with nothing to test
                               lesson(hypothesis="h", confirm_if="c"),                               # no refutation
                               lesson(hypothesis="h", confirm_if="c", refute_if="r")))
    teacher.teach(CFG, journal, DAY, reader=reader_for(fake), now=AFTER)
    a, b, c = journal.get_state("teacher:" + DAY)["lessons"]
    assert (a["study_candidate"], a["proposes_change"]) == (False, False)
    assert (b["study_candidate"], b["proposes_change"]) == (False, False)
    assert (c["study_candidate"], c["proposes_change"]) == (True, False)


def test_the_next_reflection_can_read_them_labelled_and_a_rebuild_keeps_them(journal):
    teacher.teach(CFG, journal, DAY, reader=reader_for(FakeAnthropic(reply(lesson()))), now=AFTER)
    lines = teacher.advisory_lines(journal)
    assert lines and all(l.startswith("[ADVISORY, unverified]") for l in lines)
    mem = learning.Memory()
    mem.d["teaching"] = [{"day": DAY}]
    learning.rebuild(mem, journal, {})
    assert mem.d["teaching"] == [{"day": DAY}]


# ---- post-close only ----------------------------------------------------------------------------------------------------
def test_teaching_refuses_during_the_session_and_runs_once_it_is_over(journal):
    fake = FakeAnthropic(reply(lesson()))
    got = teacher.teach(CFG, journal, DAY, reader=reader_for(fake), now=DURING)
    assert got["status"] == "skipped" and "not over" in got["why"] and fake.calls == []
    assert journal.get_state("teacher:" + DAY) is None
    assert teacher.teach(CFG, journal, DAY, reader=reader_for(fake), now=pd.Timestamp(f"{DAY} 15:29", tz=IST))["status"] == "skipped"
    assert teacher.teach(CFG, journal, "2026-10-17", reader=reader_for(fake), now=AFTER)["status"] == "skipped"   # a future day
    assert teacher.teach(CFG, journal, DAY, reader=reader_for(fake), now=pd.Timestamp(f"{DAY} 15:30", tz=IST))["status"] == "taught"
    assert len(fake.calls) == 1
    assert teacher.teach(CFG, journal, DAY, reader=reader_for(fake), now=AFTER)["status"] == "skipped"       # once a session
    assert len(fake.calls) == 1
    assert all(e == "INFO" for e in events(journal)[events(journal)["message"].str.contains("skipped")]["level"])


def test_the_minute_loop_never_reaches_the_teacher():
    for f in ("engine.py", "brain.py", "analyst.py", "playbook.py", "risk.py", "governor.py", "sim.py", "news.py"):
        src = (ROOT / "quantdesk" / "intraday" / f).read_text(encoding="utf-8")
        assert "teacher.teach" not in src and "import teach" not in src, f
    eng = (ROOT / "quantdesk" / "intraday" / "engine.py").read_text(encoding="utf-8")
    assert eng.count("teacher import") == 1 and "from .teacher import advisory_lines" in eng      # the read-only lines only


def test_a_session_with_nothing_journaled_or_no_key_is_skipped_without_a_call(journal):
    assert teacher.teach(CFG, Journal(), None, reader=reader_for(FakeAnthropic(reply())), now=AFTER)["status"] == "skipped"
    got = teacher.teach(CFG, journal, DAY, now=AFTER)                         # no reader, no key in this environment
    assert got["status"] == "skipped" and "no Claude key" in got["why"]
    assert journal.get_state(llm.BUDGET_KEY) is None


# ---- malformed output ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["not json at all", "[]", '{"summary": "x"}', '{"summary": "x", "lessons": "none"}',
                                 reply(lesson(evidence=["trade:ghost"])), reply(lesson(confidence=7), lesson(kind="amazing")),
                                 reply({"claim": "no other fields"}), None])
def test_malformed_output_is_dropped_with_a_warn_and_stores_nothing(journal, bad):
    fake = FakeAnthropic(bad)
    got = teacher.teach(CFG, journal, DAY, reader=reader_for(fake), now=AFTER)
    assert got["status"] == "dropped"
    assert journal.get_state("teacher:" + DAY) is None and teacher.recent_lessons(journal) == []
    assert events(journal, "WARN")["message"].str.contains("malformed, dropped").any()
    assert journal.get_state(llm.BUDGET_KEY)["teach_usd"] > 0                  # the call was paid for; the spend is on the ledger


def test_a_refusal_and_a_failing_client_are_events_not_errors(journal):
    assert teacher.teach(CFG, journal, DAY, reader=reader_for(FakeAnthropic(stop="refusal")), now=AFTER)["status"] == "dropped"

    class Boom:
        beta = NS(messages=NS(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("503 overloaded"))))
    got = teacher.teach(CFG, journal, DAY, reader=reader_for(Boom()), now=AFTER)
    assert got["status"] == "failed" and "teaching call errored (RuntimeError" in events(journal, "WARN")["message"].iloc[-1]
    assert "failed" not in events(journal, "WARN")["message"].iloc[-1]       # selfreview.py files an issue for any WARN with "failed"
    assert teacher.recent_lessons(journal) == []


def test_a_thin_session_with_no_lessons_but_a_summary_is_kept(journal):
    got = teacher.teach(CFG, journal, DAY, reader=reader_for(FakeAnthropic(reply(summary="too thin to teach"))), now=AFTER)
    assert got["status"] == "taught" and journal.get_state("teacher:" + DAY)["summary"] == "too thin to teach"


# ---- the budget -----------------------------------------------------------------------------------------------------------
def spend(j, kind, usd, day=DAY):
    b = llm.ClaudeBudget(CFG, j, lambda: pd.Timestamp(f"{day} 16:00", tz=IST))
    b.deny(kind)
    b.charge(NS(input_tokens=0, output_tokens=int(usd / 20 * 1e6)), kind)


def test_a_spent_teaching_half_skips_teaching_with_an_info_event_and_leaves_the_reads_alone(journal):
    pot = CFG.get("intraday.llm.claude.budget_usd") * CFG.get("intraday.llm.claude.teach_share")
    spend(journal, "teach", pot)
    fake = FakeAnthropic(reply(lesson()))
    got = teacher.teach(CFG, journal, DAY, reader=reader_for(fake), now=AFTER)
    assert got["status"] == "skipped" and fake.calls == []
    assert events(journal, "INFO")["message"].str.contains("teaching skipped: teaching pot").any()
    assert not (events(journal)["level"].isin(["WARN", "ERROR", "CRITICAL"])).any()
    b = llm.ClaudeBudget(CFG, journal, lambda: AFTER)
    assert b.deny("read") is None                                              # the reads' half is untouched


def test_a_spent_reads_half_does_not_stop_teaching_and_teaching_never_eats_into_it(journal):
    total = CFG.get("intraday.llm.claude.budget_usd")
    spend(journal, "read", total / 2)
    b = llm.ClaudeBudget(CFG, journal, lambda: AFTER)
    assert "reads budget" in b.deny("read")
    fake = FakeAnthropic(reply(lesson()))
    assert teacher.teach(CFG, journal, DAY, reader=reader_for(fake), now=AFTER)["status"] == "taught"
    st = journal.get_state(llm.BUDGET_KEY)
    assert st["total_usd"] <= total + 1e-9 and st["teach_usd"] < total / 2     # one call, from its own half
    live, teach = b._pots(b._load(), DAY)
    assert live == pytest.approx(0.0, abs=1e-6) and teach == pytest.approx(total / 2 - st["teach_usd"])


def test_a_ledger_with_no_teaching_half_means_no_teaching(journal):
    cfg = CFG.with_overrides({"intraday": {"llm": {"claude": {"teach_share": 0}}}})
    fake = FakeAnthropic(reply(lesson()))
    got = teacher.teach(cfg, journal, DAY, reader=reader_for(fake), now=AFTER)
    assert got["status"] == "skipped" and "no teaching half" in got["why"] and fake.calls == []
    off = CFG.with_overrides({"intraday": {"llm": {"claude": {"teach": False}}}})
    assert teacher.teach(off, journal, DAY, reader=reader_for(fake), now=AFTER)["status"] == "skipped" and fake.calls == []


def test_the_total_budget_is_unchanged_by_the_split():
    assert CFG.get("intraday.llm.claude.budget_usd") == 20.0 and CFG.get("intraday.llm.claude.teach_share") == 0.5


# ---- advisory only: nothing here can reach config, risk, sizing or gates --------------------------------------------------
def test_a_lesson_that_asks_for_looser_limits_changes_nothing_but_the_journal(journal):
    cfg = Config.load(DEFAULT_CONFIG)
    before = copy.deepcopy(cfg.data)
    raw = DEFAULT_CONFIG.read_bytes()
    nasty = lesson(claim="Raise risk_per_trade to 0.10 and max_open to 5", why="more size would have paid",
                   suggests_change=True, hypothesis="Larger size earns more", confirm_if="R rises", refute_if="drawdown rises")
    teacher.teach(cfg, journal, DAY, reader=reader_for(FakeAnthropic(reply(nasty))), now=AFTER)
    assert cfg.data == before and DEFAULT_CONFIG.read_bytes() == raw
    r = cfg.get("intraday.risk")
    assert (r["risk_per_trade"], r["max_trades_per_day"], r["max_open"], r["daily_loss_limit"], r["max_total_outlay"]) == \
        (0.025, 4, 2, 0.05, 0.5)
    assert cfg.get("account.mode") == "paper"
    rec = journal.get_state("teacher:" + DAY)                                  # it is only text, labelled and unapplied
    assert rec["advisory"] is True and rec["lessons"][0]["proposes_change"] is True
    assert rec["lessons"][0]["status"] == "advisory"
    assert not list((ROOT / "docs" / "prereg").glob("*teach*"))               # and it registered no study


ALLOWED_IMPORTS = {"__future__", "pandas", "json", "re", "datetime", "logging", "math", "typing", ".llm", ".learning", ".feeds"}


def test_the_teacher_imports_only_an_allow_list_with_no_risk_sizing_gate_broker_or_config_code():
    src = (ROOT / "quantdesk" / "intraday" / "teacher.py").read_text(encoding="utf-8")
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            base = "." * n.level + (n.module or "")
            mods |= {base} if n.module else {base + a.name for a in n.names}
    assert mods <= ALLOWED_IMPORTS, sorted(mods - ALLOWED_IMPORTS)
    assert "yaml" not in src and "open(" not in src and "write_text" not in src          # no file or config writes


def test_unledgered_spend_is_a_warn_not_silent(journal):
    class Unledgered(llm.ClaudeReader):
        def _call(self, *a, **kw):
            text = super()._call(*a, **kw)
            self.charge_error = "spend not ledgered (OSError: disk)"
            return text
    got = teacher.teach(CFG, journal, DAY, reader=Unledgered("k", client=FakeAnthropic(reply(lesson()))), now=AFTER)
    assert got["status"] == "taught"
    assert events(journal, "WARN")["message"].str.contains("spend not ledgered").any()


def test_the_save_guard_accepts_an_older_snapshot_without_teacher_rows_and_refuses_losing_them(journal, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("journal_counts", ROOT / "deploy" / "journal_counts.py")
    jc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jc)
    path = tmp_path / "journal.db"
    disk = sqlite3.connect(path)
    journal.db.backup(disk)
    disk.close()
    old = {k: v for k, v in jc.figures(str(path)).items() if k != "teacher_sessions"}      # a snapshot from before the teacher
    snap = tmp_path / "old.json"
    snap.write_text(json.dumps(old))
    teacher.teach(CFG, journal, DAY, reader=reader_for(FakeAnthropic(reply(lesson()))), now=AFTER)
    journal.db.backup(sqlite3.connect(path))
    assert jc.figures(str(path))["teacher_sessions"] == 1
    assert jc.main(["x", str(path), "--not-below", str(snap)]) == 0                         # more than the old snapshot had: fine
    now = tmp_path / "now.json"
    now.write_text(json.dumps(jc.figures(str(path))))
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM state WHERE key LIKE 'teacher:%'")
    assert jc.main(["x", str(path), "--not-below", str(now)]) == 1                          # losing teacher rows is refused


# live.yml's workflow env and the secrets it references, as on main aad8470 (before this feature); autolearn.yml's bytes
LIVE_ENV_BEFORE = ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "HANDOVER", "KOTAK_CONSUMER_KEY", "OLLAMA_API_KEY",
                   "PUBLISH_EVERY_MIN", "PYTHONUNBUFFERED", "TZ"]
LIVE_SECRETS_BEFORE = "af319594fcfa48a73a25baaf691d86b5c6c08f7d3198dc9c0982cd242d3a91e7"
AUTOLEARN_BEFORE = "ad6e01c7f52cc5808c1313b71087bfc05af508b7b20e9106a266d9c05d26786d"


def test_the_workflow_step_is_in_the_live_afternoon_job_before_the_save_and_widens_nothing():
    import re
    text = (ROOT / ".github" / "workflows" / "live.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    steps = wf["jobs"]["afternoon"]["steps"]
    names = [s.get("name", "") for s in steps]
    step = next(s for s in steps if "intraday teach" in s.get("run", ""))
    i, save = names.index(step["name"]), names.index("Save the journal")
    trade = next(i for i, s in enumerate(steps) if s.get("id") == "trade")
    squares = [i for i, n in enumerate(names) if "square off" in n.lower()]
    sellers = next(i for i, n in enumerate(names) if n.startswith("Expiry sellers"))
    progress = next(i for i, n in enumerate(names) if n.startswith("Progress snapshot"))
    assert max([trade, sellers, progress, *squares]) < i < save                  # after the close; before the save
    assert step["timeout-minutes"] <= 15 and step["continue-on-error"] is True and "::warning::teaching failed" in step["run"]
    assert "env" not in step and "secrets" not in step["if"] and "!cancelled()" in step["if"]
    # the save runs whatever this step did (always()), so the lessons are saved and a failed or timed-out step blocks nothing
    assert steps[save]["if"].startswith("${{ always()")
    # no secret, env or permission was added anywhere in the workflow: the same permissions, the same workflow env and the
    # same set of secrets referenced as on main aad8470 (structural, so other features' steps in this file don't break it)
    assert wf["permissions"] == {"contents": "write"} and all("permissions" not in j or j["permissions"] == {"actions": "read"}
                                                             for j in wf["jobs"].values())
    # the one reviewed exception: the Kite data feed's key and secret (market data only; owner instruction of 25 Oct 2026, written into docs/AUTONOMY.md by the owner, PR #139 merged 30 Oct 2026),
    # named here so that anything else added to the workflow still fails this pin
    kite_env, kite_secrets = {"KITE_DATA_KEY"}, {"secrets.KITE_API_KEY", "secrets.KITE_API_SECRET"}
    assert sorted(set(wf["env"]) - kite_env) == LIVE_ENV_BEFORE
    refs = " ".join(sorted(set(re.findall(r"secrets\.[A-Za-z0-9_]+", text)) - kite_secrets))
    assert hashlib.sha256(refs.encode()).hexdigest() == LIVE_SECRETS_BEFORE


def test_autolearn_is_untouched():
    assert hashlib.sha256((ROOT / ".github" / "workflows" / "autolearn.yml").read_bytes()).hexdigest() == AUTOLEARN_BEFORE


def test_the_teach_command_is_registered():
    import argparse
    from quantdesk.intraday import cli
    p = argparse.ArgumentParser()
    cli.register(p.add_subparsers())
    a = p.parse_args(["intraday", "teach", "--date", DAY])
    assert a.fn is cli.cmd_teach and a.date == DAY


# ---- durable: survives the journal save, not pruned silently -------------------------------------------------------------
def test_lessons_live_in_state_which_retention_never_prunes_and_the_save_guard_counts(journal, tmp_path):
    assert "state" not in retention.PRUNABLE
    teacher.teach(CFG, journal, DAY, reader=reader_for(FakeAnthropic(reply(lesson()))), now=AFTER)
    path = tmp_path / "journal.db"
    disk = sqlite3.connect(path)
    journal.db.backup(disk)
    disk.close()
    import importlib.util
    spec = importlib.util.spec_from_file_location("journal_counts", ROOT / "deploy" / "journal_counts.py")
    jc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jc)
    assert jc.figures(str(path))["teacher_sessions"] == 1
    restored = tmp_path / "restored.json"
    restored.write_text(json.dumps(jc.figures(str(path))))
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM state WHERE key LIKE 'teacher:%'")
    assert jc.main(["x", str(path), "--not-below", str(restored)]) == 1        # a save that lost the lessons is refused


def test_the_default_reader_is_built_from_the_environment_and_the_configured_model(journal, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    made, fake, real = {}, FakeAnthropic(reply(lesson())), llm.ClaudeReader

    def factory(key, **kw):                               # stands in for the SDK-backed reader: nothing leaves the process
        made.update(kw)
        return real(key, client=fake)
    monkeypatch.setattr(llm, "ClaudeReader", factory)
    assert teacher.teach(CFG, journal, DAY, now=AFTER)["status"] == "taught"
    assert made["model"] == CFG.get("intraday.llm.claude.model") and len(fake.calls) == 1
    src = (ROOT / "quantdesk" / "intraday" / "teacher.py").read_text(encoding="utf-8")
    assert "claude-opus" not in src and "claude-sonnet" not in src          # the model name lives in the config only


# ---- nothing that looks like a credential leaves the machine --------------------------------------------------------------
@pytest.mark.parametrize("text", ["Authorization: Bearer abcDEF123456789xyz", "api_key=sk-ant-abcdef123456", "GET https://x/y?token=abc123&z=1",
                                  "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcd1234", "key AbC123dEf456GhI789jKl012MnO345pQr678StU9",
                                  "mail me at a.b@example.com", "password: hunter2", "ucc=AB1234", "account no: 12345678", "mobile: 9876543210"])
def test_credential_like_strings_are_masked(text):
    out, n = teacher.redact(text)
    assert n >= 1 and "[redacted]" in out
    for secret in ("abcDEF123456789xyz", "sk-ant-abcdef123456", "abc123", "eyJzdWIi", "AbC123dEf456", "a.b@example.com", "hunter2", "AB1234", "12345678", "9876543210"):
        assert secret not in out


@pytest.mark.parametrize("text", ["+54700PE@506.30", "trade:I261012-0001-0cea", "pnl 2941.605976843998 R 0.32277810442249855", "NSE:NIFTY 25000 CE @ 120.5",
                                  "decision:12 | 10:06 | orb NIFTY | rejected | outlay above max_total_outlay", "tokens per minute fell", "premium_target on BANKNIFTY27OCT2654700PE"])
def test_ordinary_journal_text_is_untouched(text):
    assert teacher.redact(text) == (text, 0)


def test_a_credential_in_a_journal_row_never_reaches_the_reader_and_is_journaled_as_a_count(journal):
    journal.event(f"{DAY} 12:30:00", "WARN", "broker", "login failed: Authorization: Bearer SUPERSECRETTOKEN123456 for user a.b@example.com")
    journal.commit()
    fake = FakeAnthropic(reply(lesson(evidence=["trade:T1"])))
    got = teacher.teach(CFG, journal, DAY, reader=reader_for(fake), now=AFTER)
    sent = fake.calls[0]["messages"][0]["content"]
    assert got["status"] == "taught" and "SUPERSECRETTOKEN123456" not in sent and "a.b@example.com" not in sent and "[redacted]" in sent
    assert any("credential-like string" in m for m in events(journal, "WARN")["message"])
    assert not any("SUPERSECRET" in m or "a.b@example.com" in m for m in events(journal)["message"].astype(str))    # the teaching events hold a count, never the string


@pytest.mark.parametrize("text,secret", [("KITE_ACCESS_TOKEN=abcDEF123456789xyzABC", "abcDEF123456789xyzABC"), ("KITE_API_KEY=k123456", "k123456"), ("KOTAK_CONSUMER_KEY=3f2504e0-4f89-11d3", "3f2504e0"),
                                         ("client_secret=s3cr3t", "s3cr3t"), ("my_password=pw99", "pw99"), ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI", "wJalrXUtnFEMI"),
                                         ("Authorization: Token abc123", "abc123"), ("authorization: Bearer abcd", "abcd"), ('password="abc def"', "def"),
                                         ("Authorization: token key123:access456", "access456")])
def test_environment_style_names_and_authorization_schemes_are_masked_whole(text, secret):
    out, n = teacher.redact(text)
    assert n >= 1 and secret not in out, out


@pytest.mark.parametrize("text", ["basic structure intact", "Basic strategies worked", "basic breakouts failed", "orb rejected: premium_target not reached"])
def test_ordinary_prose_with_basic_is_untouched(text):
    assert teacher.redact(text) == (text, 0)


def test_redaction_is_linear_on_an_unbroken_run():
    import time
    t0 = time.time()
    teacher.redact("a" * 200_000)
    teacher.redact("a.b" * 70_000)
    teacher.redact("x" * 100_000 + "@")
    assert time.time() - t0 < 3.0
