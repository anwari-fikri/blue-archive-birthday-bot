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
            description="List of Commands:",
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="/toggle_birthday_reminder",
            value="Toggle birthday reminders on or off for this channel.",
            inline=False,
        )

        embed.add_field(
            name="/get_today_birthday",
            value="Get the character birthday(s) today.",
            inline=False,
        )

        embed.add_field(
            name="/get_closest_birthday",
            value="Get the upcoming closest birthday.",
            inline=False,
        )

        embed.add_field(
            name="/find_birthday_by_name",
            value="Look up a specific character's birthday by name.",
            inline=False,
        )

        embed.add_field(
            name="/refresh_character_cache",
            value="**(Owner only)** Re-scrape bluearchive.wiki and rebuild the local character cache.",
            inline=False,
        )

        embed.add_field(
            name="/list_channel_id_toggle",
            value="**(Owner only)** List every channel ID subscribed to birthday reminders.",
            inline=False,
        )

        await interaction.followup.send(embed=embed)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(General(client))
