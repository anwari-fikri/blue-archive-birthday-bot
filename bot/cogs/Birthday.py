import asyncio
import io
from bs4 import BeautifulSoup
import datetime
import os

# from datetime import datetime, timedelta
import discord
import pandas as pd
from discord.ext import commands, tasks
from discord import app_commands
from playwright.async_api import async_playwright
import json
import logging
log = logging.getLogger(__name__)

DIRECTORY = './data'
CHANNEL = "./data/set_channel.json"
TRIVIA_URL = "https://bluearchive.wiki/wiki/Characters_trivia_list"

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# The trivia table rarely changes; re-scraping it on every single command (and on every
# autocomplete keystroke) is slow and makes it more likely we get rate-limited/blocked.
TRIVIA_CACHE_TTL = datetime.timedelta(hours=6)

utc = datetime.timezone.utc
time = datetime.time(hour=0, minute=0, tzinfo=utc)


class Birthday(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self._trivia_df = None
        self._trivia_fetched_at = None

        # bluearchive.wiki's CDN 403s plain HTTP clients (tried a browser User-Agent,
        # tried cloudscraper, still blocked), so we drive an actual headless browser
        # instead. One browser instance is kept alive for the cog's lifetime rather
        # than launching one per request, launching is the slow part (~1-2s).
        self._playwright = None
        self._browser = None
        self._browser_lock = asyncio.Lock()

        try:
            with open(CHANNEL, "r") as f:
                self.set_channel = json.load(f)
        except FileNotFoundError:
            if not os.path.exists(DIRECTORY):
                os.makedirs(DIRECTORY)
            self.set_channel = []

        self.scheduled_birthday_reminder.start()
        # Warm the trivia cache once at startup so the first real interaction
        # (especially autocomplete, which only gets ~3s to respond) doesn't have
        # to pay for a browser launch + page load itself. Cog.__init__ runs inside
        # a running event loop (via setup_hook -> load_extension), so we can just
        # schedule this on it directly rather than going through client.loop, which
        # isn't guaranteed to be set up yet depending on when the cog is loaded.
        asyncio.create_task(self._warmup())

    async def cog_unload(self):
        with open(CHANNEL, "w") as f:
            json.dump(self.set_channel, f)
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def _warmup(self):
        await self.client.wait_until_ready()
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
            await page.goto(url, wait_until="networkidle", timeout=30000)
            return await page.content()
        finally:
            await page.close()

    async def get_trivia_df(self, force_refresh: bool = False) -> pd.DataFrame:
        """Fetch the character trivia table, using a short-lived cache so we don't
        hit the wiki (and spin up a browser page) on every command invocation /
        autocomplete keystroke."""
        now = datetime.datetime.now(utc)
        is_stale = (
            self._trivia_df is None
            or self._trivia_fetched_at is None
            or now - self._trivia_fetched_at > TRIVIA_CACHE_TTL
        )
        if force_refresh or is_stale:
            html = await self._fetch_html(TRIVIA_URL)
            df = pd.read_html(io.StringIO(html))[0]
            df = df.drop_duplicates(subset=["Japanese reading"])
            self._trivia_df = df
            self._trivia_fetched_at = now
        return self._trivia_df

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
        image = await self.scrape_character_image(url)
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
        try:
            with open(CHANNEL, "r") as f:
                channel_list = json.load(f)
            # Convert the list to a string for proper content parameter.
            content = "\n".join(str(channel_id) for channel_id in channel_list)
            if content == "":
                await interaction.response.send_message(content="No one is using this bot :(")
                return

            await interaction.response.send_message(
                content=content
            )
        except (FileNotFoundError, json.JSONDecodeError):
            await interaction.response.send_message(
                content="No channels are subscribed to toggle_birthday_reminder."
            )

    @app_commands.command(
        name="toggle_birthday_reminder",
        description="Enable/Disable birthday reminder on this channel",
    )
    async def toggle_birthday_reminder(self, interaction: discord.Interaction):
        if interaction.channel_id not in self.set_channel:
            self.set_channel.append(interaction.channel_id)
            await interaction.response.send_message(
                content=f"Birthday Reminder is now **ENABLED** on #{interaction.channel}"
            )
        elif interaction.channel_id in self.set_channel:
            self.set_channel.remove(interaction.channel_id)
            await interaction.response.send_message(
                content=f"Birthday Reminder is now **DISABLED** on #{interaction.channel}"
            )

        with open(CHANNEL, "w") as f:
            json.dump(self.set_channel, f)

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
        for _, result in results.iterrows():
            name = result["Japanese reading"]
            url = f"https://bluearchive.wiki/wiki/{result['Character']}"
            image = await self.scrape_character_image(url)
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
