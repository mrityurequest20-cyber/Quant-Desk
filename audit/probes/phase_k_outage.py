"""Phase K: the published site through a data.json outage and recovery, and through a stuck (never-updated) data.json.

Serves SITE_A's app over 127.0.0.1 and intercepts every data.json request (Playwright routing): serve A, fail with
HTTP 503, then serve B. The clock is Playwright's fake clock, advanced with run_for so the app's own 15-s refresh
timer and the shim's 60-s cache run as they would. Read-only; no network beyond 127.0.0.1.

    python audit/probes/phase_k_outage.py SITE_A SITE_B OUT_PREFIX "2026-10-05T12:20:30+05:30"
"""
import json
import sys
from pathlib import Path

from phase_j_shoot import CHROME, serve
from playwright.sync_api import sync_playwright


def main(site_a: Path, site_b: Path, prefix: str, start: str):
    A, B = (site_a / "data.json").read_bytes(), (site_b / "data.json").read_bytes()
    srv = serve(site_a)
    mode = {"m": "A"}
    log = []

    def route(r):
        if mode["m"] == "fail":
            r.fulfill(status=503, body="Service Unavailable")
        else:
            r.fulfill(status=200, body=A if mode["m"] == "A" else B, headers={"Content-Type": "application/json"})

    def cap(page, step, note):
        page.wait_for_timeout(400)
        st = page.inner_text("#status").replace("\n", " ")
        banner = page.locator("#d-banner").inner_text().strip().replace("\n", " ")
        now = page.locator("#d-now").inner_text().strip().replace("\n", " / ")[:160]
        page.screenshot(path=f"{prefix}_{step}.png", clip={"x": 0, "y": 0, "width": 430, "height": 760})
        log.append({"step": step, "note": note, "data_json_mode": mode["m"], "status_pill": st, "banner": banner, "now": now,
                    "fake_clock": page.evaluate("new Date().toISOString()")})

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        for scenario in ("outage", "stuck"):
            ctx = b.new_context(viewport={"width": 430, "height": 900}, timezone_id="Asia/Kolkata", service_workers="block")
            page = ctx.new_page()
            page.route("**/data.json*", route)
            page.clock.install(time=start)
            mode["m"] = "A"
            page.goto(f"http://127.0.0.1:{srv.server_port}/index.html")
            page.wait_for_timeout(2500)
            cap(page, f"{scenario}_1_loaded", "data.json = A (fresh)")
            if scenario == "outage":
                mode["m"] = "fail"
                page.clock.run_for(70_000)
                cap(page, "outage_2_failing_70s", "data.json → HTTP 503 for 70 s")
                page.clock.run_for(60_000)
                cap(page, "outage_3_failing_130s", "still 503")
                mode["m"] = "B"
                page.clock.run_for(70_000)
                cap(page, "outage_4_recovered", "data.json = B (the next real snapshot)")
            else:
                page.clock.run_for(16 * 60_000)
                cap(page, "stuck_2_16min", "data.json reachable but never updated (still A) for 16 min")
            ctx.close()
        b.close()
    srv.shutdown()
    Path(f"{prefix}_log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(log, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4])
