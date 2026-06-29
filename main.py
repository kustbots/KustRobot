"""
Kust Robot — Open-source Telegram Group Management Bot
Raw HTTP + Flask webhook, MongoDB storage.

Updates : https://t.me/kustbots
Support : https://t.me/kustbotschat
GitHub  : https://github.com/kustbots/KustRobot

Setup:
  1. pip install -r requirements.txt
  2. Set env vars: BOT_TOKEN, WEBHOOK_SECRET, ADMIN_IDS, MONGO_URI, PORT
  3. python main.py
  4. Set webhook:
     curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
          -d '{"url":"https://yourdomain.com/webhook/<SECRET>"}'
"""

import logging
from flask import Flask, request, jsonify, abort
from config import BOT_TOKEN, WEBHOOK_SECRET, PORT, BOT_NAME
from utils.api import api_request
from utils.helpers import check_rate_limit

# Modules
from modules import admin, greetings, rules, filters, notes, blacklist, pins, fun, misc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ── Webhook ────────────────────────────────────────────────────────────────────

@app.route(f"/webhook/<secret>", methods=["POST"])
def webhook(secret: str):
    if secret != WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            logger.warning("Rejected request with invalid webhook secret")
            abort(403)

    update = request.json
    if not update:
        return jsonify({"status": "ok"})

    try:
        _dispatch(update)
    except Exception as e:
        logger.exception(f"Unhandled error in dispatcher: {e}")

    return jsonify({"status": "ok"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot": BOT_NAME})


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def _dispatch(update: dict):
    # Callback queries
    if "callback_query" in update:
        cb = update["callback_query"]
        data = cb.get("data", "")

        if data.startswith("cap_"):
            greetings.handle_captcha_callback(cb)
        elif data.startswith("help_") or data == "help_back":
            misc.handle_help_callback(cb)
        else:
            api_request("answerCallbackQuery", {"callback_query_id": cb["id"]})
        return

    if "message" not in update:
        return

    message = update["message"]
    chat_id: int = message["chat"]["id"]
    chat_type: str = message["chat"].get("type", "private")
    user_id: int = message.get("from", {}).get("id", 0)
    text: str = message.get("text", "")

    # New members
    if "new_chat_members" in message:
        for member in message["new_chat_members"]:
            greetings.handle_new_member(chat_id, member)
        return

    # Rate limit (applies to commands only — let content checks always run)
    if text.startswith("/"):
        if not check_rate_limit(user_id):
            return
        _handle_command(chat_id, user_id, text, message)
        return

    # Non-command messages — run content checks
    _handle_message_checks(chat_id, user_id, message, text)


def _handle_command(chat_id: int, user_id: int, text: str, message: dict):
    # Strip bot username from command if present (e.g. /ban@KustRobot)
    cmd = text.split()[0].split("@")[0].lower().lstrip("/")

    # ── Start / Help ──
    if cmd == "start":
        misc.handle_start(chat_id, user_id)
    elif cmd == "help":
        misc.handle_help(chat_id)

    # ── Rules ──
    elif cmd == "setrules":
        rules.handle_setrules(chat_id, user_id, text)
    elif cmd == "rules":
        rules.handle_rules(chat_id)
    elif cmd == "clearrules":
        rules.handle_clearrules(chat_id, user_id)

    # ── Moderation ──
    elif cmd == "warn":
        admin.handle_warn(chat_id, user_id, text)
    elif cmd == "unwarn":
        admin.handle_unwarn(chat_id, user_id, text)
    elif cmd == "warnings":
        admin.handle_warnings(chat_id, user_id, text)
    elif cmd == "clearwarns":
        admin.handle_clearwarns(chat_id, user_id, text)
    elif cmd == "setwarnlimit":
        admin.handle_setwarnlimit(chat_id, user_id, text)
    elif cmd == "ban":
        admin.handle_ban(chat_id, user_id, text)
    elif cmd == "tban":
        admin.handle_tban(chat_id, user_id, text)
    elif cmd == "unban":
        admin.handle_unban(chat_id, user_id, text)
    elif cmd == "kick":
        admin.handle_kick(chat_id, user_id, text)
    elif cmd == "mute":
        admin.handle_mute(chat_id, user_id, text)
    elif cmd == "tmute":
        admin.handle_tmute(chat_id, user_id, text)
    elif cmd == "unmute":
        admin.handle_unmute(chat_id, user_id, text)
    elif cmd == "promote":
        admin.handle_promote(chat_id, user_id, text)
    elif cmd == "demote":
        admin.handle_demote(chat_id, user_id, text)
    elif cmd == "banlist":
        admin.handle_banlist(chat_id, user_id)
    elif cmd == "getadmins":
        admin.handle_getadmins(chat_id, user_id)

    # ── Greetings / Captcha ──
    elif cmd == "setwelcome":
        greetings.handle_setwelcome(chat_id, user_id, text)
    elif cmd == "welcome":
        greetings.handle_welcome_toggle(chat_id, user_id, text)
    elif cmd == "setcaptcha":
        greetings.handle_setcaptcha(chat_id, user_id, text)

    # ── Locks ──
    elif cmd == "lock":
        filters.handle_lock(chat_id, user_id, text)
    elif cmd == "unlock":
        filters.handle_unlock(chat_id, user_id, text)
    elif cmd == "locks":
        filters.handle_locks(chat_id, user_id)

    # ── Custom filters ──
    elif cmd == "filter":
        filters.handle_add_filter(chat_id, user_id, text)
    elif cmd == "stop":
        filters.handle_stop_filter(chat_id, user_id, text)
    elif cmd == "filters":
        filters.handle_list_filters(chat_id, user_id)

    # ── Notes ──
    elif cmd == "save":
        notes.handle_save(chat_id, user_id, text)
    elif cmd == "get":
        notes.handle_get_command(chat_id, text)
    elif cmd == "delnote":
        notes.handle_delnote(chat_id, user_id, text)
    elif cmd == "notes":
        notes.handle_notes_list(chat_id)

    # ── Blacklist ──
    elif cmd == "addblacklist":
        blacklist.handle_addblacklist(chat_id, user_id, text)
    elif cmd == "rmblacklist":
        blacklist.handle_rmblacklist(chat_id, user_id, text)
    elif cmd == "blacklist":
        blacklist.handle_blacklist_list(chat_id, user_id)

    # ── Pins / Cleanup ──
    elif cmd == "pin":
        pins.handle_pin(chat_id, user_id)
    elif cmd == "unpin":
        pins.handle_unpin(chat_id, user_id)
    elif cmd == "unpinall":
        pins.handle_unpinall(chat_id, user_id)
    elif cmd == "purge":
        pins.handle_purge(chat_id, user_id)
    elif cmd == "cleanup":
        pins.handle_cleanup(chat_id, user_id, text)
    elif cmd == "slowmode":
        pins.handle_slowmode(chat_id, user_id, text)

    # ── Misc ──
    elif cmd == "id":
        misc.handle_id(chat_id)
    elif cmd == "whois":
        misc.handle_whois(chat_id, user_id, text)
    elif cmd == "stats":
        misc.handle_stats(chat_id, user_id)

    # ── Fun ──
    elif cmd == "roll":
        fun.handle_roll(chat_id, text)
    elif cmd == "8ball":
        fun.handle_8ball(chat_id, text)
    elif cmd == "hug":
        fun.handle_hug(chat_id, text)
    elif cmd == "slap":
        fun.handle_slap(chat_id, text)
    elif cmd == "pat":
        fun.handle_pat(chat_id, text)
    elif cmd == "kiss":
        fun.handle_kiss(chat_id, text)
    elif cmd == "meme":
        fun.handle_meme(chat_id)
    elif cmd == "poll":
        fun.handle_poll(chat_id, text)
    elif cmd == "stickerid":
        fun.handle_stickerid(chat_id)
    elif cmd == "quote":
        fun.handle_quote(chat_id)
    elif cmd in ("flip", "toss"):
        fun.handle_flip(chat_id)


def _handle_message_checks(chat_id: int, user_id: int, message: dict, text: str):
    # 1. Blacklist check
    if not blacklist.check_blacklist(chat_id, message):
        return

    # 2. Lock / content filter check
    if not filters.check_message_content(chat_id, message):
        try:
            api_request("deleteMessage", {"chat_id": chat_id, "message_id": message["message_id"]})
        except Exception:
            pass
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ That content type is locked in this group."})
        return

    # 3. Custom filter triggers
    filters.check_filters(chat_id, message)

    # 4. Note triggers (#notename)
    notes.check_note_trigger(chat_id, text, reply_to=message.get("message_id"))


# ── Bot init ───────────────────────────────────────────────────────────────────

def set_bot_commands():
    commands = [
        {"command": "start", "description": "Start / bot info"},
        {"command": "help", "description": "Show help menu"},
        {"command": "rules", "description": "Show group rules"},
        {"command": "warn", "description": "Warn a user"},
        {"command": "ban", "description": "Ban a user"},
        {"command": "tban", "description": "Temporarily ban a user"},
        {"command": "kick", "description": "Kick a user"},
        {"command": "mute", "description": "Mute a user"},
        {"command": "tmute", "description": "Temporarily mute a user"},
        {"command": "unmute", "description": "Unmute a user"},
        {"command": "unban", "description": "Unban a user"},
        {"command": "promote", "description": "Promote user to admin"},
        {"command": "demote", "description": "Demote admin"},
        {"command": "pin", "description": "Pin a message"},
        {"command": "unpin", "description": "Unpin a message"},
        {"command": "purge", "description": "Purge messages"},
        {"command": "save", "description": "Save a note"},
        {"command": "get", "description": "Get a note"},
        {"command": "notes", "description": "List all notes"},
        {"command": "filter", "description": "Add a keyword filter"},
        {"command": "filters", "description": "List all filters"},
        {"command": "addblacklist", "description": "Add word to blacklist"},
        {"command": "blacklist", "description": "List blacklisted words"},
        {"command": "lock", "description": "Lock content type"},
        {"command": "unlock", "description": "Unlock content type"},
        {"command": "setwelcome", "description": "Set welcome message"},
        {"command": "setcaptcha", "description": "Toggle captcha"},
        {"command": "slowmode", "description": "Set slowmode"},
        {"command": "stats", "description": "Group statistics"},
        {"command": "id", "description": "Your user ID"},
        {"command": "whois", "description": "User information"},
        {"command": "roll", "description": "Roll a dice"},
        {"command": "8ball", "description": "Magic 8-ball"},
        {"command": "hug", "description": "Send a hug"},
        {"command": "slap", "description": "Slap someone"},
        {"command": "quote", "description": "Random quote"},
        {"command": "meme", "description": "Random meme"},
        {"command": "flip", "description": "Flip a coin"},
    ]
    try:
        api_request("setMyCommands", {"commands": commands})
        logger.info("Bot commands registered.")
    except Exception as e:
        logger.error(f"Failed to set commands: {e}")


if BOT_TOKEN:
    set_bot_commands()
else:
    logger.warning("BOT_TOKEN not set — skipping command registration.")

if __name__ == "__main__":
    logger.info(f"Starting {BOT_NAME} on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
