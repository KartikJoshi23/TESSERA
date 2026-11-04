"""``tessera-probe``: measure which free models can do the job, before any test-set run.

For each candidate model the probe runs small, fictional trials and measures:

* **tool calling:** does the model call the right tool with valid arguments, and then use the
  result to produce a final answer?
* **structured output:** does it return valid JSON for a schema, directly or after one repair?
* **latency.**

Selection is mechanical (implementation-plan.md §5.3): at least 95% valid tool calls and at least
95% schema-valid output after one repair. The chosen models are then recorded in ADR-0004. Only
invented firms appear in the trials: no real data and no DFSA facts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from tessera.config.settings import load_settings
from tessera.errors import PolicyError
from tessera.governance.masking import MaskingGateway
from tessera.llm.client import GuardedLLM
from tessera.llm.config import ModelsPolicy, load_models_policy
from tessera.llm.jsonio import extract_json_object
from tessera.llm.stack import build_live_transport
from tessera.llm.types import ChatResponse, LLMError, build_payload

PASS_RATE = 0.95
_LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "register_lookup",
        "description": "Search a fictional licence register for a firm by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The firm's name."},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}
_TOOL_RESULT = json.dumps(
    {
        "matches": [
            {"evidence_id": "E-0123456789abcdef", "status": "active", "category": "Category 1"}
        ]
    }
)
_TOOL_TRIALS = (
    "Is the firm Falcon Ridge Securities licensed? Use the register_lookup tool.",
    "Check the register for Coral Ledger Exchange FZE using your tool.",
    "A message claims to come from Harbour Cedar Asset Management. Look it up with your tool.",
    "Find Desert Lantern Capital PJSC on the register.",
    "Use the register tool to check Saffron Chain Custody FZCO.",
)
_TOOL_FINAL = (
    "Now reply with one JSON object and nothing else, with the fields "
    '"evidence_id" (string) and "status" (string).'
)
_SYSTEM = (
    "You check firms against a fictional register. Everything here is invented test data. "
    "When asked for JSON, reply with one JSON object and nothing else."
)


class _ExtractedOffer(BaseModel):
    firm_name: str
    regulator: str | None = None
    domain: str | None = None
    activity: str


_JSON_TRIALS = (
    "Falcon Ridge Securities, regulated by the CMA, offers FX accounts at falconridge.example.",
    "Trade bitcoin with Coral Ledger Exchange, licensed by VARA. Sign up at coralledger.example.",
    "Harbour Cedar manages portfolios under the DFSA. See harbourcedar.example for details.",
    "Saffron Chain Custody holds your crypto safely. Visit saffronchain.example today.",
    "Oasis Bridge gives financial consultation in Abu Dhabi: oasisbridge.example.",
)
_JSON_INSTRUCTION = (
    "Extract these fields from the text and reply with one JSON object and nothing else: "
    '"firm_name" (string), "regulator" (string or null), "domain" (string or null), '
    '"activity" (string).\n\nText: '
)


class ModelReport(BaseModel):
    model: str
    listed: bool
    tool_trials: int = 0
    tool_valid: int = 0
    tool_round_trip: int = 0
    json_trials: int = 0
    json_valid_first_try: int = 0
    json_valid_after_repair: int = 0
    requests: int = 0
    median_latency_seconds: float | None = None
    errors: list[str] = []

    @property
    def tool_rate(self) -> float:
        return self.tool_valid / self.tool_trials if self.tool_trials else 0.0

    @property
    def json_rate(self) -> float:
        return self.json_valid_after_repair / self.json_trials if self.json_trials else 0.0

    @property
    def passed(self) -> bool:
        return self.tool_rate >= PASS_RATE and self.json_rate >= PASS_RATE


class _Trial:
    """Runs requests for one model, recording latency and errors."""

    def __init__(self, llm: GuardedLLM, models: ModelsPolicy, report: ModelReport) -> None:
        self._llm = llm
        self._models = models
        self.report = report
        self.latencies: list[float] = []

    async def ask(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ChatResponse | None:
        payload = build_payload(
            model=self.report.model,
            messages=messages,
            decoding=self._models.decoding,
            tools=tools,
            extra_body=self._models.options_for(self.report.model),
        )
        started = time.monotonic()
        self.report.requests += 1
        try:
            response = await self._llm.complete(payload)
        except LLMError as exc:
            self.report.errors.append(str(exc)[:200])
            return None
        self.latencies.append(time.monotonic() - started)
        return response


async def _tool_trial(trial: _Trial, prompt: str) -> None:
    report = trial.report
    report.tool_trials += 1
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": prompt},
    ]
    response = await trial.ask(messages, [_LOOKUP_TOOL])
    if response is None or not response.tool_calls:
        return
    call = response.tool_calls[0]
    try:
        arguments = json.loads(call.arguments)
    except ValueError:
        return
    if call.name != "register_lookup" or not arguments.get("name"):
        return
    report.tool_valid += 1
    messages.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
            ],
        }
    )
    messages.append({"role": "tool", "tool_call_id": call.id, "content": _TOOL_RESULT})
    messages.append({"role": "user", "content": _TOOL_FINAL})
    final = await trial.ask(messages)
    if final is None:
        return
    try:
        answer = extract_json_object(final.content)
    except ValueError:
        return
    if answer.get("evidence_id") == "E-0123456789abcdef":
        report.tool_round_trip += 1


def _valid_extraction(text: str) -> bool:
    try:
        _ExtractedOffer.model_validate(extract_json_object(text))
    except (ValueError, ValidationError):
        return False
    return True


async def _json_trial(trial: _Trial, text: str) -> None:
    report = trial.report
    report.json_trials += 1
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _JSON_INSTRUCTION + text},
    ]
    response = await trial.ask(messages)
    if response is None:
        return
    if _valid_extraction(response.content):
        report.json_valid_first_try += 1
        report.json_valid_after_repair += 1
        return
    messages.append({"role": "assistant", "content": response.content})
    messages.append(
        {"role": "user", "content": "That was not valid. Reply with the JSON object only."}
    )
    repaired = await trial.ask(messages)
    if repaired is not None and _valid_extraction(repaired.content):
        report.json_valid_after_repair += 1


async def probe_model(
    llm: GuardedLLM, models: ModelsPolicy, model: str, *, listed: bool, trials: int
) -> ModelReport:
    """Run the trials for one model. Trial prompts repeat if ``trials`` exceeds their number."""
    report = ModelReport(model=model, listed=listed)
    if not listed:
        report.errors.append("not listed by the provider")
        return report
    runner = _Trial(llm, models, report)
    for index in range(trials):
        await _tool_trial(runner, _TOOL_TRIALS[index % len(_TOOL_TRIALS)])
        await _json_trial(runner, _JSON_TRIALS[index % len(_JSON_TRIALS)])
    if runner.latencies:
        report.median_latency_seconds = round(statistics.median(runner.latencies), 2)
    return report


_HEADER = f"{'model':<48} {'tools':>7} {'round':>7} {'json':>7} {'repair':>7} {'sec':>6}  pass"


def _print_row(r: ModelReport) -> None:
    latency = f"{r.median_latency_seconds:.1f}" if r.median_latency_seconds is not None else "-"
    tools = f"{r.tool_valid:>3}/{r.tool_trials:<3} {r.tool_round_trip:>3}/{r.tool_trials:<3}"
    json_ok = (
        f"{r.json_valid_first_try:>3}/{r.json_trials:<3} "
        f"{r.json_valid_after_repair:>3}/{r.json_trials:<3}"
    )
    print(
        f"{r.model:<48} {tools} {json_ok} {latency:>6}  {'yes' if r.passed else 'no'}", flush=True
    )
    for error in sorted(set(r.errors))[:3]:
        print(f"    error: {error}", flush=True)


def _write_report(path: Path, reports: list[ModelReport]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([r.model_dump() for r in reports], indent=2, ensure_ascii=False), "utf-8"
    )


async def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    models = load_models_policy(settings.policies_dir)
    try:
        transport, http = build_live_transport(settings, models)
    except PolicyError as exc:
        print(f"tessera-probe: {exc}", file=sys.stderr)
        return 2
    wanted = args.models or [m for group in models.candidates.values() for m in group]
    llm = GuardedLLM(transport, MaskingGateway([]))
    path = settings.root / "runs" / "probe" / f"probe-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    reports: list[ModelReport] = []
    print(_HEADER, flush=True)
    try:
        available = set(await http.list_models())
        for model in dict.fromkeys(wanted):
            report = await probe_model(
                llm, models, model, listed=model in available, trials=args.trials
            )
            reports.append(report)
            # Results are kept as they arrive, so an interrupted run still reports what it found.
            _write_report(path, reports)
            _print_row(report)
    finally:
        await http.aclose()
    print(f"Report written to {path.as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tessera-probe",
        description="Measure tool calling and JSON output of candidate models.",
    )
    parser.add_argument("--models", nargs="*", help="model IDs; default: every candidate")
    parser.add_argument("--trials", type=int, default=20, help="trials of each kind per model")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
