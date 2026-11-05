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


def run_reasoning(setup):
    """A runner whose model has a reasoning switch, set on as in every primary run."""
    runner = runner_for(setup)
    runner._extra_body = {"chat_template_kwargs": {"enable_thinking": True}}
    return asyncio.run(runner.run(SPEC, "Please check this."))


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


def test_a_payment_check_says_when_its_entry_is_not_a_register_entry(harness):
    setup = harness(OFFER)
    content, _ = setup.env.belt.execute(
        "cma_warnings_lookup",
        json.dumps({"name": "Nobody At All"}),
        allowed=("cma_warnings_lookup",),
        actor=AgentId.CMA,
    )
    no_match = json.loads(content)["no_match_evidence_id"]
    content, ok = setup.env.belt.execute(
        "analyse_payment",
        json.dumps({"entity_evidence_id": no_match}),
        allowed=("analyse_payment",),
        actor=AgentId.CLN,
    )
    assert not ok and "must be a register entry" in content


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


LOOKUP = ("dfsa_facts_lookup", {"frn": "F000000", "name": "Falcon Ridge"})
SAME_LOOKUP = ("dfsa_facts_lookup", {"name": "Falcon Ridge", "frn": "F000000"})


def lookups(setup):
    return setup.board.store.of_types("tool.called")


ROOMY = LimitsConfig(tool_calls_per_turn=32, repair_attempts=1, requests_per_case=9)


def test_a_repeated_call_is_not_run_again_and_the_model_is_told(harness):
    setup = harness(OFFER, tool_reply(LOOKUP), tool_reply(SAME_LOOKUP), json_reply({"answer": "x"}))
    result = run(setup)
    assert result.ok and result.repeats == 1 and result.tool_calls == 2
    assert len(lookups(setup)) == 1
    last_tool_reply = setup.transport.payloads[-1]["messages"][-1]
    assert last_tool_reply["role"] == "tool" and "same answer" in last_tool_reply["content"]
    assert "tools" in setup.transport.payloads[-1]


def test_a_model_that_keeps_repeating_loses_its_tools(harness):
    """The live run: a single agent called one tool 24 times in a row, to the end of its budget."""
    setup = harness(
        OFFER,
        tool_reply(LOOKUP),
        tool_reply(LOOKUP),
        tool_reply(LOOKUP),
        json_reply({"answer": "done"}),
    )
    result = run(setup, limits=ROOMY)
    assert result.ok and result.repeats == 2 and result.requests == 4
    final = setup.transport.payloads[-1]
    assert "tools" not in final and "closed for this turn" in final["messages"][-1]["content"]


def test_a_new_call_after_a_repeat_is_still_allowed(harness):
    other = ("dfsa_facts_lookup", {"frn": "F999999"})
    setup = harness(
        OFFER,
        tool_reply(LOOKUP),
        tool_reply(LOOKUP),
        tool_reply(other),
        tool_reply(LOOKUP),
        json_reply({"answer": "done"}),
    )
    result = run(setup, limits=ROOMY)
    assert result.ok and result.repeats == 2 and len(lookups(setup)) == 2


def test_a_reply_that_repeats_itself_runs_the_call_once(harness):
    setup = harness(OFFER, tool_reply(LOOKUP, LOOKUP), json_reply({"answer": "done"}))
    result = run(setup)
    assert result.ok and result.repeats == 1 and len(lookups(setup)) == 1
    messages = setup.transport.payloads[-1]["messages"]
    assert [m["role"] for m in messages[-3:]] == ["assistant", "tool", "tool"]


def test_a_failed_call_is_not_tried_again_with_the_same_arguments(harness):
    """The live run: the single agent sent one failing call 10 times over."""
    bad = ("no_such_tool", {"x": 1})
    setup = harness(OFFER, tool_reply(bad), tool_reply(bad), json_reply({"answer": "done"}))
    result = run(setup)
    assert result.ok and result.repeats == 1
    assert "same answer" in setup.transport.payloads[-1]["messages"][-1]["content"]


def test_a_failed_call_may_be_corrected(harness):
    bad = ("no_such_tool", {"x": 1})
    better = ("no_such_tool", {"x": 2})
    setup = harness(OFFER, tool_reply(bad), tool_reply(better), json_reply({"answer": "done"}))
    result = run(setup)
    assert result.ok and result.repeats == 0


def reasoning_switch(payload):
    return payload["chat_template_kwargs"]["enable_thinking"]


def test_a_reply_cut_off_at_its_limit_is_repaired_with_reasoning_off(harness):
    """The live run: 5 of 37 Reconciler replies spent the whole allowance before any JSON."""
    setup = harness(OFFER, chat_reply("", finish_reason="length"), json_reply({"answer": "done"}))
    result = run_reasoning(setup)
    assert result.ok and result.repairs == 1
    first, repair = setup.transport.payloads
    assert reasoning_switch(first) is True and reasoning_switch(repair) is False
    assert "length limit" in repair["messages"][-1]["content"]
    assert setup.board.store.of_types("agent.repair")[0].payload["cut_off"] is True


def test_other_repairs_keep_reasoning_on(harness):
    setup = harness(OFFER, chat_reply("not json"), json_reply({"answer": "done"}))
    assert run_reasoning(setup).ok
    assert [reasoning_switch(p) for p in setup.transport.payloads] == [True, True]


def test_a_cut_off_reply_on_a_model_with_no_switch_is_repaired_as_it_was(harness):
    setup = harness(OFFER, chat_reply("", finish_reason="length"), json_reply({"answer": "done"}))
    assert run(setup).ok
    assert all("chat_template_kwargs" not in p for p in setup.transport.payloads)


def test_a_turn_cut_off_twice_fails_rather_than_loops(harness):
    cut_off = chat_reply("", finish_reason="length")
    setup = harness(OFFER, cut_off, cut_off)
    result = run_reasoning(setup)
    assert not result.ok and result.failure == "invalid_output" and result.requests == 2


def test_a_repair_never_leaves_an_unanswered_tool_call_in_the_history(harness):
    """After the tool limit, a stray tool call must not reach the provider unanswered."""
    limits = LimitsConfig(tool_calls_per_turn=1, repair_attempts=1, requests_per_case=9)
    setup = harness(
        OFFER,
        tool_reply(("dfsa_facts_lookup", {"frn": "F000000"})),
        tool_reply(("dfsa_facts_lookup", {"frn": "F000000"})),
        json_reply({"answer": "done"}),
    )
    assert run(setup, limits=limits).ok
    calls = [m for m in setup.transport.payloads[-1]["messages"] if m.get("tool_calls")]
    answers = [m for m in setup.transport.payloads[-1]["messages"] if m["role"] == "tool"]
    assert len(calls) == len(answers) == 1


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
