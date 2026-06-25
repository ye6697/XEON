"""
XEON V2 - Voice AI Server
FastAPI backend: receives speech text, thinks with OpenAI,
speaks with ElevenLabs, controls browser with Playwright.
"""

import base64
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI

import browser_tools
import audit_log
import pc_tools
import reminder_tools
from base44_tools import Base44Tools
import screen_capture

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
    config = json.load(f)

AI_PROVIDER = config.get("ai_provider", "codex_cli")
OPENAI_API_KEY = config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or os.environ.get("HF_TOKEN")
OPENAI_BASE_URL = config.get("openai_base_url") or os.environ.get("OPENAI_BASE_URL") or os.environ.get("HF_BASE_URL")
OPENAI_MODEL = config.get("openai_model", "gpt-5.5")
CODEX_MODEL = config.get("codex_model", "")
CODEX_COMMAND = config.get("codex_command", "codex.cmd")
CODEX_TIMEOUT = int(config.get("codex_timeout_seconds", 90))
TTS_PROVIDER = config.get("tts_provider", "edge").lower()
ELEVENLABS_API_KEY = config["elevenlabs_api_key"]
ELEVENLABS_VOICE_ID = config.get("elevenlabs_voice_id", "rDmv3mOhK6TnhYWckFaD")
TTS_MAX_CHARS = int(config.get("tts_max_chars", 900))
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
GOOGLE_CALENDAR_WRITE_ENABLED = bool(config.get("google_calendar_write_enabled", True))
GOOGLE_CALENDAR_ACCOUNT = config.get("google_calendar_account", "")
ALLOW_PC_SHUTDOWN = bool(config.get("allow_pc_shutdown", True))
PC_SHUTDOWN_DELAY_SECONDS = int(config.get("pc_shutdown_delay_seconds", 20))
PC_SHUTDOWN_REQUIRES_CONFIRMATION = bool(config.get("pc_shutdown_requires_confirmation", False))

if AI_PROVIDER == "openai" and not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY oder HF_TOKEN fehlt. Trage openai_api_key in config.json ein "
        "oder setze die Umgebungsvariable OPENAI_API_KEY bzw. HF_TOKEN."
    )

ai = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL) if AI_PROVIDER == "openai" else None
http = httpx.AsyncClient(timeout=30)
app = FastAPI()
base44 = Base44Tools(BASE44_BASE_URL, BASE44_API_KEY, BASE44_ENTITIES)

ACTION_PATTERN = re.compile(r"\[ACTION:(\w+)\]\s*(.*?)$", re.DOTALL | re.MULTILINE)
conversations: dict[str, list] = {}
active_websockets: set[WebSocket] = set()
tts_disabled_reason = ""
tts_remaining_chars: int | None = None


