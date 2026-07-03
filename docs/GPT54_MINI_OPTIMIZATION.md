# XEON GPT-5.4-mini Optimierung

Ziel: XEON bleibt bewusst komplett auf `gpt-5.4-mini`, soll sich aber deutlich intelligenter, klarer und agentischer verhalten.

## Grundprinzip

`gpt-5.4-mini` darf nicht wie ein billiger Chatbot betrieben werden. Das Modell braucht:

1. weniger permanenten Prompt-Ballast,
2. bessere Aufgabenklassifikation,
3. dynamisches Reasoning je Aufgabe,
4. komprimierten Verlauf statt Roh-Overload,
5. Tool-Prompts nur bei Bedarf,
6. Ergebnispruefung nach Tool-Nutzung.

## Repo-Defaults

`config.example.json` ist absichtlich so gesetzt:

- `openai_model_fast`: `gpt-5.4-mini`
- `openai_model_smart`: `gpt-5.4-mini`
- `openai_model`: `gpt-5.4-mini`
- `openai_force_fast_only`: `true`
- `openai_default_to_smart`: `true`
- `conversation_prompt_messages`: `24`
- `conversation_memory_max_messages`: `80`
- `attachment_text_preview_chars`: `2500`
- `chatgpt_export_max_files`: `6`

Damit bleibt alles auf Mini, aber XEON schleppt weniger alten Kontext in jeden Call.

## Empfohlene Server-Policy

In `generate_reply()` sollte `reasoning` nicht pauschal auf `low` stehen. Besser:

```python

def openai_effort_for(route_hint: str, messages: list, max_output_tokens: int) -> str:
    text = (route_hint + "\n" + "\n".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))).lower()
    high_markers = [
        "repo", "repository", "code", "coding", "debug", "architektur", "review",
        "analys", "strategie", "lagebericht", "terminal", "desktop_agent", "shell",
    ]
    medium_markers = [
        "kalender", "base44", "mysuppliex", "news", "nachrichten", "plan", "tool",
    ]
    if max_output_tokens >= 1000 or any(marker in text for marker in high_markers):
        return "high"
    if max_output_tokens >= 450 or any(marker in text for marker in medium_markers):
        return "medium"
    return "low"


def openai_verbosity_for(route_hint: str, max_output_tokens: int) -> str:
    text = route_hint.lower()
    if any(marker in text for marker in ["json", "planner", "fast structured", "todo_rewrite"]):
        return "low"
    if max_output_tokens >= 700:
        return "medium"
    return "medium"
```

Dann in `ai.responses.create(...)`:

```python
response = await ai.responses.create(
    model=model,
    instructions=instructions,
    input=messages,
    max_output_tokens=max_output_tokens,
    reasoning={"effort": openai_effort_for(route_hint, messages, max_output_tokens)},
    text={"verbosity": openai_verbosity_for(route_hint, max_output_tokens)},
)
```

Das ist der groesste einzelne Hebel. Mini bleibt Mini, denkt aber bei schweren Aufgaben nicht mehr kuenstlich flach.

## Prompt-Architektur

Der Core-Systemprompt sollte dauerhaft kurz bleiben:

- Identitaet: XEON, deutscher Desktop-/Voice-Agent.
- Stil: kurz, direkt, loyal, strategisch.
- Arbeitsweise: Ziel erkennen, ggf. planen, Tools nutzen, Ergebnis pruefen.
- Keine langen Meta-Erklaerungen.
- Bei klaren lokalen Aufgaben handeln.

Spezialregeln gehoeren in Module:

- News-Regeln nur bei News/Lagebericht.
- Base44-Regeln nur bei Base44/MySupplieX-Daten.
- Kalender-Regeln nur bei Kalender.
- Desktop-/PC-Regeln nur bei Desktop/PC/Shell.
- Hue-Regeln nur bei Lichtbefehlen.

## Mini-Agent-Verhalten

Vor Tool-Aufrufen soll XEON intern diese Schleife fahren:

```text
Ziel erkennen -> benoetigte Daten bestimmen -> passendes Tool waehlen -> Ergebnis pruefen -> kurz antworten
```

Nicht alles muss ein separater API-Call sein. Oft reicht, diese Schleife im Prompt klar vorzuschreiben.

## Was vermieden werden muss

- Ein riesiger Universalprompt fuer jede kleine Frage.
- Dauerhaft `reasoning=low`.
- Dauerhaft `verbosity=low`.
- Zu viele alte Chat-Nachrichten im Prompt.
- Rohdaten von Tools ungefiltert in die Antwort kippen.
- Fuer einfache Antworten lange Agentenketten starten.

## Erwartetes Ergebnis

Mit denselben Modellkosten sollte XEON spuerbar besser werden:

- weniger vergesslich,
- weniger stumpf,
- bessere Tool-Auswahl,
- staerkere Coding-/Repo-Antworten,
- bessere MySupplieX-Lageberichte,
- klarere naechste Schritte,
- weniger lokales-Billig-KI-Gefuehl.
