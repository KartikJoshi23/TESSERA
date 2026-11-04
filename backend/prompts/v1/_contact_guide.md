## Contact statuses

Use the first that applies:
- `alert_listed`: `reverse_contact_lookup` shows it on an alert, warning or unlicensed list as a contact used by someone else (`matched_on` is not "contact_stated_official").
- `matches_official`: same registrable domain, email domain or phone as the official record, or the regulator itself states it as official (`matched_on` is "contact_stated_official").
- `lookalike_of_official`: `compare_domain` says `lookalike` is true.
- `not_on_record`: you compared it with an official record, and it neither matches nor imitates it.
- `not_comparable`: no register entry matched, so there is nothing to compare it with, or it cannot be compared.

Put the entry's evidence ID in `official_evidence_id`, and every evidence ID you relied on in `evidence_ids`.

## How to reason

- Use the tools' results. Do not judge a domain by how it looks to you.
- A firm can have a second domain. A different domain that does not imitate the official one is `not_on_record`, not a conflict.
- A number's country or type is not evidence of anything.
