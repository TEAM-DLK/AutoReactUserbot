import os
import random
import asyncio
import logging
import time
from typing import Optional, Dict

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, ReactionInvalid, MessageNotModified, PeerIdInvalid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "my_userbot",
    api_id=int(os.environ.get("API_ID", "YOUR-ID")),
    api_hash=os.environ.get("API_HASH", "YOUR-HASH"),
    session_string=os.environ.get("SESSION_STRING", "YOUR-STRING"),
    in_memory=True
)

# Default set of emojis to pick from
VALID_EMOJIS = [
    "☃️", "🎄", "🎅", "🎃", "🎉", "🏆", "🆒", "💯", "💋", "💊",
    "💘", "💔", "💩", "❤️", "❤️‍🔥", "🕊", "🙈", "🙉", "🙊", "🙏",
    "🤌", "🤝", "🤗", "🤘", "🤩", "🤪", "🤬", "🤓", "🤡", "🤣", "🤯",
    "🤷", "🤷‍♂️", "🤷‍♀️", "🖕", "🗿", "😁", "😇", "😈", "😍", "😎",
    "😡", "😨", "😱", "😭", "🥰", "🥱", "🥴", "😐", "😴", "🙂", "🤔",
    "🤨", "😢", "👌", "👍", "👎", "👏", "👀", "👻", "👾", "👨‍💻",
    "💅", "✍", "🫡", "🔥", "⚡", "🦄", "🐳", "🌚", "🌭", "🍾", "🍓",
    "🍌", "😘"
]

# Per-chat ON/OFF state (default True)
react_status: Dict[int, bool] = {}

# Per-chat reaction limits (per 60 seconds). None -> unlimited
react_limits: Dict[int, Optional[int]] = {}

# Per-chat counters for rate limiting: { chat_id: {"count": int, "reset": timestamp} }
react_counters: Dict[int, Dict[str, float]] = {}

alive_sent = False


async def send_alive():
    """
    Sends a single "alive" message to Saved Messages (me) once on startup.
    """
    global alive_sent
    if alive_sent:
        return
    try:
        await app.send_message(
            "me",
            "**🚀 Auto React Userbot FULLY ACTIVE!**\n\n"
            "✅ Reacts in **Private, Groups, Channels** by default\n"
            "✅ Skips **edited** messages (but now reacts to replies and own messages)\n"
            "⚙️ Use `!react on` / `!react off` → per-chat control\n"
            "🧾 Use `!reactlimit <n>` → set per-chat reactions per minute (empty/unlimited by default)\n"
            "🟢 **Status: ONLINE & REACTING EVERYWHERE (unless disabled)**",
            disable_web_page_preview=True
        )
        alive_sent = True
        logger.info("Alive message sent.")
    except Exception as e:
        logger.error(f"Failed to send alive: {e}")


def is_admin_or_me(message: Message, me_id: int) -> bool:
    """
    Returns True if the sender is the bot user (me) or is an admin in the chat.
    - For private chats: allow the sender (chat partner).
    - For groups/channels: only allow admins or the user themselves to change settings.
    """
    # Allow own messages always
    if message.from_user and message.from_user.id == me_id:
        return True

    # Private chats -> allow
    if message.chat.type == "private":
        return True

    # For groups/channels, check admin status
    try:
        member = asyncio.get_event_loop().run_until_complete(app.get_chat_member(message.chat.id, message.from_user.id))
        status = member.status  # "creator", "administrator", "member", ...
        return status in ("creator", "administrator")
    except Exception:
        # If we cannot determine, be conservative and disallow
        return False


