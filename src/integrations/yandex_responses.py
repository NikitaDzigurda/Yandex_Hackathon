"""Yandex AI Studio Responses API client."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from core.config import settings


class YandexResponsesError(Exception):
    """Raised when Yandex Responses API call fails."""


class YandexResponsesClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, project_id: str | None = None) -> None:
        self.api_key = (api_key if api_key is not None else settings.yandex_api_key).strip()
        self.base_url = (base_url if base_url is not None else settings.yandex_base_url).rstrip("/")
        self.project_id = (project_id if project_id is not None else settings.yandex_project_id).strip()

    async def async_call(
        self,
        prompt_id: str,
        input_text: str,
        timeout_sec: int = 300,
        retries: int = 3,
    ) -> tuple[str, dict[str, Any]]:
        if not self.api_key:
            raise YandexResponsesError("YANDEX_API_KEY is not configured")
        if not self.project_id:
            raise YandexResponsesError("YANDEX_PROJECT_ID is not configured")
        if not prompt_id:
            raise YandexResponsesError("Prompt ID is required")

        url = f"{self.base_url}/responses"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {self.api_key}",
            "OpenAI-Project": self.project_id,
        }
        payload = {"prompt": {"id": prompt_id}, "input": input_text}

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout_sec) as client:
                    response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                text = self._extract_text(data)
                if not text.strip():
                    raise YandexResponsesError("Empty response text from Yandex Responses API")
                return text, data
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(settings.yandex_retry_backoff_sec * attempt)
                else:
                    break
        raise YandexResponsesError(f"Failed calling prompt_id={prompt_id}: {last_error}")

    def _extract_text(self, data: dict[str, Any]) -> str:
        content = data.get("content")
        if isinstance(content, list):
            text = self._collect_texts(content)
            if text:
                return text

        output = data.get("output")
        if isinstance(output, list):
            text = self._collect_texts(output)
            if text:
                return text
        elif isinstance(output, dict):
            text = self._collect_texts([output])
            if text:
                return text
        elif isinstance(output, str) and output.strip():
            return output

        if isinstance(data.get("text"), str) and data["text"].strip():
            return data["text"]
        if isinstance(data.get("output_text"), str) and data["output_text"].strip():
            return data["output_text"]

        return json.dumps(data, ensure_ascii=False, indent=2)

    def _collect_texts(self, items: list[Any]) -> str:
        texts: list[str] = []

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                obj_type = obj.get("type")
                text_val = obj.get("text")
                if isinstance(text_val, str) and obj_type in (None, "output_text", "text"):
                    stripped = text_val.strip()
                    if stripped:
                        texts.append(stripped)
                for value in obj.values():
                    if isinstance(value, (dict, list)):
                        walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(items)
        unique: list[str] = []
        seen: set[str] = set()
        for value in texts:
            if value not in seen:
                seen.add(value)
                unique.append(value)
        return "\n\n".join(unique).strip()

    async def ping(self, prompt_id: str | None = None) -> bool:
        """Verify connectivity to Yandex AI Studio Responses API."""
        try:
            if not self.api_key or not self.project_id:
                return False
            # If no prompt_id provided, we just check if key/project are set
            if not prompt_id:
                return True
            
            await self.async_call(
                prompt_id=prompt_id,
                input_text="ping",
                timeout_sec=30,
                retries=1
            )
            return True
        except Exception:
            return False
