import asyncio
import io
import json
import os
from bs4 import BeautifulSoup
import datetime

# from datetime import datetime, timedelta
import discord
import pandas as pd
from discord.ext import commands, tasks
from discord import app_commands
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import logging

# bot.py runs from the bot/ folder, which is what ends up on sys.path (same reason
# "cogs.Birthday" resolves), so this is a plain top-level import, not a relative one.
import notion_client

log = logging.getLogger(__name__)

# Resolved from this file's own location (bot/cogs/Birthday.py) rather than the
# current working directory. Otherwise `cd bot && python bot.py` (what the
# README says) and `python bot/bot.py` from the repo root land on two different
# data/ folders depending on how the bot happens to be started, which is a very
# easy way to end up looking for characters.csv in the wrong place.
_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRECTORY = os.path.join(_BOT_DIR, "data")
CHANNEL = os.path.join(DIRECTORY, "set_channel.json")
CHARACTERS_CSV = os.path.join(DIRECTORY, "characters.csv")
TRIVIA_URL = "https://bluearchive.wiki/wiki/Characters_trivia_list"


class JsonChannelStore:
    """Original local-file storage for which channels have reminders enabled.
    Used when Notion isn't configured (see NotionChannelStore below)."""

    def __init__(self):
        self._channels: list[int] = []

    async def load(self) -> list[int]:
        try:
            with open(CHANNEL, "r") as f:
                self._channels = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            if not os.path.exists(DIRECTORY):
                os.makedirs(DIRECTORY)
            self._channels = []
        return list(self._channels)

    async def add(self, channel_id: int) -> None:
        self._channels.append(channel_id)
        self._save()

    async def remove(self, channel_id: int) -> None:
        if channel_id in self._channels:
            self._channels.remove(channel_id)
        self._save()

    def _save(self) -> None:
        if not os.path.exists(DIRECTORY):
            os.makedirs(DIRECTORY)
        with open(CHANNEL, "w") as f:
            json.dump(self._channels, f)


class NotionChannelStore:
    """Stores which channels have reminders enabled as pages in a Notion
    database instead of the local JSON file. See bot/notion_client.py."""

    def __init__(self):
        self._pages: dict[int, str] = {}  # channel_id -> Notion page id

    async def load(self) -> list[int]:
        self._pages = await notion_client.list_subscribed_channels()
        return list(self._pages.keys())

    async def add(self, channel_id: int) -> None:
        page_id = await notion_client.add_subscribed_channel(channel_id)
        self._pages[channel_id] = page_id

    async def remove(self, channel_id: int) -> None:
        page_id = self._pages.pop(channel_id, None)
        if page_id:
            await notion_client.remove_subscribed_channel(page_id)


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Politeness delay between per-character image requests when building the local
# cache from scratch (see _build_character_cache) - it's dozens of page loads in
# a row, spacing them out a bit is friendlier to the wiki.
CHARACTER_IMAGE_FETCH_DELAY = 0.3

utc = datetime.timezone.utc
time = datetime.time(hour=0, minute=0, tzinfo=utc)


