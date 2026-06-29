import re
import logging
from flask import request
from utils.api import api_request
from utils.helpers import is_admin, get_chat_setting, set_chat_setting, msg_id
from database.mongo import filters_col

logger = logging.getLogger(__name__)


def _mid():
    return msg_id(request.json)


# ── Lock / Unlock ─────────────────────────────────────────────────────────────

_LOCK_TYPES = ("links", "media", "stickers", "all", "forward", "polls")


def handle_lock(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    m = re.search(r"/lock\s+(\w+)", text.lower())
    if not m or m.group(1) not in _LOCK_TYPES:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Usage: `/lock <{' | '.join(_LOCK_TYPES)}>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    lock_type = m.group(1)
    if lock_type == "all":
        for t in _LOCK_TYPES[:-1]:
            set_chat_setting(chat_id, f"lock_{t}", True)
    else:
        set_chat_setting(chat_id, f"lock_{lock_type}", True)

    api_request("sendMessage", {"chat_id": chat_id, "text": f"🔒 {lock_type.capitalize()} locked.", "reply_to_message_id": mid})


def handle_unlock(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    m = re.search(r"/unlock\s+(\w+)", text.lower())
    if not m or m.group(1) not in _LOCK_TYPES:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Usage: `/unlock <{' | '.join(_LOCK_TYPES)}>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    lock_type = m.group(1)
    if lock_type == "all":
        for t in _LOCK_TYPES[:-1]:
            set_chat_setting(chat_id, f"lock_{t}", False)
    else:
        set_chat_setting(chat_id, f"lock_{lock_type}", False)

    api_request("sendMessage", {"chat_id": chat_id, "text": f"🔓 {lock_type.capitalize()} unlocked.", "reply_to_message_id": mid})


def handle_locks(chat_id: int, user_id: int):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    out = "🔒 *Lock Status*\n\n"
    for t in _LOCK_TYPES[:-1]:
        state = "🔒 Locked" if get_chat_setting(chat_id, f"lock_{t}", False) else "🔓 Open"
        out += f"• {t.capitalize()}: {state}\n"

    api_request("sendMessage", {"chat_id": chat_id, "text": out, "parse_mode": "Markdown", "reply_to_message_id": mid})


# ── Content check (called on every message) ───────────────────────────────────

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def check_message_content(chat_id: int, message: dict) -> bool:
    """Return False if message violates active locks (should be deleted)."""
    uid = message.get("from", {}).get("id")
    if uid and is_admin(chat_id, uid):
        return True

    if get_chat_setting(chat_id, "lock_links", False):
        text = message.get("text", "") or message.get("caption", "")
        entities = message.get("entities", []) + message.get("caption_entities", [])
        for e in entities:
            if e["type"] in ("url", "text_link"):
                return False
        if _URL_RE.search(text):
            return False

    if get_chat_setting(chat_id, "lock_media", False):
        if any(k in message for k in ("photo", "video", "audio", "document", "animation", "video_note", "voice")):
            return False

    if get_chat_setting(chat_id, "lock_stickers", False):
        if "sticker" in message:
            return False

    if get_chat_setting(chat_id, "lock_forward", False):
        if "forward_from" in message or "forward_from_chat" in message:
            return False

    if get_chat_setting(chat_id, "lock_polls", False):
        if "poll" in message:
            return False

    return True


# ── Custom filters (FallenRobot-style: /filter keyword response) ──────────────

def handle_add_filter(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    parts = text.split(None, 2)
    if len(parts) < 3:
        replied = request.json["message"].get("reply_to_message")
        if replied and len(parts) >= 2:
            keyword = parts[1].lower().strip()
            response = replied.get("text", "")
        else:
            api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/filter <keyword> <response>` or reply to a message.", "parse_mode": "Markdown", "reply_to_message_id": mid})
            return
    else:
        keyword = parts[1].lower().strip()
        response = parts[2].strip()

    if not keyword or not response:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Keyword and response cannot be empty.", "reply_to_message_id": mid})
        return

    filters_col().update_one(
        {"chat_id": chat_id, "keyword": keyword},
        {"$set": {"response": response}},
        upsert=True,
    )
    api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ Filter `{keyword}` saved.", "parse_mode": "Markdown", "reply_to_message_id": mid})


def handle_stop_filter(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    parts = text.split(None, 1)
    if len(parts) < 2:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/stop <keyword>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    keyword = parts[1].lower().strip()
    result = filters_col().delete_one({"chat_id": chat_id, "keyword": keyword})

    if result.deleted_count:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ Filter `{keyword}` removed.", "parse_mode": "Markdown", "reply_to_message_id": mid})
    else:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ No filter `{keyword}` found.", "parse_mode": "Markdown", "reply_to_message_id": mid})


def handle_list_filters(chat_id: int, user_id: int):
    mid = _mid()
    all_filters = list(filters_col().find({"chat_id": chat_id}, {"_id": 0, "keyword": 1}))
    if not all_filters:
        api_request("sendMessage", {"chat_id": chat_id, "text": "✅ No active filters in this group.", "reply_to_message_id": mid})
        return

    out = "📋 *Active Filters*\n\n" + "\n".join(f"• `{f['keyword']}`" for f in all_filters)
    api_request("sendMessage", {"chat_id": chat_id, "text": out, "parse_mode": "Markdown", "reply_to_message_id": mid})


def check_filters(chat_id: int, message: dict):
    """Trigger any matching filter response for the message text."""
    text = (message.get("text") or message.get("caption") or "").lower()
    if not text:
        return

    all_filters = list(filters_col().find({"chat_id": chat_id}))
    for f in all_filters:
        if f["keyword"] in text:
            try:
                api_request("sendMessage", {"chat_id": chat_id, "text": f["response"], "reply_to_message_id": message.get("message_id")})
            except Exception as e:
                logger.error(f"Filter response error: {e}")
            break
