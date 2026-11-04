"""The guarded path to the model: parsing, rate limit, retries, cache, transport and leak checks."""

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from tessera.config.settings import load_settings
from tessera.errors import GoldLabelLeak, PolicyError, RestrictedValueLeak
from tessera.governance.masking import MaskingGateway, RestrictedValue
from tessera.governance.network import HostNotAllowed, RegulatorAccessBlocked
from tessera.governance.policies import load_sources_policy
from tessera.llm.client import CachingTransport, GuardedLLM, RateLimiter, ResilientTransport
from tessera.llm.config import RateLimitConfig, load_models_policy
from tessera.llm.jsonio import extract_json_object, strip_reasoning
from tessera.llm.stack import build_live_transport
from tessera.llm.testing import ScriptedTransport, chat_reply, tool_reply
from tessera.llm.transport import HttpChatTransport
from tessera.llm.types import (
    LLMError,
    PermanentLLMError,
    RateLimited,
    TransientLLMError,
    parse_chat_response,
)

from .conftest import REPO_ROOT, make_settings

POLICIES = REPO_ROOT / "policies"
NETWORK = load_sources_policy(POLICIES).network
LIMITS = RateLimitConfig(
    requests_per_minute=60,
    max_concurrent=2,
    max_attempts=3,
    base_backoff_seconds=1,
    max_backoff_seconds=8,
    request_timeout_seconds=30,
)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def resilient(script, time: FakeTime | None = None, notify=None):
    clock = time or FakeTime()
    inner = ScriptedTransport(script)
    limiter = RateLimiter(60, clock=clock.clock, sleep=clock.sleep)
    return (
        ResilientTransport(
            inner, limiter, LIMITS, sleep=clock.sleep, rng=lambda: 1.0, notify=notify
        ),
        inner,
        clock,
    )


# ------------------------------------------------------------------- parsing


def test_tool_calls_and_usage_are_parsed():
    response = parse_chat_response(tool_reply(("lookup", {"name": "x"})))
    assert response.tool_calls[0].name == "lookup"
    assert json.loads(response.tool_calls[0].arguments) == {"name": "x"}
    assert response.usage.total_tokens == 120


def test_reasoning_is_kept_apart_from_content():
    response = parse_chat_response(chat_reply("{}", reasoning="thinking aloud"))
    assert response.content == "{}" and response.reasoning == "thinking aloud"


def test_a_response_without_choices_is_an_error():
    with pytest.raises(LLMError):
        parse_chat_response({"choices": []})


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        'Here you go:\n```json\n{"a": 1}\n```',
        '<think>hmm {"b": 2}</think>{"a": 1}',
        'hmm, the cut-off opening tag</think>\n{"a": 1}',
        'Sure! {"a": 1} Hope that helps.',
    ],
)
def test_json_is_extracted_tolerantly(text):
    assert extract_json_object(text) == {"a": 1}


@pytest.mark.parametrize("text", ["", "no json here", "{broken", "[1, 2]"])
def test_replies_without_a_json_object_are_rejected(text):
    with pytest.raises(ValueError):
        extract_json_object(text)


def test_reasoning_blocks_are_stripped():
    assert strip_reasoning("<think>a</think>b") == "b"


# ------------------------------------------------------------------- rate limiter and retries


def test_requests_are_spaced_evenly():
    time = FakeTime()
    limiter = RateLimiter(60, clock=time.clock, sleep=time.sleep)

    async def run():
        for _ in range(3):
            await limiter.acquire()

    asyncio.run(run())
    assert time.sleeps == [1.0, 1.0]


def test_a_429_pushes_later_requests_back():
    time = FakeTime()
    limiter = RateLimiter(60, clock=time.clock, sleep=time.sleep)
    limiter.penalize(30)

    asyncio.run(limiter.acquire())
    assert time.sleeps == [30]


def test_transient_failures_are_retried_with_backoff():
    transport, inner, time = resilient([TransientLLMError("boom"), chat_reply("ok")])
    result = asyncio.run(transport.chat({"model": "m"}))
    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(inner.payloads) == 2
    assert 1.0 in time.sleeps


def test_retry_after_is_honoured_and_reported():
    events = []
    transport, _, time = resilient(
        [RateLimited("slow down", retry_after=20), chat_reply("ok")],
        notify=lambda kind, info: events.append((kind, info)),
    )
    asyncio.run(transport.chat({"model": "m"}))
    assert 20 in time.sleeps
    assert events[0][0] == "rate_limited"


def test_retries_stop_after_max_attempts():
    transport, inner, _ = resilient([TransientLLMError("x") for _ in range(5)])
    with pytest.raises(TransientLLMError):
        asyncio.run(transport.chat({"model": "m"}))
    assert len(inner.payloads) == LIMITS.max_attempts


def test_permanent_failures_are_not_retried():
    transport, inner, _ = resilient([PermanentLLMError("HTTP 400")])
    with pytest.raises(PermanentLLMError):
        asyncio.run(transport.chat({"model": "m"}))
    assert len(inner.payloads) == 1


# ------------------------------------------------------------------- replay cache


