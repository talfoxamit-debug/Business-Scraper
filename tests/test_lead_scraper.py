"""Unit tests for lead_scraper.

HTTP calls are mocked at the `requests.get` boundary so the suite runs without
live Google Places / Yelp API keys or network access.
"""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lead_scraper as ls


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def test_normalize_phone_strips_formatting():
    assert ls.normalize_phone("(954) 555-1234") == "9545551234"
    assert ls.normalize_phone("+1 954-555-1234") == "19545551234"
    assert ls.normalize_phone("") == ""
    assert ls.normalize_phone(None) == ""


def test_dedup_key_prefers_phone():
    # Same phone, different formatting/name -> same key.
    k1 = ls.dedup_key("Joe's Marina", "123 Dock St", "(954) 555-1234")
    k2 = ls.dedup_key("Joe Marina LLC", "123 Dock Street", "954.555.1234")
    assert k1 == k2 == "phone:9545551234"


def test_dedup_key_falls_back_to_name_address():
    k = ls.dedup_key("Joe's Marina", "123 Dock St", "")
    assert k == "name_addr:joe's marina|123 dock st"


def test_google_category_skips_generic_types():
    assert ls.google_category_from_types(
        ["point_of_interest", "establishment", "boat_dealer"]
    ) == "boat dealer"
    # All generic -> empty string.
    assert ls.google_category_from_types(["point_of_interest", "establishment"]) == ""
    assert ls.google_category_from_types([]) == ""
    assert ls.google_category_from_types(None) == ""


def test_parse_google_address_components():
    components = [
        {"long_name": "123", "short_name": "123", "types": ["street_number"]},
        {"long_name": "Fort Lauderdale", "short_name": "Fort Lauderdale", "types": ["locality", "political"]},
        {"long_name": "Florida", "short_name": "FL", "types": ["administrative_area_level_1", "political"]},
    ]
    city, state = ls.parse_google_address_components(components)
    assert city == "Fort Lauderdale"
    assert state == "FL"


def test_parse_google_address_components_falls_back_when_no_locality():
    components = [
        {"long_name": "Broward County", "short_name": "Broward County", "types": ["administrative_area_level_2", "political"]},
        {"long_name": "Florida", "short_name": "FL", "types": ["administrative_area_level_1", "political"]},
    ]
    city, state = ls.parse_google_address_components(components)
    assert city == "Broward County"
    assert state == "FL"


def test_parse_google_address_components_empty():
    assert ls.parse_google_address_components([]) == ("", "")
    assert ls.parse_google_address_components(None) == ("", "")


def test_yelp_category_join():
    cats = [{"alias": "marinas", "title": "Marinas"}, {"alias": "boating", "title": "Boating"}]
    assert ls.yelp_category_from_categories(cats) == "Marinas, Boating"
    assert ls.yelp_category_from_categories([]) == ""
    assert ls.yelp_category_from_categories(None) == ""


# --------------------------------------------------------------------------- #
# HTTP mocking helpers
# --------------------------------------------------------------------------- #

class FakeResponse:
    def __init__(self, json_data, status_code=200, text=""):
        self._json = json_data
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._json


def make_google_dispatch(textsearch_data, details_data):
    """Return a requests.get replacement that routes by URL."""
    def _dispatch(url, **kwargs):
        if url == ls.GOOGLE_PLACES_TEXTSEARCH_URL:
            return FakeResponse(textsearch_data)
        if url == ls.GOOGLE_PLACES_DETAILS_URL:
            return FakeResponse(details_data)
        raise AssertionError(f"unexpected URL {url}")
    return _dispatch


# --------------------------------------------------------------------------- #
# fetch_google_places
# --------------------------------------------------------------------------- #

def test_fetch_google_places_captures_structured_fields():
    textsearch = {
        "status": "OK",
        "results": [
            {
                "place_id": "abc",
                "name": "Bahia Mar Marina",
                "formatted_address": "801 Seabreeze Blvd, Fort Lauderdale, FL 33316, USA",
                "types": ["point_of_interest", "establishment", "marina"],
                "rating": 4.5,
                "user_ratings_total": 120,
            }
        ],
    }
    details = {
        "result": {
            "formatted_phone_number": "(954) 555-1234",
            "website": "https://bahiamar.example.com",
            "address_components": [
                {"long_name": "Fort Lauderdale", "short_name": "Fort Lauderdale", "types": ["locality", "political"]},
                {"long_name": "Florida", "short_name": "FL", "types": ["administrative_area_level_1", "political"]},
            ],
        }
    }
    with mock.patch.object(ls.requests, "get", make_google_dispatch(textsearch, details)):
        rows = ls.fetch_google_places("marina", "Fort Lauderdale FL", "fake-key", limit=20)

    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Bahia Mar Marina"
    assert row["city"] == "Fort Lauderdale"
    assert row["state"] == "FL"
    assert row["category"] == "marina"
    assert row["phone"] == "(954) 555-1234"
    assert row["website"] == "https://bahiamar.example.com"
    assert row["source"] == "google"


