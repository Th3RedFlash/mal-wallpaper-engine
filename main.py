# main.py (Wallhaven API: Single Prioritized Search + Backend Duplicate Filtering + Concurrency)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import json
import time
import re
import asyncio
import traceback
import os

# --- Configuration ---
CONCURRENCY_LIMIT = int(os.environ.get("WALLHAVEN_CONCURRENCY", 3)) # Default LOW now (e.g., 3 or 4) - ADJUST IN RENDER
WALLHAVEN_API_KEY = os.environ.get("WALLHAVEN_API_KEY", None)

# Log API Key status and Concurrency Limit on startup
if WALLHAVEN_API_KEY:
    print(f"Wallhaven API Key found and will be used. Concurrency Limit: {CONCURRENCY_LIMIT}")
else:
    print(f"Wallhaven API Key *not* found. Using default rate limits. Concurrency Limit: {CONCURRENCY_LIMIT}")
if CONCURRENCY_LIMIT > 5 and not WALLHAVEN_API_KEY:
    print("WARNING: Concurrency limit > 5 without an API key might easily hit rate limits!")

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# Define standard Headers (Includes API Key if set)
HEADERS = { "User-Agent": "MAL_Wallpaper_Engine/1.5 (Filtered Single Search; Contact: YourEmailOrProjectURL)" }
if WALLHAVEN_API_KEY: HEADERS['X-API-Key'] = WALLHAVEN_API_KEY

