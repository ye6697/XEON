from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx

TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESPONSES_URL = "https://api.openai.com/v1/responses"
RESOURCE = "https://api.openai.com/v1"

_lock = asyncio.Lock()


def _credential_path() -> Path:
    return Path(os.environ.get("XEON_CHATGPT_CREDENTIALS", "/var/lib/xeon-work/chatgpt-plan.json"))


def _load() -> dict[str, Any]:
    path = _credential_path()
    if not path.exists():
        raise RuntimeError("chatgpt_plan_credentials_missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    required = ("client_id", "access_token", "refresh_token", "saved_at", "expires_in")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise RuntimeError("chatgpt_plan_credentials_incomplete:" + ",".join(missing))
    scopes = set(data.get("scopes") or str(data.get("scope") or "").split())
    if "chatgpt.tokens.use.direct" not in scopes:
        raise RuntimeError("chatgpt_plan_scope_missing")
    return data


def _save(data: dict[str, Any]) -> None:
    path = _credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def _saved_at(data: dict[str, Any]) -> datetime:
    raw = str(data.get("saved_at") or "").replace("Z", "+00:00")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.fromtimestamp(0, timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _needs_refresh(data: dict[str, Any]) -> bool:
    expires = int(data.get("expires_in") or 3600)
    expiry = _saved_at(data) + timedelta(seconds=expires)
    earliest = data.get("earliest_refresh_at")
    if earliest:
        try:
            earliest_dt = datetime.fromisoformat(str(earliest).replace("Z", "+00:00"))
            if earliest_dt.tzinfo is None:
                earliest_dt = earliest_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < earliest_dt:
                return False
        except ValueError:
            pass
    return datetime.now(timezone.utc) >= expiry - timedelta(minutes=5)


async def access_token() -> str:
    async with _lock:
        data = _load()
        if not _needs_refresh(data):
            return str(data["access_token"])

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": data["client_id"],
                    "refresh_token": data["refresh_token"],
                    "resource": RESOURCE,
                },
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        if response.status_code != 200:
            detail = response.text[:1000]
            raise RuntimeError(f"chatgpt_plan_refresh_failed:{response.status_code}:{detail}")

        fresh = response.json()
        merged = dict(data)
        for key in ("access_token", "refresh_token", "id_token", "token_type", "expires_in", "scope", "earliest_refresh_at"):
            if fresh.get(key) is not None:
                merged[key] = fresh[key]
        if fresh.get("scope"):
            merged["scopes"] = str(fresh["scope"]).split()
        merged["saved_at"] = datetime.now(timezone.utc).isoformat()
        _save(merged)
        return str(merged["access_token"])


async def prompt_architect(task: dict[str, Any]) -> str:
    token = await access_token()
    model = os.environ.get("XEON_PLANNER_MODEL", "gpt-6.1-sol")
    instructions = """You are XEON Work's Prompt Architect.
Turn the user's natural-language request plus the supplied XEON context into a precise engineering brief for an autonomous Codex coding agent.

Rules:
- Preserve the user's actual outcome and constraints.
- Do not prescribe a code-level solution before Codex inspects the repository.
- Separate durable requirements from observations and hypotheses.
- Include prior failed attempts when present so Codex does not repeat them blindly.
- Tell Codex to inspect the current implementation, identify root cause(s), create its own technical plan, implement, test, inspect adjacent paths for the same failure class, and verify behavior.
- Do not include credentials, tokens, secrets, or irrelevant personal data.
- Respect CAT1/CAT2/CAT3 boundaries supplied in the task.
- CAT1 still permits analysis, coding and tests; stop before irreversible production action.
- Output only the final engineering brief in Markdown. No preamble."""
    payload = {
        "model": model,
        "instructions": instructions,
        "input": [{"role": "user", "content": json.dumps(task, ensure_ascii=False)}],
        "store": False,
        "stream": True,
    }

    chunks: list[str] = []
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            RESPONSES_URL,
            headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
            json=payload,
        ) as response:
            if response.status_code != 200:
                detail = (await response.aread()).decode("utf-8", "replace")[:1600]
                raise RuntimeError(f"prompt_architect_failed:{response.status_code}:{detail}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "response.output_text.delta":
                    chunks.append(str(event.get("delta") or ""))
                elif event_type == "response.failed":
                    raise RuntimeError("prompt_architect_response_failed:" + json.dumps(event, ensure_ascii=False)[:1200])

    brief = "".join(chunks).strip()
    if not brief:
        raise RuntimeError("prompt_architect_empty")
    return brief
