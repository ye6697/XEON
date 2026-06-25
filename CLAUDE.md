# Agent Notes

Dieses Workspace ist **XEON** - ein persoenlicher KI-Assistent mit Sprachsteuerung, Browser-Kontrolle, Bildschirmblick und Doppelklatschen-Trigger.

## Setup-Modus

Wenn der Nutzer nach dem Setup fragt oder "Richte XEON ein" sagt, folge den Anweisungen in `SETUP.md`.

Wichtig:

- Nicht nach Anthropic- oder Claude-Keys fragen.
- Standardmaessig nutzt das Backend `ai_provider: codex_cli` und damit `codex.cmd exec` mit ChatGPT/Codex-Login.
- Ein OpenAI Platform API-Key ist nur noetig, wenn `ai_provider` explizit auf `openai` gesetzt wird.
- Der Assistent heisst `XEON`, nicht `Jarvis`.

## Voraussetzungen Pruefen

1. Python 3.10+:
   `python --version`

2. Falls Python fehlt:
   `winget install Python.Python.3.12`

3. Google Chrome muss installiert sein.

4. Python Dependencies:
   `pip install -r requirements.txt`

5. Playwright Browser:
   `playwright install chromium`

## Projektstruktur

```text
.
├── CLAUDE.md              # Agenten-Hinweise
├── SETUP.md               # Setup-Anleitung fuer XEON
├── config.json            # Persoenliche Config (gitignored)
├── config.example.json    # Template mit Platzhaltern
├── requirements.txt       # Python Dependencies
├── server.py              # FastAPI Backend (Codex CLI/OpenAI + ElevenLabs TTS)
├── browser_tools.py       # Playwright Browser-Steuerung
├── screen_capture.py      # Screenshot + Codex CLI/OpenAI Vision
├── frontend/
│   ├── index.html         # XEON Web-UI
│   ├── main.js            # Speech Recognition + WebSocket + Audio
│   └── style.css          # Dark Theme mit Orb-Animation
└── scripts/
    ├── clap-trigger.py    # Doppelklatschen-Erkennung
    └── launch-session.ps1 # Startet alle Apps + XEON
```
