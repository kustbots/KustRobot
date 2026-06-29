import re
import threading
import logging
from datetime import datetime, timezone
from flask import request
from utils.api import api_request
from utils.helpers import is_admin, get_chat_setting, set_chat_setting, resolve_target, parse_time_arg, msg_id
from database.mongo import warnings_col, banned_users_col

logger = logging.getLogger(__name__)


def _mid():
    return msg_id(request.json)


# ── Warn ──────────────────────────────────────────────────────────────────────

def handle_warn(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    message = request.json["message"]
    target_id, target_name = resolve_target(message, text, "warn")

    reason_match = re.search(r"/warn(?:@\w+)?(?:\s+@?\w+)?\s*(.*)", text, re.DOTALL)
    reason = (reason_match.group(1).strip() if reason_match and reason_match.group(1).strip() else "No reason provided")

    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Reply to a user or use `/warn @user <reason>`.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    if is_admin(chat_id, target_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Cannot warn an admin.", "reply_to_message_id": mid})
        return

    threshold = get_chat_setting(chat_id, "warn_threshold", 3)

    result = warnings_col().find_one_and_update(
        {"chat_id": chat_id, "user_id": target_id},
        {
            "$push": {"reasons": {"reason": reason, "ts": datetime.now(timezone.utc).isoformat()}},
            "$inc": {"count": 1},
        },
        upsert=True,
        return_document=True,
    )
    count = (result.get("count", 0) + 1) if result else 1

    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"⚠️ {target_name} warned ({count}/{threshold})\nReason: {reason}",
        "reply_to_message_id": mid,
    })

    if count >= threshold:
        try:
            api_request("banChatMember", {"chat_id": chat_id, "user_id": target_id})
            banned_users_col().update_one(
                {"chat_id": chat_id, "user_id": target_id},
                {"$set": {"ts": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            )
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"🚫 {target_name} has been auto-banned for reaching {threshold} warnings.",
            })
        except Exception as e:
            logger.error(f"Auto-ban error: {e}")


def handle_unwarn(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "unwarn")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Reply to a user or use `/unwarn @user`.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    doc = warnings_col().find_one({"chat_id": chat_id, "user_id": target_id})
    if not doc or doc.get("count", 0) == 0:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ {target_name} has no warnings.", "reply_to_message_id": mid})
        return

    reasons = doc.get("reasons", [])
    if reasons:
        reasons.pop()
    new_count = max(0, doc.get("count", 1) - 1)
    warnings_col().update_one({"chat_id": chat_id, "user_id": target_id}, {"$set": {"count": new_count, "reasons": reasons}})

    api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ One warning removed from {target_name}. Now has {new_count} warning(s).", "reply_to_message_id": mid})


def handle_warnings(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "warnings")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Reply to a user or use `/warnings @user`.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    threshold = get_chat_setting(chat_id, "warn_threshold", 3)
    doc = warnings_col().find_one({"chat_id": chat_id, "user_id": target_id})

    if not doc or doc.get("count", 0) == 0:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ {target_name} has no warnings.", "reply_to_message_id": mid})
        return

    count = doc.get("count", 0)
    reasons = doc.get("reasons", [])
    out = f"⚠️ {target_name}: {count}/{threshold} warnings\n\n"
    for i, r in enumerate(reasons, 1):
        out += f"{i}. {r.get('reason', '—')} ({r.get('ts', '')[:10]})\n"

    api_request("sendMessage", {"chat_id": chat_id, "text": out, "reply_to_message_id": mid})


def handle_clearwarns(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "clearwarns")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Reply to a user or use `/clearwarns @user`.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    warnings_col().delete_one({"chat_id": chat_id, "user_id": target_id})
    api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ All warnings cleared for {target_name}.", "reply_to_message_id": mid})


