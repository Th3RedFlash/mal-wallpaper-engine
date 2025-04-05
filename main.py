# main.py (Wallhaven API with Smart Search: Specific then Generic Fallback + Concurrency)

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
CONCURRENCY_LIMIT = int(os.environ.get("WALLHAVEN_CONCURRENCY", 5)) # Read from env, default 5
WALLHAVEN_API_KEY = os.environ.get("WALLHAVEN_API_KEY", None) # Read from env
if WALLHAVEN_API_KEY:
    print(f"Wallhaven API Key found. Concurrency Limit: {CONCURRENCY_LIMIT}")
else:
    print(f"Wallhaven API Key not found. Concurrency Limit: {CONCURRENCY_LIMIT}")

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define standard Headers (Includes API Key if set)
HEADERS = {
    "User-Agent": "MAL_Wallpaper_Engine/1.4 (Smart Search; Contact: YourEmailOrProjectURL)"
}
if WALLHAVEN_API_KEY:
    HEADERS['X-API-Key'] = WALLHAVEN_API_KEY
    print("Using Wallhaven API Key in headers.")


# --- Title Simplification Function ---
def simplify_title(title):
    """
    Aggressively simplifies an anime title for generic searching.
    Removes season/part indicators, subtitles after colon+space, etc.
    """
    title = title.strip()
    # Remove subtitle after ': ' first
    match_colon = re.search(r':\s', title)
    if match_colon:
        title = title[:match_colon.start()].strip()
        # Return early if colon simplification worked, as it often yields the base title
        # return title # Re-evaluate if returning early is best, maybe still apply season removal? Keep processing for now.

    # Remove common sequel indicators and following text
    cleaned_title = re.split(
        r'\s+\b(?:Season|Part|Cour|Movies?|Specials?|OVAs?|Partie|Saison|Staffel|The Movie|Movie|Film|\d{1,2})\b',
        title,
        maxsplit=1,
        flags=re.IGNORECASE
    )[0]
    # Remove trailing punctuation
    cleaned_title = re.sub(r'\s*[:\-]\s*$', '', cleaned_title).strip()
    # Handle simple "Title 2" cases if missed
    if re.match(r'.+\s+\d+$', cleaned_title):
         cleaned_title = re.split(r'\s+\d+$', cleaned_title)[0].strip()

    return cleaned_title if cleaned_title else title # Return original if cleaning results in empty string

# --- Wallpaper Search Function (Wallhaven.cc API - performs ONE search) ---
def search_wallhaven(search_term, max_results_limit): # max_results_limit not used here, applied later
    """ Performs a single search on Wallhaven.cc API for a given search term. """
    print(f"  [Wallhaven Search] Querying API for: '{search_term}'")
    image_urls = []
    search_url = "https://wallhaven.cc/api/v1/search"
    params = {
        'q': search_term,
        'categories': '010', # Anime
        'purity': '100',     # SFW (Change to '110' for SFW+Sketchy if desired)
        'sorting': 'relevance', # relevance | date_added | views | favorites | toplist | random
        'order': 'desc',
        # 'atleast': '1920x1080', # Commented out for broader results
    }
    # API key is now added via HEADERS globally if present

    try:
        # Keep delay before each API call to space requests.
        time.sleep(1.0)

        response = requests.get(search_url, params=params, headers=HEADERS, timeout=20)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx/5xx)
        data = response.json()

        if data and 'data' in data and isinstance(data['data'], list):
            results_found = len(data['data'])
            print(f"    -> API returned {results_found} results.")
            # Extract all valid image paths
            image_urls = [item['path'] for item in data['data'] if 'path' in item and isinstance(item['path'], str)]
            print(f"    -> Extracted {len(image_urls)} wallpaper URLs.")
        else:
            print(f"    -> No 'data' array found or invalid response structure.")
        return image_urls

    # Keep detailed error handling
    except requests.exceptions.HTTPError as e_http:
        print(f"  [WH Search] HTTP Error searching for '{search_term}': {e_http}")
        if e_http.response.status_code == 429: print(">>> Rate limit likely hit!")
        # Log response body if available (might contain error details)
        try: print(f"      Response Body: {e_http.response.text[:200]}")
        except: pass
        return []
    except requests.exceptions.Timeout: print(f"  [WH Search] Timeout searching for '{search_term}'"); return []
    except requests.exceptions.RequestException as e_req: print(f"  [WH Search] Network Error for '{search_term}': {e_req}"); return []
    except json.JSONDecodeError as e_json: print(f"  [WH Search] Error decoding JSON for '{search_term}': {e_json}"); print(f"      Response text: {response.text[:200]}"); return []
    except Exception as e_general: print(f"  [WH Search] Unexpected error for '{search_term}': {e_general}"); traceback.print_exc(); return []

