"""Network guard: automated access to regulator websites is impossible from this process.

:func:`install_network_guard` wraps :func:`socket.getaddrinfo` and
:func:`socket.create_connection`, so every library that opens a connection (urllib, httpx, the
model client) is refused before any packet is sent to a denied domain. :func:`assert_url_allowed`
gives callers an explicit, early check with a clear error.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit


class RegulatorAccessBlocked(PermissionError):
    """Raised for any automated attempt to reach a regulator domain."""


class HostNotAllowed(PermissionError):
    """Raised when a URL's host is not on the allow list for that purpose."""


def _normalise_host(host: str) -> str:
    return host.strip().rstrip(".").lower()


def host_matches(host: str, domains: Iterable[str]) -> bool:
    """True if ``host`` equals one of ``domains`` or is a subdomain of one."""
    h = _normalise_host(host)
    return any(h == d or h.endswith("." + d) for d in (_normalise_host(x) for x in domains))


def assert_url_allowed(
    url: str, *, deny_domains: Iterable[str], allowed_hosts: Iterable[str] | None = None
) -> None:
    """Raise unless ``url`` may be requested automatically.

    Regulator domains are always refused. If ``allowed_hosts`` is given, the host must also be on
    it (for example, only the configured model provider for LLM calls).
    """
    host = urlsplit(url).hostname
    if not host:
        raise HostNotAllowed(f"URL has no host: {url!r}")
    if host_matches(host, deny_domains):
        raise RegulatorAccessBlocked(f"automated access to {host} is not allowed (regulator site)")
    if allowed_hosts is not None and not host_matches(host, allowed_hosts):
        raise HostNotAllowed(f"{host} is not an allowed host for this request")


_lock = threading.Lock()
_state: dict[str, Any] = {"getaddrinfo": None, "create_connection": None, "deny": ()}


def _check_host(host: Any) -> None:
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="ignore")
    if isinstance(host, str) and host_matches(host, _state["deny"]):
        raise RegulatorAccessBlocked(f"automated access to {host} is not allowed (regulator site)")


def _guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    _check_host(host)
    return _state["getaddrinfo"](host, *args, **kwargs)


def _guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
    _check_host(address[0])
    return _state["create_connection"](address, *args, **kwargs)


def install_network_guard(deny_domains: Iterable[str]) -> None:
    """Install (or update) the process-wide guard. Safe to call more than once."""
    with _lock:
        _state["deny"] = tuple(_normalise_host(d) for d in deny_domains)
        if socket.getaddrinfo is not _guarded_getaddrinfo:
            _state["getaddrinfo"] = socket.getaddrinfo
            socket.getaddrinfo = _guarded_getaddrinfo
        if socket.create_connection is not _guarded_create_connection:
            _state["create_connection"] = socket.create_connection
            socket.create_connection = _guarded_create_connection


def uninstall_network_guard() -> None:
    """Restore the functions that were in place before :func:`install_network_guard`."""
    with _lock:
        if socket.getaddrinfo is _guarded_getaddrinfo and _state["getaddrinfo"] is not None:
            socket.getaddrinfo = _state["getaddrinfo"]
        if (
            socket.create_connection is _guarded_create_connection
            and _state["create_connection"] is not None
        ):
            socket.create_connection = _state["create_connection"]
        _state.update(getaddrinfo=None, create_connection=None, deny=())


def network_guard_installed() -> bool:
    return socket.getaddrinfo is _guarded_getaddrinfo
