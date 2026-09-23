"""Standalone character cache builder, no Discord bot/token needed.

Scrapes bluearchive.wiki's trivia table plus every character's image and
writes data/characters.csv, the same file the bot reads from at runtime
(see cogs/Birthday.py's get_trivia_df). Useful for building/refreshing the
cache without having to start the whole bot and wait for a slash command.

Run from anywhere, paths are resolved from this file's own location:

    venv\\Scripts\\python.exe build_cache.py
"""
import asyncio
import io
import logging
import os

import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
log = logging.getLogger("build_cache")

_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTORY = os.path.join(_BOT_DIR, "data")
CHARACTERS_CSV = os.path.join(DIRECTORY, "characters.csv")
TRIVIA_URL = "https://bluearchive.wiki/wiki/Characters_trivia_list"

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
CHARACTER_IMAGE_FETCH_DELAY = 0.3


async def fetch_html(browser, url: str) -> str:
    page = await browser.new_page(user_agent=BROWSER_USER_AGENT)
    try:
        try:
            await page.goto(url, wait_until="load", timeout=45000)
        except PlaywrightTimeoutError:
            log.warning(f"Timed out waiting for {url} to finish loading, using current page content anyway")
        html = await page.content()
        if len(html) < 2000:
            log.warning(f"Suspiciously short response ({len(html)} chars) fetching {url}, might be a bot-protection challenge page")
        return html
    finally:
        await page.close()


async def scrape_character_image(browser, url: str) -> str:
    html = await fetch_html(browser, url)
    soup = BeautifulSoup(html, "html.parser")
    character_images_div = soup.find("div", class_="character-images")
    image_element = character_images_div.find("img")
    return f"https:{image_element['src']}"


async def build() -> pd.DataFrame:
    log.info("Launching headless Chromium...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            log.info(f"Fetching trivia table from {TRIVIA_URL}...")
            html = await fetch_html(browser, TRIVIA_URL)
            df = pd.read_html(io.StringIO(html))[0]
            df = df.drop_duplicates(subset=["Japanese reading"]).reset_index(drop=True)

            total = len(df)
            log.info(f"Found {total} character(s), scraping each one's image...")

            image_urls = []
            for i, (_, row) in enumerate(df.iterrows(), start=1):
                url = f"https://bluearchive.wiki/wiki/{row['Character']}"
                try:
                    image_urls.append(await scrape_character_image(browser, url))
                except Exception as e:
                    log.warning(f"Failed to scrape image for {row['Japanese reading']} ({url}): {e}")
                    image_urls.append("")

                log.info(f"[{i}/{total}] {row['Japanese reading']}")
                await asyncio.sleep(CHARACTER_IMAGE_FETCH_DELAY)

            df["Image URL"] = image_urls
        finally:
            await browser.close()

    if not os.path.exists(DIRECTORY):
        os.makedirs(DIRECTORY)
    df.to_csv(CHARACTERS_CSV, index=False)
    log.info(f"Saved {len(df)} character(s) to {CHARACTERS_CSV}.")
    return df


if __name__ == "__main__":
    asyncio.run(build())
