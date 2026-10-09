"""Phase K: open the app's trade-detail sheet ("Why this trade" / history row → openTrade) for one trade and capture it.

    python audit/probes/phase_k_trade_sheet.py SITE_DIR TRADE_ID OUT_PREFIX CLOCK
"""
import json
import sys
from pathlib import Path

from phase_j_shoot import CHROME, serve
from playwright.sync_api import sync_playwright


def main(site, tid, prefix, clock):
    srv = serve(Path(site))
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        page = b.new_context(viewport={"width": 430, "height": 2600}, timezone_id="Asia/Kolkata",
                             service_workers="block").new_page()
        page.clock.install(time=clock)
        page.goto(f"http://127.0.0.1:{srv.server_port}/index.html")
        page.wait_for_timeout(2500)
        page.evaluate("go('trades/history')")
        page.wait_for_timeout(1500)
        page.screenshot(path=f"{prefix}_history.png", full_page=True)
        hist = page.inner_text("main")
        page.evaluate(f"openTrade({json.dumps(tid)})")
        page.wait_for_timeout(2000)
        page.locator("#sheet").screenshot(path=f"{prefix}_sheet.png")
        sheet = page.inner_text("#sheet")
        b.close()
    srv.shutdown()
    Path(f"{prefix}_text.json").write_text(json.dumps({"history": hist, "sheet": sheet}, indent=1, ensure_ascii=False))
    print(sheet[:3000])


if __name__ == "__main__":
    main(*sys.argv[1:5])
