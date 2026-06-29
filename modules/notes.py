"""
Notes module — inspired by FallenRobot / Marie bot.

Commands:
  /save <name> <content>    Save a note (or reply to a message)
  /get <name>               Get a note
  #name                     Also triggers a note (checked in dispatcher)
  /delnote <name>           Delete a note (admin)
  /notes                    List all notes
"""

import re
import logging
from flask import request
from utils.api import api_request
from utils.helpers import is_admin, msg_id
from database.mongo import notes_col

logger = logging.getLogger(__name__)


def _mid():
    return msg_id(request.json)


def handle_save(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    parts = text.split(None, 2)
    message = request.json["message"]
    replied = message.get("reply_to_message")

    if len(parts) < 2:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/save <name> <content>` or reply to a message with `/save <name>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    name = parts[1].lower().strip()

    if len(parts) >= 3:
        content = parts[2].strip()
        note_type = "text"
    elif replied:
        if replied.get("text"):
            content = replied["text"]
            note_type = "text"
        elif replied.get("photo"):
            content = replied["photo"][-1]["file_id"]
            note_type = "photo"
            caption = replied.get("caption", "")
        elif replied.get("document"):
            content = replied["document"]["file_id"]
            note_type = "document"
            caption = replied.get("caption", "")
        elif replied.get("video"):
            content = replied["video"]["file_id"]
            note_type = "video"
            caption = replied.get("caption", "")
        elif replied.get("audio"):
            content = replied["audio"]["file_id"]
            note_type = "audio"
            caption = replied.get("caption", "")
        elif replied.get("sticker"):
            content = replied["sticker"]["file_id"]
            note_type = "sticker"
            caption = ""
        else:
            api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Cannot save this type of message.", "reply_to_message_id": mid})
            return
    else:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Provide content or reply to a message.", "reply_to_message_id": mid})
        return

    doc = {"chat_id": chat_id, "name": name, "content": content, "type": note_type}
    if note_type != "text":
        doc["caption"] = locals().get("caption", "")

    notes_col().update_one({"chat_id": chat_id, "name": name}, {"$set": doc}, upsert=True)
    api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ Note `{name}` saved. Retrieve it with `#{name}` or `/get {name}`.", "parse_mode": "Markdown", "reply_to_message_id": mid})


def handle_get(chat_id: int, name: str, reply_to: int = None):
    name = name.lower().strip()
    doc = notes_col().find_one({"chat_id": chat_id, "name": name})

    if not doc:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ No note named `{name}` found.", "parse_mode": "Markdown", **({"reply_to_message_id": reply_to} if reply_to else {})})
        return

    note_type = doc.get("type", "text")
    content = doc["content"]
    caption = doc.get("caption", "")
    kwargs = {**({"reply_to_message_id": reply_to} if reply_to else {})}

    if note_type == "text":
        api_request("sendMessage", {"chat_id": chat_id, "text": content, **kwargs})
    elif note_type == "photo":
        api_request("sendPhoto", {"chat_id": chat_id, "photo": content, "caption": caption, **kwargs})
    elif note_type == "document":
        api_request("sendDocument", {"chat_id": chat_id, "document": content, "caption": caption, **kwargs})
    elif note_type == "video":
        api_request("sendVideo", {"chat_id": chat_id, "video": content, "caption": caption, **kwargs})
    elif note_type == "audio":
        api_request("sendAudio", {"chat_id": chat_id, "audio": content, "caption": caption, **kwargs})
    elif note_type == "sticker":
        api_request("sendSticker", {"chat_id": chat_id, "sticker": content, **kwargs})


def handle_get_command(chat_id: int, text: str):
    mid = _mid()
    parts = text.split(None, 1)
    if len(parts) < 2:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/get <name>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return
    handle_get(chat_id, parts[1], reply_to=mid)


def handle_delnote(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    parts = text.split(None, 1)
    if len(parts) < 2:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/delnote <name>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    name = parts[1].lower().strip()
    result = notes_col().delete_one({"chat_id": chat_id, "name": name})

    if result.deleted_count:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ Note `{name}` deleted.", "parse_mode": "Markdown", "reply_to_message_id": mid})
    else:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ No note `{name}` found.", "parse_mode": "Markdown", "reply_to_message_id": mid})


def handle_notes_list(chat_id: int):
    mid = _mid()
    all_notes = list(notes_col().find({"chat_id": chat_id}, {"_id": 0, "name": 1}))
    if not all_notes:
        api_request("sendMessage", {"chat_id": chat_id, "text": "✅ No notes saved in this group.", "reply_to_message_id": mid})
        return

    out = "📝 *Saved Notes*\n\n" + "\n".join(f"• `#{n['name']}`" for n in all_notes)
    api_request("sendMessage", {"chat_id": chat_id, "text": out, "parse_mode": "Markdown", "reply_to_message_id": mid})


def check_note_trigger(chat_id: int, text: str, reply_to: int = None):
    """Called on every message. If text starts with #word, send that note."""
    if not text or not text.startswith("#"):
        return
    m = re.match(r"#(\w+)", text)
    if m:
        handle_get(chat_id, m.group(1), reply_to=reply_to)
