#!/usr/bin/env python3
"""
XEON - Local activity monitor.
Tracks foreground process/window titles and nudges the user after extended game focus.
No keystrokes, browser contents, or files are recorded.
"""

import ctypes
import csv
import json
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes

import httpx


WORKSPACE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_PATH not in sys.path:
    sys.path.insert(0, WORKSPACE_PATH)

import todo_tools  # noqa: E402


CONFIG_PATH = os.path.join(WORKSPACE_PATH, "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
    config = json.load(f)

DEFAULT_GAME_PROCESSES = {
    "steam.exe", "epicgameslauncher.exe", "riotclientservices.exe", "leagueclient.exe",
    "valorant-win64-shipping.exe", "fortniteclient-win64-shipping.exe", "cs2.exe",
    "minecraft.exe", "robloxplayerbeta.exe", "gta5.exe", "fivem.exe", "cod.exe",
    "javaw.exe", "r5apex.exe", "rocketleague.exe", "pubg.exe", "tslgame.exe",
    "deadbydaylight-win64-shipping.exe", "helldivers2.exe", "eldenring.exe",
    "cyberpunk2077.exe", "witcher3.exe", "battle.net.exe", "eadesktop.exe",
    "ealauncher.exe", "origin.exe", "ubisoftconnect.exe",
}


def discover_xbox_game_exes() -> set[str]:
    names: set[str] = set()
    for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = fr"{drive}:\XboxGames"
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                lower = filename.lower()
                if lower.endswith(".exe"):
                    names.add(lower)
    return names


def discover_windowsapps_game_tokens() -> list[str]:
    tokens = []
    powershell = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-AppxPackage | "
            "Where-Object { $_.InstallLocation -like '*WindowsApps*' -and "
            "($_.Name -match 'Bethesda|Doom|Wolfenstein|Resident|FlightSimulator|Forza|Halo|Minecraft|SeaOfThieves|Gears|Game') } | "
            "Select-Object -ExpandProperty Name"
        ),
    ]
    try:
        result = subprocess.run(
            powershell,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return tokens
    for line in result.stdout.splitlines():
        value = re.sub(r"[^a-z0-9]+", " ", line.lower()).strip()
        if value and value not in tokens:
            tokens.append(value)
    return tokens


GAME_PROCESSES = (
    {str(item).lower() for item in config.get("focus_guard_game_processes", sorted(DEFAULT_GAME_PROCESSES))}
    | discover_xbox_game_exes()
)
GAME_TITLE_TOKENS = [
    str(item).lower()
    for item in config.get(
        "focus_guard_game_title_tokens",
        [
            "steam", "valorant", "fortnite", "minecraft", "league of legends", "roblox",
            "gta", "fivem", "call of duty", "warzone", "counter-strike", "cs2",
            "rocket league", "apex legends", "pubg", "battle.net", "epic games",
            "riot client", "ea sports", "fifa", "fc 24", "fc 25", "playstation",
        ],
    )
] + discover_windowsapps_game_tokens()
CHECK_SECONDS = 15
GAME_LIMIT_SECONDS = int(config.get("game_focus_limit_minutes", 35)) * 60
BUSINESS_CHECK_SECONDS = int(config.get("business_focus_check_minutes", 90)) * 60
NUDGE_COOLDOWN_SECONDS = 20 * 60
FOCUS_GUARD_ENABLED = bool(config.get("focus_guard_enabled", True))
FOCUS_GUARD_TERMINATE_GAMES = bool(config.get("focus_guard_terminate_games", True))
FOCUS_GUARD_COOLDOWN_SECONDS = int(config.get("focus_guard_cooldown_seconds", 90))
FOCUS_GUARD_CHECK_SECONDS = int(config.get("focus_guard_check_seconds", 2))
LAUNCH_SCRIPT = os.path.join(WORKSPACE_PATH, "scripts", "launch-session.ps1")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi


def norm_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expandvars(str(value or ""))))


def existing_game_dirs() -> list[str]:
    dirs = []
    configured = config.get("focus_guard_game_dirs", [])
    for path in configured:
        if path and os.path.exists(os.path.expandvars(str(path))):
            dirs.append(norm_path(os.path.expandvars(str(path))))
    for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        for candidate in [
            fr"{drive}:\XboxGames",
            fr"{drive}:\Games",
            fr"{drive}:\SteamLibrary\steamapps\common",
            fr"{drive}:\Program Files (x86)\Steam\steamapps\common",
        ]:
            if os.path.exists(candidate):
                dirs.append(norm_path(candidate))
    steam_config = os.path.expandvars(r"%PROGRAMFILES(X86)%\Steam\steamapps\libraryfolders.vdf")
    if os.path.exists(steam_config):
        try:
            text = open(steam_config, "r", encoding="utf-8", errors="ignore").read()
            for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                lib = match.group(1).replace("\\\\", "\\")
                common = os.path.join(lib, "steamapps", "common")
                if os.path.exists(common):
                    dirs.append(norm_path(common))
        except OSError:
            pass
    unique = []
    for path in dirs:
        if path not in unique:
            unique.append(path)
    return unique


