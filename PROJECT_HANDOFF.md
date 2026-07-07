# Lead Scraper Project: Handoff Document

## 1. Project Overview

### What this project is
A lead generation tool that pulls business contact information from public data sources (starting with Google Places and Yelp APIs) and outputs a clean, deduplicated list of leads. It began as a Python command line script and has since grown into a Streamlit browser app so search terms and locations can be changed without touching code.

### The overall objective
Build a repeatable pipeline that collects business leads in specific service industries, initially framed around businesses that could use website design services, and more broadly usable for any local business outreach campaign (the owner also runs a marina and dock rental marketplace business, so this tool doubles as a general purpose local business lead finder for that context too).

### The end goal
A scraper and enrichment pipeline that outputs CRM ready records containing: business name, owner or primary contact name where publicly listed, business address, phone number, public business email, website URL, business category, city and state, Google rating and review count, and social media links. Records should land in a format that drops directly into HubSpot (the CRM already in use) or a SQLite/Postgres database for larger volumes.

### Intended users
The project owner and a colleague (Tal) who work in outbound business development. Non-technical end use is expected, hence the shift toward a point and click app interface rather than a command line tool.

## 2. Architecture

### Tech stack
- Python 3.12
- requests (HTTP calls to Google Places and Yelp APIs)
- Streamlit (browser based UI)
- pandas (in memory table handling and CSV export in the app)
- csv (standard library, used in the CLI version)
- argparse (standard library, CLI argument parsing)

### Project structure
Current state (two files, flat structure):
```
lead_scraper/
  lead_scraper.py   # core scraping logic + CLI entrypoint
  app.py            # Streamlit UI, imports functions from lead_scraper.py
```
Both files must live in the same folder since app.py does a direct Python import from lead_scraper.py. There is no packaging (no setup.py, no requirements.txt yet) as this is still an early stage internal tool.

### Dependencies
Not yet pinned in a requirements.txt. Install manually:
```
pip install requests streamlit pandas
```

### APIs
- Google Places API: Text Search endpoint (`https://maps.googleapis.com/maps/api/place/textsearch/json`) for the initial business search, then Place Details endpoint (`https://maps.googleapis.com/maps/api/place/details/json`) per result to pull phone number and website (Text Search alone does not return those two fields).
- Yelp Fusion API: Business Search endpoint (`https://api.yelp.com/v3/businesses/search`), single call per term/location pair, paginated via offset.

Both require the caller to provide their own API key. Neither key is stored anywhere in the code, they are read from environment variables or entered by hand in the Streamlit sidebar (as a password-masked field, session only, not persisted to disk).

### External services
- Google Cloud Console account with Places API enabled (billing required past free monthly credit)
- Yelp Fusion developer account (free tier, daily call cap)

### Database schema
No database yet. Current output is a flat CSV / in-memory pandas DataFrame with these columns:
```
name, address, phone, website, rating, review_count, source, search_term, search_location
```
This is the single biggest architectural gap for the next phase: recommended schema is discussed in section 5 and 8 below.

### Data flow
1. User provides search terms (e.g. "marina", "boat dealer") and locations (e.g. "Fort Lauderdale FL") via CLI flags or the Streamlit text areas.
2. For each term x location x source combination, the corresponding fetch function is called.
3. Google flow: Text Search returns a list of places, then for each place a second Details call fetches phone and website.
4. Yelp flow: single Search call returns businesses directly including phone and website in one response, paginated if results exceed page size.
5. All rows from all sources are pooled into one list.
6. A dedup pass runs over the pooled list, keyed primarily on normalized phone number (digits only), falling back to a lowercased name + address composite key when no phone is present.
7. The deduped list is written to CSV (CLI version) or rendered as a table with a download button (Streamlit version).

### Scraping workflow
This is not page scraping. Every data source used so far is an official API called with an API key, which is a deliberate choice (see section 4). "Scraping" in this project currently means calling structured APIs, not parsing HTML from search result pages.

## 3. Current Progress

