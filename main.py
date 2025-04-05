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
def get_wallpapers(username: str, max_per_anime: int = 3):
    mal_url = f"https://myanimelist.net/malappinfo.php?u={username}&type=anime"
    response = requests.get(mal_url)
    if response.status_code != 200:
        return {"error": "Could not fetch MAL data"}

    root = ET.fromstring(response.content)
    completed = []

    for anime in root.findall("anime"):
        if anime.find("my_status").text == "Completed":
            title = anime.find("series_title").text
            completed.append(title)

    results = {}
    for title in completed:
        query = title.replace(" ", "+")
        wallhaven_url = f"https://wallhaven.cc/search?q={query}&categories=001&purity=100&atleast=1920x1080&sorting=favorites"
        html = requests.get(wallhaven_url).text
        soup = BeautifulSoup(html, "html.parser")
        thumbs = soup.select("figure > a.preview")
        images = []
        for thumb in thumbs[:max_per_anime]:
            href = thumb["href"]
            images.append(href)
        if images:
            results[title] = images

    return results
