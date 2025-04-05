# main.py (Title Simplification + wallpapers.com)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import json
import time
import re # <--- Added import

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

# Define a standard User-Agent
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120 Safari/537.36" # Using a more recent Chrome version
    ),
     # wallpapers.com API might require specific headers, observed in browser:
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    # Origin and Referer might be important for API access
    "Origin": "https://wallpapers.com",
    "Referer": "https://wallpapers.com/",
}

# --- Title Simplification Function ---
def simplify_title(title):
    """
    Simplifies an anime title based on the colon rule:
    - 'Title: Subtitle' -> 'Title'
    - 'Title:Word Subtitle' -> 'Title:Word'
    - 'Title:Word' -> 'Title:Word'
    - 'Title' -> 'Title'
    """
    title = title.strip()
    match = re.search(r':', title)
    if match:
        colon_index = match.start()
        if colon_index + 1 >= len(title) or title[colon_index + 1] == ' ':
            return title[:colon_index].strip()
        else:
            next_space_index = title.find(' ', colon_index + 1)
            if next_space_index != -1:
                return title[:next_space_index].strip()
            else:
                return title
    else:
        return title

# --- Wallpaper Search Function (wallpapers.com) ---
def search_wallpapers_com(title, max_results):
    """
    Searches wallpapers.com using its internal API and scrapes detail pages.
    WARNING: Relies on undocumented internal API - may break easily.
    """
    print(f"[wallpapers.com] Searching for: '{title}'")
    image_urls = []
    search_api_url = "https://wallpapers.com/api/search"
    base_url = "https://wallpapers.com"

    payload = {
        'term': title, 'page': 1, 'per_page': max_results * 2, 'lazy': 'true'
    }
    # Use a copy of headers to potentially modify Referer per search
    request_headers = HEADERS.copy()
    request_headers['Referer'] = f"https://wallpapers.com/search/{quote_plus(title)}"

    try:
        # --- Step 1: Call the Search API ---
        time.sleep(1.0)
        response = requests.post(search_api_url, data=payload, headers=request_headers, timeout=15)
        response.raise_for_status()
        api_data = response.json()

        if not api_data.get('success') or 'list' not in api_data:
            print(f"[wallpapers.com] API did not return success or list HTML for '{title}'.")
            return []

        # --- Step 2: Parse the HTML snippet ---
        html_snippet = api_data.get('list', '')
        if not html_snippet:
             print(f"[wallpapers.com] API returned empty list HTML for '{title}'.")
             return []
        soup = BeautifulSoup(html_snippet, 'html.parser')
        detail_page_links = soup.select('a[href^="/picture/"]')
        print(f"[wallpapers.com] Found {len(detail_page_links)} potential results via API for '{title}'.")

        # --- Step 3: Visit Detail Pages ---
        fetched_count = 0
        for link_tag in detail_page_links:
            if len(image_urls) >= max_results: break
            relative_url = link_tag.get('href')
            if not relative_url: continue

            detail_page_url = base_url + relative_url
            fetched_count += 1
            try:
                time.sleep(1.0) # Increased delay
                # Use less specific headers for detail page scraping
                detail_headers = { "User-Agent": HEADERS["User-Agent"], "Referer": search_api_url}
                wp_response = requests.get(detail_page_url, headers=detail_headers, timeout=10)

                if wp_response.status_code != 200:
                     print(f"[wallpapers.com] HTTP Error {wp_response.status_code} fetching detail page {detail_page_url}")
                     if wp_response.status_code == 429:
                         print(">>> Received 429 (Too Many Requests). Stopping search for this title.")
                         break
                     continue

                wp_soup = BeautifulSoup(wp_response.text, 'html.parser')
                download_link = wp_soup.select_one('a.download-original')

                if download_link and download_link.get('href'):
                    full_img_url = download_link['href']
                    if full_img_url.startswith('/'): full_img_url = base_url + full_img_url
                    if full_img_url.startswith("http"):
                        image_urls.append(full_img_url)
                        # print(f"  -> Found image URL: {full_img_url[:50]}...") # Reduce logging verbosity
                    else:
                        print(f"[wallpapers.com] Skipping invalid extracted URL: {full_img_url}")
                # else: # Reduce logging verbosity
                #     print(f"[wallpapers.com] Could not find download link on detail page {detail_page_url}")

            except requests.exceptions.RequestException as e_wp:
                print(f"[wallpapers.com] Network Error fetching detail page {detail_page_url}: {e_wp}")
            except Exception as e_detail:
                print(f"[wallpapers.com] Error processing detail page {detail_page_url}: {e_detail}")

        print(f"[wallpapers.com] Added {len(image_urls)} wallpapers for '{title}' (checked {fetched_count} detail pages).")
        return image_urls

    except requests.exceptions.HTTPError as e_api_http:
        print(f"[wallpapers.com] HTTP Error calling search API for '{title}': {e_api_http}")
        if e_api_http.response.status_code == 429:
             print(">>> Received 429 (Too Many Requests) on API call. Skipping this title.")
        return []
    except requests.exceptions.RequestException as e_api:
        print(f"[wallpapers.com] Network Error calling search API for '{title}': {e_api}")
        return []
    except Exception as e_general:
        print(f"[wallpapers.com] Unexpected error during search for '{title}': {e_general}")
        return []


