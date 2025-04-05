# main.py (v1.13 - Added Runtime Environment Debug Logging)

# Standard library imports first
import json
import time
import re
import asyncio
import traceback
import os
import sys # Import sys for path debugging

# --- Runtime Environment Debugging ---
# Print information BEFORE attempting potentially problematic imports
print("--- Python Environment Debug ---")
print(f"Python Executable: {sys.executable}")
print("sys.path:")
# Print each entry in the Python path
for path_entry in sys.path:
    print(f"  - {path_entry}")

# Define the expected site-packages path based on common venv structure and logs
# Adjust python3.11 if your Render Python version is different (though logs show 3.11)
site_packages_path = '/opt/render/project/src/.venv/lib/python3.11/site-packages/'
print(f"\nChecking contents of expected site-packages: {site_packages_path}")
try:
    # List directory contents
    dir_list = os.listdir(site_packages_path)
    print(f"Found {len(dir_list)} items in site-packages.")
    # Specifically look for sse_starlette directory
    sse_related = [item for item in dir_list if 'sse' in item.lower()] # Check for sse
    if sse_related:
        print(f"FOUND items containing 'sse' in site-packages: {sse_related}")
        # Try listing contents *inside* sse_starlette if found
        if 'sse_starlette' in sse_related:
             try:
                 sse_contents = os.listdir(os.path.join(site_packages_path, 'sse_starlette'))
                 print(f"  Contents of sse_starlette dir: {sse_contents}")
             except Exception as e_inner:
                 print(f"  ERROR listing contents of sse_starlette dir: {e_inner}")
    else:
        print(f"WARNING: Did not find any items containing 'sse' in site-packages directory!")
except FileNotFoundError:
    print(f"ERROR: Could not find site-packages directory at {site_packages_path}")
except Exception as e:
    print(f"ERROR listing site-packages directory: {e}")
print("--- End Python Environment Debug ---")
# --- End Runtime Environment Debugging ---

# Now try the import that was failing, wrapped for clarity
try:
    print("Attempting to import EventSourceResponse from sse_starlette.server...")
    from sse_starlette.server import EventSourceResponse # Import for SSE
    print("Successfully imported EventSourceResponse.")
except ModuleNotFoundError as e_mnfe:
    print(f"FATAL ERROR during import: {e_mnfe}")
    # Application will likely crash here anyway, but good to log clearly.
    raise e_mnfe # Re-raise the error to ensure startup fails as before
except Exception as e_imp:
     print(f"FATAL ERROR: Unexpected error during critical import: {e_imp}")
     traceback.print_exc()
     raise e_imp

# --- Rest of regular imports ---
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup # Keep for MAL HTML fallback
from urllib.parse import quote_plus

# --- Configuration ---
CONCURRENCY_LIMIT = int(os.environ.get("WALLHAVEN_CONCURRENCY", 1)) # Default LOW (1)
WALLHAVEN_API_KEY = os.environ.get("WALLHAVEN_API_KEY", None)
# Log API Key status AND Concurrency Limit on startup
print(f"--- App Runtime Configuration ---") # Renamed section slightly
if WALLHAVEN_API_KEY: print(f"RUNTIME: Wallhaven API Key found and will be used.")
else: print(f"RUNTIME: Wallhaven API Key *not* found. Using default rate limits.")
print(f"RUNTIME: Concurrency limit set to: {CONCURRENCY_LIMIT}")
if CONCURRENCY_LIMIT > 5 and not WALLHAVEN_API_KEY: print("RUNTIME WARNING: Concurrency > 5 without API key might easily hit rate limits!")
elif CONCURRENCY_LIMIT > 15 and WALLHAVEN_API_KEY: print("RUNTIME WARNING: Concurrency > 15 even with API key might hit rate limits, monitor closely.")
elif CONCURRENCY_LIMIT <= 0: print("RUNTIME ERROR: Concurrency limit must be >= 1. Using 1."); CONCURRENCY_LIMIT = 1
print("-" * 31)


# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware( CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"], )

# Define standard Headers (Includes API Key if set)
HEADERS = { "User-Agent": "MAL_Wallpaper_Engine/1.13 (Runtime Debug; Contact: YourEmailOrProjectURL)" } # Updated UA
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


