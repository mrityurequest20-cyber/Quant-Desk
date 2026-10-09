"""Phase L: analyse phase_l_consistency.py outputs — contradiction counts with denominators (read-only).

    python audit/probes/phase_l_consistency_analyze.py OUT.json cons_1005_bar.json cons_1005_tick.json ...
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase_l_consistency import read_action  # noqa: E402

PUP = re.compile(r"is (\S+) with EV .*? at P\(up\) ([\d.]+) \[([^\]]+)\]")


def ui_p_used(q: dict) -> str:
    """app.js:755 'P(up) used'."""
    return f"{round(q['p_model'] * 100)}%" if q.get("valid") and q.get("p_model") is not None else "coin flip + prior"


def analyse(r: dict) -> dict:
    mins = {m["ts"]: m for m in r["minutes"]}
    order = [m["ts"] for m in r["minutes"]]
    ticks = defaultdict(list)
    for t in r["tick_heartbeats"]:
        ticks[t["ts"]].append(t)
    after = Counter()
    ex = defaultdict(list)
    vis = Counter()
    for f in r["fires"]:
        u = f["symbol"]
        # the first heartbeat written after the fire: the tick's own (live path) or the minute step's (bar path)
        hb = (ticks.get(f["ts"]) or [None])[0] if f["mode"] == "tick" else mins.get(f["ts"])
        if hb is None:
            after["no_heartbeat_after_fire"] += 1
            continue
        act = hb["hb_actions"].get(u) or ""
        k = read_action(act)["kind"]
        armed_u = [a for a in hb["hb_armed"] if a[0] == u]
        same = any(a[1] == f["setup"] and abs(a[2] - f["level"]) < 0.006 for a in armed_u)
        shown = "reached its level" in act
        vis["outcome_in_heartbeat_action"] += shown
        vis["outcome_in_thought"] += f["thought_rows"] > 0
        vis["decision_row_written"] += f["decision_rows"] > 0
        if k == "armed" and not armed_u:
            c = "stale_armed_action_empty_armed_list"
        elif k == "armed" and same:
            c = "rearmed_same_setup_same_level"            # K-01
        elif k == "armed":
            c = "rearmed_other"
        elif k == "watch" and "no setup has triggered" in act:
            c = "watching_no_setup_has_triggered"          # K-02
        elif k == "aside":
            c = "standing_aside_other_reason"
        else:
            c = f"other:{k}"
        after[c] += 1
        if len(ex[c]) < 3:
            ex[c].append({"fire_ts": f["ts"], "symbol": u, "setup": f["setup"], "level": f["level"], "returned": f["returned"],
                          "hb_ts": hb["hb_ts"], "hb_action": act[:140], "ui_head": hb["ui"]["head"], "ui_line": hb["ui"]["lines"].get(u)})
        # the next minute step after a tick fire: what the screen settles on
        if f["mode"] == "tick":
            nxt = next((mins[t] for t in order if t > f["ts"]), None)
            if nxt:
                a2 = nxt["hb_actions"].get(u) or ""
                after["next_minute:" + ("rearmed_same_level" if any(x[0] == u and x[1] == f["setup"] and abs(x[2] - f["level"]) < 0.006 for x in nxt["hb_armed"])
                                        else read_action(a2)["kind"] + (":no_setup" if "no setup has triggered" in a2 else ""))] += 1

    # every stepped minute: screen-level contradictions
    scan = Counter()
    for m in r["minutes"] + r["tick_heartbeats"]:
        lab = "tick_hb" if m["kind"] == "tick" else "minute"
        scan[f"{lab}:total"] += 1
        rej = {d["symbol"] for d in m["decisions"] if d["detail"].startswith(tuple(f"{s} reached its level" for s in ("orb", "trend_break", "vwap_trend")))}
        for u, act in m["hb_actions"].items():
            k = read_action(act)["kind"]
            armed_u = [a for a in m["hb_armed"] if a[0] == u]
            if k == "armed" and not armed_u:
                scan[f"{lab}:symbol_line_waiting_at_level_but_nothing_armed"] += 1
            if u in rej and k == "armed":
                scan[f"{lab}:rejected_this_minute_shown_waiting_at_level"] += 1
            if u in rej and "no setup has triggered" in (act or ""):
                scan[f"{lab}:rejected_this_minute_shown_no_setup_triggered"] += 1
        if rej and m["ui"]["head"].startswith("Watching · no setup has triggered"):
            scan[f"{lab}:headline_no_setup_triggered_in_a_rejection_minute"] += 1
        if len(m["hb_armed"]) > 1:
            scan[f"{lab}:multiple_armed"] += 1
            if len({a[0] for a in m["hb_armed"]}) > 1:
                scan[f"{lab}:multiple_armed_symbols_headline_names_one"] += 1
        exp = [a for a in m["hb_armed"] if a[3] < m["ts"]]
        if exp:
            scan[f"{lab}:expired_armed_in_heartbeat"] += 1
        if m["kind"] == "minute" and m["hb_armed"]:
            scan["minute:with_armed"] += 1

    # EV floor: the P(up) in the message vs the P(up) passed to the evaluator vs the app's 'P(up) used'
    ev = Counter()
    evx = []
    calls = defaultdict(list)
    for c in r["ev_calls"]:
        calls[(c["ts"], c["symbol"], c["structure"])].append(c)
    for m in r["minutes"]:
        for d in m["decisions"]:
            g = PUP.search(d["detail"]) if d["detail"].startswith("EV below") else None
            if not g:
                continue
            ev["ev_rejections"] += 1
            struct, p_msg, src = g.group(1), float(g.group(2)), g.group(3)
            used = calls.get((d["ts"], d["symbol"], struct)) or []
            p_used = used[0]["p_up_arg"] if used else None
            sc = m["hb_score"].get(d["symbol"])
            q = m["hb_quant"].get(d["symbol"]) or {}
            ui = ui_p_used(q)
            ev["src:" + src.split(" (")[0]] += 1
            if p_used is None:
                ev["evaluator_call_not_matched"] += 1
            elif abs(p_used - p_msg) > 0.006:
                ev["message_p_differs_from_p_used"] += 1
                if used[0]["direction"] == 0:
                    ev["…of_which_nondirectional_structure_used_0.5"] += 1
            if "prior tilt" in src and sc is not None and abs(0.5 + max(-0.1, min(0.1, 0.1 * sc)) - p_msg) > 0.006:
                ev["message_p_not_prior_tilt_of_heartbeat_score"] += 1
            ev["ui_p_used_shows_number"] += ui.endswith("%")
            ev["ui_p_used_shows_coin_flip_while_message_has_number"] += ui == "coin flip + prior"
            if q.get("valid") and q.get("p_model") is not None and abs(q["p_model"] - p_msg) > 0.006:
                ev["ui_number_differs_from_p_used(clip_0.35_0.65)"] += 1
            if len(evx) < 3:
                evx.append({"ts": d["ts"], "symbol": d["symbol"], "structure": struct, "p_msg": p_msg, "p_used": p_used,
                            "src": src, "ui_p_used": ui, "hb_score": sc})
    return {"day": r["day"], "mode": r["mode"], "evidence_class": r["evidence_class"],
            "denominators": {"stepped_minutes": len(r["minutes"]), "tick_heartbeats": len(r["tick_heartbeats"]),
                             "armed_trigger_hits": len(r["fires"]), "ev_calls": len(r["ev_calls"])},
            "fire_outcomes": r["outcomes"], "outcome_visibility": dict(vis), "screen_after_fire": dict(after),
            "examples": ex, "minute_scan": dict(scan), "ev_pup": dict(ev), "ev_examples": evx,
            "expired_at_fire": len(r["expired_at_fire"])}


def main(out: Path, files):
    res = [analyse(json.loads(Path(f).read_text())) for f in files]
    tot = defaultdict(Counter)
    for x in res:
        for k in ("denominators", "fire_outcomes", "outcome_visibility", "screen_after_fire", "minute_scan", "ev_pup"):
            tot[(x["mode"], k)].update(x[k])
    summary = {f"{m}:{k}": dict(v) for (m, k), v in tot.items()}
    out.write_text(json.dumps({"per_session": res, "totals_by_mode": summary}, indent=1, default=str))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])
