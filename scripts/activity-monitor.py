#!/usr/bin/env python3
"""
XEON - Local activity monitor.
Tracks foreground process/window titles and nudges the user after extended game focus.
No keystrokes, browser contents, or files are recorded.
"""

import ctypes
import json
import os
import subprocess
import time
from ctypes import wintypes

import httpx


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
    config = json.load(f)

GAME_PROCESSES = {
    "steam.exe", "epicgameslauncher.exe", "riotclientservices.exe", "leagueclient.exe",
    "valorant-win64-shipping.exe", "fortniteclient-win64-shipping.exe", "cs2.exe",
    "minecraft.exe", "robloxplayerbeta.exe", "gta5.exe", "fivem.exe", "cod.exe",
}
CHECK_SECONDS = 15
GAME_LIMIT_SECONDS = int(config.get("game_focus_limit_minutes", 35)) * 60
BUSINESS_CHECK_SECONDS = int(config.get("business_focus_check_minutes", 90)) * 60
NUDGE_COOLDOWN_SECONDS = 20 * 60
WORKSPACE_PATH = config["workspace_path"]
LAUNCH_SCRIPT = os.path.join(WORKSPACE_PATH, "scripts", "launch-session.ps1")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi


def foreground_process_name() -> tuple[str, str]:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid.value)
    process_name = ""
    if handle:
        try:
            buf = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(handle, None, buf, 260):
                process_name = buf.value.lower()
        finally:
            kernel32.CloseHandle(handle)

    title_buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title_buf, 512)
    return process_name, title_buf.value


def notify_xeon(text: str):
    try:
        httpx.post("http://localhost:8340/notify", json={"text": text, "speak": True}, timeout=8)
    except Exception:
        pass


def ensure_xeon_open():
    try:
        httpx.get("http://localhost:8340/", timeout=3)
    except Exception:
        subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-File", LAUNCH_SCRIPT])
        time.sleep(8)


def is_business_context(proc: str, title: str) -> bool:
    t = f"{proc} {title}".lower()
    return any(token in t for token in [
        "mysuppliex", "codex", "code.exe", "chrome.exe", "base44", "calendar",
        "excel", "notion", "obsidian", "teams", "outlook", "mail", "github",
    ])


def main():
    current_game_started = None
    last_nudge = 0.0
    last_business_seen = time.time()
    while True:
        proc, title = foreground_process_name()
        now = time.time()
        is_game = proc in GAME_PROCESSES or any(token in title.lower() for token in ["steam", "valorant", "fortnite", "minecraft", "league of legends"])
        if is_business_context(proc, title):
            last_business_seen = now

        if is_game:
            if current_game_started is None:
                current_game_started = now
            if now - current_game_started >= GAME_LIMIT_SECONDS and now - last_nudge >= NUDGE_COOLDOWN_SECONDS:
                ensure_xeon_open()
                notify_xeon(
                    "Sir, Sie sind seit einer Weile im Spielmodus. Kurzer strategischer Einschub: "
                    "ein CEO kann entspannen, aber nicht verschwinden. Fuenf Minuten Abschluss, dann zurueck an MySupplieX."
                )
                last_nudge = now
        else:
            current_game_started = None

        if now - last_business_seen >= BUSINESS_CHECK_SECONDS and now - last_nudge >= NUDGE_COOLDOWN_SECONDS:
            ensure_xeon_open()
            notify_xeon(
                "Sir, ich sehe seit einer Weile keinen klaren Business-Fokus. "
                "Vorschlag: oeffnen Sie MySupplieX, pruefen Sie Orders und setzen Sie eine konkrete Wachstumsaktion fuer heute."
            )
            last_nudge = now

        time.sleep(CHECK_SECONDS)


if __name__ == "__main__":
    main()
