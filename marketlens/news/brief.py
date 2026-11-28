"""The situation analyzer's written half: one brief per running situation, by Claude Opus 5.5, once (the owner's $13
budget, shared with the labelling run: label.TOTAL_BUDGET).

Each brief is written from the situation's own dated timeline (situations.py: every flare-up episode with its top
headlines and its MEASURED market reaction, the base rates across episodes, the latest stories) and answers what an
analyst asks of a live situation:

  * where it stands now: escalating, de-escalating, stable or dormant, and what changed most recently
  * its history: the episodes that mattered, what happened in each, and what markets did (quoted from the table)
  * the sides: for each actor (US, Iran, Israel ...) its aims and its plausible next moves, with how markets have taken
    moves of that kind before
  * the escalation ladder and today's rung
  * scenarios: what could happen next, the trigger, how often something like it happened in the record (counted from the
    episode table, never invented), and the path for India: macro (crude, rupee, yields, flows, VIX) and micro (the
    sector baskets), and options (IV)
  * the transmission chain to India, link by link, with each link's measured strength where the table has it
  * what to watch, and the caveats (thin history, a regime that has changed)

Rule the model is held to: every number in a brief comes from the tables it was given; anything else is words.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .label import OPUS, PRICE, BATCH, TOTAL_BUDGET, cost

S = {"type": "string"}
SA = {"type": "array", "items": S}


def _obj(props: dict, req=None) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": req or list(props)}


SCHEMA = _obj({
    "summary": S,
    "current_state": _obj({"phase": {"type": "string", "enum": ["escalating", "de-escalating", "stable", "dormant"]},
                           "as_of": S, "what_changed": S, "ladder_rung": {"type": "integer"}}),
    "ladder": SA,
    "history": {"type": "array", "items": _obj({"date": S, "what_happened": S, "markets": S})},
    "sides": {"type": "array", "items": _obj({"side": S, "aims": S, "next_moves": {"type": "array", "items": _obj(
        {"move": S, "likelihood": {"type": "string", "enum": ["low", "medium", "high"]}, "market_effect": S})}})},
    "scenarios": {"type": "array", "items": _obj({"name": S, "trigger": S, "likelihood": {"type": "string", "enum": ["low", "medium", "high"]},
                                                  "precedent": S, "india_macro": S, "india_micro": S, "options": S})},
    "transmission": {"type": "array", "items": _obj({"from": S, "to": S, "mechanism": S, "evidence": S})},
    "watch": SA,
    "caveats": SA,
})

SYSTEM = """You are a senior macro and geopolitical analyst for an Indian derivatives desk. You write a brief on one
running situation (a conflict, a trade dispute, a policy cycle) for someone who trades NIFTY, BANKNIFTY and large Indian
stocks and their options. The brief explains the situation's history, where it stands, what each side can do next,
and what each path would mean for Indian markets, macro and micro.

You are given the situation's dated timeline: every flare-up episode found in the news since 2019 with its top
headlines and the market reaction MEASURED after it (log returns as decimals: 0.031 = +3.1%; yields in basis points;
VIX in points; "vs NIFTY: <basket>" is that sector basket's return minus NIFTY's), base rates across episodes (median,
share of episodes up, n; kept_at_20 = the 20-session move as a share of the 5-session move: below 1 means it faded),
and the latest headlines.

