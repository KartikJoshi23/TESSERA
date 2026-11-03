# Hand-recorded data

Everything in this folder except this README and `templates/` is **git-ignored and must stay
on this machine**. The commit guard blocks it even with `git add -f`.

Copy a template from `templates/`, fill it in with a spreadsheet editor or a text editor, and save
it as UTF-8 CSV. Then run `tessera-ingest` (see the root README). Lists inside a cell are
separated by semicolons (`;`). Dates use `YYYY-MM-DD`. `recorded_by` is your initials.

**DFSA files are different.** Save them under `data/restricted/dfsa/`, never in this folder.
Record only the fields below, in our own words where a label is needed. Never copy DFSA text,
never take screenshots, and never record a link other than the DFSA homepage.

## `cma_warnings.csv` (from the CMA Warnings page)

| Field | Meaning |
|---|---|
| `record_id` | Your ID, for example `CMA-W-0001` |
| `entity_name` | The warned entity's name as shown |
| `warning_date` | The date shown on the warning |
| `domains`, `phones`, `emails` | Contact details named in the warning (`;`-separated) |
| `notes` | Short notes in your own words (optional) |
| `page_url` | The warning's page link (CMA deep links are allowed) |

## `vara_register.csv` (from the VARA Public Register)

| Field | Meaning |
|---|---|
| `record_id` | Your ID, for example `VARA-R-0001` |
| `entity_name` | The entity's name as shown |
| `status` | `LICENSED`, `IPA` (In-Principle Approval) or `OTHER`. Keep IPA separate: it is not a licence |
| `licence_ref` | The reference shown on the entry, if any |
| `activities` | Licensed activities as listed (`;`-separated) |
| `website` | The website shown on the entry, if any |
| `aliases` | Other names shown, such as a trading name (`;`-separated) |
| `page_url` | The entry's page link |

## `vara_unlicensed.csv` (from VARA's Unlicensed VASPs list)

| Field | Meaning |
|---|---|
| `record_id` | Your ID, for example `VARA-U-0001` |
| `entity_name` | The name as listed |
| `domains` | Websites listed for it (`;`-separated) |
| `date_listed` | The date shown |
| `page_url` | The list's page link |

## `dfsa_register_facts.csv` → save in `data/restricted/dfsa/` (evaluation firms only)

| Field | Meaning |
|---|---|
| `record_id` | Your ID, for example `D-R-001` |
| `firm_name` | The firm's name as shown |
| `frn` | The DFSA Firm Reference Number |
| `status` | `authorised`, `withdrawn`, `suspended` or `other` |
| `permitted_services` | The financial services listed (`;`-separated) |
| `address` | The address shown |
| `website`, `phone` | If the register shows them |
| `email_domains` | Official email domains, if shown (`;`-separated) |
| `aliases` | Other names shown (`;`-separated) |

## `dfsa_alert_facts.csv` → save in `data/restricted/dfsa/` (2026 alerts)

| Field | Meaning |
|---|---|
| `record_id` | Your ID, for example `D-A-001` |
| `alert_date` | The date on the alert |
| `category` | Our label: `impersonated_authorised_firm`, `false_claim_of_authorisation`, `regulator_impersonation`, `unauthorised_firm` or `other` |
| `firm_named` | The firm the alert names (for impersonation alerts, the *legitimate* firm) |
| `frn_named` | A reference number the alert mentions, if any |
| `contact_points_named` | Domains, emails or phones the alert names as used by the impersonator (`;`-separated) |
| `legitimate_contacts_stated` | Official contacts the alert states, for example an official email domain (`;`-separated) |
