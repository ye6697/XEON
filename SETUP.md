# XEON Setup Guide

Dein persoenlicher KI-Assistent mit Sprache, Browser-Steuerung, Bildschirmblick und Doppelklatschen-Start.

Wichtig vorab: XEON ist jetzt so konfiguriert, dass es deinen lokalen Codex-Login nutzt (`codex.cmd exec`). Dafuer brauchst du keinen OpenAI-API-Key, solange Codex auf diesem Rechner mit deinem ChatGPT/Codex-Account eingeloggt ist. Das ist langsamer als die direkte OpenAI API, aber entspricht dem Setup ohne OpenAI-API-Key.

Quelle: Die Codex-Dokumentation beschreibt, dass die Codex CLI per ChatGPT-Account eingeloggt werden kann und `codex exec` non-interaktiv laeuft: https://developers.openai.com/codex/auth und https://developers.openai.com/codex/cli/reference

---

## Voraussetzungen

- Windows 10/11
- Google Chrome fuer Spracheingabe und XEON UI
- Python 3.10+
- Codex CLI, eingeloggt mit deinem ChatGPT/Codex-Account
- Ein ElevenLabs API-Key fuer die Stimme
- Optional: Google Calendar Connector im Codex-Account fuer Kalenderaktionen
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

### 3. Codex Login pruefen

```powershell
codex.cmd login status
```

Erwartet:

```text
Logged in using ChatGPT
```

Falls du nicht eingeloggt bist:

```powershell
codex.cmd login
```

### 4. Config erstellen

Kopiere `config.example.json` nach `config.json`.

```powershell
Copy-Item config.example.json config.json
```

Oeffne `config.json` und trage deine Werte ein:

```json
{
  "ai_provider": "codex_cli",
  "openai_api_key": "",
  "openai_model": "gpt-5.5",
  "codex_command": "codex.cmd",
  "codex_model": "gpt-5.5",
  "codex_timeout_seconds": 90,
  "elevenlabs_api_key": "sk_...",
  "elevenlabs_voice_id": "VOICE_ID",
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

### 5. ElevenLabs Stimme

Trage eine vorhandene ElevenLabs Voice ID in `elevenlabs_voice_id` ein. Wenn du noch keine Stimme ausgewaehlt hast, kannst du zunaechst den Standardwert aus `config.example.json` stehen lassen und spaeter anpassen.

### 6. XEON starten

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

### 7. Doppelklatschen starten

```powershell
python scripts\clap-trigger.py
```

Falls `python` noch nicht im PATH ist:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" scripts\clap-trigger.py
```

Zweimal klatschen startet die Session ueber `scripts\launch-session.ps1`.

### 8. Doppelklatschen beim Windows-Start

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
| Codex CLI fehlgeschlagen | `codex.cmd login status` pruefen |
| Codex antwortet langsam | Das ist beim `codex_cli` Provider normal; direkte API waere schneller |
| XEON spricht nicht | Pruefen ob `python server.py` laeuft und Chrome offen ist |
| Verbindung verloren | Alten Python-Prozess beenden und Server neu starten |
| Klatschen wird nicht erkannt | `THRESHOLD` in `scripts\clap-trigger.py` niedriger setzen |
| Browser-Suche geht nicht | `playwright install chromium` ausfuehren |
| Kein Audio im Browser | Einmal auf die Seite klicken |
| Doppelklatschen startet nicht | `scripts\start-clap-listener.ps1` starten und `xeon-clap-listener.err.log` pruefen |
| MySupplieX geht nicht | `base44_base_url`, `base44_api_key` und `base44_entities` in `config.json` pruefen |
| Kalender geht nicht | `codex.cmd login status` pruefen und Google Calendar Connector im Codex-Account autorisieren |

---

## Setup Mit ChatGPT/Codex Statt Claude

Wenn du ChatGPT/Codex nutzt, sage:

> Richte XEON fuer mich ein.

Die benoetigten Angaben sind:

- Dein Name
- Gewuenschte Anrede, z.B. `Sir`, `Chef`, oder dein Vorname
- Codex Login per ChatGPT-Account
- ElevenLabs API-Key
- Spotify-Song oder leer lassen
- Programme fuer den Doppelklatschen-Start
- Website fuer den Browserstart
- Stadt fuer Wetter
- Optionaler Obsidian-Inbox-Pfad

Claude Code, Anthropic und ein OpenAI-API-Key sind fuer diese Version nicht noetig.
