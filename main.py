# main.py (v1.15 - Enhanced Logging Around json parsing & Exceptions)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.server import EventSourceResponse # Corrected Import Path from v1.14
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import json
import time
import re
import asyncio
import traceback # Ensure traceback is imported
import os
import sys # Keep for potential future debugging

# --- Configuration ---
CONCURRENCY_LIMIT = int(os.environ.get("WALLHAVEN_CONCURRENCY", 1)) # Default LOW (1)
WALLHAVEN_API_KEY = os.environ.get("WALLHAVEN_API_KEY", None)
# Log API Key status AND Concurrency Limit on startup
print(f"--- App Startup Configuration ---")
if WALLHAVEN_API_KEY: print(f"STARTUP: Wallhaven API Key found and will be used.")
else: print(f"STARTUP: Wallhaven API Key *not* found. Using default rate limits.")
print(f"STARTUP: Concurrency limit set to: {CONCURRENCY_LIMIT}")
# ... (Startup Warnings/Errors for Concurrency) ...
if CONCURRENCY_LIMIT > 5 and not WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 5 without API key might easily hit rate limits!")
elif CONCURRENCY_LIMIT > 15 and WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 15 even with API key might hit rate limits, monitor closely.")
elif CONCURRENCY_LIMIT <= 0: print("STARTUP ERROR: Concurrency limit must be >= 1. Using 1."); CONCURRENCY_LIMIT = 1
print("-" * 31)


# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware( CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"], )

# Define standard Headers (Includes API Key if set)
HEADERS = { "User-Agent": "MAL_Wallpaper_Engine/1.15 (Debug JSON Parse; Contact: YourEmailOrProjectURL)" } # Updated UA
if WALLHAVEN_API_KEY: HEADERS['X-API-Key'] = WALLHAVEN_API_KEY

