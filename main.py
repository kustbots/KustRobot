"""
Kust Robot - A Telegram Group Management Bot

"Efficiency is doing better what is already being done."
— Peter Drucker

References:
- Official Telegram Bot API: https://core.telegram.org/bots/api
- setWebhook documentation: https://core.telegram.org/bots/api#setwebhook
- Available methods: https://core.telegram.org/bots/api#available-methods

README:
This bot requires Python 3.7+ and the following packages:
- Flask: Web framework for handling webhook requests
- requests: For making HTTP requests to Telegram Bot API
- sqlite3: For data storage (built-in)

Setup:
1. Install dependencies:
   pip install flask requests

2. Set environment variables:
   - BOT_TOKEN: Your Telegram bot token from @BotFather
   - WEBHOOK_URL: URL where your bot will receive updates (e.g., https://yourdomain.com/webhook/SECRET)
   - WEBHOOK_SECRET: A secret string to secure your webhook endpoint
   - ADMIN_IDS: Comma-separated list of admin user IDs (e.g., "123456789,987654321")
   - PORT: Port to run the web server on (default: 5000)

3. Run the bot:
   python kust_robot_bot.py

4. Set the webhook using curl:
   curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
        -H "Content-Type: application/json" \
        -d '{"url": "https://yourdomain.com/webhook/<WEBHOOK_SECRET>", "secret_token": "<WEBHOOK_SECRET>"}'

5. Validate the webhook:
   The bot will validate incoming requests using either the secret path or the X-Telegram-Bot-Api-Secret-Token header.

Troubleshooting:
- 401 Unauthorized: Check your BOT_TOKEN is correct
- 403 Forbidden: Make sure the bot is added to the group and has admin rights
- Webhook not working: Ensure your server is accessible via HTTPS and the URL is correct
- Bot not responding: Check logs for errors, make sure webhook is set correctly
- Webhook retries: Telegram will retry failed deliveries up to 3 times with increasing delays
"""

import os
import sys
import json
import time
import logging
import sqlite3
import threading
import re
import random
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union, Any

import requests
from flask import Flask, request, jsonify, abort

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "297310471047")
ADMIN_IDS = set(map(int, os.getenv("ADMIN_IDS", "5268762773").split(","))) if os.getenv("ADMIN_IDS") else set()
PORT = int(os.getenv("PORT", 5000))

# Database setup
DB_PATH = "kust_robot.db"

# Rate limiting
user_last_command = {}

# Bot info
BOT_NAME = "Kust Robot"
UPDATES_CHANNEL = "https://t.me/kustbots"
SUPPORT_GROUP = "https://t.me/kustbotschat"