### Features completed
- CLI scraper (`lead_scraper.py`) that queries Google Places and Yelp for a list of terms x locations, merges results, dedupes, and writes CSV. Tested end to end with mocked API responses (real API calls not testable inside the build sandbox, which only whitelists a small set of dev-related domains, not googleapis.com or yelp.com).
- Streamlit app (`app.py`) wrapping the same core functions with a browser UI: sidebar API key inputs, editable term/location text areas, source checkboxes, a run button with live progress bar, results table, and CSV download button. Boot-tested headless with no runtime errors.
- Dedup logic verified with unit-style manual tests: two records for the same business from different sources with differently formatted phone numbers and addresses correctly collapsed into one record.

### Features partially completed
- None. Everything built so far is either fully working (against mocked data, pending a real-key test) or not started.

### Features not started
- Owner/primary contact name enrichment via state Secretary of State business registries.
- Business email extraction from a company's own website (fetch homepage/contact page, parse for a listed email address).
- Social media link extraction from company websites.
- Business category normalization (currently whatever raw category string each API returns, if any, is not even being captured yet, only name/address/phone/website/rating/review_count/source/search_term/search_location are captured).
- City/state as separate structured fields (currently folded into the single `address` string).
- Persistent storage (SQLite/Postgres). Everything today is CSV/in-memory only, so nothing is preserved between runs and there's no way to detect "this lead was already collected three weeks ago."
- Re-verification / refresh pass for stale records.
- HubSpot-native field mapping or direct API push (currently just a generic CSV).
- Email validation (MX record checks) and phone number format validation.
- Deployment beyond local `streamlit run` (no hosting, no shared access for Tal yet).

### Known issues
- Google Place Details is called once per place result, which multiplies API call volume (and cost) roughly 2x versus Search alone. This was a deliberate simplification, not a bug, but it's worth flagging as a cost driver.
- No caching layer, so rerunning the same term/location combination burns API quota again with no benefit.
- No rate limiting/backoff beyond the mandatory 2 second sleep Google requires before a next_page_token becomes valid; a large batch of searches could still hit Yelp's daily cap with no graceful handling beyond a printed warning.
- Category field is not currently captured from either API's response even though both APIs return one.

### Current limitations
- No error recovery beyond try/except around each API call, a failure just logs a warning to stderr and moves on to the next combination.
- No tests directory, all verification so far was done ad hoc in the build sandbox with mocked functions.
- Streamlit app has no persistent state across browser sessions, everything resets on refresh except within a single running session's `st.session_state`.

## 4. Development Strategy

### Why certain libraries were chosen
- **requests** over httpx or urllib: simplest, most familiar, sufficient for the request volume involved, no need for async given the sequential term/location loop structure.
- **Streamlit** over Flask or a React frontend: fastest path to a usable point-and-click interface for a non-technical daily user, with almost no frontend code required, built-in widgets (text areas, checkboxes, progress bars, dataframes, download buttons) cover the entire UI need without writing HTML/CSS/JS.
- **pandas** in the Streamlit app specifically: Streamlit's `st.dataframe` and CSV export both work naturally with a DataFrame, and it was only pulled in on the app side, the CLI script deliberately stays dependency-light with just the standard library `csv` module.
- **argparse** for the CLI: standard library, no reason to add a third-party CLI framework for four flags.

### Why the scraper works the way it does
The single most important architectural decision in this project: only official, sanctioned APIs are used (Google Places API, Yelp Fusion API), never direct HTML scraping of Google Maps or Yelp web pages. This was a deliberate choice discussed explicitly with the user, for two reasons. First, official APIs return clean structured JSON with no HTML parsing fragility. Second, and more importantly, scraping the actual web pages of Google Maps or Yelp (as opposed to calling their published APIs) violates those platforms' terms of service, whereas the official APIs are built and published specifically for this kind of programmatic access. The same reasoning excluded LinkedIn entirely from the source list, LinkedIn actively prohibits and enforces against scraping (including of "publicly visible" profile pages) through contract and trespass claims, so it was recommended against rather than built.

The two-step Google flow (Text Search, then Details per result) exists because Text Search's response does not include phone number or website, only Details does. This was a known tradeoff accepted for data completeness at the cost of extra API calls.

### Scaling considerations
Current design assumes low-to-moderate volume (dozens of term/location combinations per run, tens of results per combination). At meaningfully larger scale, the flat CSV/in-memory approach breaks down for two reasons: no way to incrementally add to an existing dataset without reloading and re-deduping everything, and no way to know which records have already been collected versus are new. This is the primary reason a database layer (SQLite to start, Postgres if this grows past single-user use) is the top recommended next step.

