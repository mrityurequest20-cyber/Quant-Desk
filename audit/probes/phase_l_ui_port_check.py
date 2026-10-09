"""Phase L: validate the Python port of app.js readAction/renderNow against Phase K's Chromium renders (read-only).

For every Phase K timeline snapshot that was rendered (audit/data/phase_k_screens/k10DD_<label>_*_text.json), load the
published data.json it was rendered from and check that the port's headline and every per-index line appear in the
text Chromium actually rendered.

    python audit/probes/phase_l_ui_port_check.py PHK_DIR OUT.json      (PHK_DIR holds tl_1005/, tl_1008/)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from phase_l_consistency import render_now  # noqa: E402

SCREENS = HERE.parent / "data" / "phase_k_screens"


def main(phk: Path, out: Path):
    rows = []
    for t in sorted(SCREENS.glob("k10*_text.json")):
        day, rest = t.name[1:5], t.name[6:]
        label = "_".join(rest.split("_")[:-2])
        site = phk / f"tl_{day}" / label / "data.json"
        if not site.exists():
            continue
        st = json.loads(site.read_text())["state"]
        port = render_now(st.get("heartbeat") or {}, bool(st.get("paused")))
        desk = " ".join(json.loads(t.read_text())["desk"].split())
        lines = {s: f"{s} {x}" for s, x in port["lines"].items()}
        rows.append({"render": t.name, "port_head": port["head"], "head_in_render": port["head"] in desk,
                     "lines_in_render": {s: " ".join(x.split()) in desk for s, x in lines.items()}})
    ok = all(r["head_in_render"] and all(r["lines_in_render"].values()) for r in rows)
    res = {"compared": len(rows), "all_match": ok, "rows": rows}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps({"compared": len(rows), "all_match": ok}))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