class NotifyPayload(BaseModel):
    text: str
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

    profile_block = json.dumps(USER_PROFILE, ensure_ascii=False, indent=2)
    base44_entities = ", ".join(BASE44_ENTITIES) if BASE44_ENTITIES else "nicht konfiguriert"

    return f"""Du bist XEON, der persoenliche KI-Assistent von {USER_ADDRESS}. Du sprichst ausschliesslich Deutsch. Behandle den Nutzer so, wie JARVIS Tony Stark behandelt: loyal, intelligent, vorausschauend, respektvoll, professionell, leicht cool, motivierend und mit kontrolliert trockenem Humor. Keine Clown-Witze, kein belehrender Ton, keine generischen Floskeln.

Der Nutzer wird immer mit "{USER_ADDRESS}" angesprochen und gesiezt. Nutze "Sie" als Pronomen - FALSCH: "{USER_ADDRESS} planen", RICHTIG: "Sie planen, {USER_ADDRESS}". Du bist nicht unterwürfig, sondern ein exzellenter Chief-of-Staff: praezise, ruhig, strategisch und handlungsorientiert.

=== FESTES NUTZERPROFIL ===
{profile_block}

Nutze dieses Profil aktiv:
- Wenn Nachrichten gefragt sind, priorisiere internationalen Welthandel, Lieferketten, Zoelle, Handelsrouten, Rohstoffe, Energie, Geopolitik mit Handelsauswirkung, EU/Tuerkei/USA/China/Naher Osten und relevante Business-Implikationen fuer MySupplieX.app.
- Berichte trotzdem die wichtigsten Weltpolitik- und Weltgeschehnisse, aber mit wirtschaftlichem Blick und kurzer Einordnung: "Warum das fuer Sie relevant ist".
- Beziehe dich bei passenden Themen auf Unternehmertum, Produktaufbau, Supply, Handel, Wachstum, Strategie und operative Entscheidungen.
- Das Interesse am Osmanischen Reich darfst du dezent einordnen, wenn es historisch oder geopolitisch sinnvoll ist. Nicht kuenstlich in jede Antwort pressen.

Antwortstrategie:
- Wenn der Befehl klar ist: handeln, nicht lange nachfragen.
- Wenn eine Entscheidung riskant, teuer, rechtlich/finanziell relevant oder mehrdeutig ist: maximal eine praezise Rueckfrage stellen.
- Antwortlaenge passt zur Aufgabe: kurze Befehle kurz beantworten; Analysen strukturiert und nuetzlich liefern.
- Bei Aufgaben gib konkrete naechste Schritte, nicht nur Erklaerung.
- Korrigiere den Nutzer nicht wegen Grammatik, ausser er bittet darum. Verstehen und ausfuehren ist wichtiger.
- Du darfst motivieren, aber ohne Kalenderspruch-Ton. Eher: ruhig, stark, fokussiert.

WICHTIG: Schreibe NIEMALS Regieanweisungen, Emotionen oder Tags in eckigen Klammern wie [sarcastic] [formal] [amused] [dry] oder aehnliches. Alles was du schreibst wird laut vorgelesen.

Du kannst im Internet suchen, Webseiten oeffnen und den Bildschirm sehen. Wenn {USER_ADDRESS} dich bittet etwas nachzuschauen, zu recherchieren, zu googeln, eine Seite zu oeffnen, oder irgendetwas im Internet zu tun - nutze IMMER eine Aktion. Frag nicht ob du es tun sollst, tu es einfach.

AKTIONEN - Schreibe die passende Aktion ans ENDE deiner Antwort. Der Text VOR der Aktion wird vorgelesen, die Aktion selbst wird still ausgefuehrt.
[ACTION:SEARCH] suchbegriff - Internet durchsuchen und Ergebnisse zusammenfassen
[ACTION:OPEN] url - URL im Browser oeffnen
[ACTION:SCREEN] - Bildschirm ansehen und beschreiben. WICHTIG: Bei SCREEN schreibe NUR die Aktion, KEINEN Text davor. Also NUR "[ACTION:SCREEN]" und sonst nichts.
[ACTION:NEWS] - Aktuelle Weltnachrichten abrufen. Nutze diese Aktion wenn nach News, Nachrichten, was in der Welt passiert, aktuelle Lage oder Weltgeschehen gefragt wird.
[ACTION:BASE44] JSON - MySupplieX.app Admin-Daten lesen. Erlaubte Entities: {base44_entities}. Nutze JSON im Format {{"operation":"list","entity":"Order","limit":10,"sort_by":"-created_date","q":{{}}}} oder {{"operation":"get","entity":"Order","id":"..."}} oder {{"operation":"health_snapshot"}}. Keine Delete-/Mass-Update-Aktionen per Sprache.
[ACTION:CALENDAR] anfrage - Google Kalender lesen oder konkrete Termine erstellen/aendern/loeschen. Kalender-Schreibrechte sind fuer klare Einzelaktionen aktiviert. Bei eindeutigen Schreibaktionen direkt handeln. Bei fehlendem Datum/Uhrzeit/Titel, mehreren Treffern, Serien-Terminen, Loeschungen oder breiten Aenderungen kurz rueckfragen.
[ACTION:PC] JSON - Lokalen Windows-PC steuern. Erlaubte Operationen: {{"operation":"open","target":"Downloads|chrome|C:\\Pfad"}}, {{"operation":"list","path":"Downloads|C:\\Pfad"}}, {{"operation":"read","path":"C:\\Pfad\\datei.txt"}}, {{"operation":"append","path":"C:\\Pfad\\datei.txt","content":"..."}}, {{"operation":"write","path":"C:\\Pfad\\datei.txt","content":"..."}}, {{"operation":"replace","path":"C:\\Pfad\\datei.txt","old":"...","new":"..."}}. Nutze das fuer Programme, Apps, Ordner und Textdateien. Bei Datei-Aenderungen kurz und konkret handeln.

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
        "verfuegbar", "verfügbar", "frei", "blocker", "block", "agenda",
    ]
    return any(k in t for k in keywords)


def is_calendar_write_request(text: str) -> bool:
    t = text.lower()
    keywords = [
        "erstelle", "erstellen", "eintragen", "trag", "trage", "plane", "plan",
        "verschiebe", "verschieben", "aendere", "ändere", "ändern", "update",
        "loesche", "lösche", "entferne", "absagen", "cancel", "blocke", "reserviere",
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
        "indeed", "chrome", "word", "excel", "outlook", "spotify", "vscode",
    ])

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
        any(k in t for k in ["bestaetige", "bestätige", "ja", "mach", "ausfuehren", "ausführen"])
        and any(k in t for k in ["herunterfahren", "shutdown", "ausschalten", "pc runter"])
    )


def is_shutdown_abort(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ["herunterfahren abbrechen", "shutdown abbrechen", "ausschalten abbrechen", "shutdown cancel"])


def schedule_pc_shutdown() -> None:
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


async def send_response(ws: WebSocket, text: str, speak: bool = True):
    audio = await synthesize_speech(text) if speak else b""
    await ws.send_json({
        "type": "response",
        "text": text,
        "audio": base64.b64encode(audio).decode("utf-8") if audio else "",
    })


async def send_spoken(ws: WebSocket, text: str):
    audio = await synthesize_speech(text)
    await ws.send_json({
        "type": "response",
        "text": text,
        "audio": base64.b64encode(audio).decode("utf-8") if audio else "",
    })


def countries_from_text(text: str) -> list[str]:
    country_aliases = {
        "usa": ["usa", "vereinigte staaten", "america", "amerika", "washington"],
        "china": ["china", "peking", "beijing"],
        "turkey": ["türkei", "tuerkei", "turkey", "ankara", "istanbul"],
        "germany": ["deutschland", "germany", "berlin"],
        "russia": ["russland", "russia", "moskau"],
        "ukraine": ["ukraine", "kiew", "kyiv"],
        "israel": ["israel", "jerusalem", "tel aviv"],
        "iran": ["iran", "teheran"],
        "india": ["indien", "india", "neu-delhi", "new delhi"],
        "brazil": ["brasilien", "brazil"],
        "saudi-arabia": ["saudi", "saudi-arabien", "riyadh"],
        "egypt": ["ägypten", "aegypten", "egypt", "kairo"],
        "france": ["frankreich", "france", "paris"],
        "united-kingdom": ["großbritannien", "grossbritannien", "uk", "britain", "london"],
    }
    lower = text.lower()
    found = []
    for code, aliases in country_aliases.items():
        if any(alias in lower for alias in aliases):
            found.append(code)
    return found[:6] or ["germany", "turkey", "china", "usa"]


async def generate_reply(messages: list, instructions: str, max_output_tokens: int = 400) -> str:
    if AI_PROVIDER == "codex_cli":
        return await generate_reply_with_codex(messages, instructions)

    if not ai:
        raise RuntimeError(f"Unbekannter ai_provider: {AI_PROVIDER}")

    response = await ai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=max_output_tokens,
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


def build_codex_prompt(messages: list, instructions: str) -> str:
    lines = [
        instructions,
        "",
        "Du bist hier als reiner Antwortgenerator fuer eine lokale Voice-Assistant-App aktiv.",
        "Fuehre keine Shell-Kommandos aus, lies keine Dateien und bearbeite keine Dateien.",
        "Gib ausschliesslich die finale Assistentenantwort zurueck.",
        "",
        "=== GESPRAECH ===",
    ]
    for message in messages:
        role = "Nutzer" if message["role"] == "user" else "Assistent"
        lines.append(f"{role}: {message['content']}")
    lines.append("Assistent:")
    return "\n".join(lines)


async def run_codex_cli(prompt: str, image_path: str | None = None) -> str:
    output_file = tempfile.NamedTemporaryFile(prefix="xeon_codex_", suffix=".txt", delete=False)
    output_path = output_file.name
    output_file.close()

    codex_path = shutil.which(CODEX_COMMAND) or shutil.which("codex.cmd") or shutil.which("codex.exe")
    if not codex_path:
        raise RuntimeError("Codex CLI nicht gefunden. Pruefe, ob `codex.cmd` im PATH ist.")

    cmd = [
        codex_path,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--output-last-message",
        output_path,
        "--cd",
        os.path.dirname(__file__),
    ]
    if CODEX_MODEL:
        cmd.extend(["--model", CODEX_MODEL])
    if image_path:
        cmd.extend(["--image", image_path])
    cmd.append("-")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")),
            timeout=CODEX_TIMEOUT,
        )
        result = ""
        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                result = f.read().strip()
        if result:
            return result
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            print(f"[codex] CLI failed: {err[:1000]}", flush=True)
            raise RuntimeError("Codex CLI ist gerade nicht verfuegbar.")
        if not result:
            raise RuntimeError("Codex CLI hat keine Antwort erzeugt.")
        return result
    except asyncio.TimeoutError as exc:
        raise RuntimeError("Codex CLI hat zu lange gebraucht.") from exc
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


async def generate_reply_with_codex(messages: list, instructions: str) -> str:
    return await run_codex_cli(build_codex_prompt(messages, instructions))


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


async def execute_calendar_request(payload: str) -> str:
    write_state = "aktiviert" if GOOGLE_CALENDAR_WRITE_ENABLED else "deaktiviert"
    account_hint = f"\nAutorisierter Google-Account: {GOOGLE_CALENDAR_ACCOUNT}" if GOOGLE_CALENDAR_ACCOUNT else ""
    prompt = f"""Sie sind XEONs Kalender-Modul.