def test_identical_requests_are_answered_from_the_replay_cache():
    inner = ScriptedTransport([chat_reply("first"), chat_reply("second")])
    cache = CachingTransport(inner, ":memory:")

    async def run():
        return [
            await cache.chat({"model": "m", "n": 1}),
            await cache.chat({"n": 1, "model": "m"}),
            await cache.chat({"model": "m", "n": 2}),
        ]

    first, repeat, other = asyncio.run(run())
    assert first == repeat and other != first
    assert cache.hits == 1 and len(inner.payloads) == 2


# ------------------------------------------------------------------- the guarded client


GATEWAY = MaskingGateway([RestrictedValue("lumencrest-capital.example", "domain")])


def test_restricted_values_are_masked_before_sending():
    inner = ScriptedTransport([chat_reply("ok")])
    llm = GuardedLLM(inner, GATEWAY)
    payload = {"messages": [{"role": "user", "content": "see lumencrest-capital.example"}]}
    asyncio.run(llm.complete(payload))
    assert "lumencrest" not in json.dumps(inner.payloads[0], ensure_ascii=False)


def test_a_payload_that_would_leak_is_not_sent():
    class BrokenGateway(MaskingGateway):
        def mask_payload(self, payload):  # a masking bug
            return payload

    inner = ScriptedTransport([chat_reply("ok")])
    gateway = BrokenGateway([RestrictedValue("lumencrest-capital.example", "domain")])
    llm = GuardedLLM(inner, gateway)
    with pytest.raises(RestrictedValueLeak):
        asyncio.run(llm.complete({"content": "see lumencrest-capital.example"}))
    assert inner.payloads == []


def test_gold_fields_never_reach_a_model():
    inner = ScriptedTransport([chat_reply("ok")])
    llm = GuardedLLM(inner, MaskingGateway([]))
    with pytest.raises(GoldLabelLeak):
        asyncio.run(llm.complete({"messages": [{"gold_label": "CONFLICTS"}]}))
    assert inner.payloads == []


# ------------------------------------------------------------------- HTTP transport


def http_transport(handler) -> HttpChatTransport:
    return HttpChatTransport(
        "https://integrate.api.nvidia.com/v1",
        SecretStr("test-key-not-real"),
        network=NETWORK,
        timeout_seconds=5,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_http_success_and_auth_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json=chat_reply("hello"))

    result = asyncio.run(http_transport(handler).chat({"model": "m"}))
    assert result["choices"][0]["message"]["content"] == "hello"
    assert seen["auth"] == "Bearer test-key-not-real"
    assert seen["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"


@pytest.mark.parametrize(
    ("status", "error"),
    [(429, RateLimited), (503, TransientLLMError), (400, PermanentLLMError)],
)
def test_http_errors_are_classified(status, error):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"retry-after": "7"}, text="nope")

    with pytest.raises(error) as caught:
        asyncio.run(http_transport(handler).chat({"model": "m"}))
    if status == 429:
        assert caught.value.retry_after == 7
    assert "test-key-not-real" not in str(caught.value)


def test_network_failures_are_transient():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(TransientLLMError):
        asyncio.run(http_transport(handler).chat({"model": "m"}))


def test_model_listing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]})

    assert asyncio.run(http_transport(handler).list_models()) == ["a", "b"]


def test_only_the_configured_provider_can_be_reached():
    with pytest.raises(HostNotAllowed):
        HttpChatTransport(
            "https://api.other.example/v1", SecretStr("k"), network=NETWORK, timeout_seconds=5
        )
    with pytest.raises(RegulatorAccessBlocked):
        HttpChatTransport(
            "https://www.vara.ae/v1", SecretStr("k"), network=NETWORK, timeout_seconds=5
        )


# ------------------------------------------------------------------- configuration


def test_model_policy_loads_and_every_role_is_a_candidate():
    policy = load_models_policy(POLICIES)
    assert policy.rate_limit.requests_per_minute < 40  # stays under the free tier
    for role, model in policy.roles.items():
        assert model in policy.candidates[role]
    assert policy.decoding.temperature == 0
    assert policy.options_for(policy.roles["primary"])


def test_thinking_can_be_overridden_for_a_comparison():
    policy = load_models_policy(POLICIES)
    primary = policy.roles["primary"]
    off = policy.with_thinking(False)
    assert off.options_for(primary)["chat_template_kwargs"] == {"enable_thinking": False}
    assert policy.options_for(primary)["chat_template_kwargs"] == {"enable_thinking": True}


def test_a_clear_message_when_the_key_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    settings = make_settings(tmp_path / "data")
    with pytest.raises(PolicyError, match=r"NVIDIA_API_KEY is not set"):
        build_live_transport(settings, load_models_policy(POLICIES))


def test_the_key_is_read_from_the_root_env_file_and_never_shown(tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    (tmp_path / ".env").write_text("NVIDIA_API_KEY=not-a-real-key\n", encoding="utf-8")
    settings = load_settings(root=tmp_path)
    assert settings.nvidia_api_key.get_secret_value() == "not-a-real-key"
    assert "not-a-real-key" not in repr(settings)
