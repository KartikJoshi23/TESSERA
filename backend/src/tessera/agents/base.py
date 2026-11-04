"""What every agent shares: its environment, its turn, and its handling of conversation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from tessera.agents.schemas import OutgoingItem, ResponseItem
from tessera.agents.toolbelt import ToolBelt
from tessera.blackboard.board import Blackboard
from tessera.blackboard.views import SHARED, ViewOptions
from tessera.governance.policies import DecisionPolicy
from tessera.knowledge import ActivityTaxonomy, RuleCard
from tessera.llm.prompts import PromptLibrary
from tessera.llm.runner import AgentRunner, AgentSpec, TurnResult
from tessera.protocol.claims import ASSERTION_ADAPTER
from tessera.protocol.common import AgentId, clip_words
from tessera.protocol.evidence import EvidenceKind, EvidenceRecord, mint_evidence
from tessera.protocol.messages import MessageDraft, Performative, ProtocolViolation
from tessera.tools import ToolContext, get_rule_card
from tessera.tools.lookups import restricted_facts_for

TaskKind = Literal["initial", "respond", "challenge_round", "synthesis", "verify"]


@dataclass(frozen=True)
class Task:
    kind: TaskKind
    round: int = 0
    options: ViewOptions = SHARED


@dataclass
class AgentEnv:
    """Everything an agent turn needs. One per case."""

    board: Blackboard
    ctx: ToolContext
    belt: ToolBelt
    runner: AgentRunner
    prompts: PromptLibrary
    rule_cards: dict[str, RuleCard]
    taxonomy: ActivityTaxonomy
    decision: DecisionPolicy
    #: Regulators whose records can be consulted in this phase and mode.
    covered_regulators: frozenset[str]

    def facts_for(self, record: EvidenceRecord) -> dict[str, Any]:
        """Facts behind restricted evidence, resolved locally for one outgoing (masked) prompt."""
        return restricted_facts_for(self.ctx, record)

    def rule_evidence(self, rule_ids: Any) -> list[str]:
        """Mint rule-card evidence for the rules an agent cited. Unknown rule IDs mint nothing."""
        evidence: list[str] = []
        for rule_id in rule_ids:
            if rule_id in self.rule_cards:
                result = get_rule_card(self.ctx, rule_id=rule_id)
                self.board.add_evidence(result.evidence)
                evidence += [record.evidence_id for record in result.evidence]
        return evidence

    def quote_evidence(self, quote: str) -> list[str]:
        """Evidence that a quote really is in the offer. A quote that is not there mints nothing."""
        assert self.board.case is not None
        needle = " ".join(quote.split()).casefold()
        if not needle or needle not in " ".join(self.board.case.offer_text.split()).casefold():
            return []
        key = hashlib.sha256(needle.encode("utf-8")).hexdigest()[:12]
        record = mint_evidence(
            case_id=self.board.case_id,
            source_id="offer",
            kind=EvidenceKind.DERIVED_ANALYSIS,
            locator=f"offer_quote:{key}",
            fields={"quote": quote},
            minted_by="offer_quote",
        )
        self.board.add_evidence([record])
        return [record.evidence_id]

    def unknown_rules(self, rule_ids: Any) -> list[str]:
        return [
            f"unknown rule ID {rule_id!r}"
            for rule_id in rule_ids
            if rule_id and rule_id not in self.rule_cards
        ]


def render_user_content(board: Blackboard, case_data: dict[str, Any], task_text: str) -> str:
    """The per-case message. Offer text stays inside its own tag, marked as untrusted data."""
    assert board.case is not None
    offer = board.case.offer_text.replace("</offer_text>", "")
    data = json.dumps(case_data, ensure_ascii=False, indent=1, default=str)
    return (
        f"<offer_text>\n{offer}\n</offer_text>\n\n"
        f"<case_data>\n{data}\n</case_data>\n\n"
        f"<task>\n{task_text}\n</task>"
    )


def send_outgoing(env: AgentEnv, sender: AgentId, item: OutgoingItem, round: int) -> None:
    """Send a model-proposed message. A message that breaks a rule is logged and dropped."""
    body: dict[str, Any] = {"question": item.question}
    if item.objection:
        body["objection"] = item.objection
    env.board.try_send(
        MessageDraft(
            sender=sender,
            recipients=(item.to,),
            performative=Performative(item.performative),
            round=round,
            refs=(item.target_finding_id,) if item.target_finding_id else (),
            evidence_ids=(*item.evidence_ids, *env.rule_evidence(item.rule_ids)),
            rule_ids=tuple(item.rule_ids),
            body=body,
            rationale=clip_words(item.rationale),
        )
    )


class Agent:
    """One crew member. Subclasses define the prompt, the view and how output is applied."""

    agent_id: AgentId
    output_model: type[BaseModel]
    tool_names: tuple[str, ...] = ()

    def prompt_parts(self, env: AgentEnv, task: Task) -> tuple[str, ...]:
        raise NotImplementedError

    def case_data(self, env: AgentEnv, task: Task) -> dict[str, Any]:
        raise NotImplementedError

    def task_text(self, task: Task) -> str:
        raise NotImplementedError

    def check_output(self, env: AgentEnv, task: Task, output: Any) -> list[str]:
        """Problems a model should get a chance to repair, beyond the schema."""
        return []

    def apply(self, env: AgentEnv, task: Task, output: Any) -> list[str]:
        """Write the output to the blackboard. Returns the IDs of findings it posted."""
        raise NotImplementedError

    def spec(self, env: AgentEnv, task: Task) -> AgentSpec:
        return AgentSpec(
            agent_id=self.agent_id,
            system=env.prompts.build(*self.prompt_parts(env, task)),
            output_model=self.output_model,
            tool_names=self.tool_names,
            check_output=lambda output: self.check_output(env, task, output),
        )

    async def activate(self, env: AgentEnv, task: Task) -> TurnResult:
        """Run one turn, and announce any new findings with an INFORM."""
        content = render_user_content(env.board, self.case_data(env, task), self.task_text(task))
        result = await env.runner.run(self.spec(env, task), content, round=task.round)
        if result.output is None:
            return result
        posted = self.apply(env, task, result.output)
        if posted:
            env.board.try_send(
                MessageDraft(
                    sender=self.agent_id,
                    recipients=(AgentId.ORC,),
                    performative=Performative.INFORM,
                    round=task.round,
                    refs=tuple(posted),
                )
            )
        return result

    # ------------------------------------------------------------------ conversation

    def handle_conversation(self, env: AgentEnv, task: Task, output: Any) -> None:
        for item in output.responses:
            self._respond(env, task, item)
        for item in output.outgoing:
            send_outgoing(env, self.agent_id, item, task.round)

    def _respond(self, env: AgentEnv, task: Task, item: ResponseItem) -> None:
        board = env.board
        original = board.message(item.message_id)
        if original is None or self.agent_id not in original.recipients:
            board.log_rejection("bad_reply", f"no such message {item.message_id}", self.agent_id)
            return
        evidence = [*item.evidence_ids, *env.rule_evidence(item.rule_ids)]
        rationale = clip_words(item.rationale)
        try:
            if item.action == "REVISE":
                self._revise(env, task, item, evidence, rationale)
                return
            performative = {
                "REBUT": Performative.REBUT,
                "CONCEDE": Performative.CONCEDE,
                "ANSWER": Performative.INFORM,
            }[item.action]
            board.send(
                MessageDraft(
                    sender=self.agent_id,
                    recipients=(original.sender,),
                    performative=performative,
                    round=task.round,
                    refs=original.refs,
                    evidence_ids=tuple(evidence),
                    rule_ids=tuple(item.rule_ids),
                    rationale=rationale,
                    in_reply_to=item.message_id,
                )
            )
        except ProtocolViolation:
            pass  # the blackboard has logged the rejection

    def _revise(
        self, env: AgentEnv, task: Task, item: ResponseItem, evidence: list[str], rationale: str
    ) -> None:
        board = env.board
        original = board.message(item.message_id)
        target = board.findings.get(original.refs[0]) if original and original.refs else None
        if target is None:
            board.log_rejection("bad_revision", "a revision answers a challenge", self.agent_id)
            return
        merged = {**target.assertion.model_dump(mode="json"), **(item.revised_fields or {})}
        try:
            assertion = ASSERTION_ADAPTER.validate_python(merged)
        except ValidationError:
            board.log_rejection("bad_revision", "the revised fields are invalid", self.agent_id)
            return
        board.revise_finding(
            reply_to=item.message_id,
            sender=self.agent_id,
            assertion=assertion,
            evidence_ids=evidence,
            rule_ids=item.rule_ids,
            rationale=rationale,
            round=task.round,
        )

    def rule_card_text(self, env: AgentEnv, *prefixes: str) -> list[RuleCard]:
        return [card for card in env.rule_cards.values() if card.id.startswith(prefixes)]