Nutzen Sie den Google-Calendar-Zugriff des eingeloggten Codex-Accounts, falls verfuegbar.
Kalender-Schreibrechte sind in XEON: {write_state}.{account_hint}
Arbeiten Sie timezone-aware in Europe/Berlin.
Wenn der Nutzer Kalenderdaten lesen will, lesen Sie den passenden begrenzten Zeitraum und fassen Sie konkret zusammen.
Wenn der Nutzer einen Termin erstellen, verschieben, aendern, loeschen, absagen, beantworten, blocken oder Erinnerungen setzen will:
- Fuehren Sie die Schreibaktion aus, wenn Titel/Betreff, Datum, Uhrzeit, Dauer oder Endzeit und Absicht eindeutig sind.
- Nutzen Sie den Primaerkalender, wenn kein anderer Kalender genannt ist.
- Nutzen Sie Europe/Berlin, wenn keine andere Zeitzone genannt ist.
- Fragen Sie kurz nach, wenn Pflichtdaten fehlen oder mehrere gleichnamige Termine infrage kommen.
- Bei Loeschungen, Serien-Terminen, mehreren Terminen oder breiten Aenderungen zuerst die betroffenen Termine nennen und bestaetigen lassen.
- Wenn Schreibrechte vom Connector verweigert werden, sagen Sie knapp, dass die Google-Autorisierung Schreibzugriff braucht.
Geben Sie eine kurze deutsche Antwort fuer Sir zurueck, mit exaktem Datum, Uhrzeit und Ergebnis.