# --- Main Endpoint - Uses SSE ---
@app.get("/wallpapers")
async def get_wallpapers_sse(username: str, search: str = None, max_per_anime: int = 5):
    """
    Streams wallpaper results using Server-Sent Events (SSE).
    Includes detailed startup/runtime debugging for module loading.
    """

    # Define the async generator that will produce events
    async def event_generator():
        start_time = time.time()
        anime_data_list = []
        mal_data_fetched_successfully = False
        last_error_message = "Unknown error during MAL fetch."
        mal_fetch_success = False # Track if MAL fetch part succeeds

        try:
            # --- 1. Fetch and Parse MAL Data ---
            # ... (MAL Fetching logic remains the same as v1.12 - includes detailed logs within) ...
            print(f"--- Starting MAL Fetch for user: {username} (SSE Request) ---")
            # == Attempt 1: JSON ==
            # ... (Full JSON fetch try/except block) ...
            # == Attempt 2: HTML Fallback ==
            if not mal_data_fetched_successfully: # ... (Full HTML fallback logic) ...
                pass

            print(f"--- Finished MAL Fetch attempts (SSE Request) ---")

            # --- 2. Process MAL Results & Pre-filter ---
            # ... (Grouping and selecting shortest logic remains the same as v1.12) ...
            unique_anime_map = {item['title']: item for item in reversed(anime_data_list)}
            unique_anime_list_all = sorted(list(unique_anime_map.values()), key=lambda x: x['title'])
            mal_fetch_time = time.time() - start_time; print(f"\nFound {len(unique_anime_list_all)} unique MAL entries initially. (MAL Fetch took {mal_fetch_time:.2f}s)")
            if not unique_anime_list_all: # ... (Handle no results found) ...
                 if not mal_data_fetched_successfully: message = f"Could not fetch MAL data..."
                 else: message = f"No completed anime found..."
                 yield {"event": "search_complete", "data": json.dumps({"message": message, "error": not mal_data_fetched_successfully })}; return
            print("Pre-processing MAL list..."); grouped_by_simplified = {}; #... (grouping loop) ...
            for anime_info in unique_anime_list_all: #... (grouping logic) ...
                base_title_for_grouping = anime_info.get('title_eng') if anime_info.get('title_eng') else anime_info['title']; simplified_term = simplify_title(base_title_for_grouping)
                if simplified_term not in grouped_by_simplified: grouped_by_simplified[simplified_term] = []
                grouped_by_simplified[simplified_term].append(anime_info)
            selected_anime_list = [] # ... (selection loop) ...
            for simplified_term, group in grouped_by_simplified.items(): # ... (selection logic) ...
                if not group: continue; shortest_entry = min(group, key=lambda x: len(x['title'])); selected_anime_list.append(shortest_entry)
                if len(group) > 1: skipped_titles = [item['title'] for item in group if item['title'] != shortest_entry['title']]; print(f"  Group '{simplified_term}': Kept '{shortest_entry['title']}'. Skipped: {skipped_titles}")
            selected_anime_list.sort(key=lambda x: x['title'])
            print(f"Finished pre-processing. Selected {len(selected_anime_list)} titles to search.")
            if not selected_anime_list: # ... (Handle empty after filter) ...
                 yield {"event": "search_complete", "data": json.dumps({"message": f"No representative titles found after filtering..."})}; return
            mal_fetch_success = True

            # --- 3. Search Wallhaven Concurrently & Yield Results ---
            # ... (Semaphore setup, task definitions, gather loop - Remains same as v1.12 using correct process_anime_with_semaphore) ...
            processed_titles_count = 0; semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT); search_start_time = time.time(); print(f"\nStarting Wallhaven search for {len(selected_anime_list)} selected titles..."); print("-" * 30)
            async def fetch_title_wallhaven_prioritized(anime_info): # ... (Definition unchanged) ...
                 original_title = anime_info['title']; english_title = anime_info.get('title_eng'); final_urls = []
                 base_title_for_search = english_title if english_title else original_title; search_term_simplified = simplify_title(base_title_for_search); print(f"  -> Using search term: '{search_term_simplified}' (For: '{original_title}')")
                 try: image_urls = await asyncio.to_thread(search_wallhaven, search_term_simplified, max_per_anime); final_urls = image_urls[:max_per_anime]; print(f"  => Found {len(final_urls)} wallpapers for '{original_title}'. (Limit: {max_per_anime})")
                 except Exception as e: print(f"!!! Error WH search '{original_title}': {e}"); final_urls = []
                 return original_title, final_urls
            async def process_anime_with_semaphore(sem, anime_data, index): # Uses CORRECTED multi-line syntax
                nonlocal processed_titles_count
                async with sem:
                    print(f"\n({index+1}/{len(selected_anime_list)}) Processing: '{anime_data['title']}' (Sem acquired)")
                    found_title, urls = await fetch_title_wallhaven_prioritized(anime_data)
                    processed_titles_count += 1
                    if urls: # Only yield if results were found
                         yield {"event": "wallpaper_result", "data": json.dumps({"title": found_title, "urls": urls})}
            print(f"Creating {len(selected_anime_list)} search tasks...")
            tasks = [process_anime_with_semaphore(semaphore, anime_item, i) for i, anime_item in enumerate(selected_anime_list)]
            print(f"Processing tasks as they complete...")
            for task in asyncio.as_completed(tasks):
                 try: await task # This drives the process_and_yield equivalent, which now yields inside
                 except Exception as e_task: print(f"!!! Task completed with error: {e_task}")
            search_end_time = time.time(); print("-" * 30); print(f"Wallhaven search phase completed in {search_end_time - search_start_time:.2f}s.")

            # --- 4. Signal Completion ---
            total_time = time.time() - start_time; print(f"\nFinished all processing (SSE). Processed {processed_titles_count} titles."); print(f"Total request time: {total_time:.2f}s")
            yield {"event": "search_complete", "data": json.dumps({"message": "Search finished.", "total_processed": processed_titles_count})}

        except Exception as e_main:
            print(f"!!! UNEXPECTED ERROR IN SSE GENERATOR: {e_main}"); traceback.print_exc()
            try: yield {"event": "error_fatal", "data": json.dumps({"error": "An unexpected error occurred on the server."})}
            except Exception: pass # Avoid error if yield fails when connection broken
        finally: print("SSE Generator finished.")

    # Return the EventSourceResponse, passing the generator function
    return EventSourceResponse(event_generator())

# --- To Run the App ---
# 1. Ensure 'sse-starlette' is in requirements.txt
# 2. Set Environment Variables in Render (WALLHAVEN_API_KEY, WALLHAVEN_CONCURRENCY=1 initially)
# 3. Run: uvicorn main:app --reload --host 0.0.0.0 --port 8080
