"""File-backed notifications shared by the Admin API and Telegram bot."""
import json
import os
from glob import glob


_QUEUE_DIR = os.path.join(os.path.dirname(__file__), "notification_queue")


def pending_notifications() -> list[str]:
    os.makedirs(_QUEUE_DIR, exist_ok=True)
    return sorted(glob(os.path.join(_QUEUE_DIR, "*.json")))


def read_notification(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def remove_notification(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass