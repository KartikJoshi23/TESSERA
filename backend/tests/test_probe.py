"""The model probe: selection by measured ability, using scripted models."""

import asyncio
import json

from tessera.governance.masking import MaskingGateway
from tessera.llm.client import GuardedLLM
from tessera.llm.config import load_models_policy
from tessera.llm.probe import PASS_RATE, ModelReport, main, probe_model
from tessera.llm.testing import ScriptedTransport, chat_reply, json_reply, tool_reply
from tessera.llm.types import PermanentLLMError

from .conftest import REPO_ROOT, make_settings

MODELS = load_models_policy(REPO_ROOT / "policies")
CALL = tool_reply(("register_lookup", {"name": "Falcon Ridge Securities"}))
ROUND_TRIP = json_reply({"evidence_id": "E-0123456789abcdef", "status": "active"})
EXTRACTED = json_reply(
    {"firm_name": "Falcon", "regulator": "CMA", "domain": "x.example", "activity": "FX"}
)


def probe(*replies, listed=True, trials=1):
    transport = ScriptedTransport(replies)
    llm = GuardedLLM(transport, MaskingGateway([]))
    report = asyncio.run(probe_model(llm, MODELS, "a/model", listed=listed, trials=trials))
    return report, transport


def test_a_capable_model_passes():
    report, transport = probe(CALL, ROUND_TRIP, EXTRACTED)
    assert report.passed
    assert (report.tool_valid, report.tool_round_trip, report.json_valid_first_try) == (1, 1, 1)
    assert report.requests == len(transport.payloads) == 3
    assert report.median_latency_seconds is not None


def test_a_model_the_provider_does_not_list_costs_no_requests():
    report, transport = probe(listed=False)
    assert not report.passed and transport.payloads == []
    assert report.errors == ["not listed by the provider"]


def test_a_tool_result_that_is_not_used_is_counted():
    report, _ = probe(CALL, json_reply({"evidence_id": "E-made-up", "status": "x"}), EXTRACTED)
    assert report.tool_valid == 1 and report.tool_round_trip == 0


def test_a_model_that_ignores_tools_fails():
    report, _ = probe(chat_reply("It is licensed."), EXTRACTED)
    assert report.tool_rate == 0 and not report.passed


def test_json_repair_counts_only_toward_the_repaired_rate():
    report, _ = probe(CALL, ROUND_TRIP, chat_reply("Sure!"), EXTRACTED)
    assert report.json_valid_first_try == 0 and report.json_valid_after_repair == 1
    assert report.passed


def test_output_that_stays_invalid_fails():
    report, _ = probe(CALL, ROUND_TRIP, chat_reply("Sure!"), chat_reply("Certainly!"))
    assert report.json_rate == 0 and not report.passed


def test_model_errors_are_reported_not_raised():
    report, _ = probe(PermanentLLMError("HTTP 404: not found"), EXTRACTED)
    assert report.errors == ["HTTP 404: not found"] and report.tool_rate == 0


def test_the_pass_mark_is_the_planned_one():
    report = ModelReport(
        model="m",
        listed=True,
        tool_trials=20,
        tool_valid=19,
        json_trials=20,
        json_valid_after_repair=18,
    )
    assert PASS_RATE == 0.95 and report.tool_rate == 0.95 and not report.passed


def test_trial_prompts_are_fictional_and_repeat_as_needed():
    replies = [CALL, ROUND_TRIP, EXTRACTED] * 7
    report, transport = probe(*replies, trials=7)
    assert report.tool_trials == report.json_trials == 7
    assert "dfsa.ae" not in json.dumps(transport.payloads)


def test_a_missing_key_is_explained(monkeypatch, tmp_path, capsys):
    settings = make_settings(tmp_path / "data")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr("tessera.llm.probe.load_settings", lambda: settings)
    assert main([]) == 2
    assert "NVIDIA_API_KEY is not set" in capsys.readouterr().err


def test_every_candidate_group_is_probed_once_by_default(monkeypatch, tmp_path, capsys):
    seen = []

    class FakeHttp:
        async def list_models(self):
            return []

        async def aclose(self):
            pass

    async def fake_probe(llm, models, model, *, listed, trials):
        seen.append(model)
        return ModelReport(model=model, listed=listed)

    def fake_build(settings, models, **kwargs):
        return ScriptedTransport(), FakeHttp()

    settings = make_settings(tmp_path / "data").model_copy(update={"root": tmp_path})
    monkeypatch.setattr("tessera.llm.probe.load_settings", lambda: settings)
    monkeypatch.setattr("tessera.llm.probe.load_models_policy", lambda _: MODELS)
    monkeypatch.setattr("tessera.llm.probe.build_live_transport", fake_build)
    monkeypatch.setattr("tessera.llm.probe.probe_model", fake_probe)
    assert main([]) == 0
    assert len(seen) == len(set(seen)) and set(seen) == {
        model for group in MODELS.candidates.values() for model in group
    }
    reports = list((tmp_path / "runs" / "probe").glob("probe-*.json"))
    assert len(reports) == 1
    assert "Report written" in capsys.readouterr().out
