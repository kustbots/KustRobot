import re
import time
import logging
from typing import Any, Optional, Tuple
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
_rate_cache: dict = {}


def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    if now - _rate_cache.get(user_id, 0) < 2:
        return False
    _rate_cache[user_id] = now
    return True


def is_admin(chat_id: int, user_id: int) -> bool:
    from utils.api import api_request
    if user_id in ADMIN_IDS:
        return True
    try:
        admins = api_request("getChatAdministrators", {"chat_id": chat_id})
        return any(a["user"]["id"] == user_id for a in admins)
    except Exception as e:
        logger.error(f"is_admin error: {e}")
        return False


def get_chat_setting(chat_id: int, key: str, default=None) -> Any:
    from database.mongo import chat_settings_col
    doc = chat_settings_col().find_one({"chat_id": chat_id}, {"_id": 0})
    if doc:
        return doc.get(key, default)
    return default


def set_chat_setting(chat_id: int, key: str, value: Any):
    from database.mongo import chat_settings_col
    chat_settings_col().update_one(
        {"chat_id": chat_id},
        {"$set": {key: value}},
        upsert=True,
    )


def resolve_target(message: dict, text: str, command: str) -> Tuple[Optional[int], str]:
    """Return (user_id, display_name) from reply or @username/id in command text."""
    from utils.api import api_request

    replied = message.get("reply_to_message")
    if replied and "from" in replied:
        u = replied["from"]
        return u["id"], u.get("first_name", "Unknown")

    match = re.search(rf"/{command}(?:@\w+)?\s+@?(\w+)", text)
    if not match:
        return None, ""

    raw = match.group(1)

    try:
        uid = int(raw)
        return uid, str(uid)
    except ValueError:
        pass

    try:
        chat_id = message["chat"]["id"]
        admins = api_request("getChatAdministrators", {"chat_id": chat_id})
        for a in admins:
            if a["user"].get("username", "").lower() == raw.lower():
                u = a["user"]
                return u["id"], u.get("first_name", raw)
    except Exception:
        pass

    return None, raw


def parse_time_arg(text: str) -> Optional[int]:
    """Parse duration string like 10m, 2h, 1d into seconds. Returns None if invalid."""
    m = re.search(r"(\d+)\s*([smhd])", text.lower())
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return amount * multipliers[unit]


def msg_id(request_json: dict) -> Optional[int]:
    try:
        return request_json["message"]["message_id"]
    except (KeyError, TypeError):
        return None