### Error handling strategy
Currently minimal and intentionally so for a first version: each API call is wrapped in a try/except that catches `requests.RequestException`, logs a warning with context (which term, which location, which source) to stderr, and continues the loop rather than aborting the whole run. Non-200 responses from Yelp and non-OK/ZERO_RESULTS statuses from Google are logged and treated as "stop paginating this combination" rather than a hard failure. Nothing currently retries a failed call.

### Anti-blocking strategy
This project deliberately has no anti-blocking strategy (no proxy rotation, no user-agent spoofing, no request throttling to evade detection) because none is needed: every call goes through an official, authenticated API endpoint rather than a scraped web page, so there is nothing to "evade." The only rate consideration implemented is the mandatory short delay before reusing a Google `next_page_token`, which is a documented API requirement, not an anti-detection measure.

### Data validation approach
Essentially none implemented yet beyond the dedup key normalization (stripping/lowercasing text, digit-only phone comparison). No email validation, no phone format validation, no website liveness check exist yet. This is called out explicitly in section 5 as a near-term priority once email enrichment is added, since a scraped email is only useful if it's confirmed deliverable-looking (valid format, resolvable domain) before it goes into a CRM record or an outreach sequence.

## 5. Remaining Tasks

### High priority
1. Add business category, city, and state as separate structured fields instead of only inside the free-text address string (both APIs already return enough to derive this, small change, high value for filtering later).
2. Build the website enrichment module: given a business's website URL (already collected), fetch the page, parse for a contact email address and social media links (Instagram, Facebook, LinkedIn company page). Use requests + BeautifulSoup, respect robots.txt, add a reasonable timeout and a descriptive User-Agent identifying the request as a legitimate business outreach tool rather than spoofing a browser.
3. Move storage from flat CSV to SQLite, with a unique constraint on the dedup key so reruns naturally skip or update existing records instead of duplicating.
4. Add basic validation: regex-level email format check, MX record lookup to confirm the domain accepts mail, phone number format normalization to E.164.

