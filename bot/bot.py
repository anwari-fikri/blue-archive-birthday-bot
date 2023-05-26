import discord
from discord.ext import commands
from colorama import Back, Fore, Style
import time
import platform
import os
from dotenv import load_dotenv

load_dotenv()


class BlueArchiveBirthdayBot(commands.Bot):
    def __init__(self):
        activity = discord.Game(name="/help")
        super().__init__(
            command_prefix=">> ", intents=discord.Intents().all(), activity=activity
        )

        self.cogslist = ["cogs.General", "cogs.Birthday"]

    async def setup_hook(self):
        for ext in self.cogslist:
            await self.load_extension(ext)

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
        synced = await self.tree.sync()
        print(
            prefix
            + " Slash CMDs Synced "
            + Fore.YELLOW
            + str(len(synced))
            + " Commands"
        )


def main():
    TOKEN = os.getenv("TOKEN")
    intents = discord.Intents.default()
    intents.message_content = True
    client = BlueArchiveBirthdayBot()
    client.run(TOKEN)


if __name__ == "__main__":
    main()
