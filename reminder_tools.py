import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from dateparser.search import search_dates
except Exception:
    search_dates = None


TIMEZONE = ZoneInfo("Europe/Berlin")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
REMINDERS_PATH = os.path.join(DATA_DIR, "reminders.json")

NUMBER_WORDS = {
    "eine": 1,
    "einer": 1,
    "einen": 1,
    "eins": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fuenf": 5,
    "funf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
}

WEEKDAYS = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,
}


def now_local() -> datetime:
    return datetime.now(TIMEZONE)


def load_reminders() -> list[dict]:
    if not os.path.exists(REMINDERS_PATH):
        return []
    with open(REMINDERS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_reminders(reminders: list[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="reminders-", suffix=".json", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(reminders, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, REMINDERS_PATH)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _parse_number(value: str) -> int | None:
    value = value.strip().lower()
    if value.isdigit():
        return int(value)
    return NUMBER_WORDS.get(value)


def _parse_clock(text: str) -> tuple[int, int, str] | None:
    match = re.search(
        r"\b(?:um|gegen)\s*(\d{1,2})(?:(?:[:.])(\d{2}))?\s*(?:uhr)?\b"
        r"|\b(\d{1,2})\s*uhr(?:\s*(\d{1,2}))?\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    hour = int(match.group(1) or match.group(3))
    minute = int(match.group(2) or match.group(4) or 0)
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute, match.group(0)
    return None


def _combine_date_and_clock(base_date: datetime, clock: tuple[int, int, str] | None) -> datetime | None:
    if not clock:
        return None
    hour, minute, _ = clock
    return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _parse_due(text: str, now: datetime) -> tuple[datetime | None, str]:
    lowered = text.lower()

    relative = re.search(
        r"\bin\s+(\d+|eine|einer|einen|eins|zwei|drei|vier|fuenf|funf|sechs|sieben|acht|neun|zehn)\s+"
        r"(minute|minuten|min|stunde|stunden|tag|tagen|tage|woche|wochen)\b",
        lowered,
        re.IGNORECASE,
    )
    if relative:
        amount = _parse_number(relative.group(1))
        unit = relative.group(2)
        if amount:
            if unit.startswith(("minute", "min")):
                return now + timedelta(minutes=amount), relative.group(0)
            if unit.startswith("stunde"):
                return now + timedelta(hours=amount), relative.group(0)
            if unit.startswith(("tag", "tage")):
                return now + timedelta(days=amount), relative.group(0)
            if unit.startswith("woche"):
                return now + timedelta(weeks=amount), relative.group(0)

    clock = _parse_clock(lowered)
    day_offsets = {
        "heute": 0,
        "morgen": 1,
        "uebermorgen": 2,
        "übermorgen": 2,
    }
    for token, offset in day_offsets.items():
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            due = _combine_date_and_clock(now + timedelta(days=offset), clock)
            if due:
                if due <= now and offset == 0:
                    due += timedelta(days=1)
                phrase = token
                if clock:
                    phrase = f"{token} {clock[2]}".strip()
                return due, phrase
            return None, token

    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b(?:naechsten|nächsten|diesen|kommenden)?\s*{name}\b", lowered):
            days_ahead = (weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            due = _combine_date_and_clock(now + timedelta(days=days_ahead), clock)
            if due:
                phrase = name
                if clock:
                    phrase = f"{name} {clock[2]}".strip()
                return due, phrase
            return None, name

    date_match = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", lowered)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            base = datetime(year, month, day, tzinfo=TIMEZONE)
            due = _combine_date_and_clock(base, clock)
            if due and due <= now:
                due = due.replace(year=due.year + 1)
            if due:
                phrase = date_match.group(0)
                if clock:
                    phrase = f"{phrase} {clock[2]}".strip()
                return due, phrase
            return None, date_match.group(0)
        except ValueError:
            return None, date_match.group(0)

    if clock:
        due = _combine_date_and_clock(now, clock)
        if due and due <= now:
            due += timedelta(days=1)
        return due, clock[2]

    if search_dates:
        found = search_dates(
            text,
            languages=["de"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": now.replace(tzinfo=None),
                "TIMEZONE": "Europe/Berlin",
                "RETURN_AS_TIMEZONE_AWARE": True,
            },
        )
        if found:
            phrase, due = found[0]
            if due.tzinfo is None:
                due = due.replace(tzinfo=TIMEZONE)
            else:
                due = due.astimezone(TIMEZONE)
            return due, phrase

    return None, ""


def _clean_task(text: str, date_phrase: str) -> str:
    task = text
    task = re.sub(r"\b(?:oeffne|öffne)\s+dabei\s+(?:dann\s+)?(?:auch\s+)?(.+)$", " ", task, flags=re.IGNORECASE)
    if date_phrase:
        task = re.sub(re.escape(date_phrase), " ", task, flags=re.IGNORECASE)
    task = re.sub(r"\bin\s+\S+\s+(?:minute|minuten|min|stunde|stunden|tag|tagen|tage|woche|wochen)\b", " ", task, flags=re.IGNORECASE)
    task = re.sub(r"\b(?:heute|morgen|uebermorgen|übermorgen)\b", " ", task, flags=re.IGNORECASE)
    task = re.sub(r"\b(?:naechsten|nächsten|diesen|kommenden)?\s*(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b", " ", task, flags=re.IGNORECASE)
    task = re.sub(r"\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\.?\b", " ", task)
    task = re.sub(r"\b(?:um|gegen)\s*\d{1,2}(?:(?:[:.])\d{2})?\s*(?:uhr)?\b", " ", task, flags=re.IGNORECASE)
    task = re.sub(r"\b\d{1,2}\s*uhr(?:\s*\d{1,2})?\b", " ", task, flags=re.IGNORECASE)
    patterns = [
        r"\berinnere\s+mich\b",
        r"\berinner\s+mich\b",
        r"\berinnerung\b",
        r"\bmerk\s+dir\b",
        r"\bmerke\s+dir\b",
        r"\bsollst\s+du\s+mich\s+erinnern\b",
        r"\bdaran\b",
        r"\ban\b",
        r"\bam\b",
        r"\bab\b",
        r"\bdass\b",
        r"\bdas\b",
        r"\bmich\b",
        r"\bbitte\b",
        r"\bzu\b",
    ]
    for pattern in patterns:
        task = re.sub(pattern, " ", task, flags=re.IGNORECASE)
    task = re.sub(r"\s+", " ", task).strip(" ,.-")
    return task or "Ihre Erinnerung"


def _extract_action(text: str) -> dict | None:
    match = re.search(r"\b(?:oeffne|öffne)\s+dabei\s+(?:dann\s+)?(?:auch\s+)?(.+)$", text, re.IGNORECASE)
    if not match:
        return None
    target = match.group(1).strip(" .,!?:;")
    if not target:
        return None
    return {"operation": "open", "target": target}


def is_reminder_request(text: str) -> bool:
    t = text.lower()
    return any(token in t for token in ["erinnere", "erinner mich", "erinnerung", "merk dir", "merke dir"])


def create_reminder(raw_text: str) -> dict:
    now = now_local()
    due, date_phrase = _parse_due(raw_text, now)
    if not due:
        return {
            "ok": False,
            "error": "Ich brauche fuer die Erinnerung eine klare Zeit, Sir. Zum Beispiel: morgen um 9 Uhr oder in 20 Minuten.",
        }
    if due <= now:
        return {
            "ok": False,
            "error": "Diese Zeit liegt bereits in der Vergangenheit, Sir. Nennen Sie mir bitte eine zukuenftige Zeit.",
        }

    task = _clean_task(raw_text, date_phrase)
    reminder = {
        "id": uuid.uuid4().hex[:12],
        "text": task,
        "source": raw_text,
        "action": _extract_action(raw_text),
        "due_at": due.isoformat(),
        "created_at": now.isoformat(),
        "notified_at": None,
    }
    reminders = load_reminders()
    reminders.append(reminder)
    reminders.sort(key=lambda item: item.get("due_at", ""))
    save_reminders(reminders)
    return {"ok": True, "reminder": reminder}


def pending_reminders(limit: int = 5) -> list[dict]:
    reminders = [
        item for item in load_reminders()
        if not item.get("notified_at")
    ]
    reminders.sort(key=lambda item: item.get("due_at", ""))
    return reminders[:limit]


def due_reminders() -> list[dict]:
    now = now_local()
    due = []
    for item in load_reminders():
        if item.get("notified_at"):
            continue
        try:
            due_at = datetime.fromisoformat(item["due_at"])
        except Exception:
            continue
        if due_at <= now:
            due.append(item)
    return due


def mark_notified(reminder_id: str) -> None:
    reminders = load_reminders()
    stamped = now_local().isoformat()
    for item in reminders:
        if item.get("id") == reminder_id:
            item["notified_at"] = stamped
            break
    save_reminders(reminders)


def format_due(due_at: str) -> str:
    due = datetime.fromisoformat(due_at).astimezone(TIMEZONE)
    return due.strftime("%d.%m.%Y um %H:%M Uhr")
