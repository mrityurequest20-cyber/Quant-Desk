# Market data from more than one broker

Each broker serves the part of the market it is best at, Kotak stands behind all of them, and the live relay
switches between them by itself. **Market data only:** no feed here can place an order, and the paper desk's
fills are priced from whichever feed the relay shows.

## Who serves what

| Segment | 1st | 2nd | 3rd | Last resort |
|---|---|---|---|---|
| Indices, NSE cash, NSE futures | Kite | — | — | Kotak |
| Index and stock **options** | Kite (full mode: the bid and offer) | — | — | Kotak (last price only) |
| **MCX options** (`mopt`) | **Fyers** | Kite | — | Kotak |
| **Currency options** (`copt`) | **Angel One** | Fyers | Kite | Kotak |
| **MCX** commodities | **Fyers** | Kite | — | Kotak |
| **Currency** | **Angel One** | Fyers | Kite | Kotak |

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
| Fyers | **Built** (`fyers-feed.yml`, `deploy/fyers_autologin.py`). The access token expires at 06:30 IST daily. A **refresh token** from one full login renews it each day with the PIN (`/api/v3/validate-refresh-token`). A new refresh token comes from a TOTP login. | Fyers' official samples only show the browser login. The TOTP login uses endpoints that are not documented and that users report breaking, so it runs **only when the refresh token has expired**, at most once a day. |
| Angel One | **Built** (`angel-feed.yml`, `deploy/angel_autologin.py`). `loginByPassword(client code, MPIN, TOTP)`: the documented SmartAPI login. | User reports of feed discrepancies in June 2026: the relay's comparison catches those. |

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

## The Fyers feed (built 13 Nov 2026)

`.github/workflows/fyers-feed.yml`, started once a day by the scheduler (08:25 to 20:00 IST, one start, never retried):

1. **token job** (the only job that may write, the only one with the PIN and TOTP key): reads the stored tokens from the `fyers-token`
   branch (`deploy/fyers-token.sh`, AES-256 with the app secret). Today's already there: no login. Otherwise, if this is the first run
   of the day on its first attempt (`deploy/kite_login_gate.py`, `GATE_WORKFLOW=fyers-feed.yml`), `deploy/fyers_autologin.py` logs in:
   - the stored **refresh token + PIN** first (`/api/v3/validate-refresh-token`), which works for about 15 days;
   - the **TOTP login** only if that is refused (send login OTP, verify TOTP, verify PIN, auth code, `/api/v3/validate-authcode`), which
     also brings a new refresh token.
   Standard-library Python under `-I -S`; never prints a secret or a token (even one Fyers echoes back).
