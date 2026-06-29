from pymongo import MongoClient
from config import MONGO_URI, DB_NAME

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGO_URI)
        _db = _client[DB_NAME]
    return _db


def chat_settings_col():
    return get_db()["chat_settings"]


def warnings_col():
    return get_db()["warnings"]


def banned_users_col():
    return get_db()["banned_users"]


def captcha_col():
    return get_db()["captcha_challenges"]


def notes_col():
    return get_db()["notes"]


def blacklist_col():
    return get_db()["blacklist"]


def filters_col():
    return get_db()["filters"]
