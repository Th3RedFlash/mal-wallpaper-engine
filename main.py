# main.py (v1.7 - Added Concurrency Log, Default Concurrency 1, Single Prioritized Search + Backend Duplicate Filtering)

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
if WALLHAVEN_API_KEY:
    print(f"STARTUP: Wallhaven API Key found and will be used.")
else:
    print(f"STARTUP: Wallhaven API Key *not* found. Using default rate limits.")
print(f"STARTUP: Concurrency limit set to: {CONCURRENCY_LIMIT}")
if CONCURRENCY_LIMIT > 5 and not WALLHAVEN_API_KEY:
    print("STARTUP WARNING: Concurrency > 5 without an API key might easily hit rate limits!")
elif CONCURRENCY_LIMIT > 15 and WALLHAVEN_API_KEY:
     print("STARTUP WARNING: Concurrency > 15 even with API key might hit rate limits, monitor closely.")
elif CONCURRENCY_LIMIT <= 0:
     print("STARTUP ERROR: Concurrency limit must be >= 1. Using 1.")
     CONCURRENCY_LIMIT = 1
print("-" * 31)


# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# Define standard Headers (Includes API Key if set)
HEADERS = {
    "User-Agent": "MAL_Wallpaper_Engine/1.7 (Filtered Single Search; Contact: YourEmailOrProjectURL)"
}
if WALLHAVEN_API_KEY:
    HEADERS['X-API-Key'] = WALLHAVEN_API_KEY


