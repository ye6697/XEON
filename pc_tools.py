import json
import os
import re
import shutil
import subprocess
import time
from difflib import SequenceMatcher
from pathlib import Path

try:
    import pyautogui
except ImportError:  # pragma: no cover - handled at runtime
    pyautogui = None

try:
    import pyperclip
except ImportError:  # pragma: no cover - optional clipboard typing fallback
    pyperclip = None


TEXT_EXTENSIONS = {
    ".txt", ".md", ".json", ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".js",
    ".ts", ".tsx", ".jsx", ".py", ".ps1", ".bat", ".cmd", ".yaml", ".yml", ".toml",
    ".ini", ".log", ".env", ".sql",
}

FOLDER_ALIASES = {
    "desktop": Path.home() / "Desktop",
    "schreibtisch": Path.home() / "Desktop",
    "downloads": Path.home() / "Downloads",
    "download": Path.home() / "Downloads",
    "dokumente": Path.home() / "Documents",
    "documents": Path.home() / "Documents",
    "bilder": Path.home() / "Pictures",
    "pictures": Path.home() / "Pictures",
    "videos": Path.home() / "Videos",
    "musik": Path.home() / "Music",
    "music": Path.home() / "Music",
    "home": Path.home(),
    "benutzerordner": Path.home(),
}

APP_ALIASES = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "notepad": "notepad.exe",
    "editor": "notepad.exe",
    "rechner": "calc.exe",
    "calculator": "calc.exe",
    "explorer": "explorer.exe",
    "datei explorer": "explorer.exe",
    "dateiexplorer": "explorer.exe",
    "powershell": "powershell.exe",
    "cmd": "cmd.exe",
    "terminal": "wt.exe",
    "task manager": "taskmgr.exe",
    "taskmanager": "taskmgr.exe",
    "vscode": "code",
    "visual studio code": "code",
    "code": "code",
    "word": "winword.exe",
    "excel": "excel.exe",
    "outlook": "outlook.exe",
    "teams": "ms-teams.exe",
    "spotify": "spotify.exe",
}

WINDOWS_APP_PATHS = {
    "chrome.exe": [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ],
    "msedge.exe": [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ],
}

SITE_ALIASES = {
    "indeed": "https://de.indeed.com",
    "mysuppliex": "https://mysuppliex.app",
    "mysuppliex app": "https://mysuppliex.app",
    "base44": "https://app.base44.com",
    "google kalender": "https://calendar.google.com",
    "calendar": "https://calendar.google.com",
    "gmail": "https://mail.google.com",
    "google mail": "https://mail.google.com",
    "chatgpt": "https://chatgpt.com",
    "codex": "https://chatgpt.com/codex",
}

START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path.home() / "Desktop",
]

if pyautogui:
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.08

DESKTOP_CONTROL_OPERATIONS = {
    "screenshot", "move", "click", "double_click", "right_click", "drag",
    "scroll", "press", "hotkey", "type", "paste", "wait", "sequence",
}


BLOCKED_SYSTEM_COMMAND_PATTERNS = [
    r"\bshutdown(?:\.exe)?\b",
    r"\bstop-computer\b",
    r"\brestart-computer\b",
    r"\bshutdown\s*/[srg]\b",
    r"\bshutdown\s+-[srg]\b",
    r"\bpoweroff\b",
    r"\breboot\b",
    r"\btaskkill\b.*\b(?:explorer|winlogon|csrss|lsass)\b",
]


def is_blocked_system_command(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in BLOCKED_SYSTEM_COMMAND_PATTERNS)


def _sequence_contains_blocked_system_command(steps: list) -> bool:
    opened_run_dialog = False
    typed_after_run = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        operation = str(step.get("operation", "")).lower()
        if operation == "hotkey":
            keys = step.get("keys", [])
            if isinstance(keys, str):
                keys = re.split(r"[,+\s]+", keys)
            normalized_keys = {_normalize_key(str(key)) for key in keys if str(key).strip()}
            if {"win", "r"}.issubset(normalized_keys):
                opened_run_dialog = True
                typed_after_run = False
        if operation in {"type", "paste", "write", "append", "replace", "open"}:
            values = [
                step.get("text", ""),
                step.get("content", ""),
                step.get("target", ""),
                step.get("path", ""),
                step.get("old", ""),
                step.get("new", ""),
            ]
            if any(is_blocked_system_command(str(value)) for value in values):
                return True
            if opened_run_dialog and any(str(value).strip() for value in values):
                typed_after_run = True
        if operation == "press" and opened_run_dialog and not typed_after_run:
            key = _normalize_key(str(step.get("key", "")))
            if key == "enter":
                return True
        if operation == "sequence" and _sequence_contains_blocked_system_command(step.get("steps", [])):
            return True
    return False


