# main.py (Complete Corrected Code)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import json # Import the json library
import time # Import time for potential delays

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for simplicity (adjust for production)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define a standard User-Agent
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120 Safari/537.36" # Use a plausible, common browser UA
    )
}

@app.get("/wallpapers")
def get_wallpapers(username: str, search: str = None, max_per_anime: int = 3):
    """
    Fetches completed anime for a MAL user and finds wallpapers on Wallhaven.
    """
    anime_titles = []
    mal_data_fetched_successfully = False # Flag to track if we got MAL data

    # --- Fetch and Parse MAL Data ---
    # Attempt 1: Try the modern JSON data loading endpoint first
    mal_json_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0"
    print(f"Attempt 1: Fetching MAL data for {username} from JSON endpoint: {mal_json_url}")

    try:
        response = requests.get(mal_json_url, headers=HEADERS, timeout=15)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        if 'application/json' in response.headers.get('Content-Type', ''):
            mal_data = response.json()
            print(f"Successfully fetched JSON data directly from MAL endpoint.")
            for item in mal_data:
                # Ensure item is a dictionary and check status (usually 2 for Completed)
                if isinstance(item, dict) and item.get('status') == 2:
                    title = item.get('anime_title')
                    if title:
                        if not search or search.lower() in title.lower():
                            anime_titles.append(title)
            mal_data_fetched_successfully = True # Mark as successful
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
            response = requests.get(mal_html_url, headers=HEADERS, timeout=15)
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
                        mal_data_fetched_successfully = True # Mark as successful
                    except json.JSONDecodeError as e:
                        print(f"Error decoding JSON from data-items attribute: {e}")
                        # Don't immediately return, maybe the profile exists but data is broken
                    except Exception as e:
                        print(f"An unexpected error occurred parsing embedded JSON: {e}")
                else:
                    print("Could not find 'data-items' attribute in the MAL HTML table.")
                    # Could add the less reliable direct scraping here as a last resort if needed
            else:
                print(f"HTML page did not return HTML. Content-Type: {response.headers.get('Content-Type')}")

        except requests.exceptions.RequestException as e:
             print(f"Attempt 2 Failed (HTML page): Error fetching MAL data for {username}: {e}")
             # If both attempts fail, return error
             if not mal_data_fetched_successfully:
                 return {"error": f"Could not fetch MAL data for '{username}' after multiple attempts. Last error: {e}"}
        except Exception as e:
             print(f"Attempt 2 Failed (HTML page): An unexpected error occurred: {e}")
             if not mal_data_fetched_successfully:
                 return {"error": f"An unexpected error occurred processing MAL data for '{username}'. Last error: {e}"}

    # --- Process Results of MAL Fetching ---
    # Remove duplicates just in case
    anime_titles = sorted(list(set(anime_titles)))

    print(f"\nIdentified {len(anime_titles)} unique completed anime titles.")
    if len(anime_titles) > 0:
        print(f"First few titles: {anime_titles[:10]}...") # Log first 10

    if not mal_data_fetched_successfully:
         # This case should ideally be caught by the returns within the try/except blocks,
         # but serves as a final fallback. Check if response object exists from last attempt.
         status_code = response.status_code if 'response' in locals() else 'N/A'
         return {"error": f"Failed to fetch or parse MAL data for '{username}'. Last status: {status_code}"}

    if not anime_titles:
        # User profile likely exists but no completed anime found (or matching search)
        return {"message": f"No completed anime found for user '{username}' matching the criteria.", "wallpapers": {}}


    # --- Search Wallhaven for Wallpapers ---
    results = {}
    print(f"\nStarting Wallhaven search for {len(anime_titles)} titles...")

    for title in anime_titles:
        # --- Prepare Wallhaven Query (Corrected Section) ---
        # 1. Create the search phrase with quotes for exact matching
        quoted_title_phrase = f'"{title}"'

        # 2. URL-encode the quoted phrase
        encoded_query = quote_plus(quoted_title_phrase)

        # 3. Construct the final URL
        # Refining Wallhaven query: categories=100 (Anime/Manga), purity=100 (SFW), sorting=favorites, order=desc
        # Adding resolution 'atleast' parameter for quality
        wallhaven_url = (
            f"https://wallhaven.cc/search?q={encoded_query}&categories=100"
            f"&purity=100&atleast=1920x1080&sorting=favorites&order=desc"
        )
        # --- End Corrected Section ---

        print(f"Searching Wallhaven for: '{title}' (using query: {encoded_query}) -> {wallhaven_url}")

        try:
            # Be respectful: add a small delay between requests
            time.sleep(0.5) # 0.5 second delay before search

            search_response = requests.get(wallhaven_url, headers=HEADERS, timeout=15)
            search_response.raise_for_status()
            search_soup = BeautifulSoup(search_response.text, "html.parser")

            thumbs = search_soup.select("figure > a.preview") # Get links to wallpaper pages
            print(f"Found {len(thumbs)} potential wallpapers for '{title}' on search page.")

            images = []
            fetched_count = 0
            # Only fetch details for up to max_per_anime * 2 potential thumbs
            for thumb in thumbs[:max_per_anime * 2]:
                if len(images) >= max_per_anime:
                    break # Stop once we have enough valid images

                wallpaper_page_url = thumb.get("href")
                if not wallpaper_page_url:
                    continue

                fetched_count += 1
                try:
                    time.sleep(0.3) # Small delay before fetching detail page
                    wp_response = requests.get(wallpaper_page_url, headers=HEADERS, timeout=10)
                    wp_response.raise_for_status()
                    wp_soup = BeautifulSoup(wp_response.text, "html.parser")

                    full_img_tag = wp_soup.select_one("img#wallpaper")
                    if full_img_tag:
                        full_img_url = full_img_tag.get("src")
                        if full_img_url:
                            # Basic check if URL seems valid
                            if full_img_url.startswith("http"):
                                images.append(full_img_url)
                            else:
                                print(f"Skipping invalid image URL: {full_img_url}")
                        else:
                            print(f"Could not extract src attribute from img#wallpaper on {wallpaper_page_url}")
                    else:
                        print(f"Could not find img#wallpaper on {wallpaper_page_url}")

                except requests.exceptions.RequestException as e_wp:
                    print(f"Error fetching/parsing wallpaper page {wallpaper_page_url} for '{title}': {e_wp}")
                except Exception as e_detail:
                     print(f"Error processing wallpaper detail for {title} from {wallpaper_page_url}: {e_detail}")
                 # Continue to the next thumbnail even if one fails

            if images:
                results[title] = images
                print(f"-> Added {len(images)} wallpapers for '{title}' (checked {fetched_count} thumbnails).")
            else:
                print(f"-> No valid wallpapers found for '{title}' after checking {fetched_count} thumbnails.")

        except requests.exceptions.RequestException as e_search:
            print(f"Error searching Wallhaven for '{title}': {e_search}")
        except Exception as e_general:
             print(f"An unexpected error occurred during Wallhaven search for '{title}': {e_general}")
        # Continue to the next title even if Wallhaven search fails

    print(f"\nFinished processing. Returning {len(results)} anime with wallpapers.")
    return {"wallpapers": results} # Return results nested under a key

# --- To Run the App ---
# 1. Save this code as main.py
# 2. Install necessary libraries:
#    pip install fastapi "uvicorn[standard]" requests beautifulsoup4
# 3. Run from terminal in the same directory as the file:
#    uvicorn main:app --reload
# 4. Open your browser to http://127.0.0.1:8000/docs to test the API endpoint.