def handle_setwarnlimit(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    m = re.search(r"\d+", text)
    if not m or int(m.group()) < 1:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/setwarnlimit <number>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    limit = int(m.group())
    set_chat_setting(chat_id, "warn_threshold", limit)
    api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ Warn limit set to {limit}.", "reply_to_message_id": mid})


# ── Ban / Unban ───────────────────────────────────────────────────────────────

def handle_ban(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "ban")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/ban @user` or reply to a message.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    if is_admin(chat_id, target_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Cannot ban an admin.", "reply_to_message_id": mid})
        return

    try:
        api_request("banChatMember", {"chat_id": chat_id, "user_id": target_id})
        banned_users_col().update_one(
            {"chat_id": chat_id, "user_id": target_id},
            {"$set": {"ts": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        api_request("sendMessage", {"chat_id": chat_id, "text": f"🚫 {target_name} has been banned.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to ban: {e}", "reply_to_message_id": mid})


def handle_tban(chat_id: int, user_id: int, text: str):
    """Timed ban: /tban @user 1h reason"""
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "tban")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/tban @user 1h <reason>` (s/m/h/d)", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    if is_admin(chat_id, target_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Cannot ban an admin.", "reply_to_message_id": mid})
        return

    duration = parse_time_arg(text)
    if not duration:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Provide a time (e.g. 10m, 2h, 1d).", "reply_to_message_id": mid})
        return

    import time as _time
    until_date = int(_time.time()) + duration

    try:
        api_request("banChatMember", {"chat_id": chat_id, "user_id": target_id, "until_date": until_date})
        api_request("sendMessage", {"chat_id": chat_id, "text": f"🚫 {target_name} has been temporarily banned for {_fmt_duration(duration)}.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to tban: {e}", "reply_to_message_id": mid})


def handle_unban(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "unban")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/unban @user` or provide user ID.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    try:
        api_request("unbanChatMember", {"chat_id": chat_id, "user_id": target_id, "only_if_banned": True})
        banned_users_col().delete_one({"chat_id": chat_id, "user_id": target_id})
        api_request("sendMessage", {"chat_id": chat_id, "text": f"✅ {target_name} has been unbanned.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to unban: {e}", "reply_to_message_id": mid})


# ── Kick ──────────────────────────────────────────────────────────────────────

def handle_kick(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "kick")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/kick @user` or reply to a message.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    if is_admin(chat_id, target_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Cannot kick an admin.", "reply_to_message_id": mid})
        return

    try:
        api_request("banChatMember", {"chat_id": chat_id, "user_id": target_id})
        api_request("unbanChatMember", {"chat_id": chat_id, "user_id": target_id, "only_if_banned": True})
        api_request("sendMessage", {"chat_id": chat_id, "text": f"👢 {target_name} has been kicked.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to kick: {e}", "reply_to_message_id": mid})


# ── Mute / Unmute ─────────────────────────────────────────────────────────────

_MUTE_PERMS = {
    "can_send_messages": False,
    "can_send_media_messages": False,
    "can_send_polls": False,
    "can_send_other_messages": False,
    "can_add_web_page_previews": False,
}

_UNMUTE_PERMS = {
    "can_send_messages": True,
    "can_send_media_messages": True,
    "can_send_polls": True,
    "can_send_other_messages": True,
    "can_add_web_page_previews": True,
}


def handle_mute(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "mute")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/mute @user` or reply to a message.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    if is_admin(chat_id, target_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Cannot mute an admin.", "reply_to_message_id": mid})
        return

    try:
        api_request("restrictChatMember", {"chat_id": chat_id, "user_id": target_id, "permissions": _MUTE_PERMS})
        api_request("sendMessage", {"chat_id": chat_id, "text": f"🔇 {target_name} has been muted.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to mute: {e}", "reply_to_message_id": mid})


def handle_tmute(chat_id: int, user_id: int, text: str):
    """Timed mute: /tmute @user 30m reason"""
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "tmute")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/tmute @user 30m <reason>`", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    if is_admin(chat_id, target_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Cannot mute an admin.", "reply_to_message_id": mid})
        return

    duration = parse_time_arg(text)
    if not duration:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Provide a time (e.g. 10m, 2h, 1d).", "reply_to_message_id": mid})
        return

    import time as _time
    until_date = int(_time.time()) + duration

    try:
        api_request("restrictChatMember", {"chat_id": chat_id, "user_id": target_id, "permissions": _MUTE_PERMS, "until_date": until_date})
        api_request("sendMessage", {"chat_id": chat_id, "text": f"🔇 {target_name} muted for {_fmt_duration(duration)}.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to tmute: {e}", "reply_to_message_id": mid})


