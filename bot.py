import os
import random
import asyncio
import logging
import time
from typing import Optional, Dict

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, ReactionInvalid, PeerIdInvalid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "auto_react_bot",
    api_id=int(os.environ.get("API_ID", "12345")),
    api_hash=os.environ.get("API_HASH", "YOUR_API_HASH"),
    bot_token=os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
)

OWNER_ID = int(os.environ.get("OWNER_ID", "0"))  # Your user ID (optional)

VALID_EMOJIS = [
    "☃️", "🎄", "🎅", "🎃", "🎉", "🏆", "💯", "💋", "💊",
    "💘", "💔", "❤️", "❤️‍🔥", "🙏", "🤘", "🤩", "🤪",
    "🤓", "🤣", "🤯", "😇", "😈", "😍", "😎",
    "😭", "🥰", "😐", "🙂", "🤔", "😢", "👌", "👍", "👎",
    "👏", "👀", "👻", "🔥", "⚡", "🌚", "🍾", "🍓", "😘"
]

# Per-chat ON/OFF state
react_status: Dict[int, bool] = {}

# Per-chat reaction limits
react_limits: Dict[int, Optional[int]] = {}

# Rate limit counters
react_counters: Dict[int, Dict[str, float]] = {}

# Cache: bot admin check
bot_admin_cache: Dict[int, bool] = {}

alive_sent = False


async def send_alive():
    global alive_sent
    if alive_sent or OWNER_ID == 0:
        return

    try:
        await app.send_message(
            OWNER_ID,
            "✅ Auto React Bot is ONLINE\n"
            "• Reacts in groups & channels where I am admin\n"
            "• Use /react on/off/status\n"
            "• Use /reactlimit <number>",
        )
        alive_sent = True
    except Exception as e:
        logger.error(f"Alive message failed: {e}")


async def is_user_admin(message: Message) -> bool:
    """Check if sender is admin (or private chat)"""
    if message.chat.type == "private":
        return True

    if not message.from_user:
        return False

    try:
        member = await app.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


async def is_bot_admin(chat_id: int) -> bool:
    """Check if bot is admin in a chat (cached)"""
    if chat_id in bot_admin_cache:
        return bot_admin_cache[chat_id]

    try:
        me = await app.get_me()
        member = await app.get_chat_member(chat_id, me.id)
        is_admin = member.status in ("creator", "administrator")
        bot_admin_cache[chat_id] = is_admin
        return is_admin
    except Exception:
        bot_admin_cache[chat_id] = False
        return False


@app.on_message(filters.command("react"))
async def react_control(client, message: Message):
    if not await is_user_admin(message):
        return await message.reply("❌ Only admins can change reaction settings.")

    args = message.text.split()
    chat_id = message.chat.id

    if len(args) < 2:
        return await message.reply("Usage: /react on | off | status")

    cmd = args[1].lower()

    if cmd == "on":
        react_status[chat_id] = True
        await message.reply("✅ Auto reactions ENABLED in this chat.")

    elif cmd == "off":
        react_status[chat_id] = False
        await message.reply("❌ Auto reactions DISABLED in this chat.")

    elif cmd == "status":
        status = "ON" if react_status.get(chat_id, True) else "OFF"
        limit = react_limits.get(chat_id)
        limit_text = "unlimited" if limit is None else str(limit)
        await message.reply(f"Status: {status}\nLimit: {limit_text} reactions/min")

    else:
        await message.reply("Invalid option. Use: on / off / status")


@app.on_message(filters.command("reactlimit"))
async def react_limit(client, message: Message):
    if not await is_user_admin(message):
        return await message.reply("❌ Only admins can change limits.")

    args = message.text.split()
    chat_id = message.chat.id

    if len(args) < 2:
        limit = react_limits.get(chat_id)
        text = "unlimited" if limit is None else str(limit)
        return await message.reply(f"Current limit: {text} reactions per minute")

    value = args[1].lower()

    if value in ["unset", "none"]:
        react_limits[chat_id] = None
        await message.reply("✅ Reaction limit removed.")

    else:
        try:
            num = int(value)
            if num <= 0:
                react_status[chat_id] = False
                react_limits[chat_id] = 0
                return await message.reply("❌ Reactions disabled (limit = 0).")

            react_limits[chat_id] = num
            await message.reply(f"✅ Reaction limit set to {num} per minute.")

        except ValueError:
            await message.reply("Invalid number.")


@app.on_message(filters.incoming & (filters.group | filters.channel | filters.private))
async def auto_react(client, message: Message):
    if message.edit_date:
        return

    chat_id = message.chat.id

    # Bot must be admin in groups/channels
    if message.chat.type != "private":
        if not await is_bot_admin(chat_id):
            return

    # Check status
    if not react_status.get(chat_id, True):
        return

    limit = react_limits.get(chat_id)

    # Rate limit handling
    now = time.time()
    counter = react_counters.get(chat_id)

    if not counter or now > counter["reset"]:
        react_counters[chat_id] = {"count": 0, "reset": now + 60}
        counter = react_counters[chat_id]

    if limit is not None and counter["count"] >= limit:
        return

    try:
        emoji = random.choice(VALID_EMOJIS)
        await message.react(emoji=emoji)
        react_counters[chat_id]["count"] += 1

    except FloodWait as e:
        await asyncio.sleep(e.value)

    except ReactionInvalid:
        pass

    except PeerIdInvalid:
        pass

    except Exception as e:
        logger.error(f"Reaction failed: {e}")


async def main():
    await app.start()
    me = await app.get_me()
    logger.info(f"Bot running as @{me.username}")

    await send_alive()
    await asyncio.Event().wait()


if __name__ == "__main__":
    app.run(main())