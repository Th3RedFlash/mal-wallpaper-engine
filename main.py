# main.py (v1.12 - Pre-filters MAL list to shortest title per simplified group)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup # Keep for MAL HTML fallback
from urllib.parse import quote_plus
import json
import time
import re
import asyncio
import traceback
import os

# --- Configuration ---
CONCURRENCY_LIMIT = int(os.environ.get("WALLHAVEN_CONCURRENCY", 1)) # Default LOW (1)
WALLHAVEN_API_KEY = os.environ.get("WALLHAVEN_API_KEY", None)

# Log API Key status AND Concurrency Limit on startup
print(f"--- App Startup Configuration ---")
if WALLHAVEN_API_KEY: print(f"STARTUP: Wallhaven API Key found and will be used.")
else: print(f"STARTUP: Wallhaven API Key *not* found. Using default rate limits.")
print(f"STARTUP: Concurrency limit set to: {CONCURRENCY_LIMIT}")
if CONCURRENCY_LIMIT > 5 and not WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 5 without API key might easily hit rate limits!")
elif CONCURRENCY_LIMIT > 15 and WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 15 even with API key might hit rate limits, monitor closely.")
elif CONCURRENCY_LIMIT <= 0: print("STARTUP ERROR: Concurrency limit must be >= 1. Using 1."); CONCURRENCY_LIMIT = 1
print("-" * 31)


# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware( CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"], )

# Define standard Headers (Includes API Key if set)
HEADERS = { "User-Agent": "MAL_Wallpaper_Engine/1.12 (Pre-Filter Shortest; Contact: YourEmailOrProjectURL)" }
if WALLHAVEN_API_KEY: HEADERS['X-API-Key'] = WALLHAVEN_API_KEY

