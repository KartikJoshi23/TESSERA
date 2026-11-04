## Relevance statuses

- `primary`: the activity and the best zone signal point to this regulator.
- `possible`: it could apply, for example because a zone signal is unverified or a targeting rule may reach the offer.
- `not_indicated`: nothing points to it.
- `excluded`: a rule card rules it out, on grounds stronger than the offer's own claim.

## How to reason

- An activity is what the offer sells. Instructions for paying for it, such as a bank transfer or a deposit, are not an activity.
- Be cautious. Missing a relevant regulator can cause false reassurance, so when in doubt use `possible`.
- Several regulators can be relevant at once (JUR-08).
- A zone claimed in the offer is only a claim. A claimed DIFC address makes the DFSA relevant, but on its own it does not exclude VARA or the CMA.
- Targeting UAE clients can add the CMA (JUR-04). It never removes a regulator.
- "SCA" or "Securities and Commodities Authority" means the CMA (JUR-09).
- Regulators outside this phase's coverage (CBUAE and FSRA) must still get an honest status. The system reports them as not checked.

## Starting matrix (activity by zone)

| Zone | Virtual assets | Securities, derivatives, FX, advice, funds | Banking, lending, payments |
|---|---|---|---|
| DIFC | DFSA | DFSA | DFSA |
| ADGM | FSRA | FSRA | FSRA |
| Dubai outside the DIFC | VARA; CMA possible | CMA | CBUAE |
| Other emirates | CMA | CMA | CBUAE |
| Outside the UAE, targeting the UAE | CMA; VARA possible | CMA | CBUAE |
| Unknown | VARA, CMA, DFSA, FSRA possible | CMA, DFSA, FSRA possible | CBUAE, DFSA, FSRA possible |
