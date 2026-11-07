"""The web app as a read-only static site, in two shapes.

export_site   ONE self-contained HTML file with the account's data embedded (a frozen snapshot):
                  python -m quantdesk intraday export-site --account synthetic --out site.html
publish_site  a folder (index.html, app.js, data.json, fonts, PWA manifest + icons + service worker)
              whose page re-fetches data.json every minute; re-publish it every few minutes while the
              desk runs and the site stays live. Installable as an app on a phone (Add to Home Screen).
              This is what the GitHub Actions workflow pushes to GitHub Pages:
                  python -m quantdesk intraday export-site --dir _site

Either way a small shim answers the app's /api/i/* calls from the data, and the controls are
off (a static site has no engine behind it to command).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
from pathlib import Path


from .intraday_api import IntradayAPI


def _clean(o):
    """JSON-safe: numpy numbers to Python, non-finite floats to null, timestamps to strings (moved from the retired
    desk server)."""
    import math

    import numpy as np
    import pandas as pd
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, (pd.Timestamp,)):
        return str(o)
    return o

STATIC = Path(__file__).resolve().parent / "static" / "app"
CHART_LIB = Path(__file__).resolve().parent / "static" / "vendor" / "lightweight-charts.js"
FONTS = STATIC / "fonts"
ICONS = ("icon.svg", "icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png")      # all drawn from icon.svg (deploy/make_icons.mjs)

# Answers the app's /api/i/* calls from one data object D (same JSON the server would return).
ROUTES = r"""
function qdAnswer(D, url) {
  const reply = (obj, status) => new Response(JSON.stringify(obj), { status: status || 200, headers: { "Content-Type": "application/json" } });
  const u = new URL(String(url), "https://snapshot.local/");
  const q = Object.fromEntries(u.searchParams.entries());
  switch (u.pathname) {
    case "/api/i/accounts": return reply([{ id: "snapshot", label: D.short || "Snapshot" }]);
    case "/api/i/state": {
      const ts = D.state.heartbeat && D.state.heartbeat.ts;
      // a published desk ages in real time (no heartbeat yet = offline); a frozen snapshot never goes stale
      // Safari rejects a space separator and more than 3 fractional digits: normalise before parsing
      const t = ts ? Date.parse(String(ts).trim().replace(" ", "T").replace(/(\.\d{3})\d+/, "$1")) : NaN;
      const age = !D.live ? 0 : isFinite(t) ? Math.max(0, (Date.now() - t) / 1000) : null;
      return reply(Object.assign({}, D.state, { age_sec: age }));
    }
    case "/api/i/trades": return reply(D.trades.slice(0, Number(q.n || 100)));
    case "/api/i/trade": return D.trade[q.id] ? reply(D.trade[q.id]) : reply({ error: "trade details not in this snapshot" }, 404);
    case "/api/i/reviews": return reply(Object.keys(D.reviews).sort().reverse());
    case "/api/i/review": return D.reviews[q.date] ? reply({ date: q.date, markdown: D.reviews[q.date] }) : reply({ error: "no such review" }, 404);
    case "/api/i/stats": return reply(D.stats);
    // the pre-market brief lives on its own branch (premarket.yml), fetched as it is, not through data.json
    case "/api/i/premarket": return D.premarket_url && window.qdRealFetch ? window.qdRealFetch(D.premarket_url, { cache: "no-cache" })
      : reply({ error: "no pre-market brief on this site" }, 404);
    case "/api/config": return reply({ gocharting: { enabled: false } });
    default: return reply({ error: "not available on a read-only site" }, 404);
  }
}
"""

# one-file snapshot: the data is embedded in the page
SHIM = ROUTES + r"""
window.QD_DEMO = true;
(function () {
  const D = JSON.parse(document.getElementById("qd-data").textContent);
  window.qdRealFetch = window.fetch.bind(window);
  window.fetch = async (url) => qdAnswer(D, url);
})();
"""

# published site: the page fetches data.json (re-published every few minutes while the desk runs)
LIVE_SHIM = ROUTES + r"""
window.QD_DEMO = true;
window.QD_PUBLISHED = true;
(function () {
  const realFetch = window.fetch.bind(window);
  window.qdRealFetch = realFetch;
  let D = null, at = 0, pending = null;
  function load() {
    if (pending) return pending;
    if (D && Date.now() - at < 60000) return Promise.resolve(D);
    // no-cache = revalidate with the server (ETag), so an unchanged file costs a 304, not a download
    pending = realFetch("data.json", { cache: "no-cache" })
      .then((r) => { window.QD_OFFLINE_CACHE = r.headers.get("X-QD-Offline-Cache") === "1"; if (!r.ok) throw new Error("data.json: HTTP " + r.status); return r.json(); })
      .then((d) => { D = d; at = Date.now(); return D; })
      .catch((e) => { window.QD_OFFLINE_CACHE = true; if (!D) throw e; return D; })
      .finally(() => { pending = null; });
    return pending;
  }
  // The live relay (/live/*, the Worker's private price feed) is the one thing here that is NOT in data.json: it goes to the real network with its own headers (the key).
  // Without this the shim answered it with "not available on a read-only site" (a 404) and the Live tab could never reach the relay.
  window.fetch = async (url, init) => {
    let path = "";
    try { path = new URL(String(url), window.location.href).pathname; } catch (e) { /* not a URL: the shim answers it */ }
    if (path.startsWith("/live/")) return realFetch(url, init);
    return qdAnswer(await load(), url);
  };
  window.qdReload = () => { at = 0; return load(); };        // pull-to-refresh: skip the 60 s cache
})();
"""


def _body_and_style(html: str) -> tuple[str, str]:
    style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    body = re.sub(r"<script[^>]*></script>\s*", "", body)
    return style, body


def _setups_block(api, account: str) -> dict:
    """P0.7: the labelled-setup count (ml/setups.py) for `data.json`, which the watchdog's Saturday digest reads. Read-only on the journal and the learning
    memory; if anything at all goes wrong it says so in the block instead of failing the publish."""
    import datetime as _dt
    try:
        from ..ml import setups as SETUPS
        d = api._dir(account)
        return SETUPS.block(d / "journal.db", d / "memory.json", _dt.datetime.now(SETUPS.IST).date())
    except Exception as exc:                                    # a digest line is never worth a missed publish
        return {"line": None, "error": type(exc).__name__}


def premarket_url(cfg) -> str | None:
    """Where the published app reads the pre-market brief: config `premarket.url`, else the repository's `premarket`
    branch on GitHub (premarket.yml publishes it there), else none (a local snapshot has no branch to read)."""
    url = cfg.get("premarket.url")
    repo = os.environ.get("GITHUB_REPOSITORY")
    return url or (f"https://raw.githubusercontent.com/{repo}/premarket/brief.json" if repo else None)


def site_data(cfg, account: str, sessions: int = 3, label: str | None = None, live: bool = False,
              max_trade_details: int = 150) -> dict:
    """Everything the app reads, as one JSON-able object (the same shapes the server's API returns). The retired desk's thoughts, news and charts are no longer
    published (the app has no tab that shows them); `sessions` stays for the command line."""
    api = IntradayAPI(cfg)
    if live and not (api._dir(account) / "journal.db").exists():
        # the live site goes up before the desk's first minute: publish an empty desk, not an error
        from ..journal.journal import Journal
        api._dir(account).mkdir(parents=True, exist_ok=True)
        Journal(api._dir(account) / "journal.db").commit()
    state = api.state(account)
    since = cfg.get("app.history_since")                         # the History tab starts here (the journal is untouched: this only limits what is published)
    trades = api.trades(account, 1000, since)
    short = "Live paper" if live else ("Demo" if account == "synthetic" else "Snapshot")
    return {
        "label": label or ("Live paper desk" if live else f"{account.capitalize()} snapshot"),
        "short": short, "live": live,
        "state": {**state, "age_sec": 0},
        "setups": _setups_block(api, account),
        "trades": trades,
        "trade": {t["id"]: api.trade(account, t["id"]) for t in trades[:max_trade_details]},
        "reviews": {d: api.review(account, d)["markdown"] for d in api.reviews(account, since)},
        "stats": api.stats(account, since),
        "history_since": since,
        "premarket_url": premarket_url(cfg),
    }


def _json(data) -> str:
    return json.dumps(_clean(data), separators=(",", ":"))


def trade_config(cfg) -> dict:
    """What the app's strategy builder needs from the config, so it has one source of truth: the paper account's size, the desk's risk limits, the cost model, the slippage model, the
    risk-free rate, and each index's lot size and strike step. Read-only data; nothing here can place an order."""
    risk = cfg.get("intraday.risk", {}) or {}
    keys = ("risk_per_trade", "max_premium_outlay", "max_total_outlay", "max_lots", "max_open", "max_spread_pct", "max_margin", "credit_margin_per_lot", "daily_loss_limit")
    costs = cfg.get("costs", {}) or {}
    opt = (costs.get("segments") or {}).get("options", {}) or {}
    slip = cfg.get("slippage", {}) or {}
    inst = {u: {"lot": int(v["lot_size"]), "step": float(v["strike_step"])} for u, v in (cfg.get("instruments") or {}).items()
            if isinstance(v, dict) and v.get("kind") == "index" and "lot_size" in v and "strike_step" in v}
    return {"equity": float(cfg.get("intraday.capital")), "r": float(cfg.get("backtest.risk_free", 0.065)),
            "limits": {k: risk[k] for k in keys if k in risk},
            "costs": {"brokerage_per_order": float(costs.get("brokerage_per_order", 20.0)), "gst": float(costs.get("gst", 0.18)), "sebi_per_crore": float(costs.get("sebi_per_crore", 10.0)),
                      "options": {k: float(opt.get(k, 0.0)) for k in ("stt_buy", "stt_sell", "exchange", "stamp_buy")}},
            "slippage": {k: float(slip[k]) for k in ("option_half_spread_pct", "option_min_half_spread", "option_tick") if k in slip},
            "inst": inst}


def _trade_script(cfg) -> str:
    return "<script>window.QD_TRADE=" + json.dumps(trade_config(cfg), separators=(",", ":")).replace("</", "<\\/") + ";</script>"


def _meta(label: str, note: str) -> str:
    """The site's label and footnote, as data the app renders with textContent (never as HTML)."""
    js = f"window.QD_LABEL={json.dumps(label)};window.QD_NOTE={json.dumps(note)};"
    return "<script>" + js.replace("</", "<\\/") + "</script>"


def _font_data_uris(css: str) -> str:
    """The one-file snapshot carries its fonts inline (no folder next to it to load them from)."""
    for f in FONTS.glob("*.woff2"):
        uri = "data:font/woff2;base64," + base64.b64encode(f.read_bytes()).decode()
        css = css.replace(f"/static/app/fonts/{f.name}", uri)
    return css


def export_site(cfg, account: str, out: Path, sessions: int = 3, label: str | None = None, note: str | None = None) -> Path:
    data = site_data(cfg, account, sessions, label)
    payload = _json(data).replace("</", "<\\/")
    style, body = _body_and_style((STATIC / "index.html").read_text(encoding="utf-8"))
    # the host pads the page for phone safe areas; the sticky app bar must not add them twice
    style = style.replace(".bar{position:sticky;top:0;", ".bar{position:sticky;top:env(safe-area-inset-top,0px);")
    style = style.replace("min-height:calc(52px + env(safe-area-inset-top,0px));\npadding:env(safe-area-inset-top,0px) 4px 0 16px;",
                          "min-height:52px;\npadding:0 4px 0 16px;")
    style = _font_data_uris(style)
    note = note or ("Read-only snapshot of the intraday desk. Controls are off here; they work on your own desk while it runs.")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    html = (f"<title>QuantDesk</title>\n<style>{style}</style>\n{body}\n"
            f'<script type="application/json" id="qd-data">{payload}</script>\n'
            f"<script>{CHART_LIB.read_text(encoding='utf-8')}</script>\n"
            f"<script>{SHIM}</script>\n{_meta(data['label'], note)}\n{_trade_script(cfg)}\n<script>{app_js}</script>\n")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def publish_site(cfg, account: str, out_dir: Path, sessions: int = 3, label: str | None = None,
                 note: str | None = None) -> Path:
    """A static, installable (PWA) read-only site that stays current: index.html + app.js load
    data.json and re-fetch it every minute; a service worker keeps the app shell for offline use.
    Re-run this every few minutes while the desk trades and push the folder to any static host
    (the GitHub Actions workflow publishes it to Pages)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = site_data(cfg, account, sessions, label, live=True)
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'href="/((?:manifest\.webmanifest|icon\.svg|icon-192\.png|apple-touch-icon\.png)(?:\?v=\d+)?)"', r'href="\1"', html)      # the published site lives under a sub-path: relative links (the ?v= forces a phone to refetch a changed icon)
    html = html.replace("/static/app/fonts/", "fonts/")
    html = re.sub(r'<script src="/static/datafeed.js"></script>\s*', "", html)
    html = html.replace('<script src="/static/vendor/lightweight-charts.js"></script>', '<script src="lightweight-charts.js"></script>')
    note = note or ("Paper trades only. The desk runs by itself on NSE trading days, 09:15–15:30 IST, and this app "
                    "refreshes every minute while it does. Read-only: nothing here can place an order.")
    html = html.replace('<script src="/static/app/app.js"></script>',
                        f"<script>{LIVE_SHIM}</script>\n{_meta(data['label'], note)}\n{_trade_script(cfg)}\n<script src=\"app.js\"></script>")
    (out / "index.html").write_text(html, encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    (out / "app.js").write_text(app_js, encoding="utf-8")
    shutil.copyfile(CHART_LIB, out / "lightweight-charts.js")
    (out / "fonts").mkdir(exist_ok=True)
    for f in [*FONTS.glob("*.woff2"), *FONTS.glob("LICENSE-*.txt")]:
        shutil.copyfile(f, out / "fonts" / f.name)
    for icon in ICONS:
        shutil.copyfile(STATIC / icon, out / icon)
    man = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    man.update({"id": "./", "start_url": "./", "scope": "./"})
    for ic in man.get("icons", []):
        ic["src"] = ic["src"].lstrip("/")
    for sc in man.get("shortcuts", []):
        sc["url"] = "./" + sc["url"].lstrip("/")
        for ic in sc.get("icons", []):
            ic["src"] = ic["src"].lstrip("/")
    (out / "manifest.webmanifest").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    # the service worker's cache is named after the app's own files: a new app version replaces the
    # old cache, while an unchanged app re-publishes byte-identical (no needless Pages builds)
    ver = hashlib.sha1((html + app_js).encode()).hexdigest()[:12]
    (out / "sw.js").write_text((STATIC / "sw.js").read_text(encoding="utf-8").replace("__QD_VERSION__", ver), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    tmp = out / "data.json.tmp"
    tmp.write_text(_json(data), encoding="utf-8")
    tmp.replace(out / "data.json")                     # atomic: a reader never sees half a file
    return out
