# main.py (v1.9 - Changed default max_per_anime to 5)

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
if CONCURRENCY_LIMIT > 5 and not WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 5 without an API key might easily hit rate limits!")
elif CONCURRENCY_LIMIT > 15 and WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 15 even with API key might hit rate limits, monitor closely.")
elif CONCURRENCY_LIMIT <= 0: print("STARTUP ERROR: Concurrency limit must be >= 1. Using 1."); CONCURRENCY_LIMIT = 1
print("-" * 31)


# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware( CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"], )

# Define standard Headers (Includes API Key if set)
HEADERS = { "User-Agent": "MAL_Wallpaper_Engine/1.9 (Max 5; Contact: YourEmailOrProjectURL)" }
if WALLHAVEN_API_KEY: HEADERS['X-API-Key'] = WALLHAVEN_API_KEY

# --- Title Simplification Function ---
def simplify_title(title):
    # ... (simplify_title function remains the same) ...
    title = title.strip(); match_colon = re.search(r':\s', title)
    if match_colon: title = title[:match_colon.start()].strip()
    cleaned_title = re.split(r'\s+\b(?:Season|Part|Cour|Movies?|Specials?|OVAs?|Partie|Saison|Staffel|The Movie|Movie|Film|\d{1,2})\b', title, maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned_title = re.sub(r'\s*[:\-]\s*$', '', cleaned_title).strip()
    if re.match(r'.+\s+\d+$', cleaned_title): cleaned_title = re.split(r'\s+\d+$', cleaned_title)[0].strip()
    return cleaned_title if cleaned_title else title

# --- Wallpaper Search Function (Wallhaven.cc API - performs ONE search) ---
def search_wallhaven(search_term, max_results_limit): # max_results_limit (passed from endpoint) isn't used for API call limit, applied later
    """ Performs a single search on Wallhaven.cc API for a given search term. """
    print(f"  [Wallhaven Search] Querying API for: '{search_term}'")
    image_urls = []; search_url = "https://wallhaven.cc/api/v1/search"
    params = { 'q': search_term, 'categories': '010', 'purity': '100', 'sorting': 'relevance', 'order': 'desc' }
    try:
        time.sleep(1.0); response = requests.get(search_url, params=params, headers=HEADERS, timeout=20); response.raise_for_status(); data = response.json()
        if data and 'data' in data and isinstance(data['data'], list):
            results_found = len(data['data']); print(f"    -> API returned {results_found} results.")
            # Extract all valid image paths from this page
            image_urls = [item['path'] for item in data['data'] if 'path' in item and isinstance(item['path'], str)]
            print(f"    -> Extracted {len(image_urls)} wallpaper URLs.")
        else: print(f"    -> No 'data' array found or invalid response.")
        return image_urls
    except requests.exceptions.HTTPError as e: print(f"  [WH Search] HTTP Error '{search_term}': {e}"); return []
    except requests.exceptions.Timeout: print(f"  [WH Search] Timeout '{search_term}'"); return []
    except requests.exceptions.RequestException as e: print(f"  [WH Search] Network Error '{search_term}': {e}"); return []
    except json.JSONDecodeError as e: print(f"  [WH Search] JSON Error '{search_term}': {e}"); return []
    except Exception as e: print(f"  [WH Search] Unexpected error '{search_term}': {e}"); traceback.print_exc(); return []


# --- Main Endpoint ---
@app.get("/wallpapers")
async def get_wallpapers(username: str, search: str = None, max_per_anime: int = 5): # <<< CHANGED DEFAULT TO 5
    """
    Fetches MAL list, uses Single Prioritized Search via Wallhaven API
    with LIMITED CONCURRENCY and Backend Duplicate Filtering. Returns up to max_per_anime (default 5).
    """
    start_time = time.time()
    anime_data_list = [] # Stores {'title': '...', 'title_eng': '...', 'anime_id': ...}
    mal_data_fetched_successfully = False; last_error_message = "Unknown error during MAL fetch."; response = None

    # --- Fetch and Parse MAL Data ---
    # ... (MAL Fetching Logic - Remains the same as v1.8) ...
    print(f"--- Starting MAL Fetch for user: {username} ---")
    # == Attempt 1: JSON ==
    mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0&order=1"; print(f"MAL Attempt 1: Fetching JSON..."); print(f"  URL: {mal_json_url}")
    try: # ... (Full JSON fetch try block) ...
        mal_fetch_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"}; print(f"  Using Headers: {mal_fetch_headers}")
        response = await asyncio.to_thread(requests.get, mal_json_url, headers=mal_fetch_headers, timeout=20); print(f"  MAL JSON Attempt - Status Code: {response.status_code}"); print(f"  MAL JSON Attempt - Response Text Snippet: {response.text[:500]}...")
        response.raise_for_status()
        if 'application/json' in response.headers.get('Content-Type', ''): # ... (Parse JSON, loop, append to anime_data_list) ...
           mal_data_fetched_successfully = True # Assuming >0 results found in loop
        else: last_error_message = f"MAL JSON Non-JSON Response. CT: {response.headers.get('Content-Type')}"; print(f"  MAL JSON Attempt - {last_error_message}")
    except Exception as e: last_error_message = f"MAL JSON Attempt Error: {e}"; print(f"  {last_error_message}") # Simplified catch

    # == Attempt 2: HTML Fallback ==
    if not mal_data_fetched_successfully: # ... (Full HTML fetch try block) ...
        mal_html_url = f"https://myanimelist.net/animelist/{username}?status=2"; print(f"\nMAL Attempt 2: Fetching HTML..."); print(f"  URL: {mal_html_url}")
        try: # ... (Fetch HTML, parse soup, find data-items, load json, loop, append unique to anime_data_list) ...
            mal_data_fetched_successfully = True # Assuming >0 results found in loop
        except Exception as e: last_error_message = f"MAL HTML Attempt Error: {e}"; print(f"  {last_error_message}") # Simplified catch
    print(f"--- Finished MAL Fetch attempts ---")

    # --- Process MAL Results ---
    unique_anime_map = {item['title']: item for item in reversed(anime_data_list)}
    unique_anime_list = sorted(list(unique_anime_map.values()), key=lambda x: x['title'])
    mal_fetch_time = time.time() - start_time
    print(f"\nFound {len(unique_anime_list)} unique titles after all attempts. (MAL Fetch took {mal_fetch_time:.2f}s)")
    if not unique_anime_list: # ... (Handle no results found) ...
        if not mal_data_fetched_successfully: return {"error": f"Could not fetch MAL data for '{username}'. Last status: {last_error_message}"}
        else: return {"message": f"No completed anime found matching criteria for '{username}'.", "wallpapers": {}}

    # --- Search Wallhaven with Limited Concurrency (Single Prioritized Search) ---
    processed_titles_count = 0
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT) # Use limit from top
    print(f"\nStarting Wallhaven search for {len(unique_anime_list)} titles (Concurrency: {CONCURRENCY_LIMIT}, Max/Anime: {max_per_anime}, Single Search Strategy)...") # Log max_per_anime
    print("-" * 30)

    # This function performs the SINGLE prioritized search logic
    async def fetch_title_wallhaven_prioritized(anime_info):
        original_title = anime_info['title']; english_title = anime_info['title_eng']; final_urls = []
        base_title_for_generic = english_title if english_title else original_title
        search_term_simplified = simplify_title(base_title_for_generic)
        print(f"  -> Using search term: '{search_term_simplified}' (Derived from: '{base_title_for_generic}')")
        try:
            # Pass max_per_anime to search_wallhaven (though it doesn't use it currently for API call itself)
            image_urls = await asyncio.to_thread(search_wallhaven, search_term_simplified, max_per_anime)
            # Apply the limit HERE after getting results
            final_urls = image_urls[:max_per_anime]
            print(f"  => Found {len(final_urls)} wallpapers for '{original_title}'. (Limit: {max_per_anime})")
        except Exception as e: print(f"!!! Unexpected error during WH search processing for '{original_title}': {e}"); final_urls = []
        # Return the original title, the limited urls, AND the simplified term used for filtering later
        return original_title, final_urls, search_term_simplified

    # Helper function to manage semaphore acquisition
    async def process_anime_with_semaphore(sem, anime_data, index):
        nonlocal processed_titles_count
        async with sem:
            print(f"\n({index+1}/{len(unique_anime_list)}) Processing: '{anime_data['title']}' (Sem acquired)")
            result_tuple = await fetch_title_wallhaven_prioritized(anime_data)
            processed_titles_count += 1; return result_tuple

    # Create and run tasks concurrently
    tasks = [process_anime_with_semaphore(semaphore, anime_item, i) for i, anime_item in enumerate(unique_anime_list)]
    print(f"Running {len(tasks)} tasks with concurrency limit {CONCURRENCY_LIMIT}...")
    search_start_time = time.time()
    search_results_list = await asyncio.gather(*tasks)
    search_end_time = time.time(); print("-" * 30)
    print(f"Wallhaven search phase completed in {search_end_time - search_start_time:.2f}s.")

    # --- Post-Processing Filter for Duplicates ---
    # ... (Filtering logic remains the same) ...
    print("Filtering results to remove duplicates from title simplification...")
    final_results = {}; processed_simplified_terms = set(); skipped_count = 0
    for original_title, urls, simplified_term_used in search_results_list:
        if not urls: continue
        if simplified_term_used not in processed_simplified_terms:
            final_results[original_title] = urls; processed_simplified_terms.add(simplified_term_used)
        else: print(f"  Skipping results for '{original_title}' (term '{simplified_term_used}' already processed)."); skipped_count += 1
    print(f"Finished filtering. Kept {len(final_results)} entries, skipped {skipped_count} due to simplification collision.")


    # --- Return Final Results ---
    total_time = time.time() - start_time
    # *** Fixed variable name in log statement in v1.8, remains fixed here ***
    print(f"\nFinished all processing. Found wallpapers for {len(final_results)} titles.")
    print(f"Total request time: {total_time:.2f}s")
    return {"wallpapers": final_results} # Return the FILTERED results

# --- To Run the App ---
# 1. Set Environment Variables in Render:
#    WALLHAVEN_API_KEY='YOUR_API_KEY_HERE' (Recommended)
#    WALLHAVEN_CONCURRENCY=1 (Recommended to avoid 429 errors)
# 2. Install libraries: pip install fastapi "uvicorn[standard]" requests beautifulsoup4
# 3. Run locally (optional): uvicorn main:app --reload --host 0.0.0.0 --port 8080
