"""The entity-level set: cards built from real register and alert records (§11.2 A).

Each stratum says what its gold label should be. The decision-policy engine then works the label out
for itself from the same card, and an item is kept only if the two agree. A disagreement means the
stratum's reasoning or the record is off, and a person should look at it, so it is listed and not
overruled. Items built from DFSA facts are marked restricted.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from tessera.agents.crew import CrewStack
from tessera.baseline.rules_only import Reading
from tessera.evaluation.firms import Firm, Listed, World
from tessera.evaluation.items import EvalItem, Level
from tessera.evaluation.labelling import policy_label, reasons_of
from tessera.knowledge import ActivityTaxonomy
from tessera.protocol.common import ResultCode

GENERATOR = "entities-1"
_FX = "DER.FX_CFD"


@dataclass(frozen=True)
class Card:
    """What a card states. Each system is shown the same text for it."""

    stratum: str
    #: What the stratum expects. ``None`` means the label simply follows the record (E11).
    label: ResultCode | None
    reading: Reading
    name: str
    domain: str | None = None
    claimed: str | None = None
    reference: str | None = None
    activity: str = ""
    restricted: bool = False

    def text(self) -> str:
        lines = [f"Entity to check: {self.name}"]
        if self.claimed:
            lines.append(f"Claims to be regulated by: {self.claimed}")
        if self.reference:
            lines.append(f"Reference number given: {self.reference}")
        if self.domain:
            lines.append(f"Website given: {self.domain}")
        if self.activity:
            lines.append(f"Service offered: {self.activity}")
        return "\n".join(lines)


def _activity(taxonomy: ActivityTaxonomy, code: str) -> str:
    return next(a.label for a in taxonomy.activities if a.code == code)


def _card_for_firm(
    firm: Firm,
    stratum: str,
    label: ResultCode | None,
    code: str,
    taxonomy: ActivityTaxonomy,
    *,
    domain: str | None,
    name: str | None = None,
    outside: str | None = None,
) -> Card:
    used = name or firm.name
    words = _activity(taxonomy, code)
    return Card(
        stratum=stratum,
        label=label,
        reading=Reading(
            activities=((code, words),),
            relevant={firm.regulator: "primary"},
            firm=used,
            regulator=(firm.regulator, firm.regulator),
            reference=firm.reference,
            not_covered={code: outside} if outside else {},
        ),
        name=used,
        domain=domain,
        claimed=firm.regulator,
        reference=firm.reference,
        activity=words,
        restricted=firm.restricted,
    )


def impersonated(world: World, taxonomy: ActivityTaxonomy) -> list[Card]:
    """E1 and E2: firms named in impersonation alerts, with the alert's contact, then their own."""
    cards: list[Card] = []
    for alert in world.alerts("impersonated_authorised_firm"):
        firm = world.firm_named(alert.name)
        if firm is None or not firm.covers:
            continue
        code = firm.covers[0]
        for contact in alert.contacts[:1]:
            cards.append(
                _card_for_firm(firm, "E1", ResultCode.CONFLICTS, code, taxonomy, domain=contact)
            )
        if firm.domain:
            cards.append(
                _card_for_firm(
                    firm, "E2", ResultCode.CONSISTENT, code, taxonomy, domain=firm.domain
                )
            )
    return cards


def false_claims(world: World, taxonomy: ActivityTaxonomy) -> list[Card]:
    """E3: false claims of DFSA authorisation, and impersonation of the regulator itself."""
    cards: list[Card] = []
    code = "SEC.ADVICE"
    words = _activity(taxonomy, code)
    for alert in world.alerts("false_claim_of_authorisation", "regulator_impersonation"):
        name = alert.name or "Dubai Financial Services Authority"
        domain = alert.contacts[0] if alert.contacts else None
        cards.append(
            Card(
                stratum="E3",
                label=ResultCode.CONFLICTS,
                reading=Reading(
                    activities=((code, words),),
                    relevant={"DFSA": "primary"},
                    firm=alert.name,
                    regulator=("DFSA", "DFSA"),
                ),
                name=name,
                domain=domain,
                claimed="DFSA",
                activity=words,
                restricted=True,
            )
        )
    return cards


def _listed_card(
    entry: Listed, stratum: str, regulator: str, code: str, taxonomy: ActivityTaxonomy
) -> Card:
    assert entry.name is not None
    words = _activity(taxonomy, code)
    return Card(
        stratum=stratum,
        label=ResultCode.CONFLICTS,
        reading=Reading(((code, words),), {regulator: "primary"}, firm=entry.name),
        name=entry.name,
        domain=entry.contacts[0] if entry.contacts else None,
        activity=words,
    )


def unlicensed(world: World, taxonomy: ActivityTaxonomy) -> list[Card]:
    """E4: every entity on VARA's unlicensed list."""
    return [
        _listed_card(entry, "E4", "VARA", "VA.EXCHANGE", taxonomy)
        for entry in world.listed
        if entry.source_id == "vara_unlicensed" and entry.name
    ]


def licensed_vasps(world: World, taxonomy: ActivityTaxonomy) -> list[Card]:
    """E5: licensed VASPs, with their official contact and an activity within the licence."""
    return [
        _card_for_firm(
            firm, "E5", ResultCode.CONSISTENT, firm.covers[0], taxonomy, domain=firm.domain
        )
        for firm in world.of("VARA")
        if firm.status == "active" and firm.domain and firm.covers
    ]


