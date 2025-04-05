# main.py (Corrected Import Location)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import json
import time
import re
import asyncio # <--- MOVED IMPORT TO THE TOP
import traceback # <--- Import traceback for detailed error logging

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all origins
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods
    allow_headers=["*"], # Allows all headers
)

# Define standard Headers (Crucial for mimicking browser to wallpapers.com)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36" # Use a common, relatively recent UA
    ),
    # Headers observed from browser interactions with wallpapers.com API
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://wallpapers.com",
    "Referer": "https://wallpapers.com/", # Base referer, updated per search
}

# --- Title Simplification Function (UPDATED) ---
def simplify_title(title):
    """
    Simplifies an anime title by removing common season/part indicators
    and any text following them.
    e.g., "Bleach: Sennen Kessen-hen - Ketsubetsu-tan -" -> "Bleach" (if colon rule applied first)
    e.g., "Attack on Titan Season 3 Part 2" -> "Attack on Titan"
    e.g., "Kono Subarashii Sekai ni Shukufuku wo! 2" -> "Kono Subarashii Sekai ni Shukufuku wo!"
    """
    title = title.strip()

    # First, attempt simplification based on colon followed by space (common for subtitles)
    # This helps with titles like "Bleach: Thousand-Year Blood War" -> "Bleach"
    match_colon = re.search(r':\s', title)
    if match_colon:
        title = title[:match_colon.start()].strip()
        # Return early if colon simplification worked
        return title

    # If no colon simplification, remove common sequel indicators and following text
    # Regex looks for common indicators (\b ensures word boundaries)
    # Includes Season, Part, Cour, Movies?, Specials?, OVA?, common numbers (like 2, 3) etc.
    cleaned_title = re.split(
        r'\s+\b(?:Season|Part|Cour|Movies?|Specials?|OVAs?|Partie|Saison|Staffel|The Movie|Movie|Film|\d{1,2})\b',
        title,
        maxsplit=1, # Split only on the first occurrence
        flags=re.IGNORECASE
    )[0]

    # Optional: Remove trailing punctuation often left after splitting
    cleaned_title = re.sub(r'\s*[:\-]\s*$', '', cleaned_title).strip()

    # Optional: Handle simple cases like "Title 2" -> "Title" if not caught above
    if re.match(r'.+\s+\d+$', cleaned_title):
         cleaned_title = re.split(r'\s+\d+$', cleaned_title)[0].strip()

    return cleaned_title if cleaned_title else title # Return original if cleaning results in empty string


