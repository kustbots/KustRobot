import re
import logging
from flask import request
from utils.api import api_request
from utils.helpers import is_admin, msg_id

logger = logging.getLogger(__name__)


def _mid():
    return msg_id(request.json)


def handle_pin(chat_id: int, user_id: int):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    replied = request.json["message"].get("reply_to_message")
    if not replied:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Reply to a message to pin it.", "reply_to_message_id": mid})
        return

    try:
        api_request("pinChatMessage", {"chat_id": chat_id, "message_id": replied["message_id"], "disable_notification": False})
        api_request("sendMessage", {"chat_id": chat_id, "text": "📌 Message pinned.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to pin: {e}", "reply_to_message_id": mid})


def handle_unpin(chat_id: int, user_id: int):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    try:
        api_request("unpinChatMessage", {"chat_id": chat_id})
        api_request("sendMessage", {"chat_id": chat_id, "text": "✅ Message unpinned.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to unpin: {e}", "reply_to_message_id": mid})


def handle_unpinall(chat_id: int, user_id: int):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    try:
        api_request("unpinAllChatMessages", {"chat_id": chat_id})
        api_request("sendMessage", {"chat_id": chat_id, "text": "✅ All messages unpinned.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed: {e}", "reply_to_message_id": mid})


def handle_purge(chat_id: int, user_id: int):
    """Purge messages from replied message up to the current one."""
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    replied = request.json["message"].get("reply_to_message")
    if not replied:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Reply to the first message you want to purge.", "reply_to_message_id": mid})
        return

    start_id = replied["message_id"]
    end_id = mid

    deleted = 0
    for message_id in range(start_id, end_id + 1):
        try:
            api_request("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
            deleted += 1
        except Exception:
            pass

    try:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ Purged {deleted} messages."})
    except Exception:
        pass


def handle_cleanup(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    m = re.search(r"\d+", text)
    if not m:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/cleanup <number>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    count = int(m.group())
    if count < 1 or count > 100:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Number must be between 1 and 100.", "reply_to_message_id": mid})
        return

    deleted = 0
    for offset in range(count):
        try:
            api_request("deleteMessage", {"chat_id": chat_id, "message_id": mid - offset})
            deleted += 1
        except Exception:
            pass

    try:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ Deleted {deleted} messages."})
    except Exception:
        pass


def handle_slowmode(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    m = re.search(r"\d+", text)
    if not m:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/slowmode <seconds>` (0 to disable)", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    seconds = int(m.group())
    try:
        api_request("setChatSlowModeDelay", {"chat_id": chat_id, "slow_mode_delay": seconds})
        msg = "✅ Slowmode disabled." if seconds == 0 else f"✅ Slowmode set to {seconds} seconds."
        api_request("sendMessage", {"chat_id": chat_id, "text": msg, "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed: {e}", "reply_to_message_id": mid})
