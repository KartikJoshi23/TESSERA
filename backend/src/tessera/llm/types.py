"""OpenAI-compatible request and response shapes, and the transport interface."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from tessera.errors import TesseraError
from tessera.llm.config import DecodingConfig


class LLMError(TesseraError):
    """Base class for model-access failures."""


class TransientLLMError(LLMError):
    """A failure worth retrying: a timeout, a dropped connection or a 5xx response."""


class RateLimited(TransientLLMError):
    """HTTP 429."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PermanentLLMError(LLMError):
    """A failure that retrying will not fix, such as a bad request or a bad key."""


class ChatTransport(Protocol):
    """Anything that can answer a chat-completions payload. Tests use a scripted one."""

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: str


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = ""
    #: Reasoning text, if the model returned any. Shown to humans; never passed between agents.
    reasoning: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    usage: Usage = Usage()
    model: str | None = None
    response_id: str | None = None


def parse_chat_response(data: dict[str, Any]) -> ChatResponse:
    """Read an OpenAI-format response. Raises ``LLMError`` if it has no usable choice."""
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("the model returned no choices")
    choice = choices[0]
    message = choice.get("message") or {}
    calls = [
        ToolCall(
            id=call.get("id") or f"call_{index}",
            name=(call.get("function") or {}).get("name") or "",
            arguments=(call.get("function") or {}).get("arguments") or "{}",
        )
        for index, call in enumerate(message.get("tool_calls") or [])
    ]
    usage = data.get("usage") or {}
    return ChatResponse(
        content=message.get("content") or "",
        reasoning=message.get("reasoning_content") or message.get("reasoning"),
        tool_calls=tuple(calls),
        finish_reason=choice.get("finish_reason"),
        usage=Usage(
            prompt_tokens=usage.get("prompt_tokens") or 0,
            completion_tokens=usage.get("completion_tokens") or 0,
            total_tokens=usage.get("total_tokens") or 0,
        ),
        model=data.get("model"),
        response_id=data.get("id"),
    )


def build_payload(
    *,
    model: str,
    messages: list[dict[str, Any]],
    decoding: DecodingConfig,
    tools: list[dict[str, Any]] | None = None,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble one chat-completions request."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": decoding.temperature,
        "max_tokens": decoding.max_tokens,
        "stream": False,
    }
    if decoding.seed is not None:
        payload["seed"] = decoding.seed
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if extra_body:
        payload.update(extra_body)
    return payload
