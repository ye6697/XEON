from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPolicy:
    effort: str
    verbosity: str
    reason: str


WORKFLOW_PROMPT = """
XEON V3 WORKFLOW:
Use this internal order for non-trivial requests:
1. Understand the goal and context.
2. Make a short plan.
3. Use only the needed capability.
4. Check the result.
5. Answer briefly and concretely.
""".strip()


HARD_WORDS = {
    "repo", "repository", "code", "debug", "review", "bugfix", "refactor",
    "analysis", "analyse", "strategy", "strategie", "lagebericht", "mysuppliex",
    "base44", "error", "fehler", "build", "test",
}

MEDIUM_WORDS = {
    "calendar", "kalender", "news", "nachrichten", "plan", "browser",
    "screen", "screenshot", "research", "recherche", "search",
}

LOW_WORDS = {"json", "todo_rewrite", "learning_memory"}


def _text(route_hint: str, messages: list) -> str:
    parts = [route_hint or ""]
    for msg in messages:
        if isinstance(msg, dict):
            parts.append(str(msg.get("content", "")))
    return "\n".join(parts).lower()


def choose_policy(route_hint: str, messages: list, max_output_tokens: int) -> ModelPolicy:
    text = _text(route_hint, messages)
    if max_output_tokens >= 1000 or any(w in text for w in HARD_WORDS):
        effort = "high"
        reason = "hard"
    elif max_output_tokens >= 450 or any(w in text for w in MEDIUM_WORDS):
        effort = "medium"
        reason = "medium"
    else:
        effort = "low"
        reason = "simple"

    hint = (route_hint or "").lower()
    verbosity = "low" if max_output_tokens <= 450 and any(w in hint for w in LOW_WORDS) else "medium"
    return ModelPolicy(effort=effort, verbosity=verbosity, reason=reason)


def add_workflow(system_prompt: str) -> str:
    if "XEON V3 WORKFLOW" in system_prompt:
        return system_prompt
    marker = "Antwortstrategie:"
    if marker in system_prompt:
        return system_prompt.replace(marker, WORKFLOW_PROMPT + "\n\n" + marker, 1)
    return system_prompt + "\n\n" + WORKFLOW_PROMPT
