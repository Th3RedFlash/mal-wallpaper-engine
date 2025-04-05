from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/wallpapers")
def get_wallpapers(username: str, search: str = None, max_per_anime: int = 3):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120 Safari/537.36"
        )
    }

    mal_url = f"https://myanimelist.net/malappinfo.php?u={username}&type=anime"
    response = requests.get(mal_url, headers=headers)
    if response.status_code != 200:
        return {"error": "Could not fetch MAL data"}

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        return {"error": "Failed to parse MAL XML"}

    anime_titles = []
    for anime in root.findall("anime"):
        title = anime.find("series_title").text
        status = anime.find("my_status").text
        if status in ["1", "2", "6"]:  # Watching, Completed, Plan to Watch
            if not search or search.lower() in title.lower():
                anime_titles.append(title)

    results = {}

    for title in anime_titles:
        query = title.replace(" ", "+")
        wallhaven_url = (
            f"https://wallhaven.cc/search?q={query}&categories=001"
            "&purity=100&atleast=1920x1080&sorting=favorites"
        )

        try:
            html = requests.get(wallhaven_url, headers=headers, timeout=10).text
            soup = BeautifulSoup(html, "html.parser")
            thumbs = soup.select("figure > a.preview")
        except Exception as e:
            print(f"Error loading {title}: {e}")
            continue

        images = []

        for thumb in thumbs[:max_per_anime * 3]:
            try:
                wallpaper_page_url = thumb["href"]
                wp_html = requests.get(wallpaper_page_url, headers=headers, timeout=10).text
                wp_soup = BeautifulSoup(wp_html, "html.parser")
                full_img_tag = wp_soup.select_one("img#wallpaper")
                if full_img_tag:
                    full_img_url = full_img_tag.get("src")
                    check = requests.head(full_img_url, headers=headers, timeout=5)
                    if check.status_code == 200:
                        images.append(full_img_url)
                if len(images) >= max_per_anime:
                    break
            except Exception as e:
                print(f"Error checking image: {e}")
                continue

        if images:
            results[title] = images

    return results
