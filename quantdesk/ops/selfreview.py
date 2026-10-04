"""The desk's own engineer: after every session it reads what happened and files what needs fixing or building as
GitHub issues (label `desk-request`). The requests queue up whether or not anyone is in a chat, and a scheduled
Claude session (docs/AUTONOMY.md) works through them. Nothing here touches orders, sizing or risk.

What it checks:
- **the session:**
  - did the desk run on a trading day;
  - engine errors, grouped;
  - a long run without a paper trade;
  - the account's drawdown;
- **the chain tape:** minute coverage of every recorded series (the desk's only real point-in-time evidence);
- **the expiry sleeves:**
  - skipped or unsettled trades;
  - a defined-risk trade that lost more than its max loss (a bug);
  - a sleeve the spec retired;
  - a sleeve reaching a decision point;
- **GitHub Actions:** any workflow that failed in the last day;
- **data milestones:** the tape reaching 10, 20, 40, 60 full sessions, when real-quote plan research becomes worth
  re-running;
- **the outside world:** the config's lot sizes against the newest NSE and BSE bhavcopy (exchanges change them by
  circular).

One issue per finding key:
- a recurring problem seen again gets one comment a day;
- a transient finding whose check passes again is closed with a note;
- a research request stays open until someone (or the scheduled session) acts on it.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd

LABEL = "desk-request"
KIND_LABELS = {"bug": ("desk:bug", "d73a4a"), "ops": ("desk:ops", "fbca04"), "data": ("desk:data", "0e8a16"),
               "research": ("desk:research", "5319e7")}
AUTO = ("auto-clears", "c5def5")
MARKER = re.compile(r"<!-- desk-key: (.+?) -->")
TAPE_MILESTONES = (10, 20, 40, 60, 120)
FULL_TAPE_ATTEMPTS = 300                      # a session's minute attempts for it to count as "full" (of ~375)
NO_TRADE_SESSIONS = 5
DRAWDOWN_ALERT = 0.08


@dataclasses.dataclass
class Finding:
    key: str
    kind: str                 # bug | ops | data | research
    title: str
    detail: str
    action: str
    transient: bool = True    # closes by itself when the check passes again

    def body(self, day) -> str:
        return (f"{self.detail}\n\n**What to do:** {self.action}\n\n_Filed by the desk's self-review on {day}. "
                f"{'It closes itself when the check passes again.' if self.transient else 'Close it when done.'}_\n\n"
                f"<!-- desk-key: {self.key} -->")


# ---- checks ---------------------------------------------------------------------------------------------------------
def check_session(journal, day: dt.date, trading_day: bool) -> list[Finding]:
    since = (journal.get_state("intraday_account") or {}).get("since")
    if not trading_day or since is None or str(day) < str(since):       # before this account existed: nothing to judge
        return []
    out = []
    ev = journal.events(since=str(day))
    ev = ev[ev["ts"].astype(str).str[:10] == str(day)] if len(ev) else ev
    started = len(ev) and ev["message"].astype(str).str.startswith("session start").any()
    if not started:
        out.append(Finding("session-missing", "ops", f"The desk did not run on {day}",
                           f"No `session start` event in the journal for {day}, a trading day.",
                           "Check the Desk scheduler / Desk waiter / Live paper desk runs for the day and the Cloudflare "
                           "cron (deploy/cloudflare). Fix whatever stopped the start."))
    err = ev[ev["level"] == "ERROR"] if len(ev) else ev
    if len(err):
        top = err["message"].astype(str).str[:90].value_counts().head(6)
        lines = "\n".join(f"- {n}× `{m}`" for m, n in top.items())
        out.append(Finding("engine-errors", "bug", f"{len(err)} engine error(s) on {day}",
                           f"Errors journaled during the {day} session (most frequent first):\n\n{lines}",
                           "Reproduce from the journal (the event's data has `where`), fix the cause, add a test."))
    return out


def check_trading(journal, cal, day: dt.date, n: int = NO_TRADE_SESSIONS) -> list[Finding]:
    out = []
    days, d = [], day
    while len(days) < n:
        if cal.is_trading_day(d):
            days.append(d)
        d -= dt.timedelta(days=1)
    tr = journal.trades()
    opened = pd.to_datetime(tr["opened_at"].astype(str).str[:10], errors="coerce").dt.date if len(tr) else pd.Series([], dtype=object)
    recent = int(sum(x in set(days) for x in opened))
    starts = journal.events(since=str(days[-1]))
    ran = set(starts.loc[starts["message"].astype(str).str.startswith("session start"), "ts"].astype(str).str[:10]) if len(starts) else set()
    if recent == 0 and len(ran) >= n:
        out.append(Finding("no-trades", "research", f"No paper trade in the last {n} sessions",
                           f"The desk ran on {len(ran)} of the last {n} trading days ({days[-1]} → {days[0]}) and opened "
                           "nothing. Either nothing qualified (fine, if the gates are right) or a gate is too tight.",
                           "Read the decisions table for the vetoes that fired most, and check them against real-quote "
                           "evidence before loosening anything (never loosen risk limits to make trades happen)."))
    eq = journal.equity()
    if len(eq) and "equity" in eq:
        peak, last = float(eq["equity"].cummax().iloc[-1]), float(eq["equity"].iloc[-1])
        dd = 1 - last / peak if peak > 0 else 0.0
        if dd >= DRAWDOWN_ALERT:
            out.append(Finding("drawdown", "research", f"Paper account {dd:.1%} below its peak",
                               f"Equity ₹{last:,.0f} against a peak of ₹{peak:,.0f}.",
                               "Attribute the drawdown by strategy and setup (journal trades), and check whether one "
                               "family is breaking from its evidence."))
    return out


def check_tape(data_dir: Path, day: dt.date, trading_day: bool, min_cov: float = 0.9) -> list[Finding]:
    if not trading_day:
        return []
    from ..intraday.feeds import session_bounds
    from ..intraday.tape import completeness
    open_, close = session_bounds(day)
    rep = completeness(Path(data_dir) / str(day), open_, close)
    if not rep["series"]:
        rep["series"] = tape_log_coverage(Path(data_dir) / str(day) / "tape.csv", open_, close)
    if not rep["series"]:
        return [Finding("tape-missing", "data", f"No chain tape on {day}",
                        f"No option-chain snapshots under data/{day}/chains. The tape is the desk's only source of "
                        "real point-in-time quotes, and the expiry sleeves enter from it.",
                        "Check the tape log in the Live paper desk run (tape.log), the Kotak key, and run-session.sh.")]
    low = {s: v["coverage"] for s, v in rep["series"].items() if v["coverage"] is not None and v["coverage"] < min_cov}
    if not low:
        return []
    lines = "\n".join(f"- {s}: {c:.0%} of minutes" for s, c in sorted(low.items()))
    errs = "".join(f"\n- {n}× `{e}`" for e, n in (rep.get("top_errors") or {}).items())
    return [Finding("tape-gaps", "data", f"Chain tape below {min_cov:.0%} coverage on {day}",
                    f"{lines}\n\nAttempts {rep.get('attempts')}, failures {rep.get('failures')}.{errs}",
                    "Find why minutes were missed (rate limits, slow calls, a runner restart) and fix it.")]


def tape_log_coverage(log: Path, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Coverage from the tape's own log (saved with the journal) when the chain files aren't on this machine."""
    if not Path(log).exists():
        return {}
    lg = pd.read_csv(log)
    lg = lg[lg["ok"].astype(str).str.lower() == "true"]
    span = max(1, int((end - start).total_seconds() // 60))
    mins = pd.to_datetime(lg["ts"].astype(str).str[:16], errors="coerce")
    lg = lg.assign(minute=mins).dropna(subset=["minute"])
    return {f"{u} {e}": {"minutes": int(g["minute"].nunique()), "coverage": g["minute"].nunique() / span}
            for (u, e), g in lg.groupby(["underlying", "expiry"])}


def check_sleeves(seller, day: dt.date) -> list[Finding]:
    from ..intraday.sleeves import MIN_COST, MIN_ELIGIBLE
    out = []
    rep = seller.report()
    for r in rep["rows"]:
        tag = f"{rep['spec']}:{r['sleeve']}-{r['underlying']}"
        if r["retired"]:
            out.append(Finding(f"sleeve-retired:{tag}", "research", f"Expiry sleeve {tag} retired by its spec",
                               f"{r['retired']}. Trades: {r['n']}, P&L ₹{r['sum']:+,.0f}/lot.",
                               "Write it up (docs/reports), and decide whether a v2 spec with a different rule is "
                               "justified by evidence, not by the loss.", transient=False))
        for b in r["bugs"]:
            out.append(Finding(f"sleeve-bug:{rep['spec']}:{b.split(':')[0]}", "bug", "A defined-risk sleeve trade lost more than its max loss",
                               b, "This is impossible by construction: find the settlement or fill bug and fix it.",
                               transient=False))
        if r["n"] in (MIN_COST, MIN_ELIGIBLE):
            out.append(Finding(f"sleeve-milestone:{tag}:{r['n']}", "research",
                               f"Expiry sleeve {tag} reached {r['n']} settled trades",
                               f"Cost check: {r['cost']}; consistency: {r['consistency']}; status: {r['status']}. Mean cost "
                               f"gap ₹{r['gap_mean']:+,.0f}/lot (history assumed 0).",
                               "Record the verdict with the numbers in docs/principles.json (a decision record on this "
                               "issue). If eligible, apply the registered allocator to the paper account under the ₹5L "
                               "loss budget (BACKLOG 9); register it first if it doesn't exist yet. Real money stays off.",
                               transient=False))
    for t in rep["open"]:
        if dt.date.fromisoformat(t["expiry"]) < day:
            out.append(Finding(f"sleeve-unsettled:{rep['spec']}:{t['id']}", "data", f"Sleeve trade {t['id']} past expiry and unsettled",
                               f"Expired {t['expiry']} with no settlement: no recorded closing bars and no Yahoo close.",
                               "Recover the expiry-day close (recorded bars, the backfill's index minutes, or NSE) "
                               "and re-run `quantdesk intraday sleeves`."))
    for t in seller.trades():
        if str(t.get("day", "")) == str(day) and t.get("quote_flags"):
            legs = "; ".join(f"{x['strike']:.0f}{x['right']}: {', '.join(x['flags'])} (spread {x['spread_pct']:.0%}"
                             + (f", {x['touch_qty']:.0f} at the touch" if x.get("touch_qty") is not None else "") + ")"
                             for x in t["legs"] if x.get("flags"))
            out.append(Finding(f"sleeve-quotes:{rep['spec']}:{t['id']}", "data",
                               f"Sleeve trade {t['id']} filled on questionable quotes: {', '.join(t['quote_flags'])}",
                               (legs or "") + (f"; snapshot {t.get('snapshot_off_min')} min from 15:20" if "late" in t["quote_flags"] else ""),
                               "Check the tape at that minute: if the quotes were stale or the book thin, record a decision "
                               "on whether this trade counts toward the sleeve's assessment, and fix the tape if it missed "
                               "minutes.", transient=False))
    for u, f in rep.get("fills", {}).items():
        if f["legs"] >= 8 and f["real_vs_model"] and f["real_vs_model"] > 2:
            out.append(Finding(f"cost-model:{u}", "research",
                               f"Real fills on {u} cost {f['real_vs_model']}x what the history assumed",
                               f"{f['legs']} legs: real {f['real_cost_pts']} vs model {f['model_cost_pts']} pts a leg; median "
                               f"spread {f['median_spread_pct']:.0%} of mid.",
                               "The history's results on this instrument are too kind. Register a re-costing study (a new "
                               "spec using the measured spreads) and add a caveat to every principle that rests on it.",
                               transient=False))
    for e in rep["skips"]:
        if e.get("day") == str(day) and not e["reason"].startswith("retired"):
            out.append(Finding(f"sleeve-skip:{rep['spec']}:{e['sleeve']}-{e['underlying']}-{e['expiry']}", "data",
                               f"Expiry sleeve {e['sleeve']}-{e['underlying']} skipped the {e['expiry']} expiry",
                               e["reason"], "If the cause is the desk's (no tape, no run), fix it before the next eve.",
                               transient=False))
    return out


def check_workflows(gh, now: pd.Timestamp, hours: int = 26) -> list[Finding]:
    if gh is None:
        return []
    out, seen = [], set()
    since = (now - pd.Timedelta(hours=hours)).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in gh.runs(since):
        if r.get("conclusion") not in ("failure", "timed_out", "startup_failure") or r["name"] in seen:
            continue
        seen.add(r["name"])
        out.append(Finding(f"workflow-failed:{r['name']}", "ops", f"Workflow failed: {r['name']}",
                           f"[{r['name']} #{r.get('run_number')}]({r.get('html_url')}) ended `{r['conclusion']}` at "
                           f"{r.get('updated_at')} (branch {r.get('head_branch')}, event {r.get('event')}).",
                           "Read the failed job's log, find the root cause (never re-run a red job blindly), fix it."))
    return out


def check_milestones(data_dir: Path) -> list[Finding]:
    full = 0
    for log in sorted(Path(data_dir).glob("*/tape.csv")):
        try:
            lg = pd.read_csv(log, usecols=["ok"])
        except Exception:
            continue
        if int((lg["ok"].astype(str).str.lower() == "true").sum()) >= FULL_TAPE_ATTEMPTS:
            full += 1
    hit = [m for m in TAPE_MILESTONES if full >= m]
    if not hit:
        return []
    m = hit[-1]
    return [Finding(f"tape-milestone:{m}", "research", f"{m} full sessions of real chain tape recorded",
                    f"The chain tape now holds {full} full sessions of minute-by-minute real quotes (NIFTY's 3 nearest "
                    "expiries, BANKNIFTY's 2). That is real point-in-time evidence, the only class that can qualify a "
                    "strategy (docs/PLAN_RESEARCH.md).",
                    "Re-run plan research on the tape (real point-in-time evidence), the expiry-day 0-DTE study and "
                    "the overnight-theta study (docs/BACKLOG.md), and report what qualifies.", transient=False)]


def check_lots(cfg, folder: Path) -> list[Finding]:
    """The exchanges change lot sizes by circular. The config's lot drives sizing and costs, so check it against the
    lot in the newest NSE and BSE bhavcopy the warehouse holds (NewBrdLotQty). A mismatch is a data bug until fixed."""
    out = []
    files = [sorted(Path(folder).glob(f"{t}_*.parquet"))[-1:] for t in ("fo_bhav", "bse_fo_bhav")]
    parts = []
    for f in [x for fs in files for x in fs]:
        try:
            parts.append(pd.read_parquet(f, columns=["date", "symbol", "lot"]))
        except Exception:
            continue
    if not parts:
        return out
    d = pd.concat(parts, ignore_index=True).dropna(subset=["lot"])
    for sym, spec in (cfg.get("instruments", {}) or {}).items():
        want = spec.get("lot_size") if isinstance(spec, dict) else None
        g = d[d["symbol"] == sym]
        if not want or g.empty:
            continue
        last = g[g["date"] == g["date"].max()]
        have = int(last["lot"].mode().iloc[0])
        if have != int(want):
            out.append(Finding(f"lot-drift:{sym}", "data", f"{sym} lot size changed: config {int(want)}, exchange {have}",
                               f"The exchange's bhavcopy for {last['date'].iloc[0]} gives {sym} a lot of {have}; "
                               f"config/quantdesk.yaml says {int(want)}. Sizing and costs use the config.",
                               "Confirm against the exchange's circular, update instruments in config/quantdesk.yaml, "
                               "and check every place that assumes the old lot (sleeve specs keep their own reference "
                               "lots by design)."))
    return out


def review(cfg, day: dt.date, gh=None, now: pd.Timestamp | None = None, warehouse: Path | None = None) -> list[Finding]:
    from ..core.calendar import TradingCalendar
    from ..intraday.cli import paths
    from ..intraday.sleeves import ExpirySeller, specs
    from ..journal.journal import Journal
    cal = TradingCalendar(cfg.holidays())
    now = now if now is not None else pd.Timestamp.now(tz="Asia/Kolkata")
    p = paths(cfg, "live")
    td = cal.is_trading_day(day)
    out: list[Finding] = []
    j = Journal(p["journal"])
    try:
        out += check_session(j, day, td)
        out += check_trading(j, cal, day)
    finally:
        j.close()
    out += check_tape(p["data"], day, td)
    for spec in specs():
        out += check_sleeves(ExpirySeller(cfg, cfg.runtime_dir / "intraday" / "sleeves", p["data"], spec=spec), day)
    out += check_workflows(gh, now)
    out += check_milestones(p["data"])
    out += check_lots(cfg, Path(warehouse or "runtime/warehouse"))
    return out


def render(findings: list[Finding], day) -> str:
    if not findings:
        return f"## Self-review {day}\n\nNothing needs attention."
    out = [f"## Self-review {day}", "", f"{len(findings)} finding(s):", ""]
    for f in findings:
        out.append(f"- **[{f.kind}] {f.title}** (`{f.key}`): {f.detail.splitlines()[0]}")
    return "\n".join(out)


# ---- GitHub issues --------------------------------------------------------------------------------------------------
class GitHub:
    """The few REST calls the review needs, with the Actions token (issues: write, actions: read)."""

    def __init__(self, repo: str, token: str, session=None, api: str = "https://api.github.com"):
        import requests
        self.repo, self.api = repo, api
        self.s = session or requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})

    def _req(self, method, path, **kw):
        r = self.s.request(method, f"{self.api}/repos/{self.repo}{path}", timeout=30, **kw)
        if r.status_code >= 400 and not (method == "POST" and path == "/labels" and r.status_code == 422):
            raise RuntimeError(f"GitHub {method} {path}: {r.status_code} {r.text[:200]}")
        return r.json() if r.content else {}

    def runs(self, since: str) -> list[dict]:
        return self._req("GET", "/actions/runs", params={"created": f">={since}", "per_page": 100}).get("workflow_runs", [])

    def open_issues(self) -> list[dict]:
        return [i for i in self._req("GET", "/issues", params={"labels": LABEL, "state": "open", "per_page": 100})
                if "pull_request" not in i]

    def issues(self, label: str, state: str = "all", since: str | None = None) -> list[dict]:
        params = {"labels": label, "state": state, "per_page": 100, **({"since": since} if since else {})}
        return [i for i in self._req("GET", "/issues", params=params) if "pull_request" not in i]

    def issue_titled(self, title: str, label: str) -> dict | None:
        for i in self._req("GET", "/issues", params={"labels": label, "state": "open", "per_page": 100}):
            if i.get("title") == title and "pull_request" not in i:
                return i
        return None

    def ensure_label(self, name: str, color: str) -> None:
        self._req("POST", "/labels", json={"name": name, "color": color})

    def create(self, title: str, body: str, labels: list[str]) -> dict:
        return self._req("POST", "/issues", json={"title": title, "body": body, "labels": labels})

    def comment(self, number: int, body: str) -> None:
        self._req("POST", f"/issues/{number}/comments", json={"body": body})

    def add_label(self, number: int, name: str) -> None:
        self._req("POST", f"/issues/{number}/labels", json={"labels": [name]})

    def close(self, number: int) -> None:
        self._req("PATCH", f"/issues/{number}", json={"state": "closed", "state_reason": "completed"})


