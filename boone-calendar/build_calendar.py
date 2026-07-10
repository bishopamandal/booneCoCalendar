#!/usr/bin/env python3
"""
Builds a single merged .ics calendar from several Boone County, Indiana
event sources, and writes it to docs/calendar.ics (served by GitHub Pages).

Run on a schedule by .github/workflows/update-calendar.yml.

Each source has its own fetch_* function that returns a list of dicts:
    {"uid": str, "summary": str, "start": datetime, "end": datetime|None,
     "all_day": bool, "location": str, "description": str, "url": str,
     "source": str}
Sources that only publish loose text (dates like "every Saturday through
Sept 26") are parsed on a best-effort basis; anything we can't confidently
turn into a real date is skipped and logged to stderr rather than guessed.
"""
import re
import sys
import hashlib
import datetime as dt
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
from dateutil import parser as dtparser

UA = {"User-Agent": "Mozilla/5.0 (compatible; BooneCountyCalendarBot/1.0; +for personal use)"}
TIMEOUT = 20


def log(msg):
    print(msg, file=sys.stderr)


def make_uid(source, *parts):
    raw = "|".join(str(p) for p in parts)
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{source}-{h}@boone-consolidated-calendar"


# ---------------------------------------------------------------------------
# 1. Clean iCal (Events Calendar Pro / "The Events Calendar") feeds.
#    These three just need to be fetched and re-emitted with prefixed UIDs.
# ---------------------------------------------------------------------------
ICAL_SOURCES = {
    "lebanon": "https://lebanon.in.gov/events/list/?ical=1",
    "whitestown": "https://whitestown.in.gov/events/list/?ical=1",
    "boonecounty": "https://boonecounty.in.gov/events/list/?ical=1",
}


def fetch_ical_source(name, url):
    events = []
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        cal = Calendar.from_ical(r.text)
    except Exception as e:
        log(f"[{name}] FAILED to fetch/parse: {e}")
        return events

    for comp in cal.walk("VEVENT"):
        try:
            summary = str(comp.get("summary", ""))
            dtstart = comp.get("dtstart").dt
            dtend = comp.get("dtend").dt if comp.get("dtend") else None
            location = str(comp.get("location", "") or "")
            description = str(comp.get("description", "") or "")
            url_ = str(comp.get("url", "") or "")
            orig_uid = str(comp.get("uid", ""))
            events.append({
                "uid": make_uid(name, orig_uid),
                "summary": summary,
                "start": dtstart,
                "end": dtend,
                "all_day": not isinstance(dtstart, dt.datetime),
                "location": location,
                "description": description,
                "url": url_,
                "source": name,
            })
        except Exception as e:
            log(f"[{name}] skipped a malformed VEVENT: {e}")
    log(f"[{name}] parsed {len(events)} events")
    return events


# ---------------------------------------------------------------------------
# 2. Zionsville (CivicPlus / CivicEngage calendar). CivicPlus exposes an
#    iCalendar export at this path for the "all calendars" view. Verify this
#    still works after the first run -- CivicPlus occasionally changes the
#    catID scheme when calendars are added/removed.
# ---------------------------------------------------------------------------
ZIONSVILLE_ICAL_URL = "https://www.zionsville-in.gov/common/modules/iCalendar/iCalendar.aspx?catID=0&feed=calendar"