Rules:
1. Every number you write must come from the tables given. Quote it with its horizon and n ("Brent +4.1% at 5 sessions,
   median of 7 episodes"). If the table does not have it, say it in words without a number. Never invent a statistic.
2. "precedent" in a scenario counts episodes from the table that resemble it, by date ("3 of 9 episodes: 2020-01-03,
   2024-04-13, 2025-06-13"); say "no precedent in the record" when there is none.
3. Separate what is known from the headlines from your judgement. Likelihoods are your judgement: low / medium / high.
4. Be concrete about India: crude import bill, rupee, inflation, RBI, fiscal (fuel taxes and subsidies), foreign flows,
   and the named sector baskets. Mention options (IV) where the table shows how India VIX moved.
5. current_state.as_of is the date of the latest headline given; ladder_rung indexes into your ladder (0 = calmest).
6. Plain, precise English. No advice to buy or sell."""


def payload(sid: str, sit: dict, recent: list[dict], max_eps: int = 40) -> str:
    eps = sit["episodes"][-max_eps:]
    lines = [f"SITUATION: {sit['name']} ({sid})", f"Sides: {', '.join(sit['sides'])}",
             f"Stories in the record: {sit['stories']} from {sit['first']} to {sit['last']}; {len(sit['episodes'])} flare-up episodes.", "",
             "EPISODES (start date, stories that week, top headlines, measured reaction by horizon in sessions):"]
    for e in eps:
        lines.append(f"- {e['start']} ({e['stories']} stories): " + " | ".join(e["headlines"]))
        lines.append("  reaction: " + json.dumps(_round(e["reaction"]), separators=(",", ":")))
    lines += ["", "BASE RATES ACROSS EPISODES:", json.dumps(_round(sit["base_rates"]), separators=(",", ":")), "",
              "LATEST HEADLINES (newest last):"]
    lines += [f"- {r['date']}: {r['title']}" for r in recent[-60:]]
    return "\n".join(lines)


def _round(x):
    if isinstance(x, dict):
        return {str(k): _round(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v) for v in x]
    if isinstance(x, float):
        return round(x, 4)
    return x


def requests_for(analysis: dict, recent: dict[str, list[dict]], model: str = OPUS) -> list[dict]:
    out = []
    for sid, sit in analysis.items():
        if not sit["episodes"] and not recent.get(sid):
            continue
        out.append({"custom_id": sid.replace(":", "_"), "sid": sid,
                    "params": {"model": model, "max_tokens": 16000, "system": SYSTEM,
                               "messages": [{"role": "user", "content": payload(sid, sit, recent.get(sid, []))}],
                               "output_config": {"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}}}})
    return out


def write(client, reqs: list[dict], out: Path, spent_elsewhere: float, cap: float, say=print, sleep=time.sleep, poll_s=60) -> dict:
    """Send every brief not yet written as one batch, if its projected cost fits under the budget; save each brief."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    state_p = out / "state_briefs.json"
    state = json.loads(state_p.read_text()) if state_p.exists() else {"spent": 0.0, "batches": []}
    todo = [r for r in reqs if not (out / f"brief_{r['custom_id']}.json").exists()]
    if not todo:
        say("every brief is already written")
        return state
    room = min(cap, TOTAL_BUDGET - spent_elsewhere) - state["spent"]
    projected = sum(len(r["params"]["messages"][0]["content"]) / 3.5 * PRICE[OPUS]["in"] + 12000 * PRICE[OPUS]["out"] for r in todo) / 1e6 * BATCH
    say(f"{len(todo)} briefs to write, projected ~${projected:.2f}; room ${room:.2f}")
    if projected > room:
        say("not sent: the projected cost does not fit the budget left")
        return state
    batch = client.messages.batches.create(requests=[{"custom_id": r["custom_id"], "params": r["params"]} for r in todo])
    while client.messages.batches.retrieve(batch.id).processing_status != "ended":
        sleep(poll_s)
    by = {r["custom_id"]: r for r in todo}
    spent = 0.0
    for res in client.messages.batches.results(batch.id):
        if res.result.type != "succeeded":
            continue
        msg = res.result.message
        spent += cost(msg.usage, OPUS)
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            brief = json.loads(text)
        except ValueError:
            continue
        r = by[res.custom_id]
        (out / f"brief_{res.custom_id}.json").write_text(json.dumps({"situation": r["sid"], "model": msg.model, "brief": brief}, ensure_ascii=False, indent=1))
    state["spent"] = round(state["spent"] + spent, 6)
    state["batches"].append({"id": batch.id, "n": len(todo), "cost": round(spent, 6)})
    state_p.write_text(json.dumps(state, indent=1))
    say(f"briefs written; ${spent:.4f} this batch, ${state['spent']:.4f} in all")
    return state
