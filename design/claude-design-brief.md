# Quant Desk — UI/UX redesign brief (for Claude Design)

## What this is
Quant Desk is a personal, AI-assisted intraday options trading desk for the Indian market (NIFTY and BANKNIFTY
options; F&O stocks on a watch list). It runs by itself every trading day (09:15–15:30 IST). It reads the market
every minute, explains what it thinks and why, trades on paper with a small account (₹20,000, buying calls and
puts only for now) and learns from its own calls. This app is how its owner watches it from a phone: what the desk
sees, what it's waiting for, what it did, and whether it's any good.

Redesign the whole app. It works today but looks like a prototype: too much empty space, heavy cards, weak
hierarchy and an amateur icon. I want it to feel like a **professional Indian market-analysis product**.
- **The reference:** the restraint and clarity of **Strike (strike.money)**. Its look: clean, structured, decluttered,
  thin type and thin lines, data-dense without feeling busy, calm colours with green/red used only for meaning.
- **Not a clone:** take the design language, not Strike's brand, logo or layouts.

## Who uses it and how
- One person, mostly on a **phone (390 px wide)**, often a glance between other things. Sometimes on a laptop.
- The first 5 seconds must answer:
  - Is the desk running?
  - Am I up or down today?
  - What does it think of NIFTY / BANKNIFTY?
  - Is it in a trade or waiting for one?
- Everything else is one tap deeper, never on top of that.
- It is **read-only on the published site** (no orders from the app). A local version has 3 controls: pause,
  resume, flatten.

## Design direction
- **Density:** compact, information-rich rows; no big empty heroes; no floating cards with big shadows. Group with
  thin hairline dividers and section headers, not boxes. Any card should earn its border.
- **Type:** one neutral sans in light weights for UI (e.g. Inter / Geist / IBM Plex Sans at 400/500, no bold
  walls). One mono or tabular figure style for every number (prices, P&L, percentages line up). A strict small type
  scale (≈11/12/13/15/20/28). Small-caps or letter-spaced micro-labels for section and field names.
- **Colour:**
  - Near-white / near-black neutrals with a slight cool tint, and one restrained accent for interactive state.
  - Green and red only for up/down, profit/loss, bullish/bearish; amber for warnings / "waiting".
  - No gradients, glassmorphism, neon or emoji.
- **Themes:** light, dark and auto, all first-class (dark is not an inverted light).
- **Motion:** almost none. Subtle value-change flashes on live numbers; sheets slide up; nothing bounces.
- **Numbers:**
  - Indian formatting: ₹1,23,456; signed P&L (+₹1,240 / −₹380); percentages with 2 decimals.
  - Times in IST, 24 h (14:05).
  - Prices with a thousands separator (22,620.45).
- **Tone of copy:** plain, short, factual. "Waiting at 22,640 for a break", not marketing.

## Information architecture
Phone: a bottom tab bar with 5 tabs. Desktop (≥ 900 px): a slim left sidebar and a wider two-column layout.

1. **Desk** — the overview
2. **Chart** — price, levels and the desk's read
3. **Trades** — positions, history, performance, daily reviews
4. **Brain** — the wider picture: global markets, drivers, flows, what the desk has learned
5. **Feed** — headlines (with AI reads) and the desk's minute-by-minute log

Header on every screen:
- the screen title;
- a **status pill**: Live (green dot) · Closed (grey, with next open time) · Stale (amber, "no report for 7 min") ·
  Offline;
- a settings button (theme, glossary/help).

## Screens and their data (use this realistic sample data)

### 1. Desk
- **State banner** (only when needed): "Market closed · next session Mon 09:15" / "Desk hasn't reported for
  7 min" / "Offline · showing the last saved state".
- **Account strip** (compact, not a giant hero):
  - Paper equity ₹20,412 · Today +₹412 (+2.06%) · All-time +₹412.
  - Trades today 1/2 · Open 1 · Daily loss cap used 0%.
  - A mode badge: "Buyer only (selling from ₹3L)".
- **Markets**: one row per index (NIFTY 22,620.45 +0.42%, BANKNIFTY 54,650.20 −0.18%). Each row shows:
  - an intraday sparkline;
  - the desk's **bias** (Bullish / Bearish / Neutral, as a small signed meter from −1 to +1, e.g. +0.38);
  - **conviction** (0.62);
  - **day type** (Trend / Balance / Volatile / Forming);
  - **premium** (IV rich / fair / cheap).
  - Tap → Chart.
