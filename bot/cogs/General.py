import discord
from discord.ext import commands
from discord import app_commands


class General(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @app_commands.command(
        name="help", description="Learn about Blue Archive Birthday Bot commands"
    )
    async def help(self, interaction: discord.Interaction):
        await interaction.response.defer()

        embed = discord.Embed(
            title="Blue Archive Birthday Bot Commands",
            description="Hello!",
            color=discord.Color.yellow(),
        )

        await interaction.followup.send(embed=embed)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(General(client))
