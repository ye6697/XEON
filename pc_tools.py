import json
import os
import re
import shutil
import subprocess
import time
from difflib import SequenceMatcher
from pathlib import Path


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


def open_target(raw: str) -> str:
    target = resolve_target(raw)
    if isinstance(target, str):
        if target.startswith(("http://", "https://")):
            subprocess.Popen(["cmd.exe", "/c", "start", "", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Website geoeffnet: {target}"
        subprocess.Popen([target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Programm geoeffnet: {raw}"

    if target.exists():
        os.startfile(str(target))
        return f"Geoeffnet: {target}"

    if re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.IGNORECASE) or re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", raw, re.IGNORECASE):
        subprocess.Popen(["cmd.exe", "/c", "start", "", raw], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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


def execute_pc_operation(payload: str | dict) -> str:
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            return f"PC-Aktion konnte nicht verstanden werden: {exc}"
    else:
        data = payload

    operation = str(data.get("operation", "")).lower()
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
    return "Unbekannte PC-Aktion. Erlaubt sind: open, list, read, write, append, replace."


def parse_pc_request(text: str) -> dict | None:
    t = text.strip()
    lowered = normalize_query(t)
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
    return ", ".join(items[:limit])
