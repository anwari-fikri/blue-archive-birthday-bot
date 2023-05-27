import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import discord
import pandas as pd
from discord.ext import commands
from discord import app_commands


class Birthday(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @app_commands.command(
        name="get_today_birthday", description="Learn about Blue Archive Birthday Bot commands"
    )
    async def get_today_birthday(self, interaction: discord.Interaction):
        await interaction.response.defer()
        followup = await interaction.followup.send("Retrieving today's birthday...")
        today = datetime.today()
        today = today.strftime("%B %d")
        #  + timedelta(days=1)
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
            image = await self.scrape_image(url)

            birthday_data = {
                "name": name,
                "url": url,
                "image_url": image
            }

            birthdays.append(birthday_data)

        return birthdays
    
    async def scrape_image(self, url: str):
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

        await channel.send(embed=embed)

    # async def 



async def setup(client: commands.Bot) -> None:
    await client.add_cog(Birthday(client))