# --- Title Simplification Function ---
# ... (simplify_title function remains the same - aggressively simplifies) ...
def simplify_title(title):
    title = title.strip(); match_colon = re.search(r':\s', title)
    if match_colon: title = title[:match_colon.start()].strip() # Keep this simplification part
    cleaned_title = re.split(r'\s+\b(?:Season|Part|Cour|Movies?|Specials?|OVAs?|Partie|Saison|Staffel|The Movie|Movie|Film|\d{1,2})\b', title, maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned_title = re.sub(r'\s*[:\-]\s*$', '', cleaned_title).strip()
    if re.match(r'.+\s+\d+$', cleaned_title): cleaned_title = re.split(r'\s+\d+$', cleaned_title)[0].strip()
    return cleaned_title if cleaned_title else title

# --- Wallpaper Search Function (Wallhaven.cc API - performs ONE search) ---
# ... (search_wallhaven function remains the same) ...
def search_wallhaven(search_term, max_results_limit): # max_results_limit not used here
    print(f"  [Wallhaven Search] Querying API for: '{search_term}'")
    image_urls = []; search_url = "https://wallhaven.cc/api/v1/search"
    params = { 'q': search_term, 'categories': '010', 'purity': '100', 'sorting': 'relevance', 'order': 'desc' }
    try:
        time.sleep(1.0) # Keep delay
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
async def get_wallpapers(username: str, search: str = None, max_per_anime: int = 3):
    start_time = time.time()
    anime_data_list = [] # Stores {'title': '...', 'title_eng': '...'}
    mal_data_fetched_successfully = False; last_error_message = "Unknown"; response = None

    # --- Fetch and Parse MAL Data (Attempt 1: JSON, Attempt 2: HTML - same logic) ---
    # ... (Full MAL fetching code - populates anime_data_list) ...
    print(f"Fetching MAL data for {username}...")
    # ... (Try JSON fetch block) ...
    # ... (Try HTML fetch block if needed) ...

    # --- Process MAL Results ---
    unique_anime_map = {item['title']: item for item in reversed(anime_data_list)}
    unique_anime_list = sorted(list(unique_anime_map.values()), key=lambda x: x['title'])
    mal_fetch_time = time.time() - start_time
    print(f"\nFound {len(unique_anime_list)} unique titles. (MAL Fetch took {mal_fetch_time:.2f}s)")
    # ... (Handle cases where no titles are found) ...
    if not unique_anime_list: return {"message": f"No completed anime found matching criteria.", "wallpapers": {}}


    # --- Search Wallhaven with Limited Concurrency (Single Prioritized Search) ---
    processed_titles_count = 0
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    print(f"\nStarting Wallhaven search for {len(unique_anime_list)} titles (Concurrency: {CONCURRENCY_LIMIT}, Single Search Strategy)...")
    print("-" * 30)

    # This function performs the SINGLE prioritized search logic
    async def fetch_title_wallhaven_prioritized(anime_info):
        """ Selects best title (ENG > Main), simplifies it, and searches Wallhaven once. """
        original_title = anime_info['title']
        english_title = anime_info['title_eng']
        final_urls = []

        # Determine the single best search term (Prioritize English)
        base_title_for_generic = english_title if english_title else original_title
        search_term_simplified = simplify_title(base_title_for_generic)

        print(f"  -> Using search term: '{search_term_simplified}' (Derived from: '{base_title_for_generic}')")

        try:
            # Call Wallhaven search only ONCE
            image_urls = await asyncio.to_thread(search_wallhaven, search_term_simplified, max_per_anime)
            final_urls = image_urls[:max_per_anime] # Limit results
            print(f"  => Finished processing '{original_title}'. Found {len(final_urls)} wallpapers.")
        except Exception as e_search:
            print(f"!!! Unexpected error during search processing for '{original_title}' (term: '{search_term_simplified}'): {e_search}")
            traceback.print_exc(); final_urls = []

        # Return the original title, the urls, AND the simplified term used for filtering later
        return original_title, final_urls, search_term_simplified


    # Helper function to manage semaphore acquisition
    async def process_anime_with_semaphore(sem, anime_data, index):
        """ Acquires semaphore, calls the single search processing function """
        nonlocal processed_titles_count
        async with sem:
            print(f"\n({index+1}/{len(unique_anime_list)}) Processing: '{anime_data['title']}' (Sem acquired)")
            # Call the single-search function
            result_tuple = await fetch_title_wallhaven_prioritized(anime_data)
            processed_titles_count += 1
            return result_tuple # Returns (original_title, final_url_list, simplified_term_used)

    # Create and run tasks concurrently
    tasks = [process_anime_with_semaphore(semaphore, anime_item, i) for i, anime_item in enumerate(unique_anime_list)]
    print(f"Running {len(tasks)} tasks with concurrency limit {CONCURRENCY_LIMIT}...")
    search_start_time = time.time()
    # search_results_list will contain tuples: [(original_title, urls, simplified_term), ...]
    search_results_list = await asyncio.gather(*tasks)
    search_end_time = time.time()
    print("-" * 30)
    print(f"Wallhaven search phase completed in {search_end_time - search_start_time:.2f}s.")

    # --- Post-Processing to Filter Duplicates Caused by Simplification ---
    print("Filtering results to remove duplicates from title simplification...")
    final_results = {}
    processed_simplified_terms = set()
    skipped_count = 0

    for original_title, urls, simplified_term_used in search_results_list:
        if not urls: # Skip titles where no wallpapers were found
            continue

        # Check if we've already added results for this simplified term
        if simplified_term_used not in processed_simplified_terms:
            final_results[original_title] = urls
            processed_simplified_terms.add(simplified_term_used)
        else:
            # Skip adding this entry to prevent visual duplication
            print(f"  Skipping results for '{original_title}' as simplified term '{simplified_term_used}' already processed.")
            skipped_count += 1

    print(f"Finished filtering. Kept {len(final_results)} entries, skipped {skipped_count} due to simplification collision.")

    # --- Return Final Results ---
    total_time = time.time() - start_time
    print(f"\nFinished all processing. Found wallpapers for {len(final_results)} titles.")
    print(f"Total request time: {total_time:.2f}s")
    return {"wallpapers": final_results} # Return the FILTERED results

# --- To Run the App ---
# (Instructions remain the same - set Env Vars on Render, run with uvicorn)
