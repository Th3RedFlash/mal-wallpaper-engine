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
                                if not search or
