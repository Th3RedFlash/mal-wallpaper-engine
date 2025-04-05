@app.get("/wallpapers")
def get_wallpapers(max_per_anime: int = 3):
    completed = [
        "Attack on Titan",
        "Naruto",
        "Demon Slayer",
        "Hunter x Hunter"
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    }

    results = {}
    for title in completed:
        query = title.replace(" ", "+")
        wallhaven_url = f"https://wallhaven.cc/search?q={query}&categories=001&purity=100&atleast=1920x1080&sorting=favorites"
        html = requests.get(wallhaven_url, headers=headers).text
        soup = BeautifulSoup(html, "html.parser")
        thumbs = soup.select("figure > a.preview")
        images = []

        for thumb in thumbs[:max_per_anime * 2]:  # Search extra to filter bad links
            wallpaper_page_url = thumb["href"]
            wp_html = requests.get(wallpaper_page_url, headers=headers).text
            wp_soup = BeautifulSoup(wp_html, "html.parser")
            full_img_tag = wp_soup.select_one("img#wallpaper")
            if full_img_tag:
                full_img_url = full_img_tag.get("src")

                # HEAD request to check if image actually works
                try:
                    check = requests.head(full_img_url, headers=headers, timeout=5)
                    if check.status_code == 200:
                        images.append(full_img_url)
                except:
                    continue

            if len(images) >= max_per_anime:
                break

        if images:
            results[title] = images

    return results
