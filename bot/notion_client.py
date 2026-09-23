"""Small Notion API client for storing which channels have birthday reminders
enabled, replacing the old local data/set_channel.json file.

Mirrors the plain fetch-based approach used in the anwarifikri portfolio repo's
lib/notion.ts (direct REST calls with a Bearer token, rather than the notion-client
SDK), just translated to Python/aiohttp so it fits the bot's existing async style.

Requires two environment variables (see README):
  NOTION_API_KEY                      - an internal integration token
  NOTION_DATABASE_ID_BIRTHDAY_CHANNELS - the database's id, shared with that integration

The database needs exactly one property: "Channel ID", type Title.
"""
import os
import aiohttp

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID_BIRTHDAY_CHANNELS = os.getenv("NOTION_DATABASE_ID_BIRTHDAY_CHANNELS")
NOTION_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

CHANNEL_ID_PROPERTY = "Channel ID"


def is_configured() -> bool:
    """True once both env vars are set. The bot falls back to the local JSON
    file (see cogs/Birthday.py) when this is False, so Notion is opt-in."""
    return bool(NOTION_API_KEY) and bool(NOTION_DATABASE_ID_BIRTHDAY_CHANNELS)


async def _request(method: str, endpoint: str, json_body: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(
            method, f"{NOTION_BASE_URL}{endpoint}", headers=headers, json=json_body
        ) as response:
            data = await response.json()
            if response.status >= 400:
                message = data.get("message", data)
                raise RuntimeError(f"Notion API error ({response.status}): {message}")
            return data


async def list_subscribed_channels() -> dict[int, str]:
    """Returns {channel_id: notion_page_id} for every page in the database."""
    channels: dict[int, str] = {}
    cursor = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = await _request(
            "POST", f"/databases/{NOTION_DATABASE_ID_BIRTHDAY_CHANNELS}/query", body
        )
        for page in data.get("results", []):
            title = page["properties"].get(CHANNEL_ID_PROPERTY, {}).get("title", [])
            if not title:
                continue
            try:
                channel_id = int(title[0]["plain_text"])
            except (KeyError, ValueError, IndexError):
                continue
            channels[channel_id] = page["id"]
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return channels


async def add_subscribed_channel(channel_id: int) -> str:
    """Creates a page for this channel and returns its page id."""
    data = await _request(
        "POST",
        "/pages",
        {
            "parent": {"database_id": NOTION_DATABASE_ID_BIRTHDAY_CHANNELS},
            "properties": {
                CHANNEL_ID_PROPERTY: {
                    "title": [{"text": {"content": str(channel_id)}}]
                }
            },
        },
    )
    return data["id"]


async def remove_subscribed_channel(page_id: str) -> None:
    # Notion has no hard delete via the API; archiving is the standard equivalent.
    await _request("PATCH", f"/pages/{page_id}", {"archived": True})