2. **three feed jobs** (09:00 to 14:15, to 20:05, to 23:58; read-only): `python -m quantdesk data fyers-feed`
   (`quantdesk/data/fyers_feed.py`):
   - reads Fyers' public symbol master and picks the nearest unexpired future of every MCX commodity and currency pair (Kite's rule),
     under the desk's names (`CRUDEOIL-MCX`, `USDINR-CDS`);
   - each round: `/data/quotes` for all of them (50 a call), then the next option chains and `/data/depth` books (five levels, OI) of the
     watchlist names in turn, chains first;
   - pushes only what changed, as feed `f`. Currency stops after 17:05, MCX runs to the close.
   - **Fyers' limits** for these data calls, from 16 Oct 2026: **Standard 5 a second, 50 a minute, 5,000 a day**; Prime 10, 500 and
     5,00,000 ([Plans & Limits](https://fyers.in/api-docs/v3/getting-started/plans-and-limits/)). `config feeds.fyers_plan` names the
     plan (Standard unless changed). Our caps sit under each: Standard 3 a second, 40 a minute and **4,500 a day**; Prime 5, 250 and
     4,50,000.
   - **The day's calls are spread across the session** (08:59 to 23:59): 55% for the quotes, 45% for the option chains and books,
     three chains to every book. Each of the day's three back-to-back jobs starts with an empty budget, so however the day is split or
     re-run, it stays under the daily cap. Measured on a simulated Standard day (the real 13-name watchlist, 32 contracts,
     `tests/test_fyers_budget.py`):
     - a quote round about every **22 s** (under 27 s in 99% of rounds; a job's first round can take longer), inside the paper desk's
       30 s quote age for a fill. More than 50 contracts would need two calls a round: the run says so in its notes;
     - **every watchlist option chain within 8 minutes by day and 9 in the evening**, inside the runner's 600 s mark age and the
       12-minute chain staleness, so held MCX and currency options keep their marks, and the forced exits (the kill switch, the halts,
       expiry) close them. The owner's own sell needs a bid under 120 s old (`EXIT_AGE_S`), so after Kite's hours it may be refused
       until the next chain arrives and need a retry;
     - each name's book (the ladder and the futures' open interest) about every 23 minutes by day and 16 in the evening.
     **The limit that remains on Standard:** a new option needs a quote under 30 s old to be filled, which a chain fetched minutes
     earlier is not. In Kite's hours the relay shows Kite's fresher price; after them, MCX and currency option entries wait for the
     Data Socket (below). On Prime the 5 s floor sets the pace, with three chains and two books a round, as before.
     When Fyers' price is over a minute old, the relay shows Kite's for the segment in Kite's hours, as the routes say.
   - A **429, in the HTTP status or as code -429 in the answer, stops the feed for the day** (Fyers blocks a user who breaks the minute
     cap more than three times), and a refused token stops it too: both are warnings in the run, never a retry loop.
   - **The futures stream over Fyers' Data Socket** (`quantdesk/data/fyers_socket.py`, `config feeds.fyers_socket: true`): one WebSocket,
     no call budget, only a symbol cap (Standard 100, Prime 5,000 across connections). At the start of each job the feed turns the
     near futures into socket topics (one `/data/symbol-token` call), logs in with the token's `hsm_key`, asks for full mode and
     subscribes them; the price, best bid and offer with sizes, volume, change and open interest then arrive as they change, and go to
     the relay every 5 s round. While the socket delivers, **no REST quote call is made and the whole day budget goes to the option
     chains and books**: on a simulated Standard day every watchlist chain then comes round within five minutes by day. A future stays
     on REST until the socket has streamed it at least once; a socket that cannot log in, cannot get its topics, or has sent nothing
     for a minute hands the quotes back to REST at once, under the same day budget, and is opened again (a growing pause; eight
     failures in a row give up for the job, a session that streamed starts the count again). The handshake must end on
     `socket.fyers.in`: a redirect anywhere else is refused before the login is sent, as the REST calls refuse redirects. A 429 on the
     one `/data/symbol-token` call stops the feed for the day, like any 429. The wire protocol follows Fyers' own Python SDK (`fyers_apiv3` 3.2.1, MIT); the SDK itself is not installed (it pins old
     versions of requests, aiohttp and setuptools). No session that wrote this could reach Fyers: the **check_only** run now also
     opens the socket and waits up to 20 s for its first quotes, and says so in its summary (a socket that does not deliver is a
     warning, never a red check, since REST still carries the quotes). The run's metrics carry the socket's counts (connections,
     frames, quotes, acknowledgements, silences, frames it could not read, and the numeric codes of Fyers' own messages, such as 51001 for
     the plan's symbol limit; the summary is public, so the text Fyers writes is never kept).
   - Still on REST: the option chains. Streaming the near-the-money options of the watchlist names in the socket's remaining slots
     (about 68 on Standard), so that MCX and currency option entries can fill after Kite's hours, is the next step.
   - Nothing is written to disk. The run summary shows counts only, and the key names of any answer it could not read, never a value.
3. **Watchdog W19** at 09:40 and 20:30: the feed ran today and has not failed.

**What is verified and what is not.** The request shapes come from Fyers' own Python SDK (`fyers_apiv3` 3.2.1: hosts, the
`APP_ID:TOKEN` header, the app hash, the 50-symbol cap, the depth query). The TOTP login's four undocumented calls come from community
scripts. The answers' field names (`lp`, `bid`, `ask`, `bids`, `ask`, `oi`) are Fyers' documented ones, but no cloud session that
wrote this could reach Fyers. **The first real run is the test:** a login step that fails names the step and the secret to check, and a
feed that cannot read an answer says which keys it saw instead.

**First run by hand:** Actions, then "Fyers feed", then Run workflow. Without the refresh token stored yet, it does the TOTP login. In the
token job's log, look for "logged in with TOTP" and in the feed job for "N contracts, N cycles, N quotes pushed". Then the Markets tab
shows MCX prices with source `f`.

## The Angel One feed (built 13 Nov 2026)

`.github/workflows/angel-feed.yml`, started once a day by the scheduler (08:25 to 16:00 IST, one start, never retried). It may only
read, and nothing is stored between its jobs.

1. **feed-1** (to 14:50) logs in only if it is the first run of the day on its first attempt (`kite_login_gate.py`,
   `GATE_WORKFLOW=angel-feed.yml`). `deploy/angel_autologin.py` calls SmartAPI's documented login (`loginByPassword`: client code,
   MPIN, TOTP) in standard-library Python under `-I -S`. `deploy/angel-export.sh` hands the session to the feed, masked.
