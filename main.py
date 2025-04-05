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
    completed = [
        "Attack on Titan",
        "Naruto",
        "Demon Slayer",
        "Hunter x Hunter"
    ]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120 Safari/537.36"
        )
    }

    results = {}

    for title in completed:
        try:
            query = title.replace(" ", "+")
            wallhaven_url = (
                f"https://wallhaven.cc/search?q={query}&categories=001"
                "&purity=100&atleast=1920x1080&sorting=favorites"
            )
            html = requests.get(wallhaven_url, headers=headers, timeout=10).text
            soup = BeautifulSoup(html, "html.parser")
            thumbs = soup.select