@app.on_message(filters.command("react", prefixes=["/", "!"]) & (filters.group | filters.channel | filters.private))
async def cmd_react_toggle(client: Client, message: Message):
    """
    Toggle reactions for the current chat:
      !react on  -> enable reacting in this chat
      !react off -> disable reacting in this chat
      !react status -> show status
    Only admins (or the user themself in private) can change the setting.
    """
    me = await app.get_me()
    sender_ok = is_admin_or_me(message, me.id)

    if not sender_ok:
        await message.reply_text("❌ You must be an admin (or me) to change react settings in this chat.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.reply_text("Usage: `!react on` or `!react off` or `!react status`")
        return

    cmd = args[1].lower()
    chat_id = message.chat.id

    if cmd in ("on", "enable"):
        react_status[chat_id] = True
        await message.reply_text("🟢 Auto reactions ENABLED for this chat.")
    elif cmd in ("off", "disable"):
        react_status[chat_id] = False
        await message.reply_text("🔴 Auto reactions DISABLED for this chat.")
    elif cmd in ("status",):
        status = "ON" if react_status.get(chat_id, True) else "OFF"
        limit = react_limits.get(chat_id, None)
        limit_text = "unlimited" if limit is None else f"{limit} per minute"
        await message.reply_text(f"🤖 Auto React status: `{status}`\n⏱️ Limit: `{limit_text}`")
    else:
        await message.reply_text("Unknown option. Use `!react on`, `!react off` or `!react status`.")


@app.on_message(filters.command("reactlimit", prefixes=["/", "!"]) & (filters.group | filters.channel | filters.private))
async def cmd_react_limit(client: Client, message: Message):
    """
    Set per-chat reaction limit (per minute).
      !reactlimit 10  -> up to 10 reactions per minute in this chat
      !reactlimit 0   -> disable reactions entirely in this chat (equivalent to !react off)
      !reactlimit unset -> remove limit (unlimited)
      !reactlimit status -> show current
    Only admins (or the user themself in private) can change the setting.
    """
    me = await app.get_me()
    sender_ok = is_admin_or_me(message, me.id)

    if not sender_ok:
        await message.reply_text("❌ You must be an admin (or me) to change react limits in this chat.")
        return

    args = message.text.split()
    chat_id = message.chat.id

    if len(args) < 2:
        limit = react_limits.get(chat_id, None)
        limit_text = "unlimited" if limit is None else f"{limit} per minute"
        await message.reply_text(f"Current limit: `{limit_text}`")
        return

    val = args[1].lower()
    if val in ("unset", "none", "unlimited"):
        react_limits[chat_id] = None
        await message.reply_text("✅ Reaction limit removed — unlimited reactions allowed in this chat.")
    elif val in ("status",):
        limit = react_limits.get(chat_id, None)
        limit_text = "unlimited" if limit is None else f"{limit} per minute"
        await message.reply_text(f"Current limit: `{limit_text}`")
    else:
        try:
            n = int(val)
            if n < 0:
                raise ValueError()
            if n == 0:
                # Equivalent to disabling all reactions in this chat
                react_limits[chat_id] = 0
                react_status[chat_id] = False
                await message.reply_text("🔴 Reaction limit set to 0 — reactions disabled in this chat.")
            else:
                react_limits[chat_id] = n
                # If it was disabled, don't auto-enable; just set limit
                await message.reply_text(f"✅ Reaction limit set to `{n}` per minute for this chat.")
        except ValueError:
            await message.reply_text("Please provide a non-negative integer, or `unset` for unlimited.")


@app.on_message(
    (filters.private | filters.group | filters.channel) &
    (filters.incoming | filters.me) &                       # <-- include both incoming and your own outgoing messages
    ~filters.command(["react", "reactlimit"], prefixes=["/", "!"])
)
async def auto_react(client: Client, message: Message):
    """
    Main auto react handler:
      - skips edited messages
      - now reacts to replies too
      - includes your own messages (filters.me)
      - obeys per-chat ON/OFF (default ON)
      - obeys per-chat limits (per-minute)
    """
    # Skip edited messages
    if message.edit_date:
        return

    chat_id = message.chat.id

    # Check ON/OFF state (default ON)
    if not react_status.get(chat_id, True):
        return

    # If the chat has a limit of 0, treat as disabled
    limit = react_limits.get(chat_id, None)
    if limit == 0:
        return

    # Ensure message has an id (should always be true)
    if not message.id:
        return

    # Rate limiting per chat (sliding simple window: reset every 60s)
    now = time.time()
    counter = react_counters.get(chat_id)
    if not counter or now > counter.get("reset", 0):
        # reset window
        react_counters[chat_id] = {"count": 0, "reset": now + 60}
        counter = react_counters[chat_id]

    # If limit is set and we've reached it, skip reacting
    if limit is not None:
        if counter["count"] >= limit:
            # Reached limit for current minute
            logger.debug(f"Reaction limit reached for chat {chat_id}: {counter['count']}/{limit}")
            return

    emoji = random.choice(VALID_EMOJIS)

    try:
        await message.react(emoji=emoji)
        logger.info(f"Reacted {emoji} → {chat_id} | Msg ID: {message.id}")

        # increase counter
        react_counters[chat_id]["count"] += 1

    except ReactionInvalid:
        # emoji not allowed in this chat or other reaction-related problem
        pass
    except FloodWait as e:
        logger.warning(f"FloodWait: sleeping {e.value}s")
        await asyncio.sleep(e.value)
    except PeerIdInvalid:
        logger.warning(f"PeerIdInvalid skipped: {chat_id}")
        # Try to auto-resolve by fetching chat
        try:
            await app.get_chat(chat_id)
        except Exception:
            pass
    except Exception as e:
        error = str(e)
        if "MESSAGE_ID_INVALID" in error or "REACTION_INVALID" in error:
            # benign, skip
            pass
        else:
            logger.error(f"React failed: {error}")


@app.on_message(filters.private & filters.me)
async def auto_start_trigger(client: Client, message: Message):
    # Allow manual trigger from Saved Messages (me) to resend alive status
    await send_alive()


async def main():
    try:
        await app.start()
        me = await app.get_me()
        logger.info(f"Userbot started as @{me.username or me.first_name}")

        await send_alive()

        # Keep alive forever
        await asyncio.Event().wait()

    except Exception as e:
        logger.critical(f"Startup failed: {e}")
        await asyncio.sleep(5)
        os._exit(1)


if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        logger.info("Userbot stopped by user.")
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        os._exit(1)