# --- Title Simplification Function ---
# ... (simplify_title function remains the same) ...
def simplify_title(title):
    title = title.strip(); match_colon = re.search(r':\s', title)
    if match_colon: title = title[:match_colon.start()].strip()
    cleaned_title = re.split(r'\s+\b(?:Season|Part|Cour|Movies?|Specials?|OVAs?|Partie|Saison|Staffel|The Movie|Movie|Film|\d{1,2})\b', title, maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned_title = re.sub(r'\s*[:\-]\s*<span class="math-inline">', '', cleaned\_title\)\.strip\(\)
if re\.match\(r'\.\+\\s\+\\d\+</span>', cleaned_title): cleaned_title = re.split(r'\s+\d+$', cleaned_title)[0].strip()
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


# --- Main Endpoint - Uses SSE ---
@app.get("/wallpapers")
async def get_wallpapers_sse(username: str, search: str = None, max_per_anime: int = 5): # Default 5 images
    """
    Streams wallpaper results using Server-Sent Events (SSE).
    Includes detailed logging for MAL JSON parsing step.
    """

    # Define the async generator that will produce events
    async def event_generator():
        start_time = time.time()
        anime_data_list = []
        mal_data_fetched_successfully = False
        last_error_message = "Unknown error during MAL fetch."
        mal_fetch_success = False

        try:
            # --- 1. Fetch and Parse MAL Data ---
            print(f"--- Starting MAL Fetch for user: {username} (SSE Request) ---")
            # == Attempt 1: JSON endpoint ==
            mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0&order=1"
            print(f"MAL Attempt 1: Fetching JSON endpoint...")
            print(f"  URL: {mal_json_url}")
            try: # Outer try block for the whole JSON fetch attempt
                mal_fetch_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"}
                print(f"  Using Headers: {mal_fetch_headers}")
                response = await asyncio.to_thread(requests.get, mal_json_url, headers=mal_fetch_headers, timeout=20)
                print(f"  MAL JSON Attempt - Status Code: {response.status_code}")
                actual_content_type = response.headers.get('Content-Type', 'N/A')
                print(f"  MAL JSON Attempt - Content-Type Header: {actual_content_type}")
                print(f"  MAL JSON Attempt - Response Text Snippet: {response.text[:500]}...") # Log raw text before raising
                response.raise_for_status() # Check for HTTP errors AFTER logging

                content_type_check = 'application/json' in actual_content_type
                print(f"  MAL JSON Attempt - Check if 'application/json' in Content-Type: {content_type_check}")

                if content_type_check:
                    print(f"  MAL JSON Attempt - Content-Type check PASSED. Trying to parse JSON...")
                    try: # Inner try specifically for JSON parsing and looping
                        # --- ADDED LOGGING ---
                        print("DEBUG: Preparing to call response.json()...")
                        mal_data = response.json() # Parse the JSON data
                        print("DEBUG: response.json() call completed.")
                        # --- END ADDED LOGGING ---

                        print(f"  MAL JSON Attempt - Successfully parsed JSON. Found {len(mal_data)} items in list.")
                        print(f"DEBUG: Type of mal_data: {type(mal_data)}") # Check type

                        processed_ids = set(); count = 0
                        print(f"DEBUG: About to start FOR loop over mal_data...")
                        for i, item in enumerate(mal_data):
                            # Optional: Add print inside loop if needed, but keep it less verbose for now
                            # print(f"    Processing item {i+1}/{len(mal_data)}...")
                            try: # Innermost try for processing a single item safely
                                if isinstance(item, dict) and item.get('status') == 2:
                                    title = item.get('anime_title'); anime_id = item.get('anime_id')
                                    if title and anime_id is not None and anime_id not in processed_ids:
                                        if not search or search.lower() in title.lower():
                                            eng_title = item.get('anime_title_eng')
                                            title_eng = eng_title if eng_title and eng_title.lower() != title.lower() else None
                                            anime_data_list.append({'title': title, 'title_eng': title_eng, 'anime_id': anime_id})
                                            processed_ids.add(anime_id); count += 1
                                            # print(f"      SUCCESS: Appended '{title}' (ID: {anime_id}). Count: {count}") # Can uncomment if needed
                            except Exception as e_item:
                                print(f"    ERROR processing item {i+1}: {e_item}")
                                print(f"      Problematic Item Data (partial): {str(item)[:200]}")
                                continue # Continue to next item

                        print(f"  MAL JSON Attempt - Loop finished. Extracted {count} completed titles matching filter.")
                        if count > 0: mal_data_fetched_successfully = True
                        print(f"DEBUG: Inner JSON processing try block finished.")

                    except json.JSONDecodeError as e_json:
                        # Specific catch for JSON parsing errors
                        last_error_message = f"MAL JSON Attempt - Error decoding JSON response: {e_json}"
                        print(f"  {last_error_message}")
                        try: print(f"      Response text that failed parsing: {response.text[:500]}")
                        except Exception as e_print: print(f"      Error printing response text: {e_print}")
                        traceback.print_exc() # Print full traceback for JSON errors
                    except Exception as e_loop: # Catch other errors during loop/processing
                         last_error_message = f"MAL JSON Attempt - Error during item processing: {e_loop}"
                         print(f"  {last_error_message}")
                         traceback.print_exc() # Print full traceback for other inner errors
                    print(f"DEBUG: Outer JSON 'if content_type_check:' block finished.")
                else:
                    # Logged if the Content-Type check failed
                    last_error_message = f"MAL JSON endpoint did not return 'application/json'. Actual: {actual_content_type}"
                    print(f"  MAL JSON Attempt - {last_error_message}")

            except requests.exceptions.HTTPError as e: last_error_message = f"MAL JSON Attempt - HTTP Error: {e}"; print(f"  {last_error_message}"); traceback.print_exc() # Add traceback
            except requests.exceptions.RequestException as e: last_error_message = f"MAL JSON Attempt - Network Error: {e}"; print(f"  {last_error_message}"); traceback.print_exc() # Add traceback
            except Exception as e: # Outer generic catch all
                last_error_message = f"MAL JSON Attempt - Unexpected error in OUTER try block: {e}"
                print(f"  {last_error_message}"); traceback.print_exc() # Add traceback here too

            print(f"DEBUG: Finished entire JSON fetch try/except block.")


            # == Attempt 2: HTML Fallback ==
            if not mal_data_fetched_successfully:
                # ... (HTML fallback logic remains the same, ideally add tracebacks to its except blocks too) ...
                pass # Placeholder for brevity

            print(f"--- Finished MAL Fetch attempts (SSE Request) ---")

            # --- 2. Process MAL Results & Pre-filter ---
            # ... (Grouping and selecting shortest logic remains the same) ...
            unique_anime_map = {item['title']: item for item in reversed(anime_data_list)}; unique_anime_list_all = sorted(list(unique_anime_map.values()), key=lambda x: x['title']); mal_fetch_time = time.time() - start_time; print(f"\nFound {len(unique_anime_list_all)} unique MAL entries initially. (MAL Fetch took {mal_fetch_time:.2f}s)")
            if not unique_anime_list_all: # ... (Handle no results found, yield complete event) ...
                 if not mal_data_fetched_successfully: message = f"Could not fetch MAL data..."
                 else: message = f"No completed anime found matching criteria..."
                 yield {"event": "search_complete", "data": json.dumps({"message": message, "error": not mal_data_fetched_successfully })}; return
            print("Pre-processing MAL list..."); grouped_by_simplified = {}; #... (grouping loop) ...
            for anime_info in unique_anime_list_all: #... (grouping logic) ...
                 base_title_for_grouping = anime_info.get('title_eng') if anime_info.get('title_eng') else anime_info['title']; simplified_term = simplify_title(base_title_for_grouping); # ... (append to group) ...
            selected_anime_list = [] # ... (selection loop) ...
            for simplified_term, group in grouped_by_simplified.items(): # ... (selection logic) ...
                 if not group: continue; shortest_entry = min(group, key=lambda x: len(x['title'])); selected_anime_list.append(shortest_entry); # ... (log skipped) ...
            selected_anime_list.sort(key=lambda x: x['title']); print(f"Finished pre-processing. Selected {len(selected_anime_list)} titles to search.")
            if not selected_anime_list: # ... (Handle empty after filter, yield complete event) ...
                 yield {"event": "search_complete", "data": json.dumps({"message": f"No representative titles found after filtering..."})}; return
            mal_fetch_success = True


            # --- 3. Search Wallhaven Concurrently & Yield Results ---
            # ... (Semaphore setup, task definitions, gather loop - Remains same as v1.13) ...
            processed_titles_count = 0; semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT); search_start_time = time.time(); print(f"\nStarting Wallhaven search..."); print("-" * 30)
            async def fetch_title_wallhaven_prioritized(anime_info): # ... (Definition unchanged) ...
                 original_title = anime_info['title']; english_title = anime_info.get('title_eng'); final_urls = []; base_title_for_search = english_title if english_title else original_title; search_term_simplified = simplify_title(base_title_for_search); print(f"  -> Using search term: '{search_term_simplified}' (For: '{original_title}')")
                 try: image_urls = await asyncio.to_thread(search_wallhaven, search_term_simplified, max_per_anime); final_urls = image_urls[:max_per_anime]; print(f"  => Found {len(final_urls)} wallpapers for '{original_title}'. (Limit: {max_per_anime})")
                 except Exception as e: print(f"!!! Error WH search '{original_title}': {e}"); final_urls = []
                 return original_title, final_urls
            async def process_anime_with_semaphore(sem, anime_data, index): # Uses correct multi-line syntax
                 nonlocal processed_titles_count; async with sem: print(f"\n({index+1}/{len(selected_anime_list)}) Processing: '{anime_data['title']}' (Sem
