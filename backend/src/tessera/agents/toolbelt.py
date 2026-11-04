"""The tools an agent can call, as OpenAI-style function definitions.

The tool belt is the bridge between two worlds:

* The model lives in the **masked** world. It sees placeholders such as ``⟦R:DOMAIN-1⟧`` and passes
  them back as tool arguments.
* Tools live in the **real** world. Arguments are unmasked just before a local tool call, and the
  result is masked again before it goes back to the model or into the event log.

A tool result flagged ``restricted`` is never logged: the event keeps only its evidence IDs.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tessera.blackboard.board import Blackboard
from tessera.errors import TesseraError
from tessera.protocol.common import AgentId
from tessera.protocol.evidence import EvidenceKind, EvidenceRecord, ToolResult
from tessera.tools import (
    ToolContext,
    analyse_payment,
    analyse_phone,
    cma_register_lookup,
    cma_warnings_lookup,
    compare_domain,
    dfsa_facts_lookup,
    official_contacts_for,
    reverse_contact_lookup,
    vara_register_lookup,
    vara_unlicensed_lookup,
)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _AnyOf(_Args):
    """Lookups need at least one search term."""

    @model_validator(mode="after")
    def _at_least_one(self) -> _AnyOf:
        if not any(self.model_dump().values()):
            raise ValueError("give at least one search term")
        return self


class CmaRegisterArgs(_AnyOf):
    name: str | None = Field(default=None, description="Firm name as claimed.")
    licence_no: str | None = Field(default=None, description="Licence number as claimed.")
    domain: str | None = Field(default=None, description="Website or domain.")


class CmaWarningsArgs(_AnyOf):
    name: str | None = Field(default=None, description="Entity name.")
    domain: str | None = Field(default=None, description="Website or domain.")
    phone: str | None = Field(default=None, description="Phone number.")
    email: str | None = Field(default=None, description="Email address.")


class VaraRegisterArgs(_AnyOf):
    name: str | None = Field(default=None, description="Firm name as claimed.")
    licence_ref: str | None = Field(default=None, description="Licence reference as claimed.")
    domain: str | None = Field(default=None, description="Website or domain.")


class VaraUnlicensedArgs(_AnyOf):
    name: str | None = Field(default=None, description="Entity name.")
    domain: str | None = Field(default=None, description="Website or domain.")


class DfsaFactsArgs(_AnyOf):
    name: str | None = Field(default=None, description="Firm name as claimed.")
    frn: str | None = Field(default=None, description="Firm Reference Number as claimed.")
    domain: str | None = Field(default=None, description="Website or domain.")
    email: str | None = Field(default=None, description="Email address.")
    phone: str | None = Field(default=None, description="Phone number.")


class ReverseContactArgs(_Args):
    value: str = Field(description="One domain, URL, email address or phone number.")


class OfficialContactsArgs(_Args):
    evidence_id: str = Field(description="Evidence ID of a register entry.")


class CompareDomainArgs(_Args):
    offer_domain: str = Field(description="The domain, URL or email used in the offer.")
    official_domain: str = Field(description="The official domain from the record.")
    official_evidence_id: str = Field(description="Evidence ID of the record it came from.")


class AnalysePhoneArgs(_Args):
    offer_phone: str = Field(description="The phone number used in the offer.")
    official_phones: list[str] = Field(description="Official phone numbers from the record.")
    official_evidence_id: str = Field(description="Evidence ID of the record they came from.")


class AnalysePaymentArgs(_Args):
    iban: str | None = Field(default=None, description="IBAN in the offer.")
    beneficiary: str | None = Field(default=None, description="Payment beneficiary name.")
    wallet: str | None = Field(default=None, description="Crypto wallet address, if one is given.")
    wallet_requested: bool = Field(
        default=False,
        description="True if the offer asks for crypto payment, even with no address.",
    )
    entity_evidence_id: str | None = Field(
        default=None, description="Evidence ID of the firm's register entry."
    )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[ToolBelt, Any], ToolResult]


def _required_evidence(belt: ToolBelt, evidence_id: str) -> EvidenceRecord:
    record = belt.board.evidence.get(evidence_id)
    if record is None:
        raise ValueError(f"no evidence with ID {evidence_id} exists in this case")
    return record


def _run_official_contacts(belt: ToolBelt, a: OfficialContactsArgs) -> ToolResult:
    return official_contacts_for(belt.ctx, _required_evidence(belt, a.evidence_id))


def _run_compare_domain(belt: ToolBelt, a: CompareDomainArgs) -> ToolResult:
    official = _required_evidence(belt, a.official_evidence_id)
    return compare_domain(belt.ctx, a.offer_domain, a.official_domain, official)


def _run_analyse_phone(belt: ToolBelt, a: AnalysePhoneArgs) -> ToolResult:
    official = _required_evidence(belt, a.official_evidence_id)
    return analyse_phone(belt.ctx, a.offer_phone, a.official_phones, official)


def _run_analyse_payment(belt: ToolBelt, a: AnalysePaymentArgs) -> ToolResult:
    entity = _required_evidence(belt, a.entity_evidence_id) if a.entity_evidence_id else None
    if entity is not None and entity.kind is not EvidenceKind.REGISTER_ENTRY:
        raise ValueError(
            "entity_evidence_id must be a register entry; leave it out if none matched"
        )
    names: list[str] = []
    if entity is not None:
        record = belt.ctx.registry.table(entity.source_id).get(entity.locator)
        names = record.names() if record is not None else []
    wallet = a.wallet or ("unspecified" if a.wallet_requested else None)
    return analyse_payment(
        belt.ctx,
        iban=a.iban,
        beneficiary=a.beneficiary,
        wallet=wallet,
        entity_names=names,
        entity_evidence=entity,
    )


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "cma_register_lookup",
            "Search the CMA Licensed Companies snapshot. Returns entries, or a no-match record.",
            CmaRegisterArgs,
            lambda b, a: cma_register_lookup(
                b.ctx, name=a.name, licence_no=a.licence_no, domain=a.domain
            ),
        ),
        ToolSpec(
            "cma_warnings_lookup",
            "Search the CMA Warnings snapshot by name, domain, phone or email.",
            CmaWarningsArgs,
            lambda b, a: cma_warnings_lookup(
                b.ctx, name=a.name, domain=a.domain, phone=a.phone, email=a.email
            ),
        ),
        ToolSpec(
            "vara_register_lookup",
            "Search the VARA Public Register snapshot. Licensed firms and IPA holders stay "
            "separate.",
            VaraRegisterArgs,
            lambda b, a: vara_register_lookup(
                b.ctx, name=a.name, licence_ref=a.licence_ref, domain=a.domain
            ),
        ),
        ToolSpec(
            "vara_unlicensed_lookup",
            "Search VARA's Unlicensed VASPs list by name or domain.",
            VaraUnlicensedArgs,
            lambda b, a: vara_unlicensed_lookup(b.ctx, name=a.name, domain=a.domain),
        ),
        ToolSpec(
            "dfsa_facts_lookup",
            "Search the recorded DFSA register and alert facts. Alerts about an impersonated firm "
            "name that firm as the victim.",
            DfsaFactsArgs,
            lambda b, a: dfsa_facts_lookup(
                b.ctx, name=a.name, frn=a.frn, domain=a.domain, email=a.email, phone=a.phone
            ),
        ),
        ToolSpec(
            "reverse_contact_lookup",
            "Search every alert, warning and unlicensed list for one contact value.",
            ReverseContactArgs,
            lambda b, a: reverse_contact_lookup(b.ctx, a.value),
        ),
        ToolSpec(
            "official_contacts_for",
            "List the official domains, phones and email domains on a register entry.",
            OfficialContactsArgs,
            _run_official_contacts,
        ),
        ToolSpec(
            "compare_domain",
            "Compare an offer's domain with an official domain, and detect look-alikes.",
            CompareDomainArgs,
            _run_compare_domain,
        ),
        ToolSpec(
            "analyse_phone",
            "Compare an offer's phone number with the official numbers.",
            AnalysePhoneArgs,
            _run_analyse_phone,
        ),
        ToolSpec(
            "analyse_payment",
            "Check an IBAN, compare the beneficiary with the firm's registered name, and note a "
            "crypto payment request.",
            AnalysePaymentArgs,
            _run_analyse_payment,
        ),
    )
}


def _parameters(model: type[BaseModel]) -> dict[str, Any]:
    """A simple JSON Schema: open models handle plain types better than ``anyOf`` with null."""
    schema = model.model_json_schema()
    properties: dict[str, Any] = {}
    for name, definition in schema.get("properties", {}).items():
        clean = {k: v for k, v in definition.items() if k in {"type", "description", "items"}}
        for option in definition.get("anyOf", ()):
            if option.get("type") != "null":
                clean.update(option)
                break
        properties[name] = clean
    return {
        "type": "object",
        "properties": properties,
        "required": schema.get("required", []),
        "additionalProperties": False,
    }


def _compact(value: Any) -> Any:
    """Drop empty values, so tool results cost fewer tokens."""
    if isinstance(value, dict):
        kept = {k: _compact(v) for k, v in value.items()}
        return {k: v for k, v in kept.items() if v not in (None, [], {}, "")}
    if isinstance(value, list | tuple):
        return [_compact(item) for item in value]
    return value


class ToolBelt:
    ctx: ToolContext
    board: Blackboard

    def __init__(self, ctx: ToolContext, board: Blackboard) -> None:
        self.ctx = ctx
        self.board = board

    def definitions(self, names: Iterable[str]) -> list[dict[str, Any]]:
        """OpenAI-format tool definitions, in a fixed order."""
        return [
            {
                "type": "function",
                "function": {
                    "name": TOOLS[name].name,
                    "description": TOOLS[name].description,
                    "parameters": _parameters(TOOLS[name].args),
                },
            }
            for name in names
        ]

    def execute(
        self,
        name: str,
        raw_arguments: str,
        *,
        allowed: Iterable[str],
        actor: AgentId,
        round: int = 0,
    ) -> tuple[str, bool]:
        """Run one tool call. Returns the masked tool message and whether the call succeeded.

        Errors go back to the model as tool messages, so it can correct itself.
        """
        gateway = self.board.gateway
        spec = TOOLS.get(name)
        if spec is None or name not in set(allowed):
            return self._failed(f"{name!r} is not one of your tools"), False
        try:
            arguments = json.loads(raw_arguments or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")
            real = spec.args.model_validate(gateway.unmask_payload(arguments))
            result = spec.run(self, real)
        except (ValueError, ValidationError, TesseraError) as exc:
            message = gateway.mask(str(exc))[:400]
            self._log(
                actor, name, gateway.mask_payload(arguments_or_raw(raw_arguments)), round, message
            )
            return self._failed(message), False
        self.board.add_evidence(result.evidence)
        summary = gateway.mask_payload(_compact(result.summary))
        self.board.record(
            "tool.called",
            actor,
            {
                "tool": name,
                "arguments": gateway.mask_payload(arguments),
                "evidence_ids": [e.evidence_id for e in result.evidence],
                "restricted": result.restricted,
                "summary": None if result.restricted else summary,
                "warnings": list(result.warnings),
                "round": round,
            },
        )
        return json.dumps(summary, ensure_ascii=False), True

    def _failed(self, message: str) -> str:
        return json.dumps({"error": message}, ensure_ascii=False)

    def _log(self, actor: AgentId, name: str, arguments: Any, round: int, error: str) -> None:
        self.board.record(
            "tool.failed",
            actor,
            {"tool": name, "arguments": arguments, "error": error, "round": round},
        )


def arguments_or_raw(raw: str) -> Any:
    """The parsed arguments if possible, otherwise the raw text, for the failure log."""
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return raw[:300]