class Birthday(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self._trivia_df = None

        # bluearchive.wiki's CDN 403s plain HTTP clients (tried a browser User-Agent,
        # tried cloudscraper, still blocked), so we drive an actual headless browser
        # instead. One browser instance is kept alive for the cog's lifetime rather
        # than launching one per request, launching is the slow part (~1-2s).
        self._playwright = None
        self._browser = None
        self._browser_lock = asyncio.Lock()

        # Guards _build_character_cache so two commands hitting get_trivia_df()
        # at the same time (e.g. the startup warmup and a command someone runs
        # a moment later) don't both kick off their own full scrape in parallel.
        # The second caller just waits for the first build to finish instead.
        self._cache_build_lock = asyncio.Lock()

        # Which channels have birthday reminders enabled. Stored in Notion when
        # NOTION_API_KEY / NOTION_DATABASE_ID_BIRTHDAY_CHANNELS are set, otherwise
        # falls back to the local data/set_channel.json file. Either way, loaded
        # once at startup by _warmup and kept in sync in memory on every toggle,
        # so normal operation doesn't need a round trip per reminder tick.
        if notion_client.is_configured():
            self._store = NotionChannelStore()
            log.info("Using Notion to store subscribed channels.")
        else:
            self._store = JsonChannelStore()
            log.info(
                "NOTION_API_KEY / NOTION_DATABASE_ID_BIRTHDAY_CHANNELS not set, "
                "falling back to data/set_channel.json for subscribed channels."
            )
        self.set_channel: list[int] = []
        self._channels_loaded = asyncio.Event()

        self.scheduled_birthday_reminder.start()
        # Warm the trivia cache once at startup so the first real interaction
        # (especially autocomplete, which only gets ~3s to respond) doesn't have
        # to pay for a browser launch + page load itself. Cog.__init__ runs inside
        # a running event loop (via setup_hook -> load_extension), so we can just
        # schedule this on it directly rather than going through client.loop, which
        # isn't guaranteed to be set up yet depending on when the cog is loaded.
        asyncio.create_task(self._warmup())

    async def cog_unload(self):
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def _warmup(self):
        await self.client.wait_until_ready()
        try:
            self.set_channel = await self._store.load()
            log.info(f"Loaded {len(self.set_channel)} subscribed channel(s).")
        except Exception as e:
            log.error(f"Failed to load subscribed channels on startup: {e}")
        finally:
            # Set this even on failure, an empty list is a safe default (no
            # reminders fire) and we don't want the reminder loop stuck waiting forever.
            self._channels_loaded.set()
        try:
            await self.get_trivia_df()
            log.info("Trivia table cache warmed up.")
        except Exception as e:
            log.error(f"Failed to warm up trivia cache on startup: {e}")

    async def _get_browser(self):
        async with self._browser_lock:
            if self._browser is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def _fetch_html(self, url: str) -> str:
        browser = await self._get_browser()
        page = await browser.new_page(user_agent=BROWSER_USER_AGENT)
        try:
            try:
                # "networkidle" is the strictest wait condition, and on some hosts
                # (seen on a VPS, not locally) background requests (ads/analytics)
                # never fully settle, so it can time out even though the page we
                # actually need has long since finished loading. "load" only
                # requires the page itself (plus its own resources) to finish,
                # which is enough since this site's content is server-rendered,
                # not filled in afterwards by JS.
                await page.goto(url, wait_until="load", timeout=45000)
            except PlaywrightTimeoutError:
                # Even "load" can time out on a slow connection. The navigation
                # has usually still completed by then, so fall back to whatever
                # content is currently in the page rather than failing outright.
                log.warning(f"Timed out waiting for {url} to finish loading, using current page content anyway")
            html = await page.content()
            # Cheap early-warning sign of a bot-protection challenge page (e.g.
            # Cloudflare) instead of real content: those pages are typically tiny
            # and won't have "character-images"/trivia table markup, so a very
            # short response here is worth knowing about without needing to add
            # debug logging by hand every time this is suspected.
            if len(html) < 2000:
                log.warning(f"Suspiciously short response ({len(html)} chars) fetching {url}, might be a bot-protection challenge page rather than real content")
            return html
        finally:
            await page.close()

    async def get_trivia_df(
        self, force_refresh: bool = False, progress_callback=None
    ) -> pd.DataFrame:
        """Character data (name, birthday, image URL), backed by a local CSV cache
        (data/characters.csv) so normal operation never has to touch the wiki once
        that cache exists. The cache is built (scraping the trivia table, plus one
        page load per character for their image) the first time this runs with no
        cache file present, or whenever force_refresh is set, e.g. via the
        owner-only /refresh_character_cache command.

        progress_callback, if given, is an async callable(done: int, total: int)
        invoked periodically while the cache is being built, so a caller (e.g. a
        Discord command) can surface progress instead of leaving the user staring
        at a static "please wait" message for a few minutes."""
        if not force_refresh and self._trivia_df is not None:
            return self._trivia_df

        if not force_refresh and os.path.exists(CHARACTERS_CSV):
            df = pd.read_csv(CHARACTERS_CSV, dtype=str).fillna("")
            log.info(f"Loaded {len(df)} character(s) from local cache ({CHARACTERS_CSV}).")
            self._trivia_df = df
            return df

        async with self._cache_build_lock:
            # Someone else may have finished building it (or force_refresh'd it)
            # while we were waiting for the lock, so check again before scraping.
            if not force_refresh and self._trivia_df is not None:
                return self._trivia_df
            if not force_refresh and os.path.exists(CHARACTERS_CSV):
                df = pd.read_csv(CHARACTERS_CSV, dtype=str).fillna("")
                log.info(f"Loaded {len(df)} character(s) from local cache ({CHARACTERS_CSV}).")
                self._trivia_df = df
                return df
            self._trivia_df = await self._build_character_cache(progress_callback)
        return self._trivia_df

    async def _build_character_cache(self, progress_callback=None) -> pd.DataFrame:
        """Live-scrapes the trivia table plus every character's image, then saves
        the combined result to CHARACTERS_CSV. This is the only place that needs
        to reach bluearchive.wiki once the cache file exists, so it's worth running
        it somewhere the site doesn't block/time out the bot (a VPS's datacenter IP
        can struggle with this even when a home connection works fine), then
        committing data/characters.csv so every other environment can just read it."""
        log.info(
            "No local character cache found, building one from bluearchive.wiki "
            "(this scrapes every character's page once, so it can take a minute)..."
        )
        html = await self._fetch_html(TRIVIA_URL)
        df = pd.read_html(io.StringIO(html))[0]
        df = df.drop_duplicates(subset=["Japanese reading"]).reset_index(drop=True)

        total = len(df)
        log.info(f"Found {total} character(s) in the trivia table, scraping each one's image...")

        image_urls = []
        for i, (_, row) in enumerate(df.iterrows(), start=1):
            url = f"https://bluearchive.wiki/wiki/{row['Character']}"
            try:
                image_urls.append(await self.scrape_character_image(url))
            except Exception as e:
                log.warning(f"Failed to scrape image for {row['Japanese reading']} ({url}): {e}")
                image_urls.append("")

            # Every character, so it's obvious the build is still alive and not
            # stuck, plus every 10th as a lower-noise "how far along" marker.
            log.info(f"[{i}/{total}] {row['Japanese reading']}")
            if i % 10 == 0 or i == total:
                log.info(f"Progress: {i}/{total} character(s) scraped.")

            if progress_callback is not None and (i % 5 == 0 or i == total):
                try:
                    await progress_callback(i, total)
                except Exception as e:
                    log.warning(f"Progress callback failed: {e}")

            await asyncio.sleep(CHARACTER_IMAGE_FETCH_DELAY)
        df["Image URL"] = image_urls

        if not os.path.exists(DIRECTORY):
            os.makedirs(DIRECTORY)
        df.to_csv(CHARACTERS_CSV, index=False)
        log.info(f"Saved {len(df)} character(s) to {CHARACTERS_CSV}.")
        return df

    async def _get_character_image(self, row_index, url: str) -> str:
        """Uses the cached Image URL from the character cache when we have one, so
        a normal birthday lookup never has to touch the wiki. Only live-scrapes
        (and then updates the cache on disk) for a character missing an image,
        e.g. one added to the wiki after the local cache was last built."""
        cached = (
            self._trivia_df.at[row_index, "Image URL"]
            if "Image URL" in self._trivia_df.columns
            else ""
        )
        if cached:
            return cached

        image = await self.scrape_character_image(url)
        if "Image URL" in self._trivia_df.columns:
            self._trivia_df.at[row_index, "Image URL"] = image
            try:
                self._trivia_df.to_csv(CHARACTERS_CSV, index=False)
            except Exception as e:
                log.warning(f"Failed to persist newly scraped image to {CHARACTERS_CSV}: {e}")
        return image

    async def find_birthday_by_name_autocomplete(self, _, current):
        df = await self.get_trivia_df()
        choices = df.loc[
            df["Japanese reading"].str.lower().str.contains(current.lower()),
            "Japanese reading",
        ].tolist()
        return [app_commands.Choice(name=choice, value=choice) for choice in choices][:25]

    @app_commands.command(name="find_birthday_by_name")
    @app_commands.autocomplete(choices=find_birthday_by_name_autocomplete)
    async def find_birthday_by_name(
        self, interaction: discord.Interaction, choices: str
    ):
        student_name = choices
        await interaction.response.defer()
        followup = await interaction.followup.send(
            f"Retrieving **{student_name}**'s birthday..."
        )

        birthday_data = await self.get_birthday_by_name(student_name)
        if birthday_data is None:
            await followup.edit(
                content=f"No character named **'{student_name}'**. Please try again."
            )
            return

        await self.send_embed(
            channel=interaction.channel,
            birthday_data=birthday_data,
            title="Birthday for...",
            react=False,
        )
        await followup.delete()

    async def get_birthday_by_name(self, student_name: str):
        df = await self.get_trivia_df()

        result = df[df["Japanese reading"] == student_name]
        if result.empty:
            return None

        name = result["Japanese reading"].values[0]
        url = f"https://bluearchive.wiki/wiki/{result['Character'].values[0]}"
        image = await self._get_character_image(result.index[0], url)
        date = result["Birthday"].values[0]
        birthday_data = {"name": name, "url": url,
                         "image_url": image, "date": date}

        return birthday_data

    @app_commands.command(
        name="list_channel_id_toggle",
        description="List out all channel id that is subscribed to toggle_birthday_reminder",
    )
    @commands.is_owner()
    async def list_channel_id_toggle(self, interaction: discord.Interaction):
        await self._channels_loaded.wait()
        if not self.set_channel:
            await interaction.response.send_message(content="No one is using this bot :(")
            return

        content = "\n".join(str(channel_id) for channel_id in self.set_channel)
        await interaction.response.send_message(content=content)

    @app_commands.command(
        name="refresh_character_cache",
        description="Re-scrape bluearchive.wiki and rebuild the local character cache (data/characters.csv)",
    )
    @commands.is_owner()
    async def refresh_character_cache(self, interaction: discord.Interaction):
        await interaction.response.defer()
        followup = await interaction.followup.send(
            "Rebuilding the local character cache from bluearchive.wiki, this scrapes every "
            "character's page so it can take a minute...\n-# 0 scraped so far"
        )

        # Discord edits are rate-limited and slow-ish, so we don't fire one on
        # every single character (get_trivia_df already caps this to every 5th
        # by only calling us that often), just enough to show the number moving.
        async def on_progress(done: int, total: int):
            await followup.edit(
                content=(
                    "Rebuilding the local character cache from bluearchive.wiki...\n"
                    f"-# {done}/{total} scraped so far"
                )
            )

        try:
            df = await self.get_trivia_df(force_refresh=True, progress_callback=on_progress)
            await followup.edit(
                content=f"Done, cached {len(df)} character(s) to `data/characters.csv`."
            )
        except Exception as e:
            log.error(f"Failed to refresh character cache: {e}")
            await followup.edit(content=f"Something went wrong rebuilding the cache: {e}")

    @app_commands.command(
        name="toggle_birthday_reminder",
        description="Enable/Disable birthday reminder on this channel",
    )
    async def toggle_birthday_reminder(self, interaction: discord.Interaction):
        await self._channels_loaded.wait()
        try:
            if interaction.channel_id not in self.set_channel:
                await self._store.add(interaction.channel_id)
                self.set_channel.append(interaction.channel_id)
                await interaction.response.send_message(
                    content=f"Birthday Reminder is now **ENABLED** on #{interaction.channel}"
                )
            else:
                await self._store.remove(interaction.channel_id)
                self.set_channel.remove(interaction.channel_id)
                await interaction.response.send_message(
                    content=f"Birthday Reminder is now **DISABLED** on #{interaction.channel}"
                )
        except Exception as e:
            log.error(f"Failed to save subscribed channel: {e}")
            await interaction.response.send_message(
                content="Something went wrong saving that, please try again in a moment."
            )

    @tasks.loop(time=time)
    async def scheduled_birthday_reminder(self):
        if self.set_channel != []:
            for channel_id in self.set_channel:
                try:
                    channel = await self.client.fetch_channel(channel_id)
                    today = await self.get_today_formatted()
                    birthdays = await self.scrape_birthday_date(today)
                    if birthdays != None:
                        for birthday_data in birthdays:
                            await self.send_embed(
                                channel=channel, birthday_data=birthday_data
                            )
                            await asyncio.sleep(0.5)
                except Exception as e:
                    log.error(f"An error occurred: {e}")
                    log.error(
                        f"Channel permission not granted in: [{channel_id}]")

    @scheduled_birthday_reminder.before_loop
    async def before_scheduled_birthday_reminder(self):
        await self.client.wait_until_ready()
        await self._channels_loaded.wait()

    @app_commands.command(
        name="get_today_birthday",
        description="Retrieve today's special birthdays",
    )
    async def get_today_birthday(self, interaction: discord.Interaction):
        await interaction.response.defer()
        followup = await interaction.followup.send("Retrieving today's birthday...")
        today = await self.get_today_formatted()
        birthdays = await self.scrape_birthday_date(today)
        if birthdays != None:
            for birthday_data in birthdays:
                await self.send_embed(
                    channel=interaction.channel, birthday_data=birthday_data
                )
                await asyncio.sleep(0.5)

            await followup.delete()
        else:
            await followup.edit(content=f"It is no one's birthday today 😭 ({today})")

    @app_commands.command(
        name="get_closest_birthday", description="Retrieve the next birthday date"
    )
    async def get_closest_birthday(self, interaction: discord.Interaction):
        await interaction.response.defer()
        followup = await interaction.followup.send(
            "Retrieving closest next birthday..."
        )
        df = await self.get_trivia_df()

        birthday_dates = [
            date_str for date_str in df["Birthday"].to_list() if date_str != "-"]
        next_birthday_date = await self.get_closest_birthday_date(
            birthday_dates
        )
        birthdays = await self.scrape_birthday_date(next_birthday_date)
        for birthday_data in birthdays:
            await self.send_embed(
                channel=interaction.channel,
                birthday_data=birthday_data,
                title="Next birthday...",
                react=False,
            )
            await asyncio.sleep(0.5)
        await followup.delete()

    async def get_closest_birthday_date(self, dates_list):
        current_date = datetime.datetime.today()

        closest_birthday = min(
            dates_list,
            key=lambda birthday_str: (
                (
                    datetime.datetime.strptime(birthday_str, "%B %d").replace(
                        year=current_date.year
                    )
                    - current_date
                ).days
                % 365
            ),
        )

        return closest_birthday

    async def get_today_formatted(self):
        today = datetime.datetime.today()
        today = " ".join(today.strftime("%B %e").split())

        return today

    async def scrape_birthday_date(self, date: str):
        df = await self.get_trivia_df()

        results = df[df["Birthday"] == date]
        if results.empty:
            # print("No birthday today")
            return None

        birthdays = []
        for idx, result in results.iterrows():
            name = result["Japanese reading"]
            url = f"https://bluearchive.wiki/wiki/{result['Character']}"
            image = await self._get_character_image(idx, url)
            date = result["Birthday"]

            birthday_data = {"name": name, "url": url,
                             "image_url": image, "date": date}

            birthdays.append(birthday_data)

        return birthdays

    async def scrape_character_image(self, url: str):
        html = await self._fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")
        character_images_div = soup.find("div", class_="character-images")
        image_element = character_images_div.find("img")
        image_url = image_element["src"]

        return f"https:{image_url}"

    async def send_embed(
        self,
        channel: discord.TextChannel,
        birthday_data: dict,
        title="HAPPY BIRTHDAY! 🎊🥳🎉",
        react=True,
    ):
        embed = discord.Embed(
            title=birthday_data["name"],
            url=birthday_data["url"],
            color=discord.Color.blue(),
        )
        embed.set_author(name=title)
        embed.set_image(url=birthday_data["image_url"])
        embed.set_footer(text=birthday_data["date"])

        message = await channel.send(embed=embed)
        if react:
            await message.add_reaction("❤️")


async def setup(client: commands.Bot) -> None:
    await client.add_cog(Birthday(client))
