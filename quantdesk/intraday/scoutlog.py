"""The scout's journal (shadow, offline): everything the scout does, tries, finds and decides, in one tamper-evident, append-only log, so that a broad
review (the owner's: December 2026) can read the whole story and not only the last run. docs/ASYMMETRY_SCOUT.md.

Built on the desk's own hash chain (`autolearn.store.ChainLog`): one JSON line per entry, each carrying the hash of the one before; `verify` finds an edited,
deleted or torn entry. Nothing is ever edited: a changed mind is a NEW entry that points back (`refs`) at the old one.

Entry kinds
  run          one scout / scout-lab run: parameters, code commit, data digest, window, the sealed date, condensed results, and its TRIALS (how many cells and
               rules it tried). Written automatically by the commands.
  observation  something seen in a run, with its numbers and its caveats. Exploratory unless it says otherwise.
  hypothesis   a claim worth a pre-registered test; `status` starts "open". A later `status` entry (refs -> the hypothesis) moves it to tested / killed / confirmed.
  decision     a choice made and why (a design rule, a cost assumption, a thing not done).
  plan         what is to be done next and when (the December review).
  note         anything else, including the owner's own words.

The running total of trials (`trials()`) is the multiple-testing burden: a claim made in December has to be judged against EVERYTHING tried before it, not
against the last run. Entries hold aggregates and parameters only, never raw prices. Evidence label: external_unverified; never evidence for a gate, a
promotion, the paper gate or a profitability claim."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from ..autolearn.store import ChainLog, LogCorrupt  # noqa: F401  (LogCorrupt re-exported for callers)
from .scout import EVIDENCE, NOT_FOR

KINDS = ("run", "observation", "hypothesis", "decision", "plan", "note", "status")
STATUSES = ("open", "tested", "killed", "confirmed", "parked")
DEFAULT_REL = Path("intraday") / "scout" / "journal.jsonl"      # under the runtime dir: the desk's journal save carries runtime/intraday/ to the `journal` branch


def default_path(cfg) -> Path:
    return Path(cfg.runtime_dir) / DEFAULT_REL


class ScoutJournal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.log = ChainLog(self.path)

    def add(self, kind: str, title: str, payload: dict | None = None, refs: list[int] | tuple[int, ...] = (), tags: list[str] | tuple[str, ...] = (),
            by: str = "claude") -> dict:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        have = {r["seq"] for r in self.log.read()}
        bad = [r for r in refs if r not in have]
        if bad:
            raise ValueError(f"refs {bad} are not entries of this journal")
        rec = {"kind": kind, "title": str(title), "payload": payload or {}, "refs": list(refs), "tags": list(tags), "by": by,
               "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "evidence": EVIDENCE}
        if kind in ("run", "observation", "hypothesis"):
            rec["not_for"] = NOT_FOR
        if kind == "hypothesis":
            rec["payload"].setdefault("status", "open")
        return self.log.append(rec)

    def set_status(self, hypothesis: int, status: str, why: str, refs: list[int] | tuple[int, ...] = (), by: str = "claude") -> dict:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        return self.add("status", f"hypothesis {hypothesis} -> {status}", {"hypothesis": hypothesis, "status": status, "why": why}, [hypothesis, *refs], by=by)

    def entries(self, kind: str | None = None) -> list[dict]:
        rows = self.log.read()
        return [r for r in rows if kind is None or r["kind"] == kind]

    def verify(self) -> list[str]:
        return self.log.verify()

    def trials(self) -> dict:
        """The running total of what has been tried across every run so far (the multiple-testing burden)."""
        t = {"runs": 0, "strategy_policy_cells": 0, "rules_tried": 0, "search_nulls": 0, "candidates": 0}
        for r in self.entries("run"):
            p = r["payload"]
            t["runs"] += 1
            tr = p.get("trials") or {}
            t["strategy_policy_cells"] += int(tr.get("cells") or 0)
            t["rules_tried"] += int(tr.get("rules_tried") or 0)
            t["search_nulls"] += int(tr.get("nulls") or 0)
            t["candidates"] += int(p.get("rows") or 0)
        return t

    def hypotheses(self) -> list[dict]:
        """Every hypothesis with its latest status."""
        latest = {}
        for r in self.entries("status"):
            latest[r["payload"]["hypothesis"]] = r["payload"]["status"]
        return [{"seq": r["seq"], "title": r["title"], "status": latest.get(r["seq"], r["payload"].get("status", "open")), "recorded_at": r["recorded_at"]}
                for r in self.entries("hypothesis")]

    def summary(self) -> str:
        rows = self.log.read()
        t = self.trials()
        hy = self.hypotheses()
        L = [f"# Scout journal ({self.path.name}): {len(rows)} entries", "",
             f"Evidence label: {EVIDENCE}. {NOT_FOR}", "",
             f"**Tried so far:** {t['runs']} runs, {t['candidates']:,} candidates, {t['strategy_policy_cells']:,} strategy x exit-policy cells, "
             f"{t['rules_tried']:,} mined rules, {t['search_nulls']} null searches. A claim made later is judged against ALL of it.", ""]
        by = pd.Series([r["kind"] for r in rows]).value_counts().to_dict()
        L += ["Entries by kind: " + ", ".join(f"{k} {v}" for k, v in by.items()), ""]
        if hy:
            L += ["## Hypotheses", "", "| # | status | title |", "|---|---|---|"] + [f"| {h['seq']} | {h['status']} | {h['title']} |" for h in hy] + [""]
        plans = self.entries("plan")
        if plans:
            L += ["## Plans", ""] + [f"- #{p['seq']} {p['title']}: {p['payload'].get('when', '')} {p['payload'].get('what', '')}" for p in plans] + [""]
        L += ["## Runs", "", "| # | when (UTC) | title | window | rows | commit |", "|---|---|---|---|---|---|"]
        for r in self.entries("run"):
            p = r["payload"]
            L.append(f"| {r['seq']} | {r['recorded_at'][:16]} | {r['title']} | {p.get('first', '')} to {p.get('last', '')} | {p.get('rows', '')} | {str(p.get('code', {}).get('commit', ''))[:8]} |")
        return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------- what the commands record
def _code(man: dict) -> dict:
    c = man.get("code") or {}
    return {"commit": c.get("commit"), "dirty": c.get("dirty")}


def record_grid(j: ScoutJournal, out: Path, note: str = "", backfill: bool = False) -> dict:
    """A finished `scout` run: its manifest and the pooled base rates, which is the yardstick every later claim is measured against."""
    from .scout_report import base_rates
    out = Path(out)
    man = json.loads((out / "manifest.json").read_text())
    df = pd.read_parquet(out / "scout_candidates.parquet", columns=["symbol", "kind", "day", "reach_2", "reach_3", "reach_4", "reach_6"])
    if df["symbol"].nunique() > 10:                       # many stocks: one pooled row, not dozens of thin ones
        df = df.assign(symbol=f"{df['kind'].iloc[0]}s pooled ({df['symbol'].nunique()})")
    br = base_rates(df)
    rates = {f"{r.symbol}": {} for r in br.itertuples()}
    for r in br.itertuples():
        rates[r.symbol][f"reach_{r.k}"] = {"rate": round(r.rate, 4), "se": round(r.se, 4), "n": int(r.n), "sessions": int(r.sessions), "net_R_assumed_cost": round(r.net_R, 3)}
    payload = {"command": "scout", "params": man["params"], "source": man["source"], "rows": man["rows"], "sessions": man["sessions"], "first": man["first"],
               "last": man["last"], "sealed_from": man["sealed_from"], "by_symbol": man["by_symbol"], "code": _code(man), "base_rates": rates,
               "out_folder": str(out), "trials": {"cells": 0, "rules_tried": 0, "nulls": 0}, "backfill": backfill, "note": note}
    return j.add("run", f"scout grid: {man['source'].get('use', '')} {man['first']} to {man['last']}", payload, tags=["grid"])


def record_lab(j: ScoutJournal, out: Path, note: str = "", backfill: bool = False) -> dict:
    """A finished `scout-lab` run: the leaderboard's headline, every mined search with its null, and the trials it adds to the running total."""
    out = Path(out)
    man = json.loads((out / "manifest.json").read_text())
    payload = {"command": "scout-lab", "params": man["params"], "source": man["source"], "rows": man["rows"], "first": man["first"], "last": man["last"],
               "sealed_from": man["sealed_from"], "strategies": man["strategies"], "code": _code(man), "out_folder": str(out), "backfill": backfill, "note": note,
               "stop_floor_atr": man.get("stop_floor_atr"), "stop_cap_atr": man.get("stop_cap_atr")}
    cells = rules = nulls = 0
    lbp = out / "leaderboard.csv"
    if lbp.exists():
        lb = pd.read_csv(lbp)
        cells = int(lb["cells"].iloc[0]) if len(lb) else 0
        payload["leaderboard"] = {"cells": cells, "z_needed": round(float(lb["z_needed"].iloc[0]), 3), "passing": int(lb["passes"].sum()),
                                  "best": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
                                           for r in lb.head(8)[["strategy", "policy", "n_valid", "mean_train", "mean_valid", "t_valid", "median_valid", "top1pct_share", "passes"]].to_dict("records")],
                                  "mean_valid_by_policy": {k: round(v, 4) for k, v in lb.groupby("policy")["mean_valid"].mean().items()}}
    mined = {}
    for f in sorted(out.glob("mined_*.json")):
        m = json.loads(f.read_text())
        lg = m["ledger"]
        rules += int(lg["trials"])
        nulls += int(lg["nulls"]) * int(lg["trials"])
        mined[f.stem.removeprefix("mined_")] = {"outcome": m["outcome"], "ledger": lg, "best_valid_mean": m["best_valid_mean"], "p_vs_null": m["p_vs_null"],
                                                "null_best_valid_means": m["null_best_valid_means"], "top_rules": m["rules"][:5]}
    payload["mined"] = mined
    payload["trials"] = {"cells": cells, "rules_tried": rules + nulls, "nulls": sum(int(v["ledger"]["nulls"]) for v in mined.values())}
    return j.add("run", f"scout lab: {man['source'].get('use', '')} {man['first']} to {man['last']}", payload, tags=["lab"])
