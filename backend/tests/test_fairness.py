"""The fairness contract (§10.1): only the orchestration differs between conditions.

Each case records everything it ran with. These tests compare those records, so a difference nobody
planned fails here rather than quietly changing the comparison.
"""

import re
from typing import Any

import pytest

from tessera.agents.base import Task
from tessera.agents.crew import build_crew, build_stack
from tessera.agents.toolbelt import TOOLS
from tessera.baseline.single_agent import SingleAgent
from tessera.blackboard.store import EventStore
from tessera.devdata import load_smoke_cases
from tessera.experiment import SC5_TEMPERATURE, open_condition
from tessera.knowledge import load_activity_taxonomy, load_rule_cards
from tessera.llm.config import load_models_policy
from tessera.llm.testing import ScriptedTransport
from tessera.protocol.case import SystemCondition
from tessera.protocol.common import AgentId

from .conftest import REPO_ROOT

MODELS = load_models_policy(REPO_ROOT / "policies")
OFFER = load_smoke_cases(REPO_ROOT)[8].offer()
PROMPTS = REPO_ROOT / "backend" / "prompts" / "v1"
#: Files of guidance that every system must get in the same words.
GUIDES = (
    "_shared",
    "_jurisdiction_guide",
    "_regulator_guide",
    "_contact_guide",
    "_decision_guide",
    "regulator_cma",
    "regulator_dfsa",
    "regulator_vara",
)
#: The only settings a condition may change, and how.
PLANNED: dict[SystemCondition, set[str]] = {
    SystemCondition.CREW_FULL: set(),
    SystemCondition.CREW_SHARE: set(),
    SystemCondition.CREW_SILO: set(),
    SystemCondition.CREW_NV: set(),
    SystemCondition.RULES_ONLY: set(),
    SystemCondition.SA_BASE: {"limits.tool_calls_per_turn"},
    SystemCondition.SA_VER: {"limits.tool_calls_per_turn"},
    SystemCondition.SA_SC5: {"limits.tool_calls_per_turn", "decoding.temperature"},
    SystemCondition.SA_MAX: {"limits.tool_calls_per_turn", "decoding.max_tokens"},
    SystemCondition.SA_LARGER: {"limits.tool_calls_per_turn", "model", "model_options"},
}


def flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, item in value.items():
        name = f"{prefix}{key}"
        if isinstance(item, dict) and item and key != "chat_template_kwargs":
            flat.update(flatten(item, f"{name}."))
        else:
            flat[name] = item
    return flat


def difference(first: dict[str, Any], second: dict[str, Any]) -> set[str]:
    one, other = flatten(first), flatten(second)
    return {key for key in one.keys() | other.keys() if one.get(key) != other.get(key)}


@pytest.fixture
def stack(populated_settings):
    return build_stack(populated_settings, ScriptedTransport(), EventStore(), MODELS)


def config_of(stack, condition: SystemCondition) -> dict[str, Any]:
    env = open_condition(stack, f"case-{condition.value}", OFFER, condition=condition)
    return env.board.case.config


@pytest.mark.parametrize("condition", list(SystemCondition))
def test_a_condition_changes_only_what_it_is_there_to_test(stack, condition):
    base = config_of(stack, SystemCondition.CREW_FULL)
    changed = difference(base, config_of(stack, condition))
    planned = PLANNED[condition]
    # A model with no options of its own drops every key under model_options at once.
    if "model_options" in planned:
        changed = {key.split(".")[0] if key.startswith("model_options") else key for key in changed}
    # SA-MAX always thinks. That shows as a difference only if the other conditions do not.
    if condition is SystemCondition.SA_MAX:
        changed.discard("model_options.chat_template_kwargs")
    assert changed == planned


def test_every_condition_is_in_the_fairness_table():
    assert set(PLANNED) == set(SystemCondition)


