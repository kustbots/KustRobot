"""
Blacklist module — inspired by FallenRobot / Marie bot.

Commands:
  /addblacklist <word>    Add a word to the blacklist (admin)
  /rmblacklist <word>     Remove a word from the blacklist (admin)
  /blacklist              List blacklisted words (admin)

Auto-deletes messages containing blacklisted words and warns the user.
"""

import re
import logging
from flask import request
from utils.api import api_request
from utils.helpers import is_admin, get_chat_setting, msg_id
from database.mongo import blacklist_col, warnings_col, banned_users_col
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _mid():
    return msg_id(request.json)


def handle_addblacklist(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    parts = text.split(None, 1)
    if len(parts) < 2:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/addblacklist <word>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    word = parts[1].lower().strip()
    blacklist_col().update_one({"chat_id": chat_id}, {"$addToSet": {"words": word}}, upsert=True)
    api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ `{word}` added to blacklist.", "parse_mode": "Markdown", "reply_to_message_id": mid})


def handle_rmblacklist(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    parts = text.split(None, 1)
    if len(parts) < 2:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/rmblacklist <word>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    word = parts[1].lower().strip()
    blacklist_col().update_one({"chat_id": chat_id}, {"$pull": {"words": word}})
    api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ `{word}` removed from blacklist.", "parse_mode": "Markdown", "reply_to_message_id": mid})


def handle_blacklist_list(chat_id: int, user_id: int):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    doc = blacklist_col().find_one({"chat_id": chat_id})
    words = doc.get("words", []) if doc else []

    if not words:
        api_request("sendMessage", {"chat_id": chat_id, "text": "✅ No blacklisted words in this group.", "reply_to_message_id": mid})
        return

    out = "🚫 *Blacklisted Words*\n\n" + "\n".join(f"• `{w}`" for w in sorted(words))
    api_request("sendMessage", {"chat_id": chat_id, "text": out, "parse_mode": "Markdown", "reply_to_message_id": mid})


def check_blacklist(chat_id: int, message: dict) -> bool:
    """Return False if message contains a blacklisted word (and take action)."""
    uid = message.get("from", {}).get("id")
    if uid and is_admin(chat_id, uid):
        return True

    text = (message.get("text") or message.get("caption") or "").lower()
    if not text:
        return True

    doc = blacklist_col().find_one({"chat_id": chat_id})
    words = doc.get("words", []) if doc else []

    for word in words:
        if word in text:
            try:
                api_request("deleteMessage", {"chat_id": chat_id, "message_id": message["message_id"]})
            except Exception as e:
                logger.error(f"Blacklist delete error: {e}")

            threshold = get_chat_setting(chat_id, "warn_threshold", 3)
            result = warnings_col().find_one_and_update(
                {"chat_id": chat_id, "user_id": uid},
                {
                    "$push": {"reasons": {"reason": f"Blacklisted word: {word}", "ts": datetime.now(timezone.utc).isoformat()}},
                    "$inc": {"count": 1},
                },
                upsert=True,
                return_document=True,
            )
            count = (result.get("count", 0) + 1) if result else 1
            user_name = message.get("from", {}).get("first_name", "User")

            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"⚠️ {user_name}: message deleted for blacklisted word. Warning {count}/{threshold}.",
            })

            if count >= threshold:
                try:
                    api_request("banChatMember", {"chat_id": chat_id, "user_id": uid})
                    banned_users_col().update_one(
                        {"chat_id": chat_id, "user_id": uid},
                        {"$set": {"ts": datetime.now(timezone.utc).isoformat()}},
                        upsert=True,
                    )
                    api_request("sendMessage", {"chat_id": chat_id, "text": f"🚫 {user_name} banned for reaching {threshold} warnings."})
                except Exception as e:
                    logger.error(f"Blacklist auto-ban error: {e}")

            return False

    return True