def ipa_holders(world: World, taxonomy: ActivityTaxonomy) -> list[Card]:
    """E6: In-Principle Approval holders offering services."""
    return [
        _card_for_firm(
            firm,
            "E6",
            ResultCode.CONFLICTS,
            "VA.CUSTODY",
            taxonomy,
            domain=firm.domain,
            outside="SCOPE-VARA-01",
        )
        for firm in world.of("VARA")
        if firm.status == "ipa"
    ]


def licensed_cma(world: World, taxonomy: ActivityTaxonomy) -> list[Card]:
    """E7: CMA firms, an activity within their category, and their official contact."""
    return [
        _card_for_firm(
            firm, "E7", ResultCode.CONSISTENT, firm.covers[0], taxonomy, domain=firm.domain
        )
        for firm in world.of("CMA")
        if firm.status == "active" and firm.domain and firm.covers
    ]


def category_five_fx(world: World, taxonomy: ActivityTaxonomy) -> list[Card]:
    """E8: CMA Category 5 firms offering FX or derivatives, which that category does not allow."""
    return [
        _card_for_firm(
            firm,
            "E8",
            ResultCode.CONFLICTS,
            _FX,
            taxonomy,
            domain=firm.domain,
            outside="SCOPE-CMA-01",
        )
        for firm in world.of("CMA")
        if firm.status == "active" and firm.domain and re.search(r"\b5\b", firm.category)
    ]


def cma_warnings(world: World, taxonomy: ActivityTaxonomy) -> list[Card]:
    """E9: every CMA warning."""
    return [
        _listed_card(entry, "E9", "CMA", _FX, taxonomy)
        for entry in world.listed
        if entry.source_id == "cma_warnings" and entry.name
    ]


def outside_phase_one(names: Sequence[str], taxonomy: ActivityTaxonomy) -> list[Card]:
    """E10: firms licensed only by the CBUAE. Their names are a list recorded by hand."""
    code = "LOAN.CREDIT"
    words = _activity(taxonomy, code)
    return [
        Card(
            stratum="E10",
            label=ResultCode.UNVERIFIED,
            reading=Reading(((code, words),), {"CBUAE": "primary"}, firm=name),
            name=name,
            activity=words,
        )
        for name in names
    ]


def near_misses(world: World, taxonomy: ActivityTaxonomy, *, seed: int) -> list[Card]:
    """E11: names two letters out of place from a licensed firm's.

    Whatever else they show, these must not pass as that firm, so the label follows the record.
    """
    rng = random.Random(seed)
    cards: list[Card] = []
    for firm in world.firms:
        # An altered DFSA name would not be masked, so those firms are left out.
        if firm.restricted or firm.status != "active" or not firm.covers:
            continue
        if len(firm.short_name) < 8:
            continue
        at = rng.randrange(2, len(firm.short_name) - 2)
        changed = (
            firm.short_name[:at]
            + firm.short_name[at + 1]
            + firm.short_name[at]
            + firm.short_name[at + 2 :]
        )
        if changed == firm.short_name:
            continue
        stem = "".join(ch for ch in changed.casefold() if ch.isalnum())
        cards.append(
            _card_for_firm(
                firm,
                "E11",
                None,
                firm.covers[0],
                taxonomy,
                domain=f"{stem}.example",
                name=changed,
            )
        )
    return cards


_Build = Callable[[World, ActivityTaxonomy], list[Card]]
STRATA: tuple[_Build, ...] = (
    impersonated,
    false_claims,
    unlicensed,
    licensed_vasps,
    ipa_holders,
    licensed_cma,
    category_five_fx,
    cma_warnings,
)


@dataclass(frozen=True)
class EntitySet:
    items: tuple[EvalItem, ...]
    #: Cards the policy labelled differently from their stratum, for a person to look at.
    disputed: tuple[str, ...]


def build_entity_items(
    world: World,
    stack: CrewStack,
    taxonomy: ActivityTaxonomy,
    *,
    today: date,
    seed: int,
    cbuae_names: Sequence[str] = (),
) -> EntitySet:
    cards = [card for build in STRATA for card in build(world, taxonomy)]
    cards += near_misses(world, taxonomy, seed=seed)
    cards += outside_phase_one(cbuae_names, taxonomy)
    items: list[EvalItem] = []
    disputed: list[str] = []
    for index, card in enumerate(cards, start=1):
        item_id = f"E-{index:04d}"
        decision = policy_label(stack, f"label-{item_id}", card.text(), card.reading, today=today)
        derived = decision.result
        if card.label is not None and derived is not card.label:
            expected = card.label.value
            disputed.append(f"{item_id} {card.stratum}: {expected} expected, not {derived.value}")
            continue
        items.append(
            EvalItem(
                item_id=item_id,
                level=Level.ENTITY,
                text=card.text(),
                gold_label=derived,
                gold_reasons=reasons_of(decision),
                gold_relevant=tuple(sorted(card.reading.relevant)),
                stratum=card.stratum,
                origin="entity_card",
                generator=GENERATOR,
                restricted=card.restricted,
            )
        )
    return EntitySet(tuple(items), tuple(disputed))
