import time
import logging
import requests
from config import BOT_TOKEN

logger = logging.getLogger(__name__)
_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def api_request(method: str, params: dict = None, files: dict = None) -> dict:
    url = f"{_BASE}/{method}"
    params = params or {}
    max_retries = 5
    delay = 1

    for attempt in range(max_retries):
        try:
            if files:
                resp = requests.post(url, params=params, files=files, timeout=10)
            else:
                resp = requests.post(url, json=params, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data.get("result", {})
                logger.error(f"API error [{method}]: {data}")
                raise Exception(data.get("description", "Unknown API error"))

            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", delay))
                logger.warning(f"Rate limited, retrying in {wait}s")
                time.sleep(wait)
                delay *= 2
                continue

            if 500 <= resp.status_code < 600:
                logger.warning(f"Server error {resp.status_code}, retrying")
                time.sleep(delay)
                delay *= 2
                continue

            raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")

        except requests.RequestException as e:
            logger.error(f"Request error [{method}]: {e}")
            if attempt == max_retries - 1:
                raise Exception(f"Request failed after {max_retries} attempts: {e}")
            time.sleep(delay)
            delay *= 2

    raise Exception(f"API request [{method}] failed after {max_retries} attempts")