# --- Wallpaper Search Function (wallpapers.com - Unchanged from your provided code) ---
# WARNING: This function relies on scraping and undocumented internal API calls.
# It is FRAGILE and may break without warning if wallpapers.com changes its website structure or API.
# Rate limiting (429 errors) is also a significant possibility.
def search_wallpapers_com(title, max_results):
    """
    Searches wallpapers.com using its internal API and scrapes detail pages.
    WARNING: Relies on undocumented internal API - may break easily.
    """
    print(f"[wallpapers.com] Searching for: '{title}' (using simplified title)")
    image_urls = []
    search_api_url = "https://wallpapers.com/api/search"
    base_url = "https://wallpapers.com"

    # Payload for the internal API POST request
    payload = {
        'term': title,
        'page': 1,
        'per_page': max_results * 2, # Fetch more initially in case some detail pages fail
        'lazy': 'true'
    }
    # Use a copy of headers and set specific Referer for the API call
    request_headers = HEADERS.copy()
    request_headers['Referer'] = f"https://wallpapers.com/search/{quote_plus(title)}"

    try:
        # --- Step 1: Call the Search API (POST request) ---
        print(f"[wallpapers.com] Calling API: {search_api_url} with term '{title}'")
        time.sleep(1.5) # Slightly increased delay before API call
        response = requests.post(search_api_url, data=payload, headers=request_headers, timeout=20) # Increased timeout
        response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
        api_data = response.json()

        if not api_data.get('success') or 'list' not in api_data:
            print(f"[wallpapers.com] API did not return success or list HTML for '{title}'. Response: {api_data}")
            return []

        # --- Step 2: Parse the HTML snippet returned by API ---
        html_snippet = api_data.get('list', '')
        if not html_snippet:
            print(f"[wallpapers.com] API returned empty list HTML for '{title}'.")
            return []

        soup = BeautifulSoup(html_snippet, 'html.parser')
        # Find links that likely lead to wallpaper detail pages
        detail_page_links = soup.select('a[href^="/picture/"]')
        if not detail_page_links:
             print(f"[wallpapers.com] No '/picture/' links found in API response HTML for '{title}'.")
             return []

        print(f"[wallpapers.com] Found {len(detail_page_links)} potential detail page links via API for '{title}'.")

        # --- Step 3: Visit Detail Pages (Scraping) ---
        fetched_count = 0
        for link_tag in detail_page_links:
            if len(image_urls) >= max_results:
                print(f"[wallpapers.com] Reached max results ({max_results}) for '{title}'.")
                break

            relative_url = link_tag.get('href')
            if not relative_url:
                continue

            detail_page_url = base_url + relative_url
            fetched_count += 1
            print(f"[wallpapers.com] ({fetched_count}/{len(detail_page_links)}) Fetching detail page: {detail_page_url}")

            try:
                time.sleep(1.8) # Increased delay before scraping each detail page
                # Use simpler headers for scraping, Referer from API call might be useful
                detail_headers = {
                    "User-Agent": HEADERS["User-Agent"],
                    "Referer": search_api_url # Referer indicating we came from the search API page
                 }
                wp_response = requests.get(detail_page_url, headers=detail_headers, timeout=15) # Increased timeout

                if wp_response.status_code != 200:
                    print(f"[wallpapers.com] HTTP Error {wp_response.status_code} fetching detail page {detail_page_url}")
                    if wp_response.status_code == 429:
                        print(">>> Received 429 (Too Many Requests) on detail page. Stopping search for this title. Consider increasing delays.")
                        break # Stop processing this anime title if rate limited
                    continue # Skip this detail page on other errors

                wp_soup = BeautifulSoup(wp_response.text, 'html.parser')
                # Find the specific download link element
                download_link = wp_soup.select_one('a.download-original[href]') # Ensure href exists

                if download_link:
                    full_img_url = download_link['href']
                    # Ensure the URL is absolute
                    if full_img_url.startswith('/'):
                        full_img_url = base_url + full_img_url

                    if full_img_url.startswith("http"):
                        # Basic check to avoid obviously wrong URLs (though content type check would be better)
                        if any(ext in full_img_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                             image_urls.append(full_img_url)
                             print(f"  -> Found valid image URL.")
                        # else: # Optional: Log if URL doesn't look like an image
                        #    print(f"[wallpapers.com] Extracted URL doesn't look like image: {full_img_url}")
                    else:
                        print(f"[wallpapers.com] Skipping invalid extracted relative URL: {full_img_url}")
                # else: # Reduce logging verbosity
                    # print(f"[wallpapers.com] Could not find 'a.download-original' link on detail page {detail_page_url}")

            except requests.exceptions.Timeout:
                 print(f"[wallpapers.com] Timeout fetching detail page {detail_page_url}")
            except requests.exceptions.RequestException as e_wp:
                print(f"[wallpapers.com] Network Error fetching detail page {detail_page_url}: {e_wp}")
            except Exception as e_detail:
                print(f"[wallpapers.com] Error processing detail page {detail_page_url}: {e_detail}")

        print(f"[wallpapers.com] Added {len(image_urls)} wallpapers for '{title}' (checked {fetched_count} detail pages).")
        return image_urls

    except requests.exceptions.HTTPError as e_api_http:
        print(f"[wallpapers.com] HTTP Error calling search API for '{title}': {e_api_http}")
        # Log response body if available and useful (e.g., for non-JSON errors)
        try:
            print(f"[wallpapers.com] API Response Body: {e_api_http.response.text[:500]}") # Log beginning of response
        except: pass
        if e_api_http.response.status_code == 429:
            print(">>> Received 429 (Too Many Requests) on API call. Skipping this title.")
        return [] # Return empty list on HTTP error
    except requests.exceptions.Timeout:
        print(f"[wallpapers.com] Timeout calling search API for '{title}'")
        return []
    except requests.exceptions.RequestException as e_api:
        print(f"[wallpapers.com] Network Error calling search API for '{title}': {e_api}")
        return []
    except json.JSONDecodeError as e_json:
         print(f"[wallpapers.com] Error decoding JSON response from API for '{title}': {e_json}")
         print(f"[wallpapers.com] API Response Text: {response.text[:500]}") # Log the text that failed to parse
         return []
    except Exception as e_general:
        # Catch any other unexpected errors during the search process
        print(f"[wallpapers.com] Unexpected error during search for '{title}': {e_general}")
        traceback.print_exc() # Print full traceback for debugging
        return []


@app.get("/wallpapers")
async def get_wallpapers(username: str, search: str = None, max_per_anime: int = 3):
    """
    Fetches completed anime for a MAL user, simplifies titles (removing Season/Part etc.),
    and finds wallpapers using the wallpapers.com scraping function.
    """
    anime_titles = []
    mal_data_fetched_successfully = False
    last_error_message = "Unknown error during MAL fetch." # Placeholder
    response = None # Define response variable outside try block

    # --- Fetch and Parse MAL Data ---
    # Attempt 1: Modern JSON endpoint
    mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0&order=1"
    print(f"Attempt 1: Fetching MAL data for {username} from JSON endpoint: {mal_json_url}")
    try:
        mal_fetch_headers = {"User-Agent": HEADERS["User-Agent"]}
        # Use asyncio.to_thread for blocking requests call
        response = await asyncio.to_thread(requests.get, mal_json_url, headers=mal_fetch_headers, timeout=20)
        response.raise_for_status()
        if 'application/json' in response.headers.get('Content-Type', ''):
            mal_data = response.json()
            print(f"Successfully fetched JSON data directly from MAL endpoint.")
            for item in mal_data:
                if isinstance(item, dict) and item.get('status') == 2: # status 2 = Completed
                    title = item.get('anime_title')
                    if title:
                        # Apply optional text search filter here
                        if not search or search.lower() in title.lower():
                            anime_titles.append(title)
            mal_data_fetched_successfully = True
            print(f"Found {len(anime_titles)} completed titles matching filter (if any).")
        else:
            last_error_message = f"JSON endpoint did not return JSON. Content-Type: {response.headers.get('Content-Type')}"
            print(last_error_message)
            print(f"Response text: {response.text[:200]}")

    except requests.exceptions.HTTPError as e:
        last_error_message = f"Attempt 1 Failed (JSON endpoint): HTTP Error fetching MAL data for {username}: {e}"
        print(last_error_message)
        if e.response.status_code == 400 or e.response.status_code == 404:
             print(">>> MAL API returned 400/404, likely invalid username or private list.")
             return {"error": f"Could not fetch MAL data for '{username}'. Is the username correct and the list public?"}
    except requests.exceptions.RequestException as e:
        last_error_message = f"Attempt 1 Failed (JSON endpoint): Network Error fetching MAL data for {username}: {e}"
        print(last_error_message)
    except json.JSONDecodeError as e:
        last_error_message = f"Attempt 1 Failed (JSON endpoint): Error decoding JSON response: {e}"
        print(last_error_message)
        # Print response text if response object exists
        if response:
             print(f"Response text: {response.text[:200]}")
    except Exception as e:
        last_error_message = f"Attempt 1 Failed (JSON endpoint): An unexpected error occurred: {e}"
        print(last_error_message)
        traceback.print_exc() # Print full traceback

    # Attempt 2: Fallback to scraping embedded JSON from HTML page
    if not mal_data_fetched_successfully:
        mal_html_url = f"https://myanimelist.net/animelist/{username}?status=2"
        print(f"\nAttempt 2: Fetching MAL data for {username} from HTML page: {mal_html_url}")
        try:
            mal_fetch_headers = {"User-Agent": HEADERS["User-Agent"]}
            # Use asyncio.to_thread for blocking requests call
            response = await asyncio.to_thread(requests.get, mal_html_url, headers=mal_fetch_headers, timeout=25)
            response.raise_for_status()
            if 'text/html' in response.headers.get('Content-Type', ''):
                print(f"Fetched HTML from MAL (status code: {response.status_code}). Parsing embedded JSON.")
                soup = BeautifulSoup(response.text, "html.parser")
                # Find the table element that contains the data-items attribute
                list_table = soup.find('table', attrs={'data-items': True})
                if list_table and list_table.get('data-items'):
                    try:
                        mal_data = json.loads(list_table['data-items'])
                        print(f"Successfully parsed embedded JSON from MAL HTML.")
                        current_titles_count = len(anime_titles)
                        for item in mal_data:
                            if isinstance(item, dict) and item.get('status') == 2:
                                title = item.get('anime_title')
                                if title:
                                    if not search or search.lower() in title.lower():
                                        # Add only if not already added from JSON endpoint attempt
                                        if title not in anime_titles:
                                            anime_titles.append(title)
                        mal_data_fetched_successfully = True
                        print(f"Found {len(anime_titles) - current_titles_count} additional completed titles via HTML scraping.")
                    except json.JSONDecodeError as e:
                        last_error_message = f"Attempt 2 Failed: Error decoding JSON from data-items attribute: {e}"
                        print(last_error_message)
                    except Exception as e:
                        last_error_message = f"Attempt 2 Failed: An unexpected error occurred parsing embedded JSON: {e}"
                        print(last_error_message)
                        traceback.print_exc() # Print full traceback
                else:
                    last_error_message = "Attempt 2 Failed: Could not find 'data-items' attribute in the MAL HTML table."
                    print(last_error_message)
                    # Optionally log part of the HTML to see why it failed
                    # print(response.text[:1000])
            else:
                last_error_message = f"Attempt 2 Failed: HTML page did not return HTML. Content-Type: {response.headers.get('Content-Type')}"
                print(last_error_message)

        except requests.exceptions.HTTPError as e:
             last_error_message = f"Attempt 2 Failed (HTML page): HTTP Error fetching MAL data for {username}: {e}"
             print(last_error_message)
             # If even HTML fetch gives 404, it's likely user doesn't exist / private
             if e.response.status_code == 404:
                 print(">>> MAL HTML page returned 404.")
                 return {"error": f"Could not fetch MAL data for '{username}'. Is the username correct and the list public?"}
        except requests.exceptions.RequestException as e:
            last_error_message = f"Attempt 2 Failed (HTML page): Network Error fetching MAL data for {username}: {e}"
            print(last_error_message)
        except Exception as e:
            last_error_message = f"Attempt 2 Failed (HTML page): An unexpected error occurred: {e}"
            print(last_error_message)
            traceback.print_exc() # Print full traceback

    # --- Process Results of MAL Fetching ---
    # Use set for uniqueness, then sort for consistent processing order
    unique_raw_titles = sorted(list(set(anime_titles)))
    print(f"\nIdentified {len(unique_raw_titles)} unique completed anime titles after all attempts.")

    if not mal_data_fetched_successfully and not unique_raw_titles:
         # If both attempts failed completely
         return {"error": f"Could not fetch MAL data for '{username}' after multiple attempts. Last error: {last_error_message}"}

    if not unique_raw_titles:
        # Handle case where MAL fetch succeeded but no titles found/matched search
        return {"message": f"No completed anime found for user '{username}' matching the criteria.", "wallpapers": {}}


    # --- Search wallpapers.com for Wallpapers ---
    results = {}
    processed_titles_count = 0

    # Pre-simplify all titles
    # Store mapping: {original_title: simplified_title}
    title_simplification_map = {raw_title: simplify_title(raw_title) for raw_title in unique_raw_titles}

    print(f"\nStarting wallpapers.com search for {len(unique_raw_titles)} titles (using simplified names)...")
    print("-" * 30) # Separator

    # Define the helper function inside get_wallpapers or ensure it can access necessary scope
    async def fetch_and_process_title(original_title):
        # Make processed_titles_count nonlocal if fetch_and_process_title is defined inside get_wallpapers
        # nonlocal processed_titles_count
        current_count = processed_titles_count + 1 # Use a local var for logging index to avoid race conditions if ever made concurrent
        simplified = title_simplification_map[original_title]

        print(f"\n({current_count}/{len(unique_raw_titles)}) Processing: '{original_title}'")
        if original_title != simplified:
            print(f"  -> Simplified to: '{simplified}' for search.")
        else:
            print(f"  -> Title kept as is for search.")

        # Call the potentially blocking search function in a separate thread
        try:
            # Pass the *simplified* title to the search function
            image_urls = await asyncio.to_thread(search_wallpapers_com, simplified, max_per_anime)
            if image_urls:
                # Store results using the *original* MAL title as the key
                return original_title, image_urls
            else:
                 print(f"  -> No wallpapers found for '{simplified}' on wallpapers.com.")
                 return original_title, [] # Return empty list if none found

        except Exception as e_search:
            print(f"!!! An unexpected error occurred during wallpapers.com search processing for '{original_title}' (simplified: '{simplified}'): {e_search}")
            traceback.print_exc() # Print full traceback
            return original_title, [] # Return empty list on error for this title

    # Run the searches sequentially to be kinder to the server and avoid rate limits
    search_results_list = []
    for title in unique_raw_titles:
        result_pair = await fetch_and_process_title(title)
        search_results_list.append(result_pair)
        processed_titles_count += 1 # Increment counter after processing
        if processed_titles_count < len(unique_raw_titles):
             print(f"--- Delaying before next title ({2.5}s) ---")
             await asyncio.sleep(2.5) # Add delay between processing each ANIME TITLE


    # Process results: Filter out titles with no wallpapers found
    results = {title: urls for title, urls in search_results_list if urls}

    print("-" * 30) # Separator
    print(f"\nFinished processing all titles.")
    print(f"Returning results for {len(results)} anime with wallpapers found.")
    return {"wallpapers": results} # Return the final dictionary


# --- To Run the App ---
# 1. Save this code as main.py
# 2. Install necessary libraries:
#    pip install fastapi "uvicorn[standard]" requests beautifulsoup4 httpx # httpx might not be strictly needed now
# 3. Run from terminal in the same directory as the file:
#    uvicorn main:app --reload --host 0.0.0.0 --port 8080 # Example using different port
