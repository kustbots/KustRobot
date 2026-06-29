import re
import threading
import logging
import time
import random
from flask import request
from utils.api import api_request
from utils.helpers import is_admin, get_chat_setting, set_chat_setting, msg_id
from database.mongo import captcha_col

logger = logging.getLogger(__name__)


def _mid():
    return msg_id(request.json)


# ── Welcome ───────────────────────────────────────────────────────────────────

def handle_setwelcome(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    content = text.split("/setwelcome", 1)[1].strip() if "/setwelcome" in text else ""
    if not content:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/setwelcome <message>`\n\nPlaceholders: `{name}` `{id}` `{title}`",
            "parse_mode": "Markdown",
            "reply_to_message_id": mid,
        })
        return

    set_chat_setting(chat_id, "welcome_message", content)
    api_request("sendMessage", {"chat_id": chat_id, "text": "✅ Welcome message updated.", "reply_to_message_id": mid})


def handle_welcome_toggle(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    m = re.search(r"\b(on|off)\b", text.lower())
    if not m:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/welcome on` or `/welcome off`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    enabled = m.group(1) == "on"
    set_chat_setting(chat_id, "welcome_enabled", enabled)
    api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ Welcome messages {'enabled' if enabled else 'disabled'}.", "reply_to_message_id": mid})


# ── Captcha ───────────────────────────────────────────────────────────────────

def handle_setcaptcha(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    m = re.search(r"\b(on|off)\b", text.lower())
    if not m:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/setcaptcha on` or `/setcaptcha off`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    enabled = m.group(1) == "on"
    set_chat_setting(chat_id, "captcha_enabled", enabled)
    api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ Captcha {'enabled' if enabled else 'disabled'}.", "reply_to_message_id": mid})


def _generate_captcha():
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    op = random.choice(["+", "-", "*"])
    if op == "+":
        answer = a + b
    elif op == "-":
        answer = a - b
    else:
        answer = a * b
    return f"What is {a} {op} {b}?", str(answer)


def _send_captcha(chat_id: int, user_id: int, user_name: str):
    challenge, answer = _generate_captcha()

    wrong1 = str(int(answer) + random.choice([-1, 1, 2, -2]))
    wrong2 = str(int(answer) + random.choice([3, -3, 4, -4]))

    options = [answer, wrong1, wrong2]
    random.shuffle(options)

    keyboard = {"inline_keyboard": [[
        {"text": opt, "callback_data": f"cap_{user_id}_{opt}_{answer}"}
        for opt in options
    ]]}

    captcha_col().update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": {"answer": answer}},
        upsert=True,
    )

    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"👋 Welcome {user_name}!\n🤖 Solve this to prove you're human:\n\n{challenge}",
        "reply_markup": __import__("json").dumps(keyboard),
    })

    def _kick_unverified():
        time.sleep(300)
        if captcha_col().find_one({"chat_id": chat_id, "user_id": user_id}):
            try:
                api_request("banChatMember", {"chat_id": chat_id, "user_id": user_id})
                api_request("unbanChatMember", {"chat_id": chat_id, "user_id": user_id, "only_if_banned": True})
                api_request("sendMessage", {"chat_id": chat_id, "text": f"🚫 {user_name} was removed for not solving the captcha."})
            except Exception as e:
                logger.error(f"Captcha kick error: {e}")
            captcha_col().delete_one({"chat_id": chat_id, "user_id": user_id})

    threading.Thread(target=_kick_unverified, daemon=True).start()


def handle_captcha_callback(callback_query: dict):
    data = callback_query.get("data", "")
    if not data.startswith("cap_"):
        return

    parts = data.split("_")
    if len(parts) < 4:
        return

    _, target_uid_str, chosen, correct = parts[0], parts[1], parts[2], parts[3]
    respondent_id = callback_query["from"]["id"]
    respondent_name = callback_query["from"].get("first_name", "User")
    chat_id = callback_query["message"]["chat"]["id"]
    cb_id = callback_query["id"]

    try:
        target_uid = int(target_uid_str)
    except ValueError:
        return

    if respondent_id != target_uid:
        api_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "❌ This captcha is not for you.", "show_alert": True})
        return

    api_request("answerCallbackQuery", {"callback_query_id": cb_id})

    if chosen == correct:
        captcha_col().delete_one({"chat_id": chat_id, "user_id": target_uid})
        api_request("editMessageText", {
            "chat_id": chat_id,
            "message_id": callback_query["message"]["message_id"],
            "text": f"✅ {respondent_name} verified successfully! Welcome to the group.",
        })
    else:
        api_request("editMessageText", {
            "chat_id": chat_id,
            "message_id": callback_query["message"]["message_id"],
            "text": f"❌ Wrong answer! {respondent_name} will be removed in 5 minutes if not verified.",
        })


# ── New member handler ────────────────────────────────────────────────────────

def handle_new_member(chat_id: int, new_member: dict):
    user_id = new_member["id"]
    user_name = new_member.get("first_name", "User")

    if get_chat_setting(chat_id, "welcome_enabled", True):
        welcome_msg = get_chat_setting(chat_id, "welcome_message") or f"Welcome {user_name} to the group! Please read the rules."
        try:
            chat_info = api_request("getChat", {"chat_id": chat_id})
            chat_title = chat_info.get("title", "the group")
        except Exception:
            chat_title = "the group"

        welcome_msg = (
            welcome_msg
            .replace("{name}", user_name)
            .replace("{id}", str(user_id))
            .replace("{title}", chat_title)
        )
        api_request("sendMessage", {"chat_id": chat_id, "text": welcome_msg})

    if get_chat_setting(chat_id, "captcha_enabled", False):
        _send_captcha(chat_id, user_id, user_name)
