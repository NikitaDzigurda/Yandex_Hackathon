"""Async Yandex Tracker client."""

import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class TrackerAPIError(Exception):
    """Raised when Tracker API returns an error."""


class TrackerClient:
    base_url = "https://api.tracker.yandex.net/v2"

    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"OAuth {settings.tracker_token}",
            "X-Org-ID": settings.tracker_org_id,
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, headers=self._headers, **kwargs)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.exception("Tracker API HTTP error: %s %s", method, path)
            raise TrackerAPIError(f"Tracker API returned {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.HTTPError as exc:
            logger.exception("Tracker API transport error: %s %s", method, path)
            raise TrackerAPIError(f"Tracker API request failed: {exc}") from exc

    async def create_issue(
        self,
        queue: str,
        summary: str,
        description: str,
        tags: list[str] | None = None,
    ) -> dict:
        payload = {
            "queue": queue,
            "summary": summary,
            "description": description,
            "tags": tags or [],
        }
        data = await self._request("POST", "/issues", json=payload)
        return {"id": data.get("id"), "key": data.get("key"), "status": (data.get("status") or {}).get("key")}

    async def update_issue(
        self,
        issue_key: str,
        status: str | None = None,
        comment: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {}
        if status:
            payload["status"] = status
        if comment:
            payload["comment"] = comment
        return await self._request("PATCH", f"/issues/{issue_key}", json=payload)

    async def add_comment(self, issue_key: str, text: str) -> dict:
        return await self._request("POST", f"/issues/{issue_key}/comments", json={"text": text})

    async def get_issue(self, issue_key: str) -> dict:
        return await self._request("GET", f"/issues/{issue_key}")

    async def list_issues(self, queue: str, status: str | None = None) -> list[dict]:
        query = f'Queue: "{queue}"'
        if status:
            query = f'{query} AND Status: "{status}"'
        data = await self._request("POST", "/issues/_search", json={"query": query})
        if isinstance(data, list):
            return data
        return data.get("issues", [])
