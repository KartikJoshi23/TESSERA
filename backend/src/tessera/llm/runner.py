"""The agent runner: one code path for every model turn, crew and baselines alike.

A turn is a tool loop that ends in one JSON object:

1. The model answers with tool calls or a final message.
2. Tool calls run locally, and their results go back to the model.
3. The final message must be valid JSON for the agent's output schema. If it is not, the model
   gets one chance to repair it (a tolerated, counted event).
4. A turn that still fails becomes an ``agent.failed`` event and resolves as reason U7. A failure
   never switches to another model.

The message history is append-only within a turn, and reasoning text is never sent back.
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from tessera.blackboard.board import Blackboard
from tessera.errors import RequestBudgetExceeded
from tessera.llm.client import GuardedLLM
from tessera.llm.config import DecodingConfig, LimitsConfig
from tessera.llm.jsonio import extract_json_object, strip_reasoning
from tessera.llm.prompts import RenderedPrompt
from tessera.llm.types import ChatResponse, LLMError, build_payload
from tessera.protocol.common import AgentId
from tessera.protocol.evidence import canonical_json

_MAX_REPAIR_ERRORS = 6
_MAX_REASONING_LOGGED = 1500
_TOOLS_USED_UP = (
    "You have used all your tool calls for this turn. "
    "Reply now with the final JSON object, using what you already have."
)


class Belt(Protocol):
    """The part of the tool belt the runner needs."""

    def definitions(self, names: Any) -> list[dict[str, Any]]: ...

    def execute(
        self, name: str, raw_arguments: str, *, allowed: Any, actor: AgentId, round: int = 0
    ) -> tuple[str, bool]: ...


@dataclass
class UsageMeter:
    """Counts model requests and tokens for one case, and enforces its request budget."""

    max_requests: int
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    by_agent: Counter[str] = field(default_factory=Counter)

    def check(self) -> None:
        if self.requests >= self.max_requests:
            raise RequestBudgetExceeded(f"request budget of {self.max_requests} used up")

    def add(self, agent: AgentId, response: ChatResponse) -> None:
        self.requests += 1
        self.prompt_tokens += response.usage.prompt_tokens
        self.completion_tokens += response.usage.completion_tokens
        self.by_agent[agent.value] += 1


@dataclass(frozen=True)
class AgentSpec:
    agent_id: AgentId
    system: RenderedPrompt
    output_model: type[BaseModel]
    tool_names: tuple[str, ...] = ()
    #: Extra checks on a valid output, for example unknown activity codes. Problems trigger repair.
    check_output: Callable[[Any], list[str]] | None = None


@dataclass
class TurnResult:
    agent_id: AgentId
    output: Any | None = None
    failure: str | None = None
    requests: int = 0
    tool_calls: int = 0
    repairs: int = 0
    reasoning: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.output is not None


def _assistant_message(response: ChatResponse) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": strip_reasoning(response.content)}
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in response.tool_calls
        ]
    return message


class AgentRunner:
    def __init__(
        self,
        llm: GuardedLLM,
        belt: Belt,
        board: Blackboard,
        *,
        model: str,
        decoding: DecodingConfig,
        limits: LimitsConfig,
        meter: UsageMeter,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self._llm = llm
        self._belt = belt
        self._board = board
        self.model = model
        self._decoding = decoding
        self._limits = limits
        self.meter = meter
        self._extra_body = extra_body or {}

    def _parse(self, spec: AgentSpec, text: str) -> tuple[Any | None, list[str]]:
        """Validate a final message. The model's output is masked again before it is trusted."""
        try:
            data = self._board.gateway.mask_payload(extract_json_object(text))
            output = spec.output_model.model_validate(data)
        except ValueError as exc:  # includes pydantic's ValidationError
            return None, _describe(exc)
        problems = spec.check_output(output) if spec.check_output else []
        return (None, problems) if problems else (output, [])

    async def _complete(
        self, spec: AgentSpec, messages: list[dict[str, Any]], tools: Any, round: int
    ) -> ChatResponse:
        self.meter.check()
        payload = build_payload(
            model=self.model,
            messages=messages,
            decoding=self._decoding,
            tools=tools,
            extra_body=self._extra_body,
        )
        request_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]
        started = time.monotonic()
        response = await self._llm.complete(payload)
        latency = int((time.monotonic() - started) * 1000)
        self.meter.add(spec.agent_id, response)
        reasoning = (response.reasoning or "")[:_MAX_REASONING_LOGGED]
        self._board.record(
            "llm.response",
            spec.agent_id,
            {
                "round": round,
                "model": response.model or self.model,
                "request_sha256": request_hash,
                "finish_reason": response.finish_reason,
                "tool_calls": [call.name for call in response.tool_calls],
                "reasoning": self._board.gateway.mask(reasoning),
            },
            usage=response.usage.model_dump(),
            latency_ms=latency,
        )
        return response

    def _fail(self, result: TurnResult, code: str, detail: str = "") -> TurnResult:
        result.failure = code
        self._board.note_failure(result.agent_id, code, detail)
        return result

    async def run(self, spec: AgentSpec, user_content: str, *, round: int = 0) -> TurnResult:
        """Run one agent turn. Leak errors are never caught: they must stop the run."""
        result = TurnResult(agent_id=spec.agent_id)
        self._board.record(
            "agent.activated",
            spec.agent_id,
            {"round": round, "model": self.model, "prompt_sha256": spec.system.sha256},
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": spec.system.text},
            {"role": "user", "content": user_content},
        ]
        tools = self._belt.definitions(spec.tool_names) if spec.tool_names else None
        cap = self._limits.tool_calls_per_turn
        while True:
            offered = tools if result.tool_calls < cap else None
            try:
                response = await self._complete(spec, messages, offered, round)
            except RequestBudgetExceeded as exc:
                self._board.record("budget.exceeded", spec.agent_id, {"detail": str(exc)})
                return self._fail(result, "budget_exceeded", str(exc))
            except LLMError as exc:
                return self._fail(result, "model_error", str(exc))
            result.requests += 1
            if response.reasoning:
                result.reasoning.append(self._board.gateway.mask(response.reasoning))
            if response.finish_reason == "content_filter":
                return self._fail(result, "refused", "the provider's filter stopped the reply")

            if response.tool_calls and offered:
                messages.append(_assistant_message(response))
                for call in response.tool_calls:
                    result.tool_calls += 1
                    content, _ = self._belt.execute(
                        call.name,
                        call.arguments,
                        allowed=spec.tool_names,
                        actor=spec.agent_id,
                        round=round,
                    )
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
                if result.tool_calls >= cap:
                    messages.append({"role": "user", "content": _TOOLS_USED_UP})
                continue

            output, problems = self._parse(spec, response.content)
            if output is not None:
                result.output = output
                return result
            if result.repairs >= self._limits.repair_attempts:
                return self._fail(result, "invalid_output", "; ".join(problems))
            result.repairs += 1
            self._board.record(
                "agent.repair", spec.agent_id, {"round": round, "problems": problems[:3]}
            )
            messages.append(_assistant_message(response))
            messages.append({"role": "user", "content": _repair_request(problems)})


def _describe(exc: ValueError) -> list[str]:
    if isinstance(exc, ValidationError):
        return [
            f"{'.'.join(str(part) for part in error['loc']) or 'value'}: {error['msg']}"
            for error in exc.errors()
        ]
    return [str(exc)]


def _repair_request(problems: list[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems[:_MAX_REPAIR_ERRORS])
    return (
        "Your reply could not be used:\n"
        f"{listed}\n"
        "Reply again with one corrected JSON object that matches the output shape, "
        "and nothing else."
    )
