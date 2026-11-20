---
name: job-scan
description: Collect new job postings for job-agent. Reads the user's JobRight "Most Recent" recommendations feed in their own signed-in Chrome through a browser MCP, stops at the saved checkpoint card (or scans the full 24 hours when the checkpoint is stale), records each card's first-seen and publish time and real apply link, reads any extra sources the user configured, and falls back to the Indeed MCP connector. Writes a scan file to the workspace. Use when the user asks to find or scan new jobs, or as step 1 of job-run.
---

# job-scan

## Inputs

- Workspace: `$JOB_AGENT_HOME` or `~/.job-agent/`. Read `profile/preferences.yaml` (run `job-setup` first if missing).
- Checkpoint: `state/jobright-checkpoint.json`, shaped `{"job_key": "...", "publish_time": "...", "title": "...", "company": "...", "seen_at": "ISO time"}`. `scripts/jobright_meta.py` (this skill's folder) reads and writes it.
- First-seen log: `state/first-seen.json`, a map of job key to the ISO date the agent first saw it.

## Output

`state/scan-<YYYYMMDD-HHMM>.json`: `{"window": "<from> to <to>", "items": [...]}`, each item with `company, title, location, pay_text, posted_text, first_seen, publish_time, link, source, job_key, id, req_id (if shown), apply_url (if shown), kind (job or event)`. `job-gate` adds what it reads from the live posting. Also print a one-line summary: cards read, new cards, source, the window covered, and whether the checkpoint was reached (or why the full window was scanned).

## JobRight (default source)

0. **Window.** Run `python3 scripts/jobright_meta.py window --checkpoint <workspace>/state/jobright-checkpoint.json`. It prints where to stop: the checkpoint id when the checkpoint is under 24 hours old, or `full_window: true` with the reason when it is missing, unreadable or older. With a full window, read back 24 hours and say so in the report. **Which time sets the window:** with `freshness.reposts: keep` (this fork's default) use the card's `publishTime`, JobRight's latest post or repost time, so a big-company posting JobRight first saw weeks ago and just reposted is read, not skipped; still record its first-seen. With `freshness.reposts: cut`, use first-seen and publish time as upstream does.
1. Use your browser MCP connection (`--autoConnect` to the main Chrome, or `--browser-url` in dedicated mode). **Never have two JobRight feed tabs.** If `sources.jobright.use_open_tab` is true and the user keeps a feed tab open, find it by URL with `list_pages` and scan there, reading and scrolling only (no clicks on filters, no typing). Otherwise open `sources.jobright.feed_url` in one new tab with `new_page`, keep its page id and pass it on every call (When the URL you open may already be open in one of the user's tabs (their JobRight feed, a careers page), add a unique fragment such as `#job-agent-<short random id>` to the URL you pass to `new_page`. Your tab then keeps a URL no other tab has, so you can still find it with `list_pages` after page ids are renumbered or the connection drops, and close only it.), and close it with `close_page` at the end of the scan. If a feed tab you opened in an earlier step of this run is still open, reuse it instead of opening another. Never touch other tabs.
2. Check the feed's sort control. The checkpoint only works on a feed sorted by Most Recent. With `sources.jobright.force_most_recent: true` (this fork's default; the user opted in), select **Most Recent** in your own feed tab whenever another sort shows, wait for the list to reload, and confirm the control now says Most Recent before reading; this changes the sort on the user's JobRight account, which they asked for. If it will not switch, read the cards anyway, report it, and do not move the checkpoint. With `force_most_recent: false`, never change the sort: read the cards anyway, tell the user to save a Most Recent URL as `sources.jobright.feed_url`, and do not move the checkpoint.
3. Read cards top-down with `take_snapshot` (or one `evaluate_script` that lists the `a[href*="/jobs/info/"]` links and their card text). The list is virtualized: a snapshot holds only the cards near the viewport, and cards above drop out as you scroll. Record every card's key as you go and dedupe. For each card, build `job_key` from the card's job link (its ID or URL path). Fall back to `company|title|location` only when no link exists.
4. Stop when you reach the checkpoint card. If the checkpoint is not found, keep scrolling until cards are older than the window (24 hours, or `max_posting_age_days` if that is shorter) or a hard limit of 200 cards, then report "checkpoint not found".
   - **Exact time and the real apply link.** For each new card, read its own info page, the page a click on the card opens: in your feed tab, `evaluate_script` with `fetch('/jobs/info/<id>')` (the same page, same session, one at a time), take the `__NEXT_DATA__` script block, and pass it to `python3 scripts/jobright_meta.py next-data <file>`. It returns `publishTime` (UTC), `originalUrl`, and JobRight's match percent as `match_score` (with `match_label`, such as Strong Match). Store `match_score` on the item: job-gate orders the queue by it and cuts below `sources.jobright.min_match` when that is set, the employer's own posting. Store them as `publish_time` and `apply_url`. The req ID in `originalUrl` is what dedupe and the prior-application check use.
   - **First-seen.** JobRight ids are MongoDB ObjectIds: `python3 scripts/jobright_meta.py first-seen <id>` gives the time JobRight first saw the posting. Store it as `first_seen`. A repost keeps its old id and gets a fresh publishTime, so the id time is what catches it; `job-gate` cuts it.
5. Scroll slowly, one screen at a time, with a short pause. This is the user's signed-in session: no private API calls, no bulk requests, no parallel tabs on JobRight.
6. Record `first_seen` for each new key in `state/first-seen.json`. Freshness is judged from first-seen, because "Past 24 hours" style filters miss reposts.
7. **Move the checkpoint only after a complete scan of a Most Recent feed.** Set it to the top card of this scan with `python3 scripts/jobright_meta.py save --checkpoint <file> --id <top id> --publish-time "<its publishTime>" --title "<title>" --company "<company>"`. If the scan was cut short (error, sign-in wall, CAPTCHA), leave the old checkpoint so the next run rereads.
8. If JobRight shows a sign-in page or CAPTCHA, stop and tell the user. Do not type credentials or solve it.

### Filters: keep them loose, gate while scanning

The feed's own filters should be loose (job type, experience level, broad job functions, all work modes, sort Most Recent) and the strict rules belong to `job-gate`. Hard filters on salary, skills or industry hide good postings. A sudden drop in the number of cards usually means the location filter changed.

JobRight location gotcha: "Anywhere in the US" in the location picker means remote only, which returns a small fraction of the feed. Nationwide is the country United States with no city chips. If the picker forces a city chip, tell the user (setup asks them to fix it once); never change the user's filters during a scan.

## Simplify internship list (optional, on when `sources.simplify.enabled` is true)

Simplify and Pitt CSC publish every tech internship they track in one public JSON file on GitHub. Reading it is a plain file download, with no browser and no sign-in. Run it after JobRight, into the same scan file:

```
python3 scripts/simplify_source.py scan --seen <workspace>/state/simplify-seen.json \
  --url "<sources.simplify.listings_url>" --categories "<sources.simplify.categories, comma-joined>" \
  --term "<term from preferences>" --merge-into <workspace>/state/scan-<YYYYMMDD-HHMM>.json
```

- Leave out `--url` to use the default (the Summer 2027 repo). Leave out `--term` when `term` is blank.
- It keeps active listings in the chosen categories, drops every id it has seen before, and on the very first run keeps only listings added in the last 24 hours (the rest are marked seen, so they never flood a later run).
- `--merge-into` skips a posting the scan file already holds from JobRight (same apply URL), so one job is never applied to twice in a run.
- Items arrive with `source: simplify`, `first_seen` set to when Simplify added the listing, `term_text` from Simplify's terms, and `apply_url` pointing at the employer's own posting. `job-gate` reads the live posting and gates them like any other item.
- If it prints `"ok": false`, the seen file is untouched; say so in the scan summary and carry on with the other sources.
- Add the Simplify counts to the one-line summary: new listings, backlog items taken, backlog left, and how many were added after dedupe.

**Backlog (postings that opened before job-agent started watching).** The scan above only sees listings that are new since the last run, so roles that opened weeks ago and are still open never come up. To load them once:

```
python3 scripts/simplify_source.py backlog --backlog <workspace>/state/simplify-backlog.json \
  --days <sources.simplify.backlog_days or 20> --categories "<...>" --term "<term>" \
  --first-companies "<every company in prestige.tiers, comma-joined>"
```

Run it when the user asks for the backlog or runs `/job-agent:run backlog`. Report the count and how many runs it will take at `backlog_per_run` a run. Rebuilding replaces the file. After that, every scan (including the one in the same run) drains it: add `--backlog <workspace>/state/simplify-backlog.json --backlog-take <sources.simplify.backlog_per_run or 20>` to the scan command whenever that file exists. Backlog items carry `"backlog": true`; job-gate skips its freshness checks for them (every other rule still applies), and the queue fills fresh postings before backlog ones, so a backlog never pushes a brand-new posting back.

## Extra sources (optional, pluggable)

After JobRight, read each entry in `sources.extra` in order. Each one adds items to the same scan file with `source: <name>`, and every item is gated the same way. Built-in kinds:

- `gmail`: newsletters or job-drop emails from the `from` sender, newer than the `last_read` line for this source in `state/sources.json`. Read each issue in full, take each posting's link through to the employer's live req, and update `last_read` at the end. Drops that are days old by design belong in `freshness.exempt_sources`.
- `page`: a public careers or job-list page, read in your browser like a person would, with no login.

To add another kind (a Discord channel the user reads, a club board), write it as a short procedure in `sources.extra` with what to read, how to find the live req ID, and where to keep its checkpoint. Rules for every extra source: read every item (an image post has text in the image), resolve each to the employer's live posting and req ID, keep a checkpoint or seen set so nothing is read twice, pace like a person, and stop for good on a login wall, challenge or "unusual activity" notice (write a pause file such as `state/<source>.paused` with the reason and skip that source until the user removes it). Never type credentials or solve a challenge.

## Events

Info sessions, RSVP forms and QR-code links from any source are passes, not noise: some employers flag applications from people who attended. Add them with `kind: event`, the event date and the RSVP link. Check email for an existing RSVP first and skip events that are over. `apply-fill` fills an RSVP form like an application and never submits it, even with `auto_submit: true`.

## Indeed (fallback)

When JobRight is disabled, empty, or blocked, and an Indeed MCP connector is available, call `search_jobs` for each query in `sources.indeed.queries` with the user's locations, then `get_job_details` for each result. Map fields into the same output shape with `source: "indeed"`. If neither source works, report that and stop.

## Never

- Scrape LinkedIn or automate social media. An extra source the user set up is read through its normal viewer at human pace, never through private APIs.
- Use undocumented APIs or tokens pulled from the page. Reading a job's own info page (`/jobs/info/<id>`, the page a click opens) is reading the site, not an API.
- Apply or click Apply buttons during a scan.
