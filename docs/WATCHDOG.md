# The watchdog

The alarm for the things that **did not happen**. A recording session that never started, an evening
workflow that did not run, a credential about to expire: nothing in the desk itself raises those, because the thing that would
raise them is the thing that stopped. It lives in the Cloudflare Worker, whose cron clock does not depend on GitHub's cron
(which has been hours late on this repository). The plan it serves: [RENAISSANCE.md](RENAISSANCE.md) section 4.

It only **reads** (GitHub's public workflow-run list, the published `data.json`) and **sends alerts**. It never starts a trade,
touches a journal or holds a secret other than its own. Messages carry a check name, a workflow name, a time and a link, never a
key, a journal value or a position.

## What it checks (IST; trading days = Mon to Fri, not an NSE holiday)

| Check | When | Alert |
|---|---|---|
| W1 recorder started | 09:10 | **P1** no `Session recorder` (record.yml) run exists today |
| W3 after the close | 16:00 | **P1** `Session recorder` did not run or failed; **P2** `Collect wide data` did not run or failed |
| W5 evening jobs | 18:00 self-review, 21:00 data warehouse | **P2** did not run or failed |
| W6 failures | 16:00, 18:00, 21:00 | **P2** a workflow failed (or was cancelled, except the scheduler, site publish and CI) on `main` since the last look |
| W7 credentials | 07:30 weekdays | **P2** 14 days, **P1** 7, 2 and 0 days before an expiry date you record; **P1** every day once expired. **Push only**: the repository is public, so these never become an issue |
| W8 digest | Saturday 17:30 | sessions run of expected, failed runs on `main` (low priority push, and an issue) |
| W9 calendar | 15 Dec, 15 Jun | **P2** the next (or this) year's NSE holiday list is not in `calendar.holiday_years` |
| W10 live feed | trading days 09:50, 11:00, 13:00, 15:10 | the live relay's own health (read straight from its Durable Object, no key involved; silent unless the live view is switched on). **P1** no source (Kite, Kotak) has delivered a price in 3 minutes; **P1** Kotak refused its key; **P2** only one source is delivering (not when Kotak is not configured); **P2** the two sources disagree on more than 5% of the instruments both carry (needs 20 or more) |
| W11 Kotak universe | trading days 09:30 | **P2** the Kotak poller's universe is not today's (it idles without one; the relay also asks GitHub to rebuild it, see `docs/LIVE.md`) |

A check that cannot run (GitHub or the site unreachable) is reported as a **P2 "Watchdog could not run a check"**, so blindness is
never silent. Each check slot fires at one fixed time, so a slot alerts at most once a day.

## Two alert paths, independent of each other

- **Push**: ntfy, straight from the Worker. Needs the `NTFY_TOPIC` secret. P1 is high priority, P2 default, digest low.
- **Email**: P1 and the digest also dispatch [`watchdog-alert.yml`](../.github/workflows/watchdog-alert.yml), which opens an issue
  as the **Actions bot** and assigns the repository owner, so GitHub emails and pushes it. (An issue opened with your own token
  would notify nobody: GitHub does not notify you of your own actions.) One issue per check per day; a repeat is a comment.

ntfy's anonymous e-mail is disabled on ntfy.sh, so e-mail goes through GitHub, not ntfy.

## Owner set-up (about 15 minutes, once)

1. Install the **ntfy** app on your phone. Pick a long random topic, for example 20 or more random characters of letters and
   digits (`A-Z a-z 0-9 _ -`, 8 to 64). Anyone who knows the topic can read your alerts, so treat it as a secret.
2. Cloudflare dashboard, the `quant-desk` Worker, Settings, Variables and Secrets: add the **secret** `NTFY_TOPIC` with that topic.
   In the ntfy app subscribe to the same topic.
3. Optional **secret** `CRED_EXPIRY`, a JSON object of label to expiry date, for example
   `{"cred-1": "2027-01-15", "cred-2": "2026-12-01"}`. Use neutral labels you will recognise, not the real secret names: the label appears in the push (never in an issue).
4. Check the Worker shows **five** cron triggers after the next deploy from `main`: `*/10 2-9 * * *`, `*/10 10-16 * * *`, `*/10 0-1,17-23 * * *` (together: every ten minutes, around the clock, every day;
   each starts the desk scheduler and runs the watchdog) and the two collect-wide ones, `55 9 * * MON-FRI` and `15 10 * * MON-FRI`.
5. In GitHub, Settings, Notifications: make sure you receive email for issues assigned to you (the default).

`GH_DISPATCH_TOKEN` (already there) needs **Actions: read and write**. It also lifts GitHub's rate limit on the read-only calls.

## The drill (do it once, then after any change to the Worker)

1. Add the plain variable `WATCHDOG_TEST` = `1` to the Worker. At the next half-hour firing (:00 or :30, any hour, any day) you get a
   push **and** an issue titled `[watchdog] INFO TEST: Watchdog test`. Remove the variable straight away: it fires at every
   half-hour firing while set.
2. To prove a real failure alerts: with the desk stopped on a trading morning (or a Saturday's digest), expect the P1 push at the
   times in the table and the issue within a minute or two.
3. Plan exit test for P0: a deliberately stopped workflow produces a push **and** an e-mail within 15 minutes.

## Limits, said plainly

- **Stateless.** No stored memory of what it already sent, so there is no "resolved" message and no 30-minute escalation yet.
- **Holidays are a copy.** The Worker holds its own list of 2026 NSE holidays (a test fails if it differs from
  `config/quantdesk.yaml`). 2027 is not entered, so until it is, 2027 holidays look like trading days and W1 would raise a false
  P1 on one. W9 asks for the list on 15 Dec.
- **W2 (the desk's heartbeat) was retired with the desk on 6 Nov 2026**: the recorder publishes no heartbeat; W1, W3 and W6 cover it.
- **GitHub can be the thing that is down.** Push does not depend on it; e-mail does.
- **W6 sees 08:00 to 21:00 on trading days only.** Overnight and weekend failures are caught by the Saturday digest, which counts at most the last 100 failed runs.
- **Alerts can be forged by anyone who can dispatch `watchdog-alert.yml`** (write access, or the dispatch token): they can open a convincing issue assigned to you. That is no wider than that token's existing reach (it can already dispatch `clear-halt.yml`). Email dedupe is per check per day, and the workflow runs one at a time per check and day.
- **`WATCHDOG_TEST=1` alerts at every half-hour firing** (a push and an INFO issue; 48 a day) until the variable is removed.
- **W16 and W17 prove a run happened, not that data arrived.** `kite-evening.yml` is deliberately green when its login gate refuses (a Kite problem is a warning), so W16 can pass with no candles collected; the data-health report (`data health`) is what says whether the evening's candles are there.
- **Five cron triggers is the free plan's limit.** Any new check must reuse these firing times (a test checks every slot against
  the crons).
- **Not built yet:** the optional dead-man's switch (an external service that alerts if the Worker itself dies), per-sleeve
  trade-count checks, and the HAR session count in the digest (needs the journal).

## Around the clock (8 Nov 2026)

The Worker's cron now fires **every 10 minutes, all day, every day** (three crons that tile the 24 UTC hours, so no minute fires twice and no alert is sent twice), and each firing asks GitHub to run `scheduler.yml`; `scheduler.py` decides what, if anything, to start. New around-the-clock jobs and their checks:

| Check | When (IST) | What |
|---|---|---|
| W15 | 00:00, 04:00, 08:00, 12:00, 16:00, 20:00, every day | The news digest (`news.yml`, started every tick by the scheduler, day and night) has a successful run in the last hour. |
| W16 | 06:00 Tue to Sat | The MCX/currency evening candles (`kite-evening.yml`, started once a night by the Worker's own clock in the 00:10 IST firing (not by the desk scheduler, which a test keeps away from the Kite jobs), never retried because it logs in to Kite) was started after midnight and did not fail. |
| W17 | 11:10 Tue to Sat | The FX minute bars (`fx-minutes.yml`, started by the scheduler from 04:05 IST, retried up to three times) ran today and did not fail. |
