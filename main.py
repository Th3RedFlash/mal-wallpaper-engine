# main.py (Corrected Backend Code)

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

    # --- Fetch and Parse MAL Data ---
    mal_url = f"https://myanimelist.net/animelist/{username}/load.json?status=2&offset=0"
    # Note: Using the 'load.json' endpoint is often more reliable if available and public
    # If the above doesn't work reliably or requires auth, fall back to scraping the HTML page's JSON data:
    # mal_url = f"https://myanimelist.net/animelist/{username}?status=2"

    print(f"Attempting to fetch MAL data for {username} from: {mal_url}")

    try:
        response = requests.get(mal_url, headers=HEADERS, timeout=15) # Increased timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        # Check if we got JSON directly (preferred)
        if 'application/json' in response.headers.get('Content-Type', ''):
            mal_data = response.json()
            print(f"Successfully fetched JSON data directly from MAL endpoint.")
            # Structure of the JSON might vary, adjust keys accordingly
            # Assuming it's a list of dictionaries, each representing an anime
            for item in mal_data:
                 # Check if the status indicates completed (usually 2)
                 # The exact key for status might differ ('status', 'list_status', etc.)
                if item.get('status') == 2:
                    title = item.get('anime_title') # Adjust key if needed
                    if title:
                         if not search or search.lower() in title.lower():
                             anime_titles.append(title)

        # Fallback: If we got HTML, try to find the embedded JSON
        elif 'text/html' in response.headers.get('Content-Type', ''):
            print(f"Fetched HTML from MAL (status code: {response.status_code}). Parsing embedded JSON.")
            soup = BeautifulSoup(response.text, "html.parser")
            # Find the table that contains the data-items attribute
            list_table = soup.find('table', class_='list-table')

            if list_table and 'data-items' in list_table.attrs:
                try:
                    mal_data = json.loads(list_table['data-items'])
                    print(f"Successfully parsed embedded JSON from MAL HTML.")
                    # Iterate through the parsed JSON data
                    for item in mal_data:
                         # Check if the status indicates completed (status = 2)
                        if item.get('status') == 2:
                            # Extract the anime title (key might be 'anime_title' or similar)
                            title = item.get('anime_title')
                            if title:
                                # Apply optional search filter
                                if not search or search.lower() in title.lower():
                                    anime_titles.append(title)
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON from data-items attribute: {e}")
                    return {"error": "Could not parse anime list data from MAL page."}
            else:
                 print("Could not find the 'data-items' attribute in the MAL HTML.")
                 # As a last resort, try the original scraping method (less reliable)
                 print("Falling back to direct HTML element scraping (might be unreliable)...")
                 for item in soup.select("td.data.title.clearfix"):
                    title_tag = item.select_one("a.link.sort")
                    if title_tag:
                        title = title_tag.get_text(strip=True)
                        if title and title != "${ item.title_localized || item.anime_title }": # Avoid placeholders
                            if not search or search.lower() in title.lower():
                                anime_titles.append(title)

        else:
            print(f"Received unexpected content type from MAL: {response.headers.get('Content-Type')}")
            return {"error": f"Unexpected content type from MAL: {response.headers.get('Content-Type')}"}


    except requests.exceptions.RequestException as e:
        print(f"Error fetching MAL data for {username}: {e}")
        return {"error": f"Could not fetch MAL data: {e}"}
    except Exception as e:
         print(f"An unexpected error occurred during MAL processing: {e}")
         return {"error": f"An unexpected error occurred: {e}"}


    # Log parsed anime titles
    print(f"Parsed {len(anime_titles)} completed anime titles: {anime_titles[:10]}...") # Log first 10

    if not anime_titles:
        # Check if the user exists but has no completed anime vs profile not found
        if response.status_code == 200:
             return {"message": f"No completed anime found for user '{username}' matching the criteria.", "wallpapers": {}}
        else:
             return {"error": f"Could not fetch MAL data for '{username}'. Status: {response.status_code}"}

    # --- Search Wallhaven for Wallpapers ---
    results = {}
    print(f"\nStarting Wallhaven search for {len(anime_titles)} titles...")

    for title in anime_titles:
        query = quote_plus(title)  # URL encode the title
        # Refining Wallhaven query: categories=100 (Anime/Manga), purity=100 (SFW), sorting=favorites
        # Adding resolution 'atleast' parameter for quality
        wallhaven_url = (
            f"https://wallhaven.cc/search?q={quote_plus(f'"{title}"')}&categories=100" # Use quotes for exact phrase
            f"&purity=100&atleast=1920x1080&sorting=favorites&order=desc"
        )
        print(f"Searching Wallhaven for: '{title}' -> {wallhaven_url}")

        try:
            # Be respectful: add a small delay between requests to avoid overwhelming Wallhaven
            time.sleep(0.5) # 0.5 second delay

            search_response = requests.get(wallhaven_url, headers=HEADERS, timeout=15)
            search_response.raise_for_status()
            search_soup = BeautifulSoup(search_response.text, "html.parser")

            # Find preview links on the search results page
            thumbs = search_soup.select("figure > a.preview") # Get links to wallpaper pages
            print(f"Found {len(thumbs)} potential wallpapers for '{title}' on search page.")

            images = []
            count = 0
            # Only fetch details for up to max_per_anime * 2 potential thumbs to limit requests
            for thumb in thumbs[:max_per_anime * 2]:
                if count >= max_per_anime:
                    break # Stop once we have enough valid images

                wallpaper_page_url = thumb.get("href")
                if not wallpaper_page_url:
                    continue

                try:
                    # Add another small delay before fetching the wallpaper page
                    time.sleep(0.3)
                    wp_html = requests.get(wallpaper_page_url, headers=HEADERS, timeout=10).text
                    wp_soup = BeautifulSoup(wp_html, "html.parser")

                    # Find the actual wallpaper image tag
                    full_img_tag = wp_soup.select_one("img#wallpaper")
                    if full_img_tag:
                        full_img_url = full_img_tag.get("src")
                        if full_img_url:
                            # Optional: Check if image URL is accessible (can add overhead)
                            # check = requests.head(full_img_url, headers=HEADERS, timeout=5)
                            # if check.status_code == 200:
                            images.append(full_img_url)
                            count += 1
                            # else:
                            #     print(f"Image HEAD check failed for {full_img_url} (Status: {check.status_code})")
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
                print(f"-> Added {len(images)} wallpapers for '{title}'.")

        except requests.exceptions.RequestException as e_search:
            print(f"Error searching Wallhaven for '{title}': {e_search}")
        except Exception as e_general:
             print(f"An unexpected error occurred during Wallhaven search for '{title}': {e_general}")
        # Continue to the next title even if Wallhaven search fails

    print(f"\nFinished processing. Returning {len(results)} anime with wallpapers.")
    return {"wallpapers": results} # Return results nested under a key

# --- To Run the App ---
# Save this code as main.py
# Install necessary libraries:
# pip install fastapi uvicorn requests beautifulsoup4
# Run from terminal:
# uvicorn main:app --reload