def test_sa_max_thinks_even_when_the_others_do_not(populated_settings):
    quiet = build_stack(
        populated_settings, ScriptedTransport(), EventStore(), MODELS.with_thinking(False)
    )
    base = config_of(quiet, SystemCondition.SA_BASE)
    full = config_of(quiet, SystemCondition.SA_MAX)
    assert base["model_options"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert full["model_options"]["chat_template_kwargs"] == {"enable_thinking": True}


def test_a_case_records_what_it_ran_with(stack):
    config = config_of(stack, SystemCondition.CREW_FULL)
    assert {
        "model",
        "decoding",
        "model_options",
        "limits",
        "rate_limit",
        "policies_sha",
        "rule_cards_sha",
        "taxonomy_sha",
        "tools_sha",
        "snapshots",
    } <= set(config)
    assert set(config["snapshots"]) >= {"cma_licensed", "vara_register", "dfsa_register"}


def test_sampling_is_only_for_the_condition_that_tests_it(stack):
    for condition in SystemCondition:
        temperature = config_of(stack, condition)["decoding"]["temperature"]
        expected = SC5_TEMPERATURE if condition is SystemCondition.SA_SC5 else 0
        assert temperature == expected, condition


# ------------------------------------------------------------------- equal knowledge


def system_prompt(env, agent) -> str:
    return agent.spec(env, Task("initial")).system.text


def guide(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").strip()


@pytest.fixture
def env(stack):
    return open_condition(stack, "knowledge", OFFER, condition=SystemCondition.SA_BASE)


def test_the_single_agent_gets_every_rule_policy_and_activity(env):
    text = system_prompt(env, SingleAgent())
    for rule_id in load_rule_cards(REPO_ROOT / "knowledge"):
        assert f"[{rule_id}]" in text, rule_id
    for rule in (
        *env.decision.hard_conflicts,
        *env.decision.consistent_conditions,
        *env.decision.unverified_reasons,
        *env.decision.precedence,
    ):
        assert rule.text in text, rule.id
    for activity in load_activity_taxonomy(REPO_ROOT / "knowledge").activities:
        assert activity.code in text


@pytest.mark.parametrize("name", GUIDES)
def test_the_single_agent_gets_the_crews_guidance_in_the_same_words(env, name):
    assert guide(name) in system_prompt(env, SingleAgent())


@pytest.mark.parametrize(
    ("name", "agent"),
    [
        ("_jurisdiction_guide", AgentId.JUR),
        ("_regulator_guide", AgentId.CMA),
        ("_regulator_guide", AgentId.DFSA),
        ("_regulator_guide", AgentId.VARA),
        ("_contact_guide", AgentId.CLN),
    ],
)
def test_the_crew_gets_the_guidance_the_single_agent_gets(env, name, agent):
    assert guide(name) in system_prompt(env, build_crew()[agent])


def test_the_reconciler_gets_the_guidance_on_choosing_a_result(env):
    text = build_crew()[AgentId.REC].spec(env, Task("synthesis")).system.text
    assert guide("_decision_guide") in text


def test_the_crews_role_files_do_not_keep_private_guidance(env):
    """Knowledge lives in the shared files, so neither system can be told more than the other."""
    for name in ("jurisdiction", "clone_check", "reconciler_synthesis"):
        text = guide(name)
        assert "## How to reason" not in text, name
        assert "## Starting matrix" not in text, name


def test_the_single_agent_has_every_tool_the_crew_shares_out(env):
    crew_tools = {name for agent in build_crew().values() for name in agent.tool_names}
    assert set(SingleAgent().tool_names) == crew_tools == set(TOOLS)


def test_prompts_for_every_system_share_the_ground_rules(env):
    shared = guide("_shared")
    agents = [SingleAgent(), *build_crew().values()]
    for agent in agents:
        if agent.agent_id is AgentId.VER:
            continue
        assert shared in system_prompt(env, agent), agent.agent_id


def test_no_prompt_tells_a_system_which_condition_it_is_in(env):
    text = system_prompt(env, SingleAgent())
    assert not re.search(r"\b(?:baseline|crew|experiment)\b", text, re.IGNORECASE)
    assert "one member" not in text
