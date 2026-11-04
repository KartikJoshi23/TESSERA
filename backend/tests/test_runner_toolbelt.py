"""The tool belt (masked world to real world and back) and the agent runner's tool loop."""

import asyncio
import json

from pydantic import BaseModel

from tessera.llm.config import LimitsConfig
from tessera.llm.prompts import RenderedPrompt
from tessera.llm.runner import AgentRunner, AgentSpec, UsageMeter
from tessera.llm.testing import chat_reply, json_reply, tool_reply
from tessera.llm.types import PermanentLLMError
from tessera.protocol.common import AgentId
from tessera.protocol.evidence import EvidenceKind

OFFER = (
    "Lumen Crest Capital (DIFC) Limited, FRN F000000. "
    "Open your account at lumencrest-capital.example. Call +44 7700 900123."
)


class Answer(BaseModel):
    answer: str


SPEC = AgentSpec(
    agent_id=AgentId.DFSA,
    system=RenderedPrompt("You are a test agent.", "hash"),
    output_model=Answer,
    tool_names=("dfsa_facts_lookup", "reverse_contact_lookup"),
)


def runner_for(setup, limits=None):
    env = setup.env
    return AgentRunner(
        env.runner._llm,
        env.belt,
        env.board,
        model="scripted",
        decoding=env.runner._decoding,
        limits=limits
        or LimitsConfig(tool_calls_per_turn=3, repair_attempts=1, requests_per_case=9),
        meter=UsageMeter(max_requests=9),
    )


def run(setup, spec=SPEC, limits=None):
    runner = runner_for(setup, limits)
    return asyncio.run(runner.run(spec, "Please check this."))


# ------------------------------------------------------------------- tool belt


def test_tool_definitions_are_plain_json_schema(harness):
    setup = harness(OFFER)
    definition = setup.env.belt.definitions(["compare_domain"])[0]["function"]
    assert definition["parameters"]["additionalProperties"] is False
    assert set(definition["parameters"]["required"]) == {
        "offer_domain",
        "official_domain",
        "official_evidence_id",
    }
    optional = setup.env.belt.definitions(["cma_register_lookup"])[0]["function"]["parameters"]
    assert optional["properties"]["name"]["type"] == "string"  # no anyOf with null


def test_placeholders_are_unmasked_only_for_the_local_tool_call(harness):
    setup = harness(OFFER)
    gateway = setup.gateway
    placeholder = gateway.mask("F000000")
    content, ok = setup.env.belt.execute(
        "dfsa_facts_lookup",
        json.dumps({"frn": placeholder}),
        allowed=("dfsa_facts_lookup",),
        actor=AgentId.DFSA,
    )
    assert ok
    assert gateway.leaked_values(content) == []
    result = json.loads(content)
    assert result["register_matches"][0]["status"] == "authorised"
    assert result["register_matches"][0]["zone"] == "DIFC"  # the address itself is not sent
    assert result["register_matches"][0]["frn"] == placeholder


def test_restricted_results_are_never_logged(harness):
    setup = harness(OFFER)
    setup.env.belt.execute(
        "dfsa_facts_lookup",
        json.dumps({"frn": setup.gateway.mask("F000000")}),
        allowed=("dfsa_facts_lookup",),
        actor=AgentId.DFSA,
    )
    event = next(e for e in setup.store.read("case-1") if e.type == "tool.called")
    assert event.payload["restricted"] is True and event.payload["summary"] is None
    assert event.payload["evidence_ids"]


def test_evidence_from_a_tool_reaches_the_board(harness):
    setup = harness(OFFER)
    content, _ = setup.env.belt.execute(
        "cma_register_lookup",
        json.dumps({"name": "Falcon Ridge Securities"}),
        allowed=("cma_register_lookup",),
        actor=AgentId.CMA,
    )
    evidence_id = json.loads(content)["matches"][0]["evidence_id"]
    assert setup.board.evidence[evidence_id].kind is EvidenceKind.REGISTER_ENTRY


def test_a_query_holding_a_restricted_value_is_masked_in_no_match_evidence(harness):
    setup = harness(OFFER)
    setup.env.belt.execute(
        "reverse_contact_lookup",
        json.dumps({"value": setup.gateway.mask("lumencrest-capital.example")}),
        allowed=("reverse_contact_lookup",),
        actor=AgentId.CLN,
    )
    stored = json.dumps([e.payload for e in setup.store.read("case-1")], ensure_ascii=False)
    assert setup.gateway.leaked_values(stored) == []


def test_tools_outside_an_agents_set_are_refused(harness):
    setup = harness(OFFER)
    content, ok = setup.env.belt.execute(
        "dfsa_facts_lookup", "{}", allowed=("cma_register_lookup",), actor=AgentId.CMA
    )
    assert not ok and "not one of your tools" in content


def test_bad_arguments_go_back_to_the_model_as_an_error(harness):
    setup = harness(OFFER)
    allowed = ("cma_register_lookup",)
    for raw in ("{not json", "{}", '{"unexpected": 1}', "[1]"):
        content, ok = setup.env.belt.execute(
            "cma_register_lookup", raw, allowed=allowed, actor=AgentId.CMA
        )
        assert not ok and "error" in json.loads(content)
    assert sum(e.type == "tool.failed" for e in setup.store.read("case-1")) == 4


