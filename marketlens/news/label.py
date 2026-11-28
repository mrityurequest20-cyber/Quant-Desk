"""News phase P3: the one-time Claude labelling run (the teacher). Budget: $13 in all, enforced here.

Claude labels what the TEXT says, never what happened next: the event type, who it is about, which economic channels it
moves and which way, whether it was scheduled, whether the text reads as a surprise, how new it is, and whether it is
a market wrap (a description of a move, not a cause). Outcomes are measured from the warehouse (reactions.py), so a
label can't carry hindsight in through the back door. Claude's own direction view is kept as a field to be TESTED,
never trusted: it is scored against what followed, on news after the model's training cutoff.

Plan (owner's budget, the model choice left to us): Claude Haiku 5.5 labels the corpus through the Batch API (half
price), 25 stories a request so the long cached instructions are paid for once per request; Claude Opus 5.5 labels a
stratified sample of ~1,500 of the same stories, and the agreement between the two is the label quality we report.

Spend control: every batch is a tranche; after each, the real cost is read from the results' usage and the next tranche
is sent only if spent + its projected cost stays under the cap. `estimate` counts tokens and prices the whole run
without spending (count_tokens is free). State (batch ids, spend, labels) is saved after every tranche: a stopped run
resumes and never pays twice for a story.
"""
from __future__ import annotations

import json
import math
import random
import re
import time
from pathlib import Path

import pandas as pd

from ..universe import INDICES, STOCKS

HAIKU, OPUS = "claude-haiku-5-5", "claude-opus-5-5"
# $ per million tokens, standard rates (Batch API: half). Haiku 5.5's are for prompts up to 100K tokens.
PRICE = {HAIKU: {"in": 0.10, "out": 0.50, "cache_read": 0.01, "cache_write": 0.125},
         OPUS: {"in": 4.00, "out": 20.00, "cache_read": 0.40, "cache_write": 5.00}}
BATCH = 0.5
PER_REQUEST = 25
TOTAL_BUDGET = 13.0         # the owner's budget for the whole labelling job, both models together

SYMBOLS = [i.symbol for i in INDICES] + ["INDIAVIX"] + [s.symbol for s in STOCKS]
EVENT_TYPES = [
    "results", "guidance_outlook", "dividend_buyback", "bonus_split", "merger_acquisition", "stake_sale_block_deal",
    "fund_raise", "credit_rating", "broker_call", "order_contract", "capex_expansion", "product_launch", "business_update",
    "management_change", "governance_fraud_probe", "regulator_action_on_company", "litigation_tax", "promoter_pledge_insider",
    "index_inclusion_exclusion", "outage_accident_strike",
    "rbi_policy", "rbi_regulation_liquidity", "inflation_data", "growth_data", "budget_fiscal_tax", "government_policy",
    "election_politics", "geopolitics_conflict", "trade_tariffs", "fed_us_rates", "us_global_macro_data", "global_markets",
    "crude_energy", "gold_metals", "currency", "fund_flows", "monsoon_weather", "pandemic_health", "sebi_market_rules",
    "market_report", "opinion_explainer", "other"]
CHANNELS = ["crude", "gold", "rupee", "dollar", "us_yields", "fed", "rbi_rates", "liquidity", "inflation", "growth",
            "fiscal", "foreign_flows", "geopolitical_risk", "tariffs", "china", "global_equities", "monsoon", "bank_credit",
            "it_demand", "auto_demand", "pharma", "metals", "energy", "telecom", "consumer", "capital_markets", "company"]

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["labels"],
    "properties": {"labels": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["i", "relevant", "event_type", "market_report", "scheduled", "surprise", "novelty", "importance",
                     "targets", "channels"],
        "properties": {
            "i": {"type": "integer"},
            "relevant": {"type": "boolean"},
            "event_type": {"type": "string", "enum": EVENT_TYPES},
            "market_report": {"type": "boolean"},
            "scheduled": {"type": "boolean"},
            "surprise": {"type": "string", "enum": ["positive", "negative", "mixed", "none", "unknown"]},
            "novelty": {"type": "string", "enum": ["new", "update", "rehash"]},
            "importance": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "targets": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["symbol", "role", "view"],
                "properties": {"symbol": {"type": "string", "enum": SYMBOLS},
                               "role": {"type": "string", "enum": ["primary", "secondary"]},
                               "view": {"type": "string", "enum": ["up", "down", "unclear"]}}}},
            "channels": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["channel", "direction"],
                "properties": {"channel": {"type": "string", "enum": CHANNELS},
                               "direction": {"type": "string", "enum": ["up", "down"]}}}},
        }}}},
}

