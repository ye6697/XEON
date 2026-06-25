# XEON Ops Layer

XEON keeps its original assistant concept: voice-first local Windows assistant for Sir.

ECC-inspired additions:

- Modular local tools instead of arbitrary shell execution.
- Structured action log in `data/action_log.jsonl`.
- PC actions are explicit operations: open, list, read, write, append, replace.
- Text file edits create `.xeonbak-<timestamp>` backups.
- Strong local actions such as shutdown and reminders are logged.
- ECC repository cloned into `vendor/ECC`.
- 271 ECC skills installed into `C:\Users\User\.codex\skills` with `ecc-` prefix.
- 67 ECC agent profiles installed into `C:\Users\User\.codex\agents`.
- ECC `.agents` package copied into `C:\Users\User\.codex\.agents`.
- Global Codex `config.toml`, `AGENTS.md`, hooks and rules were not overwritten.
- Unknown open targets are not launched blindly; XEON reports when a target is not safely found.

Supported PC examples:

- `Oeffne Downloads`
- `Oeffne Chrome`
- `Liste Ordner Desktop`
- `Lies Datei C:\Users\User\Desktop\notes.txt`
- `Schreibe Datei C:\Users\User\Desktop\test.txt: Inhalt`
- `Fuege zu Datei C:\Users\User\Desktop\test.txt hinzu: Weitere Zeile`
- `Ersetze in Datei C:\Users\User\Desktop\test.txt "alt" durch "neu"`
- `Mach Google Kalender auf`
- `Ruf Indeed auf`

Notes:

- Binary files are opened through Windows, not read into chat.
- Direct file reads/edits are limited to text-like extensions.
- Arbitrary shell command execution is intentionally not exposed as a voice action.
