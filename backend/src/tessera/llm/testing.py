"""A scripted transport, so agents and the runner can be tested without a model or a network."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterable
from typing import Any

Reply = dict[str, Any] | Exception | Callable[[dict[str, Any]], dict[str, Any]]


def chat_reply(
    content: str = "",
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str | None = None,
    reasoning: str | None = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
) -> dict[str, Any]:
    """A response in OpenAI format."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if reasoning:
        message["reasoning_content"] = reasoning
    return {
        "id": "scripted",
        "model": "scripted-model",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop"),
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def tool_reply(*calls: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    """A response that calls one or more tools, for example ``tool_reply(("x", {"a": 1}))``."""
    return chat_reply(
        tool_calls=[
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
            for index, (name, arguments) in enumerate(calls)
        ]
    )


def json_reply(value: dict[str, Any]) -> dict[str, Any]:
    """A final response whose content is a JSON object."""
    return chat_reply(json.dumps(value, ensure_ascii=False))


class ScriptedTransport:
    """Returns scripted replies in order and records every payload it receives.

    A reply may be a response dict, an exception to raise, or a function of the payload.
    """

    def __init__(self, script: Iterable[Reply] = ()) -> None:
        self._script = list(script)
        self.payloads: list[dict[str, Any]] = []

    def extend(self, *replies: Reply) -> None:
        self._script.extend(replies)

    @property
    def remaining(self) -> int:
        return len(self._script)

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(copy.deepcopy(payload))
        if not self._script:
            raise AssertionError("the scripted transport ran out of replies")
        reply = self._script.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply(payload) if callable(reply) else reply
