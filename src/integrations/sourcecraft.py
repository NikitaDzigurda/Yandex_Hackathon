"""Async Sourcecraft API client."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class SourcecraftAPIError(Exception):
    """Raised when Sourcecraft API call fails."""


class SourcecraftClient:
    def __init__(self) -> None:
        self.base_url = settings.sourcecraft_base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {settings.sourcecraft_token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict | list:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, headers=self._headers, **kwargs)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.exception("Sourcecraft API HTTP error: %s %s", method, path)
            raise SourcecraftAPIError(
                f"Sourcecraft API returned {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.exception("Sourcecraft API transport error: %s %s", method, path)
            raise SourcecraftAPIError(f"Sourcecraft API request failed: {exc}") from exc

    async def get_repo_activity(self, repo_id: str, days: int = 7) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        data = await self._request("GET", f"/repos/{repo_id}/activity", params={"since": since})
        return {
            "commits": data.get("commits", 0),
            "prs": data.get("prs", 0),
            "contributors": data.get("contributors", []),
        }

    async def get_commits(self, repo_id: str, limit: int = 20) -> list[dict]:
        data = await self._request("GET", f"/repos/{repo_id}/commits", params={"limit": limit})
        if isinstance(data, list):
            commits = data
        else:
            commits = data.get("commits", [])
        return [
            {
                "sha": item.get("sha"),
                "message": item.get("message"),
                "author": item.get("author"),
                "date": item.get("date") or item.get("committed_at"),
            }
            for item in commits
        ]

    async def get_pr_status(self, repo_id: str) -> list[dict]:
        data = await self._request("GET", f"/repos/{repo_id}/pulls")
        pulls = data if isinstance(data, list) else data.get("pulls", [])
        return [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "state": item.get("state"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
            for item in pulls
        ]

    async def list_repos(self, project_name: str | None = None) -> list[dict]:
        data = await self._request("GET", "/repos")
        repos = data if isinstance(data, list) else data.get("repos", [])
        if not project_name:
            return repos
        needle = project_name.lower()
        return [repo for repo in repos if needle in (repo.get("name", "")).lower()]