### Medium priority
5. Add a Secretary of State business registry lookup module for one state to start (Florida, given the user's location), to pull owner/registered agent name for LLC-registered businesses. This will likely need to be built per-state since formats and access methods differ (some states expose bulk downloadable data, others only a one-record-at-a-time web form).
6. Add a caching layer keyed on term+location+source so reruns within a configurable window (e.g. 30 days) skip re-querying APIs for combinations already collected.
7. Add a "refresh" mode: given an existing database of leads, re-query Google/Yelp for just those specific businesses and flag ones that no longer resolve or have materially changed contact info.
8. Map output fields to HubSpot's exact contact/company import column names so CSV exports drop into HubSpot's import tool with zero manual remapping.

### Low priority
9. HubSpot API direct push (skip the CSV export step entirely).
10. Multi-state Secretary of State registry support.
11. Deploy the Streamlit app somewhere shared (e.g. a small VPS or Streamlit Community Cloud) so Tal can access it without the user running it locally, including basic auth since it will hold API keys and lead data.
12. Add a proper requirements.txt / pyproject.toml and a tests directory with real (non-mocked-inline) unit tests.

### Estimated implementation order
Category/city/state fields, then website enrichment (email + social), then SQLite migration, then validation, then Secretary of State module, then caching/refresh, then HubSpot field mapping, then deployment and direct HubSpot API push last.

## 6. Source Code

### /src/lead_scraper.py
```python
#!/usr/bin/env python3
"""
Business Directory Lead Scraper
Pulls business leads from Google Places API and Yelp Fusion API and writes a deduped CSV.

Setup:
  pip install requests

  Set your API keys as environment variables, or pass them as arguments:
    export GOOGLE_PLACES_API_KEY="your_key_here"
    export YELP_API_KEY="your_key_here"

Usage:
  python3 lead_scraper.py --terms "marina,boat dealer,yacht club" --locations "Fort Lauderdale FL,Miami FL" --output leads.csv

  Flags:
    --terms       Comma separated search terms
    --locations   Comma separated locations
    --output      Output CSV file path (default: leads.csv)
    --sources     Comma separated sources to use: google,yelp (default: both)
    --limit       Max results per term/location/source combo (default: 20, max 20 per Yelp page, Google returns up to 60 via pagination)
"""

import argparse
import csv
import os
import sys
import time
import requests


GOOGLE_PLACES_TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
GOOGLE_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
YELP_SEARCH_URL = "https://api.yelp.com/v3/businesses/search"


def normalize_phone(phone):
    if not phone:
        return ""
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits


def dedup_key(name, address, phone):
    name_key = (name or "").strip().lower()
    phone_key = normalize_phone(phone)
    addr_key = (address or "").strip().lower()
    if phone_key:
        return f"phone:{phone_key}"
    return f"name_addr:{name_key}|{addr_key}"


def fetch_google_places(term, location, api_key, limit=20):
    results = []
    query = f"{term} in {location}"
    params = {"query": query, "key": api_key}
    next_page_token = None

    while True:
        if next_page_token:
            params = {"pagetoken": next_page_token, "key": api_key}
            time.sleep(2)  # Google requires a short delay before the next_page_token becomes valid

        resp = requests.get(GOOGLE_PLACES_TEXTSEARCH_URL, params=params, timeout=15)
        data = resp.json()

        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            print(f"  [google] warning: status={status} message={data.get('error_message')}", file=sys.stderr)
            break

        for place in data.get("results", []):
            place_id = place.get("place_id")
            details = fetch_google_place_details(place_id, api_key) if place_id else {}
            results.append({
                "name": place.get("name", ""),
                "address": place.get("formatted_address", ""),
                "phone": details.get("phone", ""),
                "website": details.get("website", ""),
                "rating": place.get("rating", ""),
                "review_count": place.get("user_ratings_total", ""),
                "source": "google",
                "search_term": term,
                "search_location": location,
            })
            if len(results) >= limit:
                return results

        next_page_token = data.get("next_page_token")
        if not next_page_token:
            break

    return results


def fetch_google_place_details(place_id, api_key):
    params = {
        "place_id": place_id,
        "fields": "formatted_phone_number,website",
        "key": api_key,
    }
    try:
        resp = requests.get(GOOGLE_PLACES_DETAILS_URL, params=params, timeout=15)
        data = resp.json()
        result = data.get("result", {})
        return {
            "phone": result.get("formatted_phone_number", ""),
            "website": result.get("website", ""),
        }
    except requests.RequestException as exc:
        print(f"  [google] details fetch failed for {place_id}: {exc}", file=sys.stderr)
        return {}


def fetch_yelp(term, location, api_key, limit=20):
    results = []
    headers = {"Authorization": f"Bearer {api_key}"}
    offset = 0
    page_size = min(limit, 50)

    while len(results) < limit:
        params = {
            "term": term,
            "location": location,
            "limit": page_size,
            "offset": offset,
        }
        resp = requests.get(YELP_SEARCH_URL, headers=headers, params=params, timeout=15)

        if resp.status_code != 200:
            print(f"  [yelp] warning: status={resp.status_code} body={resp.text[:200]}", file=sys.stderr)
            break

        data = resp.json()
        businesses = data.get("businesses", [])
        if not businesses:
            break

        for biz in businesses:
            location_obj = biz.get("location", {})
            address = ", ".join(filter(None, location_obj.get("display_address", [])))
            results.append({
                "name": biz.get("name", ""),
                "address": address,
                "phone": biz.get("phone", ""),
                "website": biz.get("url", ""),
                "rating": biz.get("rating", ""),
                "review_count": biz.get("review_count", ""),
                "source": "yelp",
                "search_term": term,
                "search_location": location,
            })
            if len(results) >= limit:
                break

        offset += page_size
        if offset >= data.get("total", 0):
            break

    return results


def run(terms, locations, sources, google_key, yelp_key, limit, output_path):
    all_rows = []
    seen = set()

    for term in terms:
        for location in locations:
            if "google" in sources:
                if not google_key:
                    print("Skipping Google: no API key provided", file=sys.stderr)
                else:
                    print(f"[google] searching '{term}' in '{location}'...")
                    try:
                        rows = fetch_google_places(term, location, google_key, limit=limit)
                        all_rows.extend(rows)
                    except requests.RequestException as exc:
                        print(f"  [google] request failed: {exc}", file=sys.stderr)

            if "yelp" in sources:
                if not yelp_key:
                    print("Skipping Yelp: no API key provided", file=sys.stderr)
                else:
                    print(f"[yelp] searching '{term}' in '{location}'...")
                    try:
                        rows = fetch_yelp(term, location, yelp_key, limit=limit)
                        all_rows.extend(rows)
                    except requests.RequestException as exc:
                        print(f"  [yelp] request failed: {exc}", file=sys.stderr)

    deduped_rows = []
    for row in all_rows:
        key = dedup_key(row["name"], row["address"], row["phone"])
        if key in seen:
            continue
        seen.add(key)
        deduped_rows.append(row)

    fieldnames = ["name", "address", "phone", "website", "rating", "review_count", "source", "search_term", "search_location"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deduped_rows)

    print(f"\nDone. {len(all_rows)} raw results, {len(deduped_rows)} after dedup.")
    print(f"Written to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Scrape business leads from Google Places and Yelp APIs into a CSV")
    parser.add_argument("--terms", required=True, help="Comma separated search terms, e.g. 'marina,boat dealer,yacht club'")
    parser.add_argument("--locations", required=True, help="Comma separated locations, e.g. 'Fort Lauderdale FL,Miami FL'")
    parser.add_argument("--sources", default="google,yelp", help="Comma separated sources to use: google,yelp")
    parser.add_argument("--output", default="leads.csv", help="Output CSV file path")
    parser.add_argument("--limit", type=int, default=20, help="Max results per term/location/source combo")
    parser.add_argument("--google-key", default=os.environ.get("GOOGLE_PLACES_API_KEY"), help="Google Places API key (or set GOOGLE_PLACES_API_KEY env var)")
    parser.add_argument("--yelp-key", default=os.environ.get("YELP_API_KEY"), help="Yelp Fusion API key (or set YELP_API_KEY env var)")

    args = parser.parse_args()

    terms = [t.strip() for t in args.terms.split(",") if t.strip()]
    locations = [l.strip() for l in args.locations.split(",") if l.strip()]
    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]

    run(terms, locations, sources, args.google_key, args.yelp_key, args.limit, args.output)


if __name__ == "__main__":
    main()
```

### /src/app.py
```python
"""
Lead Scraper App
A simple browser based interface for the Google Places / Yelp lead scraper.

Setup:
  pip install streamlit pandas requests

Run:
  streamlit run app.py

This opens a local web app in your browser where you can type in search terms,
locations, pick your sources, and run the search. Results show in a table and
you can download them as CSV.
"""

import os
import io
import pandas as pd
import streamlit as st

from lead_scraper import fetch_google_places, fetch_yelp, dedup_key

st.set_page_config(page_title="Lead Scraper", page_icon="🔍", layout="wide")

st.title("Lead Scraper")
st.caption("Pull business leads from Google Places and Yelp into a clean list")

# Sidebar for API keys
with st.sidebar:
    st.header("API Keys")
    google_key = st.text_input(
        "Google Places API Key",
        value=os.environ.get("GOOGLE_PLACES_API_KEY", ""),
        type="password",
    )
    yelp_key = st.text_input(
        "Yelp API Key",
        value=os.environ.get("YELP_API_KEY", ""),
        type="password",
    )
    st.caption("Keys stay in this session only, they are not saved anywhere.")

# Main input fields
col1, col2 = st.columns(2)

with col1:
    terms_input = st.text_area(
        "Search terms (one per line, or comma separated)",
        value="marina\nboat dealer\nyacht club\ndock repair",
        height=140,
    )

with col2:
    locations_input = st.text_area(
        "Locations (one per line, or comma separated)",
        value="Fort Lauderdale FL\nMiami FL\nWest Palm Beach FL",
        height=140,
    )

col3, col4, col5 = st.columns(3)

with col3:
    use_google = st.checkbox("Search Google Places", value=True)
with col4:
    use_yelp = st.checkbox("Search Yelp", value=True)
with col5:
    limit = st.number_input("Max results per search", min_value=5, max_value=60, value=20, step=5)

run_button = st.button("Run Search", type="primary")

if "results_df" not in st.session_state:
    st.session_state.results_df = None


def parse_lines(text):
    items = []
    for chunk in text.replace(",", "\n").split("\n"):
        chunk = chunk.strip()
        if chunk:
            items.append(chunk)
    return items


if run_button:
    terms = parse_lines(terms_input)
    locations = parse_lines(locations_input)

    if not terms or not locations:
        st.error("Enter at least one search term and one location.")
    elif not use_google and not use_yelp:
        st.error("Pick at least one source.")
    else:
        all_rows = []
        total_searches = len(terms) * len(locations) * (int(use_google) + int(use_yelp))
        progress = st.progress(0, text="Starting...")
        done = 0

        for term in terms:
            for location in locations:
                if use_google:
                    done += 1
                    progress.progress(done / total_searches, text=f"Google: {term} in {location}")
                    if google_key:
                        try:
                            all_rows.extend(fetch_google_places(term, location, google_key, limit=limit))
                        except Exception as exc:
                            st.warning(f"Google search failed for '{term}' in '{location}': {exc}")
                    else:
                        st.warning("No Google API key entered, skipping Google search.")

                if use_yelp:
                    done += 1
                    progress.progress(done / total_searches, text=f"Yelp: {term} in {location}")
                    if yelp_key:
                        try:
                            all_rows.extend(fetch_yelp(term, location, yelp_key, limit=limit))
                        except Exception as exc:
                            st.warning(f"Yelp search failed for '{term}' in '{location}': {exc}")
                    else:
                        st.warning("No Yelp API key entered, skipping Yelp search.")

        progress.empty()

        seen = set()
        deduped = []
        for row in all_rows:
            key = dedup_key(row["name"], row["address"], row["phone"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)

        st.session_state.results_df = pd.DataFrame(deduped)
        st.success(f"Found {len(all_rows)} raw results, {len(deduped)} after removing duplicates.")

if st.session_state.results_df is not None and not st.session_state.results_df.empty:
    st.subheader("Results")
    st.dataframe(st.session_state.results_df, use_container_width=True)

    csv_buffer = io.StringIO()
    st.session_state.results_df.to_csv(csv_buffer, index=False)

    st.download_button(
        label="Download CSV",
        data=csv_buffer.getvalue(),
        file_name="leads.csv",
        mime="text/csv",
    )
elif st.session_state.results_df is not None:
    st.info("No results found for that search. Try different terms or locations.")
```

No other source files have been created in this project yet. There is no requirements.txt, no .env file, no tests directory, and no database schema file, all of these are listed as remaining work above.

## 7. Installation

### Install dependencies
```
pip install requests streamlit pandas
```
(No requirements.txt exists yet; creating one with these three pinned is a good first task on the new machine: `requests`, `streamlit`, `pandas`.)

### Configure environment variables
```
export GOOGLE_PLACES_API_KEY="your_google_places_key"
export YELP_API_KEY="your_yelp_fusion_key"
```
Google key: create a project in Google Cloud Console, enable the "Places API", generate an API key. Yelp key: register a free app at Yelp Fusion's developer portal, use the provided API key directly.

Both keys can alternatively be entered directly into the Streamlit app's sidebar at runtime (masked text inputs, not persisted anywhere), or passed as CLI flags (`--google-key`, `--yelp-key`) to the script version.

### Run the project
CLI version:
```
python3 lead_scraper.py --terms "marina,boat dealer,yacht club" --locations "Fort Lauderdale FL,Miami FL" --output leads.csv
```
App version (make sure `app.py` and `lead_scraper.py` are in the same directory):
```
streamlit run app.py
```
This opens a browser tab at `http://localhost:8501`.

### Build
No build step, this is a plain Python project with no compilation or bundling.

### Test
No formal test suite exists yet. Manual verification approach used so far: mock the `fetch_google_places` and `fetch_yelp` functions to return canned data, then run the `run()` function or exercise the dedup logic directly to confirm merge and dedup behavior, since real API calls require live keys and couldn't be exercised in the original build environment.

### Deploy
Not yet deployed anywhere. Currently intended to run locally via `streamlit run app.py` on whichever machine the user is on. See section 5, low priority, for shared/hosted deployment as a future step.

## 8. Future Improvements

**Faster**: cache API responses per term/location/source combination so repeat runs against the same search space don't re-hit rate-limited or metered APIs; parallelize the term x location loop with a thread pool since each API call is I/O bound and independent of the others.

**More scalable**: move from CSV/in-memory to SQLite (or Postgres once multi-user), add proper indexing on the dedup key so duplicate detection is a database constraint rather than an in-memory set rebuilt every run; separate the collection step from the enrichment step (website scraping for email/social) into distinct stages that can be run independently and resumed if interrupted.

**More reliable**: add retry with exponential backoff on transient API failures instead of a single try/except that gives up immediately; add a dead letter concept where records that fail enrichment are logged separately rather than silently dropped.

**Easier to maintain**: split `lead_scraper.py` into a package with separate modules per source (`sources/google_places.py`, `sources/yelp.py`, later `sources/website_enrichment.py`, `sources/sos_registry.py`), add type hints throughout, add a requirements.txt/pyproject.toml, add a small test suite using `responses` or `pytest-mock` to mock HTTP calls properly instead of ad hoc monkeypatching.

## 9. Context for the Next Claude

Paste this into a new chat to resume work:

"I'm continuing a lead generation scraper project. It pulls business leads (name, address, phone, website, rating, review count) from the Google Places API and Yelp Fusion API, official APIs only, no HTML scraping of any platform's web pages, that was a deliberate legal/ToS decision. There's a working CLI script (lead_scraper.py) and a working Streamlit browser app (app.py) that wraps it with editable search term and location fields, source checkboxes, a run button, a results table, and CSV download. Both are tested against mocked API responses only, real API keys haven't been exercised yet in this environment. The current output schema is: name, address, phone, website, rating, review_count, source, search_term, search_location. Dedup is done via normalized phone number as primary key, falling back to lowercased name+address when no phone exists.

The next priorities in order are: split address into city/state and capture business category (both APIs return this, just not captured yet); build a website enrichment step that fetches each business's own website and extracts a contact email and social media links (using requests + BeautifulSoup, respecting robots.txt); migrate storage from flat CSV to SQLite with the dedup key as a unique constraint; add email format and MX record validation and phone number normalization to E.164. After that: a Secretary of State business registry lookup (starting with Florida) to get owner/registered agent names, a caching layer to avoid re-querying the same term/location combos, and eventually HubSpot-native CSV field mapping or direct API push, since the end user's CRM is HubSpot.

Full source code for both files, complete architectural reasoning, and the full task backlog are in the attached PROJECT_HANDOFF.md, read that first before writing any code."

## 10. Developer Notes

**Assumptions made**: that "publicly available" data collection via official APIs is both the technically correct and legally safer path compared to page scraping, this was explicitly discussed and agreed upon rather than assumed silently. That the end user's CRM is HubSpot (confirmed from prior context in this project's broader business use, not from this specific conversation thread, worth re-confirming on the new machine if the next Claude session has no access to that context). That Florida is the right first state for Secretary of State registry work given the user's location, but this wasn'tt explicitly confirmed for this specific sub-feature.

**Important decisions and why**: API-only data collection (no page scraping) was the single most consequential decision in this project and should not be relitigated without a very good reason, it protects against ToS violations on Google, Yelp, and especially LinkedIn (which was explicitly excluded as a source). The two-call Google flow (Search then Details) is a known cost tradeoff, not an oversight, revisit only if API cost becomes a real constraint, in which case consider caching Details lookups separately from Search results since Details data changes less often.

**Caveats**: none of the code in this handoff has been run against live Google or Yelp API keys, all verification was done with mocked function returns because the build environment's network access didn't extend to googleapis.com or yelp.com. The first thing to do on the new machine is a real smoke test with actual API keys before building anything further on top.

**Lessons learned**: the original ask started from a very long, mostly templated "master blueprint" document that turned out to contain almost no unique real content once inspected closely, it was faster and more reliable to rebuild a real spec through direct questions (which sources, what output format) than to try to extract signal from that document. Worth keeping in mind if a similarly bloated spec document shows up again, verify it has real content before treating it as a source of truth.
