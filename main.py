# main.py (Using Wallhaven.cc API with Multiple Title Search Attempts)

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

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
# ... (CORS middleware setup remains the same)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define standard Headers
HEADERS = {
    "User-Agent": "MAL_Wallpaper_Engine/1.1 (Contact: YourEmailOrProjectURL; Purpose: Fetching relevant wallpapers based on user MAL list)"
}

# --- Title Simplification Function (Same as before) ---
def simplify_title(title):
    """
    Simplifies an anime title by removing common season/part indicators
    and any text following them.
    """
    # ... (simplify_title function remains the same)
    title = title.strip()
    match_colon = re.search(r':\s', title)
    if match_colon:
        title = title[:match_colon.start()].strip()
        return title
    cleaned_title = re.split(
        r'\s+\b(?:Season|Part|Cour|Movies?|Specials?|OVAs?|Partie|Saison|Staffel|The Movie|Movie|Film|\d{1,2})\b',
        title,
        maxsplit=1,
        flags=re.IGNORECASE
    )[0]
    cleaned_title = re.sub(r'\s*[:\-]\s*$', '', cleaned_title).strip()
    if re.match(r'.+\s+\d+$', cleaned_title):
         cleaned_title = re.split(r'\s+\d+$', cleaned_title)[0].strip()
    return cleaned_title if cleaned_title else title

