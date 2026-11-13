# Market data from more than one broker

Each broker serves the part of the market it is best at, Kotak stands behind all of them, and the live relay
switches between them by itself. **Market data only:** no feed here can place an order, and the paper desk's
fills are priced from whichever feed the relay shows.

## Who serves what

| Segment | 1st | 2nd | 3rd | Last resort |
|---|---|---|---|---|
| Indices, NSE cash, NSE futures | Kite | — | — | Kotak |
| Index and stock **options** | Kite (full mode: the bid and offer) | — | — | Kotak (last price only) |
| **MCX** commodities | **Fyers** | Kite | — | Kotak |
| **Currency** | **Angel One** (proposed) | Fyers | Kite | Kotak |

This is `feeds.routes` in [config/quantdesk.yaml](../config/quantdesk.yaml). `wrangler.jsonc` carries the same
table to the Worker as `FEED_ROUTES`, and a test checks that the two match.

**How the relay chooses:**
- It shows the first feed in a segment's list whose price is under 60 seconds old.
- It steps over a dead feed by itself.
- A feed not in a segment's list is still kept and compared, but never shown for it.

Until Fyers and Angel One deliver, their segments show exactly what they show today: Kite, then Kotak.

**Why this split:**
- Kite already carries everything the desk trades (3,000 instruments a connection, five levels of book), so it
  keeps the busiest work: options need its bid and offer.
- Fyers takes MCX.
- The third broker takes currency.
- Each segment then has a second feed behind its first, and the relay compares any two that are fresh and flags a
  disagreement larger than a spread.

**Why Angel One for currency:**
- **Upstox:** its own team says it does not support automating the daily login (SEBI's guidelines). That rules it
  out for a desk that logs in by itself.
- **Angel One:** SmartAPI's documented login takes the client code, the MPIN and a TOTP code, so a daily automatic
  login is the supported way, not a workaround. It is free.
- **Dhan:** works too (a 24-hour token from a TOTP endpoint), but its data API costs about ₹499 a month.

## Logging in automatically

| Broker | How | Weak point |
|---|---|---|
| Kite | done (`kite-token.yml`, `deploy/kite_autologin.py`) | — |
| Fyers | The access token expires at 06:30 IST daily. A **refresh token** from one full login renews it each day with the PIN (`/api/v3/validate-refresh-token`). A new refresh token comes from a TOTP login. | Fyers' official samples only show the browser login. The TOTP login uses endpoints that are not documented and that users report breaking, so it runs **only when the refresh token has expired**, at most once a day. |
| Angel One | `generateSession(client code, MPIN, TOTP)`: the documented SmartAPI login. | User reports of feed discrepancies in June 2026: the relay's comparison catches those. |

**The same lockout guard as Kite:** only the first attempt of the IST day may log in, so a wrong PIN costs at most
one failed login a day.

## Secrets the owner sets

Add these as **GitHub repository secrets**: Settings, then Secrets and variables, then Actions, then New
repository secret. **Nothing goes in Cloudflare:** the relay needs no broker key, because the feeds push to it with
the `LIVE_INGEST_TOKEN` it already has.

| Fyers | Angel One |
|---|---|
| `FYERS_APP_ID` (the app id, like `ABCD1234-100`) | `ANGEL_API_KEY` |
| `FYERS_SECRET_ID` (the app secret) | `ANGEL_CLIENT_CODE` |
| `FYERS_REDIRECT_URI` (the redirect URL set on the app) | `ANGEL_MPIN` |
| `FYERS_CLIENT_ID` (your Fyers login id) | `ANGEL_TOTP_SECRET` (the text under the QR code, not the API secret) |
| `FYERS_PIN` | |
| `FYERS_TOTP_SECRET` (the key shown when TOTP is enabled) | |

Never paste any of these into a chat, an issue or a commit.

## How it rolls out

1. **Done:** the relay takes pushes from any feed by its code, the route table is in place, and the instrument page
   shows each price's source.
2. **Fyers feed:** a workflow logs in, streams the MCX near-month futures (and the currency pairs, as currency's
   second feed) with the official `fyers-apiv3` data socket, and pushes them under the desk's names with code `f`.
   MCX trades until 23:30 IST, so the evening runs in a second job, like the paper desk's two halves.
3. **Angel One feed:** the same for currency, code `a`.
4. **Shadow week:** each new feed runs for a week while the relay compares it with Kite on every instrument both hold.
   It counts toward the routes only at 97% agreement or better, the bar Data health already uses for Kite against
   Kotak. Until then a route can be pointed back at Kite with one line.
5. **Watchdog:** an alert when a segment falls back from its first feed, or a login fails.

Steps 2 and 3 need the secrets above, and a session that can reach `api-t1.fyers.in` and `apiconnect.angelone.in`.
The cloud session that wrote this could not reach either, so neither adapter has been run against the real API yet.
