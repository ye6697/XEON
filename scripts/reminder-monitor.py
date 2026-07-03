#!/usr/bin/env python3
"""
XEON local reminder monitor.
Checks data/reminders.json and notifies XEON when reminders are due.
"""

import json
import os
import asyncio
import subprocess
import time

import httpx

import sys

WORKSPACE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_PATH not in sys.path:
    sys.path.insert(0, WORKSPACE_PATH)

import reminder_tools  # noqa: E402
import todo_tools  # noqa: E402
import pc_tools  # noqa: E402
import audit_log  # noqa: E402
import prayer_tools  # noqa: E402


CONFIG_PATH = os.path.join(WORKSPACE_PATH, "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
    config = json.load(f)

LAUNCH_SCRIPT = os.path.join(WORKSPACE_PATH, "scripts", "launch-session.ps1")
CHECK_SECONDS = int(config.get("reminder_check_seconds", 15))
SERVER_URL = "http://localhost:8340"


def launch_xeon():
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            LAUNCH_SCRIPT,
        ],
        cwd=WORKSPACE_PATH,
    )


def notify(text: str) -> bool:
    for attempt in range(4):
        try:
            response = httpx.post(
                f"{SERVER_URL}/notify",
                json={"text": text, "speak": True},
                timeout=20,
            )
            if response.status_code == 200 and response.json().get("sent", 0) > 0:
                return True
        except Exception:
            pass
        if attempt == 0:
            launch_xeon()
        time.sleep(6)
    return False


def reminder_message(item: dict) -> str:
    text = item.get("text", "Ihre Erinnerung")
    normalized = text.strip() or "Ihre Erinnerung"
    if "schlaf" in normalized.lower():
        fallback = (
            "Sir, kurze Intervention: Schlafenszeit. "
            "Der CEO-Akku wird jetzt geladen, sonst verhandelt morgen nur noch der Koffein-Ausschuss."
        )
    else:
        fallback = f"Sir, kurzer Einsatzbefehl: {normalized}. Nicht dramatisch, aber jetzt ist der Moment."
    try:
        response = httpx.post(
            f"{SERVER_URL}/api/reminder-phrase",
            json={
                "text": text,
                "due_at": item.get("due_at", ""),
                "source": item.get("source", "local"),
            },
            timeout=25,
        )
        if response.status_code == 200:
            styled = str(response.json().get("text") or "").strip()
            if styled:
                return styled
    except Exception as exc:
        print(f"[xeon-reminders] phrase fallback: {exc}", flush=True)
    return fallback


def todo_message(item: dict) -> str:
    severity = todo_tools.severity_for(item)
    fallback = f"Sir, Nachfassen: {item.get('text', 'offene Aufgabe')}. Ist das erledigt?"
    if severity == "strict":
        fallback = f"Sir, das ist jetzt deutlich ueberfaellig: {item.get('text')}. Ist es erledigt?"
    elif severity == "hard":
        fallback = f"Sir, genug verschoben: {item.get('text')}. Ist die Aufgabe erledigt, ja oder nein?"
    try:
        response = httpx.post(
            f"{SERVER_URL}/api/todo-followup-phrase",
            json={"todo": item},
            timeout=25,
        )
        if response.status_code == 200:
            styled = str(response.json().get("text") or "").strip()
            if styled:
                return styled
    except Exception as exc:
        print(f"[xeon-reminders] todo phrase fallback: {exc}", flush=True)
    return fallback


def main():
    print("[xeon-reminders] monitor started", flush=True)
    while True:
        try:
            prayer = asyncio.run(prayer_tools.due_prayer("Witten", "Germany"))
            if prayer:
                message = prayer_tools.prayer_message(prayer)
                print(f"[xeon-reminders] prayer due: {prayer.get('key')} {prayer.get('time')}", flush=True)
                if notify(message):
                    prayer_tools.mark_notified(str(prayer.get("key") or ""))
                    print(f"[xeon-reminders] prayer notified: {prayer.get('key')}", flush=True)
        except Exception as exc:
            print(f"[xeon-reminders] prayer check failed: {exc}", flush=True)

        for item in reminder_tools.due_reminders():
            text = item.get("text", "Ihre Erinnerung")
            message = reminder_message(item)
            print(f"[xeon-reminders] due: {item.get('id')} {text}", flush=True)
            action = item.get("action")
            if action:
                try:
                    result = pc_tools.execute_pc_operation(action)
                    audit_log.log_action("REMINDER_ACTION", action, "ok", result)
                    print(f"[xeon-reminders] action: {result}", flush=True)
                except Exception as exc:
                    audit_log.log_action("REMINDER_ACTION", action, "error", str(exc))
                    print(f"[xeon-reminders] action failed: {exc}", flush=True)
            if notify(message):
                reminder_tools.mark_notified(item["id"])
                print(f"[xeon-reminders] notified: {item.get('id')}", flush=True)
        todo = todo_tools.due_followup()
        if todo:
            message = todo_message(todo)
            print(f"[xeon-reminders] todo due: {todo.get('id')} {todo.get('text')}", flush=True)
            if notify(message):
                todo_tools.mark_followed_up(todo["id"])
                print(f"[xeon-reminders] todo notified: {todo.get('id')}", flush=True)
        time.sleep(CHECK_SECONDS)


if __name__ == "__main__":
    main()
