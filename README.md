# Business Lead Scraper

Pulls business leads from the **Google Places API** and **Yelp Fusion API** into a
clean, deduplicated list — as a CSV (CLI) or an interactive table (Streamlit app).

> Official, sanctioned APIs only. This project deliberately does **not** scrape
> Google Maps / Yelp / LinkedIn web pages — see `PROJECT_HANDOFF.md` for the
> reasoning behind that decision.

## Output fields

Each lead record contains:

| field | source |
|-------|--------|
| `name` | business name |
| `address` | full formatted address string |
| `city` | parsed city |
| `state` | parsed state (2-letter for Google) |
| `phone` | contact phone |
| `website` | business website |
| `category` | business category |
| `rating` | average rating |
| `review_count` | number of reviews |
| `source` | `google` or `yelp` |
| `search_term` | the term that surfaced this lead |
| `search_location` | the location that surfaced this lead |

Deduplication is keyed on the normalized phone number (digits only), falling
back to a lowercased `name` + `address` composite when no phone is present.

### Website enrichment (optional)

With enrichment enabled (`--enrich` on the CLI, or the checkbox in the app),
each lead's website is visited to add these columns (slotted after `website`):

| field | description |
|-------|-------------|
| `email` | public contact email (prefers `mailto:` links) |
| `instagram` / `facebook` / `linkedin` / `twitter` | first real profile link found |

Enrichment fetches the homepage and, if no email is found there, one linked
contact/about page — at most two page GETs (plus a `robots.txt` check) per site.
It **respects robots.txt** and sends a descriptive, non-spoofed User-Agent. Sites
sharing a domain are fetched only once per run. It's off by default because it
makes an extra request per lead.

## Setup

```bash
pip install -r requirements.txt
```

Provide API keys via environment variables (or enter them at runtime — see below):

```bash
export GOOGLE_PLACES_API_KEY="your_google_places_key"
export YELP_API_KEY="your_yelp_fusion_key"
```

- **Google key:** create a project in Google Cloud Console, enable the *Places API*, generate an API key.
- **Yelp key:** register a free app in the Yelp Fusion developer portal.

## Usage

### CLI

```bash
python3 lead_scraper.py \
  --terms "marina,boat dealer,yacht club" \
  --locations "Fort Lauderdale FL,Miami FL" \
  --output leads.csv
```

| flag | description |
|------|-------------|
| `--terms` | comma-separated search terms |
| `--locations` | comma-separated locations |
| `--sources` | `google,yelp` (default: both) |
| `--output` | output CSV path (default: `leads.csv`) |
| `--limit` | max results per term/location/source combo (default: 20) |
| `--enrich` | visit each lead's website for a contact email + social links (respects robots.txt) |
| `--google-key` / `--yelp-key` | override the env-var keys |

### Streamlit app

```bash
pip install -r requirements.txt
streamlit run app.py
```

`app.py` and `lead_scraper.py` must live in the same directory (the app imports
directly from the module). Keys can be entered in the sidebar (masked, session
only, never persisted). Opens at `http://localhost:8501`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

HTTP calls are mocked at the `requests.get` boundary, so the suite runs without
live API keys or network access.

## Roadmap

See `PROJECT_HANDOFF.md` §5 for the full backlog. Structured fields
(category/city/state) and website enrichment (contact email + social links) are
done. Next up: SQLite storage with the dedup key as a unique constraint, and
email/phone validation (email format + MX check, phone → E.164).