UNIVERSE_TEXT = "\n".join(f"- {i.symbol}: {i.name} ({i.sector})" for i in INDICES + STOCKS) + "\n- INDIAVIX: India VIX (implied volatility of NIFTY)"

SYSTEM = f"""You label Indian market news for a research database. Each story is a headline, or a company filing on NSE
with a short summary. You read each story as an analyst would on the day it was published.

Hard rules:
1. Judge ONLY from the story's text and what was generally known on its date. Never use knowledge of what happened
   afterwards (prices, outcomes, later news). If you happen to know how it turned out, ignore that.
2. Do not guess prices or predict moves. `view` is the direction the TEXT itself points for that instrument, as a
   careful reader would read it on the day; use "unclear" whenever the text does not clearly point one way.
3. A story that only describes a market move ("Sensex falls 500 points", "stocks to watch", "market wrap") is
   market_report=true: it reports a move, it does not cause one. Explainers, columns and listicles are opinion_explainer.
4. relevant=false for anything with no plausible bearing on Indian equities, indices or their volatility (lifestyle,
   unrelated local news, other countries' small stocks, duplicate notices).

Fields:
- event_type: the one best type from the list.
- scheduled: true for pre-announced events (results dates, RBI MPC, CPI/GDP releases, budget, Fed meetings, expiries).
- surprise: whether the text reads as better (positive) or worse (negative) than expected, mixed, none (in line /
  no expectation involved) or unknown (the text doesn't say). "Beats estimates" is positive; "misses" negative.
- novelty: new information, an update on a running story, or a rehash of known news.
- importance: low / medium / high / critical for Indian markets or the named company.
- targets: the instruments in the universe below that the story is about (primary) or plainly affects (secondary),
  each with role and view. An economy-wide story targets NIFTY (and BANKNIFTY for rates/credit/banks); a sector story
  targets the sector's index and named stocks. Only symbols from the universe; an empty list if none fits.
- channels: the economic variables the story says are moving, each with its direction (up/down): "Brent jumps 6%" is
  crude up; "rupee hits record low" is rupee down; "RBI cuts repo" is rbi_rates down; "ceasefire" is geopolitical_risk
  down. Company-specific news uses channel "company" with the direction of the company's fundamentals in the text.

Universe:
{UNIVERSE_TEXT}

Return one label per story, with `i` equal to the story's number, in the JSON format required."""


# ---- selecting and packing the stories ---------------------------------------------------------------------------------------
def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", str(t).lower())).strip()[:120]


def select(df: pd.DataFrame, filing_symbols=None) -> pd.DataFrame:
    """The stories worth a label: every headline (deduplicated on its normalised title, first seen kept) and the NSE
    filings of the watchlist stocks (filing_symbols widens that)."""
    keep = set(filing_symbols or [s.symbol for s in STOCKS])
    d = df.copy()
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
    d = d[(d["source"] != "nse") | d["symbol"].isin(keep)]
    d["norm"] = d["title"].map(_norm) + "|" + d["summary"].fillna("").str[:60].map(_norm)
    d = d.sort_values("ts").drop_duplicates("norm", keep="first")
    return d.drop(columns="norm").reset_index(drop=True)


def story_text(r) -> dict:
    s = {"date": pd.Timestamp(r.ts).tz_convert("Asia/Kolkata").strftime("%Y-%m-%d %H:%M IST") if r.ts_quality == "exact"
         else pd.Timestamp(r.ts).tz_convert("Asia/Kolkata").strftime("%Y-%m-%d"), "source": r.publisher or r.source}
    if r.source == "nse":
        s["company"], s["filing"] = r.symbol, r.title
        if r.summary:
            s["summary"] = r.summary[:500]
    else:
        s["headline"] = r.title
    return s