# --- Title Simplification Function ---
def simplify_title(title):
    """ Aggressively simplifies an anime title for generic searching. """
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
        time.sleep(1.0) # Keep delay
        response = requests.get(search_url, params=params, headers=HEADERS, timeout=20); response.raise_for_status(); data = response.json()
        if data and 'data' in data and isinstance(data['data'], list):
            results_found = len(data['data']); print(f"    -> API returned {results_found} results.")
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
async def get_wallpapers(username: str, search: str = None, max_per_anime: int = 3):
    """
    Fetches MAL list, uses Single Prioritized Search via Wallhaven API
    with LIMITED CONCURRENCY and Backend Duplicate Filtering.
    """
    start_time = time.time()
    anime_data_list = [] # Stores {'title': '...', 'title_eng': '...', 'anime_id': ...}
    mal_data_fetched_successfully = False
    last_error_message = "Unknown error during MAL fetch."
    response = None

    # --- Fetch and Parse MAL Data ---
    print(f"--- Starting MAL Fetch for user: {username} ---")
    # == Attempt 1: Modern JSON endpoint ==
    mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0&order=1"
    print(f"MAL Attempt 1: Fetching JSON endpoint...")
    print(f"  URL: {mal_json_url}")
    try:
        mal_fetch_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"}
        print(f"  Using Headers: {mal_fetch_headers}")
        response = await asyncio.to_thread(requests.get, mal_json_url, headers=mal_fetch_headers, timeout=20)
        print(f"  MAL JSON Attempt - Status Code: {response.status_code}")
        print(f"  MAL JSON Attempt - Response Text Snippet: {response.text[:500]}...")
        response.raise_for_status()
        if 'application/json' in response.headers.get('Content-Type', ''):
            print(f"  MAL JSON Attempt - Content-Type is JSON. Parsing...")
            mal_data = response.json()
            print(f"  MAL JSON Attempt - Successfully parsed JSON.")
            processed_ids = set()
            count = 0
            for item in mal_data:
                if isinstance(item, dict) and item.get('status') == 2:
                    title = item.get('anime_title'); anime_id = item.get('anime_id')
                    if title and anime_id not in processed_ids:
                        if not search or search.lower() in title.lower():
                            eng_title = item.get('anime_title_eng')
                            title_eng = eng_title if eng_title and eng_title.lower() != title.lower() else None
                            anime_data_list.append({'title': title, 'title_eng': title_eng, 'anime_id': anime_id})
                            processed_ids.add(anime_id); count += 1
            print(f"  MAL JSON Attempt - Extracted {count} completed titles.")
            if count > 0: mal_data_fetched_successfully = True
        else:
            last_error_message = f"MAL JSON endpoint Non-JSON Response. CT: {response.headers.get('Content-Type')}"
            print(f"  MAL JSON Attempt - {last_error_message}")
    except requests.exceptions.HTTPError as e: last_error_message = f"MAL JSON Attempt - HTTP Error: {e}"; print(f"  {last_error_message}")
    except requests.exceptions.RequestException as e: last_error_message = f"MAL JSON Attempt - Network Error: {e}"; print(f"  {last_error_message}")
    except json.JSONDecodeError as e: last_error_message = f"MAL JSON Attempt - Error decoding JSON response: {e}"; print(f"  {last_error_message}")
    except Exception as e: last_error_message = f"MAL JSON Attempt - Unexpected error: {e}"; print(f"  {last_error_message}"); traceback.print_exc()

    # == Attempt 2: Fallback to scraping embedded JSON from HTML page ==
    if not mal_data_fetched_successfully:
        mal_html_url = f"https://myanimelist.net/animelist/{username}?status=2"
        print(f"\nMAL Attempt 2: Fetching HTML page...")
        print(f"  URL: {mal_html_url}")
        try:
            mal_fetch_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"}
            print(f"  Using Headers: {mal_fetch_headers}")
            response = await asyncio.to_thread(requests.get, mal_html_url, headers=mal_fetch_headers, timeout=25)
            print(f"  MAL HTML Attempt - Status Code: {response.status_code}")
            if response.ok: print(f"  MAL HTML Attempt - Response Text Snippet: {response.text[:1000]}...")
            response.raise_for_status()
            if 'text/html' in response.headers.get('Content-Type', ''):
                print(f"  MAL HTML Attempt - Content-Type is HTML. Parsing...")
                soup = BeautifulSoup(response.text, "html.parser")
                list_table = soup.find('table', attrs={'data-items': True})
                if list_table and list_table.get('data-items'):
                    print("  MAL HTML Attempt - Found data-items attribute. Parsing JSON...")
                    try:
                        mal_data = json.loads(list_table['data-items'])
                        print(f"  MAL HTML Attempt - Successfully parsed embedded JSON.")
                        initial_count = len(anime_data_list); processed_ids = {item['anime_id'] for item in anime_data_list if 'anime_id' in item}; count = 0
                        for item in mal_data:
                             if isinstance(item, dict) and item.get('status') == 2:
                                title = item.get('anime_title'); anime_id = item.get('anime_id')
                                if title and (not anime_id or anime_id not in processed_ids):
                                     if not search or search.lower() in title.lower():
                                        eng_title = item.get('anime_title_eng')
                                        title_eng = eng_title if eng_title and eng_title.lower() != title.lower() else None
                                        anime_data_list.append({'title': title, 'title_eng': title_eng, 'anime_id': anime_id})
                                        if anime_id: processed_ids.add(anime_id); count += 1
                        print(f"  MAL HTML Attempt - Extracted {count} additional/unique titles.")
                        if count > 0 : mal_data_fetched_successfully = True
                    except json.JSONDecodeError as e: last_error_message = f"MAL HTML Attempt - Error decoding JSON from data-items: {e}"; print(f"  {last_error_message}")
                    except Exception as e: last_error_message = f"MAL HTML Attempt - Error processing embedded JSON: {e}"; print(f"  {last_error_message}"); traceback.print_exc()
                else: last_error_message = "MAL HTML Attempt - Could not find 'data-items' in HTML table."; print(f"  {last_error_message}")
            else: last_error_message = f"MAL HTML Attempt - Page did not return HTML. CT: {response.headers.get('Content-Type')}"; print(f"  {last_error_message}")
        except requests.exceptions.HTTPError as e:
             last_error_message = f"MAL HTML Attempt - HTTP Error: {e}"; print(f"  {last_error_message}")
             try: print(f"      Response Body: {e.response.text[:500]}")
             except: pass
        except requests.exceptions.RequestException as e: last_error_message = f"MAL HTML Attempt - Network Error: {e}"; print(f"  {last_error_message}")
        except Exception as e: last_error_message = f"MAL HTML Attempt - Unexpected error: {e}"; print(f"  {last_error_message}"); traceback.print_exc()
    print(f"--- Finished MAL Fetch attempts ---")

    # --- Process MAL Results (Deduplication) ---
    unique_anime_map = {item['title']: item for item in reversed(anime_data_list)}
    unique_anime_list = sorted(list(unique_anime_map.values()), key=lambda x: x['title'])
    mal_fetch_time = time.time() - start_time
    print(f"\nFound {len(unique_anime_list)} unique titles after all attempts. (MAL Fetch took {mal_fetch_time:.2f}s)")
    if not unique_anime_list:
        if not mal_data_fetched_successfully: return {"error": f"Could not fetch MAL data for '{username}'. Last status: {last_error_message}"}
        else: return {"message": f"No completed anime found matching criteria for '{username}'.", "wallpapers": {}}

    # --- Search Wallhaven with Limited Concurrency (Single Prioritized Search) ---
    processed_titles_count = 0
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT) # Use limit from top
    print(f"\nStarting Wallhaven search for {len(unique_anime_list)} titles (Concurrency: {CONCURRENCY_LIMIT}, Single Search Strategy)...")
    print("-" * 30)

    # This function performs the SINGLE prioritized search logic
    async def fetch_title_wallhaven_prioritized(anime_info):
        original_title = anime_info['title']; english_title = anime_info['title_eng']; final_urls = []
        base_title_for_generic = english_title if english_title else original_title
        search_term_simplified = simplify_title(base_title_for_generic)
        print(f"  -> Using search term: '{search_term_simplified}' (Derived from: '{base_title_for_generic}')")
        try:
            image_urls = await asyncio.to_thread(search_wallhaven, search_term_simplified, max_per_anime)
            final_urls = image_urls[:max_per_anime] # Limit results
            print(f"  => Found {len(final_urls)} wallpapers for '{original_title}'.")
        except Exception as e: print(f"!!! Unexpected error during WH search processing for '{original_title}': {e}"); final_urls = []
        # Return the original title, the urls, AND the simplified term used for filtering later
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
    print(f"\nFinished all processing. Found wallpapers for {len(results)} titles.") # Corrected variable name here
    print(f"Total request time: {total_time:.2f}s")
    return {"wallpapers": final_results}

# --- To Run the App ---
# 1. Set Environment Variables (in Render or locally):
#    export WALLHAVEN_API_KEY='YOUR_API_KEY_HERE' (Recommended)
#    export WALLHAVEN_CONCURRENCY=1 (Recommended starting point to avoid 429 errors)
# 2. Install libraries: pip install fastapi "uvicorn[standard]" requests beautifulsoup4
# 3. Run: uvicorn main:app --reload --host 0.0.0.0 --port 8080
