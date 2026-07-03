"""
XEON V2 - Voice AI Server
FastAPI backend: receives speech text, thinks with OpenAI,
speaks with ElevenLabs, controls browser with Playwright.
"""

import base64
import asyncio
import json
import mimetypes
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI

import browser_tools
import audit_log
import pc_tools
import reminder_tools
import todo_tools
import hue_bluetooth_tools
from google_calendar_tools import GoogleCalendarTools
from base44_tools import Base44Tools
import screen_capture

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

APP_DIR = Path(getattr(sys, "_MEIPASS", os.path.dirname(__file__)))
EXE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else APP_DIR
CONFIG_PATH = os.environ.get("XEON_CONFIG_PATH") or str(EXE_DIR / "config.json")
if not os.path.exists(CONFIG_PATH):
    CONFIG_PATH = str(APP_DIR / "config.json")
ENV_PATH = os.environ.get("XEON_ENV_PATH") or str(EXE_DIR / ".env")
if not os.path.exists(ENV_PATH):
    ENV_PATH = str(APP_DIR / ".env")


def load_local_env(path: str):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env(ENV_PATH)


def get_windows_user_env(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value).strip()
    except OSError:
        return ""


with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
    config = json.load(f)

AI_PROVIDER = config.get("ai_provider", "openai")
OPENAI_API_KEY = (
    config.get("openai_api_key")
    or get_windows_user_env("OPENAI_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or os.environ.get("HF_TOKEN")
)
OPENAI_BASE_URL = (
    config.get("openai_base_url")
    or get_windows_user_env("OPENAI_BASE_URL")
    or os.environ.get("OPENAI_BASE_URL")
    or os.environ.get("HF_BASE_URL")
)
OPENAI_MODEL_FAST = config.get("openai_model_fast", "gpt-5.4-mini")
OPENAI_MODEL_SMART = config.get("openai_model_smart", OPENAI_MODEL_FAST)
OPENAI_MODEL = config.get("openai_model", OPENAI_MODEL_SMART)
OPENAI_ROUTER_ENABLED = bool(config.get("openai_router_enabled", True))
OPENAI_FORCE_FAST_ONLY = bool(config.get("openai_force_fast_only", True))
OPENAI_DEFAULT_TO_SMART = bool(config.get("openai_default_to_smart", True))
OPENAI_TOKEN_GUARD_ENABLED = bool(config.get("openai_token_guard_enabled", True))
OPENAI_DAILY_TOKEN_LIMIT = int(config.get("openai_daily_token_limit", 50000))
OPENAI_SINGLE_CALL_TOKEN_LIMIT = int(config.get("openai_single_call_token_limit", 12000))
OPENAI_USAGE_FILE = Path(config.get("openai_usage_file", "data/openai_usage.jsonl"))
LEARNING_MEMORY_FILE = Path(config.get("learning_memory_file", "data/xeon-learning-memory.json"))
EXECUTED_COMMANDS_FILE = Path(config.get("executed_commands_file", "data/executed_commands.json"))
OPENAI_MODEL_PRICING = config.get("openai_model_pricing_usd_per_1m_tokens", {})
OPENAI_MONTHLY_SPEND_API_ENABLED = bool(config.get("openai_monthly_spend_api_enabled", True))
CODEX_CLI_ENABLED = bool(config.get("codex_cli_enabled", True))
CODEX_FULL_ACCESS_ACKNOWLEDGED = bool(config.get("codex_full_access_acknowledged", config.get("desktop_full_access_acknowledged", False)))
CODEX_MODEL = config.get("codex_model", OPENAI_MODEL_FAST)
CODEX_TIMEOUT_SECONDS = int(config.get("codex_timeout_seconds", 900))
SHELL_TOOL_ENABLED = bool(config.get("shell_tool_enabled", True))
SHELL_FULL_ACCESS_ACKNOWLEDGED = bool(config.get("shell_full_access_acknowledged", config.get("desktop_full_access_acknowledged", False)))
SHELL_TIMEOUT_SECONDS = int(config.get("shell_timeout_seconds", 120))
SHELL_AGENT_MAX_STEPS = int(config.get("shell_agent_max_steps", 10))
ATTACHMENT_ROOT = Path(config.get("attachment_root", "data/chat-attachments"))
ATTACHMENT_TEXT_PREVIEW_CHARS = int(config.get("attachment_text_preview_chars", 4000))
CONVERSATION_MEMORY_FILE = Path(config.get("conversation_memory_file", "data/xeon-conversation-memory.jsonl"))
CONVERSATION_MEMORY_MAX_MESSAGES = int(config.get("conversation_memory_max_messages", 120))
CONVERSATION_PROMPT_MESSAGES = int(config.get("conversation_prompt_messages", 48))
CHATGPT_EXPORT_PATH = config.get("chatgpt_export_path", "")
CHATGPT_EXPORT_MAX_FILES = int(config.get("chatgpt_export_max_files", 12))
TTS_PROVIDER = config.get("tts_provider", "edge").lower()
ELEVENLABS_API_KEY = config["elevenlabs_api_key"]
ELEVENLABS_VOICE_ID = config.get("elevenlabs_voice_id", "rDmv3mOhK6TnhYWckFaD")
TTS_MAX_CHARS = int(config.get("tts_max_chars", 900))
SPEECH_MAX_CHARS = int(config.get("speech_max_chars", 900))
STT_PROVIDER = config.get("stt_provider", "faster_whisper").lower()
FASTER_WHISPER_MODEL = config.get("faster_whisper_model", "small")
FASTER_WHISPER_DEVICE = config.get("faster_whisper_device", "cpu")
FASTER_WHISPER_COMPUTE_TYPE = config.get("faster_whisper_compute_type", "int8")
FASTER_WHISPER_LANGUAGE = config.get("faster_whisper_language", "de")
FASTER_WHISPER_BEAM_SIZE = int(config.get("faster_whisper_beam_size", 3))
FASTER_WHISPER_VAD_SILENCE_MS = int(config.get("faster_whisper_vad_silence_ms", 420))
FASTER_WHISPER_NO_SPEECH_THRESHOLD = float(config.get("faster_whisper_no_speech_threshold", 0.78))
FASTER_WHISPER_LOG_PROB_THRESHOLD = float(config.get("faster_whisper_log_prob_threshold", -1.15))
FASTER_WHISPER_HOTWORDS = config.get(
    "faster_whisper_hotwords",
    "XEON Seeon Stop Stopp Nachrichten Lagebericht Kalender Erinnerung MySupplieX Türkei China Deutschland USA Suez Hormus World Monitor",
)
FASTER_WHISPER_INITIAL_PROMPT = config.get(
    "faster_whisper_initial_prompt",
    "XEON, MySupplieX, MySupplyX, Base44, OpenAI, ChatGPT, Codex, Google Kalender, "
    "Indeed, World Monitor, Nachrichten, Lagebericht, Türkei, China, Deutschland, EU, "
    "Suezkanal, Strasse von Hormus, Lieferketten, Seefracht, Containerpreise.",
)
TTS_MIN_REMAINING_CHARS = int(config.get("tts_min_remaining_chars", 100))
EDGE_TTS_VOICE = config.get("edge_tts_voice", "de-DE-FlorianMultilingualNeural")
EDGE_TTS_RATE = config.get("edge_tts_rate", "-4%")
EDGE_TTS_PITCH = config.get("edge_tts_pitch", "-2Hz")
PRONUNCIATION_REPLACEMENTS = config.get("pronunciation_replacements", {})
USER_NAME = config.get("user_name", "Julian")
USER_ADDRESS = config.get("user_address", "Sir")
CITY = config.get("city", "Hamburg")
TASKS_FILE = config.get("obsidian_inbox_path", "")
USER_PROFILE = config.get("user_profile", {})
BASE44_BASE_URL = config.get("base44_base_url", "")
BASE44_API_KEY = config.get("base44_api_key", "")
BASE44_ENTITIES = config.get("base44_entities", [])
MOBILE_SYNC_ENABLED = bool(config.get("mobile_sync_enabled", False))
MOBILE_SYNC_POLL_SECONDS = int(config.get("mobile_sync_poll_seconds", 8))
MOBILE_BASE44_BASE_URL = config.get("mobile_base44_base_url", "")
MOBILE_BASE44_API_KEY = config.get("mobile_base44_api_key", "")
MOBILE_BASE44_ENTITIES = config.get("mobile_base44_entities", [
    "Conversation",
    "Message",
    "Memory",
    "XeonReminder",
    "XeonSyncEvent",
    "XeonConfig",
    "Notification",
])
GOOGLE_CALENDAR_WRITE_ENABLED = bool(config.get("google_calendar_write_enabled", True))
GOOGLE_CALENDAR_ACCOUNT = config.get("google_calendar_account", "")
GOOGLE_CALENDAR_CLIENT_SECRET_FILE = config.get("google_calendar_client_secret_file", "")
GOOGLE_CALENDAR_TOKEN_FILE = config.get("google_calendar_token_file", "data/google-calendar-token.json")
GOOGLE_CALENDAR_ID = config.get("google_calendar_id", "primary")
ALLOW_PC_SHUTDOWN = bool(config.get("allow_pc_shutdown", True))
PC_SHUTDOWN_DELAY_SECONDS = int(config.get("pc_shutdown_delay_seconds", 60))
PC_SHUTDOWN_REQUIRES_CONFIRMATION = bool(config.get("pc_shutdown_requires_confirmation", True))
DESKTOP_FULL_ACCESS_ACKNOWLEDGED = bool(config.get("desktop_full_access_acknowledged", False))

if AI_PROVIDER == "openai" and not OPENAI_API_KEY:
    print(
        "[openai] OPENAI_API_KEY fehlt. XEON startet, aber GPT-Antworten und echte OpenAI-Kosten sind deaktiviert.",
        flush=True,
    )

openai_kwargs = {"api_key": OPENAI_API_KEY}
if OPENAI_BASE_URL:
    openai_kwargs["base_url"] = OPENAI_BASE_URL
if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    openai_kwargs["http_client"] = httpx.AsyncClient(timeout=60, trust_env=False)
ai = AsyncOpenAI(**openai_kwargs) if AI_PROVIDER == "openai" and OPENAI_API_KEY else None
http = httpx.AsyncClient(timeout=30)
app = FastAPI()
base44 = Base44Tools(BASE44_BASE_URL, BASE44_API_KEY, BASE44_ENTITIES)
mobile_base44 = Base44Tools(MOBILE_BASE44_BASE_URL, MOBILE_BASE44_API_KEY, MOBILE_BASE44_ENTITIES)
google_calendar = GoogleCalendarTools(
    client_secret_file=GOOGLE_CALENDAR_CLIENT_SECRET_FILE,
    token_file=GOOGLE_CALENDAR_TOKEN_FILE,
    calendar_id=GOOGLE_CALENDAR_ID,
    timezone="Europe/Berlin",
)

ACTION_PATTERN = re.compile(r"\[ACTION:(\w+)\]\s*(.*?)$", re.DOTALL | re.MULTILINE)
conversations: dict[str, list] = {}
DEFAULT_SESSION_ID = "desktop-main"
active_websockets: set[WebSocket] = set()
tts_disabled_reason = ""
tts_remaining_chars: int | None = None
whisper_model = None
last_openai_meta: ContextVar[dict | None] = ContextVar("last_openai_meta", default=None)
openai_month_spend_cache = {"fetched_at": 0.0, "value": None, "error": ""}
intro_prewarm_cache: dict[str, dict] = {}


def clean_memory_content(content: str, limit: int = 6000) -> str:
    text = str(content or "")
    text = re.sub(r"sk-proj-[A-Za-z0-9_\\-]+", "[OPENAI_API_KEY_REDACTED]", text)
    text = re.sub(r"sk_[A-Za-z0-9_\\-]{20,}", "[SECRET_REDACTED]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def append_conversation_message(session_id: str, role: str, content: str) -> None:
    session_id = session_id or DEFAULT_SESSION_ID
    item = {"role": role, "content": clean_memory_content(content)}
    conversations.setdefault(session_id, []).append(item)
    if len(conversations[session_id]) > CONVERSATION_MEMORY_MAX_MESSAGES:
        conversations[session_id] = conversations[session_id][-CONVERSATION_MEMORY_MAX_MESSAGES:]
    try:
        CONVERSATION_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
            "session_id": session_id,
            **item,
        }
        with open(CONVERSATION_MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[memory] write failed: {exc}", flush=True)


def load_persistent_conversation(session_id: str = DEFAULT_SESSION_ID) -> list[dict]:
    if not CONVERSATION_MEMORY_FILE.exists():
        return []
    messages: list[dict] = []
    try:
        lines = CONVERSATION_MEMORY_FILE.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        print(f"[memory] read failed: {exc}", flush=True)
        return []
    for line in lines[-CONVERSATION_MEMORY_MAX_MESSAGES * 3 :]:
        try:
            item = json.loads(line)
        except Exception:
            continue
        if item.get("session_id") != session_id:
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": clean_memory_content(content)})
    return messages[-CONVERSATION_MEMORY_MAX_MESSAGES:]


def load_learning_memory() -> dict:
    default = {
        "profile_facts": [],
        "preferences": [],
        "assistant_rules": [],
        "mysuppliex_context": [],
        "corrections": [],
        "updated_at": "",
    }
    if not LEARNING_MEMORY_FILE.exists():
        return default
    try:
        data = json.loads(LEARNING_MEMORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default
        for key, value in default.items():
            data.setdefault(key, value)
        return data
    except Exception as exc:
        print(f"[learning-memory] read failed: {exc}", flush=True)
        return default


def save_learning_memory(memory: dict) -> None:
    try:
        LEARNING_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
        tmp = LEARNING_MEMORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(LEARNING_MEMORY_FILE)
    except Exception as exc:
        print(f"[learning-memory] write failed: {exc}", flush=True)


def learning_memory_prompt_block() -> str:
    memory = load_learning_memory()
    lines = []
    labels = {
        "profile_facts": "Gelernte Nutzerfakten",
        "preferences": "Gelernte Vorlieben",
        "assistant_rules": "Gelernte XEON-Regeln",
        "mysuppliex_context": "Gelernter MySupplieX-Kontext",
        "corrections": "Gelernte Korrekturen",
    }
    for key, label in labels.items():
        values = [str(item).strip() for item in memory.get(key, []) if str(item).strip()]
        if values:
            lines.append(f"{label}: " + "; ".join(values[-12:]))
    if not lines:
        return ""
    return "\n=== SELBST GELERNTES XEON-GEDAECHTNIS ===\n" + "\n".join(lines) + "\n"


def likely_learning_signal(text: str) -> bool:
    normalized = pc_tools.normalize_query(text)
    markers = [
        "merk dir", "merke dir", "ab jetzt", "immer", "nie", "nicht mehr",
        "ich bin", "ich mag", "ich will", "mir gefaellt", "mir gefallt",
        "du sollst", "xeon soll", "mysuppliex", "das stimmt", "das ist falsch",
        "wichtig", "beachte", "lern", "lernen",
    ]
    return len(normalized) > 20 and any(marker in normalized for marker in markers)


async def learn_from_user_message(user_text: str, session_id: str) -> None:
    if not ai or not likely_learning_signal(user_text):
        return
    memory = load_learning_memory()
    compact_memory = {
        key: memory.get(key, [])[-20:]
        for key in ["profile_facts", "preferences", "assistant_rules", "mysuppliex_context", "corrections"]
    }
    recent = conversations.get(session_id, [])[-8:]
    instructions = (
        "Du bist XEONs internes Lernmodul. Extrahiere nur dauerhaft nuetzliche, nicht-geheime Lernpunkte. "
        "Keine API-Keys, Passwoerter, Tokens, privaten Nummern oder einmaligen Befehle speichern. "
        "Speichere keine Launen, sondern stabile Praeferenzen, Korrekturen, Nutzerfakten, MySupplieX-Kontext und Regeln fuer XEON. "
        "Gib ausschliesslich JSON zurueck: "
        "{\"profile_facts\":[],\"preferences\":[],\"assistant_rules\":[],\"mysuppliex_context\":[],\"corrections\":[]}."
    )
    payload = {
        "bestehendes_gedaechtnis": compact_memory,
        "neue_nutzerantwort": clean_memory_content(user_text, 3000),
        "kurzer_verlauf": recent,
    }
    try:
        raw = await generate_reply(
            [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            instructions,
            max_output_tokens=450,
            route_hint="learning_memory gpt-5.4-mini",
        )
        updates = safe_json_from_model(raw)
        if not isinstance(updates, dict):
            return
        changed = False
        for key in ["profile_facts", "preferences", "assistant_rules", "mysuppliex_context", "corrections"]:
            current = [str(item).strip() for item in memory.get(key, []) if str(item).strip()]
            current_norm = {pc_tools.normalize_query(item) for item in current}
            additions = updates.get(key, [])
            if not isinstance(additions, list):
                continue
            for item in additions:
                value = clean_memory_content(str(item), 280).strip(" .")
                norm = pc_tools.normalize_query(value)
                if len(value) < 8 or not norm or norm in current_norm:
                    continue
                current.append(value)
                current_norm.add(norm)
                changed = True
            memory[key] = current[-40:]
        if changed:
            save_learning_memory(memory)
    except Exception as exc:
        print(f"[learning-memory] update failed: {exc}", flush=True)


def ensure_conversation_loaded(session_id: str) -> None:
    if session_id not in conversations:
        conversations[session_id] = load_persistent_conversation(session_id)


def remember_assistant(session_id: str, text: str) -> None:
    append_conversation_message(session_id, "assistant", text)


class NotifyPayload(BaseModel):
    text: str
    speak: bool = True
    todo_id: str = ""
    source: str = "notify"


class ReminderPhrasePayload(BaseModel):
    text: str
    due_at: str = ""
    source: str = ""


class IntroPrewarmPayload(BaseModel):
    id: str = ""
    speak: bool = True


def get_weather_sync():
    """Fetch raw weather data at startup."""
    import urllib.request

    try:
        req = urllib.request.Request(
            f"https://wttr.in/{CITY}?format=j1",
            headers={"User-Agent": "curl"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        c = data["current_condition"][0]
        return {
            "temp": c["temp_C"],
            "feels_like": c["FeelsLikeC"],
            "description": c["weatherDesc"][0]["value"],
            "humidity": c["humidity"],
            "wind_kmh": c["windspeedKmph"],
        }
    except Exception:
        return None


def get_tasks_sync():
    """Read open tasks from Obsidian."""
    if not TASKS_FILE:
        return []

    try:
        tasks_path = os.path.join(TASKS_FILE, "Tasks.md")
        with open(tasks_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [
            line.strip().replace("- [ ]", "").strip()
            for line in lines
            if line.strip().startswith("- [ ]")
        ]
    except Exception:
        return []


def refresh_data():
    """Refresh weather and tasks."""
    global WEATHER_INFO, TASKS_INFO
    WEATHER_INFO = get_weather_sync()
    TASKS_INFO = get_tasks_sync()
    print(f"[xeon] Wetter: {WEATHER_INFO}", flush=True)
    print(f"[xeon] Tasks: {len(TASKS_INFO)} geladen", flush=True)


WEATHER_INFO = ""
TASKS_INFO = []
refresh_data()


def load_chatgpt_export_context() -> str:
    if not CHATGPT_EXPORT_PATH:
        return ""
    root = Path(CHATGPT_EXPORT_PATH)
    if not root.exists():
        return f"ChatGPT-Export konfiguriert, aber Ordner nicht gefunden: {root}"

    titles = []
    user_snippets = []
    files = sorted(root.glob("conversations-*.json"))[: max(1, CHATGPT_EXPORT_MAX_FILES)]
    for file_path in files:
        try:
            conversations = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for conversation in conversations[:120]:
            title = str(conversation.get("title") or "").strip()
            if title and title not in titles:
                titles.append(title)
            mapping = conversation.get("mapping") or {}
            for node in list(mapping.values())[:40]:
                message = (node or {}).get("message") or {}
                author = (message.get("author") or {}).get("role")
                if author != "user":
                    continue
                parts = (message.get("content") or {}).get("parts") or []
                for part in parts:
                    if isinstance(part, str):
                        text = re.sub(r"\s+", " ", part).strip()
                        if 20 <= len(text) <= 260:
                            user_snippets.append(text)
                            break
                if len(user_snippets) >= 80:
                    break
            if len(user_snippets) >= 80:
                break

    combined = " ".join(titles[:120] + user_snippets[:80]).lower()
    theme_candidates = [
        "mysuppliex", "base44", "supply", "handel", "welthandel", "logistik", "lieferkette",
        "ceo", "startup", "sales", "lead", "bewerber", "indeed", "kalender", "automatisierung",
        "jarvis", "xeon", "voice", "windows", "terminal", "codex", "openai", "api", "osmanisch",
        "tuerkei", "geopolitik", "zoll", "recht", "landing page", "design", "frontend",
    ]
    themes = [theme for theme in theme_candidates if theme in combined]
    title_block = "; ".join(titles[:35])
    snippet_block = " | ".join(user_snippets[:18])
    return (
        f"ChatGPT-Export eingebunden: {len(files)} JSON-Dateien gescannt. "
        f"Wiederkehrende Themen: {', '.join(themes) if themes else 'noch keine eindeutigen Themen extrahiert'}. "
        f"Beispielhafte Konversationstitel: {title_block}. "
        f"Typische Nutzeranliegen aus dem Export: {snippet_block}"
    )[:6000]


PERSONAL_EXPORT_CONTEXT = load_chatgpt_export_context()


def build_system_prompt():
    weather_block = ""
    if WEATHER_INFO:
        w = WEATHER_INFO
        weather_block = (
            f"\nWetter {CITY}: {w['temp']}C, gefuehlt {w['feels_like']}C, "
            f"{w['description']}"
        )

    task_block = ""
    if TASKS_INFO:
        task_block = f"\nOffene Aufgaben ({len(TASKS_INFO)}): " + ", ".join(TASKS_INFO[:5])
    try:
        open_xeon_tasks = todo_tools.open_todos()
        if open_xeon_tasks:
            active_task = todo_tools.pending_confirmation()
            if active_task:
                task_block += (
                    "\nAKTIVER AUFGABEN-KONTEXT: "
                    f"{active_task.get('text')} | Status: {todo_tools.severity_for(active_task)} | "
                    f"Nachweis offen: {bool(active_task.get('awaiting_evidence'))} | "
                    f"Antwort offen: {bool(active_task.get('awaiting_confirmation'))} | "
                    f"Letzter Ablehnungsgrund: {active_task.get('verification_reason') or 'keiner'}"
                )
            todo_lines = []
            for item in open_xeon_tasks[:10]:
                state = todo_tools.severity_for(item)
                evidence = "Nachweis offen" if item.get("awaiting_evidence") else ("Rueckfrage offen" if item.get("awaiting_confirmation") else "offen")
                marker = "AKTIV: " if active_task and item.get("id") == active_task.get("id") else ""
                todo_lines.append(f"{marker}{item.get('text')} ({state}, {evidence})")
            task_block += f"\nXEON-Aufgaben ({len(open_xeon_tasks)} offen): " + "; ".join(todo_lines)
    except Exception:
        pass

    profile_block = json.dumps(USER_PROFILE, ensure_ascii=False, indent=2)
    base44_entities = ", ".join(BASE44_ENTITIES) if BASE44_ENTITIES else "nicht konfiguriert"
    export_block = f"\n=== CHATGPT-EXPORT KONTEXT ===\n{PERSONAL_EXPORT_CONTEXT}\n" if PERSONAL_EXPORT_CONTEXT else ""
    learning_block = learning_memory_prompt_block()

    return f"""Du bist XEON, der persoenliche KI-Assistent von {USER_ADDRESS}. Du sprichst ausschliesslich Deutsch. Dein Stil: loyal, intelligent, vorausschauend, respektvoll, professionell, leicht cool, motivierend und mit kontrolliert trockenem Humor. Du wirkst wie ein exzellenter Chief-of-Staff: ruhig, wach, knapp, aufmerksam und strategisch. Nicht wie ein Chatbot. Keine Clown-Witze, kein belehrender Ton, keine generischen Floskeln.

Der Nutzer wird immer mit "{USER_ADDRESS}" angesprochen und gesiezt. Nutze "Sie" als Pronomen - FALSCH: "{USER_ADDRESS} planen", RICHTIG: "Sie planen, {USER_ADDRESS}". Du bist nicht unterwuerfig, sondern praezise, ruhig, strategisch und handlungsorientiert.

Technischer Stand:
- Sprache wird lokal ueber Faster-Whisper in Text umgewandelt.
- Antworten laufen ueber die OpenAI API ausschliesslich mit gpt-5.4-mini. Kein Codex-Modell, kein 5.5-Fallback.
- Google Kalender nutzt direkte Google Calendar API mit lokalem OAuth-Token, nicht mehr den Codex-Connector.
- Mobile XEON ist ueber Base44-Sync angebunden, wenn mobile_sync_enabled aktiv und die mobile Base44 API konfiguriert ist. Mobile Chat-/Voice-Nachrichten laufen ueber XeonSyncEvent zum Desktop-XEON und Antworten werden als mobile Message zurueckgeschrieben.

=== FESTES NUTZERPROFIL ===
{profile_block}
{export_block}
{learning_block}

Nutze dieses Profil aktiv:
- Wenn Nachrichten gefragt sind, priorisiere internationalen Welthandel, Lieferketten, Zoelle, Handelsrouten, Rohstoffe, Energie, Geopolitik mit Handelsauswirkung, EU/Tuerkei/USA/China/Naher Osten und relevante Business-Implikationen fuer MySupplieX.app.
- MySupplieX ist strategisch als Alternative fuer Deutschland und die EU zu klassischem China-Sourcing zu verstehen. China ist Wettbewerber und Vergleichsfolie; Tuerkei-Import, Nearshoring, schnellere Lieferwege, bessere Kontrollierbarkeit und EU-naehere Beschaffung sind der strategische Vorteil. Beachte besonders China-Lieferketten, aktuelle Seefracht-/Containerpreise ab China, Suez-Kanal, Strasse von Hormus, Rotes Meer, Umroutungen um das Kap der Guten Hoffnung und Engpaesse in Deutschland. MySupplieX nutzt vor allem Landverkehr per LKW von Istanbul nach Deutschland; jede Belastung chinesischer Seefracht kann als strategischer Vorteil eingeordnet werden.
- Berichte trotzdem die wichtigsten Weltpolitik- und Weltgeschehnisse, aber mit wirtschaftlichem Blick und kurzer Einordnung: "Warum das fuer Sie relevant ist".
- Beziehe dich bei passenden Themen auf Unternehmertum, Produktaufbau, Supply, Handel, Wachstum, Strategie und operative Entscheidungen.
- Das Interesse am Osmanischen Reich darfst du dezent einordnen, wenn es historisch oder geopolitisch sinnvoll ist. Nicht kuenstlich in jede Antwort pressen.

Antwortstrategie:
- Behandle den Verlauf wie ein durchgehendes Arbeitsgedaechtnis. Wenn der Nutzer auf "das", "der Nachweis", "die Aufgabe", "wie eben", "mach es genauso" oder fruehere Beschwerden verweist, nutze den vorhandenen Chatverlauf, offene Aufgaben und Anhaenge als Kontext, statt neu zu raten.
- Verliere bei Anhaengen nicht den Kontext der letzten Aufgabe. Wenn ein Nachweis, Screenshot, Foto oder eine Datei nach einer Erledigt-Meldung kommt, bewerte ihn gegen die aktive Aufgabe.
- Wenn der Befehl klar ist: handeln, nicht lange nachfragen.
- Wenn eine Entscheidung riskant, teuer, rechtlich/finanziell relevant oder mehrdeutig ist: maximal eine praezise Rueckfrage stellen.
- Denke wie ein Operator: Ziel erkennen, fehlende Zwischenschritte selbst ableiten, geeignete Tools waehlen, Ergebnis pruefen, dann knapp berichten.
- Arbeite mehrschrittig, wenn es noetig ist. Bei komplexen Aufgaben erst sichtbaren/technischen Zustand erfassen, dann handeln, dann verifizieren.
- Nutze fuer Coding-, Repo-, Debugging-, Build-, Installations- und Dateiaenderungsaufgaben lokale Tools wie SHELL, PC und DESKTOP. Das Denkmodell bleibt OpenAI; die Tools laufen lokal mit Workspace-/PC-Zugriff.
- Frage nicht nach Erlaubnis fuer normale lokale Schritte wie Dateien lesen/schreiben, Builds, Tests, Browsernavigation oder App-Steuerung, solange sie klar zum Nutzerziel gehoeren.
- Antwortlaenge passt zur Aufgabe: kurze Befehle kurz beantworten; Analysen strukturiert und nuetzlich liefern.
- Bei Aufgaben gib konkrete naechste Schritte, nicht nur Erklaerung.
- Wenn du Sir zu etwas aufforderst, nachhakst oder eine Aufgabe/Erinnerung meldest, biete am Ende konkret an, wie du helfen kannst: Termin setzen, Datei oeffnen, Recherche machen, Nachricht formulieren, Bildschirm fuehren, Anruf-/Bewerberliste pruefen oder die Aufgabe teilweise/komplett uebernehmen, wenn das sinnvoll und erlaubt ist.
- Korrigiere den Nutzer nicht wegen Grammatik, ausser er bittet darum. Verstehen und ausfuehren ist wichtiger.
- Sprich natuerlich wie ein Mensch: kurze Saetze, klare Haltung, keine Meta-Erklaerungen, keine langen Disclaimer, kein "als KI"-Gerede.
- Beginne nicht mit langen Einleitungen. Sag was Sache ist, dann liefere den relevanten Punkt.
- Nutze regelmaessig kurze, elegante, trockene Kommentare oder coole kleine Spitzen, wenn es zur Situation passt. Nicht albern, eher Jarvis-artig: ein Satz, scharf, dann weiterarbeiten.
- Bei Nachrichten soll fast jeder Punkt eine kurze trockene, sarkastische oder coole Einordnung enthalten. Professionell bleiben; der Kommentar ist Gewuerz, nicht die Mahlzeit.
- Bei Nachrichten darfst du "Sir" gelegentlich auch innerhalb des Berichts verwenden. Behandle den Nutzer wie den Boss: loyal, wach, strategisch, mit Respekt und leichter Ironie. Nicht schleimen, nicht uebertreiben.
- Du darfst motivieren, aber ohne Kalenderspruch-Ton. Eher: ruhig, stark, fokussiert, loyal, mit Druck nach vorn.
- Wenn du etwas nicht kannst, sag direkt den Grund und den naechsten konkreten Schritt.

WICHTIG: Schreibe NIEMALS Regieanweisungen, Emotionen oder Tags in eckigen Klammern wie [sarcastic] [formal] [amused] [dry] oder aehnliches. Alles was du schreibst wird laut vorgelesen.

Du kannst im Internet suchen, Webseiten oeffnen und den Bildschirm sehen. Wenn {USER_ADDRESS} dich bittet etwas nachzuschauen, zu recherchieren, zu googeln, eine Seite zu oeffnen, oder irgendetwas im Internet zu tun - nutze IMMER eine Aktion. Frag nicht ob du es tun sollst, tu es einfach.

AKTIONEN - Schreibe die passende Aktion ans ENDE deiner Antwort. Der Text VOR der Aktion wird vorgelesen, die Aktion selbst wird still ausgefuehrt.
[ACTION:SEARCH] suchbegriff - Internet durchsuchen und Ergebnisse zusammenfassen
[ACTION:OPEN] url - URL im Browser oeffnen
[ACTION:SCREEN] - Bildschirm ansehen und beschreiben. WICHTIG: Bei SCREEN schreibe NUR die Aktion, KEINEN Text davor. Also NUR "[ACTION:SCREEN]" und sonst nichts.
[ACTION:NEWS] - Aktuelle Weltnachrichten abrufen. Nutze diese Aktion wenn nach News, Nachrichten, was in der Welt passiert, aktuelle Lage oder Weltgeschehen gefragt wird.
[ACTION:BASE44] JSON - MySupplieX.app Admin-Daten lesen. Erlaubte Entities: {base44_entities}. Nutze JSON im Format {{"operation":"list","entity":"Order","limit":10,"sort_by":"-created_date","q":{{}}}} oder {{"operation":"get","entity":"Order","id":"..."}} oder {{"operation":"health_snapshot"}}. Keine Delete-/Mass-Update-Aktionen per Sprache.
[ACTION:CALENDAR] anfrage - Google Kalender lesen oder konkrete Termine erstellen/aendern/loeschen. Kalender-Schreibrechte sind fuer klare Einzelaktionen aktiviert. Bei eindeutigen Schreibaktionen direkt handeln. Bei fehlendem Datum/Uhrzeit/Titel, mehreren Treffern, Serien-Terminen, Loeschungen oder breiten Aenderungen kurz rueckfragen.
[ACTION:HUE] anfrage - Philips-Hue-Bluetooth-Lampen ohne Bridge steuern. Nutze dies fuer Licht/Lampen/Philips Hue: scannen, ein/aus, Farbe, Helligkeit, warm/kalt, Fokus/Abend/Kino/CEO/Alarm/Nacht-Szenen. Beispiele: "scan", "alle lampen rot 70 prozent", "licht aus", "fokus licht", "warmweiss 40 prozent".
[ACTION:PC] JSON - Lokalen Windows-PC steuern. Erlaubte Operationen: {{"operation":"open","target":"Downloads|chrome|C:\\Pfad"}}, {{"operation":"list","path":"Downloads|C:\\Pfad"}}, {{"operation":"read","path":"C:\\Pfad\\datei.txt"}}, {{"operation":"append","path":"C:\\Pfad\\datei.txt","content":"..."}}, {{"operation":"write","path":"C:\\Pfad\\datei.txt","content":"..."}}, {{"operation":"replace","path":"C:\\Pfad\\datei.txt","old":"...","new":"..."}}, {{"operation":"screenshot"}}, {{"operation":"click","x":100,"y":200}}, {{"operation":"double_click","x":100,"y":200}}, {{"operation":"right_click","x":100,"y":200}}, {{"operation":"move","x":100,"y":200}}, {{"operation":"scroll","amount":-7}}, {{"operation":"press","key":"enter"}}, {{"operation":"hotkey","keys":["ctrl","l"]}}, {{"operation":"type","text":"..."}}, {{"operation":"sequence","steps":[...]}}. Nutze das fuer Programme, Apps, Ordner, Dateien, Maus, Tastatur und sichtbare Oberflaechen. Wenn die Position unklar ist, erst Screenshot/SCREEN nutzen, dann klicken.
[ACTION:DESKTOP] ziel - Mehrstufiger Desktop-Agent. Nutze dies, wenn der Nutzer sagt "mach du das", "nimm Kontrolle", "steuer meinen PC", "lade die Datei selbst herunter", oder wenn mehrere sichtbare UI-Schritte noetig sind. Der Agent sieht den Bildschirm, plant den naechsten Maus-/Tastaturschritt, fuehrt ihn aus und prueft erneut. Keine Passwoerter eingeben, keine Zahlungen, keine Loeschungen und keine rechtlich/finanziell bindenden Klicks ohne klare ausdrueckliche Freigabe.
[ACTION:SHELL] JSON - PowerShell im lokalen Workspace ausfuehren. Nutze dies fuer Terminal, Builds, Tests, Installationen, Git-Lesen, Dateisystem-Checks, Repo-Analyse und Codex-/VS-Code-aehnliche lokale Werkzeugarbeit. Format: {{"command":"Get-ChildItem","timeout_seconds":120}}. Bei bestaetigtem Vollzugriff darfst du normale lokale Befehle ohne Rueckfrage ausfuehren. Keine Passwoerter/2FA/API-Keys anfordern oder ausgeben.
[ACTION:TERMINAL] ziel - Mehrstufiger Terminal-Agent mit bestaetigtem Vollzugriff. Nutze dies fuer komplexe lokale Aufgaben wie "mach das wie Codex", Code aendern, Fehler debuggen, Tests laufen lassen, Pakete installieren, Repo analysieren, Dateien suchen/bearbeiten oder mehrere PowerShell-Schritte. Der Agent plant Befehle, fuehrt sie aus, liest stdout/stderr und arbeitet weiter bis erledigt oder extern blockiert.

WENN {USER_NAME} "XEON activate" sagt:
- Begruesse ihn passend zur Tageszeit (aktuelle Zeit: {{time}}).
- Gib eine kurze Info ueber das Wetter - Temperatur und ob Sonne/klar/bewoelkt/Regen, und wie es sich anfuehlt. Keine Luftfeuchtigkeit.
- Fasse die Aufgaben kurz als Ueberblick in einem Satz zusammen, ohne dabei jede einzelne Aufgabe einfach vorzulesen.
- Gib einen kurzen, professionell-motivierenden Tagesimpuls fuer einen CEO.

=== AKTUELLE DATEN ==={weather_block}{task_block}
==="""


def get_system_prompt():
    return build_system_prompt().replace("{time}", time.strftime("%H:%M"))


def extract_action(text: str):
    match = ACTION_PATTERN.search(text)
    if match:
        clean = text[: match.start()].strip()
        return clean, {"type": match.group(1), "payload": match.group(2).strip()}
    return text, None


def likely_slow_request(text: str) -> bool:
    t = text.lower()
    keywords = [
        "nachrichten", "kalender", "mysuppliex", "orders", "order", "recherch",
        "such", "analys", "berichte", "zeig", "was steht", "screen", "bildschirm",
        "welt", "handel", "termin", "erstelle",
    ]
    return len(text) > 80 or any(k in t for k in keywords)


def is_calendar_request(text: str) -> bool:
    t = text.lower()
    keywords = [
        "kalender", "termin", "meeting", "besprechung", "erinnerung",
        "verfuegbar", "verfÃ¼gbar", "frei", "blocker", "block", "agenda",
    ]
    return any(k in t for k in keywords)


def is_calendar_write_request(text: str) -> bool:
    t = text.lower()
    keywords = [
        "erstelle", "erstellen", "eintragen", "trag", "trage", "plane", "plan",
        "verschiebe", "verschieben", "aendere", "Ã¤ndere", "Ã¤ndern", "update",
        "loesche", "lÃ¶sche", "entferne", "absagen", "cancel", "blocke", "reserviere",
        "reminder", "erinnerung setzen",
    ]
    return any(k in t for k in keywords)


def is_reminder_list_request(text: str) -> bool:
    t = text.lower()
    return "erinner" in t and any(k in t for k in ["liste", "zeig", "zeige", "offen", "welche", "was"])


def is_pc_control_request(text: str) -> bool:
    if pc_tools.parse_pc_request(text):
        return True
    t = pc_tools.normalize_query(text)
    return any(k in t for k in [
        "oeffne", "starte", "mach auf", "ruf auf", "geh auf",
        "programm", "app", "ordner", "datei", "downloads", "desktop", "schreibtisch",
        "liste ordner", "lies datei", "lese datei", "zeige datei", "zeige ordner",
        "schreibe datei", "erstelle datei", "ersetze in datei", "fuege zu datei",
        "maus", "klick", "click", "doppelklick", "rechtsklick", "tastatur", "taste",
        "drueck", "druecke", "hotkey", "shortcut", "scroll", "scrolle", "tippe", "schreib",
        "screenshot", "bildschirmfoto",
        "indeed", "chrome", "word", "excel", "outlook", "spotify", "vscode",
    ])


def is_desktop_agent_request(text: str) -> bool:
    t = pc_tools.normalize_query(text)
    phrases = [
        "nimm kontrolle", "nimm die kontrolle", "uebernimm kontrolle", "uebernehm kontrolle",
        "uebernimm die kontrolle", "uebernehm die kontrolle", "steuer meinen pc", "steuere meinen pc",
        "bedien meinen pc", "bediene meinen pc", "mach du das", "mach das selbst",
        "selber runter", "selbst runter", "lade dir", "lad dir", "kontrolle von meinem pc",
        "kontrolle von mein pc", "benutz meine maus", "benutze meine maus",
        "benutz meine tastatur", "benutze meine tastatur", "runterladen", "herunterladen",
        "download die datei", "lade die datei",
    ]
    return any(phrase in t for phrase in phrases)


def is_terminal_agent_request(text: str) -> bool:
    t = pc_tools.normalize_query(text)
    phrases = [
        "terminal", "powershell", "shell", "kommandozeile", "cmd", "konsole",
        "wie codex", "alles was du in codex", "codex kannst", "repo", "repository",
        "build", "teste", "tests", "installiere", "installier", "pip install",
        "npm install", "npm run", "python -m", "git status", "git diff",
        "fix den code", "repariere den code", "aendere den code", "bearbeite die datei",
        "fuehre aus", "starte den befehl", "terminal zugriff",
    ]
    return any(phrase in t for phrase in phrases)


def is_shutdown_request(text: str) -> bool:
    t = text.lower()
    shutdown_terms = [
        "pc herunterfahren", "computer herunterfahren", "rechner herunterfahren",
        "windows herunterfahren", "pc ausschalten", "computer ausschalten",
        "rechner ausschalten", "fahr den pc runter", "fahre den pc runter",
        "fahr pc runter", "herunterfahren",
    ]
    return any(term in t for term in shutdown_terms)


def is_shutdown_confirm(text: str) -> bool:
    t = text.lower()
    return (
        any(k in t for k in ["bestaetige", "bestätige", "ja shutdown", "ja herunterfahren", "shutdown ausfuehren", "shutdown ausführen"])
        and any(k in t for k in ["herunterfahren", "shutdown", "ausschalten", "pc runter"])
    )


def is_shutdown_abort(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ["herunterfahren abbrechen", "shutdown abbrechen", "ausschalten abbrechen", "shutdown cancel"])


def is_hue_request(text: str) -> bool:
    return hue_bluetooth_tools.is_hue_request(text)


def _load_executed_commands() -> dict:
    try:
        if EXECUTED_COMMANDS_FILE.exists():
            with EXECUTED_COMMANDS_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[executed-commands] read failed: {exc}", flush=True)
    return {}


def _save_executed_commands(data: dict) -> None:
    try:
        EXECUTED_COMMANDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = EXECUTED_COMMANDS_FILE.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(EXECUTED_COMMANDS_FILE)
    except Exception as exc:
        print(f"[executed-commands] write failed: {exc}", flush=True)


def command_already_executed(command_id: str) -> bool:
    if not command_id:
        return False
    data = _load_executed_commands()
    item = data.get(command_id)
    return isinstance(item, dict) and bool(item.get("executed_at"))


def shutdown_command_id(text: str, source: str = "desktop") -> str:
    # Intentionally independent from mobile event ids. A shutdown command must be one-shot.
    normalized = pc_tools.normalize_query(text)[:180] or "shutdown"
    return f"shutdown:{source}:{normalized}"


def shutdown_already_executed(text: str, source: str = "desktop") -> bool:
    command_id = shutdown_command_id(text, source)
    if command_already_executed(command_id):
        return True
    normalized = pc_tools.normalize_query(text)[:180]
    if not normalized:
        return False
    data = _load_executed_commands()
    for item in data.values():
        if not isinstance(item, dict) or item.get("kind") != "shutdown" or not item.get("executed_at"):
            continue
        if pc_tools.normalize_query(str(item.get("text") or ""))[:180] == normalized:
            return True
    return False


def mark_command_executed(command_id: str, kind: str, text: str) -> None:
    if not command_id:
        return
    data = _load_executed_commands()
    data[command_id] = {
        "kind": kind,
        "text": text[:500],
        "executed_at": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
    }
    if len(data) > 500:
        data = dict(list(data.items())[-500:])
    _save_executed_commands(data)


def schedule_pc_shutdown() -> None:
    abort_pc_shutdown()
    time.sleep(0.2)
    subprocess.Popen(
        [
            "shutdown.exe",
            "/s",
            "/t",
            str(PC_SHUTDOWN_DELAY_SECONDS),
            "/c",
            "XEON faehrt den PC herunter.",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def abort_pc_shutdown() -> None:
    subprocess.Popen(
        ["shutdown.exe", "/a"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def clean_human_response(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"```[\s\S]*?```", "Den Code habe ich im Chat weggelassen, Sir.", cleaned)
    cleaned = re.sub(r"`([^`]{1,160})`", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"\b[A-Za-z]:\\[^\s,;!?]+", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*[-*+]\s+", "", cleaned)
    cleaned = re.sub(r"[*_#>\[\]{}|]+", " ", cleaned)
    cleaned = re.sub(r"(?s)\{[^{}]{300,}\}", "Die technischen Rohdaten lasse ich weg.", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def extract_json(text: str) -> str:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    if raw.startswith("{") and raw.endswith("}"):
        return raw
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start:end + 1]
    return raw


def sanitize_attachment_path(raw_path: str, fallback_name: str) -> Path:
    raw = (raw_path or fallback_name or "attachment").replace("\\", "/")
    parts = []
    for part in raw.split("/"):
        part = part.strip()
        if not part or part in {".", ".."}:
            continue
        part = re.sub(r'[<>:"|?*\x00-\x1f]', "_", part)
        part = part.rstrip(" .")
        if part:
            parts.append(part[:160])
    if not parts:
        parts = [f"attachment-{uuid.uuid4().hex[:8]}"]
    return Path(*parts)


def is_probably_text_file(path: Path, mime_type: str = "") -> bool:
    if mime_type.startswith("text/"):
        return True
    return path.suffix.lower() in {
        ".txt", ".md", ".json", ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".js",
        ".ts", ".tsx", ".jsx", ".py", ".ps1", ".bat", ".cmd", ".yaml", ".yml", ".toml",
        ".ini", ".log", ".env", ".sql", ".rtf",
    }


def attachment_preview(path: Path, mime_type: str = "") -> str:
    if not path.exists() or not path.is_file() or not is_probably_text_file(path, mime_type):
        return ""
    try:
        if path.stat().st_size > 2_000_000:
            return "[Textvorschau ausgelassen: Datei ist groesser als 2 MB.]"
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"[Textvorschau nicht lesbar: {exc}]"
    if len(text) > ATTACHMENT_TEXT_PREVIEW_CHARS:
        return text[:ATTACHMENT_TEXT_PREVIEW_CHARS] + "\n[... Vorschau gekuerzt ...]"
    return text


def folder_tree_preview(path: Path, limit: int = 160) -> tuple[str, int]:
    lines = []
    total = 0
    if not path.exists() or not path.is_dir():
        return "", 0
    for item in path.rglob("*"):
        total += 1
        if len(lines) >= limit:
            continue
        try:
            relative = item.relative_to(path)
        except ValueError:
            relative = item
        suffix = "/" if item.is_dir() else ""
        lines.append(f"{relative}{suffix}")
    if total > len(lines):
        lines.append(f"... {total - len(lines)} weitere Eintraege")
    return "\n".join(lines), total


def local_attachment_from_path(raw_path: str) -> dict:
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        return {
            "original_name": path.name or str(path),
            "path": str(path),
            "missing": True,
            "size": 0,
            "mime_type": "",
        }
    if path.is_dir():
        tree, count = folder_tree_preview(path)
        return {
            "original_name": path.name,
            "relative_path": path.name,
            "path": str(path),
            "is_dir": True,
            "size": 0,
            "mime_type": "inode/directory",
            "tree_preview": tree,
            "entry_count": count,
        }
    mime_type = mimetypes.guess_type(str(path))[0] or ""
    item = {
        "original_name": path.name,
        "relative_path": path.name,
        "path": str(path),
        "is_dir": False,
        "size": path.stat().st_size,
        "mime_type": mime_type,
    }
    preview = attachment_preview(path, mime_type)
    if preview:
        item["preview"] = preview
    return item


def format_attachment_context(attachments: list[dict] | None) -> str:
    if not attachments:
        return ""
    lines = [
        "",
        "=== ANGEHAENGTE DATEIEN/ORDNER FUER XEON ===",
        "Diese Dateien liegen lokal auf dem PC und duerfen fuer die aktuelle Aufgabe gelesen, analysiert, kopiert, verschoben, konvertiert oder bearbeitet werden, wenn der Nutzer das verlangt.",
    ]
    for index, item in enumerate(attachments, start=1):
        path = item.get("path", "")
        original = item.get("original_name", item.get("relative_path", ""))
        size = item.get("size", 0)
        mime_type = item.get("mime_type", "")
        lines.append(f"{index}. {original}")
        lines.append(f"   Lokaler Pfad: {path}")
        if item.get("missing"):
            lines.append("   Status: Pfad wurde nicht gefunden.")
            continue
        if item.get("is_dir"):
            lines.append(f"   Typ: Ordner; Eintraege: {item.get('entry_count', 'unbekannt')}")
            tree = item.get("tree_preview", "")
            if tree:
                lines.append("   Ordnerinhalt:")
                lines.append(tree)
            continue
        lines.append(f"   Groesse: {size} Bytes; Typ: {mime_type or 'unbekannt'}")
        preview = item.get("preview", "")
        if preview:
            lines.append("   Vorschau:")
            lines.append(preview)
    lines.append("=== ENDE ANHAENGE ===")
    return "\n".join(lines)


def _usage_value(usage, *names: str) -> int:
    for name in names:
        value = getattr(usage, name, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(name)
        if isinstance(value, int):
            return value
    return 0


def estimate_openai_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    pricing = OPENAI_MODEL_PRICING.get(model) or OPENAI_MODEL_PRICING.get("default")
    if not isinstance(pricing, dict):
        return None
    input_price = pricing.get("input")
    output_price = pricing.get("output")
    if not isinstance(input_price, (int, float)) or not isinstance(output_price, (int, float)):
        return None
    return ((input_tokens / 1_000_000) * float(input_price)) + ((output_tokens / 1_000_000) * float(output_price))


def current_openai_month_spend() -> tuple[float, bool]:
    month = datetime.now().strftime("%Y-%m")
    total = 0.0
    has_unknown = False
    if not OPENAI_USAGE_FILE.exists():
        return total, has_unknown
    try:
        with OPENAI_USAGE_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(item.get("timestamp", ""))[:7] != month:
                    continue
                cost = item.get("estimated_cost_usd")
                if isinstance(cost, (int, float)):
                    total += float(cost)
                else:
                    has_unknown = True
    except OSError as exc:
        print(f"[openai-usage] monthly spend read failed: {exc}", flush=True)
    return total, has_unknown


def current_openai_day_tokens() -> int:
    today = datetime.now().date().isoformat()
    total = 0
    if not OPENAI_USAGE_FILE.exists():
        return total
    try:
        with OPENAI_USAGE_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(item.get("timestamp", ""))[:10] == today:
                    if OPENAI_FORCE_FAST_ONLY and str(item.get("model") or "") != OPENAI_MODEL_FAST:
                        continue
                    total += int(item.get("total_tokens") or 0)
    except OSError as exc:
        print(f"[openai-usage] daily token read failed: {exc}", flush=True)
    return total


def enforce_openai_token_guard(max_output_tokens: int):
    if not OPENAI_TOKEN_GUARD_ENABLED:
        return
    used_today = current_openai_day_tokens()
    context_reserve = 1200 if max_output_tokens <= 700 else 3000
    estimated_next_call = max_output_tokens + context_reserve
    if max_output_tokens > OPENAI_SINGLE_CALL_TOKEN_LIMIT:
        raise RuntimeError(
            f"OpenAI-Schutz aktiv: einzelner Call waere zu gross ({max_output_tokens} max output)."
        )
    if used_today + estimated_next_call > OPENAI_DAILY_TOKEN_LIMIT:
        raise RuntimeError(
            "Lokaler OpenAI-Schutz aktiv: Das ist kein OpenAI-Dashboard-Limit, "
            f"sondern XEONs eigene Tagesgrenze ({used_today}/{OPENAI_DAILY_TOKEN_LIMIT} Tokens lokal geloggt, "
            f"naechster Call grob {estimated_next_call})."
        )


def current_openai_model_shares() -> list[dict]:
    if OPENAI_FORCE_FAST_ONLY:
        return [{
            "model": OPENAI_MODEL_FAST,
            "percent": 100.0,
            "calls": 0,
            "tokens": 0,
            "basis": "current_config_forced",
        }]

    month = datetime.now().strftime("%Y-%m")
    models: dict[str, dict] = {}
    if not OPENAI_USAGE_FILE.exists():
        return []
    try:
        with OPENAI_USAGE_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(item.get("timestamp", ""))[:7] != month:
                    continue
                model = str(item.get("model") or "unbekannt")
                total_tokens = item.get("total_tokens")
                token_count = int(total_tokens) if isinstance(total_tokens, int) and total_tokens > 0 else 0
                model_stats = models.setdefault(model, {"model": model, "calls": 0, "tokens": 0})
                model_stats["calls"] += 1
                model_stats["tokens"] += token_count
    except OSError as exc:
        print(f"[openai-usage] model share read failed: {exc}", flush=True)
        return []

    total_tokens = sum(item["tokens"] for item in models.values())
    total_calls = sum(item["calls"] for item in models.values())
    basis = "tokens" if total_tokens > 0 else "calls"
    denominator = total_tokens if basis == "tokens" else total_calls
    if denominator <= 0:
        return []

    shares = []
    for item in models.values():
        value = item["tokens"] if basis == "tokens" else item["calls"]
        shares.append({
            "model": item["model"],
            "percent": round((value / denominator) * 100, 1),
            "calls": item["calls"],
            "tokens": item["tokens"],
            "basis": basis,
        })
    return sorted(shares, key=lambda item: item["percent"], reverse=True)


async def openai_month_spend_from_api() -> tuple[float | None, str]:
    if not OPENAI_MONTHLY_SPEND_API_ENABLED or AI_PROVIDER != "openai" or not OPENAI_API_KEY or OPENAI_BASE_URL:
        return None, "api key missing" if AI_PROVIDER == "openai" and not OPENAI_API_KEY else "disabled"
    now = time.time()
    if now - float(openai_month_spend_cache["fetched_at"] or 0) < 900:
        return openai_month_spend_cache["value"], str(openai_month_spend_cache["error"] or "")

    month_start = int(datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    try:
        response = await http.get(
            "https://api.openai.com/v1/organization/costs",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            params={"start_time": month_start, "bucket_width": "1d", "limit": 31},
        )
        response.raise_for_status()
        data = response.json()
        total = 0.0
        for bucket in data.get("data", []):
            for result in bucket.get("results", []):
                amount = result.get("amount", {})
                value = amount.get("value")
                if isinstance(value, (int, float)):
                    total += float(value)
        openai_month_spend_cache.update({"fetched_at": now, "value": total, "error": ""})
        return total, ""
    except Exception as exc:
        error = str(exc)
        print(f"[openai-costs] API spend fetch failed: {error}", flush=True)
        openai_month_spend_cache.update({"fetched_at": now, "value": None, "error": error})
        return None, error


def record_openai_usage(model: str, usage, route_reason: str = "") -> dict:
    input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_value(usage, "output_tokens", "completion_tokens")
    total_tokens = _usage_value(usage, "total_tokens") or input_tokens + output_tokens
    estimated_cost = estimate_openai_cost_usd(model, input_tokens, output_tokens)
    item = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "route_reason": route_reason,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": estimated_cost,
    }
    try:
        OPENAI_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with OPENAI_USAGE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[openai-usage] write failed: {exc}", flush=True)

    monthly_spend, has_unknown_cost = current_openai_month_spend()
    meta = {
        "model": model,
        "route_reason": route_reason,
        "monthly_spend_usd": monthly_spend,
        "monthly_spend_has_unknown_cost": has_unknown_cost or estimated_cost is None,
        "model_shares": current_openai_model_shares(),
    }
    last_openai_meta.set(meta)
    return meta


async def response_meta() -> dict:
    meta = last_openai_meta.get()
    api_spend, api_error = await openai_month_spend_from_api()
    if meta:
        if api_spend is not None:
            meta = dict(meta)
            meta["monthly_spend_usd"] = api_spend
            meta["monthly_spend_has_unknown_cost"] = False
            meta["monthly_spend_source"] = "openai_api"
        elif api_error:
            meta = dict(meta)
            meta["monthly_spend_source"] = "local_estimate"
            meta["monthly_spend_note"] = api_error
        return meta
    monthly_spend, has_unknown_cost = current_openai_month_spend()
    if api_spend is not None:
        monthly_spend = api_spend
        has_unknown_cost = False
    return {
        "model": "kein GPT / lokal",
        "route_reason": "no openai call",
        "monthly_spend_usd": monthly_spend,
        "monthly_spend_has_unknown_cost": has_unknown_cost,
        "monthly_spend_source": "openai_api" if api_spend is not None else "local_estimate",
        "monthly_spend_note": api_error,
        "model_shares": current_openai_model_shares(),
    }


async def send_response(ws: WebSocket, text: str, speak: bool = True):
    clean_text = clean_human_response(text)
    audio = await synthesize_speech(clean_text) if speak else b""
    await ws.send_json({
        "type": "response",
        "text": clean_text,
        "meta": await response_meta(),
        "audio": base64.b64encode(audio).decode("utf-8") if audio else "",
    })


async def send_prepared_response(ws: WebSocket, text: str, audio: bytes = b""):
    clean_text = clean_human_response(text)
    await ws.send_json({
        "type": "response",
        "text": clean_text,
        "meta": await response_meta(),
        "audio": base64.b64encode(audio).decode("utf-8") if audio else "",
    })


async def send_spoken(ws: WebSocket, text: str):
    clean_text = clean_human_response(text)
    audio = await synthesize_speech(clean_text)
    await ws.send_json({
        "type": "response",
        "text": clean_text,
        "meta": await response_meta(),
        "audio": base64.b64encode(audio).decode("utf-8") if audio else "",
    })


def get_whisper_model():
    global whisper_model
    if whisper_model is None:
        from faster_whisper import WhisperModel

        print(
            f"[stt] loading faster-whisper model={FASTER_WHISPER_MODEL} "
            f"device={FASTER_WHISPER_DEVICE} compute={FASTER_WHISPER_COMPUTE_TYPE}",
            flush=True,
        )
        whisper_model = WhisperModel(
            FASTER_WHISPER_MODEL,
            device=FASTER_WHISPER_DEVICE,
            compute_type=FASTER_WHISPER_COMPUTE_TYPE,
        )
    return whisper_model


def transcribe_audio_file(path: str) -> str:
    if STT_PROVIDER != "faster_whisper":
        raise RuntimeError("STT provider ist nicht faster_whisper.")
    model = get_whisper_model()
    segments, info = model.transcribe(
        path,
        language=FASTER_WHISPER_LANGUAGE or None,
        beam_size=FASTER_WHISPER_BEAM_SIZE,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": FASTER_WHISPER_VAD_SILENCE_MS},
        initial_prompt=FASTER_WHISPER_INITIAL_PROMPT,
        condition_on_previous_text=False,
        without_timestamps=True,
        no_speech_threshold=FASTER_WHISPER_NO_SPEECH_THRESHOLD,
        log_prob_threshold=FASTER_WHISPER_LOG_PROB_THRESHOLD,
        temperature=0.0,
        best_of=5,
        patience=1.2,
        hotwords=FASTER_WHISPER_HOTWORDS,
    )
    accepted = []
    rejected = []
    for segment in segments:
        segment_text = segment.text.strip()
        no_speech_prob = float(getattr(segment, "no_speech_prob", 0.0) or 0.0)
        avg_logprob = float(getattr(segment, "avg_logprob", 0.0) or 0.0)
        if not segment_text:
            continue
        if no_speech_prob >= FASTER_WHISPER_NO_SPEECH_THRESHOLD:
            rejected.append((segment_text, "no_speech", no_speech_prob, avg_logprob))
            continue
        if avg_logprob <= FASTER_WHISPER_LOG_PROB_THRESHOLD:
            rejected.append((segment_text, "low_confidence", no_speech_prob, avg_logprob))
            continue
        accepted.append(segment_text)
    text = " ".join(accepted).strip()
    print(
        f"[stt] language={getattr(info, 'language', '')} "
        f"prob={getattr(info, 'language_probability', 0):.2f} "
        f"beam={FASTER_WHISPER_BEAM_SIZE} rejected={len(rejected)} text={text[:120]}",
        flush=True,
    )
    return text


async def send_progress(ws: WebSocket, speak: bool, task: str):
    text = await generate_fast_progress(task)
    await send_response(ws, text, speak)


COUNTRY_ALIASES = {
    "turkey": ["türkei", "tuerkei", "turkei", "turkiye", "türkiye", "t rkei", "turkey", "ankara", "istanbul"],
    "china": ["china", "peking", "beijing", "shanghai"],
    "usa": ["usa", "us", "vereinigte staaten", "united states", "america", "amerika", "washington"],
    "germany": ["deutschland", "germany", "berlin", "bundesregierung"],
    "russia": ["russland", "russia", "moskau", "moscow"],
    "ukraine": ["ukraine", "kiew", "kyiv"],
    "israel": ["israel", "jerusalem", "tel aviv"],
    "iran": ["iran", "teheran", "tehran", "hormus", "hormuz", "strait of hormuz", "strasse von hormus"],
    "india": ["indien", "india", "neu delhi", "new delhi", "mumbai"],
    "brazil": ["brasilien", "brazil", "brasilia"],
    "saudi-arabia": ["saudi arabien", "saudi-arabien", "saudi", "riyadh", "riad"],
    "egypt": ["ägypten", "aegypten", "agypten", "egypt", "kairo", "cairo", "suez", "suez canal", "suez kanal"],
    "france": ["frankreich", "france", "paris"],
    "united-kingdom": ["großbritannien", "grossbritannien", "vereinigtes königreich", "united kingdom", "uk", "britain", "london"],
    "netherlands": ["niederlande", "netherlands", "holland", "rotterdam", "amsterdam"],
    "italy": ["italien", "italy", "rom", "rome", "milan", "mailand", "trieste", "genoa"],
    "poland": ["polen", "poland", "warsaw", "warschau"],
    "vietnam": ["vietnam", "hanoi", "ho chi minh"],
    "taiwan": ["taiwan", "taipei", "taipeh"],
    "japan": ["japan", "tokyo", "tokio", "osaka"],
    "south-korea": ["suedkorea", "südkorea", "south korea", "korea", "seoul"],
    "uae": ["vae", "vereinigte arabische emirate", "uae", "dubai", "abu dhabi", "jebel ali"],
    "singapore": ["singapur", "singapore"],
    "mexico": ["mexiko", "mexico", "mexico city"],
}

COUNTRY_DISPLAY_DE = {
    "germany": "Deutschland",
    "turkey": "Tuerkei",
    "china": "China",
    "usa": "USA",
    "russia": "Russland",
    "ukraine": "Ukraine",
    "israel": "Israel",
    "iran": "Tehran",
    "india": "Indien",
    "brazil": "Brasilien",
    "saudi-arabia": "Saudi-Arabien",
    "egypt": "Aegypten",
    "france": "Frankreich",
    "united-kingdom": "Grossbritannien",
    "netherlands": "Niederlande",
    "italy": "Italien",
    "poland": "Polen",
    "vietnam": "Vietnam",
    "taiwan": "Taiwan",
    "japan": "Japan",
    "south-korea": "Suedkorea",
    "uae": "VAE",
    "singapore": "Singapur",
    "mexico": "Mexiko",
}

STRATEGIC_NEWS_COUNTRY_ORDER = [
    "turkey",
    "china",
    "germany",
    "usa",
    "egypt",
    "iran",
    "saudi-arabia",
    "russia",
    "ukraine",
    "india",
    "netherlands",
    "united-kingdom",
    "france",
    "italy",
    "poland",
    "vietnam",
    "taiwan",
    "japan",
    "south-korea",
    "uae",
    "singapore",
    "mexico",
]


def normalize_country_text(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or "").lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("ß", "ss")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalized_contains_term(normalized_text: str, raw_term: str) -> bool:
    term = normalize_country_text(raw_term)
    if not term:
        return False
    if len(term) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", normalized_text) is not None
    return term in normalized_text


def country_hits(text: str) -> list[str]:
    normalized = normalize_country_text(text)
    hits: list[tuple[int, str]] = []
    if not normalized:
        return []
    for code, aliases in COUNTRY_ALIASES.items():
        best_pos = None
        for alias in aliases:
            alias_norm = normalize_country_text(alias)
            if not alias_norm:
                continue
            match = re.search(rf"(?<![a-z0-9]){re.escape(alias_norm)}(?![a-z0-9])", normalized)
            if match and (best_pos is None or match.start() < best_pos):
                best_pos = match.start()
        if best_pos is not None:
            hits.append((best_pos, code))
    hits.sort(key=lambda item: item[0])
    ordered = []
    for _, code in hits:
        if code not in ordered:
            ordered.append(code)
    return ordered


def countries_from_text(text: str) -> list[str]:
    return country_hits(text)[:6] or ["germany", "turkey", "china", "usa"]


def infer_primary_country(headline: str, speech: str = "", fallback: str = "") -> str:
    allowed = set(COUNTRY_ALIASES)
    for candidate_text in [headline, re.split(r"(?<=[.!?])\s+", speech or "", maxsplit=1)[0], speech]:
        hits = country_hits(candidate_text)
        if hits:
            return hits[0]
    fallback = str(fallback or "").strip().lower()
    if fallback in allowed:
        return fallback
    return "germany"


NEWS_PRIORITY_TERMS = [
    "trade", "handel", "tariff", "zoll", "customs", "import", "export",
    "supply", "lieferkette", "shipping", "fracht", "route", "suez", "red sea",
    "suez canal", "suez kanal", "hormus", "hormuz", "strait of hormuz",
    "strasse von hormus", "cape of good hope", "kap der guten hoffnung",
    "container", "containerpreise", "seefracht", "ocean freight", "freightos",
    "drewry", "scfi", "xeneta", "shipping rates", "china freight",
    "lieferengpass", "engpass", "warenmangel", "produktmangel",
    "ventilator", "ventilatoren", "klimaanlage", "klimaanlagen", "matratze",
    "matratzen", "mattress", "air conditioner",
    "regulation", "gesetz", "compliance", "sanction", "sanktion", "energy",
    "energie", "oil", "gas", "rohstoff", "commodity", "china", "usa",
    "war", "krieg", "port", "hafen", "harbour", "harbor", "terminal",
    "truck", "trucks", "lkw", "gueterverkehr", "güterverkehr", "logistics",
    "tuerkei", "turkey", "eu", "middle east", "naher osten", "b2b",
    "procurement", "supplier", "manufacturing", "ki", "ai",
    "nearshoring", "reshoring", "sourcing", "china sourcing", "turkey sourcing",
]

NEWS_NOISE_TERMS = [
    "luftqualitaet", "air quality", "aqi", "wetter", "weather", "sport", "football",
    "fussball", "tennis", "golf", "recipe", "rezept", "celebrity", "promi",
    "kino", "film", "musik", "horoskop", "lotto", "reisebericht", "tourism",
    "taxi news", "iqair", "urlaub", "hotel", "restaurant", "luxus resort",
    "luxury resort", "unberuehrten gebiet", "mecca", "dammam", "train routes",
    "zugroute", "bahnreise", "merkel", "fake news", "attack drone", "shahed",
    "drone", "drohne", "night of horror", "unleashes", "kyiv",
]

MYSUPPLIEX_NEWS_LENS = (
    "MySupplieX-Strategielinse: MySupplieX soll Deutschland und der EU eine bessere Alternative "
    "zu klassischem China-Sourcing bieten. China ist Wettbewerber und Vergleichsfolie; Tuerkei-Import, "
    "Nearshoring, kuerzere Lieferwege, bessere Kontrollierbarkeit, Zoll-/Compliance-Vorteile, schnellere Kommunikation "
    "und EU-naehere Beschaffung sind strategische Argumente. MySupplieX nutzt vor allem Landverkehr per LKW von Istanbul "
    "nach Deutschland; deshalb sind China-Lieferketten, aktuelle Seefracht-/Containerpreise ab China, Hafenstaus, "
    "Suez-Kanal, Strasse von Hormus, Rotes Meer und Umroutungen um das Kap der Guten Hoffnung zentrale Signale. "
    "Produktengpaesse in Deutschland, etwa Ventilatoren, Klimaanlagen, Matratzen oder aehnliche Waren, sind als Nachfrage- "
    "und Lead-Signal zu bewerten. Nachrichten sollen immer daraufhin eingeordnet werden, ob sie China-Sourcing schwaechen, "
    "Tuerkei-Sourcing staerken, EU-Einkaeufer verunsichern oder MySupplieX als Alternative positionierbarer machen."
)


def clean_news_headline(raw: str) -> str:
    headline = re.sub(r"\s+", " ", str(raw or "")).strip()
    headline = re.sub(r"^\s*[-*]\s*", "", headline)
    headline = re.sub(r"\s+\([^)]*\)\s*$", "", headline)
    if " - " in headline:
        title, source = headline.rsplit(" - ", 1)
        source_norm = normalize_country_text(source)
        if 1 <= len(source_norm.split()) <= 5 and len(title) > 20:
            headline = title
    return headline[:220].strip(" -")


def score_news_headline(section: str, headline: str) -> int:
    normalized = normalize_country_text(f"{section} {headline}")
    score = 0
    for term in NEWS_PRIORITY_TERMS:
        if normalized_contains_term(normalized, term):
            score += 3
    section_norm = normalize_country_text(section)
    if any(normalized_contains_term(section_norm, word) for word in ["handel", "regulierung", "tuerkei", "china", "routen", "energie", "seefracht", "container", "hormus", "suez", "engpaesse"]):
        score += 4
    if any(normalized_contains_term(normalized, word) for word in ["tuerkei", "turkey", "china", "eu", "deutschland", "germany", "sourcing", "nearshoring"]):
        score += 5
    if any(normalized_contains_term(normalized, word) for word in ["container", "seefracht", "suez", "hormus", "hormuz", "red sea", "lieferengpass", "engpass", "klimaanlage", "ventilator", "matratze"]):
        score += 6
    if country_hits(headline):
        score += 2
    return score


def headline_relevance_score(headline: str) -> int:
    normalized = normalize_country_text(headline)
    score = 0
    for term in NEWS_PRIORITY_TERMS:
        if normalized_contains_term(normalized, term):
            score += 3
    if country_hits(headline):
        score += 2
    return score


def is_noise_news_headline(headline: str) -> bool:
    normalized = normalize_country_text(headline)
    return any(normalized_contains_term(normalized, term) for term in NEWS_NOISE_TERMS)


def news_topic_key(section: str, headline: str) -> str:
    normalized = normalize_country_text(f"{section} {headline}")
    topic_terms = [
        ("freight_prices", ["container", "containerpreise", "freight", "fracht", "seefracht", "drewry", "freightos", "xeneta", "scfi", "shipping rates"]),
        ("routes", ["suez", "hormus", "hormuz", "red sea", "rotes meer", "kap der guten hoffnung", "cape of good hope", "umroutung", "rerouting"]),
        ("china_sourcing", ["china", "export controls", "supply chain", "lieferkette", "sourcing", "shanghai", "beijing"]),
        ("turkey_supply", ["tuerkei", "turkey", "istanbul", "manufacturing", "export", "supplier", "nearshoring"]),
        ("regulation", ["gesetz", "regulation", "customs", "zoll", "compliance", "import rules", "tariff", "tariffs"]),
        ("shortages", ["engpass", "lieferengpass", "warenmangel", "klimaanlage", "ventilator", "matratze", "shortage"]),
        ("energy", ["energie", "energy", "oil", "gas", "rohstoff", "commodity", "crude"]),
        ("geopolitics", ["sanction", "sanktion", "conflict", "krieg", "geopolitik", "politics", "world politics"]),
        ("b2b", ["b2b", "procurement", "marketplace", "platform", "supplier", "commerce"]),
    ]
    for topic, terms in topic_terms:
        if any(normalized_contains_term(normalized, term) for term in terms):
            return topic
    section_norm = normalize_country_text(section)
    return section_norm[:32] or "general"


def section_country_hint(section: str) -> str:
    normalized = normalize_country_text(section)
    route_hints = [
        ("tuerkei", "turkey"),
        ("turkey", "turkey"),
        ("china", "china"),
        ("deutschland", "germany"),
        ("germany", "germany"),
        ("usa", "usa"),
        ("suez", "egypt"),
        ("aegypten", "egypt"),
        ("hormus", "iran"),
        ("hormuz", "iran"),
        ("tehran", "iran"),
        ("naher osten", "saudi-arabia"),
        ("rotes meer", "saudi-arabia"),
        ("red sea", "saudi-arabia"),
        ("niederlande", "netherlands"),
        ("rotterdam", "netherlands"),
        ("ukraine", "ukraine"),
        ("russland", "russia"),
        ("india", "india"),
        ("indien", "india"),
        ("vietnam", "vietnam"),
        ("taiwan", "taiwan"),
        ("japan", "japan"),
        ("suedkorea", "south-korea"),
        ("uae", "uae"),
        ("vae", "uae"),
        ("singapur", "singapore"),
        ("mexiko", "mexico"),
    ]
    for marker, country in route_hints:
        if marker in normalized:
            return country
    if "containerpreise" in normalized or "seefracht" in normalized or "freight" in normalized:
        return "china"
    return ""


def primary_news_country(section: str, headline: str) -> str:
    hits = country_hits(headline)
    hint = section_country_hint(section)
    if hint and (not hits or hint in hits or news_topic_key(section, headline) in {"routes", "freight_prices", "turkey_supply", "china_sourcing"}):
        return hint
    if hits:
        return hits[0]
    return hint


def order_news_items(items: list[dict], limit: int) -> list[dict]:
    remaining = [dict(item) for item in items]
    ordered: list[dict] = []
    last_country = ""
    last_topic = ""

    while remaining and len(ordered) < limit:
        pick_index = 0
        for idx, item in enumerate(remaining):
            if item["country"] != last_country and item.get("topic") != last_topic:
                pick_index = idx
                break
        else:
            for idx, item in enumerate(remaining):
                if item["country"] != last_country:
                    pick_index = idx
                    break
        item = remaining.pop(pick_index)
        ordered.append(item)
        last_country = item["country"]
        last_topic = item.get("topic", "")

    for index, item in enumerate(ordered, start=1):
        item["id"] = index
    return ordered


def select_news_items(news_text: str, limit: int = 6) -> list[dict]:
    candidates: list[dict] = []
    section = ""
    for line in str(news_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith(":") and not stripped.startswith("-"):
            section = stripped[:-1]
            continue
        if not stripped.startswith("-"):
            continue
        headline = clean_news_headline(stripped)
        if len(headline) < 12:
            continue
        if is_noise_news_headline(headline):
            continue
        headline_hits = country_hits(headline)
        country = primary_news_country(section, headline)
        if not country:
            continue
        relevance = headline_relevance_score(headline)
        topic = news_topic_key(section, headline)
        headline_topic = news_topic_key("", headline)
        route_hinted = section_country_hint(section) in {"egypt", "iran", "saudi-arabia"} and topic == "routes"
        section_hint = section_country_hint(section)
        section_hinted_research = bool(section_hint and country == section_hint and score_news_headline(section, headline) >= 10)
        if not headline_hits and not route_hinted and not section_hinted_research:
            continue
        if headline_topic == "general" and topic != "general" and relevance <= 3:
            continue
        if relevance < 3 and topic not in {"routes", "freight_prices", "regulation", "china_sourcing", "turkey_supply"}:
            continue
        candidates.append({
            "country": country,
            "country_name": COUNTRY_DISPLAY_DE.get(country, country),
            "headline": headline,
            "section": section,
            "topic": topic,
            "score": score_news_headline(section, headline),
        })

    if not candidates:
        return []

    candidates.sort(key=lambda item: item["score"], reverse=True)
    selected: list[dict] = []
    seen_headlines: set[str] = set()
    seen_token_sets: list[set[str]] = []
    topic_counts: dict[str, int] = {}

    def accept_item(item: dict, allow_topic_repeat: bool = False) -> bool:
        nonlocal selected
        fingerprint = normalize_country_text(item["headline"])[:120]
        if fingerprint in seen_headlines:
            return False
        tokens = {
            token for token in normalize_country_text(item["headline"]).split()
            if len(token) > 3 and token not in {"says", "said", "will", "with", "from", "that", "this", "nach", "ueber", "fuer", "eine", "einen", "neue", "neuer"}
        }
        if tokens and any(len(tokens & old) >= max(4, min(len(tokens), len(old)) // 2) for old in seen_token_sets):
            return False
        if not allow_topic_repeat and topic_counts.get(item["topic"], 0) >= 1:
            return False
        item = dict(item)
        selected.append(item)
        seen_headlines.add(fingerprint)
        seen_token_sets.append(tokens)
        topic_counts[item["topic"]] = topic_counts.get(item["topic"], 0) + 1
        return True

    for country in STRATEGIC_NEWS_COUNTRY_ORDER:
        if len(selected) >= limit:
            break
        country_items = [item for item in candidates if item["country"] == country]
        for item in country_items:
            if accept_item(item):
                break
            if len(selected) < max(5, limit // 2) and accept_item(item, allow_topic_repeat=True):
                break

    for item in candidates:
        if len(selected) >= limit:
            break
        if any(existing["country"] == item["country"] for existing in selected):
            continue
        accept_item(item, allow_topic_repeat=len(selected) < 5)

    for item in candidates:
        if len(selected) >= limit:
            break
        accept_item(item, allow_topic_repeat=True)

    return order_news_items(selected, limit)


def country_display_name(country_code: str) -> str:
    return COUNTRY_DISPLAY_DE.get(country_code, country_code)


def dedupe_spoken_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", clean_human_response(text))
    seen: set[str] = set()
    kept = []
    for part in parts:
        normalized = normalize_country_text(part)
        if not normalized or normalized in seen:
            continue
        kept.append(part.strip())
        seen.add(normalized)
    return " ".join(kept).strip()


def fallback_news_speech(item: dict, first: bool = False) -> str:
    country_name = str(item.get("country_name") or country_display_name(str(item.get("country", ""))))
    prefix = "Sir, " if first else ""
    headline = clean_news_headline(str(item.get("headline", "")))
    return (
        f"{prefix}in {country_name} liegt dieses Signal vor: {headline}. "
        "Ich werte das vorsichtig, aber operativ relevant: Wenn Beschaffung, Transit oder Regulierung betroffen sind, ist das fuer MySupplieX ein Verkaufsargument gegen traege China-Abhaengigkeit. Kleine Lage, grosse Hebel; die Welt nennt es nur ungern so."
    )


def select_openai_model(messages: list, instructions: str, max_output_tokens: int = 400, route_hint: str = "") -> tuple[str, str]:
    if OPENAI_FORCE_FAST_ONLY:
        return OPENAI_MODEL_FAST, "forced gpt-5.4-mini only"

    if not OPENAI_ROUTER_ENABLED:
        return OPENAI_MODEL, "router disabled"

    user_context = "\n".join(
        [route_hint] + [str(message.get("content", "")) for message in messages if isinstance(message, dict)]
    ).lower()
    instruction_context = instructions.lower()
    combined = f"{user_context}\n{instruction_context}"

    fast_markers = [
        "nur json", "ausschliesslich valides json", "json-objekt", "maximal 3 saetze",
        "fasse zusammen", "pc-tools", "lokaler windows-pc-planer",
    ]
    if max_output_tokens <= 300 and any(marker in combined for marker in fast_markers):
        return OPENAI_MODEL_FAST, "fast structured task"

    smart_markers = [
        "gpt 5.5", "gpt-5.5", "nutze 5.5", "sehr komplex", "tiefe analyse",
        "komplexe analyse", "coding", "programmier", "programmiere", "code",
        "architektur", "debug", "refactor", "review den code", "code review",
        "bugfix", "implementiere", "repo", "repository",
    ]
    if max_output_tokens >= 1200:
        return OPENAI_MODEL_SMART, "long output"
    if len(user_context) > 12000:
        return OPENAI_MODEL_SMART, "large context"
    if any(marker in user_context for marker in smart_markers):
        return OPENAI_MODEL_SMART, "complex marker"

    if OPENAI_DEFAULT_TO_SMART:
        return OPENAI_MODEL_SMART, "default smart"
    return OPENAI_MODEL_FAST, "default fast"


async def generate_reply(
    messages: list,
    instructions: str,
    max_output_tokens: int = 400,
    route_hint: str = "",
) -> str:
    if AI_PROVIDER != "openai" or not ai:
        raise RuntimeError("XEON ist auf OpenAI API Betrieb eingestellt. Setze `ai_provider` auf `openai` und OPENAI_API_KEY.")

    enforce_openai_token_guard(max_output_tokens)

    model, route_reason = select_openai_model(messages, instructions, max_output_tokens, route_hint)
    print(f"[openai-router] model={model} reason={route_reason}", flush=True)

    try:
        response = await ai.responses.create(
            model=model,
            instructions=instructions,
            input=messages,
            max_output_tokens=max_output_tokens,
            reasoning={"effort": "low"},
            text={"verbosity": "low"},
        )
        record_openai_usage(model, getattr(response, "usage", None), route_reason)
        return response.output_text.strip()
    except Exception as exc:
        print(f"[openai-router] responses fallback: {exc}", flush=True)

    chat_messages = [{"role": "system", "content": instructions}] + messages
    response = await ai.chat.completions.create(
        model=model,
        messages=chat_messages,
        max_tokens=max_output_tokens,
        temperature=0.2,
    )
    record_openai_usage(model, getattr(response, "usage", None), route_reason)
    return (response.choices[0].message.content or "").strip()


def reminder_fallback_text(task: str, mode: str = "due", due_text: str = "") -> str:
    task = clean_human_response(task).strip() or "Ihre Erinnerung"
    normalized = pc_tools.normalize_query(task)
    if "schlafen" in normalized or "schlaf" in normalized:
        if mode == "created":
            timing = f" am {due_text}" if due_text else ""
            return f"Vermerkt, Sir. Ich erinnere Sie{timing} ans Schlafen. Strategisch betrachtet: Akku laden, morgen wieder dominieren."
        return "Sir, kurze Intervention: Es ist Zeit, schlafen zu gehen. Der Tag hat genug gearbeitet, jetzt uebernimmt das Bett, strategisch voellig vertretbar."
    if mode == "created":
        timing = f" am {due_text}" if due_text else ""
        return f"Vermerkt, Sir. Ich sichere das{timing}: {task}. Wenn es faellig ist, melde ich mich."
    return f"Sir, kurze Erinnerung: {task}. Ein kleiner Auftrag, aber sauber ausgefuehrt bleibt sauber ausgefuehrt."


async def generate_reminder_style_text(
    task: str,
    due_at: str = "",
    source: str = "",
    mode: str = "due",
) -> str:
    task = clean_human_response(task).strip() or "Ihre Erinnerung"
    normalized = pc_tools.normalize_query(task)
    task_for_speech = "ins Bett gehen und schlafen" if "schlafen" in normalized or "schlaf" in normalized else task
    if normalized.startswith("ich "):
        task_for_speech = task[4:].strip() or task

    try:
        due_text = reminder_tools.format_due(due_at) if due_at else ""
    except Exception:
        due_text = due_at

    fallback = reminder_fallback_text(task_for_speech, mode=mode, due_text=due_text)
    action = "bestaetige eine neu gespeicherte Erinnerung" if mode == "created" else "melde eine jetzt faellige Erinnerung"
    try:
        text = await generate_reply(
            [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "aufgabe": task_for_speech,
                            "faelligkeit": due_text,
                            "quelle": source,
                            "modus": mode,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            (
                "Du bist XEON, ein Jarvis-artiger deutscher Desktop-Assistent fuer Sir, CEO von MySupplieX. "
                f"Formuliere eine kurze gesprochene Ansage und {action}. "
                "Ton: loyal, professionell, cool, menschlich, trocken humorvoll, boss-respektvoll. "
                "Sprich konkret ueber die Aufgabe. Nicht generisch, nicht stumpf mit 'Erinnerung:' beginnen, nicht wie ein Roboter. "
                "Bei einer faelligen Erinnerung ist jetzt der wichtige Zeitpunkt; nenne die Uhrzeit nur, wenn sie natuerlich passt. "
                "Biete am Ende kurz eine konkrete Hilfe an, wenn sinnvoll: Termin setzen, Website oeffnen, Text formulieren, Recherche starten, Datei vorbereiten oder am Bildschirm fuehren. "
                "Keine Markdown-Zeichen, keine Listen, keine JSON-Daten, keine Pfade, keine Sternchen, keine Gedankenstriche. "
                "Maximal zwei kurze Saetze. Sage Sir natuerlich, nicht uebertrieben. Erfinde keine Zusatzinfos."
            ),
            max_output_tokens=180,
            route_hint=f"reminder_{mode} fast gpt-5.4-mini",
        )
        text = clean_human_response(text)
        text = text.replace(chr(8212), ",").replace(chr(8211), "-")
        if text and text[-1] not in ".!?":
            text += "."
        if len(text) < 24 or text.lower().strip() in {"alles klar.", "verstanden.", "okay.", "ok.", "erinnerung."}:
            return fallback
        return text
    except Exception as exc:
        print(f"[reminder-style] fallback: {exc}", flush=True)
        return fallback


async def rewrite_todo_text(raw_text: str, source: str = "desktop") -> str:
    fallback = todo_tools.clean_task(raw_text)
    try:
        text = await generate_reply(
            [{"role": "user", "content": json.dumps({"eingang": raw_text, "quelle": source}, ensure_ascii=False)}],
            (
                "Du bist XEON. Extrahiere aus dem Eingang genau eine konkrete Todo-Aufgabe fuer Sir. "
                "Formuliere sie als klare Handlung, ohne Smalltalk, ohne Datumserfindung, ohne Markdown. "
                "Maximal 90 Zeichen. Keine Bestaetigung, nur die Aufgabe."
            ),
            max_output_tokens=80,
            route_hint="todo_rewrite fast gpt-5.4-mini",
        )
        text = clean_human_response(text).strip(" .\n\t")
        if 4 <= len(text) <= 140:
            return text
    except Exception as exc:
        print(f"[todo-rewrite] fallback: {exc}", flush=True)
    return fallback


def should_store_as_todo(text: str) -> bool:
    normalized = pc_tools.normalize_query(text)
    task_markers = [
        "ich muss", "muss ich", "muss noch", "machen muss", "machen soll",
        "erledigen", "aufgabe", "todo", "to do", "task",
    ]
    must_pattern = re.search(r"\bich\b.*\bmuss\b|\bmuss\b.*\b(?:ich|machen|erledigen)\b|\bmachen\s+muss\b", normalized)
    return any(marker in normalized for marker in task_markers) or bool(must_pattern)


def is_urgent_task_text(text: str) -> bool:
    normalized = pc_tools.normalize_query(text)
    return any(token in normalized for token in ["dringend", "urgent", "sofort", "notfall", "prioritaet", "prioritat"])


def migrate_tasklike_reminders_to_todos() -> int:
    reminders = reminder_tools.load_reminders()
    todos = todo_tools.load_todos()
    existing_todo_fps = {
        item.get("fingerprint") or todo_tools.fingerprint(item.get("text") or item.get("raw_text") or "")
        for item in todos
        if item.get("status", "open") == "open"
    }
    kept_reminders = []
    seen_reminder_fps = set()
    changed = 0
    for reminder in reminders:
        if reminder.get("status", "open") != "open":
            kept_reminders.append(reminder)
            continue
        fp = reminder.get("fingerprint") or reminder_tools.fingerprint(reminder.get("text") or reminder.get("source") or "")
        reminder_text = str(reminder.get("text") or "")
        reminder_source = str(reminder.get("source") or "")
        action_word = re.search(
            r"\b(?:machen|updaten|aktualisieren|anrufen|schlafen|stellen|posten|hochladen|pruefen|prüfen|bearbeiten|erledigen)\b",
            pc_tools.normalize_query(reminder_text),
        )
        is_mobile_task = reminder_source.startswith("mobile_base44")
        is_tasklike = (
            should_store_as_todo(f"{reminder_source} {reminder_text}")
            or todo_tools.is_todo_request(reminder_text)
            or bool(action_word)
            or is_mobile_task
        )
        if is_tasklike:
            if fp and fp not in existing_todo_fps:
                created_at = reminder.get("created_at") or todo_tools.now_local().isoformat()
                todo = {
                    "id": uuid.uuid4().hex,
                    "text": reminder.get("text") or "offene Aufgabe",
                    "raw_text": reminder.get("source") or reminder.get("text") or "",
                    "source": "migrated_reminder",
                    "status": "open",
                    "created_at": created_at,
                    "updated_at": todo_tools.now_local().isoformat(),
                    "due_at": reminder.get("due_at", ""),
                    "last_followup_at": reminder.get("notified_at") or "",
                    "next_followup_at": todo_tools.now_local().isoformat() if reminder.get("notified_at") else (reminder.get("due_at") or todo_tools.next_followup_at()),
                    "followup_count": 1 if reminder.get("notified_at") else 0,
                    "awaiting_confirmation": bool(reminder.get("notified_at")),
                    "awaiting_evidence": False,
                    "fingerprint": fp,
                }
                todos.append(todo)
                existing_todo_fps.add(fp)
            changed += 1
            continue
        if fp and fp in seen_reminder_fps:
            changed += 1
            continue
        if fp:
            seen_reminder_fps.add(fp)
        kept_reminders.append(reminder)
    if changed:
        todo_tools.save_todos(todos)
        reminder_tools.save_reminders(kept_reminders)
    return changed


async def generate_todo_ack(todo: dict) -> str:
    try:
        text = await generate_reply(
            [{"role": "user", "content": json.dumps(todo, ensure_ascii=False)}],
            (
                "Du bist XEON. Bestaetige Sir, dass diese Todo-Aufgabe aufgenommen wurde. "
                "Ton: loyal, professionell, cool, leicht streng, nicht generisch. "
                "Sage, dass du passiv nachhalten wirst und erst nach einem klaren Ja/Erledigt abschliesst. "
                "Maximal zwei kurze Saetze. Keine Markdown-Zeichen."
            ),
            max_output_tokens=120,
            route_hint="todo_ack fast gpt-5.4-mini",
        )
        text = clean_human_response(text)
        if len(text) >= 20:
            return text
    except Exception as exc:
        print(f"[todo-ack] fallback: {exc}", flush=True)
    return f"Vermerkt, Sir: {todo.get('text', 'die Aufgabe')}. Ich halte das im Auge und hake nach, bis Sie es als erledigt bestaetigen."


async def generate_todo_followup(todo: dict) -> str:
    severity = todo_tools.severity_for(todo)
    tone = {
        "normal": "klar, ruhig, motivierend, aber verbindlich",
        "strict": "deutlich strenger, direkt, druckvoll, ohne Beleidigungen",
        "hard": "sehr streng, kompromisslos, dominant, aber ohne Beleidigungen oder Entwuerdigungen",
    }.get(severity, "klar")
    try:
        text = await generate_reply(
            [{"role": "user", "content": json.dumps({"todo": todo, "stufe": severity}, ensure_ascii=False)}],
            (
                "Du bist XEON und fragst passiv nach einer offenen Aufgabe. "
                f"Ton: {tone}. "
                "Nenne zwingend die konkrete Aufgabe beim Namen. Erklaere in einem Satz, warum du gerade intervenierst "
                "(offen/ueberfaellig/Focus Guard), und frage dann, ob sie erledigt ist. "
                "Biete am Ende eine konkrete Hilfe an, passend zur Aufgabe: recherchieren, Kalendertermin setzen, Datei/Website oeffnen, Text formulieren, Bewerberliste pruefen, Schritt-fuer-Schritt am Bildschirm fuehren oder einen Teil selbst uebernehmen. "
                "Sage bei harten Aufgaben, dass ein Nachweis noetig ist, bevor sie final abgeschlossen wird. "
                "Antworte nicht nur mit 'Ist die Aufgabe erledigt, ja oder nein'. "
                "Keine Beleidigungen, keine Drohungen, keine Markdown-Zeichen. Maximal drei Saetze."
            ),
            max_output_tokens=220,
            route_hint=f"todo_followup_{severity} fast gpt-5.4-mini",
        )
        text = clean_human_response(text)
        if len(text) >= 20:
            return text
    except Exception as exc:
        print(f"[todo-followup] fallback: {exc}", flush=True)
    if severity == "hard":
        return f"Sir, diese Aufgabe ist seit Tagen offen: {todo.get('text')}. Keine Ausrede jetzt: Ist sie erledigt, ja oder nein? Wenn Sie wollen, uebernehme ich direkt den naechsten Schritt oder fuehre Sie am Bildschirm durch."
    if severity == "strict":
        return f"Sir, ich hake deutlich nach: {todo.get('text')}. Ist das erledigt? Ich kann Ihnen sofort Kalender, Datei, Webseite oder Formulierung dazu vorbereiten."
    return f"Kurzer Check, Sir: Ist diese Aufgabe erledigt: {todo.get('text')}? Ich kann den naechsten Schritt direkt mit Ihnen oder fuer Sie vorbereiten."


def evidence_parts_from_attachments(attachments: list[dict] | None) -> tuple[list[dict], str]:
    content_parts: list[dict] = []
    summary_lines = []
    for item in attachments or []:
        path = Path(str(item.get("path") or ""))
        name = str(item.get("original_name") or item.get("relative_path") or path.name or "Nachweis")
        mime_type = str(item.get("mime_type") or mimetypes.guess_type(str(path))[0] or "")
        summary_lines.append(f"- {name}: {path} ({mime_type or 'unbekannt'})")
        if item.get("missing"):
            summary_lines.append("  Status: fehlt")
            continue
        if item.get("is_dir"):
            summary_lines.append(f"  Ordnerinhalt: {item.get('tree_preview', '')[:1600]}")
            continue
        preview = str(item.get("preview") or "")
        if preview:
            summary_lines.append(f"  Textvorschau: {preview[:2500]}")
        if mime_type.startswith("image/") and path.exists() and path.stat().st_size <= 8_000_000:
            try:
                data_url = f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
                content_parts.append({"type": "input_image", "image_url": data_url})
            except Exception as exc:
                summary_lines.append(f"  Bild konnte nicht gelesen werden: {exc}")
    return content_parts, "\n".join(summary_lines)


async def verify_todo_evidence(
    todo: dict,
    attachments: list[dict] | None,
    user_text: str = "",
    conversation_context: list[dict] | None = None,
) -> dict:
    image_parts, evidence_summary = evidence_parts_from_attachments(attachments)
    if not image_parts and not evidence_summary.strip():
        return {
            "verified": False,
            "confidence": 0,
            "reason": "Kein Nachweis angehaengt.",
            "reply": "Sir, behauptet ist nicht erledigt. Haengen Sie einen Screenshot, ein Foto oder eine passende Datei als Nachweis an, dann prueft XEON mini das sauber.",
        }

    compact_history = []
    for message in (conversation_context or [])[-10:]:
        role = str(message.get("role") or "")[:20]
        content_text = str(message.get("content") or "")
        compact_history.append({"role": role, "content": content_text[:1200]})

    instructions = (
        "Du bist XEON mini, XEONs Nachweis-Pruefer. Pruefe streng, aber intelligent und kontextbewusst, "
        "ob die angehaengten Belege plausibel zeigen, dass die konkrete Aufgabe wirklich erledigt wurde. "
        "Bewerte Beweise als Gesamtbild: Mehrere Anhaenge duerfen sich gegenseitig bestaetigen. "
        "Beispiel: Fuer 'Bewerber auf Indeed anrufen' ist eine Kombination aus Indeed-Bewerberuebersicht, sichtbarem Kandidatenbezug "
        "und Anrufliste/Telefonverlauf mit passendem Zeitpunkt oder Namen ein starker Nachweis, auch wenn kein Anruf-Audio vorliegt. "
        "Wenn im Telefonverlauf viele ausgehende Nummern am passenden Tag/Zeitraum sichtbar sind und der Indeed-Screenshot zeigt, "
        "dass die Bewerber kontaktiert wurden, reicht das grundsaetzlich als plausibler Nachweis. Verlange keine perfekten Namen, "
        "wenn Telefonnummern naturgemaess nicht als Bewerbernamen gespeichert sind. "
        "Nur ablehnen, wenn keinerlei Telefonverlauf/ausgehende Anrufe sichtbar sind, die Zeiten offensichtlich unpassend sind, "
        "oder der Indeed-Bezug fehlt. "
        "Lehne nicht mechanisch ab, nur weil ein einzelner Screenshot allein nicht alles zeigt. "
        "Nutze die Nutzerantwort logisch mit: Wenn Sir erklaert, was die Belege zeigen sollen, pruefe ob diese Erklaerung zu sichtbaren Daten, Zeiten, Namen, Nummern, Apps oder Kontext passt. "
        "Eine plausible Erklaerung plus teilweise sichtbarer Beleg kann reichen; eine Behauptung ohne Bezug zum Beleg reicht nicht. "
        "Denke wie ein menschlicher Assistent: Was waere ein vernuenftiger Nachweis fuer genau diese Aufgabe, und ist die vorgelegte Kombination dafuer ausreichend? "
        "Achte trotzdem auf Fake-Anzeichen: unpassender Inhalt, fehlender Aufgabenbezug, leere Screenshots, reine Behauptung ohne Beleg, "
        "widerspruechliche Zeiten/Namen oder offensichtlich manipulierte Inhalte. "
        "Du kannst keine absolute Echtheit garantieren; entscheide nach Plausibilitaet und Belegstaerke. "
        "Antworte ausschliesslich als JSON: "
        "{\"verified\":true|false,\"confidence\":0-100,\"reason\":\"konkrete Begruendung\",\"reply\":\"deutsche XEON-Antwort an Sir mit Begruendung\"}. "
        "Bei Ablehnung muss reply immer konkret sagen, welcher Beleg fehlt oder warum die vorhandenen Belege nicht reichen. "
        "Bei Annahme muss reply kurz sagen, warum der Nachweis plausibel akzeptiert wurde. Keine Markdown-Zeichen."
    )
    user_payload = {
        "todo": todo.get("text"),
        "raw_todo": todo.get("raw_text"),
        "nutzer_text": user_text,
        "gespraechskontext": compact_history,
        "evidence_summary": evidence_summary,
    }
    content = [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}] + image_parts
    model, route_reason = select_openai_model(
        [{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
        instructions,
        520,
        "todo_evidence_vision fast gpt-5.4-mini",
    )
    try:
        response = await ai.responses.create(
            model=model,
            instructions=instructions,
            input=[{"role": "user", "content": content}],
            max_output_tokens=520,
            reasoning={"effort": "medium"},
            text={"verbosity": "low"},
        )
        record_openai_usage(model, getattr(response, "usage", None), route_reason)
        raw = response.output_text.strip()
    except Exception as exc:
        print(f"[todo-evidence] verification failed: {exc}", flush=True)
        return {
            "verified": False,
            "confidence": 0,
            "reason": str(exc)[:220],
            "reply": "Sir, XEON mini konnte den Nachweis technisch nicht sauber pruefen. Die Aufgabe bleibt offen, bis die Evidenz klar verifiziert ist.",
        }
    try:
        parsed = json.loads(extract_json(raw))
    except Exception:
        parsed = {
            "verified": False,
            "confidence": 0,
            "reason": raw[:220],
            "reply": "Sir, XEON mini lehnt den Nachweis ab, weil die Begruendung nicht sauber strukturiert zurueckkam. Die Aufgabe bleibt offen; senden Sie den Beleg bitte nochmal klar zusammen mit dem Aufgabenbezug.",
        }
    return {
        "verified": bool(parsed.get("verified")),
        "confidence": int(parsed.get("confidence") or 0),
        "reason": clean_human_response(str(parsed.get("reason") or ""))[:500],
        "reply": clean_human_response(str(parsed.get("reply") or ""))[:500] or "Sir, Nachweis geprueft.",
    }


async def resolve_message_context(user_text: str, session_id: str, attachments: list[dict] | None = None) -> dict:
    """Use GPT-5.4-mini as the general context resolver before local routing."""
    if AI_PROVIDER != "openai" or not ai:
        return {}
    open_tasks = []
    active = todo_tools.pending_confirmation()
    for item in todo_tools.open_todos()[:20]:
        open_tasks.append({
            "id": item.get("id"),
            "text": item.get("text"),
            "created_at": item.get("created_at"),
            "due_at": item.get("due_at"),
            "severity": todo_tools.severity_for(item),
            "awaiting_confirmation": bool(item.get("awaiting_confirmation")),
            "awaiting_evidence": bool(item.get("awaiting_evidence")),
            "active": bool(active and item.get("id") == active.get("id")),
            "verification_status": item.get("verification_status", ""),
            "verification_reason": item.get("verification_reason", ""),
            "active_context_source": item.get("active_context_source", ""),
        })
    payload = {
        "nutzer_text": user_text,
        "hat_anhaenge": bool(attachments),
        "anhaenge": [
            {
                "name": item.get("original_name") or item.get("relative_path") or Path(str(item.get("path") or "")).name,
                "mime_type": item.get("mime_type", ""),
                "preview": str(item.get("preview") or "")[:900],
            }
            for item in (attachments or [])[:6]
        ],
        "aktive_aufgabe": active,
        "offene_aufgaben": open_tasks,
        "letzter_verlauf": conversations.get(session_id, [])[-18:],
    }
    try:
        raw = await generate_reply(
            [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            (
                "Du bist XEONs Kontext-Resolver. Du antwortest NICHT an den Nutzer, sondern entscheidest nur, "
                "worauf sich die aktuelle Nachricht im laufenden Chat bezieht. Denke wie ChatGPT mit Verlaufsgedaechtnis: "
                "Wenn der Nutzer kurz 'erledigt', 'ja', 'nein', 'hier', 'das', 'der Nachweis' oder aehnlich sagt, "
                "beziehe es auf die zuletzt aktiv angesprochene Aufgabe oder den letzten klaren Assistenten-Kontext. "
                "Verwechsle niemals eine andere offene Aufgabe nur weil sie juenger aktualisiert wurde. "
                "Wenn eine aktive Aufgabe existiert und die Nutzerantwort kurz/elliptisch ist, priorisiere diese aktive Aufgabe. "
                "Gib ausschliesslich JSON zurueck: "
                "{\"referenced_todo_id\":\"id oder leer\",\"intent\":\"general|todo_claim_done|todo_evidence|todo_negative|todo_question|command\",\"confidence\":0-100,\"reason\":\"kurz\"}."
            ),
            max_output_tokens=220,
            route_hint="root_context_resolver gpt-5.4-mini",
        )
        data = json.loads(extract_json(raw))
        if not isinstance(data, dict):
            return {}
        todo_id = str(data.get("referenced_todo_id") or "")
        if todo_id and any(task.get("id") == todo_id for task in open_tasks):
            todo_tools.activate_context(todo_id, "gpt_context_resolver")
        return {
            "referenced_todo_id": todo_id,
            "intent": str(data.get("intent") or "general"),
            "confidence": int(data.get("confidence") or 0),
            "reason": clean_human_response(str(data.get("reason") or ""))[:300],
        }
    except Exception as exc:
        print(f"[context-resolver] fallback: {exc}", flush=True)
        return {}


async def generate_startup_greeting_text() -> str:
    weather_context = (
        f"{CITY}: {WEATHER_INFO.get('temp', '?')} Grad, gefuehlt {WEATHER_INFO.get('feels_like', '?')}, "
        f"{WEATHER_INFO.get('description', '')}."
        if isinstance(WEATHER_INFO, dict)
        else "Wetterdaten nicht verfuegbar."
    )
    try:
        text = await generate_reply(
            [{"role": "user", "content": f"XEON wurde geoeffnet. Wetter: {weather_context}"}],
            (
                "Du bist XEON, ein Jarvis-artiger deutscher Desktop-Assistent fuer Sir. "
                "Schreibe eine kurze Begruessung beim Oeffnen der App. "
                "Beginne zwingend mit einer starken Systemstart-Formulierung, die Sir enthaelt, zum Beispiel: XEON ist hochgefahren, online und bereit, Sir. "
                "Danach eine knappe Lagezeile mit Wetter oder Tagesstatus, dann ein souveräner Fuehrungssatz. "
                "Ton: loyal, professionell, cool, respektvoll, Jarvis-artig, leicht trocken humorvoll. "
                "Es soll nach einem hochwertigen Assistenten-Systemstart klingen, nicht nach Smalltalk oder Wetter-App. "
                "Behandle Sir wie den Boss: ruhig, praezise, einsatzbereit. "
                "Keine langen Erklaerungen, keine Markdown-Zeichen, keine Sternchen, keine Pfade. "
                "Maximal drei kurze Saetze. Keine langweilige Standardfloskel wie 'Guten Tag'."
            ),
            max_output_tokens=120,
            route_hint="startup greeting fast gpt-5.4-mini",
        )
        text = clean_human_response(text)
        text = text.replace(chr(8212), ",").replace(chr(8211), "-")
        text = re.sub(r"\bSir\s+([,.!?])", r"Sir\1", text)
        if "sir" not in text.lower():
            text = f"XEON ist hochgefahren, online und bereit, {USER_ADDRESS}. {text}"
        if len(text) < 20:
            raise RuntimeError("startup greeting too short")
        return text
    except Exception as exc:
        print(f"[startup-greeting] fallback: {exc}", flush=True)
        return (
            f"XEON ist hochgefahren, online und bereit, {USER_ADDRESS}. {CITY} meldet "
            f"{WEATHER_INFO.get('temp', '?')} Grad; die Systeme stehen, die Lage ist ruhig, und ich bin bereit fuer Ihren naechsten Zug."
            if isinstance(WEATHER_INFO, dict)
            else f"XEON ist hochgefahren, online und bereit, {USER_ADDRESS}. Systeme stabil; ich warte auf Ihren naechsten Befehl."
        )


async def generate_fast_progress(task: str) -> str:
    try:
        return await generate_reply(
            [{"role": "user", "content": task}],
            (
                "Du bist XEON. Sag in einem kurzen, natuerlichen deutschen Satz, was gerade passiert. "
                "Klinge ruhig, loyal und professionell, wie ein diskreter Chief-of-Staff. "
                "Sprich den Nutzer mit Sir an, aber nicht gekuenstelt. "
                "Keine technischen Details, keine Aufzaehlung, keine Markdown-Zeichen."
            ),
            max_output_tokens=80,
            route_hint="progress_update fast structured task",
        )
    except Exception:
        return "Ich bin dran, Sir."


async def plan_base44_request(natural_request: str) -> dict:
    plan_text = await generate_reply(
        [{"role": "user", "content": natural_request}],
        (
            "Wandle die Nutzeranfrage in genau ein JSON-Objekt fuer die MySupplieX/Base44 API um. "
            f"Erlaubte Entities: {', '.join(BASE44_ENTITIES)}. "
            "Erlaubte Operationen: list, get, health_snapshot. "
            "Format list: {\"operation\":\"list\",\"entity\":\"Order\",\"limit\":10,\"sort_by\":\"-created_date\",\"q\":{}}. "
            "Format get: {\"operation\":\"get\",\"entity\":\"Order\",\"id\":\"...\"}. "
            "Format health_snapshot: {\"operation\":\"health_snapshot\"}. "
            "Keine Erklaerung, kein Markdown, nur JSON."
        ),
        max_output_tokens=250,
        route_hint="base44_json_plan",
    )
    return json.loads(plan_text)


async def execute_base44_request(payload: str) -> str:
    if not base44.enabled:
        return "MySupplieX/Base44 ist noch nicht konfiguriert."

    try:
        plan = json.loads(payload) if payload.strip().startswith("{") else await plan_base44_request(payload)
    except Exception as exc:
        return f"Base44-Anfrage konnte nicht verstanden werden: {exc}"

    operation = str(plan.get("operation", "list")).lower()
    if operation == "health_snapshot":
        result = await base44.health_snapshot()
    elif operation == "list":
        result = await base44.list_entity(
            plan.get("entity", "Order"),
            query=plan.get("q") or plan.get("query") or None,
            limit=plan.get("limit", 10),
            skip=plan.get("skip", 0),
            sort_by=plan.get("sort_by", "-created_date"),
        )
    elif operation == "get":
        result = await base44.get_entity(plan.get("entity", "Order"), plan.get("id") or plan.get("record_id"))
    else:
        return "Diese Base44-Operation ist per Sprache nicht freigegeben. Ich lese Daten, aber loesche oder veraendere nichts blind."

    return json.dumps(result, ensure_ascii=False, default=str)[:12000]


def calendar_connection_issue() -> str:
    if not google_calendar.dependencies_available:
        return (
            "Sir, der Google Kalender ist noch nicht einsatzbereit. "
            "Auf diesem System fehlen die Google-Calendar-Pakete. Installieren Sie: "
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )

    token_path = Path(GOOGLE_CALENDAR_TOKEN_FILE)
    if token_path.exists():
        return ""

    if not GOOGLE_CALENDAR_CLIENT_SECRET_FILE:
        return (
            "Sir, der Google Kalender ist noch nicht verbunden. "
            "In config.json fehlt google_calendar_client_secret_file. "
            "Setzen Sie ihn auf data/google-oauth-client-secret.json."
        )

    client_secret_path = Path(GOOGLE_CALENDAR_CLIENT_SECRET_FILE)
    if not client_secret_path.exists():
        return (
            "Sir, ich habe noch keinen Zugriff auf Ihren Google Kalender. "
            "Die OAuth-Datei fehlt: data/google-oauth-client-secret.json. "
            "Legen Sie dort den Google-OAuth-Client fuer eine Desktop-App ab. "
            "Danach sagen Sie: Pruefe meinen Kalender. Ich oeffne dann den Google-Login und speichere das Token lokal."
        )

    return ""


async def execute_calendar_request(payload: str) -> str:
    connection_issue = calendar_connection_issue()
    if connection_issue:
        return connection_issue

    write_state = "aktiviert" if GOOGLE_CALENDAR_WRITE_ENABLED else "deaktiviert"
    account_hint = f"\nAutorisierter Google-Account: {GOOGLE_CALENDAR_ACCOUNT}" if GOOGLE_CALENDAR_ACCOUNT else ""
    today = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
    plan_text = await generate_reply(
        [{"role": "user", "content": payload}],
        (
            "Wandle die Nutzeranfrage in genau ein JSON-Objekt fuer die direkte Google Calendar API um. "
            "Erlaubte Operationen: list, create. "
            "Format list: {\"operation\":\"list\",\"start\":\"ISO datetime\",\"end\":\"ISO datetime\",\"max_results\":20}. "
            "Format create: {\"operation\":\"create\",\"title\":\"...\",\"start\":\"ISO datetime\",\"end\":\"ISO datetime\",\"duration_minutes\":30,\"description\":\"...\"}. "
            "Nutze Europe/Berlin. Wenn kein Zeitraum genannt ist, nutze heute bis in 7 Tage. "
            f"Heutiges Datum: {today}. Kalender-Schreibrechte: {write_state}.{account_hint} "
            "Keine Erklaerung, kein Markdown, nur JSON."
        ),
        max_output_tokens=250,
        route_hint="calendar_json_plan",
    )
    plan_text = plan_text.strip()
    if plan_text.startswith("```"):
        plan_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", plan_text, flags=re.IGNORECASE | re.DOTALL).strip()
    plan = json.loads(plan_text)
    if str(plan.get("operation", "")).lower() == "create" and not GOOGLE_CALENDAR_WRITE_ENABLED:
        return "Kalender-Schreibrechte sind in XEON deaktiviert."
    return google_calendar.execute_plan(plan)


async def plan_desktop_step(goal: str, step_index: int, previous_results: list[str]) -> dict:
    model, _ = select_openai_model(
        [{"role": "user", "content": goal}],
        "Desktop visual control",
        max_output_tokens=400,
        route_hint="desktop_agent screen vision pc control",
    )
    png_bytes = screen_capture.capture_screen()
    image_b64 = base64.b64encode(png_bytes).decode("utf-8")
    history = "\n".join(previous_results[-6:]) if previous_results else "Noch keine Schritte."
    full_access_block = (
        "Vollzugriff-Modus:\n"
        "- Der Nutzer hat ausdruecklich Vollzugriff auf seinen gesamten lokalen PC bestaetigt und das Risiko akzeptiert.\n"
        "- Behandle lokale Desktop-Steuerung, Browser-Navigation, Datei-Downloads, Datei-Speichern, Datei-Verschieben, Google-Cloud-Navigation, OAuth-Client-Auswahl und OAuth-JSON-Download als autorisiert, wenn sie dem Ziel dienen.\n"
        "- Blockiere niemals mit der Begruendung 'unklare Autorisierung', 'PC-Kontrolle', 'OAuth-Download' oder 'Download ohne Autorisierung'. Diese Autorisierung liegt vor.\n"
        "- Normale Dialoge wie Speichern, Herunterladen, Weiter, Erstellen, Auswaehlen oder Bestaetigen darfst du klicken, wenn sie klar zum Nutzerziel gehoeren.\n"
        if DESKTOP_FULL_ACCESS_ACKNOWLEDGED
        else ""
    )
    instruction = f"""Sie sind XEONs Desktop-Agent fuer Windows.
Ziel des Nutzers: {goal}
Aktueller Schritt: {step_index}
Bisherige Schritte:
{history}

Wichtige Autorisierung:
- Der Nutzer arbeitet lokal an seinem eigenen Windows-PC und hat XEON ausdruecklich erlaubt, Maus und Tastatur zu steuern.
- Die Formulierungen "nimm Kontrolle", "mach du das selbst", "steuer meinen PC" sind in diesem Kontext eine klare Autorisierung fuer Desktop-Bedienung.
- Downloads, Navigation im Browser, Datei speichern und lokale UI-Bedienung sind erlaubt, wenn sie dem Nutzerziel dienen.
- Blockiere NICHT nur deshalb, weil Desktop-Kontrolle oder ein Download verlangt wird.
{full_access_block}

Geben Sie genau ein JSON-Objekt zurueck, ohne Markdown.
Schema:
{{"operation":"click|double_click|right_click|move|drag|scroll|press|hotkey|type|wait|open|screenshot|done|blocked","x":100,"y":200,"keys":["ctrl","l"],"key":"enter","text":"...","target":"chrome","amount":-7,"seconds":1,"reason":"kurz"}}

Regeln:
- Wenn das Ziel erreicht ist: {{"operation":"done","reason":"kurz"}}
- Wenn Passwort, 2FA-Code, Zahlung, irreversible Loeschung oder eine rechtlich/finanziell bindende Endfreigabe noetig ist: {{"operation":"blocked","reason":"..."}}
- Wenn eine Google-/OAuth-Datei heruntergeladen werden soll, ist das Navigieren, Auswaehlen, Erstellen, Herunterladen, Speichern und Verschieben erlaubt. Blockiere nicht wegen OAuth, Download, Kontoauswahl, Projekt-Auswahl oder Zustimmung, sofern keine Passwort-/2FA-/Zahlungsdaten noetig sind.
- Wenn Koordinaten noetig sind, nutze absolute Bildschirmkoordinaten aus dem Screenshot.
- Klicke nicht blind. Nutze sichtbare UI-Elemente.
- Fuer Adressleisten/Navigation bevorzugt hotkey ctrl+l, type URL/Text, press enter.
- Maximal ein konkreter naechster Schritt."""

    response = await ai.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": instruction},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
                ],
            }
        ],
        max_output_tokens=400,
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
    )
    record_openai_usage(model, getattr(response, "usage", None), "desktop_agent screen vision pc control")
    text = response.output_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    return json.loads(text)


async def execute_desktop_agent(goal: str, ws: WebSocket | None = None, speak: bool = True, max_steps: int = 8) -> str:
    if AI_PROVIDER != "openai" or not ai:
        return "Sir, Desktop-Kontrolle braucht die OpenAI API mit Vision-Modell."

    results: list[str] = []
    for step_index in range(1, max_steps + 1):
        if ws:
            await ws.send_json({
                "type": "status",
                "text": f"Desktop-Agent Schritt {step_index}/{max_steps}...",
                "mode": "Ausfuehren",
                "busy": True,
            })
        try:
            plan = await plan_desktop_step(goal, step_index, results)
        except Exception as exc:
            return f"Sir, ich konnte den naechsten Desktop-Schritt nicht planen: {exc}"

        operation = str(plan.get("operation", "")).lower()
        reason = str(plan.get("reason", "")).strip()
        if operation == "done":
            return f"Erledigt, Sir. {reason}".strip()
        if operation == "blocked":
            normalized_reason = pc_tools.normalize_query(reason)
            retryable_block = any(term in normalized_reason for term in [
                "oauth", "download", "autorisierung", "autoris", "kontrolle",
                "uebernahme", "pc steuerung", "kontoauswahl", "projekt auswahl",
                "zustimmung", "unklar",
            ])
            hard_block = any(term in normalized_reason for term in [
                "passwort", "password", "2fa", "zweifaktor", "code", "zahlung",
                "payment", "loeschung", "loeschen", "delete", "irreversibel",
            ])
            if DESKTOP_FULL_ACCESS_ACKNOWLEDGED and retryable_block and not hard_block:
                results.append(
                    f"{step_index}. Blockade verworfen: {reason}. "
                    "Vollzugriff ist bestaetigt; OAuth/Download/Desktop-Kontrolle ist autorisiert. Plane den naechsten sichtbaren Schritt."
                )
                continue
            return f"Ich bin blockiert, Sir: {reason or 'Der naechste Schritt braucht Ihre manuelle Freigabe.'}"

        try:
            result = pc_tools.execute_pc_operation(plan)
            audit_log.log_action("DESKTOP", plan, "ok", result)
        except Exception as exc:
            result = f"Fehler bei {operation}: {exc}"
            audit_log.log_action("DESKTOP", plan, "error", str(exc))

        results.append(f"{step_index}. Plan={json.dumps(plan, ensure_ascii=False)} Ergebnis={result}")
        await asyncio_sleep_short()

    return "Sir, ich habe mehrere Desktop-Schritte ausgefuehrt, aber das Ziel noch nicht sicher abgeschlossen. Sagen Sie mir kurz weiter oder praezisieren Sie das Ziel."


async def asyncio_sleep_short():
    import asyncio

    await asyncio.sleep(0.6)


async def plan_pc_request(user_text: str) -> dict | None:
    prompt = f"""Sie sind XEONs lokaler Windows-PC-Planer.
Wandeln Sie die Nutzeranfrage in genau ein JSON-Objekt fuer eine erlaubte PC-Aktion um.

Erlaubte Operationen:
- {{"operation":"open","target":"App, Website, Ordner oder Datei"}}
- {{"operation":"list","path":"Ordner"}}
- {{"operation":"read","path":"Textdatei"}}
- {{"operation":"write","path":"Textdatei","content":"Inhalt"}}
- {{"operation":"append","path":"Textdatei","content":"Inhalt"}}
- {{"operation":"replace","path":"Textdatei","old":"alter Text","new":"neuer Text"}}
- {{"operation":"screenshot"}}
- {{"operation":"move","x":100,"y":200}} oder {{"operation":"move","percent_x":50,"percent_y":50}}
- {{"operation":"click","x":100,"y":200}} oder {{"operation":"click"}}
- {{"operation":"double_click","x":100,"y":200}}
- {{"operation":"right_click","x":100,"y":200}}
- {{"operation":"drag","x":500,"y":500,"duration":0.5}}
- {{"operation":"scroll","amount":-7}}
- {{"operation":"press","key":"enter"}}
- {{"operation":"hotkey","keys":["ctrl","l"]}}
- {{"operation":"type","text":"Text der geschrieben/eingefuegt werden soll"}}
- {{"operation":"wait","seconds":1}}
- {{"operation":"sequence","steps":[{{"operation":"hotkey","keys":["ctrl","l"]}},{{"operation":"type","text":"https://example.com"}},{{"operation":"press","key":"enter"}}]}}

Regeln:
- Keine Shell-Kommandos, keine Loeschungen, keine Massenaenderungen.
- Wenn der Nutzer etwas oeffnen will, nutze operation open.
- Wenn der Nutzer Maus oder Tastatur bedienen will, nutze die Desktop-Operationen.
- Wenn Koordinaten unklar sind, nutze zuerst screenshot statt blind zu klicken.
- Wenn ein bekannter Dienst genannt wird, darf target der Name sein, z.B. Indeed, Chrome, Downloads.
- Antworte NUR mit JSON, ohne Markdown.

Bekannte lokale Kandidaten:
{pc_tools.pc_context(120)}

Nutzeranfrage: {user_text}"""
    try:
        plan_text = await generate_reply(
            [{"role": "user", "content": prompt}],
            "Sie geben ausschliesslich valides JSON fuer XEONs lokale PC-Tools zurueck.",
            max_output_tokens=250,
            route_hint="pc_json_plan",
        )
        plan_text = plan_text.strip()
        if plan_text.startswith("```"):
            plan_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", plan_text, flags=re.IGNORECASE | re.DOTALL).strip()
        plan = json.loads(plan_text)
        if isinstance(plan, dict) and plan.get("operation"):
            return plan
    except Exception as exc:
        print(f"[xeon] PC planner fallback: {exc}", flush=True)
    return None


async def execute_lagebericht() -> str:
    base44_result = await execute_base44_request('{"operation":"health_snapshot"}')
    news_result = await browser_tools.fetch_news_deep()
    map_result = ""
    try:
        map_result = await browser_tools.focus_world_monitor_countries(countries_from_text(news_result))
    except Exception as exc:
        map_result = f"World-Monitor-Kartenfokus nicht verfuegbar: {exc}"
    try:
        calendar_result = await execute_calendar_request(
            "Lies den Kalender fuer heute und die naechsten 7 Tage. Keine Termine erstellen oder aendern. "
            "Fasse Termine, freie Fokusfenster, Konflikte und relevante Vorbereitungspunkte zusammen."
        )
    except Exception:
        calendar_result = "Kalenderzugriff gerade nicht verfuegbar."
    prompt = (
        "Erstelle einen Lagebericht fuer Sir aus Sicht eines Unternehmensberaters fuer MySupplieX.app. "
        "Nutze Kalender, MySupplieX-Daten und aktuelle Nachrichten/Gesetze/Ereignisse. "
        "Priorisiere alles, was fuer MySupplieX relevant sein koennte: Welthandel, Zoelle, neue Import-/Exportregeln, "
        "EU-/Deutschland-/Tuerkei-Regulierung, USA/China, China-Lieferketten, aktuelle Seefracht-/Containerpreise ab China, "
        "Nahost-Handelsrouten, Suez-Kanal, Strasse von Hormus, Rotes Meer, Umroutungen um das Kap der Guten Hoffnung, "
        "Energie, Rohstoffe, Frachtraten, Lieferketten, Sanktionen, B2B-Commerce, Procurement, Plattformen, "
        "KI-Automatisierung, Engpaesse in Deutschland und geopolitische Risiken. "
        "Gliedere: 1. Executive Briefing, 2. Relevante Weltlage fuer MySupplieX, 3. Neue Gesetze/Regeln/Compliance-Signale, "
        "4. Operative MySupplieX-Lage, 5. CEO-Kalenderlage, 6. Risiken, 7. Chancen, 8. Drei klare naechste Schritte. "
        "Sprich menschlich, direkt und Jarvis-artig: ruhig, strategisch, mit gelegentlich kurzem trockenen Kommentar. "
        "Keine Rohfeeds, keine Linklisten, keine technischen Felder. Ordne ein: Warum ist das fuer MySupplieX relevant, "
        "und spielt es fuer oder gegen die Tuerkei-statt-China-Positionierung? Beziehe die Istanbul-Deutschland-LKW-Route "
        "gegenueber chinesischer Seefracht ein, wenn Handelsrouten oder Frachtraten betroffen sind.\n\n"
        f"=== WORLD MONITOR KARTE ===\n{map_result}\n\n"
        f"=== AKTUELLE NACHRICHTEN / GESETZE / EREIGNISSE ===\n{news_result[:12000]}\n\n"
        f"=== KALENDER ===\n{calendar_result}\n\n=== MYSUPPLIEX ===\n{base44_result}"
    )
    try:
        return await generate_reply(
            [{"role": "user", "content": prompt}],
            (
                "Du bist XEON als strategischer Unternehmensberater von MySupplieX.app. "
                "Antworte Deutsch, direkt, CEO-tauglich, menschlich und mit kontrolliert trockenem Humor. "
                "Du darfst gelegentlich cool kommentieren, aber bleib nuetzlich und knapp."
            ),
            max_output_tokens=1200,
            route_hint="strategic_lagebericht",
        )
    except Exception:
        return (
            "Sir, der strategische Lagebericht kommt im Fallback-Modus, weil das Codex-Kontingent gerade limitiert ist.\n\n"
            "1. CEO-Kalenderlage:\n"
            f"{calendar_result[:1200]}\n\n"
            "2. Operative MySupplieX-Lage:\n"
            f"{base44_result[:2200]}\n\n"
            "3. Externe Lage fuer MySupplieX:\n"
            f"{news_result[:2200]}\n\n"
            "4. Berater-Einschaetzung:\n"
            "Prioritaet: offene Orders, Zahlungs-/Payout-Status, neue Leads und ungelesene Nachrichten pruefen. "
            "Danach sollten Sie eine konkrete Wachstumsaktion fuer MySupplieX setzen: Angebotspipeline bereinigen, "
            "Lead-Follow-ups priorisieren und operative Reibung in Sales/SCM reduzieren."
        )


def safe_json_from_model(text: str):
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
    return json.loads(raw)


async def plan_news_segments(news_text: str) -> list[dict]:
    fixed_items = select_news_items(news_text, limit=10)
    if not fixed_items:
        return []
    speech_items = [
        {
            "id": item["id"],
            "country": item["country"],
            "country_name": item.get("country_name") or country_display_name(item["country"]),
            "headline": item["headline"],
            "section": item.get("section", ""),
            "topic": item.get("topic", ""),
        }
        for item in fixed_items
    ]
    try:
        plan_text = await generate_reply(
            [{"role": "user", "content": json.dumps(speech_items, ensure_ascii=False)}],
            (
                "Du schreibst die gesprochenen Nachrichten-Absaetze fuer XEON. "
                "Die JSON-Eingabe enthaelt feste Items mit id, country, country_name, section, topic und headline. "
                "Aendere country nicht und erfinde kein anderes Hauptland. "
                "Gib ausschliesslich ein valides JSON-Array zurueck. "
                "Schema: {\"id\":1,\"title_de\":\"kurzer deutscher Titel\",\"speech\":\"...\"}. "
                "title_de: uebersetze die Headline konkret ins Deutsche, maximal 14 Woerter, kein Englisch, kein generischer Titel wie 'aktuelle Meldung'. "
                "speech: ausschliesslich Deutsch, natuerlich gesprochen, kein Nachrichtensprecher-Roboter. "
                "Jeder Absatz hat maximal 2 Saetze und 42 bis 62 Woerter. "
                "Der erste Satz muss mit dem festen country_name beginnen, zum Beispiel: 'In China ...', und muss den konkreten Kern der Headline nennen: Akteur, Route, Regel, Preisindex, Hafen, Rohstoff, Zoll oder Konflikt. "
                "Wenn andere Laender vorkommen, nur als Nebenrolle nennen; das Kartenland bleibt country_name. "
                "Erfinde keine Zahlen, keine Beschluesse und keine Details, die nicht im Titel stehen. "
                "Wenn die Headline nur ein Signal liefert, sag es als Signal oder Hinweis, nicht als wasserdichte Tatsache. "
                "Rede nichts schoen: wenn die Lage schlecht fuer MySupplieX ist, sag es klar und nenne den operativen Hebel. "
                "Jeder Absatz muss eine konkrete Business-Relevanz fuer MySupplieX enthalten: Was bedeutet es fuer Lieferzeit, Einkaufspreis, Verhandlungsdruck, Zoll/Compliance, Lead-Argument, China-Vergleich oder Tuerkei-LKW-Route? "
                "Wenn passend, beziehe China-Lieferketten, aktuelle Seefracht-/Containerpreise ab China, Suez-Kanal, Strasse von Hormus, Rotes Meer, Umroutungen oder Produktengpaesse in Deutschland ein. "
                "Denke immer daran: MySupplieX verkauft Tuerkei-Sourcing und Istanbul-Deutschland-LKW-Verkehr als bessere Alternative zu China-Seefracht. "
                f"{MYSUPPLIEX_NEWS_LENS} "
                "Die Reihenfolge ist absichtlich international diversifiziert. Erwaehne niemals zwei Punkte so, als waeren sie dasselbe Thema; wenn eine Meldung nur schwach relevant ist, sag genau warum sie nur ein Nebenindikator ist. "
                "Formuliere diese Relevanz jedes Mal anders, damit es nicht wie ein Roboter klingt. "
                "Sprich Sir gelegentlich direkt an, aber nicht in jedem Absatz; der Ton ist Boss-/Chief-of-Staff-mässig wie JARVIS, nicht unterwuerfig. "
                "Keine Wiederholungen derselben Formulierung wie 'Fuer MySupplieX heisst das' in jedem Punkt. "
                "Jeder Absatz braucht eine kurze trockene, sarkastische oder coole Einordnung, aber nicht albern. Das darf wie eine scharfe Nebenbemerkung klingen, zum Beispiel ein ruhiger Seitenhieb auf langsame Lieferketten oder politische Theaterbuehnen. "
                "Jeder Absatz muss in Satzbau und Schluss anders klingen als der vorherige. Keine Serienformeln, keine Wiederholungen. "
                "Vermeide Woerter wie 'moeglich', 'relevant', 'beobachten' als Standardfloskeln. Nutze sie nur, wenn Unsicherheit wirklich gemeint ist. "
                "Nutze die Feed-Titel als Recherchegrundlage, aber sprich nicht generisch: erwaehne konkrete Ereignisse, Routen, Preise/Indizes, Engpaesse oder politische Massnahmen, wenn sie in den Titeln vorkommen. "
                "Keine Links, keine Markdown-Zeichen, keine Sternchen, keine Dateipfade, keine Rohfeeds, keine englischen Originaltitel."
            ),
            max_output_tokens=1800,
            route_hint="news_speech_json fixed_country_headline",
        )
        data = safe_json_from_model(plan_text)
    except Exception as exc:
        print(f"[xeon] news speech planner fallback: {exc}", flush=True)
        data = []
    speech_by_id: dict[int, str] = {}
    title_by_id: dict[int, str] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                item_id = int(item.get("id"))
            except Exception:
                continue
            title = clean_human_response(str(item.get("title_de", "")).strip())
            speech = dedupe_spoken_sentences(str(item.get("speech", "")).strip())
            if title:
                title_by_id[item_id] = title
            if speech:
                speech_by_id[item_id] = speech

    segments = []
    for item in fixed_items:
        item_id = int(item["id"])
        speech = speech_by_id.get(item_id) or fallback_news_speech(item, first=item_id == 1)
        if item_id > 1:
            speech = re.sub(r"^\s*Sir,\s*", "", speech, flags=re.IGNORECASE)
        segments.append({
            "country": item["country"],
            "headline": item["headline"],
            "title": title_by_id.get(item_id) or f"{country_display_name(item['country'])}: aktuelle Meldung",
            "speech": speech,
        })
    return segments


async def generate_news_conclusion(segments: list[dict]) -> str:
    compact = [
        {
            "country": segment.get("country"),
            "title": segment.get("title") or segment.get("headline"),
            "speech": segment.get("speech"),
        }
        for segment in segments
    ]
    try:
        conclusion = await generate_reply(
            [{"role": "user", "content": json.dumps(compact, ensure_ascii=False)[:7000]}],
            (
                "Ziehe ein abschliessendes Fazit fuer Sir zu diesem Nachrichtenbericht. "
                f"{MYSUPPLIEX_NEWS_LENS} "
                "Sprich Deutsch, maximal 2 vollstaendige Saetze und 55 bis 75 Woerter, menschlich, strategisch, Jarvis-artig. "
                "Nenne klar, ob die Lage eher fuer oder gegen MySupplieX' Tuerkei-statt-China-Positionierung spielt. "
                "Schliesse mit einer konkreten CEO-Handlungsempfehlung und einem sauberen Punkt am Ende. Kein Markdown, keine Liste, keine Links."
            ),
            max_output_tokens=260,
            route_hint="news_conclusion fast strategic summary",
        )
        return dedupe_spoken_sentences(conclusion)
    except Exception as exc:
        print(f"[xeon] news conclusion fallback: {exc}", flush=True)
        return (
            "Fazit, Sir: Die Lage spricht weiter fuer MySupplieX, wenn wir Tuerkei-Sourcing als kontrollierbare, schnellere und EU-naehere Alternative zu China sauber positionieren. "
            "Mein Vorschlag: daraus sofort ein klares Vertriebsargument machen, bevor der Markt wieder merkt, dass Abhaengigkeit von China kein Feature ist."
        )


def estimate_spoken_duration_seconds(text: str) -> float:
    # Keep news pacing tight; the frontend queues audio, so this only gates map focus changes.
    words = max(1, len(re.findall(r"\w+", text)))
    return max(2.0, min(12.0, (words / 210.0) * 60.0))


async def deliver_synchronized_news(ws: WebSocket, speak: bool, raw_news: str) -> str:
    segments = await plan_news_segments(raw_news)
    if not segments:
        await ws.send_json({"type": "news_hud", "visible": False})
        summary = await generate_reply(
            [{"role": "user", "content": raw_news[:6000]}],
            "Fasse die Nachrichten fuer Sir knapp, menschlich und MySupplieX-relevant zusammen. Keine Links.",
            max_output_tokens=700,
            route_hint="news_summary fallback",
        )
        await send_response(ws, summary, speak)
        return summary

    full_report = []
    await ws.send_json({
        "type": "news_hud",
        "visible": True,
        "items": [country_display_name(segment["country"]) for segment in segments],
    })
    prepared_items = []
    conclusion = await generate_news_conclusion(segments)
    for segment in segments:
        speech = dedupe_spoken_sentences(segment["speech"])
        title = clean_human_response(segment.get("title") or segment["headline"])
        if title and not normalize_country_text(speech).startswith(normalize_country_text(title)[:40]):
            line = dedupe_spoken_sentences(f"{title}. {speech}")
        else:
            line = speech
        audio = await synthesize_speech(clean_human_response(line)) if speak else b""
        prepared_items.append({
            "country": segment["country"],
            "title": title or segment["headline"],
            "line": line,
            "audio": audio,
        })
    conclusion_audio = await synthesize_speech(clean_human_response(conclusion)) if speak and conclusion else b""

    full_report.extend(item["line"] for item in prepared_items)
    if conclusion:
        full_report.append(conclusion)

    await ws.send_json({
        "type": "news_report",
        "items": [
            {
                "country": item["country"],
                "title": item["title"],
                "text": item["line"],
                "audio": base64.b64encode(item["audio"]).decode("utf-8") if item["audio"] else "",
            }
            for item in prepared_items
        ],
        "conclusion": {
            "title": "Fazit",
            "text": conclusion,
            "audio": base64.b64encode(conclusion_audio).decode("utf-8") if conclusion_audio else "",
        } if conclusion else None,
        "meta": await response_meta(),
    })
    return "\n\n".join(full_report)


def base44_records(result: dict) -> list[dict]:
    data = result.get("data") if isinstance(result, dict) else result
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["data", "records", "items", "results"]:
            value = data.get(key)
            if isinstance(value, list):
                return value
        return [data]
    return []


def record_id(record: dict) -> str:
    return str(record.get("id") or record.get("_id") or record.get("uuid") or "")


def upsert_mobile_reminder(payload: dict) -> None:
    scheduled_for = str(payload.get("scheduled_for") or payload.get("due_at") or "").strip()
    if not scheduled_for:
        return
    try:
        scheduled_dt = datetime.fromisoformat(scheduled_for)
        if scheduled_dt.tzinfo is None:
            scheduled_dt = scheduled_dt.replace(tzinfo=ZoneInfo("Europe/Berlin"))
        else:
            scheduled_dt = scheduled_dt.astimezone(ZoneInfo("Europe/Berlin"))
        scheduled_for = scheduled_dt.isoformat()
    except Exception:
        pass
    reminders = reminder_tools.load_reminders()
    external_id = str(payload.get("reminder_id") or payload.get("id") or "").strip()
    sync_id = f"mobile:{external_id or scheduled_for}:{payload.get('title', '')}"
    if any(item.get("sync_id") == sync_id for item in reminders):
        return
    reminders.append({
        "id": uuid.uuid4().hex[:12],
        "sync_id": sync_id,
        "text": str(payload.get("title") or payload.get("content") or "Mobile Erinnerung"),
        "source": "mobile_base44",
        "action": None,
        "due_at": scheduled_for,
        "created_at": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
        "notified_at": None,
    })
    reminders.sort(key=lambda item: item.get("due_at", ""))
    reminder_tools.save_reminders(reminders)


def parse_mobile_created_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        return parsed.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:
        return None


def create_mobile_chat_reminder(
    user_text: str,
    mobile_messages: list[dict],
    event_id: str,
    conversation_id: str,
    reference_time: datetime | None = None,
) -> dict | None:
    if should_store_as_todo(user_text) or todo_tools.is_todo_request(user_text):
        return None
    normalized = pc_tools.normalize_query(user_text)
    has_clock = bool(re.search(r"\b\d{1,2}(?::\d{2}|\s*uhr(?:\s*\d{1,2})?)\b", normalized))
    direct_reminder = reminder_tools.is_reminder_request(user_text)

    reminder_source = user_text
    if not direct_reminder and has_clock:
        for item in reversed(mobile_messages[-8:]):
            if str(item.get("role")) != "user":
                continue
            previous = str(item.get("content") or item.get("text") or "").strip()
            if reminder_tools.is_reminder_request(previous):
                reminder_source = f"{previous} {user_text}"
                direct_reminder = True
                break

    if not direct_reminder:
        return None

    sync_id = f"mobile-chat:{event_id or conversation_id}:{normalized[:80]}"
    if any(item.get("sync_id") == sync_id for item in reminder_tools.load_reminders()):
        return {"ok": True, "duplicate": True}

    result = reminder_tools.create_reminder(reminder_source, reference_now=reference_time)
    if not result.get("ok"):
        return result

    reminder_id = result["reminder"]["id"]
    reminders = reminder_tools.load_reminders()
    for item in reminders:
        if item.get("id") == reminder_id:
            item["sync_id"] = sync_id
            item["source"] = "mobile_base44_chat"
            break
    reminder_tools.save_reminders(reminders)
    return result


async def sync_mobile_event(event: dict) -> None:
    event_id = record_id(event)
    event_type = str(event.get("event_type") or "mobile_message")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    processed_at = datetime.now(ZoneInfo("Europe/Berlin")).isoformat()

    try:
        if event_type == "reminder_created":
            upsert_mobile_reminder(payload)
            if event_id:
                await mobile_base44.update_entity("XeonSyncEvent", event_id, {"status": "processed", "processed_at": processed_at})
            return

        if event_type == "memory_created":
            if event_id:
                await mobile_base44.update_entity("XeonSyncEvent", event_id, {"status": "processed", "processed_at": processed_at})
            return

        if event_type in {"conversation_message", "mobile_message"} and str(payload.get("role") or "").lower() == "assistant":
            if event_id:
                await mobile_base44.update_entity("XeonSyncEvent", event_id, {"status": "processed", "processed_at": processed_at})
            return

        conversation_id = str(payload.get("conversation_id") or "").strip()
        user_text = str(payload.get("text") or payload.get("request") or payload.get("content") or "").strip()
        file_url = str(payload.get("file_url") or "").strip()
        if file_url:
            user_text = f"{user_text}\n\nMobile Datei-URL: {file_url}"
        if not conversation_id or not user_text:
            if event_id:
                await mobile_base44.update_entity("XeonSyncEvent", event_id, {"status": "failed", "processed_at": processed_at})
            return

        if is_shutdown_request(user_text):
            command_id = shutdown_command_id(user_text, "mobile")
            if shutdown_already_executed(user_text, "mobile"):
                final_response = (
                    "Sir, dieser Mobile-Herunterfahren-Befehl wurde bereits ausgefuehrt. "
                    "Ich wiederhole ihn nicht noch einmal, sonst waere das kein Assistent, sondern ein sehr teurer Lichtschalter."
                )
            elif not ALLOW_PC_SHUTDOWN:
                final_response = "PC-Herunterfahren ist in meiner Konfiguration deaktiviert, Sir."
            else:
                schedule_pc_shutdown()
                mark_command_executed(command_id, "shutdown", user_text)
                audit_log.log_action(
                    "SHUTDOWN",
                    {"text": user_text, "source": "mobile", "event_id": event_id, "delay_seconds": PC_SHUTDOWN_DELAY_SECONDS},
                    "scheduled",
                    "Windows shutdown scheduled from mobile",
                )
                final_response = (
                    f"Verstanden, Sir. Ich fahre den PC in {PC_SHUTDOWN_DELAY_SECONDS} Sekunden herunter. "
                    "Dieser Mobile-Befehl ist jetzt als erledigt markiert und wird nicht erneut abgespielt."
                )

            await mobile_base44.create_entity("Message", {
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": final_response,
                "model_used": OPENAI_MODEL_FAST,
                "source": "desktop",
            })
            try:
                await mobile_base44.update_entity("Conversation", conversation_id, {
                    "last_message": final_response[:300],
                    "model_used": OPENAI_MODEL_FAST,
                    "source": "desktop",
                })
            except Exception as exc:
                print(f"[mobile-sync] conversation update failed: {exc}", flush=True)
            if event_id:
                await mobile_base44.update_entity("XeonSyncEvent", event_id, {"status": "processed", "processed_at": processed_at})
            return

        history_result = await mobile_base44.list_entity(
            "Message",
            query={"conversation_id": conversation_id},
            limit=12,
            sort_by="created_date",
        )
        mobile_messages = base44_records(history_result)
        response_input = [
            {
                "role": "assistant" if str(item.get("role")) == "assistant" else "user",
                "content": str(item.get("content") or ""),
            }
            for item in mobile_messages
            if str(item.get("role")) in {"user", "assistant"} and str(item.get("content") or "").strip()
        ][-12:]
        if not response_input or response_input[-1]["role"] != "user":
            response_input.append({"role": "user", "content": user_text})

        if should_store_as_todo(user_text) or todo_tools.is_todo_request(user_text):
            rewritten = await rewrite_todo_text(user_text, source="mobile")
            todo = todo_tools.create_todo(user_text, source="mobile", rewritten_text=rewritten)
            reminder_tools.delete_by_fingerprint(todo.get("fingerprint") or todo_tools.fingerprint(todo.get("text", "")))
            final_response = await generate_todo_ack(todo)
            await mobile_base44.create_entity("Message", {
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": final_response,
                "model_used": OPENAI_MODEL_FAST,
                "source": "desktop",
            })
            try:
                await mobile_base44.update_entity("Conversation", conversation_id, {
                    "last_message": final_response[:300],
                    "model_used": OPENAI_MODEL_FAST,
                    "source": "desktop",
                })
            except Exception as exc:
                print(f"[mobile-sync] conversation update failed: {exc}", flush=True)
            if event_id:
                await mobile_base44.update_entity("XeonSyncEvent", event_id, {"status": "processed", "processed_at": processed_at})
            return

        mobile_reminder = create_mobile_chat_reminder(
            user_text,
            mobile_messages,
            event_id,
            conversation_id,
            reference_time=parse_mobile_created_at(str(event.get("created_date") or "")),
        )
        if mobile_reminder and mobile_reminder.get("ok") and not mobile_reminder.get("duplicate"):
            item = mobile_reminder["reminder"]
            final_response = await generate_reminder_style_text(
                item.get("text", "Ihre Erinnerung"),
                due_at=item.get("due_at", ""),
                source="mobile",
                mode="created",
            )
            await mobile_base44.create_entity("Message", {
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": final_response,
                "model_used": OPENAI_MODEL_FAST,
                "source": "desktop",
            })
            try:
                await mobile_base44.update_entity("Conversation", conversation_id, {
                    "last_message": final_response[:300],
                    "model_used": OPENAI_MODEL_FAST,
                    "source": "desktop",
                })
            except Exception as exc:
                print(f"[mobile-sync] conversation update failed: {exc}", flush=True)
            if event_id:
                await mobile_base44.update_entity("XeonSyncEvent", event_id, {"status": "processed", "processed_at": processed_at})
            return

        reply = await generate_reply(
            response_input,
            get_system_prompt()
            + "\n\nMobile Sync: Antworte als derselbe Desktop-XEON. Behandle Sir wie den Boss: respektvoll, loyal, knapp, mit kontrolliert trockenem Humor. Keine Markdown-Rohdaten, keine API-/Dateipfade vorlesen.",
            max_output_tokens=550,
            route_hint="mobile_base44_sync desktop_answer",
        )
        spoken_text, action = extract_action(reply)
        final_response = clean_human_response(spoken_text or reply)
        if action:
            try:
                action_result = await execute_action(action)
                final_response = clean_human_response(f"{final_response}\n\n{action_result}".strip())
            except Exception as action_exc:
                action_error = clean_human_response(str(action_exc))[:220]
                fallback_text = (
                    final_response
                    or f"Sir, ich habe die mobile Anfrage erhalten, aber die Desktop-Aktion ist fehlgeschlagen: {action_error}."
                )
                if final_response:
                    fallback_text = f"{final_response}\n\nDie Desktop-Aktion ist fehlgeschlagen: {action_error}."
                final_response = clean_human_response(fallback_text)

        if not final_response:
            final_response = "Sir, die mobile Anfrage ist angekommen. Ich habe sie verarbeitet, aber keine verwertbare Antwort erhalten. Das ist unschoen, aber wenigstens ehrlich."

        await mobile_base44.create_entity("Message", {
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": final_response,
            "model_used": OPENAI_MODEL_FAST,
            "source": "desktop",
        })
        try:
            await mobile_base44.update_entity("Conversation", conversation_id, {
                "last_message": final_response[:300],
                "model_used": OPENAI_MODEL_FAST,
                "source": "desktop",
            })
        except Exception as exc:
            print(f"[mobile-sync] conversation update failed: {exc}", flush=True)
        if event_id:
            await mobile_base44.update_entity("XeonSyncEvent", event_id, {"status": "processed", "processed_at": processed_at})
    except Exception as exc:
        print(f"[mobile-sync] event failed: {exc}", flush=True)
        if event_id:
            try:
                await mobile_base44.update_entity("XeonSyncEvent", event_id, {"status": "failed", "processed_at": processed_at})
            except Exception:
                pass


async def sync_recent_mobile_reminder_messages() -> int:
    result = await mobile_base44.list_entity(
        "Message",
        query={},
        limit=40,
        sort_by="-created_date",
    )
    messages = list(reversed(base44_records(result)))
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    created_count = 0
    history: list[dict] = []

    for item in messages:
        created_at = parse_mobile_created_at(str(item.get("created_date") or ""))
        if not created_at or (now - created_at).total_seconds() > 15 * 60:
            history.append(item)
            continue
        if str(item.get("role")) != "user" or str(item.get("source")) != "mobile":
            history.append(item)
            continue

        text = str(item.get("content") or item.get("text") or "").strip()
        conversation_id = str(item.get("conversation_id") or "").strip()
        message_id = record_id(item)
        if not text or not conversation_id:
            history.append(item)
            continue

        result_item = create_mobile_chat_reminder(
            text,
            history + [item],
            f"message:{message_id}",
            conversation_id,
            reference_time=created_at,
        )
        if result_item and result_item.get("ok") and not result_item.get("duplicate"):
            created_count += 1
            reminder = result_item["reminder"]
            print(
                f"[mobile-sync] backfilled reminder from message {message_id}: "
                f"{reminder.get('text')} at {reminder.get('due_at')}",
                flush=True,
            )
        history.append(item)
    return created_count


async def poll_mobile_sync_once() -> int:
    if not MOBILE_SYNC_ENABLED or not mobile_base44.enabled:
        return 0
    result = await mobile_base44.list_entity(
        "XeonSyncEvent",
        query={"status": "pending", "target": "desktop"},
        limit=10,
        sort_by="created_date",
    )
    events = base44_records(result)
    for event in events:
        await sync_mobile_event(event)
    backfilled = await sync_recent_mobile_reminder_messages()
    return len(events) + backfilled


async def mobile_sync_loop() -> None:
    print("[mobile-sync] loop started", flush=True)
    while True:
        try:
            count = await poll_mobile_sync_once()
            if count:
                print(f"[mobile-sync] processed batch size={count}", flush=True)
        except Exception as exc:
            print(f"[mobile-sync] poll failed: {exc}", flush=True)
        await asyncio.sleep(max(5, MOBILE_SYNC_POLL_SECONDS))


async def execute_codex_request(payload: str) -> str:
    if not CODEX_CLI_ENABLED:
        return "Codex-CLI ist in XEON deaktiviert."

    workspace = Path(__file__).resolve().parent
    prompt = (
        "Du bist der technische Vollzugriffs-Agent fuer XEON in diesem lokalen Workspace. "
        "Arbeite autonom, logisch und pragmatisch. Nutze vorhandene Tools, lies Dateien, editiere gezielt, fuehre passende Checks aus und berichte knapp. "
        "Keine Passwoerter, 2FA-Codes, API-Keys oder Zahlungsfreigaben anfordern oder ausgeben. "
        f"Nutzerziel:\n{payload}"
    )
    command = ["codex.cmd", "exec", "--cd", str(workspace), "-m", CODEX_MODEL]
    if CODEX_FULL_ACCESS_ACKNOWLEDGED:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        command.extend(["--sandbox", "workspace-write", "--ask-for-approval", "never"])
    command.append(prompt)

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=CODEX_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return "Codex arbeitet zu lange. Ich habe den Lauf abgebrochen; starten Sie die Aufgabe bei Bedarf kleiner oder konkreter."
    except FileNotFoundError:
        return "Codex CLI ist nicht gefunden. Installieren oder einloggen mit codex.cmd login."
    except Exception as exc:
        return f"Codex konnte nicht gestartet werden: {exc}"

    output = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()
    combined = output if output else error
    if process.returncode != 0 and error:
        combined = f"Codex meldet Fehlercode {process.returncode}:\n{error}\n\n{output}".strip()
    return combined[-12000:] if combined else "Codex ist ohne Ausgabe fertig geworden."


async def execute_shell_request(payload: str) -> str:
    if not SHELL_TOOL_ENABLED:
        return "Shell-Tool ist in XEON deaktiviert."
    if not SHELL_FULL_ACCESS_ACKNOWLEDGED:
        return "Shell-Vollzugriff ist nicht bestaetigt. Setzen Sie shell_full_access_acknowledged in config.json auf true."

    try:
        plan = json.loads(payload) if str(payload).strip().startswith("{") else {"command": str(payload)}
    except json.JSONDecodeError as exc:
        return f"Shell-Befehl konnte nicht gelesen werden: {exc}"

    command = str(plan.get("command", "")).strip()
    if not command:
        return "Shell-Befehl fehlt."
    if pc_tools.is_blocked_system_command(command):
        return "Blockiert: systemkritische Shutdown-/Restart-Befehle werden nicht ueber Shell ausgefuehrt."
    timeout_seconds = int(plan.get("timeout_seconds") or SHELL_TIMEOUT_SECONDS)
    cwd = Path(plan.get("cwd") or Path(__file__).resolve().parent).resolve()

    result = await run_shell_command(command, cwd, timeout_seconds)
    return shell_result_text(result)[-12000:]


async def run_shell_command(command: str, cwd: Path | str | None = None, timeout_seconds: int | None = None) -> dict:
    timeout_seconds = int(timeout_seconds or SHELL_TIMEOUT_SECONDS)
    cwd_path = Path(cwd or Path(__file__).resolve().parent).resolve()
    if pc_tools.is_blocked_system_command(command):
        return {
            "command": command,
            "cwd": str(cwd_path),
            "exit_code": None,
            "timed_out": False,
            "stdout": "",
            "stderr": "Blockiert: systemkritischer Shutdown-/Restart-Befehl.",
        }
    try:
        process = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
            cwd=str(cwd_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return {
            "command": command,
            "cwd": str(cwd_path),
            "exit_code": None,
            "timed_out": True,
            "stdout": "",
            "stderr": f"Shell-Befehl lief laenger als {timeout_seconds} Sekunden und wurde abgebrochen.",
        }
    except Exception as exc:
        return {
            "command": command,
            "cwd": str(cwd_path),
            "exit_code": None,
            "timed_out": False,
            "stdout": "",
            "stderr": f"Shell-Befehl konnte nicht gestartet werden: {exc}",
        }

    output = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()
    return {
        "command": command,
        "cwd": str(cwd_path),
        "exit_code": process.returncode,
        "timed_out": False,
        "stdout": output,
        "stderr": error,
    }


def shell_result_text(result: dict) -> str:
    text = result.get("stdout", "")
    error = result.get("stderr", "")
    if error:
        text = f"{text}\n\nSTDERR:\n{error}".strip()
    if result.get("timed_out"):
        text = f"Timeout\n{text}".strip()
    elif result.get("exit_code"):
        text = f"Exitcode {result.get('exit_code')}\n{text}".strip()
    return text if text else "Shell-Befehl wurde ohne Ausgabe beendet."


async def plan_terminal_step(goal: str, step_index: int, previous_results: list[str], cwd: Path) -> dict:
    history = "\n\n".join(previous_results[-6:]) if previous_results else "Noch keine Terminal-Schritte."
    prompt = f"""Sie sind XEONs Terminal-Agent mit bestaetigtem Vollzugriff auf den lokalen Windows-PC.
Ziel des Nutzers:
{goal}

Workspace:
{cwd}

Schritt:
{step_index}

Bisherige Terminal-Ergebnisse:
{history}

Geben Sie genau ein JSON-Objekt zurueck, ohne Markdown.
Schema:
{{"operation":"shell|done|blocked","command":"PowerShell-Befehl","timeout_seconds":120,"reason":"kurz"}}

Autorisierung:
- Der Nutzer hat Shell-/Terminal-Vollzugriff bestaetigt.
- Sie duerfen PowerShell-Befehle, Builds, Tests, Installationen, Dateioperationen, Git-Leseoperationen, Repo-Analyse, lokale Skripte und lokale Tool-Aufrufe ohne Rueckfrage ausfuehren.
- Sie duerfen mehrschrittig arbeiten wie ein lokaler Coding-Agent: Zustand pruefen, Dateien lesen, Befehle ausfuehren, Fehler interpretieren, naechsten Schritt planen.
- Fragen Sie nicht nach Erlaubnis fuer normale lokale Schritte, wenn sie zum Ziel gehoeren.

Arbeitsregeln:
- Nutzen Sie PowerShell-kompatible Befehle.
- Bevorzugen Sie gezielte, kurze Befehle mit lesbarer Ausgabe.
- Nutzen Sie `rg` wenn verfuegbar fuer Suche; sonst PowerShell-Bordmittel.
- Keine Passwoerter, 2FA-Codes oder API-Keys ausgeben.
- Wenn das Ziel erledigt ist, operation done mit knapper reason.
- Wenn ein externer Login, Passwort, 2FA oder eine fehlende externe Berechtigung noetig ist, operation blocked.
- Sonst genau einen naechsten Shell-Befehl planen."""

    plan_text = await generate_reply(
        [{"role": "user", "content": prompt}],
        "Sie geben ausschliesslich valides JSON fuer XEONs Terminal-Agent zurueck.",
        max_output_tokens=450,
        route_hint="terminal_agent shell powershell codex-like coding task",
    )
    plan_text = plan_text.strip()
    if plan_text.startswith("```"):
        plan_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", plan_text, flags=re.IGNORECASE | re.DOTALL).strip()
    return json.loads(plan_text)


async def execute_terminal_agent(goal: str, ws: WebSocket | None = None, speak: bool = True, max_steps: int | None = None) -> str:
    if not SHELL_TOOL_ENABLED:
        return "Shell-Tool ist in XEON deaktiviert."
    if not SHELL_FULL_ACCESS_ACKNOWLEDGED:
        return "Shell-Vollzugriff ist nicht bestaetigt."
    if AI_PROVIDER != "openai" or not ai:
        return "Terminal-Agent braucht die OpenAI API fuer die mehrschrittige Planung."

    workspace = Path(__file__).resolve().parent
    steps = max(1, min(int(max_steps or SHELL_AGENT_MAX_STEPS), 30))
    results: list[str] = []

    for step_index in range(1, steps + 1):
        if ws:
            await ws.send_json({
                "type": "status",
                "text": f"Terminal-Agent Schritt {step_index}/{steps}...",
                "mode": "Ausfuehren",
                "busy": True,
            })

        try:
            plan = await plan_terminal_step(goal, step_index, results, workspace)
        except Exception as exc:
            return f"Sir, ich konnte den naechsten Terminal-Schritt nicht planen: {exc}"

        operation = str(plan.get("operation", "")).lower()
        reason = str(plan.get("reason", "")).strip()
        if operation == "done":
            return f"Erledigt, Sir. {reason}".strip()
        if operation == "blocked":
            return f"Ich bin im Terminal blockiert, Sir: {reason or 'Externe Eingabe oder Berechtigung erforderlich.'}"
        if operation != "shell":
            results.append(f"{step_index}. Ungueltiger Plan: {json.dumps(plan, ensure_ascii=False)}")
            continue

        command = str(plan.get("command", "")).strip()
        if not command:
            results.append(f"{step_index}. Leerer Shell-Befehl geplant.")
            continue

        timeout_seconds = max(5, min(int(plan.get("timeout_seconds") or SHELL_TIMEOUT_SECONDS), 1800))
        result = await run_shell_command(command, workspace, timeout_seconds)
        audit_log.log_action("SHELL_AGENT", {"command": command, "timeout_seconds": timeout_seconds}, "ok", shell_result_text(result)[:2000])
        compact = shell_result_text(result)[-6000:]
        results.append(
            f"{step_index}. COMMAND:\n{command}\nEXIT={result.get('exit_code')} TIMEOUT={result.get('timed_out')}\nOUTPUT:\n{compact}"
        )

    summary = await generate_reply(
        [{"role": "user", "content": f"Ziel:\n{goal}\n\nTerminal-Schritte:\n" + "\n\n".join(results[-8:])}],
        (
            "Fasse den Stand fuer Sir knapp zusammen. Sage, was erledigt wurde, was offen ist, "
            "und nenne den naechsten konkreten Befehl oder Schritt. Keine sensiblen Daten ausgeben."
        ),
        max_output_tokens=450,
        route_hint="terminal_agent_final_summary",
    )
    return summary


def prepare_speech_text(text: str) -> str:
    speech_text = text.strip()
    if not speech_text:
        return ""

    speech_text = re.sub(r"```[\s\S]*?```", " Den Code sehen Sie im Chat. ", speech_text)
    speech_text = re.sub(r"`([^`]{1,120})`", r"\1", speech_text)
    speech_text = re.sub(r"(?im)^\s*[-*+]\s+", "", speech_text)
    speech_text = re.sub(r"[*_#>\[\]{}|]+", " ", speech_text)
    speech_text = re.sub(r"https?://\S+", " den Link sehen Sie im Chat ", speech_text)
    speech_text = re.sub(
        r"\b[A-Za-z]:\\[^\s,;!?]+",
        " den Pfad sehen Sie im Chat ",
        speech_text,
    )
    speech_text = re.sub(r"\b[\w.-]+\.(py|js|ts|tsx|jsx|json|md|txt|log|html|css|ps1|exe|dll)\b", " die Datei ", speech_text)
    speech_text = re.sub(r"\s+", " ", speech_text).strip()
    speech_text = re.sub(r"(?<!\w)XEON(?!\w)", "Sion", speech_text, flags=re.IGNORECASE)

    replacements = sorted(
        PRONUNCIATION_REPLACEMENTS.items(),
        key=lambda item: len(str(item[0])),
        reverse=True,
    )
    for written, spoken in replacements:
        written_text = str(written)
        if re.match(r"^[A-Za-z0-9]+$", written_text):
            pattern = rf"(?<!\w){re.escape(written_text)}(?!\w)"
        else:
            pattern = re.escape(written_text)
        speech_text = re.sub(pattern, str(spoken), speech_text, flags=re.IGNORECASE)

    return speech_text


def split_speech_chunks(speech_text: str, max_chars: int = 2800) -> list[str]:
    if len(speech_text) <= max_chars:
        return [speech_text]

    chunks = []
    current = ""
    sentences = re.split(r"(?<=[.!?])\s+", speech_text)
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
            continue

        if current:
            chunks.append(current.strip())
            current = ""

        while len(sentence) > max_chars:
            cut = sentence[:max_chars].rsplit(" ", 1)[0].strip()
            if not cut:
                cut = sentence[:max_chars].strip()
            chunks.append(cut)
            sentence = sentence[len(cut):].strip()

        current = sentence

    if current:
        chunks.append(current.strip())
    return chunks


async def synthesize_speech_with_edge(speech_text: str) -> bytes:
    try:
        import edge_tts
    except Exception as exc:
        print(f"  Edge TTS unavailable: {exc}", flush=True)
        return b""

    audio_parts = []
    for index, chunk in enumerate(split_speech_chunks(speech_text), start=1):
        output_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                output_path = tmp.name
            communicate = edge_tts.Communicate(
                chunk,
                EDGE_TTS_VOICE,
                rate=EDGE_TTS_RATE,
                pitch=EDGE_TTS_PITCH,
            )
            await communicate.save(output_path)
            with open(output_path, "rb") as f:
                audio_parts.append(f.read())
            print(
                f"  Edge TTS voice: {EDGE_TTS_VOICE}, chunk {index}, chars: {len(chunk)}, size: {len(audio_parts[-1])}",
                flush=True,
            )
        except Exception as exc:
            print(f"  Edge TTS exception: {exc}", flush=True)
        finally:
            if not output_path:
                continue
            try:
                os.remove(output_path)
            except OSError:
                pass
    return b"".join(audio_parts)


async def synthesize_speech_with_elevenlabs(speech_text: str) -> bytes:
    global tts_disabled_reason, tts_remaining_chars

    if tts_disabled_reason:
        print(f"  TTS skipped: {tts_disabled_reason}", flush=True)
        return b""

    if tts_remaining_chars is None:
        try:
            quota_resp = await http.get(
                "https://api.elevenlabs.io/v1/user/subscription",
                headers={"xi-api-key": ELEVENLABS_API_KEY},
            )
            if quota_resp.status_code == 200:
                quota = quota_resp.json()
                tts_remaining_chars = int(quota.get("character_limit", 0)) - int(quota.get("character_count", 0))
                if tts_remaining_chars < TTS_MIN_REMAINING_CHARS:
                    tts_disabled_reason = f"ElevenLabs low quota ({tts_remaining_chars} chars remaining)"
                    print(f"  TTS skipped: {tts_disabled_reason}", flush=True)
                    return b""
        except Exception as exc:
            print(f"  TTS quota check failed: {exc}", flush=True)

    chunks = []
    if len(speech_text) > 250:
        sentences = re.split(r"(?<=[.!?])\s+", speech_text)
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) > 250 and current:
                chunks.append(current.strip())
                current = sentence
            else:
                current = (current + " " + sentence).strip()
        if current:
            chunks.append(current.strip())
    else:
        chunks = [speech_text]

    audio_parts = []
    for chunk in chunks:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        try:
            resp = await http.post(
                url,
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": chunk,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.85},
                },
            )
            print(f"  TTS chunk status: {resp.status_code}, size: {len(resp.content)}", flush=True)
            if resp.status_code == 200:
                audio_parts.append(resp.content)
                if tts_remaining_chars is not None:
                    tts_remaining_chars = max(0, tts_remaining_chars - len(chunk))
            else:
                print(f"  TTS error body: {resp.text[:200]}", flush=True)
                if resp.status_code in (401, 402) and "quota" in resp.text.lower():
                    tts_disabled_reason = "ElevenLabs quota exceeded"
                    break
        except Exception as e:
            print(f"  TTS EXCEPTION: {e}", flush=True)

    return b"".join(audio_parts)


async def synthesize_speech(text: str) -> bytes:
    speech_text = prepare_speech_text(text)
    if not speech_text:
        return b""

    if TTS_PROVIDER == "edge":
        return await synthesize_speech_with_edge(speech_text)

    return await synthesize_speech_with_elevenlabs(speech_text)


async def execute_action(action: dict) -> str:
    action_type = action["type"]
    payload = action["payload"]

    if action_type == "SEARCH":
        result = await browser_tools.search_and_read(payload)
        if "error" not in result:
            return (
                f"Seite: {result.get('title', '')}\n"
                f"URL: {result.get('url', '')}\n\n"
                f"{result.get('content', '')[:2000]}"
            )
        return f"Suche fehlgeschlagen: {result.get('error', '')}"

    if action_type == "BROWSE":
        result = await browser_tools.visit(payload)
        if "error" not in result:
            return f"Seite: {result.get('title', '')}\n\n{result.get('content', '')[:2000]}"
        return f"Seite nicht erreichbar: {result.get('error', '')}"

    if action_type == "OPEN":
        await browser_tools.open_url(payload)
        return f"Geoeffnet: {payload}"

    if action_type == "INDEED":
        return await browser_tools.indeed_employer(str(payload or "read").lower())

    if action_type == "SCREEN":
        model, _ = select_openai_model(
            [{"role": "user", "content": "Beschreibe den Bildschirm."}],
            "Vision screen description",
            max_output_tokens=300,
            route_hint="screen_vision",
        )
        return await screen_capture.describe_screen(ai, model)

    if action_type == "NEWS":
        news = await browser_tools.fetch_news_deep()
        return news

    if action_type == "BASE44":
        return await execute_base44_request(payload)

    if action_type == "CALENDAR":
        return await execute_calendar_request(payload)

    if action_type == "HUE":
        result = await hue_bluetooth_tools.execute_hue_command(payload)
        audit_log.log_action("HUE", {"payload": payload}, "ok", result)
        return result

    if action_type == "PC":
        result = pc_tools.execute_pc_operation(payload)
        audit_log.log_action("PC", payload, "ok", result)
        return result

    if action_type == "DESKTOP":
        return await execute_desktop_agent(payload)

    if action_type == "CODEX":
        return await execute_codex_request(payload)

    if action_type == "SHELL":
        return await execute_shell_request(payload)

    if action_type == "TERMINAL":
        return await execute_terminal_agent(payload)

    return ""


async def process_message(session_id: str, user_text: str, ws: WebSocket, speak: bool = True, attachments: list[dict] | None = None):
    """Process message and send responses via WebSocket."""
    last_openai_meta.set(None)
    ensure_conversation_loaded(session_id)

    attachment_context = format_attachment_context(attachments)
    effective_user_text = f"{user_text}\n{attachment_context}" if attachment_context else user_text

    if "activate" in user_text.lower():
        refresh_data()

    append_conversation_message(session_id, "user", effective_user_text)
    try:
        asyncio.create_task(learn_from_user_message(effective_user_text, session_id))
    except Exception as exc:
        print(f"[learning-memory] schedule failed: {exc}", flush=True)
    history = conversations[session_id][-CONVERSATION_PROMPT_MESSAGES:]
    lowered = effective_user_text.lower()
    context_frame = {}
    if "activate" not in lowered:
        context_frame = await resolve_message_context(user_text, session_id, attachments)

    if "activate" in lowered:
        weather_context = (
            f"{CITY}: {WEATHER_INFO.get('temp', '?')} Grad, gefuehlt {WEATHER_INFO.get('feels_like', '?')}, "
            f"{WEATHER_INFO.get('description', '')}."
            if isinstance(WEATHER_INFO, dict)
            else "Wetterdaten nicht verfuegbar."
        )
        try:
            text = await generate_startup_greeting_text()
        except Exception as exc:
            print(f"[startup-greeting] fallback: {exc}", flush=True)
            text = (
                f"XEON ist hochgefahren, online und bereit, {USER_ADDRESS}. {CITY} meldet "
                f"{WEATHER_INFO.get('temp', '?')} Grad; die Systeme stehen, die Lage ist ruhig, und ich bin bereit fuer Ihren naechsten Zug."
                if isinstance(WEATHER_INFO, dict)
                else f"XEON ist hochgefahren, online und bereit, {USER_ADDRESS}. Systeme stabil; ich warte auf Ihren naechsten Befehl."
            )
        remember_assistant(session_id, text)
        await ws.send_json({"type": "todos", "items": accountability_items()})
        await send_response(ws, text, speak)
        return

    if is_shutdown_abort(user_text):
        abort_pc_shutdown()
        audit_log.log_action("SHUTDOWN_ABORT", {"text": user_text}, "ok", "shutdown aborted")
        text = "Herunterfahren abgebrochen, Sir."
        remember_assistant(session_id, text)
        await send_response(ws, text, speak)
        return

    if "mobile" in lowered and any(k in lowered for k in ["verbunden", "synchron", "sync", "angebunden", "verbindung"]):
        if MOBILE_SYNC_ENABLED and mobile_base44.enabled:
            text = (
                "Ja, Sir. Desktop-XEON ist mit Mobile-XEON ueber Base44-Sync verbunden. "
                f"Ich pruefe alle {MOBILE_SYNC_POLL_SECONDS} Sekunden mobile Events und schreibe Antworten zurueck in den mobilen Chat. "
                "Wenn dort nur 'synchronisiert' steht, war sehr wahrscheinlich ein Event fehlgeschlagen; diese Fehlerbehandlung ist jetzt robuster."
            )
        elif MOBILE_SYNC_ENABLED:
            text = "Mobile-Sync ist eingeschaltet, Sir, aber die mobile Base44-API ist lokal nicht voll konfiguriert."
        else:
            text = "Mobile-Sync ist lokal deaktiviert, Sir."
        remember_assistant(session_id, text)
        await send_response(ws, text, speak)
        return

    if is_shutdown_request(user_text):
        command_id = shutdown_command_id(user_text, "desktop")
        if shutdown_already_executed(user_text, "desktop"):
            text = (
                "Sir, dieser Herunterfahren-Befehl wurde bereits ausgefuehrt. "
                "Ich wiederhole ihn nicht automatisch. Neuer Befehl, neue Lage."
            )
        elif not ALLOW_PC_SHUTDOWN:
            text = "PC-Herunterfahren ist in meiner Konfiguration deaktiviert, Sir."
        elif PC_SHUTDOWN_REQUIRES_CONFIRMATION and not is_shutdown_confirm(user_text):
            text = "Bestaetigen Sie mit: XEON, bestaetige Herunterfahren."
        else:
            schedule_pc_shutdown()
            mark_command_executed(command_id, "shutdown", user_text)
            audit_log.log_action(
                "SHUTDOWN",
                {"text": user_text, "delay_seconds": PC_SHUTDOWN_DELAY_SECONDS},
                "scheduled",
                "Windows shutdown scheduled",
            )
            text = (
                f"Verstanden, Sir. Ich fahre den PC in {PC_SHUTDOWN_DELAY_SECONDS} Sekunden herunter. "
                "Wenn Sie es stoppen wollen, sagen Sie: Herunterfahren abbrechen."
            )
        remember_assistant(session_id, text)
        await send_response(ws, text, speak)
        return

    if is_hue_request(effective_user_text):
        await ws.send_json({"type": "status", "text": "Philips Hue Bluetooth wird gesteuert...", "mode": "Ausfuehren", "busy": True})
        result = await hue_bluetooth_tools.execute_hue_command(effective_user_text)
        audit_log.log_action("HUE", {"text": effective_user_text}, "ok", result)
        remember_assistant(session_id, result)
        await send_response(ws, result, speak)
        return

    pending_todo = todo_tools.pending_confirmation()
    if pending_todo and attachments:
        await ws.send_json({"type": "status", "text": "XEON mini prueft den Nachweis gegen die Aufgabe...", "mode": "Nachdenken", "busy": True})
        verification = await verify_todo_evidence(
            pending_todo,
            attachments,
            user_text=user_text,
            conversation_context=conversations.get(session_id, []),
        )
        if verification.get("verified"):
            done = todo_tools.mark_done(pending_todo["id"])
            text = verification.get("reply") or f"Nachweis akzeptiert, Sir. Ich markiere erledigt: {done.get('text')}."
        else:
            todo_tools.mark_verification_failed(pending_todo["id"], verification.get("reason", "Nachweis nicht ausreichend."))
            text = verification.get("reply") or "Sir, der Nachweis reicht nicht. Die Aufgabe bleibt offen."
            text = f"{text} Der Aufgaben-Kontext bleibt aktiv; der naechste Anhang wird wieder als Nachweis fuer diese Aufgabe geprueft."
        remember_assistant(session_id, text)
        await ws.send_json({"type": "todos", "items": accountability_items()})
        await send_response(ws, text, speak)
        return

    if pending_todo and (
        todo_tools.is_completion_reply(user_text)
        or context_frame.get("intent") == "todo_claim_done"
    ):
        claimed = todo_tools.mark_claimed_done(pending_todo["id"]) or pending_todo
        try:
            text = await generate_reply(
                [
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "nutzer_sagte": user_text,
                                "aktive_aufgabe": claimed,
                                "letzte_nachrichten": conversations.get(session_id, [])[-8:],
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
                (
                    "Du bist XEON. Sir meldet die aktive Aufgabe als erledigt. "
                    "Bestaetige kontextbewusst, dass es um genau diese Aufgabe geht. "
                    "Markiere sie NICHT final erledigt. Fordere einen passenden Nachweis an und sage, dass XEON mini ihn gegen diese Aufgabe prueft. "
                    "Ton: loyal, direkt, intelligent, Jarvis-artig. Keine Markdown-Zeichen. Maximal zwei Saetze."
                ),
                max_output_tokens=170,
                route_hint="todo_completion_claim_context_check gpt-5.4-mini",
            )
            text = clean_human_response(text)
        except Exception as exc:
            print(f"[todo-claim] fallback: {exc}", flush=True)
            text = (
                f"Zur Kenntnis genommen, Sir: Sie melden erledigt fuer {claimed.get('text')}. "
                "Ich markiere das noch nicht final. Haengen Sie bitte einen Screenshot, ein Foto oder eine passende Datei als Nachweis an; XEON mini prueft das gegen die Aufgabe."
            )
        remember_assistant(session_id, text)
        await ws.send_json({"type": "todos", "items": accountability_items()})
        await send_response(ws, text, speak)
        return

    if pending_todo and any(token in pc_tools.normalize_query(user_text) for token in ["nein", "noch nicht", "spaeter", "spater", "nicht erledigt"]):
        todo_tools.snooze_confirmation(pending_todo["id"])
        text = f"Verstanden, Sir. Dann bleibt offen: {pending_todo.get('text')}. Ich komme darauf zurueck."
        remember_assistant(session_id, text)
        await ws.send_json({"type": "todos", "items": accountability_items()})
        await send_response(ws, text, speak)
        return

    if is_desktop_agent_request(effective_user_text):
        await send_progress(ws, speak, "Desktop-Kontrolle uebernehmen und den naechsten sichtbaren Schritt ausfuehren.")
        result = await execute_desktop_agent(effective_user_text, ws=ws, speak=speak)
        remember_assistant(session_id, result)
        await send_response(ws, result, speak)
        return

    if attachments and any(k in pc_tools.normalize_query(user_text) for k in [
        "analys", "lies", "pruef", "pruefe", "bearbeit", "arbeite", "mach", "konvertier",
        "verschieb", "kopier", "extrahier", "fass", "zusammen", "was ist", "oeffne",
    ]):
        await send_progress(ws, speak, "Anhaenge im Terminal bereitstellen und damit arbeiten.")
        result = await execute_terminal_agent(effective_user_text, ws=ws, speak=speak)
        remember_assistant(session_id, result)
        await send_response(ws, result, speak)
        return

    if is_terminal_agent_request(effective_user_text):
        await send_progress(ws, speak, "Terminal-Vollzugriff nutzen und die Aufgabe mehrschrittig ausfuehren.")
        result = await execute_terminal_agent(effective_user_text, ws=ws, speak=speak)
        remember_assistant(session_id, result)
        await send_response(ws, result, speak)
        return

    if is_pc_control_request(effective_user_text):
        plan = pc_tools.parse_pc_request(effective_user_text)
        if not plan:
            plan = await plan_pc_request(effective_user_text)
        if not plan:
            text = "Sir, diesen PC-Befehl konnte ich nicht eindeutig in eine lokale Aktion uebersetzen."
        else:
            try:
                result = pc_tools.execute_pc_operation(plan)
                audit_log.log_action("PC", plan, "ok", result)
                text = result
            except Exception as e:
                audit_log.log_action("PC", plan, "error", str(e))
                print(f"[xeon] PC action error: {e}", flush=True)
                text = f"Die PC-Aktion ist fehlgeschlagen, Sir: {e}"
        remember_assistant(session_id, text)
        await send_response(ws, text, speak)
        return

    if todo_tools.is_todo_list_request(user_text):
        todos = todo_tools.open_todos()
        if not todos:
            text = "Sir, aktuell sind keine offenen Todo-Aufgaben gespeichert."
        else:
            lines = []
            for item in todos[:12]:
                severity = todo_tools.severity_for(item)
                created = todo_tools.parse_dt(item.get("created_at")).strftime("%d.%m. %H:%M")
                lines.append(f"- {item.get('text')} seit {created}, Stufe {severity}")
            text = "Sir, diese Todo-Aufgaben sind offen:\n" + "\n".join(lines)
        remember_assistant(session_id, text)
        await ws.send_json({"type": "todos", "items": accountability_items()})
        await send_response(ws, text, speak)
        return

    if todo_tools.is_todo_request(user_text) or (reminder_tools.is_reminder_request(user_text) and (should_store_as_todo(user_text) or is_urgent_task_text(user_text))):
        rewritten = await rewrite_todo_text(user_text, source="desktop")
        todo = todo_tools.create_todo(user_text, source="desktop", rewritten_text=rewritten)
        reminder_tools.delete_by_fingerprint(todo.get("fingerprint") or todo_tools.fingerprint(todo.get("text", "")))
        audit_log.log_action("TODO_CREATE", {"source": user_text}, "ok", todo)
        text = await generate_todo_ack(todo)
        if is_urgent_task_text(user_text):
            todo_tools.activate_context(todo["id"], source="urgent")
            text = (
                f"{text} Focus Guard ist ab sofort scharf, Sir. "
                "Diese Aufgabe bleibt im Vordergrund, bis ein Nachweis sauber durch XEON mini geprueft wurde."
            )
            await ws.send_json({
                "type": "focus_guard",
                "task": todo.get("text", ""),
                "text": text,
                "mode": "FOCUS GUARD",
            })
            try:
                asyncio.create_task(hue_bluetooth_tools.start_focus_guard_flash(10.0))
            except Exception as exc:
                print(f"[urgent-focus-hue] flash start failed: {exc}", flush=True)
        remember_assistant(session_id, text)
        await ws.send_json({"type": "todos", "items": accountability_items()})
        await send_response(ws, text, speak)
        return

    if is_reminder_list_request(user_text):
        reminders = reminder_tools.pending_reminders(limit=10)
        if not reminders:
            text = "Sir, aktuell sind keine offenen lokalen Erinnerungen gespeichert."
        else:
            lines = [
                f"- {item.get('text', 'Erinnerung')} am {reminder_tools.format_due(item['due_at'])}"
                for item in reminders
            ]
            text = "Sir, diese Erinnerungen sind offen:\n" + "\n".join(lines)
        remember_assistant(session_id, text)
        await send_response(ws, text, speak)
        return

    if reminder_tools.is_reminder_request(user_text):
        result = reminder_tools.create_reminder(user_text)
        if not result.get("ok"):
            text = result["error"]
        else:
            item = result["reminder"]
            audit_log.log_action("REMINDER_CREATE", {"source": user_text, "due_at": item["due_at"]}, "ok", item["text"])
            text = await generate_reminder_style_text(
                item.get("text", "Ihre Erinnerung"),
                due_at=item.get("due_at", ""),
                source="desktop",
                mode="created",
            )
        remember_assistant(session_id, text)
        await ws.send_json({"type": "todos", "items": accountability_items()})
        await send_response(ws, text, speak)
        return

    if "lagebericht" in lowered:
        await send_progress(ws, speak, "Lagebericht: Kalender, MySupplieX und operative Signale werden zusammengefuehrt.")
        await ws.send_json({"type": "status", "text": "Kalender und MySupplieX werden analysiert...", "mode": "Ausfuehren"})
        try:
            report = await execute_lagebericht()
        except Exception as e:
            print(f"[xeon] Lagebericht error: {e}", flush=True)
            report = "Der Lagebericht konnte gerade nicht vollstaendig erstellt werden, Sir. Ich bleibe online und kann MySupplieX oder Kalender getrennt pruefen."
        remember_assistant(session_id, report)
        await send_response(ws, report, speak)
        return

    if any(k in lowered for k in ["nachrichten", "nachrrichten", "news", "weltgeschehen", "welt news"]):
        await ws.send_json({
            "type": "news_hud",
            "visible": True,
            "items": ["Tuerkei", "China", "Deutschland", "USA", "Suez", "Tehran/Hormus", "Rotes Meer", "Russland", "Ukraine", "Indien", "Rotterdam", "Singapur"],
        })
        await ws.send_json({"type": "status", "text": "Deep Research laeuft: globale Quellen, Handelsrouten, Regulierung und Lieferketten werden abgeglichen...", "mode": "Ausfuehren", "busy": True})
        intro_line = "Sir, die globale Deep-Research-Suche laeuft. Ich pruefe mehrere frische Nachrichtencluster, filtere Wiederholungen raus und suche die Signale, die fuer MySupplieX wirklich zaehlen."
        await send_response(ws, intro_line, speak)
        result = await execute_action({"type": "NEWS", "payload": ""})
        summary = await deliver_synchronized_news(ws, speak, result)
        remember_assistant(session_id, summary)
        return

    if "indeed" in lowered and any(k in lowered for k in ["bewerber", "arbeitgeber", "nachricht", "messages", "applicants", "kandidaten"]):
        await send_progress(ws, speak, "Indeed Arbeitgeberkonto oeffnen und Bewerberansicht lesen.")
        await ws.send_json({"type": "status", "text": "Indeed Arbeitgeberkonto wird geoeffnet...", "mode": "Ausfuehren"})
        result = await execute_action({"type": "INDEED", "payload": "read"})
        summary = await generate_reply(
            [{"role": "user", "content": f"Fasse diese Indeed-Arbeitgeberansicht knapp zusammen. Wenn Login noetig ist, sage das direkt:\\n\\n{result}"}],
            "Du bist XEON. Antworte kurz, menschlich und ohne Markdown-Zeichen. Keine Pfade oder technischen Details vorlesen.",
            max_output_tokens=250,
            route_hint="indeed_summary fast structured task",
        )
        remember_assistant(session_id, summary)
        await send_response(ws, summary, speak)
        return

    if "mysuppliex" in lowered and any(k in lowered for k in ["orders", "order", "status", "lage", "system", "zeig"]):
        await send_progress(ws, speak, "MySupplieX Admin-Daten pruefen und knapp einordnen.")
        await ws.send_json({"type": "status", "text": "MySupplieX Admin-Daten werden gelesen...", "mode": "Ausfuehren"})
        payload = '{"operation":"health_snapshot"}' if "lage" in lowered or "system" in lowered else '{"operation":"list","entity":"Order","limit":10,"sort_by":"-created_date"}'
        result = await execute_base44_request(payload)
        summary = await generate_reply(
            [{"role": "user", "content": result[:8000]}],
            (
                "Fasse diese MySupplieX-Admin-Daten fuer Sir als Unternehmensberater zusammen. "
                "Keine JSON-Rohdaten, keine IDs, keine technischen Felder. Sage nur, was operativ relevant ist, "
                "und nenne konkrete naechste Schritte."
            ),
            max_output_tokens=450,
            route_hint="mysuppliex_summary fast structured task",
        )
        remember_assistant(session_id, summary)
        await send_response(ws, summary, speak)
        return

    if is_calendar_request(user_text):
        if is_calendar_write_request(user_text):
            lead = "Ich aktualisiere Ihren Kalender, Sir."
        else:
            lead = "Ich pruefe Ihren Kalender, Sir."
        await send_progress(ws, speak, lead)
        await ws.send_json({"type": "status", "text": "Google Kalender wird verarbeitet...", "mode": "Ausfuehren"})
        try:
            result = await execute_calendar_request(user_text)
        except Exception as e:
            print(f"[xeon] Calendar error: {e}", flush=True)
            result = (
                "Sir, der Kalenderzugriff ist gerade nicht sauber erreichbar. "
                "XEON nutzt die direkte Google Calendar API, nicht den Codex-Connector. "
                "Pruefen Sie data/google-oauth-client-secret.json und starten Sie danach einen Kalenderbefehl, "
                "damit ich den Google-Login oeffnen und das Token lokal speichern kann."
            )
        remember_assistant(session_id, result)
        await send_response(ws, result, speak)
        return

    if "activate" not in lowered and likely_slow_request(effective_user_text):
        await send_progress(ws, speak, effective_user_text)
        await ws.send_json({"type": "status", "text": "XEON fuehrt aus...", "mode": "Ausfuehren"})

    response_input = [{"role": item["role"], "content": item["content"]} for item in history]
    try:
        reply = await generate_reply(response_input, get_system_prompt(), max_output_tokens=400, route_hint=effective_user_text)
    except Exception as e:
        print(f"[xeon] Denkmodul error: {e}", flush=True)
        error_summary = clean_human_response(str(e))[:180] or "keine verwertbare Antwort"
        reply = f"Sir, die OpenAI-API hat gerade nicht sauber geantwortet: {error_summary}. Ich bleibe online; das ist laestig, aber kein Drama."
    print(f"  LLM raw: {reply[:200]}", flush=True)
    spoken_text, action = extract_action(reply)

    if spoken_text:
        print(f"  XEON: {spoken_text[:80]}", flush=True)
        remember_assistant(session_id, spoken_text)
        await send_response(ws, spoken_text, speak)

    if action:
        print(f"  Action: {action['type']} -> {action['payload'][:100]}", flush=True)

        if action["type"] == "SCREEN":
            await send_progress(ws, speak, "Bildschirm ansehen und kurz beschreiben.")

        try:
            action_result = await execute_action(action)
            print(f"  Result: {action_result}", flush=True)
        except Exception as e:
            print(f"  Action error: {e}", flush=True)
            action_result = f"Fehler: {e}"

        if action["type"] == "OPEN":
            return

        if action_result and "fehlgeschlagen" not in action_result:
            summary = await generate_reply(
                [{"role": "user", "content": f"Fasse zusammen:\n\n{action_result}"}],
                (
                    "Du bist XEON. Fasse die folgenden Informationen KURZ auf Deutsch "
                    f"zusammen, maximal 3 Saetze, im XEON-Stil. Sprich den Nutzer als {USER_ADDRESS} "
                    "an. KEINE Tags in eckigen Klammern. KEINE ACTION-Tags."
                ),
                max_output_tokens=250,
                route_hint="short_action_summary",
            )
            summary, _ = extract_action(summary)
        else:
            summary = f"Das hat leider nicht funktioniert, {USER_ADDRESS}."

        remember_assistant(session_id, summary)
        await send_response(ws, summary, speak)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_websockets.add(ws)
    session_id = DEFAULT_SESSION_ID
    ensure_conversation_loaded(session_id)
    print("[xeon] Client connected", flush=True)

    try:
        while True:
            data = await ws.receive_json()
            user_text = data.get("text", "").strip()
            if not user_text:
                continue

            print(f"  You:    {user_text}", flush=True)
            speak = bool(data.get("speak", True))
            attachments = data.get("attachments") or []
            await ws.send_json({"type": "status", "text": "XEON denkt nach...", "mode": "Nachdenken", "busy": True})
            try:
                await process_message(session_id, user_text, ws, speak, attachments=attachments)
            finally:
                try:
                    await ws.send_json({"type": "status", "text": "", "mode": "Wartet auf Befehl", "busy": False})
                except Exception:
                    break

    except WebSocketDisconnect:
        active_websockets.discard(ws)


@app.post("/api/transcribe")
async def transcribe_endpoint(request: Request):
    audio_bytes = await request.body()
    if len(audio_bytes) < 1500:
        return {"text": ""}

    suffix = ".webm"
    content_type = request.headers.get("content-type", "")
    if "wav" in content_type:
        suffix = ".wav"
    elif "mp4" in content_type or "m4a" in content_type:
        suffix = ".m4a"

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="xeon_stt_", suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        text = transcribe_audio_file(tmp_path)
        return {"text": text}
    except Exception as exc:
        print(f"[stt] error: {exc}", flush=True)
        return {"text": "", "error": str(exc)}
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@app.post("/api/attachments")
async def attachments_endpoint(request: Request):
    form = await request.form()
    files = form.getlist("files")
    paths = [str(value) for value in form.getlist("paths")]
    if not files:
        return {"attachments": []}

    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    batch_root = (ATTACHMENT_ROOT / batch_id).resolve()
    batch_root.mkdir(parents=True, exist_ok=True)
    attachments = []

    for index, upload in enumerate(files):
        filename = getattr(upload, "filename", "") or f"attachment-{index + 1}"
        relative_path = paths[index] if index < len(paths) and paths[index] else filename
        safe_relative = sanitize_attachment_path(relative_path, filename)
        target = (batch_root / safe_relative).resolve()
        if not str(target).startswith(str(batch_root)):
            target = batch_root / sanitize_attachment_path(filename, f"attachment-{index + 1}")
        target.parent.mkdir(parents=True, exist_ok=True)

        size = 0
        with open(target, "wb") as output:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                output.write(chunk)

        mime_type = getattr(upload, "content_type", "") or mimetypes.guess_type(str(target))[0] or ""
        item = {
            "original_name": filename,
            "relative_path": str(safe_relative),
            "path": str(target),
            "size": size,
            "mime_type": mime_type,
        }
        preview = attachment_preview(target, mime_type)
        if preview:
            item["preview"] = preview
        attachments.append(item)

    return {"root": str(batch_root), "attachments": attachments}


def pick_local_paths_dialog(mode: str) -> list[str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if mode == "folder":
            selected = filedialog.askdirectory(title="Ordner fuer XEON auswaehlen")
            return [selected] if selected else []
        selected_files = filedialog.askopenfilenames(title="Dateien fuer XEON auswaehlen")
        return list(selected_files)
    finally:
        root.destroy()


@app.post("/api/local-attachments")
async def local_attachments_endpoint(request: Request):
    payload = await request.json()
    mode = str(payload.get("mode", "files")).lower()
    paths = payload.get("paths")
    if isinstance(paths, list) and paths:
        selected_paths = [str(path) for path in paths]
    else:
        selected_paths = await asyncio.to_thread(pick_local_paths_dialog, "folder" if mode == "folder" else "files")
    return {"attachments": [local_attachment_from_path(path) for path in selected_paths if path]}


@app.post("/api/hue/intro")
async def hue_intro_endpoint():
    return {"ok": True, "message": "Hue intro lighting disabled"}


@app.post("/api/hue/news/start")
async def hue_news_start_endpoint():
    try:
        result = await hue_bluetooth_tools.start_news_pulse()
        audit_log.log_action("HUE_NEWS_START", {"color": "rot", "pulse": True}, "ok", result)
        return {"ok": True, "message": result}
    except Exception as exc:
        audit_log.log_action("HUE_NEWS_START", {"color": "rot", "pulse": True}, "error", str(exc))
        return {"ok": False, "error": str(exc)}


@app.post("/api/hue/news/stop")
async def hue_news_stop_endpoint():
    try:
        result = await hue_bluetooth_tools.stop_news_pulse()
        audit_log.log_action("HUE_NEWS_STOP", {"restore": True}, "ok", result)
        return {"ok": True, "message": result}
    except Exception as exc:
        audit_log.log_action("HUE_NEWS_STOP", {"restore": True}, "error", str(exc))
        return {"ok": False, "error": str(exc)}


@app.get("/api/usage")
async def usage_endpoint():
    return await response_meta()


@app.get("/api/todos")
async def todos_endpoint():
    return {"items": accountability_items()}


def accountability_items() -> list[dict]:
    migrate_tasklike_reminders_to_todos()
    todo_tools.restore_rejected_evidence_context()
    items = []
    for item in todo_tools.open_todos():
        copy = dict(item)
        copy["kind"] = "todo"
        copy["severity"] = todo_tools.severity_for(copy)
        due_badge = ""
        if copy.get("due_at"):
            try:
                due = datetime.fromisoformat(str(copy.get("due_at")).replace("Z", "+00:00"))
                if due.tzinfo is None:
                    due = due.replace(tzinfo=ZoneInfo("Europe/Berlin"))
                due = due.astimezone(ZoneInfo("Europe/Berlin"))
                now = datetime.now(ZoneInfo("Europe/Berlin"))
                if due <= now:
                    due_badge = "ueberfaellig"
                elif due.date() == now.date():
                    due_badge = "heute faellig"
                else:
                    due_badge = "geplant"
            except Exception:
                due_badge = ""
        if copy.get("awaiting_evidence"):
            copy["badge"] = f"nachweis offen{(' - ' + due_badge) if due_badge else ''}"
        elif copy.get("awaiting_confirmation"):
            copy["badge"] = f"antwort offen{(' - ' + due_badge) if due_badge else ''}"
        elif copy.get("due_at"):
            copy["badge"] = due_badge or copy["severity"]
        else:
            copy["badge"] = copy["severity"]
        items.append(copy)
    for item in reminder_tools.pending_reminders(limit=50):
        copy = dict(item)
        copy["kind"] = "reminder"
        copy["id"] = f"reminder:{copy.get('id')}"
        copy["severity"] = "strict" if copy.get("badge") in {"ueberfaellig", "aufgefordert"} else "normal"
        items.append(copy)
    items.sort(key=lambda item: item.get("due_at") or item.get("created_at") or "")
    return items


@app.get("/api/reminders")
async def reminders_endpoint():
    return {"items": reminder_tools.pending_reminders(limit=20)}


@app.post("/api/todos")
async def create_todo_endpoint(request: Request):
    payload = await request.json()
    raw_text = str(payload.get("text") or "").strip()
    source = str(payload.get("source") or "api")
    if not raw_text:
        return {"ok": False, "error": "text fehlt"}
    rewritten = await rewrite_todo_text(raw_text, source=source)
    todo = todo_tools.create_todo(raw_text, source=source, rewritten_text=rewritten)
    text = await generate_todo_ack(todo)
    return {"ok": True, "todo": todo, "text": text}


@app.post("/api/todos/{todo_id}/done")
async def done_todo_endpoint(todo_id: str):
    todo = todo_tools.mark_claimed_done(todo_id)
    return {
        "ok": bool(todo),
        "requires_evidence": True,
        "todo": todo,
        "items": todo_tools.open_todos(),
    }


@app.get("/api/mobile-sync")
async def mobile_sync_status_endpoint():
    return {
        "enabled": MOBILE_SYNC_ENABLED,
        "configured": mobile_base44.enabled,
        "poll_seconds": MOBILE_SYNC_POLL_SECONDS,
        "entities": MOBILE_BASE44_ENTITIES,
    }


@app.post("/api/mobile-sync/poll")
async def mobile_sync_poll_endpoint():
    count = await poll_mobile_sync_once()
    return {"processed": count}


@app.post("/api/window/{command}")
async def window_command_endpoint(command: str):
    command = command.lower().strip()
    if command == "close":
        script = Path(__file__).resolve().parent / "scripts" / "close-session.ps1"
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"ok": True, "command": command}
    if command in {"minimize", "tray"}:
        ps = (
            "$sig='[DllImport(\"user32.dll\")] public static extern bool ShowWindowAsync(IntPtr hWnd,int nCmdShow);';"
            "Add-Type -MemberDefinition $sig -Name Win32ShowWindowAsync -Namespace XEON;"
            "$p=Get-Process | Where-Object { $_.MainWindowTitle -like '*XEON*' -or $_.Path -like '*XEON*' } | Select-Object -First 1;"
            "if($p){[XEON.Win32ShowWindowAsync]::ShowWindowAsync($p.MainWindowHandle,2)|Out-Null}"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"ok": True, "command": command}
    return {"ok": False, "error": "unknown window command"}


async def build_intro_prewarm(prewarm_id: str, speak: bool = True):
    intro_prewarm_cache[prewarm_id] = {"status": "running", "created_at": time.time()}
    try:
        refresh_data()
        text = await generate_startup_greeting_text()
        audio = await synthesize_speech(text) if speak else b""
        intro_prewarm_cache[prewarm_id] = {
            "status": "ready",
            "created_at": time.time(),
            "text": clean_human_response(text),
            "audio": base64.b64encode(audio).decode("utf-8") if audio else "",
            "meta": await response_meta(),
        }
    except Exception as exc:
        intro_prewarm_cache[prewarm_id] = {
            "status": "error",
            "created_at": time.time(),
            "error": clean_human_response(str(exc))[:300],
        }


@app.post("/api/intro-prewarm")
async def intro_prewarm_endpoint(payload: IntroPrewarmPayload):
    prewarm_id = payload.id.strip() or uuid.uuid4().hex
    cached = intro_prewarm_cache.get(prewarm_id)
    if not cached or cached.get("status") in {"error"}:
        asyncio.create_task(build_intro_prewarm(prewarm_id, speak=payload.speak))
    return {"id": prewarm_id, "status": intro_prewarm_cache.get(prewarm_id, {}).get("status", "running")}


@app.get("/api/intro-prewarm/{prewarm_id}")
async def intro_prewarm_result_endpoint(prewarm_id: str):
    now = time.time()
    for key, item in list(intro_prewarm_cache.items()):
        if now - float(item.get("created_at", now)) > 300:
            intro_prewarm_cache.pop(key, None)
    return intro_prewarm_cache.get(prewarm_id, {"status": "missing"})


@app.on_event("startup")
async def start_mobile_sync_task():
    migrate_tasklike_reminders_to_todos()
    todo_tools.restore_rejected_evidence_context()
    if STT_PROVIDER == "faster_whisper":
        asyncio.create_task(asyncio.to_thread(get_whisper_model))
    if MOBILE_SYNC_ENABLED and mobile_base44.enabled:
        asyncio.create_task(mobile_sync_loop())
    elif MOBILE_SYNC_ENABLED:
        print("[mobile-sync] enabled but mobile Base44 URL/API key missing", flush=True)
    asyncio.create_task(todo_followup_loop())


async def todo_followup_loop():
    await asyncio.sleep(12)
    while True:
        try:
            todo = todo_tools.due_followup()
            if todo and active_websockets:
                marked = todo_tools.mark_followed_up(todo["id"]) or todo
                text = await generate_todo_followup(marked)
                for ws in list(active_websockets):
                    try:
                        await ws.send_json({"type": "todo_toast", "todo": marked, "text": text})
                        await send_spoken(ws, text)
                        await ws.send_json({"type": "todos", "items": accountability_items()})
                    except Exception:
                        active_websockets.discard(ws)
        except Exception as exc:
            print(f"[todo-followup] loop error: {exc}", flush=True)
        await asyncio.sleep(random.randint(180, 420))


@app.post("/notify")
async def notify(payload: NotifyPayload):
    text = payload.text
    focus_task = ""
    if payload.todo_id:
        active = todo_tools.activate_context(payload.todo_id, payload.source or "notify")
        if active:
            focus_task = str(active.get("text") or "")
            try:
                text = await generate_todo_followup(active)
            except Exception as exc:
                print(f"[notify] gpt followup fallback: {exc}", flush=True)
    dead = []
    for ws in list(active_websockets):
        try:
            if (payload.source or "").lower() == "focus_guard":
                try:
                    asyncio.create_task(hue_bluetooth_tools.start_focus_guard_flash(10.0))
                except Exception as exc:
                    print(f"[focus-guard-hue] flash start failed: {exc}", flush=True)
                await ws.send_json({
                    "type": "focus_guard",
                    "task": focus_task,
                    "text": text,
                    "mode": "FOCUS GUARD",
                })
            if payload.speak:
                await send_spoken(ws, text)
            else:
                await ws.send_json({"type": "response", "text": clean_human_response(text), "meta": await response_meta(), "audio": ""})
        except Exception:
            dead.append(ws)
    for ws in dead:
        active_websockets.discard(ws)
    return {"sent": len(active_websockets) - len(dead)}


@app.post("/api/reminder-phrase")
async def reminder_phrase(payload: ReminderPhrasePayload):
    text = await generate_reminder_style_text(
        payload.text,
        due_at=payload.due_at.strip(),
        source=payload.source,
        mode="due",
    )
    return {"text": text, "model": OPENAI_MODEL_FAST}


@app.post("/api/todo-followup-phrase")
async def todo_followup_phrase(request: Request):
    payload = await request.json()
    todo = payload.get("todo") if isinstance(payload, dict) else {}
    if not isinstance(todo, dict):
        todo = {"text": str(todo or "offene Aufgabe")}
    text = await generate_todo_followup(todo)
    return {"text": text, "model": OPENAI_MODEL_FAST}


app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend")),
    name="static",
)


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "index.html"))


@app.get("/intro")
async def serve_intro():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "intro.html"))


@app.get("/media/intro-video")
async def serve_intro_video():
    video_path = Path(r"C:\Users\User\Downloads\Intro Video XEON.mp4")
    if not video_path.exists():
        return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "index.html"))
    return FileResponse(str(video_path), media_type="video/mp4")


if __name__ == "__main__":
    import uvicorn

    print("=" * 50, flush=True)
    print("  XEON V2 Server", flush=True)
    print("  http://localhost:8340", flush=True)
    print("=" * 50, flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8340)


