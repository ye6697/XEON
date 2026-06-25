"""Local Ollama provider for XEON."""

from __future__ import annotations

import httpx


class OllamaProvider:
    def __init__(self, base_url: str, model: str, timeout_seconds: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def chat(self, messages: list[dict], instructions: str, max_output_tokens: int = 400) -> str:
        payload_messages = []
        if instructions:
            payload_messages.append({"role": "system", "content": instructions})
        payload_messages.extend(messages)

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": payload_messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": max_output_tokens,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

        content = ((data.get("message") or {}).get("content") or "").strip()
        if not content:
            raise RuntimeError("Ollama hat keine Antwort erzeugt.")
        return content

    async def healthcheck(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])
                return any(str(item.get("name", "")).startswith(self.model) for item in models)
        except Exception:
            return False