# API helper function
def api_request(method: str, params: Dict[str, Any] = None, files: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Make a request to the Telegram Bot API with error handling and retries.
    
    Args:
        method: The API method to call (e.g., "sendMessage")
        params: Parameters to send with the request
        files: Files to upload (if any)
    
    Returns:
        The JSON response from the API
    
    Raises:
        Exception: If the API request fails after retries
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    params = params or {}
    
    # Log the request
    logger.info(f"API Request: {method}, Params: {params}")
    
    # Retry logic with exponential backoff
    max_retries = 5
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            if files:
                response = requests.post(url, params=params, files=files, timeout=10)
            else:
                response = requests.post(url, json=params, timeout=10)
            
            # Check for successful response
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    return result.get("result", {})
                else:
                    logger.error(f"API Error: {result}")
                    raise Exception(f"API Error: {result.get('description', 'Unknown error')}")
            
            # Handle rate limiting (429)
            elif response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", retry_delay))
                logger.warning(f"Rate limited. Retrying after {retry_after} seconds...")
                time.sleep(retry_after)
                retry_delay *= 2  # Exponential backoff
                continue
            
            # Handle server errors (5xx)
            elif 500 <= response.status_code < 600:
                logger.warning(f"Server error ({response.status_code}). Retrying...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            
            # Handle other errors
            else:
                logger.error(f"HTTP Error: {response.status_code} - {response.text}")
                raise Exception(f"HTTP Error: {response.status_code}")
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Request Exception: {e}")
            if attempt == max_retries - 1:
                raise Exception(f"Request failed after {max_retries} attempts: {e}")
            time.sleep(retry_delay)
            retry_delay *= 2
    
    raise Exception(f"API request failed after {max_retries} attempts")

# Database functions
def get_db_connection():
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with required tables."""
    with get_db_connection() as conn:
        # Chat settings table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id INTEGER PRIMARY KEY,
            welcome_message TEXT,
            welcome_enabled BOOLEAN DEFAULT 1,
            rules TEXT,
            captcha_enabled BOOLEAN DEFAULT 0,
            warn_threshold INTEGER DEFAULT 3,
            lock_links BOOLEAN DEFAULT 0,
            lock_media BOOLEAN DEFAULT 0,
            lock_stickers BOOLEAN DEFAULT 0,
            lock_all BOOLEAN DEFAULT 0,
            slowmode INTEGER DEFAULT 0,
            language TEXT DEFAULT 'en'
        )
        """)
        
        # User warnings table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            reason TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id, user_id)
        )
        """)
        
        # Banned users table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            chat_id INTEGER,
            user_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(chat_id, user_id)
        )
        """)
        
        # Captcha challenges table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS captcha_challenges (
            chat_id INTEGER,
            user_id INTEGER,
            challenge TEXT,
            answer TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(chat_id, user_id)
        )
        """)
        
        # Backup data table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS backup_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            data TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        conn.commit()

# Rate limiting
def check_rate_limit(user_id: int) -> bool:
    """
    Check if a user has exceeded the rate limit for commands.
    
    Args:
        user_id: The user's Telegram ID
    
    Returns:
        True if the user is allowed to execute a command, False otherwise
    """
    current_time = time.time()
    last_command_time = user_last_command.get(user_id, 0)
    
    # Allow 1 command per 2 seconds
    if current_time - last_command_time < 2:
        return False
    
    user_last_command[user_id] = current_time
    return True

# Helper functions
def is_admin(chat_id: int, user_id: int) -> bool:
    """
    Check if a user is an admin in the specified chat.
    
    Args:
        chat_id: The chat ID
        user_id: The user ID
    
    Returns:
        True if the user is an admin, False otherwise
    """
    # Global admins are always admins
    if user_id in ADMIN_IDS:
        return True
    
    try:
        admins = api_request("getChatAdministrators", {"chat_id": chat_id})
        for admin in admins:
            if admin["user"]["id"] == user_id:
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

def get_chat_setting(chat_id: int, setting: str, default=None):
    """
    Get a setting for a specific chat.
    
    Args:
        chat_id: The chat ID
        setting: The setting name
        default: Default value if setting is not found
    
    Returns:
        The setting value or default
    """
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,)).fetchone()
        if row:
            return row[setting]
        return default

def set_chat_setting(chat_id: int, setting: str, value):
    """
    Set a setting for a specific chat.
    
    Args:
        chat_id: The chat ID
        setting: The setting name
        value: The value to set
    """
    with get_db_connection() as conn:
        # Check if chat exists in DB
        row = conn.execute("SELECT 1 FROM chat_settings WHERE chat_id = ?", (chat_id,)).fetchone()
        
        if row:
            # Update existing setting
            conn.execute(f"UPDATE chat_settings SET {setting} = ? WHERE chat_id = ?", (value, chat_id))
        else:
            # Insert new chat with default settings
            conn.execute(f"INSERT INTO chat_settings (chat_id, {setting}) VALUES (?, ?)", (chat_id, value))
        
        conn.commit()

def add_warning(chat_id: int, user_id: int, reason: str) -> int:
    """
    Add a warning to a user.
    
    Args:
        chat_id: The chat ID
        user_id: The user ID
        reason: The reason for the warning
    
    Returns:
        The new warning count for the user
    """
    with get_db_connection() as conn:
        # Check if user already has warnings
        row = conn.execute("SELECT COUNT(*) as count FROM user_warnings WHERE chat_id = ? AND user_id = ?", 
                          (chat_id, user_id)).fetchone()
        warning_count = row["count"]
        
        # Add new warning
        conn.execute("INSERT INTO user_warnings (chat_id, user_id, reason) VALUES (?, ?, ?)",
                    (chat_id, user_id, reason))
        conn.commit()
        
        return warning_count + 1

def get_warnings(chat_id: int, user_id: int) -> List[Dict[str, Any]]:
    """
    Get all warnings for a user in a chat.
    
    Args:
        chat_id: The chat ID
        user_id: The user ID
    
    Returns:
        List of warnings
    """
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM user_warnings WHERE chat_id = ? AND user_id = ? ORDER BY timestamp DESC",
                          (chat_id, user_id)).fetchall()
        return [dict(row) for row in rows]

def clear_warnings(chat_id: int, user_id: int):
    """
    Clear all warnings for a user in a chat.
    
    Args:
        chat_id: The chat ID
        user_id: The user ID
    """
    with get_db_connection() as conn:
        conn.execute("DELETE FROM user_warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        conn.commit()

def generate_captcha() -> Tuple[str, str]:
    """
    Generate a simple math captcha challenge.
    
    Returns:
        A tuple of (challenge, answer)
    """
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    operations = ['+', '-', '*']
    op = random.choice(operations)
    
    if op == '+':
        answer = str(a + b)
    elif op == '-':
        answer = str(a - b)
    else:  # op == '*'
        answer = str(a * b)
    
    challenge = f"What is {a} {op} {b}?"
    return challenge, answer

def create_captcha_challenge(chat_id: int, user_id: int) -> Tuple[str, str]:
    """
    Create and store a captcha challenge for a user.
    
    Args:
        chat_id: The chat ID
        user_id: The user ID
    
    Returns:
        A tuple of (challenge, answer)
    """
    challenge, answer = generate_captcha()
    
    with get_db_connection() as conn:
        # Remove any existing challenges for this user
        conn.execute("DELETE FROM captcha_challenges WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        
        # Store new challenge
        conn.execute("INSERT INTO captcha_challenges (chat_id, user_id, challenge, answer) VALUES (?, ?, ?, ?)",
                    (chat_id, user_id, challenge, answer))
        conn.commit()
    
    return challenge, answer

def verify_captcha(chat_id: int, user_id: int, user_answer: str) -> bool:
    """
    Verify a user's answer to a captcha challenge.
    
    Args:
        chat_id: The chat ID
        user_id: The user ID
        user_answer: The user's answer
    
    Returns:
        True if the answer is correct, False otherwise
    """
    with get_db_connection() as conn:
        row = conn.execute("SELECT answer FROM captcha_challenges WHERE chat_id = ? AND user_id = ?",
                          (chat_id, user_id)).fetchone()
        
        if not row:
            return False
        
        correct_answer = row["answer"]
        
        # Remove the challenge regardless of whether the answer is correct
        conn.execute("DELETE FROM captcha_challenges WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        conn.commit()
        
        return user_answer.strip() == correct_answer

def backup_chat_data(chat_id: int) -> str:
    """
    Backup chat settings and data.
    
    Args:
        chat_id: The chat ID
    
    Returns:
        The backup ID
    """
    with get_db_connection() as conn:
        # Get chat settings
        settings_row = conn.execute("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,)).fetchone()
        settings = dict(settings_row) if settings_row else {}
        
        # Get warnings
        warnings_rows = conn.execute("SELECT * FROM user_warnings WHERE chat_id = ?", (chat_id,)).fetchall()
        warnings = [dict(row) for row in warnings_rows]
        
        # Get banned users
        banned_rows = conn.execute("SELECT * FROM banned_users WHERE chat_id = ?", (chat_id,)).fetchall()
        banned = [dict(row) for row in banned_rows]
        
        # Create backup data
        backup_data = {
            "chat_id": chat_id,
            "settings": settings,
            "warnings": warnings,
            "banned_users": banned,
            "timestamp": datetime.now().isoformat()
        }
        
        # Store backup
        conn.execute("INSERT INTO backup_data (chat_id, data) VALUES (?, ?)",
                    (chat_id, json.dumps(backup_data)))
        conn.commit()
        
        # Return backup ID
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def restore_chat_data(chat_id: int, backup_id: int) -> bool:
    """
    Restore chat settings and data from a backup.
    
    Args:
        chat_id: The chat ID
        backup_id: The backup ID
    
    Returns:
        True if successful, False otherwise
    """
    with get_db_connection() as conn:
        # Get backup data
        row = conn.execute("SELECT data FROM backup_data WHERE id = ? AND chat_id = ?", 
                          (backup_id, chat_id)).fetchone()
        
        if not row:
            return False
        
        try:
            backup_data = json.loads(row["data"])
            
            # Restore settings
            if "settings" in backup_data:
                settings = backup_data["settings"]
                # Remove chat_id from settings if present
                settings.pop("chat_id", None)
                
                # Check if chat exists
                existing = conn.execute("SELECT 1 FROM chat_settings WHERE chat_id = ?", (chat_id,)).fetchone()
                
                if existing:
                    # Update existing settings
                    set_clause = ", ".join([f"{k} = ?" for k in settings.keys()])
                    values = list(settings.values()) + [chat_id]
                    conn.execute(f"UPDATE chat_settings SET {set_clause} WHERE chat_id = ?", values)
                else:
                    # Insert new settings
                    columns = ", ".join(["chat_id"] + list(settings.keys()))
                    placeholders = ", ".join(["?"] * (len(settings) + 1))
                    values = [chat_id] + list(settings.values())
                    conn.execute(f"INSERT INTO chat_settings ({columns}) VALUES ({placeholders})", values)
            
            # Restore warnings
            if "warnings" in backup_data:
                # Clear existing warnings
                conn.execute("DELETE FROM user_warnings WHERE chat_id = ?", (chat_id,))
                
                # Add warnings from backup
                for warning in backup_data["warnings"]:
                    conn.execute(
                        "INSERT INTO user_warnings (chat_id, user_id, reason, timestamp) VALUES (?, ?, ?, ?)",
                        (warning["chat_id"], warning["user_id"], warning["reason"], warning["timestamp"])
                    )
            
            # Restore banned users
            if "banned_users" in backup_data:
                # Clear existing bans
                conn.execute("DELETE FROM banned_users WHERE chat_id = ?", (chat_id,))
                
                # Add bans from backup
                for ban in backup_data["banned_users"]:
                    conn.execute(
                        "INSERT INTO banned_users (chat_id, user_id, timestamp) VALUES (?, ?, ?)",
                        (ban["chat_id"], ban["user_id"], ban["timestamp"])
                    )
            
            conn.commit()
            return True
        
        except Exception as e:
            logger.error(f"Error restoring backup: {e}")
            conn.rollback()
            return False

# Message handlers
def handle_start_command(chat_id: int, user_id: int):
    """Handle the /start command."""
    # Create inline keyboard with Help button
    keyboard = {
        "inline_keyboard": [
            [{"text": "Help", "callback_data": "help_main"}]
        ]
    }
    
    # Send welcome message
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"Hello! I am **{BOT_NAME}**, a comprehensive group management bot.\n\n"
                f"I can help you manage your group with features like:\n"
                f"• User moderation (warn, kick, ban)\n"
                f"• Anti-spam and content filters\n"
                f"• Welcome messages and captcha\n"
                f"• Fun commands and engagement tools\n\n"
                f"Click the button below to see all available commands!",
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(keyboard)
    })

def handle_help_command(chat_id: int, user_id: int):
    """Handle the /help command."""
    # Create inline keyboard with categories
    keyboard = {
        "inline_keyboard": [
            [{"text": "Moderation", "callback_data": "help_moderation"}],
            [{"text": "Utility", "callback_data": "help_utility"}],
            [{"text": "Fun", "callback_data": "help_fun"}],
            [{"text": "Settings", "callback_data": "help_settings"}]
        ]
    }
    
    # Send help message
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"**{BOT_NAME} Help Menu**\n\n"
                f"Please select a category to see the available commands:",
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(keyboard)
    })

def handle_callback_query(callback_query: Dict[str, Any]):
    """Handle callback queries from inline keyboards."""
    callback_data = callback_query.get("data", "")
    chat_id = callback_query["message"]["chat"]["id"]
    user_id = callback_query["from"]["id"]
    
    # Answer the callback query to remove the loading state
    api_request("answerCallbackQuery", {
        "callback_query_id": callback_query["id"]
    })
    
    # Handle different callback data
    if callback_data == "help_main":
        handle_help_command(chat_id, user_id)
    
    elif callback_data == "help_moderation":
        keyboard = {
            "inline_keyboard": [
                [{"text": "« Back", "callback_data": "help_main"}]
            ]
        }
        
        help_text = (
            "**Moderation Commands**\n\n"
            "• `/setrules <text>` - Set group rules\n"
            "• `/rules` - Display group rules\n"
            "• `/warn @user <reason>` - Warn a user\n"
            "• `/warnings @user` - Check user's warnings\n"
            "• `/kick @user` - Kick a user from the group\n"
            "• `/ban @user` - Ban a user from the group\n"
            "• `/unban @user` - Unban a user\n"
            "• `/mute @user` - Mute a user\n"
            "• `/unmute @user` - Unmute a user\n"
            "• `/promote @user` - Promote a user to admin\n"
            "• `/demote @user` - Demote an admin\n"
            "• `/pin` - Pin the replied message\n"
            "• `/unpin` - Unpin the current pinned message\n"
            "• `/banlist` - List all banned users\n"
            "• `/getadmins` - List all group admins\n"
            "• `/setwelcome <message>` - Set welcome message\n"
            "• `/welcome on|off` - Enable/disable welcome messages\n"
            "• `/setcaptcha on|off` - Enable/disable captcha for new users\n"
            "• `/lock links|media|stickers|all` - Lock certain message types\n"
            "• `/cleanup <n>` - Delete last n messages\n"
            "• `/purge @user` - Delete all messages from a user\n"
            "• `/slowmode <seconds>` - Set slowmode delay\n"
        )
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": help_text,
            "parse_mode": "Markdown",
            "reply_markup": json.dumps(keyboard)
        })
    
    elif callback_data == "help_utility":
        keyboard = {
            "inline_keyboard": [
                [{"text": "« Back", "callback_data": "help_main"}]
            ]
        }
        
        help_text = (
            "**Utility Commands**\n\n"
            "• `/help` - Show this help menu\n"
            "• `/id` - Get your user ID and chat ID\n"
            "• `/whois @user` - Get information about a user\n"
            "• `/stats` - Show group statistics\n"
            "• `/setlang <code>` - Set bot language (en, es, fr, etc.)\n"
            "• `/backup` - Backup group settings and data\n"
            "• `/restore <backup_id>` - Restore group from backup\n"
        )
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": help_text,
            "parse_mode": "Markdown",
            "reply_markup": json.dumps(keyboard)
        })
    
    elif callback_data == "help_fun":
        keyboard = {
            "inline_keyboard": [
                [{"text": "« Back", "callback_data": "help_main"}]
            ]
        }
        
        help_text = (
            "**Fun Commands**\n\n"
            "• `/roll [sides]` - Roll a dice (default 6 sides)\n"
            "• `/8ball <question>` - Ask the magic 8-ball a question\n"
            "• `/hug [@user]` - Send a hug\n"
            "• `/slap [@user]` - Slap someone\n"
            "• `/pat [@user]` - Pat someone\n"
            "• `/meme` - Get a random meme\n"
            "• `/poll <question>|opt1|opt2...` - Create a poll\n"
            "• `/stickerid` - Get the ID of a replied sticker\n"
            "• `/quote` - Get a random inspirational quote\n"
        )
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": help_text,
            "parse_mode": "Markdown",
            "reply_markup": json.dumps(keyboard)
        })
    
    elif callback_data == "help_settings":
        keyboard = {
            "inline_keyboard": [
                [{"text": "« Back", "callback_data": "help_main"}]
            ]
        }
        
        help_text = (
            "**Settings Commands**\n\n"
            "• `/setwelcome <message>` - Set welcome message\n"
            "• `/welcome on|off` - Enable/disable welcome messages\n"
            "• `/setcaptcha on|off` - Enable/disable captcha for new users\n"
            "• `/lock links|media|stickers|all` - Lock certain message types\n"
            "• `/slowmode <seconds>` - Set slowmode delay\n"
            "• `/setlang <code>` - Set bot language\n"
        )
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": help_text,
            "parse_mode": "Markdown",
            "reply_markup": json.dumps(keyboard)
        })
    
    # Handle captcha verification
    elif callback_data.startswith("captcha_verify_"):
        captcha_id = callback_data.split("_", 2)[2]
        
        # Verify the captcha
        if verify_captcha(chat_id, user_id, captcha_id):
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "✅ Captcha verified successfully! Welcome to the group.",
                "reply_to_message_id": callback_query["message"]["message_id"]
            })
        else:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ Incorrect answer. Please try again.",
                "reply_to_message_id": callback_query["message"]["message_id"]
            })
            
            # Generate a new captcha
            challenge, answer = create_captcha_challenge(chat_id, user_id)
            
            # Create inline keyboard with the answer
            keyboard = {
                "inline_keyboard": [
                    [{"text": answer, "callback_data": f"captcha_verify_{answer}"}]
                ]
            }
            
            # Send new captcha
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"🤖 Please solve this captcha to verify you're human:\n\n{challenge}",
                "reply_markup": json.dumps(keyboard)
            })
    
    # Handle confirmation for destructive commands
    elif callback_data.startswith("confirm_"):
        action = callback_data.split("_", 1)[1]
        
        if action == "ban":
            # Extract user_id from the message
            message_text = callback_query["message"]["text"]
            user_id_match = re.search(r"User ID: (\d+)", message_text)
            
            if user_id_match:
                target_user_id = int(user_id_match.group(1))
                
                try:
                    # Ban the user
                    api_request("banChatMember", {
                        "chat_id": chat_id,
                        "user_id": target_user_id
                    })
                    
                    # Add to banned users table
                    with get_db_connection() as conn:
                        conn.execute("INSERT OR REPLACE INTO banned_users (chat_id, user_id) VALUES (?, ?)",
                                    (chat_id, target_user_id))
                        conn.commit()
                    
                    # Update the confirmation message
                    api_request("editMessageText", {
                        "chat_id": chat_id,
                        "message_id": callback_query["message"]["message_id"],
                        "text": f"✅ User has been banned.",
                        "reply_markup": json.dumps({"inline_keyboard": []})
                    })
                
                except Exception as e:
                    logger.error(f"Error banning user: {e}")
                    api_request("editMessageText", {
                        "chat_id": chat_id,
                        "message_id": callback_query["message"]["message_id"],
                        "text": f"❌ Failed to ban user: {str(e)}",
                        "reply_markup": json.dumps({"inline_keyboard": []})
                    })
        
        elif action == "kick":
            # Extract user_id from the message
            message_text = callback_query["message"]["text"]
            user_id_match = re.search(r"User ID: (\d+)", message_text)
            
            if user_id_match:
                target_user_id = int(user_id_match.group(1))
                
                try:
                    # Kick the user
                    api_request("kickChatMember", {
                        "chat_id": chat_id,
                        "user_id": target_user_id
                    })
                    
                    # Update the confirmation message
                    api_request("editMessageText", {
                        "chat_id": chat_id,
                        "message_id": callback_query["message"]["message_id"],
                        "text": f"✅ User has been kicked.",
                        "reply_markup": json.dumps({"inline_keyboard": []})
                    })
                
                except Exception as e:
                    logger.error(f"Error kicking user: {e}")
                    api_request("editMessageText", {
                        "chat_id": chat_id,
                        "message_id": callback_query["message"]["message_id"],
                        "text": f"❌ Failed to kick user: {str(e)}",
                        "reply_markup": json.dumps({"inline_keyboard": []})
                    })
        
        elif action == "purge":
            # Extract user_id from the message
            message_text = callback_query["message"]["text"]
            user_id_match = re.search(r"User ID: (\d+)", message_text)
            
            if user_id_match:
                target_user_id = int(user_id_match.group(1))
                
                try:
                    # Get messages to delete
                    messages = api_request("searchChatMessages", {
                        "chat_id": chat_id,
                        "from_user_id": target_user_id,
                        "limit": 100
                    })
                    
                    # Delete messages
                    for message in messages:
                        api_request("deleteMessage", {
                            "chat_id": chat_id,
                            "message_id": message["message_id"]
                        })
                    
                    # Update the confirmation message
                    api_request("editMessageText", {
                        "chat_id": chat_id,
                        "message_id": callback_query["message"]["message_id"],
                        "text": f"✅ Deleted {len(messages)} messages from user.",
                        "reply_markup": json.dumps({"inline_keyboard": []})
                    })
                
                except Exception as e:
                    logger.error(f"Error purging messages: {e}")
                    api_request("editMessageText", {
                        "chat_id": chat_id,
                        "message_id": callback_query["message"]["message_id"],
                        "text": f"❌ Failed to purge messages: {str(e)}",
                        "reply_markup": json.dumps({"inline_keyboard": []})
                    })
    
    # Handle cancellation of destructive commands
    elif callback_data == "cancel":
        api_request("editMessageText", {
            "chat_id": chat_id,
            "message_id": callback_query["message"]["message_id"],
            "text": "❌ Operation cancelled.",
            "reply_markup": json.dumps({"inline_keyboard": []})
        })

def handle_setrules_command(chat_id: int, user_id: int, text: str):
    """Handle the /setrules command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Extract rules text
    rules = text.split("/setrules", 1)[1].strip()
    
    if not rules:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Please provide the rules text.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Save rules to database
    set_chat_setting(chat_id, "rules", rules)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": "✅ Group rules have been updated.",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_rules_command(chat_id: int):
    """Handle the /rules command."""
    rules = get_chat_setting(chat_id, "rules")
    
    if not rules:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ No rules have been set for this group.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"**Group Rules:**\n\n{rules}",
        "parse_mode": "Markdown",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_warn_command(chat_id: int, user_id: int, text: str):
    """Handle the /warn command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse command
    match = re.match(r"/warn\s+@?(\w+)(?:\s+(.+))?", text)
    if not match:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/warn @user <reason>`",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    username = match.group(1)
    reason = match.group(2) or "No reason provided"
    
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user_id = replied_message["from"]["id"]
        target_user_name = replied_message["from"].get("first_name", "Unknown")
    else:
        # If no reply, try to find user by username
        try:
            chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
            target_user_id = None
            target_user_name = username
            
            for member in chat_members:
                if member["user"].get("username") == username:
                    target_user_id = member["user"]["id"]
                    target_user_name = member["user"].get("first_name", "Unknown")
                    break
            
            if not target_user_id:
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ User @{username} not found in this group.",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Error finding user: {str(e)}",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    
    # Don't warn admins
    if is_admin(chat_id, target_user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You cannot warn an admin.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Add warning
    warning_count = add_warning(chat_id, target_user_id, reason)
    
    # Get warning threshold
    warn_threshold = get_chat_setting(chat_id, "warn_threshold", 3)
    
    # Send warning message
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"⚠️ User {target_user_name} has been warned ({warning_count}/{warn_threshold}).\n"
                f"Reason: {reason}",
        "reply_to_message_id": request.json["message"]["message_id"]
    })
    
    # Check if threshold reached
    if warning_count >= warn_threshold:
        # Create confirmation keyboard
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Confirm Ban", "callback_data": "confirm_ban"},
                    {"text": "❌ Cancel", "callback_data": "cancel"}
                ]
            ]
        }
        
        # Send confirmation message
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"⚠️ User {target_user_name} has reached the warning threshold ({warning_count}/{warn_threshold}).\n\n"
                    f"User ID: {target_user_id}\n"
                    f"Do you want to ban this user?",
            "reply_markup": json.dumps(keyboard)
        })

def handle_warnings_command(chat_id: int, user_id: int, text: str):
    """Handle the /warnings command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse command
    match = re.match(r"/warnings\s+@?(\w+)", text)
    if not match:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/warnings @user`",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    username = match.group(1)
    
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user_id = replied_message["from"]["id"]
        target_user_name = replied_message["from"].get("first_name", "Unknown")
    else:
        # If no reply, try to find user by username
        try:
            chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
            target_user_id = None
            target_user_name = username
            
            for member in chat_members:
                if member["user"].get("username") == username:
                    target_user_id = member["user"]["id"]
                    target_user_name = member["user"].get("first_name", "Unknown")
                    break
            
            if not target_user_id:
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ User @{username} not found in this group.",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Error finding user: {str(e)}",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    
    # Get warnings
    warnings = get_warnings(chat_id, target_user_id)
    
    if not warnings:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"✅ {target_user_name} has no warnings.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Format warnings
    warnings_text = f"⚠️ Warnings for {target_user_name} ({len(warnings)}):\n\n"
    for warning in warnings:
        timestamp = datetime.strptime(warning["timestamp"], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
        warnings_text += f"• {timestamp}: {warning['reason']}\n"
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": warnings_text,
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_ban_command(chat_id: int, user_id: int, text: str):
    """Handle the /ban command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user_id = replied_message["from"]["id"]
        target_user_name = replied_message["from"].get("first_name", "Unknown")
    else:
        # Parse command
        match = re.match(r"/ban\s+@?(\w+)", text)
        if not match:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ Usage: `/ban @user` or reply to a user's message with `/ban`",
                "parse_mode": "Markdown",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
        
        username = match.group(1)
        
        # Try to find user by username
        try:
            chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
            target_user_id = None
            target_user_name = username
            
            for member in chat_members:
                if member["user"].get("username") == username:
                    target_user_id = member["user"]["id"]
                    target_user_name = member["user"].get("first_name", "Unknown")
                    break
            
            if not target_user_id:
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ User @{username} not found in this group.",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Error finding user: {str(e)}",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    
    # Don't ban admins
    if is_admin(chat_id, target_user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You cannot ban an admin.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Create confirmation keyboard
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm Ban", "callback_data": "confirm_ban"},
                {"text": "❌ Cancel", "callback_data": "cancel"}
            ]
        ]
    }
    
    # Send confirmation message
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"⚠️ Are you sure you want to ban {target_user_name}?\n\n"
                f"User ID: {target_user_id}",
        "reply_markup": json.dumps(keyboard)
    })

def handle_unban_command(chat_id: int, user_id: int, text: str):
    """Handle the /unban command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse command
    match = re.match(r"/unban\s+@?(\w+)", text)
    if not match:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/unban @user`",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    username = match.group(1)
    
    # Try to find user by username
    try:
        chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
        target_user_id = None
        target_user_name = username
        
        for member in chat_members:
            if member["user"].get("username") == username:
                target_user_id = member["user"]["id"]
                target_user_name = member["user"].get("first_name", "Unknown")
                break
        
        if not target_user_id:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ User @{username} not found.",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    except Exception as e:
        logger.error(f"Error getting chat members: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Error finding user: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    try:
        # Unban the user
        api_request("unbanChatMember", {
            "chat_id": chat_id,
            "user_id": target_user_id
        })
        
        # Remove from banned users table
        with get_db_connection() as conn:
            conn.execute("DELETE FROM banned_users WHERE chat_id = ? AND user_id = ?", (chat_id, target_user_id))
            conn.commit()
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"✅ {target_user_name} has been unbanned.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error unbanning user: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to unban user: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_kick_command(chat_id: int, user_id: int, text: str):
    """Handle the /kick command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user_id = replied_message["from"]["id"]
        target_user_name = replied_message["from"].get("first_name", "Unknown")
    else:
        # Parse command
        match = re.match(r"/kick\s+@?(\w+)", text)
        if not match:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ Usage: `/kick @user` or reply to a user's message with `/kick`",
                "parse_mode": "Markdown",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
        
        username = match.group(1)
        
        # Try to find user by username
        try:
            chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
            target_user_id = None
            target_user_name = username
            
            for member in chat_members:
                if member["user"].get("username") == username:
                    target_user_id = member["user"]["id"]
                    target_user_name = member["user"].get("first_name", "Unknown")
                    break
            
            if not target_user_id:
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ User @{username} not found in this group.",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Error finding user: {str(e)}",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    
    # Don't kick admins
    if is_admin(chat_id, target_user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You cannot kick an admin.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Create confirmation keyboard
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm Kick", "callback_data": "confirm_kick"},
                {"text": "❌ Cancel", "callback_data": "cancel"}
            ]
        ]
    }
    
    # Send confirmation message
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"⚠️ Are you sure you want to kick {target_user_name}?\n\n"
                f"User ID: {target_user_id}",
        "reply_markup": json.dumps(keyboard)
    })

def handle_mute_command(chat_id: int, user_id: int, text: str):
    """Handle the /mute command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user_id = replied_message["from"]["id"]
        target_user_name = replied_message["from"].get("first_name", "Unknown")
    else:
        # Parse command
        match = re.match(r"/mute\s+@?(\w+)", text)
        if not match:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ Usage: `/mute @user` or reply to a user's message with `/mute`",
                "parse_mode": "Markdown",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
        
        username = match.group(1)
        
        # Try to find user by username
        try:
            chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
            target_user_id = None
            target_user_name = username
            
            for member in chat_members:
                if member["user"].get("username") == username:
                    target_user_id = member["user"]["id"]
                    target_user_name = member["user"].get("first_name", "Unknown")
                    break
            
            if not target_user_id:
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ User @{username} not found in this group.",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Error finding user: {str(e)}",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    
    # Don't mute admins
    if is_admin(chat_id, target_user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You cannot mute an admin.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    try:
        # Mute the user (restrict permissions)
        api_request("restrictChatMember", {
            "chat_id": chat_id,
            "user_id": target_user_id,
            "permissions": {
                "can_send_messages": False,
                "can_send_media_messages": False,
                "can_send_polls": False,
                "can_send_other_messages": False,
                "can_add_web_page_previews": False,
                "can_change_info": False,
                "can_invite_users": False,
                "can_pin_messages": False
            }
        })
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"✅ {target_user_name} has been muted.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error muting user: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to mute user: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_unmute_command(chat_id: int, user_id: int, text: str):
    """Handle the /unmute command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user_id = replied_message["from"]["id"]
        target_user_name = replied_message["from"].get("first_name", "Unknown")
    else:
        # Parse command
        match = re.match(r"/unmute\s+@?(\w+)", text)
        if not match:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ Usage: `/unmute @user` or reply to a user's message with `/unmute`",
                "parse_mode": "Markdown",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
        
        username = match.group(1)
        
        # Try to find user by username
        try:
            chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
            target_user_id = None
            target_user_name = username
            
            for member in chat_members:
                if member["user"].get("username") == username:
                    target_user_id = member["user"]["id"]
                    target_user_name = member["user"].get("first_name", "Unknown")
                    break
            
            if not target_user_id:
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ User @{username} not found in this group.",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Error finding user: {str(e)}",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    
    try:
        # Unmute the user (restore permissions)
        api_request("restrictChatMember", {
            "chat_id": chat_id,
            "user_id": target_user_id,
            "permissions": {
                "can_send_messages": True,
                "can_send_media_messages": True,
                "can_send_polls": True,
                "can_send_other_messages": True,
                "can_add_web_page_previews": True,
                "can_change_info": False,
                "can_invite_users": False,
                "can_pin_messages": False
            }
        })
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"✅ {target_user_name} has been unmuted.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error unmuting user: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to unmute user: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_promote_command(chat_id: int, user_id: int, text: str):
    """Handle the /promote command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user_id = replied_message["from"]["id"]
        target_user_name = replied_message["from"].get("first_name", "Unknown")
    else:
        # Parse command
        match = re.match(r"/promote\s+@?(\w+)", text)
        if not match:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ Usage: `/promote @user` or reply to a user's message with `/promote`",
                "parse_mode": "Markdown",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
        
        username = match.group(1)
        
        # Try to find user by username
        try:
            chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
            target_user_id = None
            target_user_name = username
            
            for member in chat_members:
                if member["user"].get("username") == username:
                    target_user_id = member["user"]["id"]
                    target_user_name = member["user"].get("first_name", "Unknown")
                    break
            
            if not target_user_id:
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ User @{username} not found in this group.",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Error finding user: {str(e)}",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    
    try:
        # Promote the user
        api_request("promoteChatMember", {
            "chat_id": chat_id,
            "user_id": target_user_id,
            "can_change_info": True,
            "can_post_messages": True,
            "can_edit_messages": True,
            "can_delete_messages": True,
            "can_invite_users": True,
            "can_restrict_members": True,
            "can_pin_messages": True,
            "can_promote_members": False
        })
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"✅ {target_user_name} has been promoted to admin.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error promoting user: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to promote user: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_demote_command(chat_id: int, user_id: int, text: str):
    """Handle the /demote command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user_id = replied_message["from"]["id"]
        target_user_name = replied_message["from"].get("first_name", "Unknown")
    else:
        # Parse command
        match = re.match(r"/demote\s+@?(\w+)", text)
        if not match:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ Usage: `/demote @user` or reply to a user's message with `/demote`",
                "parse_mode": "Markdown",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
        
        username = match.group(1)
        
        # Try to find user by username
        try:
            chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
            target_user_id = None
            target_user_name = username
            
            for member in chat_members:
                if member["user"].get("username") == username:
                    target_user_id = member["user"]["id"]
                    target_user_name = member["user"].get("first_name", "Unknown")
                    break
            
            if not target_user_id:
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ User @{username} not found in this group.",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Error finding user: {str(e)}",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    
    # Don't demote the creator
    try:
        chat_info = api_request("getChat", {"chat_id": chat_id})
        if "creator" in chat_info and chat_info["creator"]["id"] == target_user_id:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ You cannot demote the group creator.",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    except Exception as e:
        logger.error(f"Error getting chat info: {e}")
    
    try:
        # Demote the user
        api_request("promoteChatMember", {
            "chat_id": chat_id,
            "user_id": target_user_id,
            "can_change_info": False,
            "can_post_messages": False,
            "can_edit_messages": False,
            "can_delete_messages": False,
            "can_invite_users": False,
            "can_restrict_members": False,
            "can_pin_messages": False,
            "can_promote_members": False
        })
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"✅ {target_user_name} has been demoted.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error demoting user: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to demote user: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_pin_command(chat_id: int, user_id: int):
    """Handle the /pin command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Check if the command is a reply to a message
    replied_message = request.json["message"].get("reply_to_message")
    if not replied_message:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Please reply to a message to pin it.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    try:
        # Pin the message
        api_request("pinChatMessage", {
            "chat_id": chat_id,
            "message_id": replied_message["message_id"],
            "disable_notification": True
        })
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "✅ Message has been pinned.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error pinning message: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to pin message: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_unpin_command(chat_id: int, user_id: int):
    """Handle the /unpin command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    try:
        # Unpin the message
        api_request("unpinChatMessage", {
            "chat_id": chat_id
        })
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "✅ Message has been unpinned.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error unpinning message: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to unpin message: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_banlist_command(chat_id: int, user_id: int):
    """Handle the /banlist command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Get banned users from database
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM banned_users WHERE chat_id = ?", (chat_id,)).fetchall()
        banned_users = [dict(row) for row in rows]
    
    if not banned_users:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "✅ No banned users in this group.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Format banlist
    banlist_text = f"🚫 Banned Users ({len(banned_users)}):\n\n"
    
    for user in banned_users:
        try:
            # Try to get user info
            user_info = api_request("getChat", {"chat_id": user["user_id"]})
            user_name = user_info.get("first_name", "Unknown")
            username = f" (@{user_info['username']})" if "username" in user_info else ""
            banlist_text += f"• {user_name}{username} (ID: {user['user_id']})\n"
        except Exception:
            banlist_text += f"• Unknown User (ID: {user['user_id']})\n"
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": banlist_text,
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_getadmins_command(chat_id: int, user_id: int):
    """Handle the /getadmins command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    try:
        # Get chat administrators
        admins = api_request("getChatAdministrators", {"chat_id": chat_id})
        
        if not admins:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ No administrators found in this group.",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
        
        # Format admin list
        admin_list_text = f"👥 Group Administrators ({len(admins)}):\n\n"
        
        for admin in admins:
            user = admin["user"]
            user_name = user.get("first_name", "Unknown")
            username = f" (@{user['username']})" if "username" in user else ""
            
            # Get admin status
            status = "Creator" if admin.get("status") == "creator" else "Admin"
            
            admin_list_text += f"• {user_name}{username} - {status}\n"
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": admin_list_text,
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error getting admins: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to get admins: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_setwelcome_command(chat_id: int, user_id: int, text: str):
    """Handle the /setwelcome command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Extract welcome message
    welcome_message = text.split("/setwelcome", 1)[1].strip()
    
    if not welcome_message:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Please provide a welcome message.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Save welcome message to database
    set_chat_setting(chat_id, "welcome_message", welcome_message)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": "✅ Welcome message has been updated.",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_welcome_command(chat_id: int, user_id: int, text: str):
    """Handle the /welcome command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse command
    match = re.match(r"/welcome\s+(on|off)", text.lower())
    if not match:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/welcome on` or `/welcome off`",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    state = match.group(1)
    enabled = state == "on"
    
    # Save setting to database
    set_chat_setting(chat_id, "welcome_enabled", enabled)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"✅ Welcome messages have been {'enabled' if enabled else 'disabled'}.",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_setcaptcha_command(chat_id: int, user_id: int, text: str):
    """Handle the /setcaptcha command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse command
    match = re.match(r"/setcaptcha\s+(on|off)", text.lower())
    if not match:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/setcaptcha on` or `/setcaptcha off`",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    state = match.group(1)
    enabled = state == "on"
    
    # Save setting to database
    set_chat_setting(chat_id, "captcha_enabled", enabled)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"✅ Captcha verification has been {'enabled' if enabled else 'disabled'}.",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_lock_command(chat_id: int, user_id: int, text: str):
    """Handle the /lock command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse command
    match = re.match(r"/lock\s+(links|media|stickers|all)", text.lower())
    if not match:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/lock links|media|stickers|all`",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    lock_type = match.group(1)
    
    # Save settings to database
    if lock_type == "links":
        set_chat_setting(chat_id, "lock_links", True)
    elif lock_type == "media":
        set_chat_setting(chat_id, "lock_media", True)
    elif lock_type == "stickers":
        set_chat_setting(chat_id, "lock_stickers", True)
    elif lock_type == "all":
        set_chat_setting(chat_id, "lock_links", True)
        set_chat_setting(chat_id, "lock_media", True)
        set_chat_setting(chat_id, "lock_stickers", True)
        set_chat_setting(chat_id, "lock_all", True)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"✅ {lock_type.capitalize()} have been locked.",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_cleanup_command(chat_id: int, user_id: int, text: str):
    """Handle the /cleanup command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse command
    match = re.match(r"/cleanup\s+(\d+)", text)
    if not match:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/cleanup <number>`",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    count = int(match.group(1))
    
    if count <= 0 or count > 100:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Please provide a number between 1 and 100.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    try:
        # Get the last n messages
        messages = api_request("getChatHistory", {
            "chat_id": chat_id,
            "limit": count
        })
        
        # Delete messages
        deleted_count = 0
        for message in messages:
            try:
                api_request("deleteMessage", {
                    "chat_id": chat_id,
                    "message_id": message["message_id"]
                })
                deleted_count += 1
            except Exception:
                # Skip messages that can't be deleted
                pass
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"✅ Deleted {deleted_count} messages.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error cleaning up messages: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to cleanup messages: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_purge_command(chat_id: int, user_id: int, text: str):
    """Handle the /purge command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user_id = replied_message["from"]["id"]
        target_user_name = replied_message["from"].get("first_name", "Unknown")
    else:
        # Parse command
        match = re.match(r"/purge\s+@?(\w+)", text)
        if not match:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ Usage: `/purge @user` or reply to a user's message with `/purge`",
                "parse_mode": "Markdown",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
        
        username = match.group(1)
        
        # Try to find user by username
        try:
            chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
            target_user_id = None
            target_user_name = username
            
            for member in chat_members:
                if member["user"].get("username") == username:
                    target_user_id = member["user"]["id"]
                    target_user_name = member["user"].get("first_name", "Unknown")
                    break
            
            if not target_user_id:
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ User @{username} not found in this group.",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Error finding user: {str(e)}",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    
    # Don't purge admins
    if is_admin(chat_id, target_user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You cannot purge messages from an admin.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Create confirmation keyboard
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm Purge", "callback_data": "confirm_purge"},
                {"text": "❌ Cancel", "callback_data": "cancel"}
            ]
        ]
    }
    
    # Send confirmation message
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"⚠️ Are you sure you want to delete all messages from {target_user_name}?\n\n"
                f"User ID: {target_user_id}",
        "reply_markup": json.dumps(keyboard)
    })

