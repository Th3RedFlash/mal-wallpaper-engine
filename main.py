# main.py (v1.10 - Enhanced MAL JSON Processing Logs)

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
CONCURRENCY_LIMIT = int(os.environ.get("WALLHAVEN_CONCURRENCY", 1))
WALLHAVEN_API_KEY = os.environ.get("WALLHAVEN_API_KEY", None)
# ... (Startup Logging - unchanged) ...
print(f"--- App Startup Configuration ---")
if WALLHAVEN_API_KEY: print(f"STARTUP: Wallhaven API Key found and will be used.")
else: print(f"STARTUP: Wallhaven API Key *not* found. Using default rate limits.")
print(f"STARTUP: Concurrency limit set to: {CONCURRENCY_LIMIT}")
if CONCURRENCY_LIMIT > 5 and not WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 5 without API key might easily hit rate limits!")
elif CONCURRENCY_LIMIT > 15 and WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 15 even with API key might hit rate limits, monitor closely.")
elif CONCURRENCY_LIMIT <= 0: print("STARTUP ERROR: Concurrency limit must be >= 1. Using 1."); CONCURRENCY_LIMIT = 1
print("-" * 31)

app = FastAPI()
app.add_middleware( CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"], )
HEADERS = { "User-Agent": "MAL_Wallpaper_Engine/1.10 (Debug MAL JSON; Contact: YourEmailOrProjectURL)" }
if WALLHAVEN_API_KEY: HEADERS['X-API-Key'] = WALLHAVEN_API_KEY

# --- Title Simplification Function ---
# ... (simplify_title function remains the same) ...
def simplify_title(title):
    title = title.strip(); match_colon = re.search(r':\s', title)
    if match_colon: title = title[:match_colon.start()].strip()
    cleaned_title = re.split(r'\s+\b(?:Season|Part|Cour|Movies?|Specials?|OVAs?|Partie|Saison|Staffel|The Movie|Movie|Film|\d{1,2})\b', title, maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned_title = re.sub(r'\s*[:\-]\s*$', '', cleaned_title).strip()
    if re.match(r'.+\s+\d+$', cleaned_title): cleaned_title = re.split(r'\s+\d+$', cleaned_title)[0].strip()
    return cleaned_title if cleaned_title else title

# --- Wallpaper Search Function (Wallhaven.cc API - performs ONE search) ---
# ... (search_wallhaven function remains the same) ...
def search_wallhaven(search_term, max_results_limit):
    print(f"  [Wallhaven Search] Querying API for: '{search_term}'")
    image_urls = []; search_url = "https://wallhaven.cc/api/v1/search"
    params = { 'q': search_term, 'categories': '010', 'purity': '100', 'sorting': 'relevance', 'order': 'desc' }
    try:
        time.sleep(1.0); response = requests.get(search_url, params=params, headers=HEADERS, timeout=20); response.raise_for_status(); data = response.json()
        if data and 'data' in data and isinstance(data['data'], list):
            results_found = len(data['data']); print(f"    -> API returned {results_found} results.")
            image_urls = [item['path'] for item in data['data'] if 'path' in item and isinstance(item['path'], str)]
            print(f"    -> Extracted {len(image_urls)} wallpaper URLs.")
        else: print(f"    -> No 'data' array found or invalid response.")
        return image_urls
    except Exception as e: print(f"  [WH Search] Error for '{search_term}': {e}"); return []


# --- Main Endpoint ---
@app.get("/wallpapers")
async def get_wallpapers(username: str, search: str = None, max_per_anime: int = 5): # Default 5 images
    start_time = time.time()
    anime_data_list = []
    mal_data_fetched_successfully = False
    last_error_message = "Unknown error during MAL fetch."
    response = None

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
        actual_content_type = response.headers.get('Content-Type', 'N/A') # Get actual content type
        print(f"  MAL JSON Attempt - Content-Type Header: {actual_content_type}") # Log actual Content-Type
        print(f"  MAL JSON Attempt - Response Text Snippet: {response.text[:500]}...")
        response.raise_for_status() # Check for HTTP errors AFTER logging

        # *** ADDED DETAILED LOGGING BELOW ***
        content_type_check = 'application/json' in actual_content_type # Perform the check
        print(f"  MAL JSON Attempt - Check if 'application/json' in Content-Type: {content_type_check}") # Log check result

        if content_type_check:
            print(f"  MAL JSON Attempt - Content-Type check PASSED. Trying to parse JSON...")
            try:
                mal_data = response.json()
                print(f"  MAL JSON Attempt - Successfully parsed JSON. Found {len(mal_data)} items in list.") # Log success + length
                processed_ids = set(); count = 0
                print(f"  MAL JSON Attempt - Starting loop through items...") # Log loop start
                for i, item in enumerate(mal_data):
                    is_dict = isinstance(item, dict)
                    status_ok = item.get('status') == 2 if is_dict else False
                    # print(f"    Item {i}: IsDict={is_dict}, StatusOK={status_ok}") # Deeper debug log (optional)
                    if is_dict and status_ok:
                        title = item.get('anime_title'); anime_id = item.get('anime_id')
                        id_ok = anime_id not in processed_ids
                        # print(f"    Item {i}: Title='{title}', ID={anime_id}, ID_OK={id_ok}") # Deeper debug log (optional)
                        if title and id_ok:
                            search_ok = not search or search.lower() in title.lower()
                            # print(f"    Item {i}: SearchOK={search_ok}") # Deeper debug log (optional)
                            if search_ok:
                                # print(f"    Item {i}: Appending.") # Deeper debug log (optional)
                                eng_title = item.get('anime_title_eng')
                                title_eng = eng_title if eng_title and eng_title.lower() != title.lower() else None
                                anime_data_list.append({'title': title, 'title_eng': title_eng, 'anime_id': anime_id})
                                processed_ids.add(anime_id); count += 1
                print(f"  MAL JSON Attempt - Loop finished. Extracted {count} completed titles matching filter.") # Updated log message
                if count > 0: mal_data_fetched_successfully = True
            except json.JSONDecodeError as e_json:
                # Specific catch for JSON parsing errors
                last_error_message = f"MAL JSON Attempt - Error decoding JSON response: {e_json}"
                print(f"  {last_error_message}")
                print(f"      Response text that failed parsing: {response.text[:500]}") # Log text again
            except Exception as e_loop: # Catch errors during loop/append
                 last_error_message = f"MAL JSON Attempt - Error during item processing loop: {e_loop}"
                 print(f"  {last_error_message}")
                 traceback.print_exc()
        else:
            # Logged if the Content-Type check failed
            last_error_message = f"MAL JSON endpoint did not return 'application/json'. Actual: {actual_content_type}"
            print(f"  MAL JSON Attempt - {last_error_message}")
        # *** END DETAILED LOGGING ***

    except requests.exceptions.HTTPError as e: last_error_message = f"MAL JSON Attempt - HTTP Error: {e}"; print(f"  {last_error_message}")
    except requests.exceptions.RequestException as e: last_error_message = f"MAL JSON Attempt - Network Error: {e}"; print(f"  {last_error_message}")
    # Removed broad Exception here to let specific ones above handle things unless absolutely necessary
    # except Exception as e: last_error_message = f"MAL JSON Attempt - Unexpected error BEFORE processing: {e}"; print(f"  {last_error_message}"); traceback.print_exc()


    # == Attempt 2: HTML Fallback ==
    if not mal_data_fetched_successfully:
        # ... (HTML fetch logic remains the same, including its own detailed logging) ...
        pass # Placeholder - Full HTML fetch logic is unchanged from v1.8

    print(f"--- Finished MAL Fetch attempts ---")

    # --- Process MAL Results ---
    # ... (Deduplication logic remains the same) ...
    unique_anime_map = {item['title']: item for item in reversed(anime_data_list)}
    unique_anime_list = sorted(list(unique_anime_map.values()), key=lambda x: x['title'])
    mal_fetch_time = time.time() - start_time
    print(f"\nFound {len(unique_anime_list)} unique titles after all attempts. (MAL Fetch took {mal_fetch_time:.2f}s)")
    # ... (Handle cases where no titles are found) ...
    if not unique_anime_list: # Check after both attempts
        if not mal_data_fetched_successfully: return {"error": f"Could not fetch MAL data for '{username}'. Last status: {last_error_message}"}
        else: return {"message": f"No completed anime found matching criteria for '{username}'.", "wallpapers": {}}


    # --- Search Wallhaven with Limited Concurrency ---
    # ... (Semaphore setup, task definition, gather, filtering - all remain the same as v1.8) ...
    processed_titles_count = 0; semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    print(f"\nStarting Wallhaven search for {len(unique_anime_list)} titles (Concurrency: {CONCURRENCY_LIMIT}, Max/Anime: {max_per_anime}, Single Search Strategy)...")
    print("-" * 30)
    async def fetch_title_wallhaven_prioritized(anime_info): # ... (function definition unchanged) ...
        original_title = anime_info['title']; english_title = anime_info['title_eng']; final_urls = []
        base_title_for_generic = english_title if english_title else original_title
        search_term_simplified = simplify_title(base_title_for_generic)
        print(f"  -> Using search term: '{search_term_simplified}' (From: '{base_title_for_generic}')")
        try:
            image_urls = await asyncio.to_thread(search_wallhaven, search_term_simplified, max_per_anime)
            final_urls = image_urls[:max_per_anime]; print(f"  => Found {len(final_urls)} wallpapers for '{original_title}'. (Limit: {max_per_anime})")
        except Exception as e: print(f"!!! Unexpected error during WH search processing for '{original_title}': {e}"); final_urls = []
        return original_title, final_urls, search_term_simplified
    async def process_anime_with_semaphore(sem, anime_data, index): # ... (function definition unchanged) ...
        nonlocal processed_titles_count; async with sem: print(f"\n({index+1}/{len(unique_anime_list)}) Processing: '{anime_data['title']}' (Sem acquired)"); result_tuple = await fetch_title_wallhaven_prioritized(anime_data); processed_titles_count += 1; return result_tuple
    tasks = [process_anime_with_semaphore(semaphore, anime_item, i) for i, anime_item in enumerate(unique_anime_list)]
    print(f"Running {len(tasks)} tasks with concurrency limit {CONCURRENCY_LIMIT}..."); search_start_time = time.time()
    search_results_list = await asyncio.gather(*tasks)
    search_end_time = time.time(); print("-" * 30); print(f"Wallhaven search phase completed in {search_end_time - search_start_time:.2f}s.")

    # --- Post-Processing Filter ---
    # ... (Filtering logic unchanged) ...
    print("Filtering results..."); final_results = {}; processed_simplified_terms = set(); skipped_count = 0; title_to_info_map = {item['title']: item for item in unique_anime_list}
    for original_title, urls, simplified_term_used in search_results_list:
        if not urls: continue
        if simplified_term_used not in processed_simplified_terms: final_results[original_title] = urls; processed_simplified_terms.add(simplified_term_used)
        else: print(f"  Skipping results for '{original_title}' (term '{simplified_term_used}' processed)."); skipped_count += 1
    print(f"Finished filtering. Kept {len(final_results)}, skipped {skipped_count}.")

    # --- Return Final Results ---
    total_time = time.time() - start_time
    print(f"\nFinished all processing. Found wallpapers for {len(final_results)} titles.")
    print(f"Total request time: {total_time:.2f}s")
    return {"wallpapers": final_results}

# --- To Run the App ---
# (Instructions remain the same)
