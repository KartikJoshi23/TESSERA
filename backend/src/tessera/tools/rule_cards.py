"""Rule-card retrieval. Scope and jurisdiction conclusions cite rule cards as evidence."""

from __future__ import annotations

from tessera.knowledge import load_rule_cards
from tessera.protocol.evidence import EvidenceKind, ToolResult, mint_evidence
from tessera.tools.context import ToolContext


def get_rule_card(
    ctx: ToolContext, *, rule_id: str | None = None, regulator: str | None = None
) -> ToolResult:
    """Return one rule card by ID, or every card for a regulator (plus rules for ``ALL``)."""
    if not (rule_id or regulator):
        raise ValueError("give a rule_id or a regulator")
    cards = load_rule_cards(ctx.settings.knowledge_dir)
    if rule_id:
        selected = [cards[rule_id]] if rule_id in cards else []
    else:
        wanted = {str(regulator).upper(), "ALL"}
        selected = [card for card in cards.values() if card.regulator in wanted]
    evidence = tuple(
        mint_evidence(
            case_id=ctx.case_id,
            source_id="rule_cards",
            kind=EvidenceKind.RULE_CARD,
            locator=card.id,
            fields={
                "rule_id": card.id,
                "regulator": card.regulator,
                "statement": card.statement,
                "effect": card.effect,
                "status": card.status,
                "last_reviewed": card.last_reviewed.isoformat(),
            },
            minted_by="get_rule_card",
        )
        for card in selected
    )
    return ToolResult(
        tool="get_rule_card",
        evidence=evidence,
        summary={
            "found": bool(evidence),
            "rules": [{"evidence_id": e.evidence_id, **e.fields} for e in evidence],
        },
        warnings=() if evidence else (f"no rule card for {rule_id or regulator}",),
    )