def test_fetch_google_places_respects_limit():
    textsearch = {
        "status": "OK",
        "results": [
            {"place_id": f"id{i}", "name": f"Marina {i}", "formatted_address": "", "types": ["marina"]}
            for i in range(5)
        ],
        "next_page_token": "should-not-be-used",
    }
    details = {"result": {"formatted_phone_number": "", "website": "", "address_components": []}}
    with mock.patch.object(ls.requests, "get", make_google_dispatch(textsearch, details)):
        rows = ls.fetch_google_places("marina", "Miami FL", "fake-key", limit=3)
    assert len(rows) == 3


# --------------------------------------------------------------------------- #
# fetch_yelp
# --------------------------------------------------------------------------- #

def test_fetch_yelp_captures_structured_fields():
    payload = {
        "total": 1,
        "businesses": [
            {
                "name": "Pier Sixty-Six Marina",
                "phone": "+19545551234",
                "url": "https://yelp.com/biz/pier-66",
                "rating": 4.0,
                "review_count": 55,
                "categories": [{"alias": "marinas", "title": "Marinas"}],
                "location": {
                    "city": "Fort Lauderdale",
                    "state": "FL",
                    "display_address": ["2301 SE 17th St", "Fort Lauderdale, FL 33316"],
                },
            }
        ],
    }
    with mock.patch.object(ls.requests, "get", lambda *a, **k: FakeResponse(payload)):
        rows = ls.fetch_yelp("marina", "Fort Lauderdale FL", "fake-key", limit=20)

    assert len(rows) == 1
    row = rows[0]
    assert row["city"] == "Fort Lauderdale"
    assert row["state"] == "FL"
    assert row["category"] == "Marinas"
    assert row["address"] == "2301 SE 17th St, Fort Lauderdale, FL 33316"
    assert row["source"] == "yelp"


def test_fetch_yelp_stops_on_non_200():
    with mock.patch.object(ls.requests, "get", lambda *a, **k: FakeResponse({}, status_code=429, text="rate limited")):
        rows = ls.fetch_yelp("marina", "Miami FL", "fake-key", limit=20)
    assert rows == []


# --------------------------------------------------------------------------- #
# Cross-source dedup (end-to-end through run())
# --------------------------------------------------------------------------- #

def test_run_dedupes_across_sources(tmp_path):
    google_rows = [{
        "name": "Bahia Mar Marina", "address": "801 Seabreeze Blvd", "city": "Fort Lauderdale",
        "state": "FL", "phone": "(954) 555-1234", "website": "", "category": "marina",
        "rating": 4.5, "review_count": 120, "source": "google",
        "search_term": "marina", "search_location": "Fort Lauderdale FL",
    }]
    yelp_rows = [{
        "name": "Bahia Mar", "address": "801 Seabreeze Boulevard", "city": "Fort Lauderdale",
        "state": "FL", "phone": "954.555.1234", "website": "", "category": "Marinas",
        "rating": 4.0, "review_count": 55, "source": "yelp",
        "search_term": "marina", "search_location": "Fort Lauderdale FL",
    }]
    output = tmp_path / "leads.csv"
    with mock.patch.object(ls, "fetch_google_places", return_value=google_rows), \
         mock.patch.object(ls, "fetch_yelp", return_value=yelp_rows):
        ls.run(
            terms=["marina"], locations=["Fort Lauderdale FL"], sources=["google", "yelp"],
            google_key="g", yelp_key="y", limit=20, output_path=str(output),
        )

    contents = output.read_text().strip().splitlines()
    header = contents[0]
    data_lines = contents[1:]
    # Same phone (differently formatted) -> collapsed to a single row.
    assert len(data_lines) == 1
    assert "city" in header and "state" in header and "category" in header


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
