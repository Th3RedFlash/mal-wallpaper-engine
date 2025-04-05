# main.py (v1.13 - Implements Server-Sent Events for Progressive Loading)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.server import EventSourceResponse # Import for SSE
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
CONCURRENCY_LIMIT = int(os.environ.get("WALLHAVEN_CONCURRENCY", 1)) # Keep default low
WALLHAVEN_API_KEY = os.environ.get("WALLHAVEN_API_KEY", None)
# ... (Startup Logging - unchanged) ...
print(f"--- App Startup Configuration ---")
if WALLHAVEN_API_KEY: print(f"STARTUP: Wallhaven API Key found.")
else: print(f"STARTUP: Wallhaven API Key *not* found.")
print(f"STARTUP: Concurrency limit set to: {CONCURRENCY_LIMIT}")
# ... (Warnings based on concurrency/key) ...
print("-" * 31)

app = FastAPI()
app.add_middleware( CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"], )
HEADERS = { "User-Agent": "MAL_Wallpaper_Engine/1.13 (SSE; Contact: YourEmailOrProjectURL)" }
if WALLHAVEN_API_KEY: HEADERS['X-API-Key'] = WALLHAVEN_API_KEY

# --- Title Simplification Function ---
# ... (simplify_title function unchanged) ...
def simplify_title(title):
    title = title.strip(); match_colon = re.search(r':\s', title)
    if match_colon: title = title[:match_colon.start()].strip()
    cleaned_title = re.split(r'\s+\b(?:Season|Part|Cour|Movies?|Specials?|OVAs?|Partie|Saison|Staffel|The Movie|Movie|Film|\d{1,2})\b', title, maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned_title = re.sub(r'\s*[:\-]\s*$', '', cleaned_title).strip()
    if re.match(r'.+\s+\d+$', cleaned_title): cleaned_title = re.split(r'\s+\d+$', cleaned_title)[0].strip()
    return cleaned_title if cleaned_title else title

# --- Wallpaper Search Function (Wallhaven.cc API - performs ONE search) ---
# ... (search_wallhaven function unchanged - still synchronous using requests) ...
def search_wallhaven(search_term, max_results_limit):
    # ... (same implementation as v1.12) ...
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


# --- Main Endpoint - NOW MODIFIED FOR SSE ---
@app.get("/wallpapers")
async def get_wallpapers_sse(username: str, search: str = None, max_per_anime: int = 5): # Renamed endpoint function slightly
    """
    Streams wallpaper results using Server-Sent Events (SSE).
    Fetches MAL list, pre-filters, searches Wallhaven concurrently.
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
            # This part still runs sequentially first to get the list of anime
            print(f"--- Starting MAL Fetch for user: {username} (SSE Request) ---")
            # == Attempt 1: JSON ==
            mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0&order=1"; print(f"MAL Attempt 1: Fetching JSON..."); # ... (print URL) ...
            try: # ... (Full JSON fetch logic with detailed logging - unchanged from v1.12) ...
                 # ... Populates anime_data_list ...
                 # ... Sets mal_data_fetched_successfully = True if count > 0 ...
                mal_fetch_headers = {"User-Agent": "Mozilla/5.0"}; response = await asyncio.to_thread(requests.get, mal_json_url, headers=mal_fetch_headers, timeout=20); # ... (logging) ...; response.raise_for_status()
                actual_content_type = response.headers.get('Content-Type', 'N/A'); content_type_check = 'application/json' in actual_content_type; print(f"  MAL JSON Attempt - Content-Type Check: {content_type_check}")
                if content_type_check: # ... (Full try/except block for parsing and looping - unchanged) ...
                    mal_data_fetched_successfully = True # Assume success if we got here and parsed/looped
                else: last_error_message = f"MAL JSON Non-JSON CT: {actual_content_type}"; print(f"  {last_error_message}")
            except Exception as e: last_error_message = f"MAL JSON Attempt Error: {e}"; print(f"  {last_error_message}")

            # == Attempt 2: HTML Fallback ==
            if not mal_data_fetched_successfully: # ... (Full HTML fallback logic - unchanged) ...
                 pass # Placeholder

            print(f"--- Finished MAL Fetch attempts (SSE Request) ---")

            # --- 2. Process MAL Results & Pre-filter ---
            unique_anime_map = {item['title']: item for item in reversed(anime_data_list)}
            unique_anime_list_all = sorted(list(unique_anime_map.values()), key=lambda x: x['title'])
            mal_fetch_time = time.time() - start_time
            print(f"\nFound {len(unique_anime_list_all)} unique MAL entries initially. (SSE Request - MAL Fetch took {mal_fetch_time:.2f}s)")

            if not unique_anime_list_all:
                 if not mal_data_fetched_successfully: message = f"Could not fetch MAL data for '{username}'. Last status: {last_error_message}"
                 else: message = f"No completed anime found matching criteria for '{username}'."
                 # Send a completion event with an error/message
                 yield {"event": "search_complete", "data": json.dumps({"message": message, "error": not mal_data_fetched_successfully })}
                 return # Stop the generator

            # --- Pre-processing Filter ---
            # ... (Grouping and selecting shortest logic - unchanged from v1.12) ...
            print("Pre-processing MAL list..."); grouped_by_simplified = {}; #... (grouping loop) ...
            for anime_info in unique_anime_list_all: #... (grouping logic) ...
                base_title_for_grouping = anime_info.get('title_eng') if anime_info.get('title_eng') else anime_info['title']; simplified_term = simplify_title(base_title_for_grouping)
                if simplified_term not in grouped_by_simplified: grouped_by_simplified[simplified_term] = []
                grouped_by_simplified[simplified_term].append(anime_info)
            selected_anime_list = [] # ... (selection loop) ...
            for simplified_term, group in grouped_by_simplified.items(): # ... (selection logic) ...
                if not group: continue; shortest_entry = min(group, key=lambda x: len(x['title'])); selected_anime_list.append(shortest_entry)
                # ... (logging skipped entries) ...
            selected_anime_list.sort(key=lambda x: x['title'])
            print(f"Finished pre-processing. Selected {len(selected_anime_list)} titles to search.")
            # --- End Pre-processing ---

            if not selected_anime_list:
                 yield {"event": "search_complete", "data": json.dumps({"message": f"No representative titles found after filtering for '{username}'."})}
                 return # Stop generator

            mal_fetch_success = True # Indicate MAL part succeeded

            # --- 3. Search Wallhaven Concurrently & Yield Results ---
            processed_titles_count = 0
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
            search_start_time = time.time()
            print(f"\nStarting Wallhaven search for {len(selected_anime_list)} selected titles (SSE - Concurrency: {CONCURRENCY_LIMIT}, Max/Anime: {max_per_anime})...")

            # This function performs the SINGLE prioritized search logic (unchanged)
            async def fetch_title_wallhaven_prioritized(anime_info):
                # ... (definition unchanged - returns tuple: original_title, final_urls) ...
                original_title = anime_info['title']; english_title = anime_info.get('title_eng'); final_urls = []
                base_title_for_search = english_title if english_title else original_title; search_term_simplified = simplify_title(base_title_for_search); print(f"  -> Using search term: '{search_term_simplified}' (For: '{original_title}')")
                try: image_urls = await asyncio.to_thread(search_wallhaven, search_term_simplified, max_per_anime); final_urls = image_urls[:max_per_anime]; print(f"  => Found {len(final_urls)} wallpapers for '{original_title}'. (Limit: {max_per_anime})")
                except Exception as e: print(f"!!! Error WH search '{original_title}': {e}"); final_urls = []
                return original_title, final_urls

            # Wrapper for semaphore and yielding results
            async def process_and_yield(sem, anime_data, index):
                nonlocal processed_titles_count
                original_title = anime_data['title'] # Get title for logging before acquire
                try:
                    async with sem:
                        print(f"\n({index+1}/{len(selected_anime_list)}) Processing: '{original_title}' (Sem acquired)")
                        # Perform the search for this anime
                        found_title, urls = await fetch_title_wallhaven_prioritized(anime_data)
                        processed_titles_count += 1
                        # If results were found, yield them immediately
                        if urls:
                            yield {
                                "event": "wallpaper_result",
                                "data": json.dumps({"title": found_title, "urls": urls})
                            }
                            # Optional: small sleep after yielding? Might not be needed.
                            # await asyncio.sleep(0.05)
                        # Else: no results found, do nothing, just proceed
                except Exception as e_proc:
                     # Log errors during processing but don't stop the whole stream
                     print(f"!!! ERROR processing '{original_title}': {e_proc}")
                     traceback.print_exc()
                     # Optionally yield an error event for this specific title
                     # yield {"event": "error_item", "data": json.dumps({"title": original_title, "error": str(e_proc)})}

            # Create and run tasks concurrently using asyncio.gather
            # Gather will wait for ALL tasks to complete before proceeding after the gather call
            # We need results yielded *as tasks complete* - gather doesn't do that directly when awaited inside generator.
            # Alternative: Create tasks and use asyncio.as_completed

            print(f"Creating {len(selected_anime_list)} search tasks...")
            tasks = [process_and_yield(semaphore, anime_item, i) for i, anime_item in enumerate(selected_anime_list)]

            # Process tasks as they complete and yield their results
            for task in asyncio.as_completed(tasks):
                # This loop yields None for tasks that don't yield results, need to handle that?
                # The yielding is inside process_and_yield, so await task will make it run and yield
                try:
                    # Awaiting the task ensures exceptions from process_and_yield are raised here if not caught inside
                    await task # This drives the process_and_yield function, which handles yielding events
                except Exception as e_task:
                    print(f"!!! Task completed with unexpected error: {e_task}")
                    # Optionally yield a general error event
                    # yield {"event": "error_general", "data": json.dumps({"error": str(e_task)})}


            search_end_time = time.time()
            print("-" * 30)
            print(f"Wallhaven search phase completed in {search_end_time - search_start_time:.2f}s.")

            # --- 4. Signal Completion ---
            total_time = time.time() - start_time
            print(f"\nFinished all processing (SSE). Processed {processed_titles_count} titles.")
            print(f"Total request time: {total_time:.2f}s")
            yield {"event": "search_complete", "data": json.dumps({"message": "Search finished.", "total_processed": processed_titles_count})}

        except Exception as e_main:
            # Catch unexpected errors in the main generator logic
            print(f"!!! UNEXPECTED ERROR IN SSE GENERATOR: {e_main}")
            traceback.print_exc()
            # Send an error event to the client
            yield {"event": "error_fatal", "data": json.dumps({"error": "An unexpected error occurred on the server."})}
        finally:
             print("SSE Generator finished.") # Log when generator exits


    # Return the EventSourceResponse, passing the generator function
    return EventSourceResponse(event_generator())

# --- To Run the App ---
# 1. Install SSE library: pip install sse-starlette
# 2. Set Environment Variables in Render (WALLHAVEN_API_KEY, WALLHAVEN_CONCURRENCY=1 initially)
# 3. Run: uvicorn main:app --reload --host 0.0.0.0 --port 8080
