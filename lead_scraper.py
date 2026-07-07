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
    --enrich      Visit each lead's website to extract a contact email and social media links (respects robots.txt)
"""

import argparse
import csv
import os
import sys
import time
import requests

from enrichment import enrich_website


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


# Google Place "types" are a mix of a few useful business categories and a lot
# of generic scaffolding tags. Drop the generic ones so we surface something
# meaningful (e.g. "restaurant") rather than "point of interest".
GOOGLE_GENERIC_TYPES = {
    "point_of_interest",
    "establishment",
    "premise",
    "subpremise",
    "geocode",
    "political",
}


def google_category_from_types(types):
    """Pick a human-readable primary category from a Google 'types' list."""
    for t in types or []:
        if t not in GOOGLE_GENERIC_TYPES:
            return t.replace("_", " ")
    return ""


def parse_google_address_components(components):
    """Extract (city, state) from a Google Place Details address_components list.

    City comes from the 'locality' component; state from the 2-letter
    short_name of 'administrative_area_level_1'. Falls back to related
    component types when the primary ones are absent (e.g. unincorporated
    areas that have no 'locality').
    """
    city = ""
    state = ""
    for comp in components or []:
        comp_types = comp.get("types", [])
        if not city and "locality" in comp_types:
            city = comp.get("long_name", "")
        if not state and "administrative_area_level_1" in comp_types:
            state = comp.get("short_name", "")

    if not city:
        for comp in components or []:
            comp_types = comp.get("types", [])
            if "postal_town" in comp_types or "administrative_area_level_2" in comp_types:
                city = comp.get("long_name", "")
                break
    return city, state


def yelp_category_from_categories(categories):
    """Join Yelp category titles (e.g. [{'title': 'Marinas'}]) into a string."""
    titles = [c.get("title", "") for c in categories or [] if c.get("title")]
    return ", ".join(titles)


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
                "city": details.get("city", ""),
                "state": details.get("state", ""),
                "phone": details.get("phone", ""),
                "website": details.get("website", ""),
                "category": google_category_from_types(place.get("types")),
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
        "fields": "formatted_phone_number,website,address_component",
        "key": api_key,
    }
    try:
        resp = requests.get(GOOGLE_PLACES_DETAILS_URL, params=params, timeout=15)
        data = resp.json()
        result = data.get("result", {})
        city, state = parse_google_address_components(result.get("address_components"))
        return {
            "phone": result.get("formatted_phone_number", ""),
            "website": result.get("website", ""),
            "city": city,
            "state": state,
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
                "city": location_obj.get("city", ""),
                "state": location_obj.get("state", ""),
                "phone": biz.get("phone", ""),
                "website": biz.get("url", ""),
                "category": yelp_category_from_categories(biz.get("categories")),
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


ENRICHMENT_FIELDS = ["email", "instagram", "facebook", "linkedin", "twitter"]


def enrich_rows(rows, cache=None):
    """Populate contact email + social links for each row from its website.

    Rows are enriched in place. A per-run cache keyed on the website URL avoids
    re-fetching the same site when several leads share a domain.
    """
    if cache is None:
        cache = {}
    for row in rows:
        website = row.get("website", "")
        for field in ENRICHMENT_FIELDS:
            row.setdefault(field, "")
        if not website:
            continue
        if website in cache:
            enriched = cache[website]
        else:
            enriched = enrich_website(website)
            cache[website] = enriched
        for field in ENRICHMENT_FIELDS:
            row[field] = enriched.get(field, "")
    return rows


def run(terms, locations, sources, google_key, yelp_key, limit, output_path, enrich=False):
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

    if enrich:
        print(f"[enrich] fetching websites for {len(deduped_rows)} leads...")
        enrich_rows(deduped_rows)

    fieldnames = ["name", "address", "city", "state", "phone", "website", "category", "rating", "review_count", "source", "search_term", "search_location"]
    if enrich:
        # Slot the enrichment columns next to website, before the metadata tail.
        website_idx = fieldnames.index("website") + 1
        fieldnames = fieldnames[:website_idx] + ENRICHMENT_FIELDS + fieldnames[website_idx:]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
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
    parser.add_argument("--enrich", action="store_true", help="Visit each lead's website to extract a contact email and social media links (respects robots.txt)")
    parser.add_argument("--google-key", default=os.environ.get("GOOGLE_PLACES_API_KEY"), help="Google Places API key (or set GOOGLE_PLACES_API_KEY env var)")
    parser.add_argument("--yelp-key", default=os.environ.get("YELP_API_KEY"), help="Yelp Fusion API key (or set YELP_API_KEY env var)")

    args = parser.parse_args()

    terms = [t.strip() for t in args.terms.split(",") if t.strip()]
    locations = [l.strip() for l in args.locations.split(",") if l.strip()]
    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]

    run(terms, locations, sources, args.google_key, args.yelp_key, args.limit, args.output, enrich=args.enrich)


if __name__ == "__main__":
    main()
