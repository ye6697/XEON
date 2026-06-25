# XEON - Personal AI Voice Assistant

XEON ist ein lokaler Sprachassistent fuer Windows: Chrome nimmt Sprache auf, ein FastAPI-Server verarbeitet die Anfrage, ElevenLabs spricht die Antwort, Playwright steuert den Browser, und ein Doppelklatschen kann die komplette Session starten.

Diese Version nutzt standardmaessig deinen lokalen Codex-Login ueber `codex.cmd exec`. Dafuer brauchst du keinen OpenAI-API-Key, solange Codex mit deinem ChatGPT/Codex-Account eingeloggt ist.

## Features

- Doppelklatschen startet dein Setup
- Sprachgespraeche im Browser
- Codex CLI als KI-Provider ohne OpenAI-API-Key
- ElevenLabs Text-to-Speech
- Browser-Suche und URL-Oeffnen via Playwright
- Screenshot-Beschreibung via Codex CLI Bild-Input
- Wetter und optionale Obsidian-Aufgaben beim Start

## Quick Start

```powershell
codex.cmd login status
pip install -r requirements.txt
playwright install chromium
Copy-Item config.example.json config.json
```

In `config.json` bleiben diese Werte fuer den Codex-Modus:

```json
{
  "ai_provider": "codex_cli",
  "openai_api_key": "",
  "codex_command": "codex.cmd",
  "codex_model": "gpt-5.5",
  "codex_timeout_seconds": 90
}
```

Du musst trotzdem `elevenlabs_api_key`, `elevenlabs_voice_id`, `user_name`, `city` und `workspace_path` passend setzen.

Server starten:

```powershell
python server.py
```

Falls `python` noch nicht im PATH ist:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" server.py
```

Dann Chrome oeffnen:

```text
http://localhost:8340
```

## Hinweise

- `codex_cli` ist deutlich langsamer als direkte OpenAI API-Aufrufe, weil pro Antwort ein Codex-Exec-Lauf gestartet wird.
- Codex muss eingeloggt sein: `codex.cmd login status`.
- Voice braucht weiterhin ElevenLabs-Zugangsdaten.

## Fehlerbehebung

| Problem | Loesung |
|---|---|
| Codex CLI fehlgeschlagen | `codex.cmd login status` pruefen |
| XEON antwortet langsam | Bei `ai_provider: codex_cli` normal |
| XEON spricht nicht | ElevenLabs-Key/Voice-ID pruefen und einmal in Chrome klicken |
| Browser-Automation scheitert | `playwright install chromium` ausfuehren |
| Klatschen wird nicht erkannt | `THRESHOLD` in `scripts\clap-trigger.py` senken |
