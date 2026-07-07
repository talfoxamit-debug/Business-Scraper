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

from lead_scraper import fetch_google_places, fetch_yelp, dedup_key, enrich_rows

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

use_enrich = st.checkbox(
    "Enrich websites (fetch contact email + social links)",
    value=False,
    help="After searching, visit each lead's website to pull a public contact "
         "email and Instagram/Facebook/LinkedIn/Twitter links. Respects "
         "robots.txt. Slower, since it makes an extra request per website.",
)

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

        if use_enrich and deduped:
            enrich_progress = st.progress(0, text="Enriching websites...")
            cache = {}
            for i, row in enumerate(deduped, start=1):
                enrich_rows([row], cache=cache)
                enrich_progress.progress(i / len(deduped), text=f"Enriching websites ({i}/{len(deduped)})")
            enrich_progress.empty()

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