2. **feed-2** (to 17:05) logs in again only because feed-1's login worked, and never on a re-run. A wrong MPIN costs one failed login
   a day.
3. `python -m quantdesk data angel-feed` (`quantdesk/data/angel_feed.py`):
   - reads Angel One's public instrument master (`OpenAPIScripMaster.json`) for the nearest unexpired currency future (`FUTCUR` on
     CDS) of each pair, under the desk's names (`USDINR-CDS`);
   - every 5 s, one FULL quote call (50 tokens a call) gives price, volume, OI and five-level depth for all of them;
   - pushes what changed, as feed `a`. Our cap is 2 calls a second and 40 a minute. A 429 or a refused session stops it for the day.
4. **Watchdog W20** at 09:40: the feed ran today and has not failed.

**Verified from:** Angel One's own SDK (`smartapi-python` 1.5.5: the host, the login route and body, the quote route and body, the
headers). The SDK itself sends fixed placeholder IP and MAC headers, so this does too. Not yet run against Angel One: the first real run
is the test, and like the Fyers feed it names any answer it cannot read by its key names.

**First run by hand:** Actions, then "Angel One feed", then Run workflow (between 09:00 and 16:00 on a trading day). Look for "angel
login: logged in" and "N contracts, N cycles, N quotes pushed".

## The tape: every Fyers and Angel One quote is kept (audit K-20, 21 Nov 2026)

Until 21 Nov the Fyers and Angel One feeds kept nothing: their MCX and currency quotes, five-level books and option chains existed only in the relay's latest
snapshot, so nothing AUTO decided on could be studied, replayed or trained on, and every MCX option series that expired was lost for good (Kite lists only live
contracts). Now each quote a feed hands the relay is also written to a tape (`quantdesk/data/tape.py`): the time, the name, and the whole quote as JSON (price,
bid, ask, sizes, volume, open interest, change, segment, and the book when the feed sent one), in gzip CSV chunks. The relay's view is unchanged, and a tape
problem is counted (`tape_errors` in the run's counts), never allowed to stop the feed.

The data is licensed to the subscriber and this repository is public, so the tape is **encrypted before it is kept** and is never uploaded in the clear: at
the end of each streaming job it is tarred and encrypted (AES-256-CBC, PBKDF2 with 200,000 iterations) with the repository secret **`MARKET_TAPE_KEY`**, and
kept as a 90-day artifact (`fyers-tape-<job>`, `angel-tape-<job>`). Without the secret the tape is deleted at the end of the job with a warning.

**Owner set-up (once):** add the secret `MARKET_TAPE_KEY` (Settings, Secrets and variables, Actions): a long random string, used for nothing else, kept somewhere
safe (without it the tapes cannot be read). **To read a tape:** download the artifact, then
`MARKET_TAPE_KEY=... openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:MARKET_TAPE_KEY -in fyers_tape.tar.enc | tar -xf -`.

Artifacts expire after 90 days. A durable private copy (a store outside this public repository) is the next step; until then, download what you want to keep.

## Checking a login before the first session (14 Nov 2026)

Run **Fyers feed** or **Angel One feed** from the Actions tab with **check_only** ticked. It logs in exactly as the morning run does (the same login gate:
one login a day, first attempt only), makes ONE round of requests with the clock held at midday, and sends nothing to the relay. On a weekend the
brokers answer with the last prices. The run's summary shows counts only: contracts, instruments with a quote, and calls. It is green only if quotes
came back. A Fyers check also stores the token (and the 15-day refresh token), so the next morning's run starts from it.

## How it rolls out

1. **Done:** the relay takes pushes from any feed by its code, the route table is in place, and the instrument page
   shows each price's source.
2. **Done (13 Nov 2026), awaiting its first real run: the Fyers feed** (above). It polls Fyers' REST quotes and depth every 5 s rather than
   holding the data socket: every piece is testable offline, and 5 s is the relay's own cadence. The socket can replace it later if 5 s is too slow.
3. **Done (13 Nov 2026), awaiting its first real run: the Angel One feed** (above), code `a`.
4. **Shadow week:** each new feed runs for a week while the relay compares it with Kite on every instrument both hold.
   It counts toward the routes only at 97% agreement or better, the bar Data health already uses for Kite against
   Kotak. Until then a route can be pointed back at Kite with one line.
5. **Watchdog:** an alert when a segment falls back from its first feed, or a login fails.

The owner added both brokers' secrets on 13 Nov 2026. The cloud session that wrote the adapters could not reach either broker, so neither has
been run against the real API yet: their first runs in GitHub Actions are the test.
