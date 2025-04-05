from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
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
def get_wallpapers(max_per_anime: int = 3):
    # Temporary fixed anime list for testing (bypassing MAL)
    completed = [
        "Attack on Titan",
        "Naruto",
        "Demon Slayer",
        "Hunter x Hunter"
    ]

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
