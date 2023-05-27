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
time = datetime.time(
    hour=3, minute=37, tzinfo=utc
)  # 1am utc = 9am gmt+8 (singapore time)

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
                today = datetime.datetime.today() + datetime.timedelta(days=4)
                today = today.strftime("%B %d")
                birthdays = await self.scrape_birthday_date(today)
                if birthdays != None:
                    for birthday_data in birthdays:
                        await self.send_embed(channel=channel, birthday_data=birthday_data)
                        await asyncio.sleep(0.5)

    @app_commands.command(
        name="get_today_birthday", description="Learn about Blue Archive Birthday Bot commands"
    )
    async def get_today_birthday(self, interaction: discord.Interaction):
        await interaction.response.defer()
        followup = await interaction.followup.send("Retrieving today's birthday...")
        today = datetime.datetime.today() + datetime.timedelta(days=4)
        today = today.strftime("%B %d")
        birthdays = await self.scrape_birthday_date(today)
        if birthdays != None:
            for birthday_data in birthdays:
                await self.send_embed(channel=interaction.channel, birthday_data=birthday_data)
                await asyncio.sleep(0.5)
        
            await followup.delete()
        else:
            await followup.edit(content=f"It is no one's birthday today. ({today})")


    async def scrape_birthday_date(self, date: str):
        df = pd.read_html("https://bluearchive.wiki/wiki/Characters_trivia_list")[0]
        df = df.drop_duplicates(subset=['Japanese reading'])

        results = df[df["Birthday"] == date]
        if results.empty:
            print("No birthday today")
            return None

        birthdays = []
        for _, result in results.iterrows():
            name = result["Japanese reading"]
            url = f"https://bluearchive.wiki/wiki/{result['Character']}"
            image = await self.scrape_character_image(url)

            birthday_data = {
                "name": name,
                "url": url,
                "image_url": image
            }

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
        self, channel: discord.TextChannel, birthday_data: dict
    ):
        embed = discord.Embed(
            title=birthday_data["name"],
            url=birthday_data["url"],
            color=discord.Color.blue(),
        )
        embed.set_author(name="HAPPY BIRTHDAY! 🎊🥳🎉")
        embed.set_image(url=birthday_data["image_url"])

        message = await channel.send(embed=embed) 
        await message.add_reaction("❤️")

    # async def 



async def setup(client: commands.Bot) -> None:
    await client.add_cog(Birthday(client))
