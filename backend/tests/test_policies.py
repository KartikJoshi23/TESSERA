from pathlib import Path

import pytest
import yaml

from tessera.errors import PolicyError
from tessera.governance.language import lint_text
from tessera.governance.policies import (
    UAE_REGULATORS,
    load_decision_policy,
    load_language_policy,
    load_policies,
    load_sources_policy,
)
from tessera.protocol.contacts import DEFAULT_CONTACT_ROLES

from .conftest import REPO_ROOT

POLICIES = REPO_ROOT / "policies"


def test_no_regulator_source_allows_automated_access_or_framing():
    policy = load_sources_policy(POLICIES)
    regulator_sources = [s for s in policy.sources.values() if s.regulator in UAE_REGULATORS]
    assert regulator_sources
    for source in regulator_sources:
        assert not source.automated_access, source.id
        assert not source.framing_allowed, source.id


def test_dfsa_sources_are_restricted_and_homepage_only():
    policy = load_sources_policy(POLICIES)
    for source_id in ("dfsa_register", "dfsa_alerts"):
        source = policy.source(source_id)
        assert source.restricted
        assert source.storage == "restricted_facts"
        assert not source.deep_links_allowed and source.page_url is None
        assert source.homepage == "https://www.dfsa.ae/"


def test_every_regulator_domain_is_denied():
    deny = load_sources_policy(POLICIES).network.deny_automated_domains
    for domain in (
        "dfsa.ae",
        "uaecma.gov.ae",
        "sca.gov.ae",
        "vara.ae",
        "centralbank.ae",
        "adgm.com",
    ):
        assert domain in deny


def test_policy_that_weakens_a_rule_is_rejected(tmp_path: Path):
    data = yaml.safe_load((POLICIES / "sources.yaml").read_text(encoding="utf-8"))
    data["sources"]["cma_licensed"]["automated_access"] = True
    (tmp_path / "sources.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(PolicyError, match="automated access"):
        load_sources_policy(tmp_path)


def test_restricted_source_cannot_gain_deep_links(tmp_path: Path):
    data = yaml.safe_load((POLICIES / "sources.yaml").read_text(encoding="utf-8"))
    data["sources"]["dfsa_alerts"]["deep_links_allowed"] = True
    (tmp_path / "sources.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(PolicyError, match="homepage only"):
        load_sources_policy(tmp_path)


def test_language_and_decision_policies_agree_on_result_wording():
    language = load_language_policy(POLICIES)
    decision = load_decision_policy(POLICIES)
    assert language.result_strings == decision.outcomes
    assert decision.outcomes["UNVERIFIED"] == "Could not verify"


def test_decision_policy_lists_every_rule():
    decision = load_decision_policy(POLICIES)
    assert [r.id for r in decision.hard_conflicts] == [f"HC{i}" for i in range(1, 7)]
    assert [r.id for r in decision.consistent_conditions] == [f"K{i}" for i in range(1, 8)]


def test_contact_roles_in_code_match_the_policy():
    decision = load_decision_policy(POLICIES)
    assert {
        kind.value: role.value for kind, role in DEFAULT_CONTACT_ROLES.items()
    } == decision.contact_roles


def test_the_policys_own_wording_passes_the_language_policy():
    """Reports quote these texts, so they must follow the rules a report is held to."""
    policies = load_policies(REPO_ROOT / "policies")
    decision = policies.decision
    rules = (
        *decision.hard_conflicts,
        *decision.consistent_conditions,
        *decision.unverified_reasons,
    )
    assert not [r.id for r in rules if lint_text(r.text, policies.language)]
