"""Rate limiting, retries, the development replay cache, and the guarded model client."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import sqlite3
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from tessera.errors import GoldLabelLeak, RestrictedValueLeak
from tessera.governance.masking import MaskingGateway
from tessera.llm.config import RateLimitConfig
from tessera.llm.types import (
    ChatResponse,
    ChatTransport,
    RateLimited,
    TransientLLMError,
    parse_chat_response,
)
from tessera.protocol.evidence import canonical_json

Sleep = Callable[[float], Awaitable[None]]
Notify = Callable[[str, dict[str, Any]], None]


class RateLimiter:
    """Spaces requests evenly. One instance is shared by every agent in a run."""

    def __init__(
        self,
        requests_per_minute: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._interval = 60.0 / requests_per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0

    async def acquire(self) -> float:
        """Wait for the next free slot. Returns the seconds waited."""
        now = self._clock()
        slot = max(now, self._next_slot)
        self._next_slot = slot + self._interval  # reserved before sleeping, so waits never overlap
        wait = slot - now
        if wait > 0:
            await self._sleep(wait)
        return wait

    def penalize(self, seconds: float) -> None:
        """Push every later request back, after the provider says we are going too fast."""
        self._next_slot = max(self._next_slot, self._clock() + seconds)


#: Past the HTTP client's own timeouts, so those fire first and give their own reason.
_DEADLINE_GRACE_SECONDS = 60


class ResilientTransport:
    """Applies the shared rate limit, caps concurrency and retries transient failures.

    Every wait is bounded. A request that has not finished by its deadline is cut off and retried,
    however slowly its bytes arrive, and a provider's request to wait is honoured only up to the
    longest backoff. Either could otherwise stall a run for hours with nothing to show for it.
    """

    def __init__(
        self,
        inner: ChatTransport,
        limiter: RateLimiter,
        config: RateLimitConfig,
        *,
        notify: Notify | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        deadline: float | None = None,
    ) -> None:
        self._inner = inner
        self._limiter = limiter
        self._config = config
        self._notify = notify or (lambda _kind, _info: None)
        self._sleep = sleep
        self._rng = rng
        self._slots = asyncio.Semaphore(config.max_concurrent)
        self._deadline = (
            deadline
            if deadline is not None
            else config.request_timeout_seconds + _DEADLINE_GRACE_SECONDS
        )

    def _backoff(self, attempt: int) -> float:
        ceiling = self._config.base_backoff_seconds * (2 ** (attempt - 1))
        return min(self._config.max_backoff_seconds, ceiling) * (0.5 + self._rng() / 2)

    async def _within_deadline(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(self._inner.chat(payload), self._deadline)
        except TimeoutError as exc:
            raise TransientLLMError(f"no reply within {self._deadline:g} seconds") from exc

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._slots:
                    await self._limiter.acquire()
                    return await self._within_deadline(payload)
            except RateLimited as exc:
                asked = exc.retry_after
                cap = self._config.max_backoff_seconds
                delay = min(asked, cap) if asked else self._backoff(attempt)
                self._limiter.penalize(delay)
                self._notify(
                    "rate_limited",
                    {"attempt": attempt, "delay_seconds": round(delay, 1), "asked_seconds": asked},
                )
                if attempt >= self._config.max_attempts:
                    raise
            except TransientLLMError as exc:
                delay = self._backoff(attempt)
                self._notify("llm.retry", {"attempt": attempt, "reason": str(exc)[:120]})
                if attempt >= self._config.max_attempts:
                    raise
            await self._sleep(delay)


class CachingTransport:
    """Development replay cache: answers identical requests locally, to save free quota.

    It stores only masked requests, because it sits below the masking layer. Evaluation runs never
    use it.
    """

    def __init__(self, inner: ChatTransport, path: Path | str) -> None:
        self._inner = inner
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("CREATE TABLE IF NOT EXISTS replay (key TEXT PRIMARY KEY, body TEXT)")
        self._conn.commit()
        self.hits = 0

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        row = self._conn.execute("SELECT body FROM replay WHERE key = ?", (key,)).fetchone()
        if row is not None:
            self.hits += 1
            return json.loads(row[0])
        response = await self._inner.chat(payload)
        self._conn.execute(
            "INSERT OR REPLACE INTO replay (key, body) VALUES (?, ?)",
            (key, json.dumps(response, ensure_ascii=False)),
        )
        self._conn.commit()
        return response


def _gold_keys(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        found = [key for key in payload if isinstance(key, str) and key.startswith("gold_")]
        for value in payload.values():
            found += _gold_keys(value)
        return found
    if isinstance(payload, list | tuple):
        return [key for item in payload for key in _gold_keys(item)]
    return []


class GuardedLLM:
    """The only way agents reach a model. Two invariants are checked on every request:

    * no restricted value leaves the machine (requirement R21);
    * no gold label reaches a system under test.

    A failed check raises, so nothing is sent.
    """

    def __init__(self, transport: ChatTransport, gateway: MaskingGateway) -> None:
        self._transport = transport
        self._gateway = gateway

    async def complete(self, payload: dict[str, Any]) -> ChatResponse:
        masked = self._gateway.mask_payload(payload)
        if self._gateway.leaked_values(json.dumps(masked, ensure_ascii=False)):
            raise RestrictedValueLeak("a model request still held restricted values; not sent")
        if gold := _gold_keys(masked):
            raise GoldLabelLeak(f"a model request held gold fields {sorted(set(gold))}; not sent")
        return parse_chat_response(await self._transport.chat(masked))
