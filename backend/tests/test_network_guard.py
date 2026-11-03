import socket

import pytest

from tessera.governance.network import (
    HostNotAllowed,
    RegulatorAccessBlocked,
    assert_url_allowed,
    host_matches,
    install_network_guard,
    network_guard_installed,
    uninstall_network_guard,
)
from tessera.governance.policies import load_sources_policy

from .conftest import REPO_ROOT


@pytest.fixture
def network_policy():
    policy = load_sources_policy(REPO_ROOT / "policies").network
    install_network_guard(policy.deny_automated_domains)
    yield policy
    uninstall_network_guard()


@pytest.mark.parametrize(
    "host",
    [
        "www.dfsa.ae",
        "dfsa.ae",
        "WWW.VARA.AE",
        "www.uaecma.gov.ae",
        "centralbank.ae",
        "www.adgm.com",
    ],
)
def test_dns_lookups_of_regulator_hosts_are_blocked(network_policy, host):
    with pytest.raises(RegulatorAccessBlocked):
        socket.getaddrinfo(host, 443)


def test_connections_to_regulator_hosts_are_blocked(network_policy):
    with pytest.raises(RegulatorAccessBlocked):
        socket.create_connection(("www.dfsa.ae", 443), timeout=1)


def test_host_matching_is_exact_or_subdomain():
    assert host_matches("a.b.dfsa.ae", ["dfsa.ae"])
    assert not host_matches("notdfsa.ae", ["dfsa.ae"])
    assert not host_matches("dfsa.ae.example", ["dfsa.ae"])


def test_llm_calls_may_reach_only_the_configured_provider(network_policy):
    deny, allow = network_policy.deny_automated_domains, network_policy.allowed_llm_hosts
    assert_url_allowed(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        deny_domains=deny,
        allowed_hosts=allow,
    )
    with pytest.raises(HostNotAllowed):
        assert_url_allowed(
            "https://api.other-provider.example/v1", deny_domains=deny, allowed_hosts=allow
        )
    with pytest.raises(RegulatorAccessBlocked):
        assert_url_allowed("https://www.vara.ae/en/", deny_domains=deny, allowed_hosts=allow)


def test_uninstall_restores_the_previous_resolver():
    before = socket.getaddrinfo
    install_network_guard(["dfsa.ae"])
    assert network_guard_installed()
    install_network_guard(["dfsa.ae"])  # idempotent
    uninstall_network_guard()
    assert socket.getaddrinfo is before
    assert not network_guard_installed()
