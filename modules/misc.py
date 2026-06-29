import json
import logging
from flask import request
from config import BOT_NAME, UPDATES_CHANNEL, SUPPORT_GROUP
from utils.api import api_request
from utils.helpers import is_admin, get_chat_setting, set_chat_setting, resolve_target, msg_id
from database.mongo import warnings_col, banned_users_col, chat_settings_col

logger = logging.getLogger(__name__)


def _mid():
    return msg_id(request.json)


# ── Start / Help ───────────────────────────────────────────────────────────────

def handle_start(chat_id: int, user_id: int):
    keyboard = {"inline_keyboard": [
        [{"text": "🛡 Moderation", "callback_data": "help_mod"}, {"text": "⚙️ Settings", "callback_data": "help_settings"}],
        [{"text": "🎉 Fun", "callback_data": "help_fun"}, {"text": "📝 Notes", "callback_data": "help_notes"}],
        [{"text": "🔗 Updates", "url": UPDATES_CHANNEL}, {"text": "💬 Support", "url": SUPPORT_GROUP}],
    ]}
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"👋 Hello! I'm **{BOT_NAME}** — an open-source Telegram group management bot.\n\n"
            f"Features:\n"
            f"• Moderation: ban, kick, mute, warn, promote\n"
            f"• Filters, blacklist, locks, anti-spam\n"
            f"• Notes system (save & retrieve with #note)\n"
            f"• Welcome messages & captcha verification\n"
            f"• Fun commands: 8ball, roll, hug, slap & more\n\n"
            f"Add me to a group and make me admin to get started!"
        ),
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(keyboard),
    })


def handle_help(chat_id: int):
    mid = _mid()
    keyboard = {"inline_keyboard": [
        [{"text": "🛡 Moderation", "callback_data": "help_mod"}, {"text": "⚙️ Settings", "callback_data": "help_settings"}],
        [{"text": "🎉 Fun", "callback_data": "help_fun"}, {"text": "📝 Notes & Filters", "callback_data": "help_notes"}],
        [{"text": "🔧 Admin Tools", "callback_data": "help_admin"}, {"text": "ℹ️ Misc", "callback_data": "help_misc"}],
    ]}
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"📖 **{BOT_NAME} Help**\n\nSelect a category below:",
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(keyboard),
        "reply_to_message_id": mid,
    })


def handle_help_callback(callback_query: dict):
    data = callback_query.get("data", "")
    chat_id = callback_query["message"]["chat"]["id"]
    cb_id = callback_query["id"]
    back_btn = [{"text": "« Back", "callback_data": "help_back"}]

    api_request("answerCallbackQuery", {"callback_query_id": cb_id})

    texts = {
        "help_mod": (
            "🛡 *Moderation Commands*\n\n"
            "`/ban` — Ban a user\n"
            "`/tban` — Temporarily ban (e.g. `/tban @user 1h`)\n"
            "`/unban` — Unban a user\n"
            "`/kick` — Kick a user\n"
            "`/mute` — Mute a user\n"
            "`/tmute` — Temporarily mute\n"
            "`/unmute` — Unmute a user\n"
            "`/warn` — Warn a user\n"
            "`/unwarn` — Remove one warning\n"
            "`/clearwarns` — Clear all warnings\n"
            "`/warnings` — Check warnings\n"
            "`/setwarnlimit` — Set warn threshold\n"
            "`/promote` — Promote to admin\n"
            "`/demote` — Demote admin\n"
            "`/banlist` — List banned users\n"
            "`/getadmins` — List all admins"
        ),
        "help_settings": (
            "⚙️ *Settings Commands*\n\n"
            "`/setwelcome` — Set welcome message\n"
            "`/welcome on|off` — Toggle welcome\n"
            "`/setcaptcha on|off` — Toggle captcha\n"
            "`/setrules` — Set group rules\n"
            "`/rules` — Show rules\n"
            "`/clearrules` — Clear rules\n"
            "`/setwarnlimit` — Set warn threshold\n"
            "`/slowmode` — Set slowmode delay\n"
            "`/lock links|media|stickers|all|forward|polls` — Lock content\n"
            "`/unlock` — Unlock content\n"
            "`/locks` — Show lock status"
        ),
        "help_fun": (
            "🎉 *Fun Commands*\n\n"
            "`/roll [sides]` — Roll a dice\n"
            "`/flip` — Flip a coin\n"
            "`/8ball <question>` — Magic 8-ball\n"
            "`/hug [@user]` — Send a hug\n"
            "`/slap [@user]` — Slap someone\n"
            "`/pat [@user]` — Pat someone\n"
            "`/kiss [@user]` — Send a kiss\n"
            "`/meme` — Random meme\n"
            "`/quote` — Inspirational quote\n"
            "`/poll <question>|opt1|opt2` — Create a poll\n"
            "`/stickerid` — Get sticker file ID"
        ),
        "help_notes": (
            "📝 *Notes & Filters*\n\n"
            "`/save <name> <content>` — Save a note\n"
            "`/get <name>` or `#name` — Retrieve a note\n"
            "`/delnote <name>` — Delete a note\n"
            "`/notes` — List all notes\n\n"
            "`/filter <keyword> <reply>` — Add auto-reply filter\n"
            "`/stop <keyword>` — Remove a filter\n"
            "`/filters` — List all filters\n\n"
            "`/addblacklist <word>` — Blacklist a word\n"
            "`/rmblacklist <word>` — Remove from blacklist\n"
            "`/blacklist` — List blacklisted words"
        ),
        "help_admin": (
            "🔧 *Admin Tools*\n\n"
            "`/pin` — Pin replied message\n"
            "`/unpin` — Unpin current pinned\n"
            "`/unpinall` — Unpin all messages\n"
            "`/purge` — Purge messages from reply to now\n"
            "`/cleanup <n>` — Delete last n messages\n"
            "`/id` — Show user & chat ID\n"
            "`/whois [@user]` — User info\n"
            "`/stats` — Group statistics"
        ),
        "help_misc": (
            "ℹ️ *Misc Commands*\n\n"
            "`/start` — Start / info\n"
            "`/help` — This menu\n"
            "`/id` — Your user ID\n"
            "`/whois [@user]` — User lookup\n"
            "`/stats` — Group stats"
        ),
    }

    if data == "help_back":
        keyboard = {"inline_keyboard": [
            [{"text": "🛡 Moderation", "callback_data": "help_mod"}, {"text": "⚙️ Settings", "callback_data": "help_settings"}],
            [{"text": "🎉 Fun", "callback_data": "help_fun"}, {"text": "📝 Notes & Filters", "callback_data": "help_notes"}],
            [{"text": "🔧 Admin Tools", "callback_data": "help_admin"}, {"text": "ℹ️ Misc", "callback_data": "help_misc"}],
        ]}
        api_request("editMessageText", {
            "chat_id": chat_id,
            "message_id": callback_query["message"]["message_id"],
            "text": f"📖 **{BOT_NAME} Help**\n\nSelect a category below:",
            "parse_mode": "Markdown",
            "reply_markup": json.dumps(keyboard),
        })
        return

    if data in texts:
        api_request("editMessageText", {
            "chat_id": chat_id,
            "message_id": callback_query["message"]["message_id"],
            "text": texts[data],
            "parse_mode": "Markdown",
            "reply_markup": json.dumps({"inline_keyboard": [back_btn]}),
        })


