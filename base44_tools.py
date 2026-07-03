"""
XEON - MySupplieX/Base44 API tools.
Read-focused access for admin reporting inside the local assistant.
"""

import json
from typing import Any

import httpx


class Base44Tools:
    def __init__(self, base_url: str, api_key: str, entities: list[str]):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.entities = entities

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"api_key": self.api_key, "Accept": "application/json"}

    async def list_entity(
        self,
        entity: str,
        query: dict[str, Any] | None = None,
        limit: int = 10,
        skip: int = 0,
        sort_by: str | None = "-created_date",
    ) -> dict[str, Any]:
        entity = self._validate_entity(entity)
        params: dict[str, Any] = {"limit": min(max(int(limit), 1), 50), "skip": max(int(skip), 0)}
        if query:
            params["q"] = json.dumps(query, ensure_ascii=False)
        if sort_by:
            params["sort_by"] = sort_by

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.base_url}/entities/{entity}",
                headers=self._headers(),
                params=params,
            )
            response.raise_for_status()
            return {"entity": entity, "operation": "list", "data": response.json()}

    async def get_entity(self, entity: str, record_id: str) -> dict[str, Any]:
        entity = self._validate_entity(entity)
        if not record_id:
            raise ValueError("record_id fehlt.")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.base_url}/entities/{entity}/{record_id}",
                headers=self._headers(),
            )
            response.raise_for_status()
            return {"entity": entity, "operation": "get", "data": response.json()}

    async def create_entity(self, entity: str, data: dict[str, Any]) -> dict[str, Any]:
        entity = self._validate_entity(entity)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/entities/{entity}",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=data,
            )
            response.raise_for_status()
            return {"entity": entity, "operation": "create", "data": response.json()}

    async def update_entity(self, entity: str, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        entity = self._validate_entity(entity)
        if not record_id:
            raise ValueError("record_id fehlt.")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.put(
                f"{self.base_url}/entities/{entity}/{record_id}",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=data,
            )
            if response.status_code == 405:
                response = await client.patch(
                    f"{self.base_url}/entities/{entity}/{record_id}",
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json=data,
                )
            response.raise_for_status()
            return {"entity": entity, "operation": "update", "data": response.json()}

    async def health_snapshot(self) -> dict[str, Any]:
        focus_entities = ["Order", "Message", "Lead", "User", "StatusUpdate", "SystemHealthReport"]
        results = {}
        for entity in focus_entities:
            if entity in self.entities:
                try:
                    results[entity] = await self.list_entity(entity, limit=5, sort_by="-created_date")
                except Exception as exc:
                    results[entity] = {"error": str(exc)}
        return {"operation": "health_snapshot", "data": results}

    def _validate_entity(self, entity: str) -> str:
        match = next((name for name in self.entities if name.lower() == str(entity).lower()), None)
        if not match:
            raise ValueError(f"Unbekannte Entity: {entity}. Erlaubt: {', '.join(self.entities)}")
        return match