def test_unknown_evidence_ids_are_reported_to_the_model(harness):
    setup = harness(OFFER)
    content, ok = setup.env.belt.execute(
        "official_contacts_for",
        json.dumps({"evidence_id": "E-invented"}),
        allowed=("official_contacts_for",),
        actor=AgentId.CLN,
    )
    assert not ok and "no evidence with ID" in content


# ------------------------------------------------------------------- runner


def test_a_turn_runs_tools_then_returns_validated_output(harness):
    setup = harness(
        OFFER,
        tool_reply(("dfsa_facts_lookup", {"frn": "F000000"})),
        json_reply({"answer": "done"}),
    )
    result = run(setup)
    assert result.ok and result.output.answer == "done"
    assert result.requests == 2 and result.tool_calls == 1
    tool_message = setup.transport.payloads[1]["messages"][-1]
    assert tool_message["role"] == "tool" and "register_matches" in tool_message["content"]
    setup.assert_no_leaks()


def test_several_tool_calls_in_one_reply_all_run(harness):
    setup = harness(
        OFFER,
        tool_reply(
            ("dfsa_facts_lookup", {"frn": "F000000"}),
            ("reverse_contact_lookup", {"value": "lumencrest-capital.example"}),
        ),
        json_reply({"answer": "done"}),
    )
    result = run(setup)
    assert result.tool_calls == 2
    roles = [m["role"] for m in setup.transport.payloads[1]["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "tool"]


def test_invalid_output_gets_one_repair(harness):
    setup = harness(OFFER, chat_reply("not json"), json_reply({"answer": "fixed"}))
    result = run(setup)
    assert result.ok and result.repairs == 1
    assert "could not be used" in setup.transport.payloads[1]["messages"][-1]["content"]


def test_a_schema_error_is_named_in_the_repair_request(harness):
    setup = harness(OFFER, json_reply({"wrong": 1}), json_reply({"answer": "fixed"}))
    run(setup)
    assert "answer" in setup.transport.payloads[1]["messages"][-1]["content"]


def test_output_still_invalid_after_repair_is_a_recorded_failure(harness):
    setup = harness(OFFER, chat_reply("no"), chat_reply("still no"))
    result = run(setup)
    assert not result.ok and result.failure == "invalid_output"
    assert setup.board.failures[0]["code"] == "invalid_output"


def test_the_tool_limit_forces_a_final_answer(harness):
    limits = LimitsConfig(tool_calls_per_turn=1, repair_attempts=1, requests_per_case=9)
    setup = harness(
        OFFER,
        tool_reply(("dfsa_facts_lookup", {"frn": "F000000"})),
        json_reply({"answer": "done"}),
    )
    result = run(setup, limits=limits)
    assert result.ok
    final = setup.transport.payloads[-1]
    assert "tools" not in final and "used all your tool calls" in final["messages"][-1]["content"]


def test_the_request_budget_stops_a_case(harness):
    setup = harness(OFFER, tool_reply(("dfsa_facts_lookup", {"frn": "F000000"})))
    runner = runner_for(setup)
    runner.meter.max_requests = 1
    result = asyncio.run(runner.run(SPEC, "Please check this."))
    assert result.failure == "budget_exceeded"
    assert any(e.type == "budget.exceeded" for e in setup.store.read("case-1"))


def test_a_model_error_fails_the_turn_without_switching_models(harness):
    setup = harness(OFFER, PermanentLLMError("HTTP 400: bad model"))
    result = run(setup)
    assert result.failure == "model_error"
    assert len(setup.transport.payloads) == 1


def test_a_provider_refusal_is_recorded(harness):
    setup = harness(OFFER, chat_reply("", finish_reason="content_filter"))
    assert run(setup).failure == "refused"


def test_reasoning_is_never_sent_back_to_the_model(harness):
    setup = harness(
        OFFER,
        chat_reply("<think>private thoughts</think>not json", reasoning="more private thoughts"),
        json_reply({"answer": "fixed"}),
    )
    result = run(setup)
    assert result.reasoning == ["more private thoughts"]
    assert "private thoughts" not in setup.outgoing_text()


def test_usage_is_counted_per_agent(harness):
    setup = harness(OFFER, json_reply({"answer": "done"}))
    runner = runner_for(setup)
    asyncio.run(runner.run(SPEC, "Please check this."))
    assert runner.meter.requests == 1 and runner.meter.by_agent["DFSA"] == 1
    assert runner.meter.prompt_tokens == 100


def test_model_calls_are_logged_with_usage_but_without_the_prompt(harness):
    setup = harness(OFFER, json_reply({"answer": "done"}))
    run(setup)
    event = next(e for e in setup.store.read("case-1") if e.type == "llm.response")
    assert event.usage["total_tokens"] == 120 and event.latency_ms is not None
    assert "messages" not in event.payload and event.payload["request_sha256"]
