"""Builds the transport stack for live model calls."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from tessera.config.settings import Settings
from tessera.errors import PolicyError
from tessera.governance.network import install_network_guard
from tessera.governance.policies import load_sources_policy
from tessera.llm.client import CachingTransport, RateLimiter, ResilientTransport
from tessera.llm.config import ModelsPolicy
from tessera.llm.transport import HttpChatTransport
from tessera.llm.types import ChatTransport

MISSING_KEY = (
    "NVIDIA_API_KEY is not set. Create a free key at build.nvidia.com and add this line to the "
    ".env file at the repository root: NVIDIA_API_KEY=<your key>"
)


def build_live_transport(
    settings: Settings,
    models: ModelsPolicy,
    *,
    cache_path: Path | None = None,
    notify: Callable[[str, dict[str, Any]], None] | None = None,
) -> tuple[ChatTransport, HttpChatTransport]:
    """Return the stack to use, and the HTTP layer (for listing models and closing).

    The network guard is installed first, so nothing in this process can reach a regulator site.
    """
    key = settings.nvidia_api_key
    if key is None or not key.get_secret_value().strip():
        raise PolicyError(MISSING_KEY)
    network = load_sources_policy(settings.policies_dir).network
    install_network_guard(network.deny_automated_domains)
    http = HttpChatTransport(
        models.provider.base_url,
        key,
        network=network,
        timeout_seconds=models.rate_limit.request_timeout_seconds,
    )
    limiter = RateLimiter(models.rate_limit.requests_per_minute)
    transport: ChatTransport = ResilientTransport(http, limiter, models.rate_limit, notify=notify)
    if cache_path is not None:
        transport = CachingTransport(transport, cache_path)
    return transport, http
