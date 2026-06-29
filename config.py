import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "297310471047")
ADMIN_IDS = (
    set(map(int, os.getenv("ADMIN_IDS", "5268762773").split(",")))
    if os.getenv("ADMIN_IDS")
    else {5268762773}
)
PORT = int(os.getenv("PORT", 5000))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "kustrobot")

BOT_NAME = "Kust Robot"
UPDATES_CHANNEL = "https://t.me/kustbots"
SUPPORT_GROUP = "https://t.me/kustbotschat"