GAME_DIRS = existing_game_dirs()
SAFE_PROCESS_NAMES = {
    "explorer.exe", "chrome.exe", "msedge.exe", "code.exe", "python.exe", "powershell.exe",
    "cmd.exe", "conhost.exe", "gamebarpresencewriter.exe", "gameinputredistservice.exe",
    "gameinputsvc.exe", "gamingservices.exe", "gamingservicesnet.exe", "xgamehelper.exe",
    "xboxpcappft.exe", "applicationframehost.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "widgetboard.exe", "widgetservice.exe", "microsoftstartfeedprovider.exe",
}


def foreground_process_name() -> tuple[int, str, str]:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0, "", ""

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
    return int(pid.value), process_name, title_buf.value


def notify_xeon(text: str, todo_id: str = "", source: str = "activity-monitor"):
    try:
        httpx.post(
            "http://localhost:8340/notify",
            json={"text": text, "speak": True, "todo_id": todo_id, "source": source},
            timeout=8,
        )
    except Exception:
        pass


def hard_overdue_todos() -> list[dict]:
    return [todo for todo in todo_tools.open_todos() if todo_tools.severity_for(todo) == "hard"]


def terminate_process_by_pid(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
        return True
    except Exception:
        return False


def terminate_game_process(proc: str) -> bool:
    proc = (proc or "").strip().lower()
    if not proc or proc not in GAME_PROCESSES:
        return False
    try:
        subprocess.run(
            ["taskkill.exe", "/IM", proc, "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
        return True
    except Exception:
        return False


def process_rows() -> list[tuple[int, str, str, str]]:
    powershell = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Csv -NoTypeInformation",
    ]
    try:
        result = subprocess.run(
            powershell,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=12,
            check=False,
        )
    except Exception:
        return []
    rows = []
    for row in csv.reader(result.stdout.splitlines()):
        if not row or row[0] == "ProcessId" or len(row) < 4:
            continue
        try:
            pid = int(row[0])
        except ValueError:
            continue
        rows.append((pid, row[1].strip().lower(), row[2].strip(), row[3].strip()))
    return rows


def is_game_process(name: str, path: str, command_line: str = "") -> bool:
    name = (name or "").lower()
    path_norm = norm_path(path) if path else ""
    command_norm = norm_path(command_line) if command_line else ""
    if name in GAME_PROCESSES:
        return True
    if name in SAFE_PROCESS_NAMES:
        return False
    combined = f"{name} {path_norm} {command_norm}".lower()
    if any(token in combined for token in GAME_TITLE_TOKENS):
        return True
    if "\\windowsapps\\" in combined and any(token in combined for token in [
        "bethesda", "doom", "wolfenstein", "resident", "flightsimulator", "forza",
        "halo", "minecraft", "seaofthieves", "gears", "game",
    ]):
        return True
    if path_norm and any(path_norm.startswith(game_dir + os.sep) or path_norm == game_dir for game_dir in GAME_DIRS):
        return True
    if command_norm and any(game_dir in command_norm for game_dir in GAME_DIRS):
        return True
    return False


def running_game_processes() -> list[tuple[int, str]]:
    matches = []
    for pid, name, path, command_line in process_rows():
        if is_game_process(name, path, command_line):
            matches.append((pid, name))
    return matches


def ensure_xeon_open(force_window: bool = False):
    if force_window:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", LAUNCH_SCRIPT, "-Mode", "focus_guard"],
            cwd=WORKSPACE_PATH,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(4)
        return
    try:
        httpx.get("http://localhost:8340/", timeout=3)
    except Exception:
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", LAUNCH_SCRIPT], cwd=WORKSPACE_PATH)
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
    last_focus_guard = 0.0
    last_business_seen = time.time()
    while True:
        pid, proc, title = foreground_process_name()
        now = time.time()
        title_l = title.lower()
        is_game = proc in GAME_PROCESSES or any(token in title_l for token in GAME_TITLE_TOKENS)
        if is_business_context(proc, title):
            last_business_seen = now

        hard_todos = hard_overdue_todos() if FOCUS_GUARD_ENABLED else []
        running_games = running_game_processes() if hard_todos else []
        if hard_todos and (is_game or running_games):
            todo_text = hard_todos[0].get("text", "die ueberfaellige Aufgabe")
            todo_id = str(hard_todos[0].get("id") or "")
            if FOCUS_GUARD_TERMINATE_GAMES:
                if is_game:
                    if not terminate_game_process(proc):
                        terminate_process_by_pid(pid)
                for game_pid, game_name in running_games:
                    terminate_process_by_pid(game_pid)
            if now - last_focus_guard >= FOCUS_GUARD_COOLDOWN_SECONDS:
                ensure_xeon_open(force_window=True)
                notify_xeon(
                    f"Sir, Focus Guard ist aktiv: {todo_text} ist seit mindestens vier Tagen offen. "
                    "Das Spiel wird blockiert, bis Sie die Aufgabe erledigen und mir klar mit Ja oder Erledigt bestaetigen.",
                    todo_id=todo_id,
                    source="focus_guard",
                )
                last_focus_guard = now
            current_game_started = None
            time.sleep(FOCUS_GUARD_CHECK_SECONDS)
            continue

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

        time.sleep(FOCUS_GUARD_CHECK_SECONDS if hard_todos else CHECK_SECONDS)


if __name__ == "__main__":
    main()
