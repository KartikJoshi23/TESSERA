"""The local API and the case-runner command, with scripted model replies."""

import json

import pytest
from fastapi.testclient import TestClient

from tessera.agents.crew import build_stack
from tessera.api import app as api_app
from tessera.api.app import create_app, main
from tessera.api.service import CaseService
from tessera.blackboard.store import EventStore
from tessera.devdata import FICTION_DATE, load_smoke_cases
from tessera.errors import PolicyError
from tessera.governance.synthetic_gate import OfferInput
from tessera.llm.config import load_models_policy
from tessera.llm.testing import ScriptedTransport, chat_reply
from tessera.orchestration.cli import main as run_main

from .conftest import REPO_ROOT

MODELS = load_models_policy(REPO_ROOT / "policies")
SMOKE = {case.id: case for case in load_smoke_cases(REPO_ROOT)}
OFFER = {"text": SMOKE["S09"].offer().text, "synthetic": True, "corpus_item_id": "S09"}


def make_service(settings, replies=None, **kwargs):
    transport = ScriptedTransport(replies if replies is not None else [chat_reply("no")] * 60)
    stack = build_stack(settings, transport, EventStore(), MODELS)
    return CaseService(stack, today=FICTION_DATE, **kwargs)


@pytest.fixture
def service(populated_settings):
    return make_service(populated_settings)


@pytest.fixture
def client(service):
    with TestClient(create_app(service), base_url="http://localhost") as test_client:
        yield test_client


def finished_case(client, service, **changes):
    response = client.post("/api/cases", json={**OFFER, **changes})
    assert response.status_code == 202, response.text
    case_id = response.json()["case_id"]
    client.portal.call(service.wait)
    return case_id


def events_of(client, case_id, **kwargs):
    with client.stream("GET", f"/api/cases/{case_id}/events", **kwargs) as stream:
        lines = [line for line in stream.iter_lines() if line.startswith("data: ")]
    return [json.loads(line.removeprefix("data: ")) for line in lines]


# ------------------------------------------------------------------- what the API reports


def test_status_says_what_is_loaded_and_covered(client):
    status = client.get("/api/status").json()
    assert status["mode"] == "RESEARCH_INTERNAL" and status["model_ready"] is True
    assert status["covered_regulators"] == ["CMA", "DFSA", "VARA"]
    assert {s["source_id"] for s in status["sources"]} >= {"cma_licensed", "dfsa_register"}
    assert all(s["as_of"] == "2026-11-04" for s in status["sources"])
    assert status["conditions"][0] == "CREW-FULL"


def test_examples_are_fictional_and_hold_no_gold(client):
    examples = client.get("/api/examples").json()
    assert len(examples) == 25 and set(examples[0]) == {"id", "channel", "text"}
    assert "gold_" not in json.dumps(examples)


# ------------------------------------------------------------------- starting a case


def test_a_real_message_is_refused(client):
    response = client.post("/api/cases", json={**OFFER, "synthetic": False})
    assert response.status_code == 422 and "synthetic" in response.json()["detail"]


def test_a_synthetic_offer_needs_a_source_or_an_attestation(client):
    response = client.post("/api/cases", json={"text": "An offer.", "synthetic": True})
    assert response.status_code == 422 and "attestation" in response.json()["detail"]


def test_real_looking_personal_data_is_flagged(client, service):
    text = "Pay with card 4111 1111 1111 1111 at falconridge.example."
    response = client.post(
        "/api/cases", json={"text": text, "synthetic": True, "corpus_item_id": "X"}
    )
    assert response.status_code == 202 and response.json()["warnings"]
    client.portal.call(service.wait)


@pytest.mark.parametrize("text", ["", "x" * 20_001])
def test_an_offer_outside_the_size_limits_is_refused(client, text):
    assert client.post("/api/cases", json={**OFFER, "text": text}).status_code == 422


def test_a_missing_key_is_explained_when_a_case_starts(populated_settings):
    service = make_service(populated_settings, model_ready=False, not_ready_reason="No key yet.")
    with TestClient(create_app(service), base_url="http://localhost") as client:
        response = client.post("/api/cases", json=OFFER)
        assert response.status_code == 503 and response.json()["detail"] == "No key yet."
        assert client.get("/api/status").json()["model_ready"] is False


def test_a_condition_with_no_crew_is_refused_before_a_case_exists(client, service):
    response = client.post("/api/cases", json={**OFFER, "condition": "SA-BASE"})
    assert response.status_code == 422 and "not a crew condition" in response.json()["detail"]
    assert service.stack.store.case_ids() == []


# ------------------------------------------------------------------- streaming


def test_a_stream_gives_every_event_in_order_and_ends(client, service):
    case_id = finished_case(client, service)
    events = events_of(client, case_id)
    assert events[0]["type"] == "case.created" and events[-1]["type"] == "result.finalized"
    sequence = [event["seq"] for event in events]
    assert sequence == sorted(sequence) and len(set(sequence)) == len(sequence)


