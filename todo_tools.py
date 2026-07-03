import json
import os
import random
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Europe/Berlin")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TODOS_PATH = os.path.join(DATA_DIR, "todos.json")


def now_local() -> datetime:
    return datetime.now(TIMEZONE)


def load_todos() -> list[dict]:
    if not os.path.exists(TODOS_PATH):
        return []
    with open(TODOS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_todos(todos: list[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="todos-", suffix=".json", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(todos, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, TODOS_PATH)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TIMEZONE)
    return dt.astimezone(TIMEZONE)


def is_todo_request(text: str) -> bool:
    normalized = normalize(text)
    return bool(
        re.search(r"\b(todo|to do|aufgabe|task|erledigen|muss ich|ich muss|muss noch|machen muss|machen soll|zu machen|setze.*aufgabe|notier.*aufgabe)\b", normalized)
        and not re.search(r"\b(liste|zeige|was.*offen|offene)\b", normalized)
    )


def is_todo_list_request(text: str) -> bool:
    normalized = normalize(text)
    return bool(
        re.search(r"\b(todo|todos|aufgabe|aufgaben|tasks)\b", normalized)
        and re.search(r"\b(liste|zeige|offen|status|uebersicht|übersicht)\b", normalized)
    )


def is_completion_reply(text: str) -> bool:
    normalized = normalize(text).strip(" .,!?:;")
    if normalized in {
        "ja", "jap", "jo", "yes", "erledigt", "ist erledigt", "habe ich erledigt",
        "gemacht", "fertig", "done", "abgeschlossen", "ja erledigt",
    }:
        return True
    return bool(re.search(
        r"\b(ich\s+)?(habe|hab|hatte)\s+(es|das|die\s+aufgabe|den\s+auftrag)?\s*(gemacht|erledigt|abgeschlossen|fertig\s+gemacht)\b",
        normalized,
    ))


def normalize(text: str) -> str:
    return (
        str(text or "").lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def clean_task(text: str) -> str:
    task = str(text or "").strip()
    task = re.sub(r"\b(?:xeon|bitte)\b", " ", task, flags=re.IGNORECASE)
    task = re.sub(r"\b(?:setze|mach|lege|notier(?:e)?|erstelle|speicher(?:e)?)\b", " ", task, flags=re.IGNORECASE)
    task = re.sub(r"\b(?:todo|to do|aufgabe|task|erledigen|auf meine liste|in die liste)\b", " ", task, flags=re.IGNORECASE)
    task = re.sub(r"\b(?:ich muss|muss ich|muss noch|soll ich|soll noch)\b", " ", task, flags=re.IGNORECASE)
    task = re.sub(r"\s+", " ", task).strip(" .,!?:;-")
    return task or "offene Aufgabe"


def fingerprint(text: str) -> str:
    normalized = normalize(text)
    normalized = re.sub(r"\b(?:sir|xeon|bitte|erinner(?:e|n|ung)?|todo|aufgabe|task|ich|mich|mir|dass|das|an|am|um|uhr|heute|morgen|uebermorgen|machen|muss|soll|sollst|du|noch)\b", " ", normalized)
    normalized = re.sub(r"\b\d{1,2}(?::|\.)?\d{0,2}\b", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def severity_for(todo: dict, now: datetime | None = None) -> str:
    now = now or now_local()
    created = parse_dt(todo.get("created_at", now.isoformat()))
    age_days = max(0, (now - created).total_seconds() / 86400)
    if age_days >= 4:
        return "hard"
    if age_days >= 2:
        return "strict"
    return "normal"


def next_followup_at(now: datetime | None = None, severity: str = "normal") -> str:
    now = now or now_local()
    if severity == "hard":
        minutes = random.randint(25, 75)
    elif severity == "strict":
        minutes = random.randint(55, 150)
    else:
        minutes = random.randint(120, 420)
    return (now + timedelta(minutes=minutes)).isoformat()


def create_todo(raw_text: str, source: str = "desktop", rewritten_text: str | None = None) -> dict:
    now = now_local()
    task = (rewritten_text or clean_task(raw_text)).strip()
    fp = fingerprint(task or raw_text)
    for existing in open_todos():
        if fingerprint(existing.get("text") or existing.get("raw_text") or "") == fp and fp:
            existing["duplicate"] = True
            return existing
    todo = {
        "id": uuid.uuid4().hex,
        "text": task,
        "raw_text": raw_text,
        "source": source,
        "status": "open",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "last_followup_at": "",
        "next_followup_at": next_followup_at(now),
        "followup_count": 0,
        "awaiting_confirmation": False,
        "fingerprint": fp,
    }
    todos = load_todos()
    todos.append(todo)
    save_todos(todos)
    return todo


def open_todos() -> list[dict]:
    todos = [item for item in load_todos() if item.get("status") == "open"]
    todos.sort(key=lambda item: item.get("created_at", ""))
    return todos


def pending_confirmation() -> dict | None:
    focused = [
        item for item in open_todos()
        if item.get("active_context_at")
    ]
    focused.sort(key=lambda item: item.get("active_context_at", ""), reverse=True)
    if focused:
        return focused[0]
    active = [
        item for item in open_todos()
        if item.get("awaiting_confirmation") or item.get("awaiting_evidence")
    ]
    active.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    if active:
        return active[0]
    rejected = [
        item for item in open_todos()
        if item.get("verification_status") == "rejected" and item.get("claimed_done_at")
    ]
    rejected.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    if rejected:
        return rejected[0]
    return None


def activate_context(todo_id: str, source: str = "xeon") -> dict | None:
    todos = load_todos()
    now = now_local().isoformat()
    updated = None
    for item in todos:
        if item.get("status") != "open":
            item.pop("active_context_at", None)
            item.pop("active_context_source", None)
            continue
        if item.get("id") == todo_id:
            item["active_context_at"] = now
            item["active_context_source"] = source
            item["updated_at"] = now
            updated = item
        else:
            item.pop("active_context_at", None)
            item.pop("active_context_source", None)
    save_todos(todos)
    return updated


def clear_context(todo_id: str | None = None) -> None:
    todos = load_todos()
    changed = False
    for item in todos:
        if todo_id is None or item.get("id") == todo_id:
            if "active_context_at" in item or "active_context_source" in item:
                item.pop("active_context_at", None)
                item.pop("active_context_source", None)
                changed = True
    if changed:
        save_todos(todos)


def mark_claimed_done(todo_id: str) -> dict | None:
    todos = load_todos()
    now = now_local().isoformat()
    updated = None
    for item in todos:
        if item.get("id") == todo_id and item.get("status") == "open":
            item["claimed_done_at"] = now
            item["awaiting_confirmation"] = False
            item["awaiting_evidence"] = True
            item["active_context_at"] = now
            item["active_context_source"] = "claimed_done"
            item["updated_at"] = now
            updated = item
        else:
            item.pop("active_context_at", None)
            item.pop("active_context_source", None)
    save_todos(todos)
    return updated


def mark_done(todo_id: str) -> dict | None:
    todos = load_todos()
    now = now_local().isoformat()
    updated = None
    for item in todos:
        if item.get("id") == todo_id:
            item["status"] = "done"
            item["completed_at"] = now
            item["updated_at"] = now
            item["awaiting_confirmation"] = False
            item["awaiting_evidence"] = False
            item.pop("active_context_at", None)
            item.pop("active_context_source", None)
            item["verification_status"] = "verified"
            updated = item
            break
    save_todos(todos)
    return updated


def due_followup() -> dict | None:
    now = now_local()
    candidates = []
    for item in open_todos():
        if item.get("awaiting_confirmation"):
            continue
        due_raw = item.get("next_followup_at")
        try:
            due = parse_dt(due_raw)
        except Exception:
            due = now
        if due <= now:
            candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (severity_for(item, now) != "hard", item.get("next_followup_at", "")))
    return candidates[0]


def mark_followed_up(todo_id: str) -> dict | None:
    todos = load_todos()
    now = now_local()
    updated = None
    for item in todos:
        if item.get("id") == todo_id and item.get("status") == "open":
            severity = severity_for(item, now)
            item["last_followup_at"] = now.isoformat()
            item["next_followup_at"] = next_followup_at(now, severity)
            item["followup_count"] = int(item.get("followup_count") or 0) + 1
            item["awaiting_confirmation"] = True
            item["awaiting_evidence"] = False
            item["active_context_at"] = now.isoformat()
            item["active_context_source"] = "followup"
            item["updated_at"] = now.isoformat()
            updated = item
        else:
            item.pop("active_context_at", None)
            item.pop("active_context_source", None)
    save_todos(todos)
    return updated


def snooze_confirmation(todo_id: str) -> None:
    todos = load_todos()
    now = now_local()
    for item in todos:
        if item.get("id") == todo_id and item.get("status") == "open":
            severity = severity_for(item, now)
            item["awaiting_confirmation"] = False
            item["awaiting_evidence"] = False
            item.pop("active_context_at", None)
            item.pop("active_context_source", None)
            item["next_followup_at"] = next_followup_at(now, severity)
            item["updated_at"] = now.isoformat()
            break
    save_todos(todos)


def mark_verification_failed(todo_id: str, reason: str = "") -> dict | None:
    todos = load_todos()
    now = now_local()
    updated = None
    for item in todos:
        if item.get("id") == todo_id and item.get("status") == "open":
            severity = severity_for(item, now)
            item["awaiting_confirmation"] = False
            item["awaiting_evidence"] = True
            item["verification_status"] = "rejected"
            item["verification_reason"] = reason[:500]
            item["active_context_at"] = now.isoformat()
            item["active_context_source"] = "evidence_rejected"
            item["next_followup_at"] = next_followup_at(now, severity)
            item["updated_at"] = now.isoformat()
            updated = item
        else:
            item.pop("active_context_at", None)
            item.pop("active_context_source", None)
    save_todos(todos)
    return updated


def restore_rejected_evidence_context() -> int:
    todos = load_todos()
    changed = 0
    for item in todos:
        if (
            item.get("status") == "open"
            and item.get("verification_status") == "rejected"
            and item.get("claimed_done_at")
            and not item.get("awaiting_evidence")
        ):
            item["awaiting_evidence"] = True
            item["awaiting_confirmation"] = False
            item["updated_at"] = now_local().isoformat()
            changed += 1
    if changed:
        save_todos(todos)
    return changed