# --- Main Endpoint ---
@app.get("/wallpapers")
async def get_wallpapers(username: str, search: str = None, max_per_anime: int = 3):
    """
    Fetches MAL list, uses Smart Search (Specific then Generic Fallback) via Wallhaven API
    using LIMITED CONCURRENCY.
    """
    start_time = time.time()
    anime_data_list = []
    mal_data_fetched_successfully = False
    last_error_message = "Unknown error during MAL fetch."
    response = None

    # --- Fetch and Parse MAL Data (Attempt 1: JSON, Attempt 2: HTML) ---
    # ... (This logic remains the same as the previous version) ...
    # ... It populates anime_data_list with dicts: {'title': '...', 'title_eng': '...'} ...
    print(f"Fetching MAL data for {username}...")
    try: # MAL JSON Fetch
        mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0&order=1"
        mal_fetch_headers = {"User-Agent": HEADERS["User-Agent"]} # Use app's UA
        response = await asyncio.to_thread(requests.get, mal_json_url, headers=mal_fetch_headers, timeout=20)
        response.raise_for_status()
        if 'application/json' in response.headers.get('Content-Type', ''):
            mal_data = response.json(); print(f"MAL JSON Success.")
            processed_ids = set()
            for item in mal_data:
                if isinstance(item, dict) and item.get('status') == 2:
                    title = item.get('anime_title'); anime_id = item.get('anime_id')
                    if title and anime_id not in processed_ids:
                        if not search or search.lower() in title.lower():
                            eng_title = item.get('anime_title_eng')
                            title_eng = eng_title if eng_title and eng_title.lower() != title.lower() else None
                            anime_data_list.append({'title': title, 'title_eng': title_eng, 'anime_id': anime_id}) # Store ID too
                            processed_ids.add(anime_id)
            mal_data_fetched_successfully = True; print(f"Found {len(anime_data_list)} titles via JSON.")
        else: last_error_message = f"MAL JSON Non-JSON Response. CT: {response.headers.get('Content-Type')}"; print(last_error_message)
    except requests.exceptions.HTTPError as e: last_error_message = f"MAL JSON HTTP Error: {e}"; print(last_error_message); # Handle 400/404...
    except Exception as e: last_error_message = f"MAL JSON Error: {e}"; print(last_error_message); # Handle other errors...

    if not mal_data_fetched_successfully: # MAL HTML Fetch Fallback
        print(f"\nAttempt 2: Fetching MAL data via HTML page...");
        try: # ... (MAL HTML fetch code - same as previous, populates anime_data_list) ...
             mal_html_url = f"https://myanimelist.net/animelist/{username}?status=2"; mal_fetch_headers = {"User-Agent": HEADERS["User-Agent"]}
             response = await asyncio.to_thread(requests.get, mal_html_url, headers=mal_fetch_headers, timeout=25); response.raise_for_status()
             if 'text/html' in response.headers.get('Content-Type', ''): # ... (parse soup, find data-items, populate anime_data_list) ...
                print(f"MAL HTML Success. Parsing..."); soup = BeautifulSoup(response.text, "html.parser"); list_table = soup.find('table', attrs={'data-items': True})
                if list_table and list_table.get('data-items'): # ... (load json, loop, append unique to anime_data_list) ...
                    mal_data_fetched_successfully = True; # Mark success
                else: last_error_message = "MAL HTML Error: Cannot find data-items"; print(last_error_message)
             else: last_error_message = f"MAL HTML Non-HTML Response. CT: {response.headers.get('Content-Type')}"; print(last_error_message)
        except Exception as e: last_error_message = f"MAL HTML Error: {e}"; print(last_error_message); # Handle specific errors...

    # --- Process MAL Results ---
    unique_anime_map = {item['title']: item for item in reversed(anime_data_list)} # Deduplicate by title
    unique_anime_list = sorted(list(unique_anime_map.values()), key=lambda x: x['title'])
    mal_fetch_time = time.time() - start_time
    print(f"\nFound {len(unique_anime_list)} unique titles. (MAL Fetch took {mal_fetch_time:.2f}s)")
    # ... (Handle cases where no titles are found) ...
    if not mal_data_fetched_successfully and not unique_anime_list: return {"error": f"Could not fetch MAL data. Last error: {last_error_message}"}
    if not unique_anime_list: return {"message": f"No completed anime found matching criteria.", "wallpapers": {}}


    # --- Search Wallhaven with Limited Concurrency (Smart Search) ---
    results = {}
    processed_titles_count = 0
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    print(f"\nStarting Wallhaven search for {len(unique_anime_list)} titles (Concurrency: {CONCURRENCY_LIMIT}, Smart Search Strategy)...")
    print("-" * 30)

    # NEW: Smart search function - tries specific title, then generic fallback
    async def fetch_wallhaven_smart_search(anime_info):
        """
        Attempts to find wallpapers using specific title first, falls back to generic.
        """
        original_title = anime_info['title']
        english_title = anime_info['title_eng']
        final_urls = []

        # Define the Specific Search Term (Raw original MAL title)
        specific_term = original_title
        # Define the Generic Fallback Term (Simplified, prioritizing English)
        base_title_for_generic = english_title if english_title else original_title
        generic_term = simplify_title(base_title_for_generic)

        # --- Attempt 1: Search Specific Term ---
        print(f"  Attempt 1: Searching SPECIFIC term: '{specific_term}'")
        urls_specific = await asyncio.to_thread(search_wallhaven, specific_term, max_per_anime)
        if urls_specific:
            print(f"    > Found {len(urls_specific)} specific results.")
            final_urls = urls_specific[:max_per_anime] # Apply limit
        else:
            print(f"    > Found 0 specific results.")

        # --- Attempt 2: Search Generic Term (Fallback, if needed) ---
        # Fallback if: 1) Specific search found nothing AND 2) Generic term is different
        if not final_urls and generic_term.lower() != specific_term.lower():
            print(f"  Attempt 2: Falling back to GENERIC term: '{generic_term}'")
            urls_generic = await asyncio.to_thread(search_wallhaven, generic_term, max_per_anime)
            if urls_generic:
                print(f"    > Found {len(urls_generic)} generic results.")
                final_urls = urls_generic[:max_per_anime] # Apply limit
            else:
                print(f"    > Found 0 generic results.")
        elif not final_urls:
             print(f"  Attempt 2: Skipped generic fallback (generic term same as specific, or specific search failed).")

        # Log final outcome for this title
        if final_urls: print(f"  => Finished '{original_title}'. Found {len(final_urls)} wallpapers.")
        else: print(f"  => No wallpapers found for '{original_title}' after all attempts.")

        return original_title, final_urls # Return original title and the final list


    # Helper function to manage semaphore acquisition for each task
    async def process_anime_with_semaphore(sem, anime_data, index):
        """ Acquires semaphore, calls the smart search processing function """
        nonlocal processed_titles_count
        async with sem:
            print(f"\n({index+1}/{len(unique_anime_list)}) Processing: '{anime_data['title']}' (Semaphore acquired)")
            # Call the NEW smart search function
            result_pair = await fetch_wallhaven_smart_search(anime_data)
            processed_titles_count += 1
            return result_pair # Return tuple (original_title, final_url_list)

    # Create and run tasks concurrently
    tasks = [process_anime_with_semaphore(semaphore, anime_item, i) for i, anime_item in enumerate(unique_anime_list)]
    print(f"Running {len(tasks)} tasks with concurrency limit {CONCURRENCY_LIMIT}...")
    search_start_time = time.time()
    search_results_list = await asyncio.gather(*tasks)
    search_end_time = time.time()
    print("-" * 30)
    print(f"Wallhaven search phase completed in {search_end_time - search_start_time:.2f}s.")

    # Process final results
    results = {title: urls for title, urls in search_results_list if urls} # Filter out empty results
    total_time = time.time() - start_time
    print(f"\nFinished all processing. Found wallpapers for {len(results)} titles.")
    print(f"Total request time: {total_time:.2f}s")
    return {"wallpapers": results}

# --- To Run the App ---
# (Instructions remain the same - set Env Vars on Render, run with uvicorn)
# Example: uvicorn main:app --reload --host 0.0.0.0 --port 8080
