## Blue Archive Birthday Bot

[![discord](https://img.shields.io/badge/Invite-Blue_Archive_Birthday_Bot-blue?logo=discord&logoColor=white)](https://discord.com/api/oauth2/authorize?client_id=1111574965981036604&permissions=2147485696&scope=bot)

### Preview

![Animation6](https://github.com/anwari-fikri/blue-archive-birthday-bot/assets/50336496/ea8e0854-70b6-4bc2-93d5-30876d3a50a3)



The Blue Archive Birthday Bot announces students' birthdays. Here are the available commands:

- `/toggle_birthday_reminder`: Toggle birthday reminders on or off. When enabled, the bot will automatically announce the student's birthday on their birthday.

- `/get_closest_birthday`: Get the upcoming closest birthday.

- `/get_today_birthday`: Get the student's birthday(s) today.

- `/find_birthday_by_name [name]`: Find the birthday of a student by their name. Provide the name of the student as an argument to retrieve their birthday.

To use the bot, simply type one of the commands in the chat or command prompt. The bot will respond with the requested information.

Data are retrieved from https://bluearchive.wiki/wiki/Characters_trivia_list. The wiki blocks plain HTTP requests, so the bot drives a real headless Chromium browser (via [Playwright](https://playwright.dev/python/)) to fetch pages, rather than a simple HTTP client.

### Running it yourself

Requirements: Python 3.10+ (tested on 3.14).

```
git clone https://github.com/anwari-fikri/blue-archive-birthday-bot.git
cd blue-archive-birthday-bot
python -m venv venv
```

Activate the virtual environment:
- Windows (PowerShell): `.\venv\Scripts\Activate.ps1`
- macOS/Linux: `source venv/bin/activate`

Install dependencies and the headless browser Playwright needs:
```
pip install -r requirements.txt
playwright install chromium
```

Create a `.env` file inside the `bot/` folder with your bot's token:
```
TOKEN=your_bot_token_here
```
Get a token from the [Discord Developer Portal](https://discord.com/developers/applications) (Applications → your app → Bot). Under the Bot page, make sure **Message Content Intent** is enabled, the bot won't start without it.

#### Optional: storing subscribed channels in Notion

By default, the list of channels that have `/toggle_birthday_reminder` enabled is stored in a local file, `data/set_channel.json`. If you'd rather keep that list in a Notion database instead, add two more variables to the `.env` file:
```
NOTION_API_KEY=your_notion_integration_token
NOTION_DATABASE_ID_BIRTHDAY_CHANNELS=your_notion_database_id
```

To set this up:
1. Create an internal integration at [notion.so/my-integrations](https://www.notion.so/my-integrations) and copy its token, that's `NOTION_API_KEY`.
2. Create a Notion database with exactly one property named `Channel ID`, of type Title.
3. Share that database with the integration (`•••` menu on the database → Connections → add your integration).
4. Copy the database ID from its URL (the 32-character id right after your workspace name and before the `?v=`), that's `NOTION_DATABASE_ID_BIRTHDAY_CHANNELS`.

Both variables are optional. Leave them unset and the bot keeps using `data/set_channel.json` exactly as before.

Run the bot:
```
cd bot
python bot.py
```

Feel free to suggest additional commands if you have any ideas, or if you prefer, you can submit a pull request to add new functionality yourself.
