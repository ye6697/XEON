import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ACTION_LOG_PATH = os.path.join(DATA_DIR, "action_log.jsonl")
TIMEZONE = ZoneInfo("Europe/Berlin")


def log_action(action_type: str, payload: dict | str | None, status: str, result: str = "") -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    entry = {
        "timestamp": datetime.now(TIMEZONE).isoformat(),
        "action_type": action_type,
        "payload": payload,
        "status": status,
        "result": result[:2000] if result else "",
    }
    with open(ACTION_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
