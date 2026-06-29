from flask import request
from utils.api import api_request
from utils.helpers import is_admin, get_chat_setting, set_chat_setting, msg_id


def _mid():
    return msg_id(request.json)


def handle_setrules(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    content = text.split("/setrules", 1)[1].strip() if "/setrules" in text else ""
    if not content:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/setrules <rules text>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    set_chat_setting(chat_id, "rules", content)
    api_request("sendMessage", {"chat_id": chat_id, "text": "✅ Group rules updated.", "reply_to_message_id": mid})


def handle_rules(chat_id: int):
    mid = _mid()
    rules = get_chat_setting(chat_id, "rules")
    if not rules:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ No rules set for this group.", "reply_to_message_id": mid})
        return

    api_request("sendMessage", {"chat_id": chat_id, "text": f"📜 *Group Rules*\n\n{rules}", "parse_mode": "Markdown", "reply_to_message_id": mid})


def handle_clearrules(chat_id: int, user_id: int):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    set_chat_setting(chat_id, "rules", None)
    api_request("sendMessage", {"chat_id": chat_id, "text": "✅ Group rules cleared.", "reply_to_message_id": mid})
