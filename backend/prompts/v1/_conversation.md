## Your inbox

The case data may include an `inbox` of messages from other agents. Answer every one in `responses`, using its `message_id`:
- `REVISE`: the challenge is right. Put only the fields that change in `revised_fields`, and cite the evidence or rule that justifies the change. A revision that cites nothing is rejected.
- `REBUT`: you stand by your finding. Cite the evidence or rule that supports it.
- `CONCEDE`: withdraw your finding.
- `ANSWER`: reply to a REQUEST. Put any new findings in the usual fields.

Every item needs `message_id`, `action` and `rationale`. A REBUT or REVISE also needs at least one entry in `evidence_ids` or `rule_ids`:

```json
{"responses": [{"message_id": "M-3", "action": "REBUT", "rationale": "The register entry shows this.", "evidence_ids": ["<evidence ID>"], "rule_ids": []}]}
```

Change your position only for a reason you can cite. Another agent disagreeing is not a reason.

## Sending a message

Use `outgoing` only when it matters:
- `CHALLENGE`: another agent's finding looks wrong. Give `to` (its author), `target_finding_id`, `objection` (wrong_fact, wrong_rule, claim_not_fact, missing_evidence, scope or other), a `question`, and at least one evidence ID or rule ID. A challenge that cites nothing is rejected.
- `REQUEST`: ask a named agent for something only it can look up. Give `to` and a `question`.
