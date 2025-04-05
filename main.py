# main.py (v1.6 - Added Detailed MAL Fetch Logging)

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
CONCURRENCY_LIMIT = int(os.environ.get("WALLHAVEN_CONCURRENCY", 3)) # Default LOW (3)
WALLHAVEN_API_KEY = os.environ.get("WALLHAVEN_API_KEY", None)
# Log status ONCE on startup
if WALLHAVEN_API_KEY: print(f"STARTUP: Wallhaven API Key found. Concurrency Limit: {CONCURRENCY_LIMIT}")
else: print(f"STARTUP: Wallhaven API Key *not* found. Using default rate limits. Concurrency Limit: {CONCURRENCY_LIMIT}")
if CONCURRENCY_LIMIT > 5 and not WALLHAVEN_API_KEY: print("STARTUP WARNING: Concurrency > 5 without API key may cause rate limits!")

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware( CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"], )

# Define standard Headers (Includes API Key if set)
HEADERS = { "User-Agent": "MAL_Wallpaper_Engine/1.6 (Debug MAL Fetch; Contact: YourEmailOrProjectURL)" }
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
def search_wallhaven(search_term, max_results_limit):
    # ... (search_wallhaven function remains the same) ...
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
async def get_wallpapers(username: str, search: str = None, max_per_anime: int = 3):
    start_time = time.time()
    anime_data_list = [] # Stores {'title': '...', 'title_eng': '...'}
    mal_data_fetched_successfully = False
    last_error_message = "Unknown error during MAL fetch."
    response = None # Define response variable outside try blocks

    # --- Fetch and Parse MAL Data ---
    print(f"--- Starting MAL Fetch for user: {username} ---")

    # == Attempt 1: Modern JSON endpoint ==
    mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0&order=1"
    print(f"MAL Attempt 1: Fetching JSON endpoint...")
    print(f"  URL: {mal_json_url}") # DEBUG LOG
    try:
        # Using a generic user-agent for MAL specifically
        mal_fetch_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"}
        print(f"  Using Headers: {mal_fetch_headers}") # DEBUG LOG
        response = await asyncio.to_thread(requests.get, mal_json_url, headers=mal_fetch_headers, timeout=20)

        # --- ADDED LOGGING ---
        print(f"  MAL JSON Attempt - Status Code: {response.status_code}")
        print(f"  MAL JSON Attempt - Response Text Snippet: {response.text[:500]}...") # Log first 500 chars
        # --- END ADDED LOGGING ---

        response.raise_for_status() # Check for HTTP errors AFTER logging status/text

        if 'application/json' in response.headers.get('Content-Type', ''):
            print(f"  MAL JSON Attempt - Content-Type is JSON. Parsing...") # DEBUG LOG
            mal_data = response.json()
            print(f"  MAL JSON Attempt - Successfully parsed JSON.") # DEBUG LOG
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
            print(f"  MAL JSON Attempt - Extracted {count} completed titles.") # DEBUG LOG
            if count > 0: mal_data_fetched_successfully = True # Mark success only if items were found
        else:
            last_error_message = f"MAL JSON endpoint did not return JSON. Content-Type: {response.headers.get('Content-Type')}"
            print(f"  MAL JSON Attempt - {last_error_message}") # DEBUG LOG

    except requests.exceptions.HTTPError as e:
        last_error_message = f"MAL JSON Attempt - HTTP Error: {e}"
        print(f"  {last_error_message}") # DEBUG LOG
        # Keep specific error handling for 400/404 if needed for immediate return
        # if e.response.status_code in [400, 404]: return {"error": f"MAL Error: {username} not found or list private?"}
    except requests.exceptions.RequestException as e:
        last_error_message = f"MAL JSON Attempt - Network Error: {e}"
        print(f"  {last_error_message}") # DEBUG LOG
    except json.JSONDecodeError as e:
        last_error_message = f"MAL JSON Attempt - Error decoding JSON response: {e}"
        print(f"  {last_error_message}") # DEBUG LOG
        # Already logging response text above
    except Exception as e:
        last_error_message = f"MAL JSON Attempt - Unexpected error: {e}"
        print(f"  {last_error_message}") # DEBUG LOG
        traceback.print_exc()


    # == Attempt 2: Fallback to scraping embedded JSON from HTML page ==
    if not mal_data_fetched_successfully:
        mal_html_url = f"https://myanimelist.net/animelist/{username}?status=2"
        print(f"\nMAL Attempt 2: Fetching HTML page...")
        print(f"  URL: {mal_html_url}") # DEBUG LOG
        try:
            mal_fetch_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"}
            print(f"  Using Headers: {mal_fetch_headers}") # DEBUG LOG
            response = await asyncio.to_thread(requests.get, mal_html_url, headers=mal_fetch_headers, timeout=25)

            # --- ADDED LOGGING ---
            print(f"  MAL HTML Attempt - Status Code: {response.status_code}")
            # Only log snippet if status code seems okay, otherwise error handled below
            if response.ok:
                 print(f"  MAL HTML Attempt - Response Text Snippet: {response.text[:1000]}...") # Log more for HTML
            # --- END ADDED LOGGING ---

            response.raise_for_status() # Check for HTTP errors AFTER logging status/text

            if 'text/html' in response.headers.get('Content-Type', ''):
                print(f"  MAL HTML Attempt - Content-Type is HTML. Parsing...") # DEBUG LOG
                soup = BeautifulSoup(response.text, "html.parser")
                list_table = soup.find('table', attrs={'data-items': True})
                if list_table and list_table.get('data-items'):
                    print("  MAL HTML Attempt - Found data-items attribute. Parsing JSON...") # DEBUG LOG
                    try:
                        mal_data = json.loads(list_table['data-items'])
                        print(f"  MAL HTML Attempt - Successfully parsed embedded JSON.") # DEBUG LOG
                        initial_count = len(anime_data_list)
                        # Rebuild processed IDs if Attempt 1 added some but failed overall
                        processed_ids = {item['anime_id'] for item in anime_data_list if 'anime_id' in item}
                        count = 0
                        for item in mal_data:
                             if isinstance(item, dict) and item.get('status') == 2:
                                title = item.get('anime_title'); anime_id = item.get('anime_id')
                                if title and (not anime_id or anime_id not in processed_ids):
                                     if not search or search.lower() in title.lower():
                                        eng_title = item.get('anime_title_eng')
                                        title_eng = eng_title if eng_title and eng_title.lower() != title.lower() else None
                                        anime_data_list.append({'title': title, 'title_eng': title_eng, 'anime_id': anime_id})
                                        if anime_id: processed_ids.add(anime_id); count += 1
                        print(f"  MAL HTML Attempt - Extracted {count} additional/unique titles.") # DEBUG LOG
                        if count > 0 : mal_data_fetched_successfully = True # Mark success if items found
                    except json.JSONDecodeError as e:
                        last_error_message = f"MAL HTML Attempt - Error decoding JSON from data-items attribute: {e}"
                        print(f"  {last_error_message}") # DEBUG LOG
                    except Exception as e:
                        last_error_message = f"MAL HTML Attempt - Error processing embedded JSON: {e}"
                        print(f"  {last_error_message}") # DEBUG LOG
                        traceback.print_exc()
                else:
                    last_error_message = "MAL HTML Attempt - Could not find 'data-items' attribute in the HTML table."
                    print(f"  {last_error_message}") # DEBUG LOG
            else:
                last_error_message = f"MAL HTML Attempt - Page did not return HTML. Content-Type: {response.headers.get('Content-Type')}"
                print(f"  {last_error_message}") # DEBUG LOG

        except requests.exceptions.HTTPError as e:
             last_error_message = f"MAL HTML Attempt - HTTP Error: {e}"
             print(f"  {last_error_message}") # DEBUG LOG
             # Log response text on error here too
             try: print(f"      Response Body: {e.response.text[:500]}")
             except: pass
        except requests.exceptions.RequestException as e:
            last_error_message = f"MAL HTML Attempt - Network Error: {e}"
            print(f"  {last_error_message}") # DEBUG LOG
        except Exception as e:
            last_error_message = f"MAL HTML Attempt - Unexpected error: {e}"
            print(f"  {last_error_message}") # DEBUG LOG
            traceback.print_exc()

    print(f"--- Finished MAL Fetch attempts ---") # DEBUG LOG

    # --- Process MAL Results (Deduplication) ---
    unique_anime_map = {item['title']: item for item in reversed(anime_data_list)}
    unique_anime_list = sorted(list(unique_anime_map.values()), key=lambda x: x['title'])
    mal_fetch_time = time.time() - start_time
    print(f"\nFound {len(unique_anime_list)} unique titles after all attempts. (MAL Fetch took {mal_fetch_time:.2f}s)")

    # --- Handle No Results Found ---
    if not unique_anime_list: # Check after both attempts are fully done
        # If MAL fetch genuinely failed vs. just finding 0 items
        if not mal_data_fetched_successfully:
            return {"error": f"Could not fetch MAL data for '{username}'. List private, invalid user, or MAL error? Last status: {last_error_message}"}
        else: # Fetch worked but list section is empty or filtered out
            return {"message": f"No completed anime found matching the criteria for '{username}'.", "wallpapers": {}}


    # --- Search Wallhaven with Limited Concurrency (Single Prioritized Search) ---
    processed_titles_count = 0
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    print(f"\nStarting Wallhaven search for {len(unique_anime_list)} titles (Concurrency: {CONCURRENCY_LIMIT}, Single Search Strategy)...")
    print("-" * 30)

    # Define the single search function (reverted logic)
    async def fetch_title_wallhaven_prioritized(anime_info):
        original_title = anime_info['title']; english_title = anime_info['title_eng']; final_urls = []
        base_title_for_generic = english_title if english_title else original_title
        search_term_simplified = simplify_title(base_title_for_generic)
        print(f"  -> Using search term: '{search_term_simplified}' (From: '{base_title_for_generic}')")
        try:
            image_urls = await asyncio.to_thread(search_wallhaven, search_term_simplified, max_per_anime)
            final_urls = image_urls[:max_per_anime]; print(f"  => Found {len(final_urls)} wallpapers for '{original_title}'.")
        except Exception as e: print(f"!!! Error during WH search processing for '{original_title}': {e}"); final_urls = []
        return original_title, final_urls, search_term_simplified # Return term used

    # Semaphore wrapper
    async def process_anime_with_semaphore(sem, anime_data, index):
        nonlocal processed_titles_count
        async with sem:
            print(f"\n({index+1}/{len(unique_anime_list)}) Processing: '{anime_data['title']}' (Sem acquired)")
            result_tuple = await fetch_title_wallhaven_prioritized(anime_data)
            processed_titles_count += 1; return result_tuple

    # Create and run tasks
    tasks = [process_anime_with_semaphore(semaphore, anime_item, i) for i, anime_item in enumerate(unique_anime_list)]
    print(f"Running {len(tasks)} tasks with concurrency limit {CONCURRENCY_LIMIT}...")
    search_start_time = time.time()
    search_results_list = await asyncio.gather(*tasks)
    search_end_time = time.time(); print("-" * 30)
    print(f"Wallhaven search phase completed in {search_end_time - search_start_time:.2f}s.")

    # --- Post-Processing Filter for Duplicates ---
    # ... (This filtering logic remains the same as the previous version) ...
    print("Filtering results to remove duplicates from title simplification...")
    final_results = {}; processed_simplified_terms = set(); skipped_count = 0
    title_to_info_map = {item['title']: item for item in unique_anime_list}
    for original_title, urls, simplified_term_used in search_results_list:
        if not urls: continue
        if simplified_term_used not in processed_simplified_terms:
            final_results[original_title] = urls; processed_simplified_terms.add(simplified_term_used)
        else: print(f"  Skipping results for '{original_title}' (term '{simplified_term_used}' already processed)."); skipped_count += 1
    print(f"Finished filtering. Kept {len(final_results)} entries, skipped {skipped_count}.")

    # --- Return Final Results ---
    total_time = time.time() - start_time
    print(f"\nFinished all processing. Found wallpapers for {len(final_results)} titles.")
    print(f"Total request time: {total_time:.2f}s")
    return {"wallpapers": final_results}

# --- To Run the App ---
# (Instructions remain the same - set Env Vars on Render, run with uvicorn)