- **Now**: one line of what the desk is doing, with the time. Examples: "Watching · no setup has triggered",
  "Standing aside · breaking news 4 min ago", "Armed · ORB buy on a break of 22,640".
- **Waiting at the level** (0–3 items; the desk's pending entries): setup (ORB / Trend break / VWAP pullback),
  direction, trigger level 22,640, stop 22,580, expires in 1:40, one-line why.
- **Open position** (0–1): NIFTY 22,650 CE × 1 lot (65), entry ₹92.40 → ₹104.10, +₹760 (+0.6R), stop at premium
  ₹64.70 / underlying 22,580, target 22,760, time stop 11:45. Tap → trade sheet.
- **Global pulse**: a thin horizontal ticker: S&P fut −0.3%, Nikkei +0.8%, Brent +1.2%, DXY +0.1%, USD/INR 83.42,
  US VIX 15.2.
- **Headlines** (top 3): title, source, minutes ago, a tone tag, an impact tag (High/Med/Low) and an event tag
  (Policy, Earnings, Inflation…).
- **Closed today**: compact rows.

### 2. Chart
- **Quote header**: NIFTY · Wed 30 Sep · 22,620.45 · −95.75 (−0.42%) · H 22,690 L 22,569 · VWAP 22,617.
- **Controls** (one compact row; wraps on phone, never clips):
  - [NIFTY | BANKNIFTY];
  - [Index | Futures];
  - [1m | 5m | 15m];
  - full screen.
- **The chart** (built with TradingView Lightweight Charts v5, so style within what it can draw):
  - candles, with volume as a faint histogram at the bottom;
  - VWAP as a line that restarts every session;
  - the last 2–5 sessions with a quiet session divider;
  - a **session volume profile** drawn from the right edge (POC highlighted, value area tinted);
  - **level lines** with small right-axis labels: PDH/PDL, opening range, initial balance, VAH/VAL/POC, CPR,
    OI call/put walls;
  - **trade markers**: entry arrows, exit dots with P&L;
  - a crosshair **OHLC legend** in the top-left that never covers the axis labels.
- **Level chips**: toggle groups — Prior day · Opening range · Value area · CPR · OI walls · Initial balance.
- **Desk read**:
  - the bias meter, score, conviction, day type and premium view;
  - a 3–5 sentence narrative;
  - "No-trade flags" when present;
  - a "Track record" line (e.g. VWAP ×1.09, VIX ×0.87).
- **Evidence**: a ranked list of the factors behind the read. Each row has:
  - the factor name and category (Trend, Structure, Momentum, Flow, Options, Volatility, News, Global, Quant);
  - a signed direction bar (−1..+1) and its weight;
  - a one-line observation;
  - a "learned ×1.08" chip.
  Probation factors (weight 0) are shown muted.
- **Key levels table**: level, price, distance from spot (pts and %).
- **Quant**, small labelled stats:
  - P(up in 30 min) 0.56; model AUC 0.54; 30-min σ 0.21%;
  - futures basis +108 pts (carry 7.1%/yr), OI build-up "Long build-up";
  - IV percentile 66 (ATM IV 12.4 vs RV 10.8); PCR 1.12; max pain 22,600.

### 3. Trades
Segmented: Positions · History · Performance · Reviews.
- **History**: rows of time 10:05–10:48, setup, structure (Long call / Long put), lots, P&L ₹, R, exit reason
  (Target / Stop / Time / Square-off), grade (A–F).
- **Trade detail (bottom sheet / side panel)**:
  - the plan as written before entry: thesis, invalidation, target, premium stop, time stop;
  - the evidence at entry;
  - sizing notes;
  - legs with fills (bid/ask at the time);
  - the expected value / probability the desk priced;
  - MAE/MFE;
  - a mini price chart with entry/exit;
  - the post-trade grade and lessons.
- **Performance**:
  - KPI strip: net P&L, return %, win rate, profit factor, avg R, max drawdown, green days, costs paid;
  - an **equity curve** against the starting-capital baseline;
  - P&L by setup (horizontal bars);
  - a breakdown table switchable by day type / structure / exit / hour / index;
  - a calibration table (probability assumed vs realised).
- **Reviews**: one per session, a readable long-form page. It covers:
  - how the read evolved and the bias path;
  - each trade's why and how it ended;
  - "What the desk learned";
  - Claude's after-close reflection (lessons + what to watch tomorrow);
  - the language-model cost line.
  Make long text comfortable to read (65–75 characters a line on desktop).

### 4. Brain
Per index (NIFTY / BANKNIFTY):
- **Regime**: Risk-on / Risk-off / Mixed with a score, global stress (σ) and the size multiplier.
- **Influence graph**: world drivers → India's read → bias → decision (a calm node-link diagram, not a hairball).
- **Drivers board**: US equities, Asia, Europe, Dollar, Rupee, Crude, US rates, Fear (VIX), Gold. Each with:
  - its move (last 30 min or last session) in σ;
  - the news tone on it;
  - a status tag: **Validated** (votes) / **Probation** (graded live, no vote yet).
- **Leaders pulse**: HDFC Bank, ICICI Bank, Reliance, Infosys… index-weighted 30-min move, with a "narrow move"
  flag when the index goes against its leaders.
- **Flows**: FIIs 27% long index futures (31% a week ago); FII cash −₹9,484 cr, DII +₹10,042 cr.
- **Opening gap explained**: India opened +0.42%; the global cue was +0.30% (S&P +0.21%, Nikkei +0.09%).
- **What the desk has learned**: the factor weights it moved (×0.87 … ×1.11), trust in each news reader
  (rules / Gemini / Ollama / Claude) and each news type, and setups it stands aside from.
- **Stocks watch**: liquid F&O stocks, with:
  - premium traded (₹cr), lot, price;
  - the cheapest option one lot would cost;
  - a "Fits the account" / "Not yet" tag (e.g. HDFCBANK ₹6,662 a lot, not yet).

### 5. Feed
Segmented: Headlines · Desk log.
- **Headlines**:
  - filter chips: All · NIFTY · BANKNIFTY · High impact · Bullish · Bearish;
  - each item: title, source, time, impact, tone, event type, a surprise chip ("CPI 5.4% vs 5.0% expected"),
    a "Retelling" / "Rumour" marker when relevant;
  - the AI readers' calls: Gemini +0.40, Ollama +0.45, Rules +0.30.
- **Desk log**: a dense timeline of the desk's minute-by-minute thoughts (time · index · bias · action). Trades are
  highlighted, with a "Trades only" filter.

### Settings (sheet)
- Theme: Auto / Dark / Light.
- Glossary: bias, conviction, R, premium view, levels, evidence, probation, buyer only.
- About.

## States to design (every screen)
- Loading (skeletons that match the final layout).
- Empty / first run ("The desk's read appears here from 09:15 IST").
- Market closed.
- Desk not reporting (stale).
- Offline (last saved state, clearly labelled).
- Errors.
- No trades yet (Performance).
- Futures data not recorded yet.

## The app icon (important)
The current icon (three candlesticks on dark) is generic. Design a **distinctive mark** for "Quant Desk":
- **Form:** simple and geometric, readable at 16 px and at 1024 px. No candlesticks, bulls, rockets or rupee signs.
- **Direction to explore:** a price path that meets and breaks through a level line (the desk's core idea:
  waiting at a level), or a monogram built from that.
- **Colour:** one accent on a near-black tile, plus a monochrome version.
- **Deliver as:** SVG, and PNG at 32 (favicon), 180 (apple-touch), 192, 512, and 512 maskable (safe zone).
- Include a small wordmark lock-up for the header.

## What I need back
1. **Design tokens** as CSS variables for light and dark: neutrals, accent, up/down/warn, text levels, lines;
   type scale; spacing (4-pt grid); radii; borders; the one or two shadows allowed.
2. **Component sheet:** list row, KPI tile, stat strip, segmented control, filter chips, tags (bias, impact,
   tone, status), signed meter, direction bar, sparkline, data table, bottom sheet, banner, empty state, skeleton,
   status pill, tab bar, desktop sidebar.
3. **High-fidelity screens:**
   - all 5 tabs plus the trade detail and settings, on phone (390 × 844), light and dark;
   - Desk and Chart on desktop (1440 wide), dark.
4. **The icon set and the wordmark.**

## Constraints for the build (so the design can be implemented as-is)
- **Stack:** a static single-page app in plain HTML/CSS/JavaScript (no React), served from GitHub Pages as an
  installable PWA. Data is a JSON file refreshed about every minute (no streaming). Respect phone safe areas;
  standalone mode has no browser chrome.
- **Charts:** TradingView Lightweight Charts v5 for price and equity charts. Style them via its options: colours,
  grid, crosshair, price lines, markers, and one custom primitive for the volume profile. Other small charts
  (sparklines, bars, meters, the graph) can be inline SVG.
- **Fonts:** Google Fonts only.
- **Accessibility:** WCAG AA contrast in both themes; tap targets ≥ 40 px; information never carried by colour
  alone (add + / − signs and arrows).
