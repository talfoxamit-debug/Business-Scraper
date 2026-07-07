#!/usr/bin/env python3
"""
Website enrichment for the lead scraper.

Given a business website URL (already collected from Google / Yelp), fetch the
site and extract a public contact email address and social media links
(Instagram, Facebook, LinkedIn, Twitter/X).

Design notes / deliberate choices:
- Uses the official `requests` library plus BeautifulSoup with Python's built-in
  `html.parser` (no lxml dependency).
- Respects robots.txt: before fetching a page we check the site's robots.txt
  with a urllib RobotFileParser fed from a `requests`-fetched body. If robots.txt
  disallows the path for our agent, we skip that page.
- Sends a descriptive, honest User-Agent that identifies this as a business
  outreach contact-discovery tool rather than spoofing a browser.
- Only fetches the homepage and, if no email is found there, one likely
  "contact" page linked from it. That caps network work to at most two GETs
  (plus one robots.txt fetch) per site.
"""

import re
import sys
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - surfaced clearly at runtime
    BeautifulSoup = None


# Honest, non-spoofed identification. If you deploy this, point the URL at a
# page describing the crawler and how to contact you.
USER_AGENT = (
    "BusinessLeadScraper/1.0 (+https://example.com/bot-info; "
    "business outreach contact discovery)"
)

DEFAULT_TIMEOUT = 10

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Domains / suffixes that are almost never a real contact address but do match
# the email regex (asset filenames like "logo@2x.png", tracking/CDN domains).
_EMAIL_JUNK_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico",
    ".css", ".js", ".json", ".webmanifest",
)
_EMAIL_JUNK_DOMAINS = {
    "example.com", "example.org", "email.com", "domain.com",
    "sentry.io", "wixpress.com", "sentry-next.wixpress.com",
    "godaddy.com", "squarespace.com",
}

SOCIAL_HOSTS = {
    "instagram": ("instagram.com",),
    "facebook": ("facebook.com", "fb.com"),
    "linkedin": ("linkedin.com",),
    "twitter": ("twitter.com", "x.com"),
}

# Link path fragments that indicate a share/widget/tracking link rather than a
# real profile, so we don't record those as the business's social page.
_SOCIAL_SKIP_FRAGMENTS = (
    "/sharer", "/share", "/plugins", "/tr?", "/intent", "/dialog",
    "/home?", "/hashtag/",
)

CONTACT_LINK_HINTS = ("contact", "about", "reach-us", "reach_us", "get-in-touch")


def _looks_like_junk_email(email):
    lower = email.lower()
    if "@2x" in lower or "@3x" in lower:
        return True
    domain = lower.split("@", 1)[1]
    if domain in _EMAIL_JUNK_DOMAINS:
        return True
    if any(domain.endswith(suffix) for suffix in _EMAIL_JUNK_SUFFIXES):
        return True
    return False


def extract_emails(soup, html_text):
    """Return a de-duplicated, ordered list of plausible contact emails.

    `mailto:` links are trusted most, so they come first; a regex sweep over the
    page text backfills the rest. Junk (asset filenames, tracking domains) is
    filtered out.
    """
    emails = []
    seen = set()

    def _add(candidate):
        candidate = candidate.strip().strip(".,;:")
        if not candidate:
            return
        low = candidate.lower()
        if low in seen or _looks_like_junk_email(candidate):
            return
        seen.add(low)
        emails.append(candidate)

    if soup is not None:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().startswith("mailto:"):
                addr = href[len("mailto:"):].split("?", 1)[0]
                for part in addr.split(","):
                    _add(part)

    for match in EMAIL_RE.findall(html_text or ""):
        _add(match)

    return emails


def extract_social_links(soup, base_url=""):
    """Return {instagram, facebook, linkedin, twitter} -> first real profile URL."""
    found = {key: "" for key in SOCIAL_HOSTS}
    if soup is None:
        return found

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        host = urlparse(absolute).netloc.lower()
        if host.startswith("www."):
            host = host[4:]

        lower_url = absolute.lower()
        if any(frag in lower_url for frag in _SOCIAL_SKIP_FRAGMENTS):
            continue

        for platform, hosts in SOCIAL_HOSTS.items():
            if found[platform]:
                continue
            if any(host == h or host.endswith("." + h) for h in hosts):
                found[platform] = absolute
                break

    return found


def _fetch(url, timeout):
    """GET a URL with our identifying UA. Returns response or None on failure."""
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        print(f"  [enrich] fetch failed for {url}: {exc}", file=sys.stderr)
        return None
    if resp.status_code != 200:
        print(f"  [enrich] {url} returned status {resp.status_code}", file=sys.stderr)
        return None
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype.lower() and ctype:
        return None
    return resp


def _robots_allowed(url, timeout):
    """Check robots.txt for our User-Agent. Missing/unreadable robots.txt = allowed."""
    parts = urlparse(url)
    if not parts.scheme or not parts.netloc:
        return False
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        resp = requests.get(
            robots_url, headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
    except requests.RequestException:
        return True  # can't fetch robots.txt -> default to allowed
    if resp.status_code != 200 or not resp.text:
        return True
    parser = RobotFileParser()
    parser.parse(resp.text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


def _find_contact_url(soup, base_url):
    """Find a likely 'contact'/'about' page link on the homepage, if any."""
    if soup is None:
        return None
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        text = (a.get_text() or "").lower()
        target = (href + " " + text).lower()
        if any(hint in target for hint in CONTACT_LINK_HINTS):
            absolute = urljoin(base_url, href)
            # Stay on the same site.
            if urlparse(absolute).netloc == urlparse(base_url).netloc:
                return absolute
    return None


def enrich_website(url, timeout=DEFAULT_TIMEOUT, follow_contact_page=True):
    """Fetch a business website and extract contact email + social links.

    Returns a dict with keys: email, instagram, facebook, linkedin, twitter.
    Missing values are empty strings. Never raises for network/parse issues —
    failures degrade to empty fields (logged to stderr).
    """
    empty = {"email": "", "instagram": "", "facebook": "", "linkedin": "", "twitter": ""}
    if not url:
        return dict(empty)
    if BeautifulSoup is None:
        print("  [enrich] BeautifulSoup not installed; skipping enrichment", file=sys.stderr)
        return dict(empty)

    # Normalize a bare domain into an https URL.
    if not urlparse(url).scheme:
        url = "https://" + url

    if not _robots_allowed(url, timeout):
        print(f"  [enrich] robots.txt disallows {url}; skipping", file=sys.stderr)
        return dict(empty)

    resp = _fetch(url, timeout)
    if resp is None:
        return dict(empty)

    html_text = resp.text
    soup = BeautifulSoup(html_text, "html.parser")
    base_url = resp.url  # honor redirects for relative-link resolution

    emails = extract_emails(soup, html_text)
    social = extract_social_links(soup, base_url)

    # If the homepage yielded no email, try one linked contact/about page.
    if follow_contact_page and not emails:
        contact_url = _find_contact_url(soup, base_url)
        if contact_url and contact_url != base_url and _robots_allowed(contact_url, timeout):
            contact_resp = _fetch(contact_url, timeout)
            if contact_resp is not None:
                contact_soup = BeautifulSoup(contact_resp.text, "html.parser")
                emails = extract_emails(contact_soup, contact_resp.text)
                # Backfill any social links the homepage missed.
                contact_social = extract_social_links(contact_soup, contact_resp.url)
                for key, value in contact_social.items():
                    if not social[key] and value:
                        social[key] = value

    result = dict(empty)
    result["email"] = emails[0] if emails else ""
    result.update(social)
    return result