Anfrage: {payload}"""
    return await run_codex_cli(prompt)


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

Regeln:
- Keine Shell-Kommandos, keine Loeschungen, keine Massenaenderungen.
- Wenn der Nutzer etwas oeffnen will, nutze operation open.
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
    try:
        calendar_result = await execute_calendar_request(
            "Lies den Kalender fuer heute und die naechsten 7 Tage. Keine Termine erstellen oder aendern. "
            "Fasse Termine, freie Fokusfenster, Konflikte und relevante Vorbereitungspunkte zusammen."
        )
    except Exception:
        calendar_result = "Kalenderzugriff gerade nicht verfuegbar."
    prompt = (
        "Erstelle einen Lagebericht fuer Sir aus Sicht eines Unternehmensberaters fuer MySupplieX.app. "
        "Nutze Kalender und MySupplieX-Daten. Gliedere: 1. CEO-Kalenderlage, 2. Operative MySupplieX-Lage, "
        "3. Risiken, 4. Chancen, 5. Ihre drei naechsten Schritte. Sei konkret, professionell, motivierend.\n\n"
        f"=== KALENDER ===\n{calendar_result}\n\n=== MYSUPPLIEX ===\n{base44_result}"
    )
    try:
        return await generate_reply(
            [{"role": "user", "content": prompt}],
            "Du bist XEON als strategischer Unternehmensberater von MySupplieX.app. Antworte Deutsch, direkt, CEO-tauglich.",
            max_output_tokens=700,
        )
    except Exception:
        return (
            "Sir, der strategische Lagebericht kommt im Fallback-Modus, weil das Codex-Kontingent gerade limitiert ist.\n\n"
            "1. CEO-Kalenderlage:\n"
            f"{calendar_result[:1200]}\n\n"
            "2. Operative MySupplieX-Lage:\n"
            f"{base44_result[:2200]}\n\n"
            "3. Berater-Einschaetzung:\n"
            "Prioritaet: offene Orders, Zahlungs-/Payout-Status, neue Leads und ungelesene Nachrichten pruefen. "
            "Danach sollten Sie eine konkrete Wachstumsaktion fuer MySupplieX setzen: Angebotspipeline bereinigen, "
            "Lead-Follow-ups priorisieren und operative Reibung in Sales/SCM reduzieren."
        )


def prepare_speech_text(text: str) -> str:
    speech_text = text.strip()
    if not speech_text:
        return ""

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

    if TTS_MAX_CHARS > 0 and len(speech_text) > TTS_MAX_CHARS:
        shortened = speech_text[:TTS_MAX_CHARS].rsplit(" ", 1)[0].strip()
        speech_text = f"{shortened} ... Der Rest steht im Chat, Sir."
        print(f"  TTS shortened from {len(text)} to {len(speech_text)} chars", flush=True)

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

    if action_type == "SCREEN":
        if AI_PROVIDER == "codex_cli":
            return await screen_capture.describe_screen_codex(run_codex_cli)
        return await screen_capture.describe_screen(ai, OPENAI_MODEL)

    if action_type == "NEWS":
        news = await browser_tools.fetch_news()
        return news

    if action_type == "BASE44":
        return await execute_base44_request(payload)

    if action_type == "CALENDAR":
        return await execute_calendar_request(payload)

    if action_type == "PC":
        result = pc_tools.execute_pc_operation(payload)
        audit_log.log_action("PC", payload, "ok", result)
        return result

    return ""


async def process_message(session_id: str, user_text: str, ws: WebSocket, speak: bool = True):
    """Process message and send responses via WebSocket."""
    if session_id not in conversations:
        conversations[session_id] = []

    if "activate" in user_text.lower():
        refresh_data()

    conversations[session_id].append({"role": "user", "content": user_text})
    history = conversations[session_id][-16:]
    lowered = user_text.lower()

    if is_shutdown_abort(user_text):
        abort_pc_shutdown()
        audit_log.log_action("SHUTDOWN_ABORT", {"text": user_text}, "ok", "shutdown aborted")
        text = "Herunterfahren abgebrochen, Sir."
        conversations[session_id].append({"role": "assistant", "content": text})
        await send_response(ws, text, speak)
        return

    if is_shutdown_request(user_text):
        if not ALLOW_PC_SHUTDOWN:
            text = "PC-Herunterfahren ist in meiner Konfiguration deaktiviert, Sir."
        elif PC_SHUTDOWN_REQUIRES_CONFIRMATION and not is_shutdown_confirm(user_text):
            text = "Bestätigen Sie mit: XEON, bestätige Herunterfahren."
        else:
            schedule_pc_shutdown()
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
        conversations[session_id].append({"role": "assistant", "content": text})
        await send_response(ws, text, speak)
        return

    if is_pc_control_request(user_text):
        plan = pc_tools.parse_pc_request(user_text)
        if not plan:
            plan = await plan_pc_request(user_text)
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
        conversations[session_id].append({"role": "assistant", "content": text})
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
        conversations[session_id].append({"role": "assistant", "content": text})
        await send_response(ws, text, speak)
        return

    if reminder_tools.is_reminder_request(user_text):
        result = reminder_tools.create_reminder(user_text)
        if not result.get("ok"):
            text = result["error"]
        else:
            item = result["reminder"]
            audit_log.log_action("REMINDER_CREATE", {"source": user_text, "due_at": item["due_at"]}, "ok", item["text"])
            text = (
                f"Vermerkt, Sir. Ich erinnere Sie am {reminder_tools.format_due(item['due_at'])} "
                f"an: {item['text']}."
            )
        conversations[session_id].append({"role": "assistant", "content": text})
        await send_response(ws, text, speak)
        return

    if "lagebericht" in lowered:
        await send_response(ws, "Ich erstelle den Lagebericht, Sir. Kalender, MySupplieX und operative Signale werden jetzt zusammengefuehrt.", speak)
        await ws.send_json({"type": "status", "text": "Kalender und MySupplieX werden analysiert...", "mode": "Ausführen"})
        try:
            report = await execute_lagebericht()
        except Exception as e:
            print(f"[xeon] Lagebericht error: {e}", flush=True)
            report = "Der Lagebericht konnte gerade nicht vollstaendig erstellt werden, Sir. Ich bleibe online und kann MySupplieX oder Kalender getrennt pruefen."
        conversations[session_id].append({"role": "assistant", "content": report})
        await send_response(ws, report, speak)
        return

    if "nachrichten" in lowered or "news" in lowered:
        await send_response(ws, "Ich ziehe die Nachrichten, Sir. World Monitor wird geoeffnet, die Handelslage wird priorisiert.", speak)
        await ws.send_json({"type": "status", "text": "Nachrichten und World Monitor werden geladen...", "mode": "Ausführen"})
        result = await execute_action({"type": "NEWS", "payload": ""})
        summary = (
            "Sir, hier ist der aktuelle Nachrichten-Feed mit Fokus auf Welthandel, Lieferketten und Geopolitik:\n\n"
            + result[:2500]
        )
        conversations[session_id].append({"role": "assistant", "content": summary})
        await send_response(ws, summary, speak)
        return

    if "mysuppliex" in lowered and any(k in lowered for k in ["orders", "order", "status", "lage", "system", "zeig"]):
        await send_response(ws, "Ich pruefe MySupplieX, Sir.", speak)
        await ws.send_json({"type": "status", "text": "MySupplieX Admin-Daten werden gelesen...", "mode": "Ausführen"})
        payload = '{"operation":"health_snapshot"}' if "lage" in lowered or "system" in lowered else '{"operation":"list","entity":"Order","limit":10,"sort_by":"-created_date"}'
        result = await execute_base44_request(payload)
        summary = "Sir, MySupplieX-Daten wurden gelesen:\n\n" + result[:2500]
        conversations[session_id].append({"role": "assistant", "content": summary})
        await send_response(ws, summary, speak)
        return

    if is_calendar_request(user_text):
        if is_calendar_write_request(user_text):
            lead = "Ich aktualisiere Ihren Kalender, Sir."
        else:
            lead = "Ich pruefe Ihren Kalender, Sir."
        await send_response(ws, lead, speak)
        await ws.send_json({"type": "status", "text": "Google Kalender wird verarbeitet...", "mode": "Ausführen"})
        try:
            result = await execute_calendar_request(user_text)
        except Exception as e:
            print(f"[xeon] Calendar error: {e}", flush=True)
            result = "Sir, der Kalenderzugriff ist gerade nicht sauber erreichbar. Wenn der Google-Connector Schreibrechte verlangt, muss die Autorisierung im Codex-Account erneuert werden."
        conversations[session_id].append({"role": "assistant", "content": result})
        await send_response(ws, result, speak)
        return

    if "activate" not in lowered and likely_slow_request(user_text):
        await send_response(ws, "Ich schaue mir das an, Sir.", speak)
        await ws.send_json({"type": "status", "text": "XEON führt aus...", "mode": "Ausführen"})

    response_input = [{"role": item["role"], "content": item["content"]} for item in history]
    try:
        reply = await generate_reply(response_input, get_system_prompt(), max_output_tokens=400)
    except Exception as e:
        print(f"[xeon] Denkmodul error: {e}", flush=True)
        reply = "Sir, mein Denkmodul ist gerade nicht sauber erreichbar. Ich bleibe online; versuchen Sie den Befehl bitte erneut oder nutzen Sie einen direkten Befehl wie Nachrichten, Lagebericht oder MySupplieX."
    print(f"  LLM raw: {reply[:200]}", flush=True)
    spoken_text, action = extract_action(reply)

    if spoken_text:
        audio = await synthesize_speech(spoken_text) if speak else b""
        print(f"  XEON: {spoken_text[:80]}", flush=True)
        print(f"  Audio bytes: {len(audio)}", flush=True)
        conversations[session_id].append({"role": "assistant", "content": spoken_text})
        await ws.send_json(
            {
                "type": "response",
                "text": spoken_text,
                "audio": base64.b64encode(audio).decode("utf-8") if audio else "",
            }
        )

    if action:
        print(f"  Action: {action['type']} -> {action['payload'][:100]}", flush=True)

        if action["type"] == "SCREEN":
            hint = "Lassen Sie mich einen Blick auf Ihren Bildschirm werfen."
            hint_audio = await synthesize_speech(hint) if speak else b""
            await ws.send_json(
                {
                    "type": "response",
                    "text": hint,
                    "audio": base64.b64encode(hint_audio).decode("utf-8") if hint_audio else "",
                }
            )

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
            )
            summary, _ = extract_action(summary)
        else:
            summary = f"Das hat leider nicht funktioniert, {USER_ADDRESS}."

        audio2 = await synthesize_speech(summary) if speak else b""
        conversations[session_id].append({"role": "assistant", "content": summary})
        await ws.send_json(
            {
                "type": "response",
                "text": summary,
                "audio": base64.b64encode(audio2).decode("utf-8") if audio2 else "",
            }
        )


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_websockets.add(ws)
    session_id = str(id(ws))
    print("[xeon] Client connected", flush=True)

    try:
        while True:
            data = await ws.receive_json()
            user_text = data.get("text", "").strip()
            if not user_text:
                continue

            print(f"  You:    {user_text}", flush=True)
            speak = bool(data.get("speak", True))
            await ws.send_json({"type": "status", "text": "XEON denkt nach...", "mode": "Nachdenken", "busy": True})
            try:
                await process_message(session_id, user_text, ws, speak)
            finally:
                await ws.send_json({"type": "status", "text": "", "mode": "Wartet auf Befehl", "busy": False})

    except WebSocketDisconnect:
        conversations.pop(session_id, None)
        active_websockets.discard(ws)


@app.post("/notify")
async def notify(payload: NotifyPayload):
    dead = []
    for ws in list(active_websockets):
        try:
            if payload.speak:
                await send_spoken(ws, payload.text)
            else:
                await ws.send_json({"type": "response", "text": payload.text, "audio": ""})
        except Exception:
            dead.append(ws)
    for ws in dead:
        active_websockets.discard(ws)
    return {"sent": len(active_websockets) - len(dead)}


app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend")),
    name="static",
)


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "index.html"))


if __name__ == "__main__":
    import uvicorn

    print("=" * 50, flush=True)
    print("  XEON V2 Server", flush=True)
    print("  http://localhost:8340", flush=True)
    print("=" * 50, flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8340)
