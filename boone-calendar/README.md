# Boone County, IN -- Consolidated Events Calendar

Pulls events from nine local sources (Lebanon, Whitestown, Boone County
government, Discover Boone County, Heart of Lebanon, Thorntown, Zionsville,
Jamestown) and merges them into one `.ics` file, twice a week, for free,
hosted on GitHub Pages so you can subscribe to it from Google Calendar.

## One-time setup (about 10 minutes)

1. **Create a GitHub account** if you don't have one: https://github.com/signup
   (free).

2. **Create a new repository.**
   - Click the `+` in the top right -> "New repository".
   - Name it anything, e.g. `boone-calendar`.
   - Set it to **Public** (required for the free version of GitHub Pages to
     serve the file without authentication -- so the .ics contents will be
     visible to anyone with the link, same as any public calendar feed).
   - Click "Create repository".

3. **Upload these files** to that repository, keeping the folder structure:
   ```
   boone-calendar/
     build_calendar.py
     requirements.txt
     README.md
     docs/
       calendar.ics
     .github/
       workflows/
         update-calendar.yml
   ```
   Easiest way: on the repo's GitHub page, click "Add file" -> "Upload
   files", drag the whole folder in, and commit.

4. **Turn on GitHub Pages.**
   - In the repo, go to Settings -> Pages.
   - Under "Build and deployment" -> "Source", choose **Deploy from a
     branch**.
   - Branch: `main`, folder: `/docs`. Save.
   - GitHub will show you a URL like:
     `https://<your-username>.github.io/boone-calendar/`
   - Your calendar file will be at:
     `https://<your-username>.github.io/boone-calendar/calendar.ics`

5. **Run it once by hand** to populate real data (don't wait for the
   schedule):
   - Go to the "Actions" tab -> "Update consolidated calendar" workflow ->
     "Run workflow" -> "Run workflow".
   - Wait ~1 minute, refresh, confirm it finished with a green check.
   - Check the "build" step's log output -- it prints how many events it
     found per source and flags anything it couldn't parse (see
     "Known limitations" below).

6. **Subscribe in Google Calendar:**
   - Open Google Calendar on desktop -> left sidebar -> "Other calendars"
     -> `+` -> "From URL".
   - Paste `https://<your-username>.github.io/boone-calendar/calendar.ics`
   - Click "Add calendar".
   - Google typically re-checks subscribed URLs every 12-24 hours on its
     own schedule (this isn't configurable) -- separately, this repo
     refreshes the underlying file twice a week automatically.

That's it. From here on, the GitHub Action re-runs automatically Mondays
and Thursdays at 11:00 UTC (edit the `cron` lines in
`.github/workflows/update-calendar.yml` to change the schedule), regenerates
`docs/calendar.ics`, and commits it -- no further action needed from you.

## Known limitations (please read)

These sources are a mix of clean machine-readable feeds and plain HTML
pages never meant to be scraped, so quality varies a lot by source:

- **Lebanon, Whitestown, Boone County government** -- clean official iCal
  feeds. Reliable.
- **Zionsville** -- CivicPlus calendar. The script uses a guessed export
  URL for their iCal feed; if it 0-events on first run, open
  `zionsville-in.gov/Calendar.aspx`, click "Subscribe to iCalendar," copy
  the real link, and paste it into `ZIONSVILLE_ICAL_URL` in
  `build_calendar.py`.
- **Discover Boone County** -- no feed, paginated HTML scrape. Many of
  their listings use loose text for recurring events (e.g. "Sundays, July
  19, 26, and August 2") -- the script captures the first date as an anchor
  and puts the full text in the event description rather than guessing at
  every recurrence.
- **Heart of Lebanon** -- no feed at all (the `?ical=1` URL you gave
  returns a 404; this site isn't running the plugin that generates one).
  The script only reliably captures their "Up Next" (today/tomorrow)
  section. Their full monthly calendar is a JS-rendered grid that a simple
  scrape can't read reliably. **This is the weakest source** -- if this
  calendar matters most to you, the better fix is asking Heart of Lebanon
  to publish an iCal feed, or switching to their Facebook events if they
  post there too.
- **Thorntown** -- uses the Google Sheet as the source of truth (the town
  page itself is stale, showing only Jan/Feb). Make sure that sheet's
  sharing setting is "Anyone with the link can view," or the export URL
  will fail.
- **Jamestown** -- their calendar page redirected repeatedly when tested
  and its structure is unknown; the script has a generic best-effort
  scraper. Check the Action log after the first run -- if it says 0
  events, open the page yourself and tell me what the event listing looks
  like so the selector can be fixed.

Every event's title is prefixed with its source in brackets (e.g.
`[lebanon] City Council Meeting`) so you can tell at a glance where it came
from, and because Google Calendar subscribed feeds are read-only anyway.

## Adjusting the schedule

Edit `.github/workflows/update-calendar.yml`. The two `cron` lines are in
UTC. For example, to run Tuesday and Friday at 7am Eastern (11:00/12:00
UTC depending on DST):
```yaml
- cron: "0 11 * * 2"
- cron: "0 11 * * 5"
```