# ── Utility commands ───────────────────────────────────────────────────────────

def handle_id(chat_id: int):
    mid = _mid()
    info = request.json["message"]["from"]
    name = info.get("first_name", "Unknown")
    uname = f" (@{info['username']})" if info.get("username") else ""
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"🆔 *Your Info*\nName: {name}{uname}\nUser ID: `{info['id']}`\nChat ID: `{chat_id}`",
        "parse_mode": "Markdown",
        "reply_to_message_id": mid,
    })


def handle_whois(chat_id: int, user_id: int, text: str):
    mid = _mid()
    target_id, target_name = resolve_target(request.json["message"], text, "whois")

    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Reply to a user or use `/whois @user`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    warn_doc = warnings_col().find_one({"chat_id": chat_id, "user_id": target_id})
    warn_count = warn_doc.get("count", 0) if warn_doc else 0
    banned = banned_users_col().find_one({"chat_id": chat_id, "user_id": target_id})
    admin = is_admin(chat_id, target_id)

    status = "Creator/Admin" if admin else ("Banned" if banned else "Member")

    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"👤 *User Info*\n"
            f"Name: {target_name}\n"
            f"User ID: `{target_id}`\n"
            f"Status: {status}\n"
            f"Warnings: {warn_count}"
        ),
        "parse_mode": "Markdown",
        "reply_to_message_id": mid,
    })


def handle_stats(chat_id: int, user_id: int):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    try:
        chat_info = api_request("getChat", {"chat_id": chat_id})
        admins = api_request("getChatAdministrators", {"chat_id": chat_id})
        member_count = api_request("getChatMemberCount", {"chat_id": chat_id})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to fetch stats: {e}", "reply_to_message_id": mid})
        return

    banned_count = banned_users_col().count_documents({"chat_id": chat_id})
    warn_count = sum(
        (d.get("count", 0) for d in warnings_col().find({"chat_id": chat_id}))
    )

    welcome_on = get_chat_setting(chat_id, "welcome_enabled", True)
    captcha_on = get_chat_setting(chat_id, "captcha_enabled", False)

    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"📊 *Group Statistics*\n\n"
            f"Name: {chat_info.get('title', '—')}\n"
            f"Members: {member_count}\n"
            f"Admins: {len(admins)}\n"
            f"Banned: {banned_count}\n"
            f"Total Warnings: {warn_count}\n\n"
            f"⚙️ Settings:\n"
            f"Welcome: {'✅' if welcome_on else '❌'}\n"
            f"Captcha: {'✅' if captcha_on else '❌'}"
        ),
        "parse_mode": "Markdown",
        "reply_to_message_id": mid,
    })