@app.get("/wallpapers")
def get_wallpapers(username: str, search: str = None, max_per_anime: int = 3):
    """
    Fetches completed anime for a MAL user and finds wallpapers on wallpapers.com.
    Uses title simplification based on colon rule.
    """
    anime_titles = []
    mal_data_fetched_successfully = False

    # --- Fetch and Parse MAL Data ---
    # (MAL Fetching Logic - Remains the Same as previous versions)
    # Attempt 1: Try the modern JSON data loading endpoint first
    mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0"
    print(f"Attempt 1: Fetching MAL data for {username} from JSON endpoint: {mal_json_url}")
    try:
        mal_fetch_headers = {"User-Agent": HEADERS["User-Agent"]} # Simpler headers for MAL
        response = requests.get(mal_json_url, headers=mal_fetch_headers, timeout=15)
        response.raise_for_status()
        if 'application/json' in response.headers.get('Content-Type', ''):
            mal_data = response.json()
            print(f"Successfully fetched JSON data directly from MAL endpoint.")
            for item in mal_data:
                if isinstance(item, dict) and item.get('status') == 2:
                    title = item.get('anime_title')
                    if title:
                        if not search or search.lower() in title.lower():
                            anime_titles.append(title)
            mal_data_fetched_successfully = True
        else:
            print(f"JSON endpoint did not return JSON. Content-Type: {response.headers.get('Content-Type')}")
    except requests.exceptions.RequestException as e:
        print(f"Attempt 1 Failed (JSON endpoint): Error fetching MAL data for {username}: {e}")
    except json.JSONDecodeError as e:
         print(f"Attempt 1 Failed (JSON endpoint): Error decoding JSON response: {e}")
    except Exception as e:
         print(f"Attempt 1 Failed (JSON endpoint): An unexpected error occurred: {e}")

    # Attempt 2: Fallback to scraping embedded JSON from HTML page if Attempt 1 failed
    if not mal_data_fetched_successfully:
        mal_html_url = f"https://myanimelist.net/animelist/{username}?status=2"
        print(f"\nAttempt 2: Fetching MAL data for {username} from HTML page: {mal_html_url}")
        try:
            mal_fetch_headers = {"User-Agent": HEADERS["User-Agent"]} # Simpler headers for MAL
            response = requests.get(mal_html_url, headers=mal_fetch_headers, timeout=15)
            response.raise_for_status()
            if 'text/html' in response.headers.get('Content-Type', ''):
                print(f"Fetched HTML from MAL (status code: {response.status_code}). Parsing embedded JSON.")
                soup = BeautifulSoup(response.text, "html.parser")
                list_table = soup.find('table', class_='list-table')
                if list_table and 'data-items' in list_table.attrs:
                    try:
                        mal_data = json.loads(list_table['data-items'])
                        print(f"Successfully parsed embedded JSON from MAL HTML.")
                        for item in mal_data:
                            if isinstance(item, dict) and item.get('status') == 2:
                                title = item.get('anime_title')
                                if title:
                                    if not search or search.lower() in title.lower():
                                        anime_titles.append(title)
                        mal_data_fetched_successfully = True
                    except json.JSONDecodeError as e:
                        print(f"Error decoding JSON from data-items attribute: {e}")
                    except Exception as e:
                        print(f"An unexpected error occurred parsing embedded JSON: {e}")
                else:
                    print("Could not find 'data-items' attribute in the MAL HTML table.")
            else:
                print(f"HTML page did not return HTML. Content-Type: {response.headers.get('Content-Type')}")
        except requests.exceptions.RequestException as e:
             print(f"Attempt 2 Failed (HTML page): Error fetching MAL data for {username}: {e}")
             if not mal_data_fetched_successfully:
                 return {"error": f"Could not fetch MAL data for '{username}' after multiple attempts. Last error: {e}"}
        except Exception as e:
             print(f"Attempt 2 Failed (HTML page): An unexpected error occurred: {e}")
             if not mal_data_fetched_successfully:
                 return {"error": f"An unexpected error occurred processing MAL data for '{username}'. Last error: {e}"}

    # --- Process Results of MAL Fetching ---
    raw_anime_titles = sorted(list(set(anime_titles))) # Get unique raw titles
    print(f"\nIdentified {len(raw_anime_titles)} unique completed anime titles.")
    if not raw_anime_titles:
         # Handle case where MAL fetch succeeded but no titles found/matched search
         if mal_data_fetched_successfully:
              return {"message": f"No completed anime found for user '{username}' matching the criteria.", "wallpapers": {}}
         else: # Handle case where MAL fetch failed entirely
              status_code = response.status_code if 'response' in locals() else 'N/A'
              return {"error": f"Failed to fetch or parse MAL data for '{username}'. Last status: {status_code}"}

    # --- Search wallpapers.com for Wallpapers ---
    results = {}
    processed_titles_count = 0
    # Simplify titles *before* iterating for search
    simplified_titles_map = {raw_title: simplify_title(raw_title) for raw_title in raw_anime_titles}

    print(f"\nStarting wallpapers.com search for {len(raw_anime_titles)} titles...")

    # Iterate using the original titles for the results dictionary keys
    for original_title in raw_anime_titles:
        processed_titles_count += 1
        simplified = simplified_titles_map[original_title]
        print(f"\n({processed_titles_count}/{len(raw_anime_titles)}) Processing: '{original_title}' -> Simplified: '{simplified}'")

        # Call the new search function
        try:
            # Pass the *simplified* title to the search function
            image_urls = search_wallpapers_com(simplified, max_per_anime)
            if image_urls:
                # Store results using the *original* MAL title as the key
                results[original_title] = image_urls

        except Exception as e_search:
             print(f"An unexpected error occurred during wallpapers.com search processing for '{original_title}': {e_search}")
             # Continue to the next title even if one fails

    print(f"\nFinished processing. Returning {len(results)} anime with wallpapers.")
    return {"wallpapers": results} # Keep the return structure simple


# --- To Run the App ---
# (Instructions remain the same)
# 1. Save this code as main.py
# 2. Install necessary libraries:
#    pip install fastapi "uvicorn[standard]" requests beautifulsoup4
# 3. Run from terminal in the same directory as the file:
#    uvicorn main:app --reload
# 4. Open your browser to http://127.0.0.1:8000/docs to test the API endpoint.
