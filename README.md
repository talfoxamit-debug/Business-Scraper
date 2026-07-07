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

See `PROJECT_HANDOFF.md` §5 for the full backlog. Near-term priorities after the
current structured-fields work: website enrichment (contact email + social
links), SQLite storage with the dedup key as a unique constraint, and
email/phone validation.
