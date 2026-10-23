# The watchdog

The desk's alarm for the things that **did not happen**. A session that never started, a heartbeat that went stale, an evening
workflow that did not run, a credential about to expire: nothing in the desk itself raises those, because the thing that would
raise them is the thing that stopped. It lives in the Cloudflare Worker, whose cron clock does not depend on GitHub's cron
(which has been hours late on this repository). Design and reasons: [MASTER_PLAN.md](MASTER_PLAN.md) section 3.

It only **reads** (GitHub's public workflow-run list, the published `data.json`) and **sends alerts**. It never starts a trade,
touches a journal or holds a secret other than its own. Messages carry a check name, a workflow name, a time and a link, never a
key, a journal value or a position.

## What it checks (IST; trading days = Mon to Fri, not an NSE holiday)

| Check | When | Alert |
|---|---|---|
| W1 desk started | 09:10 | **P1** no `Live paper desk` run exists today |
| W2 heartbeat | 09:30, 11:00, 13:00, 15:00 | **P1** heartbeat older than 20 minutes (the site is republished every 6 minutes plus Pages lag; the drill measures the real figure), or the desk halted; **P2** the feed fell back from Kotak (no "kotak" in the label) or more than half of polls came from Yahoo (a normal day on 23 Oct was a third: `kotak+yahoo (190 of 570 polls from Yahoo)`), or the heartbeat is unreadable |
| W3 after the close | 16:00 | **P1** `Live paper desk` did not run or failed; **P2** `Collect wide data` did not run or failed |
| W5 evening jobs | 18:00 self-review, 21:00 data warehouse | **P2** did not run or failed |
| W6 failures | 16:00, 18:00, 21:00 | **P2** a workflow failed (or was cancelled, except the scheduler, site publish and CI) on `main` since the last look |
| W7 credentials | 07:30 weekdays | **P2** 14 days, **P1** 7, 2 and 0 days before an expiry date you record; **P1** every day once expired. **Push only**: the repository is public, so these never become an issue |
| W8 digest | Saturday 17:30 | sessions run of expected, failed runs on `main` (low priority push, and an issue) |
| W9 calendar | 15 Dec, 15 Jun | **P2** the next (or this) year's NSE holiday list is not in `calendar.holiday_years` |

A check that cannot run (GitHub or the site unreachable) is reported as a **P2 "Watchdog could not run a check"**, so blindness is
never silent. Each check slot fires at one fixed time, so a slot alerts at most once a day (W2 has four slots, so it can alert up to four times).

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
4. Check the Worker shows **five** cron triggers after the next deploy from `main` (the fifth is `0,30 10-16 * * *`, the
   watchdog's own; it does not start the desk).
5. In GitHub, Settings, Notifications: make sure you receive email for issues assigned to you (the default).

`GH_DISPATCH_TOKEN` (already there) needs **Actions: read and write**. It also lifts GitHub's rate limit on the read-only calls.

## The drill (do it once, then after any change to the Worker)

1. Add the plain variable `WATCHDOG_TEST` = `1` to the Worker. At the next half-hour firing (15:30 to 22:00 IST, any day) you get a
   push **and** an issue titled `[watchdog] INFO TEST: Watchdog test`. Remove the variable straight away: it fires at every
   firing while set.
2. To prove a real failure alerts: with the desk stopped on a trading morning (or a Saturday's digest), expect the P1 push at the
   times in the table and the issue within a minute or two.
3. Plan exit test for P0: a deliberately stopped workflow produces a push **and** an e-mail within 15 minutes.

## Limits, said plainly

- **Stateless.** No stored memory of what it already sent, so there is no "resolved" message and no 30-minute escalation yet.
- **Holidays are a copy.** The Worker holds its own list of 2026 NSE holidays (a test fails if it differs from
  `config/quantdesk.yaml`). 2027 is not entered, so until it is, 2027 holidays look like trading days and W1 would raise a false
  P1 on one. W9 asks for the list on 15 Dec.
- **W2 depends on `data.json`'s `state.heartbeat` fields** (`ts`, `halted`, `feed`), which exist in the published file (checked 23 Oct
  2026). If the shape changes, W2 raises a P2 "Heartbeat unreadable" rather than staying quiet.
- **GitHub can be the thing that is down.** Push does not depend on it; e-mail does.
- **W6 sees 08:00 to 21:00 on trading days only.** Overnight and weekend failures are caught by the Saturday digest, which counts at most the last 100 failed runs.
- **Alerts can be forged by anyone who can dispatch `watchdog-alert.yml`** (write access, or the dispatch token): they can open a convincing issue assigned to you. That is no wider than that token's existing reach (it can already dispatch `clear-halt.yml`). Email dedupe is per check per day, and the workflow runs one at a time per check and day.
- **`WATCHDOG_TEST=1` alerts at every half-hour firing** (a push and an INFO issue) until the variable is removed.
- **Five cron triggers is the free plan's limit.** Any new check must reuse these firing times (a test checks every slot against
  the crons).
- **Not built yet:** the optional dead-man's switch (an external service that alerts if the Worker itself dies), per-sleeve
  trade-count checks, and the HAR session count in the digest (needs the journal).
