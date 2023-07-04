import asyncio
import requests
from bs4 import BeautifulSoup
import datetime

# from datetime import datetime, timedelta
import discord
import pandas as pd
from discord.ext import commands, tasks
from discord import app_commands
import json

CHANNEL = "./data/set_channel.json"

utc = datetime.timezone.utc
time = datetime.time(hour=0, minute=0, tzinfo=utc)


class Birthday(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        try:
            with open(CHANNEL, "r") as f:
                self.set_channel = json.load(f)
        except FileNotFoundError:
            self.set_channel = []

        self.scheduled_birthday_reminder.start()

    def cog_unload(self):
        with open(CHANNEL, "w") as f:
            json.dump(self.set_channel, f)

    async def find_birthday_by_name_autocomplete(self, _, current):
        df = pd.read_html("https://bluearchive.wiki/wiki/Characters_trivia_list")[0]
        df = df.drop_duplicates(subset=["Japanese reading"])
        choices = df.loc[
            df["Japanese reading"].str.lower().str.contains(current.lower()),
            "Japanese reading",
        ].tolist()
        return [app_commands.Choice(name=choice, value=choice) for choice in choices]

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
        df = pd.read_html("https://bluearchive.wiki/wiki/Characters_trivia_list")[0]
        df = df.drop_duplicates(subset=["Japanese reading"])

        result = df[df["Japanese reading"] == student_name]
        if result.empty:
            return None

        name = result["Japanese reading"].values[0]
        url = f"https://bluearchive.wiki/wiki/{result['Character'].values[0]}"
        image = await self.scrape_character_image(url)
        date = result["Birthday"].values[0]
        birthday_data = {"name": name, "url": url, "image_url": image, "date": date}

        return birthday_data

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

    @tasks.loop(time=time)
    async def scheduled_birthday_reminder(self):
        if self.set_channel != []:
            for channel_id in self.set_channel:
                channel = await self.client.fetch_channel(channel_id)
                today = await self.get_today_formatted()
                birthdays = await self.scrape_birthday_date(today)
                if birthdays != None:
                    for birthday_data in birthdays:
                        await self.send_embed(
                            channel=channel, birthday_data=birthday_data
                        )
                        await asyncio.sleep(0.5)

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
        df = pd.read_html("https://bluearchive.wiki/wiki/Characters_trivia_list")[0]
        df = df.drop_duplicates(subset=["Japanese reading"])

        next_birthday_date = await self.get_closest_birthday_date(
            df["Birthday"].to_list()
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
        df = pd.read_html("https://bluearchive.wiki/wiki/Characters_trivia_list")[0]
        df = df.drop_duplicates(subset=["Japanese reading"])

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

            birthday_data = {"name": name, "url": url, "image_url": image, "date": date}

            birthdays.append(birthday_data)

        return birthdays

    async def scrape_character_image(self, url: str):
        response = requests.get(url)

        soup = BeautifulSoup(response.content, "html.parser")
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