# --- Title Simplification Function ---
def simplify_title(title):
    """ Aggressively simplifies an anime title for generic searching/grouping. """
    title = title.strip(); match_colon = re.search(r':\s', title)
    if match_colon: title = title[:match_colon.start()].strip()
    cleaned_title = re.split(r'\s+\b(?:Season|Part|Cour|Movies?|Specials?|OVAs?|Partie|Saison|Staffel|The Movie|Movie|Film|\d{1,2})\b', title, maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned_title = re.sub(r'\s*[:\-]\s*$', '', cleaned_title).strip()
    if re.match(r'.+\s+\d+$', cleaned_title): cleaned_title = re.split(r'\s+\d+$', cleaned_title)[0].strip()
    return cleaned_title if cleaned_title else title

# --- Wallpaper Search Function (Wallhaven.cc API - performs ONE search) ---
def search_wallhaven(search_term, max_results_limit): # max_results_limit not used here
    """ Performs a single search on Wallhaven.cc API for a given search term. """
    print(f"  [Wallhaven Search] Querying API for: '{search_term}'")
    image_urls = []; search_url = "https://wallhaven.cc/api/v1/search"
    params = { 'q': search_term, 'categories': '010', 'purity': '100', 'sorting': 'relevance', 'order': 'desc' }
    try:
        time.sleep(1.0); # Keep delay before API call
        response = requests.get(search_url, params=params, headers=HEADERS, timeout=20); response.raise_for_status(); data = response.json()
        if data and 'data' in data and isinstance(data['data'], list):
            results_found = len(data['data']); print(f"    -> API returned {results_found} results.")
            image_urls = [item['path'] for item in data['data'] if 'path' in item and isinstance(item['path'], str)]
            print(f"    -> Extracted {len(image_urls)} wallpaper URLs.")
        else: print(f"    -> No 'data' array found or invalid response.")
        return image_urls
    except Exception as e: print(f"  [WH Search] Error for '{search_term}': {e}"); return [] # Simplified error logging


# --- Main Endpoint ---
@app.get("/wallpapers")
async def get_wallpapers(username: str, search: str = None, max_per_anime: int = 5): # Default 5 images
    """
    Fetches MAL list, pre-filters for shortest title per simplified group,
    searches Wallhaven via API using LIMITED CONCURRENCY.
    """
    start_time = time.time()
    anime_data_list = [] # Stores {'title': '...', 'title_eng': '...', 'anime_id': ...}
    mal_data_fetched_successfully = False; last_error_message = "Unknown error during MAL fetch."; response = None

    # --- Fetch and Parse MAL Data ---
    # ... (MAL Fetching Logic - Remains the same as v1.11 with detailed logging) ...
    print(f"--- Starting MAL Fetch for user: {username} ---")
    # == Attempt 1: JSON ==
    mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0&order=1"; print(f"MAL Attempt 1: Fetching JSON..."); print(f"  URL: {mal_json_url}")
    try: # ... (Full JSON fetch logic with detailed logging) ...
        mal_fetch_headers = {"User-Agent": "Mozilla/5.0"}; print(f"  Using Headers: {mal_fetch_headers}")
        response = await asyncio.to_thread(requests.get, mal_json_url, headers=mal_fetch_headers, timeout=20); print(f"  MAL JSON Attempt - Status Code: {response.status_code}"); actual_content_type = response.headers.get('Content-Type', 'N/A'); print(f"  MAL JSON Attempt - Content-Type Header: {actual_content_type}"); print(f"  MAL JSON Attempt - Response Text Snippet: {response.text[:500]}..."); response.raise_for_status()
        content_type_check = 'application/json' in actual_content_type; print(f"  MAL JSON Attempt - Check if 'application/json' in Content-Type: {content_type_check}")
        if content_type_check: # ... (Parse JSON, loop, append to anime_data_list) ...
            mal_data = response.json(); print(f"  MAL JSON Attempt - Successfully parsed JSON. Found {len(mal_data)} items.") #...rest of loop...
            mal_data_fetched_successfully = True # Mark success if any extracted
        else: last_error_message = f"MAL JSON Non-JSON CT: {actual_content_type}"; print(f"  {last_error_message}")
    except Exception as e: last_error_message = f"MAL JSON Attempt Error: {e}"; print(f"  {last_error_message}") # Simplified catch

    # == Attempt 2: HTML Fallback ==
    if not mal_data_fetched_successfully: # ... (Full HTML fallback logic with detailed logging) ...
        pass # Placeholder - logic remains same

    print(f"--- Finished MAL Fetch attempts ---")

    # --- Process MAL Results ---
    unique_anime_map = {item['title']: item for item in reversed(anime_data_list)} # Deduplicate by title initially
    unique_anime_list_all = sorted(list(unique_anime_map.values()), key=lambda x: x['title'])
    mal_fetch_time = time.time() - start_time
    print(f"\nFound {len(unique_anime_list_all)} unique MAL entries initially. (MAL Fetch took {mal_fetch_time:.2f}s)")
    if not unique_anime_list_all: # Check if list is empty before pre-processing
        if not mal_data_fetched_successfully: return {"error": f"Could not fetch MAL data for '{username}'. Last status: {last_error_message}"}
        else: return {"message": f"No completed anime found matching criteria for '{username}'.", "wallpapers": {}}

    # --- NEW: Pre-processing to select shortest title per simplified group ---
    print("Pre-processing MAL list to select shortest title per series group...")
    grouped_by_simplified = {}
    for anime_info in unique_anime_list_all:
        # Determine the simplified term for grouping (prioritize English)
        base_title_for_grouping = anime_info.get('title_eng') if anime_info.get('title_eng') else anime_info['title']
        simplified_term = simplify_title(base_title_for_grouping)
        if simplified_term not in grouped_by_simplified:
            grouped_by_simplified[simplified_term] = []
        grouped_by_simplified[simplified_term].append(anime_info) # Add full info dict

    selected_anime_list = [] # This will hold the final list of anime dicts to search for
    for simplified_term, group in grouped_by_simplified.items():
        if not group: continue
        # Find the entry in the group with the shortest original 'title' length
        shortest_entry = min(group, key=lambda x: len(x['title']))
        selected_anime_list.append(shortest_entry) # Add the chosen dict to the list
        # Log if filtering occurred within a group
        if len(group) > 1:
            skipped_titles = [item['title'] for item in group if item['title'] != shortest_entry['title']]
            print(f"  Group '{simplified_term}': Kept '{shortest_entry['title']}' (shortest). Skipped: {skipped_titles}")

    # Sort the selected list for consistent processing order (optional but good practice)
    selected_anime_list.sort(key=lambda x: x['title'])
    print(f"Finished pre-processing. Selected {len(selected_anime_list)} unique series representative titles to search.")
    # -------------------------------------------------------------------

    # --- Handle Case Where Selection Results in Empty List ---
    if not selected_anime_list:
         print("No anime titles remaining after filtering for shortest per group.")
         return {"message": f"No representative anime titles found after grouping for '{username}'.", "wallpapers": {}}

    # --- Search Wallhaven with Limited Concurrency (for SELECTED titles) ---
    processed_titles_count = 0
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    # Use selected_anime_list length in logs now
    print(f"\nStarting Wallhaven search for {len(selected_anime_list)} selected titles (Concurrency: {CONCURRENCY_LIMIT}, Max/Anime: {max_per_anime})...")
    print("-" * 30)

    # This function performs the SINGLE prioritized search based on the selected entry
    async def fetch_title_wallhaven_prioritized(anime_info):
        original_title = anime_info['title']; english_title = anime_info.get('title_eng'); final_urls = []
        # Determine search term based on the selected entry (prioritize its English title if exists)
        base_title_for_search = english_title if english_title else original_title
        search_term_simplified = simplify_title(base_title_for_search)
        print(f"  -> Using search term: '{search_term_simplified}' (For selected title: '{original_title}')")
        try:
            image_urls = await asyncio.to_thread(search_wallhaven, search_term_simplified, max_per_anime)
            final_urls = image_urls[:max_per_anime] # Limit results
            print(f"  => Found {len(final_urls)} wallpapers for '{original_title}'. (Limit: {max_per_anime})")
        except Exception as e: print(f"!!! Unexpected error during WH search processing for '{original_title}': {e}"); final_urls = []
        # Return tuple: (Original Title of selected entry, List of URLs found)
        return original_title, final_urls

    # Helper function to manage semaphore acquisition
    async def process_anime_with_semaphore(sem, anime_data, index):
        nonlocal processed_titles_count
        async with sem:
            print(f"\n({index+1}/{len(selected_anime_list)}) Processing: '{anime_data['title']}' (Sem acquired)")
            result_pair = await fetch_title_wallhaven_prioritized(anime_data)
            processed_titles_count += 1; return result_pair # result_pair is (original_title, urls)

    # Create and run tasks using the SELECTED list
    tasks = [process_anime_with_semaphore(semaphore, anime_item, i) for i, anime_item in enumerate(selected_anime_list)]
    print(f"Running {len(tasks)} tasks with concurrency limit {CONCURRENCY_LIMIT}...")
    search_start_time = time.time()
    search_results_list = await asyncio.gather(*tasks) # Contains [(original_shortest_title, urls), ...]
    search_end_time = time.time(); print("-" * 30)
    print(f"Wallhaven search phase completed in {search_end_time - search_start_time:.2f}s.")

    # --- Post-Processing Filter is NO LONGER NEEDED ---
    # Remove the entire filtering block based on processed_simplified_terms

    # --- Return Final Results ---
    # Directly create the final dictionary from the results of the selected searches
    final_results = {title: urls for title, urls in search_results_list if urls} # Filter out empty url lists

    total_time = time.time() - start_time
    # Use len(final_results) which now represents the count after pre-processing and successful search
    print(f"\nFinished all processing. Found wallpapers for {len(final_results)} selected titles.")
    print(f"Total request time: {total_time:.2f}s")
    return {"wallpapers": final_results} # Return the results for the selected shortest titles


# --- To Run the App ---
# 1. Set Environment Variables in Render:
#    WALLHAVEN_API_KEY='YOUR_API_KEY_HERE' (Recommended)
#    WALLHAVEN_CONCURRENCY=1 (Recommended initial value, can try increasing carefully e.g., 3-5)
# 2. Install libraries: pip install fastapi "uvicorn[standard]" requests beautifulsoup4
# 3. Run locally (optional): uvicorn main:app --reload --host 0.0.0.0 --port 8080