def test_a_stream_can_resume_where_it_stopped(client, service):
    case_id = finished_case(client, service)
    events = events_of(client, case_id)
    middle = events[len(events) // 2]["seq"]
    by_query = events_of(client, case_id, params={"after": middle})
    by_header = events_of(client, case_id, headers={"last-event-id": str(middle)})
    assert by_query == by_header == [e for e in events if e["seq"] > middle]


def test_a_live_stream_and_a_replay_are_the_same(client, service):
    case_id = client.post("/api/cases", json=OFFER).json()["case_id"]
    live = events_of(client, case_id)
    client.portal.call(service.wait)
    assert live == events_of(client, case_id)


def test_streams_hold_no_restricted_values(client, service):
    case_id = finished_case(client, service)
    text = json.dumps(events_of(client, case_id), ensure_ascii=False)
    assert service.stack.gateway.leaked_values(text) == []


def test_a_case_that_crashes_ends_its_stream_and_names_only_the_error_type(
    client, service, monkeypatch
):
    async def boom(*args, **kwargs):
        raise RuntimeError("a message that could quote a value")

    monkeypatch.setattr("tessera.api.service.run_crew", boom)
    case_id = finished_case(client, service)
    events = events_of(client, case_id)
    assert events[-1]["type"] == "case.aborted"
    assert events[-1]["payload"] == {"error": "RuntimeError"}


# ------------------------------------------------------------------- reading a case


def test_a_stream_ends_for_a_case_nothing_is_running(client, service):
    """After a restart a case may never finish, and its stream must not wait for ever."""
    offer = OfferInput(text="An offer.", synthetic=True, corpus_item_id="X")
    service.stack.open_case("orphan", offer)
    with client.stream("GET", "/api/cases/orphan/events") as stream:
        body = "\n".join(stream.iter_lines())
    assert "case.created" in body and "event: case.interrupted" in body


def test_a_finished_case_has_a_report_and_a_state(client, service):
    case_id = finished_case(client, service)
    report = client.get(f"/api/cases/{case_id}/report").json()
    assert report["wording"] == "Could not verify" and report["synthetic"] is True
    state = client.get(f"/api/cases/{case_id}").json()
    assert state["final"]["result"] == "UNVERIFIED" and state["case"]["case_id"] == case_id
    listed = client.get("/api/cases").json()
    assert listed == [
        {"case_id": case_id, "condition": "CREW-FULL", "result": "UNVERIFIED", "running": False}
    ]


def test_a_report_waits_for_the_case_to_finish(client, service):
    offer = OfferInput(text="An offer.", synthetic=True, corpus_item_id="X")
    service.stack.open_case("waiting", offer)
    assert client.get("/api/cases/waiting/report").status_code == 409


def test_unknown_cases_are_404(client):
    for path in ("/api/cases/none", "/api/cases/none/report", "/api/cases/none/events"):
        assert client.get(path).status_code == 404


# ------------------------------------------------------------------- it stays local


def test_requests_for_another_host_are_refused(client):
    response = client.get("/api/status", headers={"host": "evil.example"})
    assert response.status_code == 400


def test_only_local_pages_may_call_the_api(client):
    allowed = client.get("/api/status", headers={"origin": "http://localhost:3000"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    refused = client.get("/api/status", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in refused.headers


def test_the_server_binds_to_this_machine_only(monkeypatch, populated_settings):
    seen = {}
    monkeypatch.setattr(api_app.uvicorn, "run", lambda app, **kwargs: seen.update(kwargs))
    monkeypatch.setattr(api_app, "build_service", lambda fiction: make_service(populated_settings))
    assert main([]) == 0
    assert seen["host"] == "127.0.0.1"
    with pytest.raises(SystemExit):
        main(["--host", "0.0.0.0"])


# ------------------------------------------------------------------- tessera-run


def stub_transport(monkeypatch, replies):
    class Http:
        async def aclose(self):
            pass

    def build(settings, models, **kwargs):
        return ScriptedTransport(replies), Http()

    monkeypatch.setattr("tessera.orchestration.cli.build_live_transport", build)


def test_tessera_run_prints_a_report(monkeypatch, tmp_path, capsys):
    stub_transport(monkeypatch, [chat_reply("no")] * 40)
    monkeypatch.setattr(
        "tessera.orchestration.cli.load_settings",
        _settings_in(tmp_path),
    )
    assert run_main(["--case", "S01", "--run-dir", str(tmp_path / "run")]) == 0
    output = capsys.readouterr().out
    assert "COULD NOT VERIFY" in output and "SYNTHETIC" in output
    assert "It is not a finding about any firm or person" in output


def _settings_in(tmp_path):
    from tessera.config.settings import load_settings

    def fake(**overrides):
        overrides.pop("data_dir", None)
        return load_settings(**{"data_dir": tmp_path / "data", **overrides})

    return fake


def test_tessera_run_refuses_text_nobody_attested(monkeypatch, tmp_path, capsys):
    stub_transport(monkeypatch, [])
    assert run_main(["--text", "An offer.", "--run-dir", str(tmp_path)]) == 2
    assert "attestation" in capsys.readouterr().err


def test_tessera_run_explains_a_missing_key(monkeypatch, tmp_path, capsys):
    def no_key(*args, **kwargs):
        raise PolicyError("NVIDIA_API_KEY is not set.")

    monkeypatch.setattr("tessera.orchestration.cli.build_live_transport", no_key)
    assert run_main(["--text", "An offer.", "--run-dir", str(tmp_path)]) == 2
    assert "NVIDIA_API_KEY is not set" in capsys.readouterr().err


def test_tessera_run_needs_an_offer(capsys):
    with pytest.raises(SystemExit):
        run_main([])
