"""Async Yandex Cloud Foundation Models client."""

import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class YCAgentError(Exception):
    """Raised when Yandex Cloud API invocation fails."""


class YandexCloudAgentClient:
    base_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Api-Key {settings.yc_api_key}",
            "Content-Type": "application/json",
        }

    def build_model_uri(self, model_name: str) -> str:
        return f"gpt://{settings.yc_folder_id}/{model_name}/latest"

    async def invoke_agent(
        self,
        model_uri: str,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ) -> str:
        payload = {
            "modelUri": model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": str(max_tokens),
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_message},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.base_url, json=payload, headers=self._headers)
            response.raise_for_status()
            data = response.json()
            return data["result"]["alternatives"][0]["message"]["text"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            logger.exception("Yandex Cloud agent invocation failed")
            raise YCAgentError(f"Yandex Cloud request failed: {exc}") from exc
