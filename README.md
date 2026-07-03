# XEON - Personal AI Voice Assistant

XEON ist ein lokaler Sprachassistent fuer Windows: Chrome nimmt Sprache auf, ein FastAPI-Server verarbeitet die Anfrage, ElevenLabs oder Edge-TTS spricht die Antwort, Playwright steuert den Browser, und ein Doppelklatschen kann die komplette Session starten.

Diese Version ist auf direkten OpenAI-API-Betrieb mit `gpt-5.4-mini` optimiert. Das Ziel ist nicht, ein groesseres Modell zu nutzen, sondern aus Mini durch weniger Prompt-Ballast, kompakteren Verlauf und bessere Tool-Fuehrung mehr herauszuholen.

## Features

- Doppelklatschen startet dein Setup
- Sprachgespraeche im Browser
- OpenAI API als KI-Provider mit `gpt-5.4-mini`
- ElevenLabs oder Edge-TTS fuer Sprachausgabe
- Browser-Suche und URL-Oeffnen via Playwright
- Screenshot-/Desktop-Agent fuer sichtbare UI-Schritte
- Wetter, Aufgaben, Kalender, Base44/MySupplieX und optionale Mobile-Sync-Funktionen

## Quick Start

```powershell
pip install -r requirements.txt
playwright install chromium
Copy-Item config.example.json config.json
```

OpenAI API-Key als Windows-User-Variable setzen:

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-...", "User")
```

Danach Terminal, VS Code und XEON neu starten.

In `config.json` bleiben diese Werte fuer den Mini-only-Modus:

```json
{
  "ai_provider": "openai",
  "openai_model_fast": "gpt-5.4-mini",
  "openai_model_smart": "gpt-5.4-mini",
  "openai_model": "gpt-5.4-mini",
  "openai_force_fast_only": true,
  "openai_default_to_smart": true,
  "conversation_prompt_messages": 24,
  "conversation_memory_max_messages": 80
}
```

Du musst trotzdem `elevenlabs_api_key`, `elevenlabs_voice_id`, `user_name`, `city` und `workspace_path` passend setzen, sofern du ElevenLabs nutzt.

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

## Mini-Optimierung

Die Mini-only-Strategie ist in `docs/GPT54_MINI_OPTIMIZATION.md` dokumentiert.

Wichtig:

- XEON soll weiterhin ausschliesslich `gpt-5.4-mini` nutzen.
- Der Kontext wurde in den Defaults reduziert, damit Mini nicht bei jeder Anfrage alten Ballast mitschleppt.
- `openai_default_to_smart` bleibt trotzdem aktiv, aber `smart` zeigt ebenfalls auf `gpt-5.4-mini`.
- Fuer schwere Aufgaben sollte `server.py` dynamisches Reasoning nutzen: einfache Aufgaben `low`, Analyse/Repo/Desktop/Shell `medium` bis `high`.

## Hinweise

- Direkte OpenAI API-Aufrufe sind fuer Voice deutlich schneller als Codex-CLI-Exec-Laeufe.
- Voice braucht ElevenLabs-Zugangsdaten, ausser du nutzt Edge-TTS.
- Fuer Kalender brauchst du optional Google OAuth-Dateien.
- Fuer Base44/MySupplieX brauchst du Base44-URL, API-Key und freigegebene Entities.

## Fehlerbehebung

| Problem | Loesung |
|---|---|
| OpenAI API fehlt | `OPENAI_API_KEY` als Windows-User-Env setzen und XEON neu starten |
| XEON wirkt stumpf | Pruefen, ob `conversation_prompt_messages` niedrig genug ist und Mini nicht mit altem Kontext ueberladen wird |
| XEON antwortet zu knapp | In `server.py` Reasoning/Verbosity fuer schwere Aufgaben dynamisch auf `medium`/`high` setzen |
| XEON spricht nicht | ElevenLabs-Key/Voice-ID pruefen oder Edge-TTS aktivieren und einmal in Chrome klicken |
| Browser-Automation scheitert | `playwright install chromium` ausfuehren |
| Klatschen wird nicht erkannt | `THRESHOLD` in `scripts\clap-trigger.py` senken |