def handle_unmute(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "unmute")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/unmute @user` or reply to a message.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    try:
        api_request("restrictChatMember", {"chat_id": chat_id, "user_id": target_id, "permissions": _UNMUTE_PERMS})
        api_request("sendMessage", {"chat_id": chat_id, "text": f"🔊 {target_name} has been unmuted.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to unmute: {e}", "reply_to_message_id": mid})


# ── Promote / Demote ──────────────────────────────────────────────────────────

def handle_promote(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "promote")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/promote @user` or reply to a message.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    try:
        api_request("promoteChatMember", {
            "chat_id": chat_id,
            "user_id": target_id,
            "can_change_info": True,
            "can_delete_messages": True,
            "can_invite_users": True,
            "can_restrict_members": True,
            "can_pin_messages": True,
            "can_promote_members": False,
        })
        api_request("sendMessage", {"chat_id": chat_id, "text": f"⬆️ {target_name} has been promoted to admin.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to promote: {e}", "reply_to_message_id": mid})


def handle_demote(chat_id: int, user_id: int, text: str):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    target_id, target_name = resolve_target(request.json["message"], text, "demote")
    if not target_id:
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Usage: `/demote @user` or reply to a message.", "parse_mode": "Markdown", "reply_to_message_id": mid})
        return

    try:
        api_request("promoteChatMember", {
            "chat_id": chat_id,
            "user_id": target_id,
            "can_change_info": False,
            "can_delete_messages": False,
            "can_invite_users": False,
            "can_restrict_members": False,
            "can_pin_messages": False,
            "can_promote_members": False,
        })
        api_request("sendMessage", {"chat_id": chat_id, "text": f"⬇️ {target_name} has been demoted.", "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed to demote: {e}", "reply_to_message_id": mid})


# ── Lists ─────────────────────────────────────────────────────────────────────

def handle_banlist(chat_id: int, user_id: int):
    mid = _mid()
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {"chat_id": chat_id, "text": "❌ Admins only.", "reply_to_message_id": mid})
        return

    bans = list(banned_users_col().find({"chat_id": chat_id}, {"_id": 0}))
    if not bans:
        api_request("sendMessage", {"chat_id": chat_id, "text": "✅ No banned users in this group.", "reply_to_message_id": mid})
        return

    out = f"🚫 Banned Users ({len(bans)}):\n\n"
    for b in bans:
        out += f"• ID: `{b['user_id']}` — {b.get('ts', 'unknown')[:10]}\n"

    api_request("sendMessage", {"chat_id": chat_id, "text": out, "parse_mode": "Markdown", "reply_to_message_id": mid})


def handle_getadmins(chat_id: int, user_id: int):
    mid = _mid()
    try:
        admins = api_request("getChatAdministrators", {"chat_id": chat_id})
        out = f"👥 Administrators ({len(admins)}):\n\n"
        for a in admins:
            u = a["user"]
            name = u.get("first_name", "Unknown")
            uname = f" (@{u['username']})" if u.get("username") else ""
            role = "Creator" if a.get("status") == "creator" else "Admin"
            out += f"• {name}{uname} — {role}\n"
        api_request("sendMessage", {"chat_id": chat_id, "text": out, "reply_to_message_id": mid})
    except Exception as e:
        api_request("sendMessage", {"chat_id": chat_id, "text": f"❌ Failed: {e}", "reply_to_message_id": mid})


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"