def sync(gh, findings: list[Finding], day: dt.date, say=print) -> dict:
    """One open issue per finding key. New → created; seen again → one comment a day; a transient finding that's gone
    → closed. Returns what happened."""
    done = {"created": [], "commented": [], "closed": []}
    for name, color in [(LABEL, "1d76db"), AUTO, *KIND_LABELS.values()]:
        gh.ensure_label(name, color)
    open_ = {}
    for i in gh.open_issues():
        m = MARKER.search(i.get("body") or "")
        if m:
            open_[m.group(1)] = i
    keys = {f.key for f in findings}
    for f in findings:
        if f.key in open_:
            i = open_[f.key]
            if f.transient and str(i.get("updated_at", ""))[:10] < str(day):     # a recurring problem, not a request
                gh.comment(i["number"], f"Seen again on {day}.\n\n{f.detail}")
                done["commented"].append(i["number"])
            continue
        labels = [LABEL, KIND_LABELS[f.kind][0]] + ([AUTO[0]] if f.transient else [])
        i = gh.create(f"[desk] {f.title}", f.body(day), labels)
        done["created"].append(i.get("number"))
    for key, i in open_.items():
        auto = any((x.get("name") if isinstance(x, dict) else x) == AUTO[0] for x in i.get("labels", []))
        if key not in keys and auto:
            gh.comment(i["number"], f"Cleared on {day}: the check passed again. Closing.")
            gh.close(i["number"])
            done["closed"].append(i["number"])
    say(f"issues: created {done['created'] or 'none'}, commented {done['commented'] or 'none'}, "
        f"closed {done['closed'] or 'none'}")
    return done


def to_json(findings: list[Finding]) -> str:
    return json.dumps([dataclasses.asdict(f) for f in findings], indent=1)