def requests_for(stories: pd.DataFrame, model: str, per: int = PER_REQUEST) -> list[dict]:
    out = []
    for k in range(0, len(stories), per):
        part = stories.iloc[k:k + per]
        items = [{"i": j, **story_text(r)} for j, r in enumerate(part.itertuples())]
        out.append({"custom_id": f"r{k // per:06d}", "ids": list(part["id"]),
                    "params": {"model": model, "max_tokens": 9000,
                               "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                               "messages": [{"role": "user", "content": "Label these stories:\n" + json.dumps(items, ensure_ascii=False)}],
                               "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}}}})
    return out


def cost(usage, model: str, batch: bool = True) -> float:
    p = PRICE[model]
    get = (lambda k: getattr(usage, k, None) or 0) if not isinstance(usage, dict) else (lambda k: usage.get(k) or 0)
    c = (get("input_tokens") * p["in"] + get("output_tokens") * p["out"] + get("cache_read_input_tokens") * p["cache_read"]
         + get("cache_creation_input_tokens") * p["cache_write"]) / 1e6
    return c * (BATCH if batch else 1.0)


def parse(text: str, ids: list[str]) -> list[dict]:
    """Labels from one response, keyed back to the story ids; anything malformed or out of range is dropped."""
    try:
        labels = json.loads(text)["labels"]
    except (ValueError, KeyError, TypeError):
        return []
    out, seen = [], set()
    for lab in labels:
        i = lab.get("i")
        if not isinstance(i, int) or not 0 <= i < len(ids) or i in seen:
            continue
        seen.add(i)
        out.append({"id": ids[i], **{k: v for k, v in lab.items() if k != "i"}})
    return out


# ---- the run -------------------------------------------------------------------------------------------------------------------
class Run:
    """One labelling run's saved state: labels.jsonl (one label per story), state.json (spend and batches)."""

    def __init__(self, root: Path, model: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        tag = "haiku" if model == HAIKU else "opus"
        self.lab_path, self.state_path = self.root / f"labels_{tag}.jsonl", self.root / f"state_{tag}.json"
        self.model = model
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {"spent": 0.0, "batches": [], "requests": 0}
        self.done = set()
        if self.lab_path.exists():
            for line in self.lab_path.read_text().splitlines():
                try:
                    self.done.add(json.loads(line)["id"])
                except (ValueError, KeyError):
                    pass

    def save(self, labels: list[dict], spent: float, batch_id: str, n_req: int):
        with self.lab_path.open("a") as f:
            for lab in labels:
                if lab["id"] not in self.done:
                    f.write(json.dumps(lab, ensure_ascii=False) + "\n")
                    self.done.add(lab["id"])
        self.state["spent"] = round(self.state["spent"] + spent, 6)
        self.state["batches"].append({"id": batch_id, "requests": n_req, "cost": round(spent, 6)})
        self.state["requests"] += n_req
        self.state_path.write_text(json.dumps(self.state, indent=1))

    def files(self) -> list[str]:
        return [p.name for p in (self.lab_path, self.state_path) if p.exists()]


def total_spent(root: Path, but: str | None = None) -> float:
    """What every part of the job has spent (labels, audit, briefs: their state_*.json files), less one of them."""
    tot = 0.0
    for p in Path(root).glob("state_*.json"):
        if but and p.name == but:
            continue
        try:
            tot += float(json.loads(p.read_text()).get("spent", 0))
        except (ValueError, OSError):
            pass
    return tot


def estimate(client, reqs: list[dict], model: str, sample: int = 5, out_per_story: int = 110) -> dict:
    """Price the run without spending: input tokens counted exactly on a sample of requests (count_tokens is free),
    output estimated per story (the JSON label, plus low-effort thinking: measured by the pilot)."""
    if not reqs:
        return {"requests": 0, "usd": 0.0}
    pick = reqs[:: max(1, len(reqs) // sample)][:sample]
    ins, schema_allow = [], 0
    for r in pick:
        p = r["params"]
        try:
            n = client.messages.count_tokens(model=model, system=p["system"], messages=p["messages"],
                                             output_config={"format": p["output_config"]["format"]}).input_tokens
        except TypeError:                                         # an SDK without output_config on count_tokens
            n = client.messages.count_tokens(model=model, system=p["system"], messages=p["messages"]).input_tokens
            schema_allow = 1500                                   # the schema's own prompt tokens, a generous allowance
        ins.append(n + schema_allow)
    sys_tok = client.messages.count_tokens(model=model, system=reqs[0]["params"]["system"],
                                           messages=[{"role": "user", "content": "x"}]).input_tokens
    n_stories = sum(len(r["ids"]) for r in reqs)
    avg_in = sum(ins) / len(ins)
    usage = {"input_tokens": (avg_in - sys_tok) * len(reqs), "cache_read_input_tokens": sys_tok * len(reqs),
             "output_tokens": out_per_story * n_stories}
    return {"requests": len(reqs), "stories": n_stories, "avg_input_tokens": round(avg_in), "system_tokens": sys_tok,
            "usd": round(cost(usage, model), 4), "assumed_output_per_story": out_per_story}


def label(client, reqs: list[dict], run: Run, cap_usd: float, tranche: int = 400, poll_s: int = 60,
          say=print, sleep=time.sleep, max_wait_s: int = 6 * 3600) -> dict:
    """Send the requests not yet labelled, a tranche at a time, under the cap. Returns the run's totals."""
    todo = [r for r in reqs if not all(i in run.done for i in r["ids"])]
    say(f"{len(todo)} of {len(reqs)} requests still to label; spent so far ${run.state['spent']:.4f} of ${cap_usd:.2f}")
    per_req = None
    for start in range(0, len(todo), tranche):
        part = todo[start:start + tranche]
        projected = (per_req or 0) * len(part)
        if per_req is not None and run.state["spent"] + projected > cap_usd:
            n_fit = int((cap_usd - run.state["spent"]) / per_req) if per_req > 0 else 0
            if n_fit < 1:
                say(f"cap reached: ${run.state['spent']:.4f} spent, the next tranche would cost ~${projected:.4f}; stopping")
                break
            part = part[:n_fit]
        batch = client.messages.batches.create(requests=[{"custom_id": r["custom_id"], "params": r["params"]} for r in part])
        say(f"batch {batch.id}: {len(part)} requests")
        waited = 0
        while True:
            b = client.messages.batches.retrieve(batch.id)
            if b.processing_status == "ended":
                break
            if waited > max_wait_s:
                say(f"batch {batch.id} still running after {waited}s; the next run collects it")
                return run.state
            sleep(poll_s)
            waited += poll_s
        by_id = {r["custom_id"]: r for r in part}
        labels, spent, bad = [], 0.0, 0
        for res in client.messages.batches.results(batch.id):
            r = by_id.get(res.custom_id)
            if r is None:
                continue
            if res.result.type != "succeeded":
                bad += 1
                continue
            msg = res.result.message
            spent += cost(msg.usage, run.model)
            if msg.stop_reason != "end_turn":
                bad += 1
                continue
            text = next((blk.text for blk in msg.content if blk.type == "text"), "")
            labels.extend(parse(text, r["ids"]))
        run.save(labels, spent, batch.id, len(part))
        per_req = spent / max(1, len(part))
        say(f"  {len(labels)} labels, {bad} requests failed, ${spent:.4f} (per request ${per_req:.5f}); "
            f"total ${run.state['spent']:.4f}")
    return run.state


def audit_sample(stories: pd.DataFrame, n: int = 1500, seed: int = 7) -> pd.DataFrame:
    """A stratified sample for the Opus check: equal shares from each year and source, so rare kinds are in it too."""
    s = stories.copy()
    s["stratum"] = pd.to_datetime(s["ts"], utc=True).dt.year.astype(str) + "|" + s["source"]
    groups = list(s.groupby("stratum"))
    per = math.ceil(n / max(1, len(groups)))
    rng = random.Random(seed)
    take = []
    for _, g in groups:
        idx = list(g.index)
        rng.shuffle(idx)
        take.extend(idx[:per])
    return s.loc[sorted(take)].drop(columns="stratum").head(n)


def smoke(client, stories: pd.DataFrame, model: str = HAIKU, n: int = 6) -> dict:
    """One small live request (not a batch) to prove the instructions, the schema and the parsing work end to end
    before any money is spent at scale. Costs a fraction of a cent."""
    req = requests_for(stories.head(n), model, per=n)[0]
    p = req["params"]
    msg = client.messages.create(**p)
    text = next((b.text for b in msg.content if b.type == "text"), "")
    labels = parse(text, req["ids"])
    return {"model": msg.model, "stop": msg.stop_reason, "labels": labels, "usage": msg.usage.model_dump() if hasattr(msg.usage, "model_dump") else str(msg.usage),
            "usd_at_standard_price": round(cost(msg.usage, model, batch=False), 6), "estimate": estimate(client, [req], model, sample=1)}