# --- Wallpaper Search Function (Wallhaven.cc API - performs ONE search) ---
def search_wallhaven(search_term, max_results_limit):
    """
    Performs a single search on Wallhaven.cc API for a given search term.
    Returns a list of image URLs found.
    """
    print(f"  [Wallhaven Search] Querying API for: '{search_term}'")
    image_urls = []
    search_url = "https://wallhaven.cc/api/v1/search"
    params = {
        'q': search_term,
        'categories': '010', # Anime
        'purity': '100',     # SFW
        'sorting': 'relevance',
        'order': 'desc',
        # 'atleast': '1920x1080', # Keep resolution filter commented out for broader results initially
    }

    try:
        # Delay before this specific API call
        time.sleep(1.5)

        response = requests.get(search_url, params=params, headers=HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()

        if data and 'data' in data and isinstance(data['data'], list):
            results_found = len(data['data'])
            print(f"    -> API returned {results_found} results.")
            count = 0
            for item in data['data']:
                # Stop if we conceptually have enough overall, although this function doesn't know the final target count
                # if count >= max_results_limit: break # This limit isn't very useful here, apply limit when combining
                if 'path' in item and isinstance(item['path'], str):
                    image_urls.append(item['path'])
                    count += 1
            print(f"    -> Extracted {count} wallpaper URLs.")
        else:
            print(f"    -> No 'data' array found or invalid response.")
        return image_urls

    except requests.exceptions.HTTPError as e_http:
        print(f"  [Wallhaven Search] HTTP Error searching for '{search_term}': {e_http}")
        if e_http.response.status_code == 429: print(">>> Rate limit likely hit!")
        return []
    except requests.exceptions.Timeout:
        print(f"  [Wallhaven Search] Timeout searching for '{search_term}'")
        return []
    except requests.exceptions.RequestException as e_req:
        print(f"  [Wallhaven Search] Network Error searching for '{search_term}': {e_req}")
        return []
    except json.JSONDecodeError as e_json:
        print(f"  [Wallhaven Search] Error decoding JSON response for '{search_term}': {e_json}")
        print(f"      Response text: {response.text[:200]}")
        return []
    except Exception as e_general:
        print(f"  [Wallhaven Search] Unexpected error during search for '{search_term}': {e_general}")
        traceback.print_exc()
        return []

# --- Main Endpoint ---
@app.get("/wallpapers")
async def get_wallpapers(username: str, search: str = None, max_per_anime: int = 3):
    """
    Fetches completed anime for a MAL user, attempts multiple title variations
    to find wallpapers using the Wallhaven.cc API.
    """
    # Stores dicts: {'title': main_title, 'title_eng': english_title_or_none}
    anime_data_list = []
    mal_data_fetched_successfully = False
    last_error_message = "Unknown error during MAL fetch."
    response = None

    # --- Fetch and Parse MAL Data ---
    # Attempt 1: Modern JSON endpoint
    mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0&order=1"
    print(f"Attempt 1: Fetching MAL data for {username} from JSON endpoint...")
    try:
        mal_fetch_headers = {"User-Agent": HEADERS["User-Agent"]}
        response = await asyncio.to_thread(requests.get, mal_json_url, headers=mal_fetch_headers, timeout=20)
        response.raise_for_status()
        if 'application/json' in response.headers.get('Content-Type', ''):
            mal_data = response.json()
            print(f"Successfully fetched JSON data from MAL endpoint.")
            processed_ids = set() # Keep track of processed anime IDs
            for item in mal_data:
                if isinstance(item, dict) and item.get('status') == 2:
                    title = item.get('anime_title')
                    anime_id = item.get('anime_id')
                    if title and anime_id not in processed_ids:
                        # Apply optional text search filter here FIRST
                        if not search or search.lower() in title.lower():
                            eng_title = item.get('anime_title_eng')
                            # Add if English title exists and is different from main title
                            title_eng = eng_title if eng_title and eng_title.lower() != title.lower() else None
                            anime_data_list.append({'title': title, 'title_eng': title_eng})
                            processed_ids.add(anime_id)
            mal_data_fetched_successfully = True
            print(f"Found {len(anime_data_list)} completed titles matching filter (if any) via JSON.")
        # ... (Error handling for JSON endpoint - same as before) ...
        else:
            last_error_message = f"JSON endpoint did not return JSON. CT: {response.headers.get('Content-Type')}"
            print(last_error_message); print(f"Response text: {response.text[:200]}")
    except requests.exceptions.HTTPError as e: # ... other except blocks ...
        last_error_message = f"Attempt 1 Failed (JSON): HTTP Error MAL {username}: {e}"
        print(last_error_message); # ... specific 400/404 handling ...
        if e.response.status_code in [400, 404]: return {"error": f"MAL Error: {username} not found or list private?"}
    except Exception as e: # Catch-all for JSON attempt
        last_error_message = f"Attempt 1 Failed (JSON): Unexpected error: {e}"
        print(last_error_message); traceback.print_exc()


    # Attempt 2: Fallback to scraping embedded JSON from HTML page
    if not mal_data_fetched_successfully: # Or maybe always run if results seem low? For now, only on failure.
        mal_html_url = f"https://myanimelist.net/animelist/{username}?status=2"
        print(f"\nAttempt 2: Fetching MAL data for {username} from HTML page...")
        try:
            mal_fetch_headers = {"User-Agent": HEADERS["User-Agent"]}
            response = await asyncio.to_thread(requests.get, mal_html_url, headers=mal_fetch_headers, timeout=25)
            response.raise_for_status()
            if 'text/html' in response.headers.get('Content-Type', ''):
                print(f"Fetched HTML from MAL. Parsing...")
                soup = BeautifulSoup(response.text, "html.parser")
                list_table = soup.find('table', attrs={'data-items': True})
                if list_table and list_table.get('data-items'):
                    try:
                        mal_data = json.loads(list_table['data-items'])
                        print(f"Successfully parsed embedded JSON from MAL HTML.")
                        initial_count = len(anime_data_list)
                        processed_ids = {item['anime_id'] for item in mal_data_list if 'anime_id' in item} # Rebuild processed IDs if needed
                        for item in mal_data:
                            if isinstance(item, dict) and item.get('status') == 2:
                                title = item.get('anime_title')
                                anime_id = item.get('anime_id') # Assuming ID is available here too
                                # Add only if title exists, matches filter, and not already added
                                if title and (not anime_id or anime_id not in processed_ids):
                                     if not search or search.lower() in title.lower():
                                        eng_title = item.get('anime_title_eng')
                                        title_eng = eng_title if eng_title and eng_title.lower() != title.lower() else None
                                        anime_data_list.append({'title': title, 'title_eng': title_eng, 'anime_id': anime_id}) # Store ID if available
                                        if anime_id: processed_ids.add(anime_id)
                        mal_data_fetched_successfully = True # Mark as success even if only HTML worked
                        print(f"Found {len(anime_data_list) - initial_count} additional/unique titles via HTML.")
                    # ... (Error handling for HTML parsing - same as before) ...
                    except json.JSONDecodeError as e: last_error_message = f"Attempt 2 Failed: Error decoding data-items: {e}"; print(last_error_message)
                    except Exception as e: last_error_message = f"Attempt 2 Failed: Error parsing embedded JSON: {e}"; print(last_error_message); traceback.print_exc()
                else: last_error_message = "Attempt 2 Failed: Could not find 'data-items' in MAL HTML."; print(last_error_message)
            # ... (Error handling for HTML fetch - same as before) ...
            else: last_error_message = f"Attempt 2 Failed: Page did not return HTML. CT: {response.headers.get('Content-Type')}"; print(last_error_message)
        except requests.exceptions.HTTPError as e: # ... other except blocks ...
            last_error_message = f"Attempt 2 Failed (HTML): HTTP Error MAL {username}: {e}"
            print(last_error_message); # ... specific 404 handling ...
            if e.response.status_code == 404 and not mal_data_fetched_successfully: return {"error": f"MAL Error: {username} not found or list private?"}
        except Exception as e: # Catch-all for HTML attempt
             last_error_message = f"Attempt 2 Failed (HTML): Unexpected error: {e}"; print(last_error_message); traceback.print_exc()

    # --- Process Results of MAL Fetching ---
    # Use a dictionary to ensure uniqueness based on main title, preserving extracted data
    unique_anime_map = {item['title']: item for item in reversed(anime_data_list)} # Prioritize later entries if duplicates exist
    unique_anime_list = sorted(list(unique_anime_map.values()), key=lambda x: x['title']) # Sort by title

    print(f"\nIdentified {len(unique_anime_list)} unique completed anime titles after all attempts.")

    if not mal_data_fetched_successfully and not unique_anime_list:
         return {"error": f"Could not fetch MAL data for '{username}' after multiple attempts. Last error: {last_error_message}"}
    if not unique_anime_list:
        return {"message": f"No completed anime found for user '{username}' matching the criteria.", "wallpapers": {}}

    # --- Search Wallhaven.cc for Wallpapers (with multiple attempts per title) ---
    results = {}
    processed_titles_count = 0

    print(f"\nStarting Wallhaven.cc search for {len(unique_anime_list)} titles (trying multiple variations)...")
    print("-" * 30)

    async def fetch_and_process_title_wallhaven_multi(anime_info):
        """
        Orchestrates multiple search attempts for a single anime.
        anime_info is a dict: {'title': '...', 'title_eng': '...'}
        """
        nonlocal processed_titles_count
        processed_titles_count += 1
        original_title = anime_info['title']
        english_title = anime_info['title_eng'] # Could be None
        combined_urls = set() # Use a set to automatically handle duplicates

        print(f"\n({processed_titles_count}/{len(unique_anime_list)}) Processing: '{original_title}'")

        # --- Attempt 1: Simplified Main Title ---
        simplified_main = simplify_title(original_title)
        print(f"  Attempt 1: Searching with simplified title: '{simplified_main}'")
        urls1 = await asyncio.to_thread(search_wallhaven, simplified_main, max_per_anime)
        combined_urls.update(urls1)
        print(f"    > Found {len(urls1)}. Total unique: {len(combined_urls)}")

        # --- Attempt 2: Simplified English Title (if applicable) ---
        if len(combined_urls) < max_per_anime and english_title:
            simplified_eng = simplify_title(english_title)
            if simplified_eng.lower() != simplified_main.lower(): # Avoid searching same string twice
                print(f"  Attempt 2: Searching with simplified ENG title: '{simplified_eng}'")
                urls2 = await asyncio.to_thread(search_wallhaven, simplified_eng, max_per_anime)
                combined_urls.update(urls2)
                print(f"    > Found {len(urls2)}. Total unique: {len(combined_urls)}")
            else:
                print(f"  Attempt 2: Skipped (Simplified ENG same as simplified main)")

        # --- Attempt 3: Raw Main Title (if applicable) ---
        # Only try if simplification actually changed the title and we still need more results
        if len(combined_urls) < max_per_anime and original_title.lower() != simplified_main.lower():
             print(f"  Attempt 3: Searching with RAW main title: '{original_title}'")
             urls3 = await asyncio.to_thread(search_wallhaven, original_title, max_per_anime)
             combined_urls.update(urls3)
             print(f"    > Found {len(urls3)}. Total unique: {len(combined_urls)}")
        elif len(combined_urls) < max_per_anime:
             print(f"  Attempt 3: Skipped (Raw title same as simplified or already have enough results)")


        # Return the original title and the list of unique URLs found (up to max)
        final_urls = list(combined_urls)[:max_per_anime]
        if final_urls:
             print(f"  => Final results for '{original_title}': {len(final_urls)} wallpapers.")
        else:
             print(f"  => No wallpapers found for '{original_title}' after all attempts.")

        return original_title, final_urls

    # Run searches sequentially with delay between *anime*
    search_results_list = []
    for anime_item in unique_anime_list:
        result_pair = await fetch_and_process_title_wallhaven_multi(anime_item)
        search_results_list.append(result_pair)
        # Check processed_titles_count inside the loop if needed, but it's handled by nonlocal
        if processed_titles_count < len(unique_anime_list):
             # Increased delay between processing different anime because each might involve multiple API calls now
             delay = 3.0
             print(f"--- Delaying before next anime ({delay}s) ---")
             await asyncio.sleep(delay)

    # Filter results and return
    results = {title: urls for title, urls in search_results_list if urls}
    print("-" * 30)
    print(f"\nFinished processing all titles.")
    print(f"Returning results for {len(results)} anime with wallpapers found via Wallhaven multi-search.")
    return {"wallpapers": results}

# --- To Run the App ---
# (Instructions remain the same)
# uvicorn main:app --reload --host 0.0.0.0 --port 8080
