import discord
from discord.ext import commands
from colorama import Back, Fore, Style
import time
import platform
import os
import logging
from dotenv import load_dotenv

load_dotenv()


class BlueArchiveBirthdayBot(commands.Bot):
    def __init__(self):
        activity = discord.Game(name="/help")
        super().__init__(
            command_prefix=">> ", intents=discord.Intents().all(), activity=activity
        )

        self.cogslist = ["cogs.General", "cogs.Birthday"]
        self.synced_command_count = 0

    async def setup_hook(self):
        for ext in self.cogslist:
            await self.load_extension(ext)

        # Sync here (once, at startup) rather than in on_ready, which fires again on
        # every reconnect and would re-sync slash commands every time, risking rate limits.
        synced = await self.tree.sync()
        self.synced_command_count = len(synced)

    async def on_ready(self):
        prefix = (
            Back.BLACK
            + Fore.GREEN
            + time.strftime("%H:%M:%S UTC", time.gmtime())
            + Back.RESET
            + Fore.WHITE
            + Style.BRIGHT
        )

        print(prefix + " Logged in as " + Fore.YELLOW + self.user.name)
        print(prefix + " Bot ID " + Fore.YELLOW + str(self.user.id))
        print(prefix + " Discord Version " + Fore.YELLOW + discord.__version__)
        print(
            prefix + " Python Version " + Fore.YELLOW + str(platform.python_version())
        )
        print(
            prefix
            + " Slash CMDs Synced "
            + Fore.YELLOW
            + str(self.synced_command_count)
            + " Commands"
        )


def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        raise RuntimeError(
            "No TOKEN found. Create a .env file with TOKEN=<your bot token> "
            "(see README) before running the bot."
        )
    client = BlueArchiveBirthdayBot()
    client.run(TOKEN, log_level=logging.INFO)


if __name__ == "__main__":
    main()
