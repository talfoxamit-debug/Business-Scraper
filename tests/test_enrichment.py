"""Unit tests for the website enrichment module.

All network access is mocked at the `requests.get` boundary; robots.txt,
homepage, and contact-page fetches are routed by URL.
"""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import enrichment as en


class FakeResponse:
    def __init__(self, text="", status_code=200, url="", content_type="text/html"):
        self.text = text
        self.status_code = status_code
        self.url = url or ""
        self.headers = {"Content-Type": content_type}


def router(routes, robots="", robots_status=200):
    """Build a requests.get replacement that dispatches by URL.

    `routes` maps a URL -> FakeResponse. Any */robots.txt request returns the
    given robots body (200 by default).
    """
    def _get(url, headers=None, timeout=None, allow_redirects=True):
        if url.endswith("/robots.txt"):
            return FakeResponse(text=robots, status_code=robots_status, url=url)
        if url in routes:
            resp = routes[url]
            if not resp.url:
                resp.url = url
            return resp
        return FakeResponse(status_code=404, url=url)
    return _get


# --------------------------------------------------------------------------- #
# Pure parsing helpers
# --------------------------------------------------------------------------- #

def test_extract_emails_prefers_mailto_and_filters_junk():
    from bs4 import BeautifulSoup
    html = """
        <a href="mailto:info@marina.com">Email us</a>
        <img src="logo@2x.png">
        contact us at sales@marina.com or noise@sentry.io
    """
    soup = BeautifulSoup(html, "html.parser")
    emails = en.extract_emails(soup, html)
    assert emails[0] == "info@marina.com"          # mailto first
    assert "sales@marina.com" in emails
    assert not any("2x.png" in e for e in emails)  # asset filename filtered
    assert not any("sentry.io" in e for e in emails)


def test_looks_like_junk_email():
    assert en._looks_like_junk_email("logo@2x.png") is True
    assert en._looks_like_junk_email("x@example.com") is True
    assert en._looks_like_junk_email("owner@realbusiness.com") is False


def test_extract_social_links():
    from bs4 import BeautifulSoup
    html = """
        <a href="https://www.instagram.com/marina">IG</a>
        <a href="https://facebook.com/marinapage">FB</a>
        <a href="https://facebook.com/sharer/sharer.php?u=x">share</a>
        <a href="https://www.linkedin.com/company/marina">LI</a>
        <a href="https://x.com/marina">X</a>
    """
    soup = BeautifulSoup(html, "html.parser")
    social = en.extract_social_links(soup, "https://marina.com")
    assert social["instagram"] == "https://www.instagram.com/marina"
    assert social["facebook"] == "https://facebook.com/marinapage"   # not the sharer link
    assert social["linkedin"] == "https://www.linkedin.com/company/marina"
    assert social["twitter"] == "https://x.com/marina"


# --------------------------------------------------------------------------- #
# enrich_website end-to-end (mocked HTTP)
# --------------------------------------------------------------------------- #

def test_enrich_website_extracts_from_homepage():
    homepage = """
        <html><body>
          <a href="mailto:hello@marina.com">Contact</a>
          <a href="https://instagram.com/marina">Instagram</a>
        </body></html>
    """
    routes = {"https://marina.com": FakeResponse(text=homepage, url="https://marina.com")}
    with mock.patch.object(en.requests, "get", router(routes)):
        result = en.enrich_website("https://marina.com")
    assert result["email"] == "hello@marina.com"
    assert result["instagram"] == "https://instagram.com/marina"
    assert result["facebook"] == ""


def test_enrich_website_follows_contact_page_for_email():
    homepage = """
        <html><body>
          <a href="/contact">Contact us</a>
          <a href="https://facebook.com/marina">FB</a>
        </body></html>
    """
    contact = '<html><body><a href="mailto:sales@marina.com">Reach us</a></body></html>'
    routes = {
        "https://marina.com": FakeResponse(text=homepage, url="https://marina.com"),
        "https://marina.com/contact": FakeResponse(text=contact, url="https://marina.com/contact"),
    }
    with mock.patch.object(en.requests, "get", router(routes)):
        result = en.enrich_website("https://marina.com")
    assert result["email"] == "sales@marina.com"     # pulled from the contact page
    assert result["facebook"] == "https://facebook.com/marina"  # kept from homepage


def test_enrich_website_respects_robots_disallow():
    homepage = '<a href="mailto:hello@marina.com">x</a>'
    routes = {"https://marina.com": FakeResponse(text=homepage, url="https://marina.com")}
    robots = "User-agent: *\nDisallow: /"
    with mock.patch.object(en.requests, "get", router(routes, robots=robots)):
        result = en.enrich_website("https://marina.com")
    # Disallowed -> nothing fetched, all fields empty.
    assert result == {"email": "", "instagram": "", "facebook": "", "linkedin": "", "twitter": ""}


def test_enrich_website_handles_empty_url():
    result = en.enrich_website("")
    assert result["email"] == ""
    assert set(result.keys()) == {"email", "instagram", "facebook", "linkedin", "twitter"}


def test_enrich_website_normalizes_bare_domain():
    homepage = '<a href="mailto:hi@marina.com">x</a>'
    routes = {"https://marina.com": FakeResponse(text=homepage, url="https://marina.com")}
    with mock.patch.object(en.requests, "get", router(routes)):
        result = en.enrich_website("marina.com")   # no scheme
    assert result["email"] == "hi@marina.com"


# --------------------------------------------------------------------------- #
# enrich_rows integration (from lead_scraper)
# --------------------------------------------------------------------------- #

def test_enrich_rows_uses_cache_for_shared_domain():
    import lead_scraper as ls
    rows = [
        {"name": "A", "website": "https://shared.com"},
        {"name": "B", "website": "https://shared.com"},
        {"name": "C", "website": ""},
    ]
    call_count = {"n": 0}

    def fake_enrich(url, *a, **k):
        call_count["n"] += 1
        return {"email": "x@shared.com", "instagram": "", "facebook": "", "linkedin": "", "twitter": ""}

    with mock.patch.object(ls, "enrich_website", fake_enrich):
        ls.enrich_rows(rows)

    # Same domain fetched once; empty-website row skipped entirely.
    assert call_count["n"] == 1
    assert rows[0]["email"] == "x@shared.com"
    assert rows[1]["email"] == "x@shared.com"
    assert rows[2]["email"] == ""


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
