# XEON Setup Guide

Dein persoenlicher KI-Assistent mit Sprache, Browser-Steuerung, Bildschirmblick und Doppelklatschen-Start.

Wichtig vorab: XEON ist jetzt auf direkten OpenAI-API-Betrieb ausgelegt. Codex CLI wird zur Laufzeit nicht mehr fuer Antworten, Routing, Kalender oder Bildschirmbeschreibung genutzt.
Spracherkennung laeuft lokal ueber Faster-Whisper: Der Browser nimmt nur Mikrofon-Audio auf, die Transkription passiert im lokalen Python-Server.

---

## Voraussetzungen

- Windows 10/11
- Google Chrome fuer Spracheingabe und XEON UI
- Python 3.10+
- OpenAI API-Key
- Faster-Whisper wird per `requirements.txt` installiert; beim ersten Spracheingang wird das Modell lokal geladen.
- Optional: Google OAuth Client fuer direkte Google-Calendar-API
- Optional: ElevenLabs API-Key, falls ElevenLabs statt Edge-TTS genutzt wird
- Optional: MySupplieX/Base44 API-Key fuer Admin-Entity-Reads

---

## Setup Schritt Fuer Schritt

### 1. Python pruefen

```powershell
python --version
```

Wenn Python fehlt:

```powershell
winget install Python.Python.3.12
```

Danach VS Code oder das Terminal neu starten. Falls `python` im aktuellen Terminal noch auf den Microsoft-Store-Alias zeigt, nutze vorerst den direkten Pfad:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" --version
```

### 2. Dependencies installieren

```powershell
pip install -r requirements.txt
playwright install chromium
```

Falls `python`/`pip` noch nicht im PATH ist:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pip install -r requirements.txt
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m playwright install chromium
```

### 3. OpenAI API-Key setzen

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-...", "User")
```

Danach Terminal, VS Code und XEON neu starten.

### 4. Config erstellen

Kopiere `config.example.json` nach `config.json`.

```powershell
Copy-Item config.example.json config.json
```

Oeffne `config.json` und trage deine Werte ein:

```json
{
  "ai_provider": "openai",
  "openai_api_key": "",
  "openai_router_enabled": true,
  "openai_model_fast": "gpt-5.4-mini",
  "openai_model_smart": "gpt-5.5",
  "openai_model": "gpt-5.5",
  "google_calendar_client_secret_file": "data/google-oauth-client-secret.json",
  "google_calendar_token_file": "data/google-calendar-token.json",
  "google_calendar_id": "primary",
  "elevenlabs_api_key": "sk_...",
  "elevenlabs_voice_id": "VOICE_ID",
  "stt_provider": "faster_whisper",
  "faster_whisper_model": "small",
  "faster_whisper_device": "cpu",
  "faster_whisper_compute_type": "int8",
  "faster_whisper_language": "de",
  "user_name": "Dein Name",
  "user_address": "Sir",
  "city": "Hamburg",
  "workspace_path": "C:\\Users\\User\\Downloads\\jarvis-voice-assistant-master\\jarvis-voice-assistant-master",
  "spotify_track": "spotify:track:DEIN_TRACK_ID",
  "browser_url": "https://deine-website.com",
  "obsidian_inbox_path": "C:\\pfad\\zum\\obsidian\\inbox",
  "apps": ["obsidian://open"]
}
```

Falls du keinen Obsidian-Inbox-Pfad nutzen willst, setze:

```json
"obsidian_inbox_path": ""
```

### 5. Google Kalender direkt verbinden

Wenn XEON deinen Google Kalender lesen/schreiben soll, erstelle in der Google Cloud Console einen OAuth Client fuer eine Desktop-App, lade die JSON-Datei herunter und lege sie hier ab:

```text
data/google-oauth-client-secret.json
```

Beim ersten Kalenderbefehl oeffnet XEON den Google-Login im Browser und speichert danach das Token unter:

```text
data/google-calendar-token.json
```

### 6. ElevenLabs Stimme

Trage eine vorhandene ElevenLabs Voice ID in `elevenlabs_voice_id` ein. Wenn du noch keine Stimme ausgewaehlt hast, kannst du zunaechst den Standardwert aus `config.example.json` stehen lassen und spaeter anpassen.

### 7. XEON starten

```powershell
python server.py
```

Falls `python` noch nicht im PATH ist:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" server.py
```

Dann in Chrome oeffnen:

```text
http://localhost:8340
```

Beim ersten Laden einmal in die Seite klicken, damit Chrome Audio abspielen darf.

### 8. Doppelklatschen starten

```powershell
python scripts\clap-trigger.py
```

Falls `python` noch nicht im PATH ist:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" scripts\clap-trigger.py
```

Zweimal klatschen startet die Session ueber `scripts\launch-session.ps1`.

### 9. Doppelklatschen beim Windows-Start

Der persistente Listener kann beim Windows-Login gestartet werden:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install-clap-autostart.ps1
```

Wenn der Task Scheduler keine Rechte gibt, erstellt das Skript automatisch einen Eintrag im Windows-Startup-Ordner.

---

## Was XEON Kann

- "Wie ist das Wetter?"
- "Such nach ..."
- "Oeffne skool.com"
- "Was siehst du auf meinem Bildschirm?"
- "Was passiert gerade in der Welt?"
- "Was steht heute in meinem Kalender?"
- "Erstelle morgen um 10 Uhr einen Termin ..."
- "Zeig mir die letzten MySupplieX Orders"
- "Wie sieht die aktuelle MySupplieX Systemlage aus?"

---

## Fehlerbehebung

| Problem | Loesung |
|---|---|
| OpenAI API fehlt | `OPENAI_API_KEY` als Windows-User-Env setzen und XEON neu starten |
| XEON spricht nicht | Pruefen ob `python server.py` laeuft und Chrome offen ist |
| Verbindung verloren | Alten Python-Prozess beenden und Server neu starten |
| Klatschen wird nicht erkannt | `THRESHOLD` in `scripts\clap-trigger.py` niedriger setzen |
| Browser-Suche geht nicht | `playwright install chromium` ausfuehren |
| Kein Audio im Browser | Einmal auf die Seite klicken |
| Doppelklatschen startet nicht | `scripts\start-clap-listener.ps1` starten und `xeon-clap-listener.err.log` pruefen |
| MySupplieX geht nicht | `base44_base_url`, `base44_api_key` und `base44_entities` in `config.json` pruefen |
| Kalender geht nicht | `google_calendar_client_secret_file` pruefen und Google OAuth im Browser einmal abschliessen |

---

## Setup Mit OpenAI API Statt Claude/Codex

Wenn du ChatGPT/Codex nutzt, sage:

> Richte XEON fuer mich ein.

Die benoetigten Angaben sind:

- Dein Name
- Gewuenschte Anrede, z.B. `Sir`, `Chef`, oder dein Vorname
- OpenAI API-Key
- Optional ElevenLabs API-Key
- Optional Google OAuth Client fuer Kalender
- Spotify-Song oder leer lassen
- Programme fuer den Doppelklatschen-Start
- Website fuer den Browserstart
- Stadt fuer Wetter
- Optionaler Obsidian-Inbox-Pfad

Claude Code, Anthropic und Codex CLI sind fuer diese Version nicht noetig.
