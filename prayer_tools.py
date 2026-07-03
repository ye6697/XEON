import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx


TIMEZONE = ZoneInfo("Europe/Berlin")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
STATE_PATH = os.path.join(DATA_DIR, "prayer_state.json")
PRAYERS = [
    ("Fajr", "Fadschr"),
    ("Dhuhr", "Dhuhr"),
    ("Asr", "Asr"),
    ("Maghrib", "Maghrib"),
    ("Isha", "Ischa"),
]


def now_local() -> datetime:
    return datetime.now(TIMEZONE)


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _clean_time(value: str) -> str:
    return str(value or "").split(" ")[0].strip()


async def fetch_prayer_times(city: str = "Witten", country: str = "Germany") -> dict:
    date_key = now_local().strftime("%d-%m-%Y")
    url = f"https://api.aladhan.com/v1/timingsByCity/{date_key}"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        response = await client.get(url, params={"city": city, "country": country, "method": 13})
        response.raise_for_status()
        data = response.json()
    timings = ((data.get("data") or {}).get("timings") or {})
    result = {}
    today = now_local().date()
    for key, label in PRAYERS:
        raw = _clean_time(timings.get(key, ""))
        if not raw:
            continue
        hour, minute = [int(part) for part in raw.split(":")[:2]]
        result[key] = {
            "key": key,
            "label": label,
            "time": raw,
            "due_at": datetime(today.year, today.month, today.day, hour, minute, tzinfo=TIMEZONE).isoformat(),
        }
    return result


async def due_prayer(city: str = "Witten", country: str = "Germany", grace_minutes: int = 80) -> dict | None:
    now = now_local()
    today_key = now.strftime("%Y-%m-%d")
    state = load_state()
    if state.get("date") != today_key:
        state = {"date": today_key, "notified": []}
        save_state(state)
    notified = set(state.get("notified") or [])
    try:
        timings = await fetch_prayer_times(city, country)
    except Exception as exc:
        print(f"[prayer] fetch failed: {exc}", flush=True)
        return None

    due_items = []
    for key, _label in PRAYERS:
        item = timings.get(key)
        if not item or key in notified:
            continue
        due_at = datetime.fromisoformat(item["due_at"])
        if due_at <= now and now - due_at <= timedelta(minutes=grace_minutes):
            due_items.append(item)
    if not due_items:
        return None
    # Only the latest currently due prayer, no backlog stack.
    return due_items[-1]


def mark_notified(prayer_key: str) -> None:
    now = now_local()
    today_key = now.strftime("%Y-%m-%d")
    state = load_state()
    if state.get("date") != today_key:
        state = {"date": today_key, "notified": []}
    notified = list(state.get("notified") or [])
    if prayer_key not in notified:
        notified.append(prayer_key)
    state["notified"] = notified
    save_state(state)


def prayer_message(item: dict) -> str:
    label = item.get("label") or item.get("key") or "Gebet"
    time_text = item.get("time") or ""
    return (
        f"Sir, {label} ist jetzt faellig, Gebetszeit Witten: {time_text} Uhr. "
        "Kein Nachweis, kein Theater; nur eine saubere Erinnerung, damit der Tag seine Ordnung behaelt."
    )
