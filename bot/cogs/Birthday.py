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
        await self.send_embed(channel=interaction.channel)
        await followup.delete()


    async def send_embed(
        self, channel: discord.TextChannel, 
    ):
        embed = discord.Embed(
            title="Sunaōkami Shiroko",
            url="https://bluearchive.wiki/wiki/Shiroko",
            color=discord.Color.blue(),
        )
        embed.set_author(name="HAPPY BIRTHDAY! 🎊🥳🎉")
        embed.set_image(url="https://static.miraheze.org/bluearchivewiki/6/63/Shiroko.png")

        await channel.send(embed=embed)

    # async def 



async def setup(client: commands.Bot) -> None:
    await client.add_cog(Birthday(client))
