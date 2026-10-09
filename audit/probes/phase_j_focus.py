"""Phase J: screenshot just the UI group (.grp / .panel / .nowbar / #status) that contains a given text, on a given tab.

    python audit/probes/phase_j_focus.py SITE_DIR OUT_PNG CLOCK TAB "text to find"
"""
import json
import sys
from pathlib import Path

from phase_j_shoot import CHROME, serve
from playwright.sync_api import sync_playwright


def main(site, out_png, clock, tab, text):
    srv = serve(Path(site))
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        page = b.new_context(viewport={"width": 430, "height": 1600}, timezone_id="Asia/Kolkata",
                             service_workers="block").new_page()
        page.clock.install(time=clock)
        page.goto(f"http://127.0.0.1:{srv.server_port}/index.html")
        page.wait_for_timeout(2500)
        page.evaluate(f"go({json.dumps(tab)})")
        page.wait_for_timeout(1500)
        el = page.get_by_text(text, exact=False).first
        box = el.locator("xpath=ancestor-or-self::*[contains(concat(' ',@class,' '),' grp ') or contains(concat(' ',@class,' '),' panel ') "
                         "or contains(concat(' ',@class,' '),' nowbar ') or @id='status'][1]")
        target = box if box.count() else el
        target.scroll_into_view_if_needed()
        target.screenshot(path=out_png)
        print(out_png, "|", target.inner_text()[:400].replace("\n", " | "))
        b.close()
    srv.shutdown()


if __name__ == "__main__":
    main(*sys.argv[1:6])
