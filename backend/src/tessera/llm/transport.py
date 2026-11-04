"""HTTPS transport to the OpenAI-compatible endpoint.

A plain ``httpx`` client keeps the request visible and adds no dependency beyond the HTTP library.
The host is checked against the policy when the transport is created, and the API key is sent only
in the ``Authorization`` header. It is never logged or included in an error.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from tessera.governance.network import assert_url_allowed
from tessera.governance.policies import NetworkPolicy
from tessera.llm.types import PermanentLLMError, RateLimited, TransientLLMError

_MAX_ERROR_BODY = 300


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None


class HttpChatTransport:
    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        *,
        network: NetworkPolicy,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        assert_url_allowed(
            f"{self._base_url}/chat/completions",
            deny_domains=network.deny_automated_domains,
            allowed_hosts=network.allowed_llm_hosts,
        )
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._headers = {
            "Authorization": f"Bearer {api_key.get_secret_value()}",
            "Accept": "application/json",
        }

    async def _send(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = await self._client.request(method, url, headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise TransientLLMError(f"network failure: {type(exc).__name__}") from exc
        status = response.status_code
        if status == 429:
            raise RateLimited("rate limited (HTTP 429)", _retry_after(response))
        if status >= 500:
            raise TransientLLMError(f"provider error (HTTP {status})")
        if status >= 400:
            raise PermanentLLMError(f"HTTP {status}: {response.text[:_MAX_ERROR_BODY]}")
        try:
            return response.json()
        except ValueError as exc:
            raise TransientLLMError("the provider returned invalid JSON") from exc

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._send("POST", "/chat/completions", json=payload)

    async def list_models(self) -> list[str]:
        data = await self._send("GET", "/models")
        return sorted(item["id"] for item in data.get("data", []) if "id" in item)

    async def aclose(self) -> None:
        await self._client.aclose()
