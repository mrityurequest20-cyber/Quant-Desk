"""Phase J: open a built site in headless Chromium (Playwright), at a fixed IST clock, and save a screenshot and the
visible text of each tab. Read-only: serves a local folder on 127.0.0.1; no network access is needed.

    python audit/probes/phase_j_shoot.py SITE_DIR OUT_PREFIX "2026-10-09T15:29:30+05:30" [tabs...]
"""
import functools
import http.server
import json
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def serve(folder: Path):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    h.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main(site: Path, prefix: str, clock: str, tabs: list[str]):
    srv = serve(site)
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        ctx = b.new_context(viewport={"width": 430, "height": 2400}, timezone_id="Asia/Kolkata", service_workers="block")
        page = ctx.new_page()
        page.clock.install(time=clock)
        page.goto(f"http://127.0.0.1:{srv.server_port}/index.html")
        page.wait_for_timeout(2500)
        for tab in tabs:
            page.evaluate(f"go({json.dumps(tab)})")
            page.wait_for_timeout(1500)
            page.screenshot(path=f"{prefix}_{tab.replace('/', '-')}.png", full_page=True)
            out[tab] = page.inner_text("main")
        out["status_pill"] = page.inner_text("#status")
        b.close()
    srv.shutdown()
    Path(f"{prefix}_text.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v[:300] for k, v in out.items()}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4:] or ["desk", "brain", "feed"])
