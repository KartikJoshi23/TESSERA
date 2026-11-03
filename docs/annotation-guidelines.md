# Annotation guidelines (v0)

Gold labels decide how every system is scored, so they must be consistent. This version covers the
three outcome labels. Part 6 adds the jurisdiction set, key facts and difficulty factors.

## 1. The three labels

| Label | Use when |
|---|---|
| **Consistent with the official record** | The claimed firm is on the register of a relevant regulator; its licence is active and covers the offered activity; **every** deciding contact detail (website or domain, email domain, phone, IBAN, wallet) matches the official record; and no checked list names the offer's details or the firm as unauthorised |
| **Conflicts with the official record** | At least one hard conflict holds (HC1–HC6 in `policies/decision_policy.yaml`). For example: a contact detail is on an alert or warning list; the claimed licence or reference number is contradicted by the register; the licence does not cover the activity; a domain imitates the official one; the payment goes to a different name |
| **Could not verify** | Anything else. For example: the firm is not found and the offer makes no checkable claim; a relevant regulator is not covered yet (CBUAE or FSRA in Phase 1); a contact detail is neither on record nor contradicted |

## 2. Procedure for each item

1. Read the item, and **ignore its tone.** Urgency or polish is never evidence.
2. List the claims: firm name, regulator, licence or reference number, activity, address.
3. List the deciding contact details. Addresses and social handles never decide a label.
4. Check the records you were given for this item.
5. Apply the hard conflicts first. If any holds, the label is "Conflicts".
6. Otherwise, check every condition for "Consistent" (K1–K7). If any fails, the label is
   "Could not verify".
7. Write one sentence of rationale citing the record IDs you used.

## 3. Traps

- **A name match is not enough.** Impersonators copy names, addresses and reference numbers.
- **An impersonation alert names the real firm as the victim.** That is not a conflict by itself;
  the contact details decide.
- **Absence is not proof.** A firm missing from a list is "Could not verify", unless the offer
  claims an authorisation that the register contradicts.
- **In-Principle Approval (VARA) is not a licence.**
- **A CMA Category 5 licence never covers FX or derivatives trading.**

## 4. Disagreements and quality

- **Two annotators** label independently, without seeing the intended label. Disagreements are
  settled by discussion, and Cohen's κ is reported, with a target of ≥ 0.8.
- **With only one annotator,** that person labels everything twice, at least two weeks apart, and
  we report agreement between the two passes. A free model may flag items for a second look but
  never sets labels.
- **Unclear items** are fixed or dropped, and every drop is logged with a reason.

## 5. Worked example (fictional)

> SYNTHETIC: "Lumen Crest Capital (DIFC) Limited, DFSA FRN F000000 … open your account at
> lumencrest-capital.example …"

The records show three things: the firm is authorised; its official website is
`lumencrest.example`; and an alert names `lumencrest-capital.example`. The label is
**Conflicts with the official record**, under HC1 (the domain is alert-listed) and HC5 (the
domain imitates the official one). The rationale cites the register and alert record IDs.
