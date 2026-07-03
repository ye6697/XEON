"""
Patch server.py so XEON keeps using gpt-5.4-mini but stops forcing every
OpenAI Responses call into low-effort / low-verbosity mode.

Run from repo root:
    python scripts/apply-mini-optimizer.py

The script is idempotent and creates server.py.bak before writing.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
BACKUP = ROOT / "server.py.bak"


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        return text
    return text.replace(old, new, 1)


def main() -> None:
    text = SERVER.read_text(encoding="utf-8-sig")
    original = text

    helpers = '''\n\ndef openai_effort_for(route_hint: str, messages: list, max_output_tokens: int) -> str:\n    """Choose the strongest useful reasoning mode while staying on gpt-5.4-mini."""\n    combined = (route_hint + "\\n" + "\\n".join(\n        str(message.get("content", "")) for message in messages if isinstance(message, dict)\n    )).lower()\n    high_markers = [\n        "repo", "repository", "code", "coding", "debug", "architektur", "review",\n        "bugfix", "refactor", "implementiere", "terminal", "shell", "desktop_agent",\n        "screen vision", "analyse", "analys", "strategie", "lagebericht",\n    ]\n    medium_markers = [\n        "kalender", "calendar", "base44", "mysuppliex", "news", "nachrichten",\n        "plan", "planner", "tool", "pc control", "browser",\n    ]\n    if max_output_tokens >= 1000 or any(marker in combined for marker in high_markers):\n        return "high"\n    if max_output_tokens >= 450 or any(marker in combined for marker in medium_markers):\n        return "medium"\n    return "low"\n\n\ndef openai_verbosity_for(route_hint: str, max_output_tokens: int) -> str:\n    """Keep JSON/planner calls tight, but stop making normal answers artificially thin."""\n    hint = route_hint.lower()\n    low_markers = ["json", "planner", "fast structured", "todo_rewrite", "learning_memory"]\n    if any(marker in hint for marker in low_markers) and max_output_tokens <= 450:\n        return "low"\n    return "medium"\n'''

    if "def openai_effort_for(" not in text:
        anchor = '''    if OPENAI_DEFAULT_TO_SMART:\n        return OPENAI_MODEL_SMART, "default smart"\n    return OPENAI_MODEL_FAST, "default fast"\n'''
        text = text.replace(anchor, anchor + helpers, 1)

    text = text.replace(
        '''            reasoning={"effort": "low"},\n            text={"verbosity": "low"},''',
        '''            reasoning={"effort": openai_effort_for(route_hint, messages, max_output_tokens)},\n            text={"verbosity": openai_verbosity_for(route_hint, max_output_tokens)},''',
    )

    text = text.replace(
        '''        reasoning={"effort": "low"},\n        text={"verbosity": "low"},''',
        '''        reasoning={"effort": openai_effort_for("desktop_agent screen vision pc control", [{"role": "user", "content": instruction}], 400)},\n        text={"verbosity": "low"},''',
    )

    if text == original:
        print("No changes needed; server.py already appears patched.")
        return

    if not BACKUP.exists():
        BACKUP.write_text(original, encoding="utf-8")
    SERVER.write_text(text, encoding="utf-8")
    print("Patched server.py for dynamic gpt-5.4-mini reasoning/verbosity.")
    print("Backup written to server.py.bak")


if __name__ == "__main__":
    main()
