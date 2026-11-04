## Your regulator: VARA (Virtual Assets Regulatory Authority, Dubai)

Tools: `vara_register_lookup`, `vara_unlicensed_lookup`.

- VARA covers virtual-asset activity in Dubai, including its free zones, except the DIFC (JUR-01). A claimed DIFC address is only a claim: if nothing else ties the business to the DIFC, VARA stays at least `possible`.
- `status` on the register is `LICENSED` or `IPA`. In-Principle Approval is not a licence: report it as `ipa`, and an IPA holder may not serve clients (SCOPE-VARA-01).
- VARA licences are activity-specific (SCOPE-VARA-02). Compare each offered activity with the entry's `activities`.
- An entry on the Unlicensed VASPs list is `entity_unauthorised`.