def _strip_quotes(value: str) -> str:
    return value.strip().strip('"').strip("'").strip()


def normalize_query(value: str) -> str:
    value = value.lower().strip()
    value = (
        value.replace("\u00e4", "ae")
        .replace("\u00f6", "oe")
        .replace("\u00fc", "ue")
        .replace("\u00df", "ss")
    )
    replacements = {
        "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
        "Ã¤": "ae", "Ã¶": "oe", "Ã¼": "ue", "ÃŸ": "ss",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _score(query: str, candidate: str) -> float:
    q = normalize_query(query)
    c = normalize_query(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.88
    return SequenceMatcher(None, q, c).ratio()


def _iter_start_menu_shortcuts() -> list[Path]:
    shortcuts = []
    for root in START_MENU_DIRS:
        if not root.exists():
            continue
        try:
            shortcuts.extend(root.rglob("*.lnk"))
            shortcuts.extend(root.rglob("*.url"))
        except OSError:
            continue
    return shortcuts


def find_best_local_target(query: str) -> Path | str | None:
    candidates: list[tuple[float, Path | str, str]] = []
    for name, value in APP_ALIASES.items():
        candidates.append((_score(query, name), value, name))
    for name, value in SITE_ALIASES.items():
        candidates.append((_score(query, name), value, name))
    for name, value in FOLDER_ALIASES.items():
        candidates.append((_score(query, name), value, name))

    for shortcut in _iter_start_menu_shortcuts():
        candidates.append((_score(query, shortcut.stem), shortcut, shortcut.stem))

    for folder in FOLDER_ALIASES.values():
        if not folder.exists() or not folder.is_dir():
            continue
        try:
            for item in folder.iterdir():
                candidates.append((_score(query, item.name), item, item.name))
        except OSError:
            continue

    best = max(candidates, key=lambda item: item[0], default=(0.0, None, ""))
    return best[1] if best[0] >= 0.62 else None


def resolve_target(raw: str) -> Path | str:
    target = _strip_quotes(raw)
    lowered = normalize_query(target)

    if lowered in FOLDER_ALIASES:
        return FOLDER_ALIASES[lowered]
    if lowered in APP_ALIASES:
        return APP_ALIASES[lowered]
    if lowered in SITE_ALIASES:
        return SITE_ALIASES[lowered]

    executable = shutil.which(target)
    if executable:
        return executable

    expanded = os.path.expandvars(os.path.expanduser(target))
    path = Path(expanded)
    if path.exists():
        return path

    if not path.is_absolute() and len(target) <= 100:
        for folder in FOLDER_ALIASES.values():
            candidate = folder / target
            if candidate.exists():
                return candidate
        fuzzy = find_best_local_target(target)
        if fuzzy:
            return fuzzy
    return path


def _resolve_windows_app_path(command: str) -> Path | None:
    command_name = Path(command).name.lower()
    candidates = WINDOWS_APP_PATHS.get(command_name, [])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    executable = shutil.which(command)
    return Path(executable) if executable else None


def _shell_start(target: str) -> None:
    subprocess.Popen(
        ["cmd.exe", "/c", "start", "", target],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def open_target(raw: str) -> str:
    if is_blocked_system_command(raw):
        return "Blockiert: systemkritischer Befehl wird nicht ueber PC-Steuerung geoeffnet oder ausgefuehrt."
    target = resolve_target(raw)
    if isinstance(target, str):
        if target.startswith(("http://", "https://")):
            _shell_start(target)
            return f"Website geoeffnet: {target}"

        app_path = _resolve_windows_app_path(target)
        if app_path:
            subprocess.Popen([str(app_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Programm geoeffnet: {raw}"

        try:
            subprocess.Popen([target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            _shell_start(target)
        return f"Programm geoeffnet: {raw}"

    if target.exists():
        os.startfile(str(target))
        return f"Geoeffnet: {target}"

    if re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.IGNORECASE) or re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", raw, re.IGNORECASE):
        _shell_start(raw)
        return f"Website geoeffnet: {raw}"

    return f"Ziel nicht sicher gefunden: {raw}. Sagen Sie den App-Namen, Ordnernamen oder Pfad genauer, Sir."


def list_directory(raw: str, limit: int = 80) -> str:
    target = resolve_target(raw)
    if isinstance(target, str):
        return "Das ist ein Programm oder eine Website, kein Ordner."
    if not target.exists():
        return f"Ordner nicht gefunden: {target}"
    if not target.is_dir():
        return f"Das ist kein Ordner: {target}"

    entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:limit]
    lines = []
    for item in entries:
        kind = "Ordner" if item.is_dir() else "Datei"
        lines.append(f"- {kind}: {item.name}")
    if not lines:
        return f"Der Ordner ist leer: {target}"
    return f"Inhalt von {target}:\n" + "\n".join(lines)


def read_text_file(raw: str, max_chars: int = 12000) -> str:
    target = resolve_target(raw)
    if isinstance(target, str):
        return "Das ist ein Programm oder eine Website, keine Datei."
    if not target.exists():
        return f"Datei nicht gefunden: {target}"
    if not target.is_file():
        return f"Das ist keine Datei: {target}"
    if target.suffix.lower() not in TEXT_EXTENSIONS:
        return f"Ich lese aktuell nur Textdateien direkt. Dateityp: {target.suffix or 'ohne Erweiterung'}"
    if target.stat().st_size > 2_000_000:
        return "Die Datei ist zu gross fuer eine direkte Sprach-/Chat-Ausgabe."

    content = target.read_text(encoding="utf-8", errors="replace")
    if len(content) > max_chars:
        return f"{content[:max_chars]}\n\n[gekuerzt: {len(content)} Zeichen insgesamt]"
    return content


def _backup_file(path: Path) -> Path:
    backup = path.with_name(f"{path.name}.xeonbak-{time.time_ns()}")
    shutil.copy2(path, backup)
    return backup


def write_text_file(raw_path: str, content: str, append: bool = False) -> str:
    target = resolve_target(raw_path)
    if isinstance(target, str):
        return "Das Ziel ist ein Programm oder eine Website, keine Datei."
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists() and target.is_file():
        backup = _backup_file(target)

    mode = "a" if append else "w"
    prefix = "\n" if append and target.exists() and target.stat().st_size > 0 else ""
    with open(target, mode, encoding="utf-8") as f:
        f.write(prefix + content)

    if backup:
        return f"Datei {'ergaenzt' if append else 'geschrieben'}: {target}. Backup: {backup}"
    return f"Datei {'ergaenzt' if append else 'erstellt'}: {target}"


def replace_in_file(raw_path: str, old: str, new: str) -> str:
    target = resolve_target(raw_path)
    if isinstance(target, str):
        return "Das Ziel ist ein Programm oder eine Website, keine Datei."
    if not target.exists() or not target.is_file():
        return f"Datei nicht gefunden: {target}"
    if target.suffix.lower() not in TEXT_EXTENSIONS:
        return f"Ich bearbeite aktuell nur Textdateien direkt. Dateityp: {target.suffix or 'ohne Erweiterung'}"

    content = target.read_text(encoding="utf-8", errors="replace")
    if old not in content:
        return "Der zu ersetzende Text wurde in der Datei nicht gefunden."
    backup = _backup_file(target)
    updated = content.replace(old, new)
    target.write_text(updated, encoding="utf-8")
    count = content.count(old)
    return f"Ersetzt: {count} Treffer in {target}. Backup: {backup}"


def _require_desktop_control():
    if not pyautogui:
        raise RuntimeError("Desktop-Steuerung fehlt. Installiere: pip install pyautogui pyperclip")
    return pyautogui


def _screen_size() -> tuple[int, int]:
    pg = _require_desktop_control()
    size = pg.size()
    return int(size.width), int(size.height)


def _coerce_xy(data: dict) -> tuple[int | None, int | None]:
    width, height = _screen_size()
    if "x" in data and "y" in data:
        return int(data["x"]), int(data["y"])
    if "percent_x" in data and "percent_y" in data:
        return round(width * float(data["percent_x"]) / 100), round(height * float(data["percent_y"]) / 100)
    if "px" in data and "py" in data:
        return round(width * float(data["px"]) / 100), round(height * float(data["py"]) / 100)
    return None, None


def _normalize_key(key: str) -> str:
    value = normalize_query(str(key))
    aliases = {
        "steuerung": "ctrl",
        "strg": "ctrl",
        "control": "ctrl",
        "cmd": "win",
        "windows": "win",
        "eingabe": "enter",
        "return": "enter",
        "loeschen": "delete",
        "entfernen": "delete",
        "esc": "escape",
        "leertaste": "space",
        "tabulator": "tab",
        "bild runter": "pagedown",
        "bild hoch": "pageup",
        "hoch": "up",
        "runter": "down",
        "links": "left",
        "rechts": "right",
    }
    return aliases.get(value, value.replace(" ", ""))


def take_desktop_screenshot(path: str = "data/desktop-screenshot.png") -> str:
    pg = _require_desktop_control()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image = pg.screenshot()
    image.save(target)
    width, height = _screen_size()
    x, y = pg.position()
    return f"Screenshot gespeichert: {target}. Bildschirm: {width}x{height}. Mausposition: {int(x)},{int(y)}"


def execute_desktop_operation(data: dict) -> str:
    pg = _require_desktop_control()
    operation = str(data.get("operation", "")).lower()

    if operation == "screenshot":
        return take_desktop_screenshot(str(data.get("path") or "data/desktop-screenshot.png"))

    if operation == "wait":
        seconds = max(0.0, min(float(data.get("seconds", 1)), 30.0))
        time.sleep(seconds)
        return f"Gewartet: {seconds:g} Sekunden."

    if operation == "move":
        x, y = _coerce_xy(data)
        if x is None or y is None:
            return "Fuer Mausbewegung brauche ich x/y oder percent_x/percent_y."
        pg.moveTo(x, y, duration=max(0.0, min(float(data.get("duration", 0.15)), 2.0)))
        return f"Maus bewegt: {x},{y}."

    if operation in {"click", "double_click", "right_click"}:
        x, y = _coerce_xy(data)
        button = str(data.get("button", "left")).lower()
        if operation == "right_click":
            button = "right"
        clicks = 2 if operation == "double_click" else int(data.get("clicks", 1))
        clicks = max(1, min(clicks, 5))
        if x is not None and y is not None:
            pg.click(x=x, y=y, clicks=clicks, button=button)
            return f"Geklickt: {x},{y}."
        pg.click(clicks=clicks, button=button)
        return "Geklickt an der aktuellen Mausposition."

    if operation == "drag":
        x, y = _coerce_xy(data)
        if x is None or y is None:
            return "Fuer Ziehen brauche ich Zielkoordinaten x/y oder percent_x/percent_y."
        pg.dragTo(x, y, duration=max(0.05, min(float(data.get("duration", 0.35)), 5.0)), button=str(data.get("button", "left")))
        return f"Maus gezogen nach: {x},{y}."

    if operation == "scroll":
        amount = int(data.get("amount", data.get("clicks", -5)))
        amount = max(-50, min(amount, 50))
        pg.scroll(amount)
        direction = "hoch" if amount > 0 else "runter"
        return f"Gescrollt: {direction}."

    if operation == "press":
        key = _normalize_key(str(data.get("key", "")))
        if not key:
            return "Taste fehlt."
        presses = max(1, min(int(data.get("presses", 1)), 20))
        pg.press(key, presses=presses)
        return f"Taste gedrueckt: {key}."

    if operation == "hotkey":
        keys = data.get("keys", [])
        if isinstance(keys, str):
            keys = re.split(r"[,+\s]+", keys)
        keys = [_normalize_key(key) for key in keys if str(key).strip()]
        if not keys:
            return "Hotkey-Tasten fehlen."
        pg.hotkey(*keys)
        return f"Hotkey gedrueckt: {'+'.join(keys)}."

    if operation in {"type", "paste"}:
        text = str(data.get("text", ""))
        if not text:
            return "Text fehlt."
        if is_blocked_system_command(text):
            return "Blockiert: systemkritischer Befehl wird nicht ueber Tastatur/Clipboard ausgefuehrt."
        if pyperclip:
            pyperclip.copy(text)
            pg.hotkey("ctrl", "v")
        else:
            pg.write(text, interval=max(0.0, min(float(data.get("interval", 0.01)), 0.2)))
        return f"Text eingefuegt: {len(text)} Zeichen."

    if operation == "sequence":
        steps = data.get("steps", [])
        if not isinstance(steps, list):
            return "Sequenz muss eine Liste von Schritten enthalten."
        if _sequence_contains_blocked_system_command(steps):
            return "Blockiert: diese Sequenz enthaelt einen systemkritischen Shutdown-/Restart-Befehl."
        results = []
        for index, step in enumerate(steps[:30], start=1):
            if not isinstance(step, dict):
                results.append(f"{index}: ungueltiger Schritt")
                continue
            results.append(f"{index}: {execute_desktop_operation(step)}")
        return "Sequenz ausgefuehrt:\n" + "\n".join(results)

    return (
        "Unbekannte Desktop-Aktion. Erlaubt sind: screenshot, move, click, double_click, "
        "right_click, drag, scroll, press, hotkey, type, paste, wait, sequence."
    )


def execute_pc_operation(payload: str | dict) -> str:
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            return f"PC-Aktion konnte nicht verstanden werden: {exc}"
    else:
        data = payload

    operation = str(data.get("operation", "")).lower()
    if operation in DESKTOP_CONTROL_OPERATIONS:
        return execute_desktop_operation(data)
    if operation == "open":
        return open_target(str(data.get("target", "")))
    if operation == "list":
        return list_directory(str(data.get("path", "")))
    if operation == "read":
        return read_text_file(str(data.get("path", "")))
    if operation == "write":
        return write_text_file(str(data.get("path", "")), str(data.get("content", "")), append=False)
    if operation == "append":
        return write_text_file(str(data.get("path", "")), str(data.get("content", "")), append=True)
    if operation == "replace":
        return replace_in_file(str(data.get("path", "")), str(data.get("old", "")), str(data.get("new", "")))
    return (
        "Unbekannte PC-Aktion. Erlaubt sind: open, list, read, write, append, replace, "
        "screenshot, move, click, double_click, right_click, drag, scroll, press, hotkey, type, paste, wait, sequence."
    )


def parse_pc_request(text: str) -> dict | None:
    t = text.strip()
    lowered = normalize_query(t)
    if any(term in lowered for term in ["screenshot", "bildschirmfoto", "mach ein bild vom bildschirm"]):
        return {"operation": "screenshot"}

    if lowered in {"klick", "click", "klicken", "mausklick"}:
        return {"operation": "click"}

    match = re.search(r"\b(?:klick|click|klicken)\b.*?\b(?:bei|auf|an)?\s*(\d{1,4})\s*[,x ]\s*(\d{1,4})\b", lowered)
    if match:
        return {"operation": "click", "x": int(match.group(1)), "y": int(match.group(2))}

    if any(term in lowered for term in ["doppelklick", "double click", "doubleclick"]):
        return {"operation": "double_click"}

    if any(term in lowered for term in ["rechtsklick", "rechte maustaste", "right click"]):
        return {"operation": "right_click"}

    if lowered.startswith(("scroll ", "scrolle ", "runter scroll", "hoch scroll")):
        direction_down = any(term in lowered for term in ["runter", "down", "nach unten"])
        amount = -7 if direction_down else 7
        return {"operation": "scroll", "amount": amount}

    match = re.match(r"^(?:drueck|druecke|druck|taste|press)\s+(.+)$", t, re.IGNORECASE)
    if match:
        raw = match.group(1).strip()
        normalized_raw = normalize_query(raw)
        if "+" in raw or " und " in f" {normalized_raw} ":
            keys = re.split(r"\s*(?:\+|und)\s*", raw, flags=re.IGNORECASE)
            return {"operation": "hotkey", "keys": keys}
        return {"operation": "press", "key": normalized_raw}

    match = re.match(r"^(?:hotkey|shortcut)\s+(.+)$", t, re.IGNORECASE)
    if match:
        keys = re.split(r"\s*(?:\+|und|,)\s*", match.group(1).strip(), flags=re.IGNORECASE)
        return {"operation": "hotkey", "keys": keys}

    match = re.match(r"^(?:schreib|schreibe|tippe|tipp|type)\s+(.+)$", t, re.IGNORECASE | re.DOTALL)
    if match and "datei" not in lowered:
        return {"operation": "type", "text": match.group(1).strip()}

    match = re.match(r"^(?:warte|wait)\s+(\d{1,2})", lowered)
    if match:
        return {"operation": "wait", "seconds": int(match.group(1))}

    if lowered.startswith(("oeffne ", "starte ", "open ")):
        parts = t.split(maxsplit=1)
        target = parts[1].strip() if len(parts) > 1 else ""
        target = re.sub(r"^(programm|ordner|datei)\s+", "", target, flags=re.IGNORECASE).strip()
        return {"operation": "open", "target": target}

    if lowered.startswith(("mach ", "ruf ", "geh ")) and re.search(r"\b(auf|zu)\b", lowered):
        target = re.sub(r"^(mach|ruf|geh)\s+", "", t, flags=re.IGNORECASE).strip()
        target = re.sub(r"\b(auf|zu)\b", "", target, flags=re.IGNORECASE).strip()
        return {"operation": "open", "target": target}

    if lowered.startswith(("oeffne ", "starte ", "open ")):
        target = re.sub(r"^(oeffne|öffne|starte|open)\s+(programm|ordner|datei)?\s*", "", t, flags=re.IGNORECASE).strip()
        return {"operation": "open", "target": target}

    if lowered.startswith(("liste ", "zeige ordner ", "zeig ordner ", "inhalt von ")):
        path = re.sub(r"^(liste|zeige|zeig)\s+(ordner|inhalt von)?\s*", "", t, flags=re.IGNORECASE).strip()
        path = re.sub(r"^inhalt von\s+", "", path, flags=re.IGNORECASE).strip()
        return {"operation": "list", "path": path}

    if lowered.startswith(("lies datei ", "lese datei ", "lies mir datei ", "zeige datei ")):
        path = re.sub(r"^(lies|lese|zeige)\s+(mir\s+)?datei\s*", "", t, flags=re.IGNORECASE).strip()
        return {"operation": "read", "path": path}

    match = re.match(r"^(?:fuege|füge)\s+(?:zu\s+)?datei\s+(.+?)\s+(?:hinzu|an):\s*(.+)$", t, re.IGNORECASE | re.DOTALL)
    if match:
        return {"operation": "append", "path": _strip_quotes(match.group(1)), "content": match.group(2).strip()}

    match = re.match(r"^(?:schreibe|erstelle)\s+datei\s+(.+?):\s*(.+)$", t, re.IGNORECASE | re.DOTALL)
    if match:
        return {"operation": "write", "path": _strip_quotes(match.group(1)), "content": match.group(2).strip()}

    match = re.match(r"^ersetze\s+(?:in\s+)?datei\s+(.+?)\s+['\"](.+?)['\"]\s+durch\s+['\"](.+?)['\"]$", t, re.IGNORECASE | re.DOTALL)
    if match:
        return {"operation": "replace", "path": _strip_quotes(match.group(1)), "old": match.group(2), "new": match.group(3)}

    return None


def pc_context(limit: int = 80) -> str:
    items = []
    for name in sorted(set(APP_ALIASES) | set(SITE_ALIASES) | set(FOLDER_ALIASES)):
        items.append(name)
    for shortcut in _iter_start_menu_shortcuts()[:120]:
        items.append(shortcut.stem)
    desktop = ""
    if pyautogui:
        try:
            width, height = _screen_size()
            x, y = pyautogui.position()
            desktop = f" Desktop-Control aktiv, Bildschirm {width}x{height}, Maus {int(x)},{int(y)}."
        except Exception:
            desktop = " Desktop-Control installiert, Bildschirmstatus unbekannt."
    else:
        desktop = " Desktop-Control nicht installiert."
    return ", ".join(items[:limit]) + "." + desktop
