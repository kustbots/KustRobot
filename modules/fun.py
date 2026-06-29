import re
import random
import logging
import requests as http
from flask import request
from utils.api import api_request
from utils.helpers import msg_id

logger = logging.getLogger(__name__)


def _mid():
    return msg_id(request.json)


def _sender_name():
    return request.json["message"]["from"].get("first_name", "User")


def _target_name(text: str, command: str) -> str:
    replied = request.json["message"].get("reply_to_message")
    if replied and "from" in replied:
        u = replied["from"]
        return f"@{u['username']}" if u.get("username") else u.get("first_name", "someone")
    m = re.search(rf"/{command}(?:@\w+)?\s+@?(\w+)", text)
    return f"@{m.group(1)}" if m else "everyone"


def handle_roll(chat_id: int, text: str):
    mid = _mid()
    m = re.search(r"\d+", text.split("/roll", 1)[1]) if "/roll" in text else None
    sides = max(2, int(m.group()) if m else 6)
    result = random.randint(1, sides)
    api_request("sendMessage", {"chat_id": chat_id, "text": f"🎲 Rolled a **{result}** (1–{sides})", "parse_mode": "Markdown", "reply_to_message_id": mid})


def handle_8ball(chat_id: int, text: str):
    mid = _mid()
    question = text.split("/8ball", 1)[1].strip() if "/8ball" in text else ""
    if not question:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Ask me something! e.g. `/8ball Will I win?`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return
    responses = [
        "It is certain.", "It is decidedly so.", "Without a doubt.", "Yes, definitely.",
        "You may rely on it.", "As I see it, yes.", "Most likely.", "Outlook good.",
        "Yes.", "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
        "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
        "Don't count on it.", "My reply is no.", "My sources say no.",
        "Outlook not so good.", "Very doubtful.",
    ]
    api_request("sendMessage", {"chat_id": chat_id, "text": f"🎱 {random.choice(responses)}", "reply_to_message_id": mid})


def handle_hug(chat_id: int, text: str):
    mid = _mid()
    sender = _sender_name()
    target = _target_name(text, "hug")
    msgs = [
        f"{sender} gives {target} a warm hug! 🤗",
        f"{sender} hugs {target} tightly! 🫂",
        f"{sender} wraps {target} in a big bear hug! 🤗",
    ]
    api_request("sendMessage", {"chat_id": chat_id, "text": random.choice(msgs), "reply_to_message_id": mid})


def handle_slap(chat_id: int, text: str):
    mid = _mid()
    sender = _sender_name()
    target = _target_name(text, "slap")
    weapons = ["a large trout 🐟", "a wet noodle 🍜", "a rubber chicken 🐔", "a smelly fish 🐟", "a flip-flop 👡"]
    api_request("sendMessage", {"chat_id": chat_id, "text": f"{sender} slaps {target} with {random.choice(weapons)}!", "reply_to_message_id": mid})


def handle_pat(chat_id: int, text: str):
    mid = _mid()
    sender = _sender_name()
    target = _target_name(text, "pat")
    msgs = [
        f"{sender} pats {target} gently on the head! 👋",
        f"{sender} gives {target} a reassuring pat! 🤝",
        f"{sender} softly pats {target}! ✨",
    ]
    api_request("sendMessage", {"chat_id": chat_id, "text": random.choice(msgs), "reply_to_message_id": mid})


def handle_kiss(chat_id: int, text: str):
    mid = _mid()
    sender = _sender_name()
    target = _target_name(text, "kiss")
    msgs = [
        f"{sender} blows a kiss to {target}! 😘",
        f"{sender} gives {target} a sweet kiss! 💋",
    ]
    api_request("sendMessage", {"chat_id": chat_id, "text": random.choice(msgs), "reply_to_message_id": mid})


def handle_meme(chat_id: int):
    mid = _mid()
    try:
        resp = http.get("https://meme-api.com/gimme", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            url = data.get("url")
            title = data.get("title", "Random Meme")
            if url:
                api_request("sendPhoto", {"chat_id": chat_id, "photo": url, "caption": f"🤣 {title}", "reply_to_message_id": mid})
                return
    except Exception as e:
        logger.warning(f"Meme API error: {e}")

    fallbacks = [
        "When your code works on the first try 🤔",
        "Me: I'll just fix one bug. The bug: 🐛➡️🦎",
        "404: Sleep not found 😴",
        "99 bugs in the code... fix one... 127 bugs in the code 🤯",
        "When someone says 'it works on my machine' 💻",
    ]
    api_request("sendMessage", {"chat_id": chat_id, "text": random.choice(fallbacks), "reply_to_message_id": mid})


def handle_poll(chat_id: int, text: str):
    mid = _mid()
    raw = text.split("/poll", 1)[1].strip() if "/poll" in text else ""
    if not raw:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/poll <question>|option1|option2|...`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    parts = [p.strip() for p in raw.split("|") if p.strip()]
    if len(parts) < 3:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Please provide a question and at least 2 options.", "reply_to_message_id": mid})
        return

    question, options = parts[0], parts[1:]
    try:
        api_request("sendPoll", {"chat_id": chat_id, "question": question, "options": options, "is_anonymous": True, "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to create poll: {e}", "reply_to_message_id": mid})


def handle_stickerid(chat_id: int):
    mid = _mid()
    replied = request.json["message"].get("reply_to_message")
    if not replied or "sticker" not in replied:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Reply to a sticker to get its ID.", "reply_to_message_id": mid})
        return

    sticker = replied["sticker"]
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"🔖 File ID: `{sticker['file_id']}`\nEmoji: {sticker.get('emoji', '—')}",
        "parse_mode": "Markdown",
        "reply_to_message_id": mid,
    })


def handle_quote(chat_id: int):
    mid = _mid()
    quotes = [
        ("The only way to do great work is to love what you do.", "Steve Jobs"),
        ("Innovation distinguishes between a leader and a follower.", "Steve Jobs"),
        ("The future belongs to those who believe in the beauty of their dreams.", "Eleanor Roosevelt"),
        ("It does not matter how slowly you go as long as you do not stop.", "Confucius"),
        ("Life is what happens when you're busy making other plans.", "John Lennon"),
        ("You only live once, but if you do it right, once is enough.", "Mae West"),
        ("In the middle of every difficulty lies opportunity.", "Albert Einstein"),
        ("The best time to plant a tree was 20 years ago. The second best time is now.", "Chinese Proverb"),
        ("Believe you can and you're halfway there.", "Theodore Roosevelt"),
        ("Efficiency is doing better what is already being done.", "Peter Drucker"),
    ]
    quote, author = random.choice(quotes)
    api_request("sendMessage", {"chat_id": chat_id, "text": f"💭 *{quote}*\n\n— _{author}_", "parse_mode": "Markdown", "reply_to_message_id": mid})


def handle_flip(chat_id: int):
    mid = _mid()
    result = random.choice(["🪙 Heads!", "🪙 Tails!"])
    api_request("sendMessage", {"chat_id": chat_id, "text": result, "reply_to_message_id": mid})


def handle_toss(chat_id: int):
    handle_flip(chat_id)