def handle_slowmode_command(chat_id: int, user_id: int, text: str):
    """Handle the /slowmode command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse command
    match = re.match(r"/slowmode\s+(\d+)", text)
    if not match:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/slowmode <seconds>`",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    seconds = int(match.group(1))
    
    if seconds < 0:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Slowmode seconds cannot be negative.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    try:
        # Set slowmode
        api_request("setChatPermissions", {
            "chat_id": chat_id,
            "permissions": {
                "can_send_messages": True,
                "can_send_media_messages": True,
                "can_send_polls": True,
                "can_send_other_messages": True,
                "can_add_web_page_previews": True,
                "can_change_info": False,
                "can_invite_users": False,
                "can_pin_messages": False
            },
            "slow_mode_delay": seconds
        })
        
        # Save setting to database
        set_chat_setting(chat_id, "slowmode", seconds)
        
        if seconds == 0:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "✅ Slowmode has been disabled.",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
        else:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"✅ Slowmode has been set to {seconds} seconds.",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
    except Exception as e:
        logger.error(f"Error setting slowmode: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to set slowmode: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_id_command(chat_id: int, user_id: int):
    """Handle the /id command."""
    # Get user info
    user_info = request.json["message"]["from"]
    user_name = user_info.get("first_name", "Unknown")
    username = f" (@{user_info['username']})" if "username" in user_info else ""
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"🆔 Your Information:\n\n"
                f"Name: {user_name}{username}\n"
                f"User ID: {user_id}\n"
                f"Chat ID: {chat_id}",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_whois_command(chat_id: int, user_id: int, text: str):
    """Handle the /whois command."""
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user = replied_message["from"]
        target_user_id = target_user["id"]
        target_user_name = target_user.get("first_name", "Unknown")
        target_username = target_user.get("username", "")
    else:
        # Parse command
        match = re.match(r"/whois\s+@?(\w+)", text)
        if not match:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "❌ Usage: `/whois @user` or reply to a user's message with `/whois`",
                "parse_mode": "Markdown",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
        
        username = match.group(1)
        
        # Try to find user by username
        try:
            chat_members = api_request("getChatAdministrators", {"chat_id": chat_id})
            target_user_id = None
            target_user_name = username
            target_username = username
            
            for member in chat_members:
                if member["user"].get("username") == username:
                    target_user_id = member["user"]["id"]
                    target_user_name = member["user"].get("first_name", "Unknown")
                    target_username = member["user"].get("username", "")
                    break
            
            if not target_user_id:
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"❌ User @{username} not found in this group.",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Error finding user: {str(e)}",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
            return
    
    # Get user warnings
    warnings = get_warnings(chat_id, target_user_id)
    
    # Format user info
    user_info_text = f"👤 User Information:\n\n"
    user_info_text += f"Name: {target_user_name}\n"
    if target_username:
        user_info_text += f"Username: @{target_username}\n"
    user_info_text += f"User ID: {target_user_id}\n"
    user_info_text += f"Warnings: {len(warnings)}\n"
    
    # Check if user is admin
    if is_admin(chat_id, target_user_id):
        user_info_text += "Status: Admin\n"
    
    # Check if user is banned
    with get_db_connection() as conn:
        banned = conn.execute("SELECT 1 FROM banned_users WHERE chat_id = ? AND user_id = ?",
                             (chat_id, target_user_id)).fetchone()
        if banned:
            user_info_text += "Status: Banned\n"
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": user_info_text,
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_stats_command(chat_id: int, user_id: int):
    """Handle the /stats command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    try:
        # Get chat info
        chat_info = api_request("getChat", {"chat_id": chat_id})
        chat_name = chat_info.get("title", "Unknown")
        chat_type = chat_info.get("type", "Unknown")
        
        # Get member count
        member_count = chat_info.get("members_count", 0)
        
        # Get admin count
        admins = api_request("getChatAdministrators", {"chat_id": chat_id})
        admin_count = len(admins)
        
        # Get banned users count
        with get_db_connection() as conn:
            banned_count = conn.execute("SELECT COUNT(*) FROM banned_users WHERE chat_id = ?", 
                                      (chat_id,)).fetchone()[0]
        
        # Get warnings count
        with get_db_connection() as conn:
            warnings_count = conn.execute("SELECT COUNT(*) FROM user_warnings WHERE chat_id = ?", 
                                        (chat_id,)).fetchone()[0]
        
        # Format stats
        stats_text = f"📊 Group Statistics for {chat_name}:\n\n"
        stats_text += f"Type: {chat_type.capitalize()}\n"
        stats_text += f"Members: {member_count}\n"
        stats_text += f"Administrators: {admin_count}\n"
        stats_text += f"Banned Users: {banned_count}\n"
        stats_text += f"Total Warnings: {warnings_count}\n"
        
        # Get settings
        welcome_enabled = get_chat_setting(chat_id, "welcome_enabled", False)
        captcha_enabled = get_chat_setting(chat_id, "captcha_enabled", False)
        slowmode = get_chat_setting(chat_id, "slowmode", 0)
        
        stats_text += f"\n⚙️ Settings:\n"
        stats_text += f"Welcome Messages: {'Enabled' if welcome_enabled else 'Disabled'}\n"
        stats_text += f"Captcha Verification: {'Enabled' if captcha_enabled else 'Disabled'}\n"
        stats_text += f"Slowmode: {slowmode} seconds\n"
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": stats_text,
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to get stats: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_setlang_command(chat_id: int, user_id: int, text: str):
    """Handle the /setlang command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse command
    match = re.match(r"/setlang\s+([a-z]{2})", text.lower())
    if not match:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/setlang <code>` (e.g., en, es, fr, de, etc.)",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    lang_code = match.group(1)
    
    # Save setting to database
    set_chat_setting(chat_id, "language", lang_code)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"✅ Bot language has been set to {lang_code}.",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_backup_command(chat_id: int, user_id: int):
    """Handle the /backup command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    try:
        # Create backup
        backup_id = backup_chat_data(chat_id)
        
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"✅ Backup created successfully.\n\n"
                    f"Backup ID: {backup_id}\n"
                    f"Use `/restore {backup_id}` to restore from this backup.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to create backup: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_restore_command(chat_id: int, user_id: int, text: str):
    """Handle the /restore command."""
    if not is_admin(chat_id, user_id):
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ You need to be an admin to use this command.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse command
    match = re.match(r"/restore\s+(\d+)", text)
    if not match:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/restore <backup_id>`",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    backup_id = int(match.group(1))
    
    try:
        # Restore from backup
        success = restore_chat_data(chat_id, backup_id)
        
        if success:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"✅ Group data has been restored from backup {backup_id}.",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
        else:
            api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Backup {backup_id} not found or restore failed.",
                "reply_to_message_id": request.json["message"]["message_id"]
            })
    except Exception as e:
        logger.error(f"Error restoring backup: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to restore backup: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_roll_command(chat_id: int, user_id: int, text: str):
    """Handle the /roll command."""
    # Parse command
    match = re.match(r"/roll\s*(\d*)", text)
    sides = 6  # Default sides
    
    if match.group(1):
        try:
            sides = int(match.group(1))
            if sides <= 0:
                sides = 6
        except ValueError:
            sides = 6
    
    # Roll the dice
    result = random.randint(1, sides)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"🎲 You rolled a {result} (1-{sides}).",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_8ball_command(chat_id: int, user_id: int, text: str):
    """Handle the /8ball command."""
    # Extract question
    question = text.split("/8ball", 1)[1].strip()
    
    if not question:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Please ask a question.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Magic 8-ball responses
    responses = [
        "It is certain.",
        "It is decidedly so.",
        "Without a doubt.",
        "Yes, definitely.",
        "You may rely on it.",
        "As I see it, yes.",
        "Most likely.",
        "Outlook good.",
        "Yes.",
        "Signs point to yes.",
        "Reply hazy, try again.",
        "Ask again later.",
        "Better not tell you now.",
        "Cannot predict now.",
        "Concentrate and ask again.",
        "Don't count on it.",
        "My reply is no.",
        "My sources say no.",
        "Outlook not so good.",
        "Very doubtful."
    ]
    
    # Get random response
    response = random.choice(responses)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"🎱 {response}",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_hug_command(chat_id: int, user_id: int, text: str):
    """Handle the /hug command."""
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user = replied_message["from"]
        target_user_name = target_user.get("first_name", "Unknown")
        target_username = f"@{target_user['username']}" if "username" in target_user else ""
    else:
        # Parse command
        match = re.match(r"/hug\s+@?(\w+)", text)
        if match:
            target_user_name = match.group(1)
            target_username = f"@{target_user_name}"
        else:
            target_user_name = "everyone"
            target_username = ""
    
    # Get user info
    user_info = request.json["message"]["from"]
    user_name = user_info.get("first_name", "Unknown")
    
    # Hug messages
    hug_messages = [
        f"{user_name} gives {target_username or target_user_name} a big hug! 🤗",
        f"{user_name} hugs {target_username or target_user_name} tightly! 🤗",
        f"{user_name} gives {target_username or target_user_name} a warm hug! 🤗",
        f"{user_name} sends a virtual hug to {target_username or target_user_name}! 🤗",
    ]
    
    # Get random hug message
    message = random.choice(hug_messages)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": message,
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_slap_command(chat_id: int, user_id: int, text: str):
    """Handle the /slap command."""
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user = replied_message["from"]
        target_user_name = target_user.get("first_name", "Unknown")
        target_username = f"@{target_user['username']}" if "username" in target_user else ""
    else:
        # Parse command
        match = re.match(r"/slap\s+@?(\w+)", text)
        if match:
            target_user_name = match.group(1)
            target_username = f"@{target_user_name}"
        else:
            target_user_name = "everyone"
            target_username = ""
    
    # Get user info
    user_info = request.json["message"]["from"]
    user_name = user_info.get("first_name", "Unknown")
    
    # Slap messages
    slap_messages = [
        f"{user_name} slaps {target_username or target_user_name} with a large trout! 🐟",
        f"{user_name} slaps {target_username or target_user_name} with a wet noodle! 🍜",
        f"{user_name} slaps {target_username or target_user_name} with a smelly fish! 🐟",
        f"{user_name} slaps {target_username or target_user_name} with a rubber chicken! 🐔",
    ]
    
    # Get random slap message
    message = random.choice(slap_messages)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": message,
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_pat_command(chat_id: int, user_id: int, text: str):
    """Handle the /pat command."""
    # Try to get user info from the replied message if available
    replied_message = request.json["message"].get("reply_to_message")
    if replied_message and "from" in replied_message:
        target_user = replied_message["from"]
        target_user_name = target_user.get("first_name", "Unknown")
        target_username = f"@{target_user['username']}" if "username" in target_user else ""
    else:
        # Parse command
        match = re.match(r"/pat\s+@?(\w+)", text)
        if match:
            target_user_name = match.group(1)
            target_username = f"@{target_user_name}"
        else:
            target_user_name = "everyone"
            target_username = ""
    
    # Get user info
    user_info = request.json["message"]["from"]
    user_name = user_info.get("first_name", "Unknown")
    
    # Pat messages
    pat_messages = [
        f"{user_name} pats {target_username or target_user_name} gently! 👋",
        f"{user_name} gives {target_username or target_user_name} a pat on the back! 👋",
        f"{user_name} pats {target_username or target_user_name}'s head! 👋",
        f"{user_name} sends a pat to {target_username or target_user_name}! 👋",
    ]
    
    # Get random pat message
    message = random.choice(pat_messages)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": message,
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_meme_command(chat_id: int, user_id: int):
    """Handle the /meme command."""
    try:
        # Try to get a random meme from an API
        response = requests.get("https://meme-api.herokuapp.com/gimme", timeout=5)
        if response.status_code == 200:
            meme_data = response.json()
            meme_url = meme_data.get("url")
            meme_title = meme_data.get("title", "Random Meme")
            
            if meme_url:
                api_request("sendPhoto", {
                    "chat_id": chat_id,
                    "photo": meme_url,
                    "caption": f"🤣 {meme_title}",
                    "reply_to_message_id": request.json["message"]["message_id"]
                })
                return
    except Exception as e:
        logger.error(f"Error getting meme: {e}")
    
    # Fallback to a text-based meme
    memes = [
        "When you finally understand the code after hours of debugging: 🤯",
        "When your code works on the first try: 🤔",
        "When you see someone using tabs instead of spaces: 😱",
        "When you realize you forgot to save your work: 😭",
        "When your code passes all tests: 🎉",
        "When you see a 'TODO' comment from 3 years ago: ⏰",
        "When someone says 'it works on my machine': 🙄",
        "When you finally fix a bug with a single character: 🤯",
    ]
    
    meme_text = random.choice(memes)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": meme_text,
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_poll_command(chat_id: int, user_id: int, text: str):
    """Handle the /poll command."""
    # Extract poll data
    poll_data = text.split("/poll", 1)[1].strip()
    
    if not poll_data:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Usage: `/poll <question>|option1|option2|...`",
            "parse_mode": "Markdown",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    # Parse poll data
    parts = poll_data.split("|")
    if len(parts) < 2:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Please provide at least one question and one option.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    question = parts[0].strip()
    options = [option.strip() for option in parts[1:] if option.strip()]
    
    if len(options) < 2:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Please provide at least two options.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    try:
        # Create poll
        api_request("sendPoll", {
            "chat_id": chat_id,
            "question": question,
            "options": json.dumps(options),
            "is_anonymous": True,
            "reply_to_message_id": request.json["message"]["message_id"]
        })
    except Exception as e:
        logger.error(f"Error creating poll: {e}")
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"❌ Failed to create poll: {str(e)}",
            "reply_to_message_id": request.json["message"]["message_id"]
        })

def handle_stickerid_command(chat_id: int, user_id: int):
    """Handle the /stickerid command."""
    # Check if the command is a reply to a sticker
    replied_message = request.json["message"].get("reply_to_message")
    if not replied_message or "sticker" not in replied_message:
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "❌ Please reply to a sticker to get its ID.",
            "reply_to_message_id": request.json["message"]["message_id"]
        })
        return
    
    sticker = replied_message["sticker"]
    sticker_id = sticker.get("file_id", "Unknown")
    sticker_emoji = sticker.get("emoji", "")
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"🔖 Sticker ID: `{sticker_id}`\nEmoji: {sticker_emoji}",
        "parse_mode": "Markdown",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

def handle_quote_command(chat_id: int, user_id: int):
    """Handle the /quote command."""
    # List of inspirational quotes
    quotes = [
        {
            "text": "The only way to do great work is to love what you do.",
            "author": "Steve Jobs"
        },
        {
            "text": "Innovation distinguishes between a leader and a follower.",
            "author": "Steve Jobs"
        },
        {
            "text": "Your time is limited, so don't waste it living someone else's life.",
            "author": "Steve Jobs"
        },
        {
            "text": "The future belongs to those who believe in the beauty of their dreams.",
            "author": "Eleanor Roosevelt"
        },
        {
            "text": "It is during our darkest moments that we must focus to see the light.",
            "author": "Aristotle"
        },
        {
            "text": "Whoever is happy will make others happy too.",
            "author": "Anne Frank"
        },
        {
            "text": "The purpose of our lives is to be happy.",
            "author": "Dalai Lama"
        },
        {
            "text": "Life is what happens when you're busy making other plans.",
            "author": "John Lennon"
        },
        {
            "text": "Get busy living or get busy dying.",
            "author": "Stephen King"
        },
        {
            "text": "You only live once, but if you do it right, once is enough.",
            "author": "Mae West"
        }
    ]
    
    # Get random quote
    quote = random.choice(quotes)
    
    api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"💭 *{quote['text']}*\n\n— {quote['author']}",
        "parse_mode": "Markdown",
        "reply_to_message_id": request.json["message"]["message_id"]
    })

# Anti-spam and content filters
def check_message_content(chat_id: int, message: Dict[str, Any]) -> bool:
    """
    Check if a message violates any content filters.
    
    Args:
        chat_id: The chat ID
        message: The message object
    
    Returns:
        True if the message is allowed, False if it should be deleted
    """
    # Check if user is admin
    user_id = message["from"]["id"]
    if is_admin(chat_id, user_id):
        return True
    
    # Get chat settings
    lock_links = get_chat_setting(chat_id, "lock_links", False)
    lock_media = get_chat_setting(chat_id, "lock_media", False)
    lock_stickers = get_chat_setting(chat_id, "lock_stickers", False)
    lock_all = get_chat_setting(chat_id, "lock_all", False)
    
    # Check for links
    if lock_links or lock_all:
        text = message.get("text", "")
        entities = message.get("entities", [])
        
        for entity in entities:
            if entity["type"] in ["url", "text_link"]:
                return False
        
        # Simple URL pattern matching
        url_pattern = re.compile(r'https?://\S+|www\.\S+')
        if url_pattern.search(text):
            return False
    
    # Check for media
    if lock_media or lock_all:
        if any(key in message for key in ["photo", "video", "audio", "document", "animation", "video_note", "voice"]):
            return False
    
    # Check for stickers
    if lock_stickers or lock_all:
        if "sticker" in message:
            return False
    
    return True

def check_flood(chat_id: int, user_id: int) -> bool:
    """
    Check if a user is flooding the chat.
    
    Args:
        chat_id: The chat ID
        user_id: The user ID
    
    Returns:
        True if the user is flooding, False otherwise
    """
    # Simple flood detection based on message frequency
    # In a real implementation, you would track message timestamps
    # For now, we'll rely on Telegram's built-in flood protection
    return False

# Webhook endpoint
@app.route(f"/webhook/<webhook_secret>", methods=["POST"])
def webhook(webhook_secret: str):
    """Handle incoming webhook updates from Telegram."""
    # Verify webhook secret
    if webhook_secret != WEBHOOK_SECRET:
        # Check for secret token in header
        secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret_token != WEBHOOK_SECRET:
            logger.warning("Invalid webhook secret")
            abort(403)
    
    # Get update data
    update = request.json
    
    # Process the update
    try:
        # Handle message updates
        if "message" in update:
            message = update["message"]
            chat_id = message["chat"]["id"]
            user_id = message["from"]["id"]
            text = message.get("text", "")
            
            # Check rate limit
            if not check_rate_limit(user_id):
                logger.info(f"Rate limit exceeded for user {user_id}")
                return jsonify({"status": "ok"})
            
            # Handle new chat members
            if "new_chat_members" in message:
                for new_member in message["new_chat_members"]:
                    handle_new_chat_member(chat_id, new_member)
                return jsonify({"status": "ok"})
            
            # Handle left chat member
            if "left_chat_member" in message:
                return jsonify({"status": "ok"})
            
            # Check message content for filters
            if not check_message_content(chat_id, message):
                # Delete the message
                api_request("deleteMessage", {
                    "chat_id": chat_id,
                    "message_id": message["message_id"]
                })
                
                # Warn the user
                warning_count = add_warning(chat_id, user_id, "Posted restricted content")
                
                # Get warning threshold
                warn_threshold = get_chat_setting(chat_id, "warn_threshold", 3)
                
                # Send warning message
                api_request("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"⚠️ Your message was deleted for violating group rules. "
                            f"Warning: {warning_count}/{warn_threshold}"
                })
                
                # Check if threshold reached
                if warning_count >= warn_threshold:
                    # Ban the user
                    api_request("banChatMember", {
                        "chat_id": chat_id,
                        "user_id": user_id
                    })
                    
                    # Add to banned users table
                    with get_db_connection() as conn:
                        conn.execute("INSERT OR REPLACE INTO banned_users (chat_id, user_id) VALUES (?, ?)",
                                    (chat_id, user_id))
                        conn.commit()
                    
                    api_request("sendMessage", {
                        "chat_id": chat_id,
                        "text": f"🚫 User has been banned for reaching the warning threshold."
                    })
                
                return jsonify({"status": "ok"})
            
            # Handle commands
            if text.startswith("/"):
                # Handle /start command
                if text.startswith("/start"):
                    handle_start_command(chat_id, user_id)
                
                # Handle /help command
                elif text.startswith("/help"):
                    handle_help_command(chat_id, user_id)
                
                # Handle /setrules command
                elif text.startswith("/setrules"):
                    handle_setrules_command(chat_id, user_id, text)
                
                # Handle /rules command
                elif text.startswith("/rules"):
                    handle_rules_command(chat_id)
                
                # Handle /warn command
                elif text.startswith("/warn"):
                    handle_warn_command(chat_id, user_id, text)
                
                # Handle /warnings command
                elif text.startswith("/warnings"):
                    handle_warnings_command(chat_id, user_id, text)
                
                # Handle /ban command
                elif text.startswith("/ban"):
                    handle_ban_command(chat_id, user_id, text)
                
                # Handle /unban command
                elif text.startswith("/unban"):
                    handle_unban_command(chat_id, user_id, text)
                
                # Handle /kick command
                elif text.startswith("/kick"):
                    handle_kick_command(chat_id, user_id, text)
                
                # Handle /mute command
                elif text.startswith("/mute"):
                    handle_mute_command(chat_id, user_id, text)
                
                # Handle /unmute command
                elif text.startswith("/unmute"):
                    handle_unmute_command(chat_id, user_id, text)
                
                # Handle /promote command
                elif text.startswith("/promote"):
                    handle_promote_command(chat_id, user_id, text)
                
                # Handle /demote command
                elif text.startswith("/demote"):
                    handle_demote_command(chat_id, user_id, text)
                
                # Handle /pin command
                elif text.startswith("/pin"):
                    handle_pin_command(chat_id, user_id)
                
                # Handle /unpin command
                elif text.startswith("/unpin"):
                    handle_unpin_command(chat_id, user_id)
                
                # Handle /banlist command
                elif text.startswith("/banlist"):
                    handle_banlist_command(chat_id, user_id)
                
                # Handle /getadmins command
                elif text.startswith("/getadmins"):
                    handle_getadmins_command(chat_id, user_id)
                
                # Handle /setwelcome command
                elif text.startswith("/setwelcome"):
                    handle_setwelcome_command(chat_id, user_id, text)
                
                # Handle /welcome command
                elif text.startswith("/welcome"):
                    handle_welcome_command(chat_id, user_id, text)
                
                # Handle /setcaptcha command
                elif text.startswith("/setcaptcha"):
                    handle_setcaptcha_command(chat_id, user_id, text)
                
                # Handle /lock command
                elif text.startswith("/lock"):
                    handle_lock_command(chat_id, user_id, text)
                
                # Handle /cleanup command
                elif text.startswith("/cleanup"):
                    handle_cleanup_command(chat_id, user_id, text)
                
                # Handle /purge command
                elif text.startswith("/purge"):
                    handle_purge_command(chat_id, user_id, text)
                
                # Handle /slowmode command
                elif text.startswith("/slowmode"):
                    handle_slowmode_command(chat_id, user_id, text)
                
                # Handle /id command
                elif text.startswith("/id"):
                    handle_id_command(chat_id, user_id)
                
                # Handle /whois command
                elif text.startswith("/whois"):
                    handle_whois_command(chat_id, user_id, text)
                
                # Handle /stats command
                elif text.startswith("/stats"):
                    handle_stats_command(chat_id, user_id)
                
                # Handle /setlang command
                elif text.startswith("/setlang"):
                    handle_setlang_command(chat_id, user_id, text)
                
                # Handle /backup command
                elif text.startswith("/backup"):
                    handle_backup_command(chat_id, user_id)
                
                # Handle /restore command
                elif text.startswith("/restore"):
                    handle_restore_command(chat_id, user_id, text)
                
                # Handle /roll command
                elif text.startswith("/roll"):
                    handle_roll_command(chat_id, user_id, text)
                
                # Handle /8ball command
                elif text.startswith("/8ball"):
                    handle_8ball_command(chat_id, user_id, text)
                
                # Handle /hug command
                elif text.startswith("/hug"):
                    handle_hug_command(chat_id, user_id, text)
                
                # Handle /slap command
                elif text.startswith("/slap"):
                    handle_slap_command(chat_id, user_id, text)
                
                # Handle /pat command
                elif text.startswith("/pat"):
                    handle_pat_command(chat_id, user_id, text)
                
                # Handle /meme command
                elif text.startswith("/meme"):
                    handle_meme_command(chat_id, user_id)
                
                # Handle /poll command
                elif text.startswith("/poll"):
                    handle_poll_command(chat_id, user_id, text)
                
                # Handle /stickerid command
                elif text.startswith("/stickerid"):
                    handle_stickerid_command(chat_id, user_id)
                
                # Handle /quote command
                elif text.startswith("/quote"):
                    handle_quote_command(chat_id, user_id)
        
        # Handle callback queries
        elif "callback_query" in update:
            handle_callback_query(update["callback_query"])
        
        return jsonify({"status": "ok"})
    
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def handle_new_chat_member(chat_id: int, new_member: Dict[str, Any]):
    """Handle a new chat member event."""
    user_id = new_member["id"]
    user_name = new_member.get("first_name", "Unknown")
    
    # Check if welcome messages are enabled
    welcome_enabled = get_chat_setting(chat_id, "welcome_enabled", True)
    
    if welcome_enabled:
        # Get welcome message
        welcome_message = get_chat_setting(chat_id, "welcome_message")
        
        if not welcome_message:
            # Default welcome message
            welcome_message = f"Welcome {user_name} to the group! Please read the rules and enjoy your stay."
        
        # Replace placeholders
        welcome_message = welcome_message.replace("{name}", user_name)
        welcome_message = welcome_message.replace("{id}", str(user_id))
        welcome_message = welcome_message.replace("{title}", f"Group {chat_id}")
        
        # Send welcome message
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": welcome_message
        })
    
    # Check if captcha is enabled
    captcha_enabled = get_chat_setting(chat_id, "captcha_enabled", False)
    
    if captcha_enabled:
        # Generate captcha challenge
        challenge, answer = create_captcha_challenge(chat_id, user_id)
        
        # Create inline keyboard with the answer
        keyboard = {
            "inline_keyboard": [
                [{"text": answer, "callback_data": f"captcha_verify_{answer}"}]
            ]
        }
        
        # Send captcha message
        api_request("sendMessage", {
            "chat_id": chat_id,
            "text": f"🤖 Please solve this captcha to verify you're human:\n\n{challenge}",
            "reply_markup": json.dumps(keyboard)
        })
        
        # Schedule a task to kick the user if they don't verify
        def kick_if_not_verified():
            time.sleep(300)  # 5 minutes
            try:
                # Check if the user has already verified
                with get_db_connection() as conn:
                    row = conn.execute("SELECT 1 FROM captcha_challenges WHERE chat_id = ? AND user_id = ?",
                                      (chat_id, user_id)).fetchone()
                    
                    # If the challenge still exists, the user hasn't verified
                    if row:
                        # Kick the user
                        api_request("kickChatMember", {
                            "chat_id": chat_id,
                            "user_id": user_id
                        })
                        
                        # Send notification
                        api_request("sendMessage", {
                            "chat_id": chat_id,
                            "text": f"🚫 {user_name} was kicked for not verifying the captcha."
                        })
            except Exception as e:
                logger.error(f"Error in captcha verification check: {e}")
        
        # Start the verification check in a separate thread
        threading.Thread(target=kick_if_not_verified, daemon=True).start()

def set_bot_commands():
    """Set the bot's commands using setMyCommands."""
    commands = [
        {"command": "start", "description": "Start the bot"},
        {"command": "help", "description": "Show help menu"},
        {"command": "setrules", "description": "Set group rules"},
        {"command": "rules", "description": "Display group rules"},
        {"command": "warn", "description": "Warn a user"},
        {"command": "warnings", "description": "Check user's warnings"},
        {"command": "ban", "description": "Ban a user"},
        {"command": "unban", "description": "Unban a user"},
        {"command": "kick", "description": "Kick a user"},
        {"command": "mute", "description": "Mute a user"},
        {"command": "unmute", "description": "Unmute a user"},
        {"command": "promote", "description": "Promote a user to admin"},
        {"command": "demote", "description": "Demote an admin"},
        {"command": "pin", "description": "Pin a message"},
        {"command": "unpin", "description": "Unpin a message"},
        {"command": "banlist", "description": "List banned users"},
        {"command": "getadmins", "description": "List group admins"},
        {"command": "setwelcome", "description": "Set welcome message"},
        {"command": "welcome", "description": "Enable/disable welcome messages"},
        {"command": "setcaptcha", "description": "Enable/disable captcha"},
        {"command": "lock", "description": "Lock certain message types"},
        {"command": "cleanup", "description": "Delete last n messages"},
        {"command": "purge", "description": "Delete all messages from a user"},
        {"command": "slowmode", "description": "Set slowmode delay"},
        {"command": "id", "description": "Get your ID and chat ID"},
        {"command": "whois", "description": "Get user information"},
        {"command": "stats", "description": "Show group statistics"},
        {"command": "setlang", "description": "Set bot language"},
        {"command": "backup", "description": "Backup group data"},
        {"command": "restore", "description": "Restore group from backup"},
        {"command": "roll", "description": "Roll a dice"},
        {"command": "8ball", "description": "Ask the magic 8-ball"},
        {"command": "hug", "description": "Send a hug"},
        {"command": "slap", "description": "Slap someone"},
        {"command": "pat", "description": "Pat someone"},
        {"command": "meme", "description": "Get a random meme"},
        {"command": "poll", "description": "Create a poll"},
        {"command": "stickerid", "description": "Get sticker ID"},
        {"command": "quote", "description": "Get a random quote"}
    ]
    
    try:
        api_request("setMyCommands", {"commands": commands})
        logger.info("Bot commands set successfully")
    except Exception as e:
        logger.error(f"Error setting bot commands: {e}")

# Initialize the database
init_db()

# Set bot commands on startup
set_bot_commands()

# Health check endpoint
@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "ok"})

# Main entry point
if __name__ == "__main__":
    """
    "The best way to predict the future is to invent it."
    — Alan Kay
    
    Kust Robot - A Telegram Group Management Bot
    
    Updates channel: https://t.me/kustbots
    Support group: https://t.me/kustbotschat
    """
    logger.info(f"Starting {BOT_NAME} on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
