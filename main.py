# main.py (v1.12 - Enhanced MAL JSON Processing Loop Logging)

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
# Default to 1 for safety if ENV VAR not set. User MUST set it lower in Render if needed.
CONCURRENCY_LIMIT = int(os.environ.get("WALLHAVEN_CONCURRENCY", 1))
WALLHAVEN_API_KEY = os.environ.get("WALLHAVEN_API_KEY", None)

# Log API Key status AND Concurrency Limit on startup
print(f"--- App Startup Configuration ---")
if WALLHAVEN_API_KEY: print(f"STARTUP: Wallhaven API Key found and will be used.")
else: print(f"STARTUP: Wallhaven API Key *not* found. Using default rate limits.")
print(f"STARTUP: Concurrency limit set to: {CONCURRENCY_LIMIT}") # Log the value being used
if CONCURRENCY_LIMIT > 5 and not WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 5 without an API key might easily hit rate limits!")
elif CONCURRENCY_LIMIT > 15 and WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 15 even with API key might hit rate limits, monitor closely.")
elif CONCURRENCY_LIMIT <= 0: print("STARTUP ERROR: Concurrency limit must be >= 1. Using 1."); CONCURRENCY_LIMIT = 1
print("-" * 31)


# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware( CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"], )

# Define standard Headers (Includes API Key if set)
HEADERS = { "User-Agent": "MAL_Wallpaper_Engine/1.12 (Debug MAL JSON Loop; Contact: YourEmailOrProjectURL)" } # Updated UA
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
def search_wallhaven(search_term, max_results_limit):
    """ Performs a single search on Wallhaven.cc API for a given search term. """
    print(f"  [Wallhaven Search] Querying API for: '{search_term}'")
    image_urls = []; search_url = "https://wallhaven.cc/api/v1/search"
    params = { 'q': search_term, 'categories': '010', 'purity': '100', 'sorting': 'relevance', 'order': 'desc' }
    try:
        time.sleep(1.0); # Keep delay
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
async def get_wallpapers(username: str, search: str = None, max_per_anime: int = 5): # Default 5 images
    """
    Fetches MAL list, uses Single Prioritized Search via Wallhaven API
    with LIMITED CONCURRENCY and Backend Duplicate Filtering. Includes detailed MAL logging.
    """
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
        actual_content_type = response.headers.get('Content-Type', 'N/A')
        print(f"  MAL JSON Attempt - Content-Type Header: {actual_content_type}")
        print(f"  MAL JSON Attempt - Response Text Snippet: {response.text[:500]}...")
        response.raise_for_status()

        content_type_check = 'application/json' in actual_content_type
        print(f"  MAL JSON Attempt - Check if 'application/json' in Content-Type: {content_type_check}")

        if content_type_check:
            print(f"  MAL JSON Attempt - Content-Type check PASSED. Trying to parse JSON...")
            try: # Inner try for parsing and loop
                mal_data = response.json()
                # --- NEW DEBUG LOGS ---
                print(f"  MAL JSON Attempt - Successfully parsed JSON. Found {len(mal_data)} items in list.")
                print(f"DEBUG: Type of mal_data: {type(mal_data)}") # What type is it?
                # --- END NEW DEBUG LOGS ---

                processed_ids = set(); count = 0
                # --- NEW DEBUG LOG ---
                print(f"DEBUG: About to start FOR loop over mal_data...")
                # --- END NEW DEBUG LOG ---
                for i, item in enumerate(mal_data):
                    print(f"    Processing item {i+1}/{len(mal_data)}...") # Log start of item processing
                    try: # Inner try for processing a single item
                        if isinstance(item, dict) and item.get('status') == 2:
                            title = item.get('anime_title'); anime_id = item.get('anime_id')
                            if title and anime_id is not None and anime_id not in processed_ids: # Explicit check for None ID
                                if not search or search.lower() in title.lower():
                                    eng_title = item.get('anime_title_eng')
                                    title_eng = eng_title if eng_title and eng_title.lower() != title.lower() else None
                                    anime_data_list.append({'title': title, 'title_eng': title_eng, 'anime_id': anime_id})
                                    processed_ids.add(anime_id); count += 1
                                    print(f"      SUCCESS: Appended '{title}' (ID: {anime_id}). Count: {count}") # Log success
                    except Exception as e_item:
                        print(f"    ERROR processing item {i+1}: {e_item}")
                        print(f"      Problematic Item Data (partial): {str(item)[:200]}")
                        continue # Continue to next item

                # This log should now always appear after the loop finishes or if mal_data was empty
                print(f"  MAL JSON Attempt - Loop finished. Extracted {count} completed titles matching filter.")
                if count > 0: mal_data_fetched_successfully = True

                # --- NEW DEBUG LOG ---
                print(f"DEBUG: Inner JSON processing try block finished.")
                # --- END NEW DEBUG LOG ---

            except json.JSONDecodeError as e_json:
                last_error_message = f"MAL JSON Attempt - Error decoding JSON response: {e_json}"
                print(f"  {last_error_message}"); print(f"      Response text that failed parsing: {response.text[:500]}")
            except Exception as e_loop: # Catch other errors during loop setup/processing
                 last_error_message = f"MAL JSON Attempt - Error during item processing: {e_loop}"
                 print(f"  {last_error_message}"); traceback.print_exc()

            # --- NEW DEBUG LOG ---
            print(f"DEBUG: Outer JSON 'if content_type_check:' block finished.")
            # --- END NEW DEBUG LOG ---
        else:
            last_error_message = f"MAL JSON endpoint did not return 'application/json'. Actual: {actual_content_type}"
            print(f"  MAL JSON Attempt - {last_error_message}")

    except requests.exceptions.HTTPError as e: last_error_message = f"MAL JSON Attempt - HTTP Error: {e}"; print(f"  {last_error_message}")
    except requests.exceptions.RequestException as e: last_error_message = f"MAL JSON Attempt - Network Error: {e}"; print(f"  {last_error_message}")
    except Exception as e: # Outer generic catch all
        last_error_message = f"MAL JSON Attempt - Unexpected error in OUTER try block: {e}"
        print(f"  {last_error_message}"); traceback.print_exc()

    # --- NEW DEBUG LOG ---
    print(f"DEBUG: Finished entire JSON fetch try/except block.")
    # --- END NEW DEBUG LOG ---


    # == Attempt 2: HTML Fallback ==
    if not mal_data_fetched_successfully:
        # ... (HTML fallback logic remains the same, including its own detailed logging) ...
        pass # Placeholder for brevity


    print(f"--- Finished MAL Fetch attempts ---")

    # --- Process MAL Results ---
    # ... (Deduplication logic using unique_anime_map remains the same) ...
    unique_anime_map = {item['title']: item for item in reversed(anime_data_list)}
    unique_anime_list_all = sorted(list(unique_anime_map.values()), key=lambda x: x['title']) # Rename to avoid confusion
    mal_fetch_time = time.time() - start_time
    print(f"\nFound {len(unique_anime_list_all)} unique MAL entries after fetch. (MAL Fetch took {mal_fetch_time:.2f}s)")

    # --- Pre-processing Filter ---
    # ... (Grouping and selecting shortest logic remains the same) ...
    print("Pre-processing MAL list to select shortest title per series group...")
    grouped_by_simplified = {}; # ... (grouping loop) ...
    for anime_info in unique_anime_list_all: # Use _all list here
        base_title_for_grouping = anime_info.get('title_eng') if anime_info.get('title_eng') else anime_info['title']
        simplified_term = simplify_title(base_title_for_grouping)
        if simplified_term not in grouped_by_simplified: grouped_by_simplified[simplified_term] = []
        grouped_by_simplified[simplified_term].append(anime_info)
    selected_anime_list = [] # This holds entries to search
    for simplified_term, group in grouped_by_simplified.items(): # ... (selection loop) ...
        if not group: continue; shortest_entry = min(group, key=lambda x: len(x['title'])); selected_anime_list.append(shortest_entry)
        if len(group) > 1: skipped_titles = [item['title'] for item in group if item['title'] != shortest_entry['title']]; print(f"  Group '{simplified_term}': Kept '{shortest_entry['title']}'. Skipped: {skipped_titles}")
    selected_anime_list.sort(key=lambda x: x['title'])
    print(f"Finished pre-processing. Selected {len(selected_anime_list)} titles to search.")
    # --- End Pre-processing ---

    if not selected_anime_list: # Check if selection resulted in empty list
         print("No anime titles remaining after filtering for shortest per group.")
         # Return appropriate message based on whether MAL fetch worked initially
         if not mal_data_fetched_successfully and len(anime_data_list)==0: # Check original list too
              return {"error": f"Could not fetch MAL data for '{username}'. Last status: {last_error_message}"}
         else: # MAL fetch worked, but filtering removed everything or no completed items matched
              return {"message": f"No completed anime found matching criteria after filtering for '{username}'.", "wallpapers": {}}


    # --- Search Wallhaven with Limited Concurrency ---
    # ... (Semaphore setup, task definition using process_anime_with_semaphore, gather - remains the same) ...
    # ... Uses selected_anime_list ...
    processed_titles_count = 0; semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT); print(f"\nStarting Wallhaven search for {len(selected_anime_list)} selected titles..."); print("-" * 30)
    async def fetch_title_wallhaven_prioritized(anime_info): # ... (function definition unchanged) ...
        original_title = anime_info['title']; english_title = anime_info.get('title_eng'); final_urls = []
        base_title_for_search = english_title if english_title else original_title; search_term_simplified = simplify_title(base_title_for_search); print(f"  -> Using search term: '{search_term_simplified}' (For: '{original_title}')")
        try: image_urls = await asyncio.to_thread(search_wallhaven, search_term_simplified, max_per_anime); final_urls = image_urls[:max_per_anime]; print(f"  => Found {len(final_urls)} wallpapers for '{original_title}'. (Limit: {max_per_anime})")
        except Exception as e: print(f"!!! Error WH search '{original_title}': {e}"); final_urls = []
        return original_title, final_urls # Return tuple (original title of selected, urls)
    async def process_anime_with_semaphore(sem, anime_data, index): # ... (function definition unchanged - calls prioritized fetch) ...
        nonlocal processed_titles_count; async with sem: print(f"\n({index+1}/{len(selected_anime_list)}) Processing: '{anime_data['title']}' (Sem acquired)"); result_pair = await fetch_title_wallhaven_prioritized(anime_data); processed_titles_count += 1; return result_pair
    tasks = [process_anime_with_semaphore(semaphore, anime_item, i) for i, anime_item in enumerate(selected_anime_list)]; print(f"Running {len(tasks)} tasks with concurrency limit {CONCURRENCY_LIMIT}..."); search_start_time = time.time()
    search_results_list = await asyncio.gather(*tasks); search_end_time = time.time(); print("-" * 30); print(f"Wallhaven search phase completed in {search_end_time - search_start_time:.2f}s.")

    # --- Post-Processing Filter is NO LONGER NEEDED ---

    # --- Return Final Results ---
    final_results = {title: urls for title, urls in search_results_list if urls} # Create dict from results
    total_time = time.time() - start_time
    print(f"\nFinished all processing. Found wallpapers for {len(final_results)} selected titles.")
    print(f"Total request time: {total_time:.2f}s")
    return {"wallpapers": final_results}

# --- To Run the App ---
# (Instructions remain the same)