def fetch_zionsville():
    events = []
    try:
        r = requests.get(ZIONSVILLE_ICAL_URL, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        cal = Calendar.from_ical(r.text)
    except Exception as e:
        log(f"[zionsville] FAILED ({e}) -- CivicPlus export URL may need updating. "
            f"Visit https://www.zionsville-in.gov/calendar.aspx , click 'Subscribe to "
            f"iCalendar', and copy the real URL into ZIONSVILLE_ICAL_URL.")
        return events

    for comp in cal.walk("VEVENT"):
        try:
            summary = str(comp.get("summary", ""))
            dtstart = comp.get("dtstart").dt
            dtend = comp.get("dtend").dt if comp.get("dtend") else None
            location = str(comp.get("location", "") or "")
            description = str(comp.get("description", "") or "")
            url_ = str(comp.get("url", "") or "")
            orig_uid = str(comp.get("uid", "")) or summary + str(dtstart)
            events.append({
                "uid": make_uid("zionsville", orig_uid),
                "summary": summary,
                "start": dtstart,
                "end": dtend,
                "all_day": not isinstance(dtstart, dt.datetime),
                "location": location,
                "description": description,
                "url": url_,
                "source": "zionsville",
            })
        except Exception as e:
            log(f"[zionsville] skipped malformed VEVENT: {e}")
    log(f"[zionsville] parsed {len(events)} events")
    return events


# ---------------------------------------------------------------------------
# 3. Discover Boone County -- paginated WordPress listing, no feed.
#    We walk /events/upcoming-events/ and /events/upcoming-events/page/N/
#    until a page 404s or repeats. Dates are loosely formatted ("July 10,
#    and Friday nights thru July 31, 2026") so we only extract the FIRST
#    concrete date in each listing as the anchor date; the free-text date
#    range is preserved in the description so nothing is lost, just not
#    fully expanded into recurring instances.
# ---------------------------------------------------------------------------
DBC_BASE = "https://discoverboonecounty.com/events/upcoming-events/"
DATE_RE = re.compile(
    r"([A-Z][a-z]+ \d{1,2}(?:\s*[-–,]\s*\d{1,2})?,?\s*\d{4})"
)


def parse_first_date(text):
    m = DATE_RE.search(text)
    if not m:
        return None
    chunk = m.group(1)
    chunk = re.sub(r"\s*[-–]\s*\d{1,2}", "", chunk)  # drop "10-12" -> "10"
    try:
        return dtparser.parse(chunk, fuzzy=True).date()
    except Exception:
        return None


def fetch_discover_boone_county(max_pages=10):
    events = []
    for page in range(1, max_pages + 1):
        url = DBC_BASE if page == 1 else urljoin(DBC_BASE, f"page/{page}/")
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            if r.status_code == 404:
                break
            r.raise_for_status()
        except Exception as e:
            log(f"[discoverboonecounty] stopped at page {page}: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        # Each event is an <h2>/<h3> link inside the events list; adjust
        # selector here if the site's markup changes.
        cards = soup.select("article, .event-listing, li.event") or soup.find_all("h2")
        found_this_page = 0
        for h in soup.find_all(["h2", "h3"]):
            a = h.find("a")
            if not a or "/events/event/" not in (a.get("href") or ""):
                continue
            title = a.get_text(strip=True)
            link = a["href"]
            # date/location text usually follows in sibling text nodes
            container = h.find_parent()
            text = container.get_text(" ", strip=True) if container else ""
            date_ = parse_first_date(text)
            if not date_:
                log(f"[discoverboonecounty] couldn't parse a date for '{title}', skipping")
                continue
            found_this_page += 1
            events.append({
                "uid": make_uid("discoverboonecounty", link),
                "summary": title,
                "start": date_,
                "end": None,
                "all_day": True,
                "location": "",
                "description": f"{text}\n{link}",
                "url": link,
                "source": "discoverboonecounty",
            })
        log(f"[discoverboonecounty] page {page}: {found_this_page} events")
        if found_this_page == 0:
            break
    log(f"[discoverboonecounty] total {len(events)} events")
    return events


# ---------------------------------------------------------------------------
# 4. Heart of Lebanon -- no ical feed; the "Up Next" section on
#    /calendar-of-events/ only covers today/tomorrow reliably. We pull that,
#    plus best-effort parse of the monthly table if present.
# ---------------------------------------------------------------------------
HOL_URL = "https://heartoflebanon.org/calendar-of-events/"


def fetch_heart_of_lebanon():
    events = []
    try:
        r = requests.get(HOL_URL, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        log(f"[heartoflebanon] FAILED to fetch: {e}")
        return events

    soup = BeautifulSoup(r.text, "html.parser")
    # "Up Next" list items look like: bold title, then "Month D, YYYY H:MM AM - H:MM PM  Location"
    for item in soup.select("li"):
        strong = item.find(["strong", "b"])
        if not strong:
            continue
        title = strong.get_text(strip=True)
        text = item.get_text(" ", strip=True)
        m = re.search(
            r"([A-Z][a-z]+ \d{1,2}, \d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)",
            text,
        )
        if not m:
            continue
        try:
            start = dtparser.parse(f"{m.group(1)} {m.group(2)}")
            end = dtparser.parse(f"{m.group(1)} {m.group(3)}")
        except Exception:
            continue
        events.append({
            "uid": make_uid("heartoflebanon", title, m.group(0)),
            "summary": title,
            "start": start,
            "end": end,
            "all_day": False,
            "location": "",
            "description": text,
            "url": HOL_URL,
            "source": "heartoflebanon",
        })
    log(f"[heartoflebanon] parsed {len(events)} events (Up Next section only -- "
        f"this site has no iCal feed, so far-future events aren't reliably captured)")
    return events


# ---------------------------------------------------------------------------
# 5. Thorntown -- meeting schedule Google Sheet (CSV export) is the
#    authoritative source; the town website page is often stale/partial.
# ---------------------------------------------------------------------------
THORNTOWN_SHEET_CSV = (
    "https://docs.google.com/spreadsheets/d/"
    "1BGjLONlhcr-MEXs9PupSH9TrUG7QDenWnNtdyrwaTLY/export?format=csv&gid=0"
)


def fetch_thorntown():
    events = []
    try:
        r = requests.get(THORNTOWN_SHEET_CSV, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
    except Exception as e:
        log(f"[thorntown] FAILED to fetch meeting schedule sheet: {e}")
        return events

    import csv
    import io
    reader = csv.reader(io.StringIO(r.text))
    rows = list(reader)
    # Expect roughly: [meeting name, date, time, ...] per row -- the exact
    # columns depend on the sheet's layout, so we scan every cell for a
    # date-looking token and pair it with the row's other text as the title.
    for row in rows:
        row_text = " | ".join(c.strip() for c in row if c.strip())
        if not row_text:
            continue
        date_ = None
        time_ = None
        for cell in row:
            cell = cell.strip()
            if not cell:
                continue
            try:
                parsed = dtparser.parse(cell, fuzzy=False)
                if re.search(r"\d{1,2}:\d{2}", cell):
                    time_ = parsed.time()
                elif re.search(r"\d{4}", cell) or re.search(r"[A-Za-z]+ \d{1,2}", cell):
                    date_ = parsed.date()
            except Exception:
                continue
        if not date_:
            continue
        title = row[0].strip() if row[0].strip() else row_text[:60]
        start = dt.datetime.combine(date_, time_) if time_ else date_
        events.append({
            "uid": make_uid("thorntown", row_text),
            "summary": title,
            "start": start,
            "end": None,
            "all_day": time_ is None,
            "location": "Thorntown Town Hall, 101 W. Main St., Thorntown, IN 46071",
            "description": row_text,
            "url": "https://townofthorntown.com/calendar-of-events",
            "source": "thorntown",
        })
    log(f"[thorntown] parsed {len(events)} rows from meeting schedule sheet")
    return events


# ---------------------------------------------------------------------------
# 6. Jamestown -- in.gov town page. Structure unknown/unstable at time of
#    writing (redirected repeatedly during testing). Best-effort generic
#    scrape; check stderr output after first run and adjust the selector.
# ---------------------------------------------------------------------------
JAMESTOWN_URL = "https://www.in.gov/towns/jamestown/calendar/"


def fetch_jamestown():
    events = []
    try:
        r = requests.get(JAMESTOWN_URL, headers=UA, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        log(f"[jamestown] FAILED to fetch ({e}). This page may require manual "
            f"inspection -- open it in a browser and update fetch_jamestown().")
        return events

    soup = BeautifulSoup(r.text, "html.parser")
    for item in soup.select("li, .event, article"):
        text = item.get_text(" ", strip=True)
        date_ = parse_first_date(text)
        if not date_:
            continue
        title_el = item.find(["h2", "h3", "h4", "a"])
        title = title_el.get_text(strip=True) if title_el else text[:60]
        events.append({
            "uid": make_uid("jamestown", title, str(date_)),
            "summary": title,
            "start": date_,
            "end": None,
            "all_day": True,
            "location": "Jamestown, IN",
            "description": text,
            "url": JAMESTOWN_URL,
            "source": "jamestown",
        })
    log(f"[jamestown] parsed {len(events)} events")
    return events


# ---------------------------------------------------------------------------
# Merge + write .ics
# ---------------------------------------------------------------------------
def build():
    all_events = []
    for name, url in ICAL_SOURCES.items():
        all_events += fetch_ical_source(name, url)
    all_events += fetch_zionsville()
    all_events += fetch_discover_boone_county()
    all_events += fetch_heart_of_lebanon()
    all_events += fetch_thorntown()
    all_events += fetch_jamestown()

    cal = Calendar()
    cal.add("prodid", "-//Boone County IN Consolidated Calendar//github//")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Boone County, IN -- Consolidated Events")
    cal.add("x-wr-timezone", "America/Indiana/Indianapolis")

    seen_uids = set()
    for e in all_events:
        if e["uid"] in seen_uids:
            continue
        seen_uids.add(e["uid"])

        ev = Event()
        ev.add("uid", e["uid"])
        ev.add("summary", f"[{e['source']}] {e['summary']}")
        ev.add("dtstart", e["start"])
        if e["end"]:
            ev.add("dtend", e["end"])
        if e["location"]:
            ev.add("location", e["location"])
        desc = e["description"] or ""
        if e["url"]:
            desc = f"{desc}\n\n{e['url']}".strip()
        if desc:
            ev.add("description", desc)
        ev.add("dtstamp", dt.datetime.utcnow())
        cal.add_component(ev)

    log(f"TOTAL merged events: {len(seen_uids)}")

    with open("docs/calendar.ics", "wb") as f:
        f.write(cal.to_ical())


if __name__ == "__main__":
    build()
